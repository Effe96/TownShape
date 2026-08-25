# Town Magic Prevalence — Design

## Context

This is sub-slice **1c** of capability 1 ("narrative-to-parameters
generation") from `../../../Agent_Control_Doc.md` — see
`2026-08-24-town-narrative-parameters-design.md` (1a) for the full
capability breakdown. 1a and 1b are done and merged: 1a established the
`town_narrative.parameters.TownParameters` dataclass and the
`generate_town_from_parameters(params, db_path)` orchestrator; 1b added
rivers/coastline/port geometry. This slice extends both further.

1c adds a `magic_prevalence` parameter representing how prevalent magic is
in the town, expressed across three previously-unconnected extensibility
points already established by A/B: a new building type (`town_shaper`'s
per-zone building-type dicts, following the exact precedent of 1b's
`ZoneType.PORT`), new goods (`town_db`'s SV-weighted goods/purchases
system), and a new per-resident demographic trait (`town_db`'s
`residents` table, following the exact precedent of the existing
`is_noble` tagging pass).

## Scope

Changes to `town_shaper/buildings.py`, `town_shaper/generate.py`,
`town_db/goods.py`, `town_db/purchases.py`, `town_db/households.py`,
`town_db/generate.py`, `town_db/schema.py`, `town_narrative/parameters.py`,
`town_narrative/generate.py`, `docs/narrative-town-parameters.md`, and
`.claude/skills/generate-town-from-narrative/SKILL.md`. No new package, no
new `ZoneType`, no new spatial-placement logic (unlike 1b's `PORT`,
`arcane_shop` needs no special anchor placement — it's a plain addition to
`MERCHANT`'s existing building-type weights).

Out of scope: any gameplay/simulation logic reading `has_magical_talent`
(deferred to a future capability — safe-mode simulation or creative-mode
editing, per the Agent Control Doc); enforcing a correlation between
`has_magical_talent` and the `mage`/`apprentice` occupations; aggression/
stress (1d, a separate spec).

## Data Model

### `TownParameters` addition (`town_narrative/parameters.py`)

```python
magic_prevalence: float = 0.0
```

Validated in `__post_init__`: `0.0 <= magic_prevalence <= 1.0`, raising
`ValueError` otherwise — same pattern as the existing `rich_proportion`
check.

### `generation_parameters` table gains

```sql
magic_prevalence REAL NOT NULL
```

### `residents` table gains

```sql
has_magical_talent INTEGER NOT NULL DEFAULT 0
```

Boolean as `0`/`1`, matching the existing `is_noble` convention.

### `GOODS_CATALOG` gains three entries (`town_db/goods.py`)

No historical reference document backs these (unlike the
demographics-PDF-grounded existing goods) — flagged as reasonable starting
values, open to tuning like every other empirically-set constant in this
project:

```python
{"name": "healing potion", "category": "magic", "typical_price": 4.0, "sv": 500},
{"name": "spell scroll", "category": "magic", "typical_price": 8.0, "sv": 300},
{"name": "arcane reagents", "category": "magic", "typical_price": 1.5, "sv": 700},
```

## Building Type + Occupations (`town_shaper`)

`BUILDING_TYPES_BY_ZONE[ZoneType.MERCHANT]` stays exactly as-is in the
module-level dict (`{"shop": 0.5, "tavern": 0.2, "market_stall": 0.3}`) —
`arcane_shop` is **not** a static entry there, since its weight must scale
continuously with `magic_prevalence`, not sit at a fixed value.

```python
ARCANE_SHOP_WEIGHT_SCALE = 0.5
```

`fill_district_buildings` gains `magic_prevalence: float = 0.0`. When the
district's `zone_type == ZoneType.MERCHANT` and `magic_prevalence > 0`, the
function adds `"arcane_shop": magic_prevalence * ARCANE_SHOP_WEIGHT_SCALE`
to a **copy** of the zone's type-weights dict before the weighted
`rng.choices(...)` call that picks each building's type — mirroring the
existing pattern already used for `university`'s conditional inclusion in
`CIVIC` (copy the dict, conditionally mutate, never touch the module-level
constant). At `magic_prevalence = 1.0`, an arcane shop is as common as a
general `shop` (weight `0.5` vs. `0.5`); at `magic_prevalence = 0.1`,
weight `0.05` — rare relative to its neighbors. At the default
`magic_prevalence = 0.0`, `arcane_shop` never appears — exact backward
compatibility, no test or call site changes required.

```python
JOB_VACANCIES_BY_BUILDING_TYPE["arcane_shop"] = [("mage", 1), ("apprentice", 2)]
```

A static entry like every other building type, mirroring `shop`'s
`shopkeep` + `shop_staff` shape (one senior role, more junior staff). No
`BUILDING_HOME_CAPACITY` entry — not housing, same treatment as `shop`.

`generate_town` gains `magic_prevalence: float = 0.0`, threaded straight
into the existing `fill_district_buildings(...)` call.

## Goods + Purchases (`town_db`)

Today, `generate_purchases` draws a good (SV-weighted, population-wide)
and a shop (uniformly from all `shop_building_ids`) **independently** — no
good is scoped to a specific shop type. Magic goods need real scoping
(per the design decision made during brainstorming: they should only be
purchasable when an `arcane_shop` actually exists), which is a small,
well-contained generalization:

```python
def generate_purchases(
    seed, household_rows, resident_rows, goods_ids, shop_building_ids, year_start,
    weeks: int = 52,
    magic_prevalence: float = 0.0,
    arcane_shop_building_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
```

- `arcane_shop_building_ids` defaults to `[]` when `None`.
- A good's `category` (already present on every `GOODS_CATALOG` entry) is
  looked up alongside its `sv`/`typical_price`. Goods with
  `category == "magic"` are **excluded entirely** from the weighted-choice
  pool unless `magic_prevalence > 0` **and** `arcane_shop_building_ids` is
  non-empty — a town with `magic_prevalence > 0` but no `arcane_shop`
  building (or `magic_prevalence = 0` regardless of buildings) generates
  zero magic purchases, not an error.
- When eligible, a magic good's weight is `sv * magic_prevalence` (same
  "weight directly by sv" logic as every other good, scaled down for
  lower prevalence) and its `shop_id` is drawn from
  `arcane_shop_building_ids` specifically, not the general
  `shop_building_ids` pool. Every non-magic good's weight and shop
  selection is completely unchanged.
- At `magic_prevalence = 0.0` (default) with `arcane_shop_building_ids`
  omitted, behavior is byte-identical to today.

`generate_town_database` computes `arcane_shop_building_ids` the same way
it already computes `school_ids`/`garrison_ids` — a list comprehension
over `town.districts`/`buildings` filtering `building_type ==
"arcane_shop"` — and threads `magic_prevalence` through to both
`generate_town` and `generate_purchases`.

## Resident Trait — `has_magical_talent` (`town_db`)

`build_households_and_residents` gains `magic_prevalence: float = 0.0`.
Each resident row gets `"has_magical_talent": False` initialized alongside
its other per-member fields (mirroring `"is_noble": False`'s
initialization), then a new helper:

```python
def _tag_magical_talent(rng, resident_rows: List[Dict[str, Any]], magic_prevalence: float) -> None:
    for row in resident_rows:
        row["has_magical_talent"] = rng.random() < magic_prevalence
```

called right after `_tag_nobility(...)` — an independent post-hoc pass,
structurally identical to `_tag_nobility`'s shape (a single loop flipping
a boolean per resident), except unconditional over the whole population
rather than restricted to an eligible subset (nobility is restricted to
rich adults with a fixed count; magical talent is a flat independent
probability over everyone, matching the "latent talent across the general
population" design decision).

**Deliberately independent of occupation.** A resident's
`has_magical_talent` is not correlated with being a `mage`/`apprentice`.
Occupation assignment (`town_shaper/assignment.py`) happens purely by
capacity/vacancy with no awareness of resident attributes, and existing
traits (race, SES) aren't correlated with occupation either — this keeps
the new trait consistent with that existing architecture rather than
introducing new cross-cutting assignment logic for one trait. A `mage`
who doesn't happen to roll `has_magical_talent` is an accepted, minor
narrative loose end for this slice; a future capability could tighten the
correlation if it turns out to matter.

`_insert_residents` (`town_db/generate.py`) gains the new column in its
`INSERT` statement and value tuple.

## Error Handling & Edge Cases

- `magic_prevalence` outside `[0.0, 1.0]` raises `ValueError` from
  `TownParameters.__post_init__`, before any generation work starts — same
  pattern as `rich_proportion`.
- No `arcane_shop` spawning is not an error. At low `magic_prevalence`
  and/or small towns, it's entirely possible no `MERCHANT` district rolls
  one (same "district shortfall" tolerance already accepted elsewhere in
  this project, e.g. `density_multiplier`'s housing-shortfall behavior).
  `generate_purchases` already handles the empty-`arcane_shop_building_ids`
  case by excluding magic goods from the pool rather than raising.
- `has_magical_talent` has no correlation requirement with occupation,
  buildings, or anything else — pure independent probability per resident,
  which can occasionally (rarely) produce zero talented residents even at
  a nonzero `magic_prevalence` for a small population; not treated as an
  error, matching the existing tolerance for statistical outcomes
  elsewhere (e.g. `rich_proportion` at small populations).

## Testing Strategy

- **`TownParameters` validation**: `magic_prevalence` defaults to `0.0`;
  values outside `[0.0, 1.0]` raise `ValueError`; boundary values (`0.0`,
  `1.0`) are valid.
- **`town_shaper` building placement**: `arcane_shop` never appears at
  `magic_prevalence = 0.0` (many districts/seeds); appears with
  meaningfully higher frequency at higher `magic_prevalence` (statistical
  assertion over many districts, matching the existing `university` test
  style); `JOB_VACANCIES_BY_BUILDING_TYPE["arcane_shop"]` matches
  `mage` + `apprentice`; `generate_town`'s default reproduces prior exact
  behavior (backward-compatibility test, same shape as 1a/1b's).
- **`town_db.goods`/`purchases`**: magic goods excluded from the pool when
  `arcane_shop_building_ids` is empty or `magic_prevalence = 0`; included
  and correctly shop-scoped (only assigned to `arcane_shop_building_ids`)
  when both are present; purchase frequency scales with `magic_prevalence`
  (statistical, over many simulated weeks).
- **`town_db.households`**: `has_magical_talent` proportion roughly tracks
  `magic_prevalence` over a large resident sample (statistical, same
  style as the existing `rich_proportion` test in `town_shaper`); no
  assertion forcing correlation with occupation (explicitly not a
  requirement).
- **End-to-end**: `generate_town_from_parameters` with `magic_prevalence`
  set produces a valid database — `generation_parameters` records the
  value, `residents.has_magical_talent` is populated, `PRAGMA
  foreign_key_check` is clean, and (with a high enough `magic_prevalence`
  and population) at least one `arcane_shop` with `dock`-style vacancies
  filled and at least one magic-good purchase exist across a
  determinism-preserving sweep of a few seeds.
- **Backward compatibility**: every touched function (`fill_district_buildings`,
  `generate_town`, `generate_purchases`, `build_households_and_residents`,
  `generate_town_database`, `generate_town_from_parameters`) called with no
  new arguments reproduces current exact behavior for a fixed seed —
  regression guard, same shape as 1a's and 1b's own backward-compatibility
  tests.

## Out of Scope for This Spec

- Any gameplay/simulation logic reading `has_magical_talent` — deferred to
  a future capability (safe-mode simulation or creative-mode editing).
- Enforcing a correlation between `has_magical_talent` and the
  `mage`/`apprentice` occupations.
- A new `ZoneType` or any spatial-placement logic for `arcane_shop` — it's
  a plain addition to `MERCHANT`'s existing building-type weights, not a
  water-relative or otherwise specially-placed building like 1b's `PORT`.
- Aggression/stress (1d — a separate spec).
- Magic-specific building types beyond `arcane_shop` (e.g. a
  `mage_tower`/`arcane_academy` in `CIVIC`) — considered during
  brainstorming and explicitly deferred in favor of a single, simpler
  building type for this slice.
