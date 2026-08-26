# Town Social Unrest (Aggression & Stress) — Design

## Context

This is sub-slice **1d**, the final piece of capability 1 ("narrative-to-
parameters generation") from `../../../Agent_Control_Doc.md` — see
`2026-08-24-town-narrative-parameters-design.md` (1a) for the full
capability breakdown. 1a, 1b, and 1c are done and merged: 1a established
`TownParameters`/`generate_town_from_parameters`; 1b added rivers/coastline/
port geometry; 1c added a `magic_prevalence` parameter driving a building
type, an economy category, and a resident trait.

1d adds an `aggression` parameter driving skirmish/incident events —
`town_db`'s year-of-history generation gains a new event type alongside
`disease_events`/`births`/`deaths` — and a derived `stress` metric computed
from the resulting town data (poor-population fraction + skirmish
frequency), per the Agent Control Doc's original framing ("is the
population more or less aggressive? what is the overall level of stress in
the city?") as refined during brainstorming: `aggression` is the only new
input; `stress` is a read-only, on-demand computed value with no consumer
yet (no capability 2 or 3 exists to read it), so it is not stored.

## Scope

New module `town_db/unrest.py` (skirmish event + casualty generation),
new module `town_db/stats.py` (`compute_stress`). Changes to
`town_db/schema.py` (new `skirmish_events` table, new nullable
`deaths.skirmish_event_id` column), `town_db/generate.py` (wiring),
`town_narrative/parameters.py` and `town_narrative/generate.py`
(`aggression` threading), plus the narrative-mapping doc and skill.

Out of scope: a rich-vs-poor conflict variant (skirmishes are always
poor-vs-guard for this slice); any effect of the computed `stress` value
feeding back into generation (no consumer exists yet — deferred to a
future capability, most likely safe-mode simulation); persisted/stored
stress; magic prevalence, water/port (already shipped, unrelated).

## Data Model

### `TownParameters` addition (`town_narrative/parameters.py`)

```python
aggression: float = 0.0
```

Validated in `__post_init__`: `0.0 <= aggression <= 1.0`, raising
`ValueError` otherwise — identical pattern to `magic_prevalence`.

### `generation_parameters` table gains

```sql
aggression REAL NOT NULL
```

### New `skirmish_events` table (`town_db/schema.py`)

```sql
CREATE TABLE skirmish_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    skirmish_date TEXT NOT NULL,
    severity REAL NOT NULL
);
```

A single-day incident (unlike `disease_events`' start/end outbreak range) —
`name` is a fixed descriptive string (e.g. `"a clash between the poor
quarter and the city guard"`), `severity` drives casualty rates (see
below).

### `deaths` table gains

```sql
skirmish_event_id INTEGER REFERENCES skirmish_events(id)
```

Nullable, parallel to the existing `disease_event_id` — a death has at most
one cause-event FK populated (disease or skirmish), never both.

## Skirmish Event Generation (`town_db/unrest.py`)

```python
SKIRMISH_WEEKLY_CHANCE_SCALE = 0.1
POOR_CASUALTY_RATE_SCALE = 0.002
GUARD_CASUALTY_RATE_SCALE = 0.01
SKIRMISH_NAME = "a clash between the poor quarter and the city guard"

def generate_skirmish_events(
    seed, year_start: date, resident_rows: List[Dict[str, Any]], aggression: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
```

Called from `generate_town_database` **after** `generate_births_and_deaths`
(so only residents still alive after age/disease deaths are eligible —
extends the existing "vital records run before purchases/taxes" ordering
one step further) and **before** `purchases`/`taxes` (so skirmish
casualties stop transacting the same year they die, same reasoning as the
existing ordering comment).

**Frequency**: reuses the per-week Bernoulli-trial pattern already
established in `town_db/purchases.py` (rather than `disease_events`' single
one-shot roll, since real frequency scaling is required). Each of the 52
weeks independently rolls a skirmish with probability `aggression *
SKIRMISH_WEEKLY_CHANCE_SCALE`. At `aggression=1.0`, ~5.2 expected
skirmishes/year; at `aggression=0.3`, ~1.5/year; at `aggression=0.0`
(default), zero — exact backward compatibility, no existing call site or
test requires changes.

Each triggered week produces one `skirmish_events` row: a random day within
that week (mirroring `purchases.py`'s `week_start + timedelta(days=...)`
pattern) and `severity = rng.uniform(0.2, 1.0)`.

**Casualties**: for each skirmish event, independently for every resident
currently alive (`row["death_date"] is None`):
- If `row["ses"] == "poor"` and `row["age_bracket"] == "adult"`: roll death
  with probability `severity * POOR_CASUALTY_RATE_SCALE`.
- If `row.get("occupation") in {"guard", "soldier"}`: roll death with
  probability `severity * GUARD_CASUALTY_RATE_SCALE` (guards are far fewer
  and more directly exposed, hence the higher per-resident rate).
- All other residents (rich, children, non-guard occupations) are never
  eligible for skirmish casualties — a deliberate restriction, not an
  oversight.

A resident who dies gets `row["death_date"]` set in place (same mutation
style as `generate_births_and_deaths`) and a death record appended with
`cause="skirmish"`, `skirmish_event_id` set, `disease_event_id=None`, and
`reported_by_building_id` resolved the same way military service resolves
a garrison: a `guard_post` building if one exists, else `garrison`, else
`None`. If no reporting building exists, no skirmish deaths are recorded
that year (the skirmish event itself is still logged) — same tolerance
already established for vital records with no temple/healer.

Returns `(skirmish_event_rows, death_rows)` — `death_rows` has the same
shape as `generate_births_and_deaths`' `deaths` return value, so
`generate_town_database` can reuse its existing `INSERT INTO deaths` loop
directly (with `disease_event_id` always `None` and `skirmish_event_id`
populated for these rows, the mirror image of today's disease-death rows).

## Derived `stress` (`town_db/stats.py`)

```python
STRESS_PER_SKIRMISH = 0.1

def compute_stress(db_path: str) -> float:
    conn = sqlite3.connect(db_path)
    poor_count, total_count = conn.execute(
        "SELECT SUM(CASE WHEN ses = 'poor' THEN 1 ELSE 0 END), COUNT(*) FROM residents"
    ).fetchone()
    skirmish_count = conn.execute("SELECT COUNT(*) FROM skirmish_events").fetchone()[0]
    conn.close()
    poor_fraction = poor_count / total_count if total_count else 0.0
    return min(1.0, poor_fraction + skirmish_count * STRESS_PER_SKIRMISH)
```

A plain, query-time function — no stored state, no dependency on
`town_narrative`, callable independently by anything with a `db_path`
(a future narrative-reporting skill, a safe-mode-sim capability, or ad-hoc
inspection). Values are fantasy-original (no historical grounding
available for a "stress" metric), flagged as a reasonable starting
formula, open to tuning — same spirit as other empirically-ungrounded
constants introduced in 1c.

## Wiring (`town_db/generate.py`, `town_narrative/*`)

`generate_town_database` gains `aggression: float = 0.0`. After the
existing `generate_births_and_deaths` call and its `births`/`deaths`
insert loop, add:

```python
guard_post_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "guard_post"), None)
garrison_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "garrison"), None)
reporting_building_id = guard_post_id if guard_post_id is not None else garrison_id

skirmish_rows, skirmish_deaths = generate_skirmish_events(seed, year_start, resident_rows, aggression)
for s in skirmish_rows:
    cursor = conn.execute(
        "INSERT INTO skirmish_events (name, skirmish_date, severity) VALUES (?, ?, ?)",
        (s["name"], s["skirmish_date"], s["severity"]),
    )
    s["_db_id"] = cursor.lastrowid
for death in skirmish_deaths:
    conn.execute(
        "INSERT INTO deaths (resident_id, death_date, cause, skirmish_event_id, reported_by_building_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (death["resident_db_id"], death["death_date"], death["cause"],
         death["skirmish_event_id"], death["reported_by_building_id"]),
    )
    conn.execute(
        "UPDATE residents SET death_date = ? WHERE id = ?",
        (death["death_date"], death["resident_db_id"]),
    )
```

placed before the `purchases`/`taxes` block, consistent with the ordering
requirement above. `TownParameters` and `generate_town_from_parameters`
thread `aggression` through and record it in `generation_parameters`,
exactly mirroring `magic_prevalence`'s wiring in 1c.

## Error Handling & Edge Cases

- `aggression` outside `[0.0, 1.0]` raises `ValueError` from
  `TownParameters.__post_init__`, before any generation work starts.
- No upper bound enforced anywhere else in the pipeline (matches this
  project's established tolerance for extreme parameter combinations
  degrading gracefully rather than erroring) — an absurd `aggression` just
  means more frequent, still well-formed skirmish events.
- No `guard_post`/`garrison` building existing: skirmishes still occur and
  are logged, but produce zero deaths (no reporting building) — not an
  error, matches the existing vital-records tolerance.
- Zero eligible poor adults or zero eligible guards: that side simply never
  takes casualties in a given skirmish — not an error.
- `compute_stress` on a database with zero residents returns `0.0` rather
  than dividing by zero.

## Testing Strategy

- **`TownParameters` validation**: `aggression` defaults to `0.0`; values
  outside `[0.0, 1.0]` raise; boundary values valid.
- **`generate_skirmish_events` frequency**: skirmish count scales with
  `aggression` (statistical, broad seed sweep — per this project's
  established lesson that probabilistic generation logic needs real
  verification, not a single seed); `aggression=0.0` produces zero
  skirmishes.
- **Casualty eligibility**: across many skirmishes/seeds, every skirmish
  death is either a poor adult or a guard/soldier — never a child, a rich
  resident, or an unrelated occupation.
- **Schema**: `skirmish_events` accepts a row; `deaths.skirmish_event_id`
  accepts a value and stays nullable for disease/other-cause deaths.
- **`compute_stress`**: increases with a higher poor-population fraction;
  increases with more skirmish events; clamped at `1.0`; returns `0.0` for
  an empty-residents database without raising.
- **End-to-end**: `generate_town_from_parameters` with `aggression` set
  produces a valid database — `generation_parameters` records the value,
  `skirmish_events`/`deaths` rows exist at a high-enough `aggression` and
  population, `PRAGMA foreign_key_check` is clean, and `compute_stress`
  runs successfully against the result.
- **Backward compatibility**: every touched function called with no new
  arguments reproduces current exact behavior for a fixed seed — same
  regression-guard shape as 1a/1b/1c.

## Out of Scope for This Spec

- A rich-vs-poor conflict variant of skirmishes (poor-vs-guard only, for
  this slice).
- Any effect of the computed `stress` value feeding back into generation —
  no consumer exists yet; deferred to a future capability (most likely
  safe-mode simulation).
- Persisting `stress` anywhere — computed on demand only.
- Capability 2 (safe-mode simulation) and capability 3 (creative-mode
  editing) themselves — this spec only finishes capability 1.
