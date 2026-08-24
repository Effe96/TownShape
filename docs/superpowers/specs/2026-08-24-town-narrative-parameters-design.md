# Town Narrative Parameters — Design

## Context

Sub-projects A (Town Shaper), B (Town DB), and C (Town Relationships) are
done and merged — see their specs under `docs/superpowers/specs/`. The
originally-planned fourth sub-project ("D. Agent-driven daily
simulation") has been superseded by a broader vision, captured in
`../../../Agent_Control_Doc.md` (one level above this repo): a
narrative-based tool for D&D campaigns with three capabilities:

1. **Narrative-to-parameters generation** (this spec) — read freeform
   narrative input (a vague hint, or a full campaign-wiki page) and turn
   it into concrete generation parameters for A/B, asking clarifying
   questions and giving recommendations when the input doesn't resolve
   cleanly.
2. **Safe-mode simulation** — the town evolves over time on its own
   (deaths, disease, economic cascades), following internally-consistent
   rules. Closest to the original "D" concept. Not started.
3. **Creative-mode narrative editing** — the author asserts a story fact
   mid-session and the agent retroactively backfills consistent world
   state. Not started.

Capability 1 is itself too large for one spec — it needs new spatial
features (rivers/ports), a new domain (magic prevalence), and a new
domain (social unrest driven by aggression/stress) on top of the basic
parameter plumbing. It's split into four sub-slices, built in order:

- **1a. Parameter plumbing (this spec)** — a `TownParameters` schema
  covering knobs that already exist or need only a constant→parameter
  promotion in existing A code: population, seed, physical town size,
  building density/sparseness, richness. Plus the narrative-mapping
  workflow for turning story language into these values.
- **1b. Water & port features** — rivers/coastline as real geometry in
  A's spatial model, docks/port buildings. Not started.
- **1c. Magic prevalence** — new building types, goods, and/or resident
  traits in A/B representing magic's presence. Not started.
- **1d. Social unrest (aggression & stress)** — a new event type in B's
  year-of-history generation: skirmishes/incidents between social
  classes and/or city guard. Not started.

This spec covers **1a only**.

**Who is "the agent"?** For now, Claude Code itself, driving generation
conversationally in a session — there is no embedded LLM call inside this
package. The parameter schema and entry point are designed to be
agent-neutral (a plain Python function boundary + a markdown reference
doc), so a different kind of agent could drive the same interface later;
only the Claude-Code-specific invocation wrapper (the skill file) would
need re-doing for a different agent.

### Necessary departure from A/B's "don't touch merged work" norm

Unlike C (which was purely additive and touched nothing in A or B), 1a
**modifies** A's `town_shaper/generate.py`, `buildings.py`, and
`assignment.py` to accept new optional parameters, and adds one new table
via B's `town_db/schema.py`. This is not the "improve old code because we
found better data" situation the project has twice declined to reopen —
it's new capability that structurally requires touching existing
modules. Every new parameter defaults to the value that reproduces
today's exact behavior, so A's and B's existing test suites pass
unchanged with no argument-list updates required at call sites that
don't pass the new parameters.

## Scope

New top-level package `town_narrative/` (parallel to `town_shaper/`,
`town_db/`, `town_relationships/`), holding the parameter schema and the
orchestrating entry point:

```
town_narrative.parameters.TownParameters   # the schema
town_narrative.generate.generate_town_from_parameters(
    params: TownParameters, db_path: str
) -> None
```

`generate_town_from_parameters` composes `town_shaper.generate.generate_town`
and `town_db.generate.generate_town_database` (both extended with new
optional parameters, see below), then inserts one row into the new
`generation_parameters` table recording what was chosen.

## Data Model

### `TownParameters` (Python dataclass, `town_narrative/parameters.py`)

```python
@dataclass
class TownParameters:
    seed: Any
    target_population: int
    area_per_resident_multiplier: float = 1.0
    density_multiplier: float = 1.0
    rich_proportion: float = 0.05
```

Validated in `__post_init__` (raises `ValueError`, matching the existing
`compute_anchor_counts` precedent in `town_shaper/anchors.py`):
- `target_population > 0`
- `area_per_resident_multiplier > 0`
- `density_multiplier > 0`
- `0.0 <= rich_proportion <= 1.0`

**Field meaning:**
- `area_per_resident_multiplier` — scales the town's total physical
  footprint independent of population (today's fixed
  `AREA_PER_RESIDENT = 150.0` in `town_shaper/generate.py` becomes
  `AREA_PER_RESIDENT * area_per_resident_multiplier`). This is "how
  large the city is," physically, as distinct from headcount.
- `density_multiplier` — scales how tightly buildings are packed within
  whatever area exists, independent of size. At `1.0`, behavior is
  unchanged from today. Values `< 1.0` spread buildings out (fewer per
  unit area, more spacing between them); `> 1.0` packs them tighter. A
  low-density, small-area, high-population combination reduces total
  housing capacity below `target_population`; residents beyond capacity
  are omitted from the generated town entirely
  (`town_shaper/assignment.py`'s `_find_home_with_capacity` returns
  `None` and the resident is never appended to the `residents` list —
  not marked "unhoused" anywhere in the data, simply absent) and 1a does
  not add new validation against it. Future sub-slices should treat the
  resulting capacity shortfall as something to surface explicitly (e.g.
  a count or warning), not assume it is recorded anywhere today.
- `rich_proportion` — promotes the currently-hardcoded
  `SES_PROPORTIONS[SES.RICH] = 0.05` constant in
  `town_shaper/assignment.py` to a caller-supplied value. "Poor" is
  always `1.0 - rich_proportion`; the two-tier SES model itself is
  unchanged (a finer wealth spectrum is out of scope for 1a).

### `generation_parameters` table (new, `town_db/schema.py`)

```sql
CREATE TABLE generation_parameters (
    seed TEXT NOT NULL,
    target_population INTEGER NOT NULL,
    area_per_resident_multiplier REAL NOT NULL,
    density_multiplier REAL NOT NULL,
    rich_proportion REAL NOT NULL
);
```

Exactly one row per database, inserted by
`generate_town_from_parameters`. `seed` is stored as `str(params.seed)`
(seeds are already treated as opaque, `repr`-able values by
`town_shaper/seeding.py derive_seed`; nothing reads this column back into
a live seed, it's a record for future sub-slices/pieces — e.g. 1c/1d and
the safe-mode simulation piece reading "what was this town generated
with"). No foreign keys — this table describes the database as a whole,
not a specific entity in it.

## Behavior Changes to Existing Modules

All new parameters are optional with defaults that reproduce current
behavior exactly — existing call sites and tests in `town_shaper`'s and
`town_db`'s own test suites require no changes.

**`town_shaper/generate.py`:**
```python
def compute_town_bounds(target_population: int, area_per_resident_multiplier: float = 1.0) -> Tuple[...]:
    area = target_population * AREA_PER_RESIDENT * area_per_resident_multiplier
    ...

def generate_town(
    seed, target_population: int,
    area_per_resident_multiplier: float = 1.0,
    density_multiplier: float = 1.0,
    rich_proportion: float = 0.05,
) -> Town:
    bounds = compute_town_bounds(target_population, area_per_resident_multiplier)
    ...
    buildings = fill_district_buildings(
        district, seed, next_building_id,
        target_population=target_population, density_multiplier=density_multiplier,
    )
    ...
    residents = assign_residents(seed, households, districts, rich_proportion=rich_proportion)
    ...
```

**`town_shaper/buildings.py`** — `fill_district_buildings` gains
`density_multiplier: float = 1.0`:
```python
target_count = max(1, round(area * density * density_multiplier))
spacing = MIN_BUILDING_SPACING[district.zone_type] / density_multiplier
```

**`town_shaper/assignment.py`** — `assign_residents` gains
`rich_proportion: float = 0.05`, threaded into `_draw_household_ses`:
```python
def _draw_household_ses(rng, rich_proportion: float) -> SES:
    return SES.RICH if rng.random() < rich_proportion else SES.POOR
```
The module-level `SES_PROPORTIONS` constant is removed in favor of the
threaded parameter (nothing else in `town_shaper` reads it — confirmed
via the earlier grep of `assignment.py`/`buildings.py`).

**`town_db/generate.py`** — `generate_town_database` gains the same
three parameters, passed straight through to `generate_town`; no other
change (B's own generation logic doesn't depend on physical size,
density, or richness beyond what already flows through `resident_rows`).

## Narrative-Mapping Workflow

Two artifacts, one content source:

- **`docs/narrative-town-parameters.md`** — agent-neutral reference: each
  `TownParameters` field's meaning, default, and a qualitative-language
  → value table for mapping narrative description to numbers. Starter
  anchors (open to tuning like B's constants):

  | Narrative language | Field | Suggested value |
  |---|---|---|
  | "sprawling", "spread out", physically large | `area_per_resident_multiplier` | 1.5 – 2.5 |
  | "compact", "walled", small footprint | `area_per_resident_multiplier` | 0.4 – 0.7 |
  | (no size cue) | `area_per_resident_multiplier` | 1.0 (default) |
  | "cramped", "crowded", "packed" | `density_multiplier` | 1.3 – 2.0 |
  | "sparse", "spread thin", "a village in a large town" | `density_multiplier` | 0.3 – 0.6 |
  | (no density cue) | `density_multiplier` | 1.0 (default) |
  | "wealthy", "prosperous", "opulent" | `rich_proportion` | 0.15 – 0.3 |
  | "poor", "impoverished", "destitute" | `rich_proportion` | 0.01 – 0.03 |
  | (no wealth cue) | `rich_proportion` | 0.05 (default) |

  A firm rule stated up front: when narrative input doesn't clearly
  resolve to a value or range, the agent asks the user directly, states
  its recommended default and why, rather than silently guessing.

- **`.claude/skills/generate-town-from-narrative/SKILL.md`** — the
  Claude-Code-specific invocation wrapper (so this is reachable as
  `/generate-town-from-narrative`). Points to the doc above for the
  mapping table, and additionally documents the *procedure*: read the
  narrative input (inline text or a file path, per the Agent Control
  Doc's "vague broad indications" vs. "detailed narrative input, e.g. a
  campaign-wiki page" distinction), propose a filled-in
  `TownParameters`, confirm with the user before generating, then call
  `generate_town_from_parameters`.

## Error Handling & Edge Cases

- Invalid parameters (`target_population <= 0`,
  `area_per_resident_multiplier <= 0`, `density_multiplier <= 0`,
  `rich_proportion` outside `[0.0, 1.0]`) raise `ValueError` from
  `TownParameters.__post_init__`, before any generation work starts.
- Extreme `density_multiplier`/`area_per_resident_multiplier` combinations
  that leave many residents unhoused are not an error (see Data Model
  above) — this is an intentional, existing tolerance in A, not new
  behavior introduced by 1a.
- `generate_town_from_parameters` shares the same "safe to call once
  per `db_path`" precondition already documented on
  `generate_town_database` and `derive_relationships` — not re-litigated
  here.

## Testing Strategy

- **`TownParameters` validation**: each invalid-field case raises
  `ValueError`; a fully-valid set of fields constructs successfully;
  defaults match today's hardcoded constants exactly
  (`area_per_resident_multiplier=1.0`, `density_multiplier=1.0`,
  `rich_proportion=0.05`).
- **Backward compatibility**: calling `generate_town`/
  `generate_town_database`/`fill_district_buildings`/`assign_residents`
  with no new arguments produces byte-identical output to before this
  change, for a fixed seed (regression guard against the constant→
  parameter refactor changing behavior at the default).
- **Size independent of population**: same `target_population`, two
  different `area_per_resident_multiplier` values → different `bounds`
  from `compute_town_bounds`, same anchor/household counts.
- **Density independent of size**: same `target_population` and
  `area_per_resident_multiplier`, two different `density_multiplier`
  values → different building counts per district from
  `fill_district_buildings`.
- **Richness threading**: a `rich_proportion` far from the default
  (e.g. `0.9`) run through `assign_residents` with a fixed seed produces
  a majority-rich household population (statistical assertion over a
  reasonably large household count, not an exact count — matches B's own
  existing style for probabilistic generation tests).
- **`generation_parameters` round-trip**: after
  `generate_town_from_parameters`, the table has exactly one row whose
  values match the `TownParameters` that were passed in.
- **End-to-end**: `generate_town_from_parameters` on a small population
  produces a valid, queryable database (schema present, `PRAGMA
  foreign_key_check` clean) — mirrors B's and C's own end-to-end test
  shape.

## Out of Scope for This Spec

- Rivers/ports, magic prevalence, aggression/stress (1b/1c/1d — separate
  specs).
- Any embedded LLM call — the narrative-reading "intelligence" is Claude
  Code itself, in-session, per the Agent Control Doc's current framing.
- Editing an *already-generated* town from narrative input (creative
  mode, piece 3 of the Agent Control Doc) — 1a only covers generating a
  new town from scratch.
- The safe-mode simulation (piece 2) and any of its interaction with
  these parameters (e.g. `rich_proportion` or a future `stress` value
  modulating daily event rates) — noted as a likely future consumer of
  `generation_parameters`, not built here.
- A finer-grained wealth spectrum beyond the existing two-tier
  rich/poor SES model.
