# Town Year-Advance (Safe-Mode Simulation, Slice 1) — Design

## Context

This is **slice 1 of capability 2** ("safe-mode simulation") from
`../../../Agent_Control_Doc.md`. Capability 1 (narrative-to-parameters,
D1a-D1d) and capability 3's first slice (creative-mode entity mutation,
`town_db/edits.py`) are both done and merged.

Per the Agent Control Doc's original framing, safe-mode simulation is
where "the town evolves over time on its own... nothing external injects
into it." During brainstorming, the user confirmed capability 2 now also
absorbs the previously-separate "multi-entity event propagation" idea
(disease/disaster/war consistently affecting many entities) — so the full
capability is decomposed into five ordered sub-slices:

1. **Year-advance orchestrator** (this spec) — the town keeps living:
   ages residents, carries births/deaths/purchases/taxes/enrollment/
   military forward using the *existing* per-year generators against the
   *current* population, and adds the two mechanics that make later years
   meaningfully different from year 1 — new-household formation and job
   vacancy succession. No new event types yet.
2. Event-propagation engine — a general primitive (scope, severity,
   effects) generalizing what capability 3's `scope_disease_event`/
   `create_disease_event` started, but decided autonomously by the engine
   rather than an author.
3. Disease overhaul — everyday, ongoing illness instead of a rare
   yearly coin-flip, built on (2).
4. Natural disaster — new event type on (2).
5. War — new event type on (2), likely the most complex.

This spec covers slice 1 only.

## Scope

New module `town_db/simulation.py` (orchestration entry point,
`town_state` persistence), new module `town_db/household_formation.py`
(new-household formation pass), new module `town_db/job_market.py` (job
vacancy fill pass). Changes to `town_db/schema.py` (new `town_state`
table), `town_db/generate.py` (writes the initial `town_state` row),
`town_relationships/generate.py` (idempotency fix so `derive_relationships`
is safely re-runnable).

Out of scope (deferred to later slices or explicitly logged as open
gaps): any new event type (disease overhaul, disaster, war — slices 2-5);
the town's physical footprint changing size (new/demolished buildings —
logged in `docs/narrative-gaps.md`, 2026-08-28 entry); job-switching for
already-employed residents; `TownParameters`-level tuning of the new
household-formation rate (kept a plain module constant for this slice);
any narrative/creative-mode interaction (this is the safe-mode path only
— capability 3's `edits.py` is untouched).

## Data Model

### New `town_state` table (`town_db/schema.py`)

```sql
CREATE TABLE town_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    year_start TEXT NOT NULL,
    current_date TEXT NOT NULL,
    aggression REAL NOT NULL,
    magic_prevalence REAL NOT NULL
);
```

Singleton row, same convention as `generation_parameters`. **Deliberately
independent of `generation_parameters`**: `generation_parameters` is only
ever written by `town_narrative.generate_town_from_parameters` (confirmed
by reading `town_narrative/generate.py` directly) — `town_db.generate_town_database`,
which is what actually needs to persist this data, is regularly called
directly with no `town_narrative` involvement at all (every test in
`tests/test_db_generate.py` does exactly this), so a database can easily
have no `generation_parameters` row. `town_state` is written unconditionally
by `generate_town_database` itself instead, so `advance_town` never depends
on whether the narrative layer was used.

`year_start` is immutable (the town's original generation start date, for
deriving `year_index` — see Orchestration below); `current_date` is "as of
what date is this town's data," mutated by `advance_town`. `aggression`/
`magic_prevalence` are copied from `generate_town_database`'s own
parameters (which it already receives) so `advance_town` can re-drive
`generate_skirmish_events`/`generate_purchases` without any dependency on
`generation_parameters`. `generate_town_database` inserts this row (year_start
value it already has as a parameter; `current_date = year_start + 1 year`,
the end of the year it already generates) — a pure persistence addition,
no behavior change to existing generation. `advance_town` reads and updates
`current_date`.

### `households` table — no schema change

New households created by the formation pass use the existing
`households(id, family_name, race)` shape; `id` continues from
`MAX(id)+1`.

## Orchestration (`town_db/simulation.py`)

```python
def advance_town(db_path: str, seed, years: int = 1) -> None
```

For each of `years` iterations:

1. Read `town_state.current_date` as `year_start`; `year_end = year_start
   + 1 year` (using the same date-arithmetic already used for
   `DEFAULT_YEAR_START`-based generation).
2. Compute a per-year effective seed: `year_seed = rng_for(seed,
   "town_state", "year", year_index)`, where `year_index` is a stable
   counter of how many years have elapsed since the town's original
   `year_start` (so it stays consistent across repeated `advance_town`
   calls on the same town, never resets) — see Implementation Note below
   for how `year_index` is computed. `year_seed` is passed as the `seed`
   argument into every existing generator call below, unmodified.
3. Run steps in this order (mirrors `generate_town_database`'s existing
   "events and vital records before economic activity" rationale, extended
   one step further for the two new mechanics):
   1. `generate_disease_events(year_seed, year_start)`,
      `generate_skirmish_events(year_seed, year_start, aggression)` —
      reused as-is, reading `aggression`/`magic_prevalence` back out of
      `town_state` (not `generation_parameters` — see Data Model above).
   2. `generate_births_and_deaths(...)`, skirmish casualties — reused as-is,
      against the currently-living population.
   3. **New**: `generate_household_formations(conn, year_seed, year_start,
      year_end)` (`town_db/household_formation.py`).
   4. **New**: `fill_job_vacancies(conn, year_seed, year_start)`
      (`town_db/job_market.py`).
   5. `generate_purchases`, `generate_tax_payments`,
      `generate_school_enrollments`, `generate_military_service` — reused
      as-is, against the now-current living population and household
      structure.
   6. `derive_relationships(db_path, reference_date=year_end)` — re-synced
      every simulated year (see below), not just at the end of the whole
      `advance_town` call, so the DB stays consistent and queryable after
      every year.
4. Update `town_state.current_date = year_end`.

**Implementation note on `year_index`**: rather than adding a new
`elapsed_years` counter column (extra state to keep in sync), `year_index`
is computed at the start of each iteration as `(town_state.current_date -
town_state.year_start).days // 365`, both columns read from the same
`town_state` row (no dependency on `generation_parameters`).

## Household Formation (`town_db/household_formation.py`)

```python
HOUSEHOLD_FORMATION_RATE = 0.15

def generate_household_formations(conn, seed, year_start: date, year_end: date) -> None
```

Reuses `town_relationships/family.py`'s existing structural definition of
"married": within a household, the first two adults (age ≥
`ADULT_AGE_RANGE[0]`, sorted by id) are the couple; any further adults are
unmarried dependents. Eligible movers = living adults beyond their
household's first-two-adult slot, as of `year_start`.

For each eligible adult (deterministic order — sorted by resident id, so
results are reproducible for a given `seed`):

- Roll `rng.random() < HOUSEHOLD_FORMATION_RATE`. If it doesn't fire, skip
  (retried next simulated year automatically, since eligibility is
  recomputed from current data each call).
- If it fires, look for a spouse candidate: another eligible adult from a
  *different* household, not yet paired this year, chosen via
  `rng.choice` from the remaining eligible pool (no gender constraint,
  matching how `build_households_and_residents` already assigns spouses
  without one).
- Look for a destination: a building with `building_type` in
  `BUILDING_HOME_CAPACITY` and current resident count (by
  `home_building_id`) below `BUILDING_HOME_CAPACITY[building_type]`.
- If both a spouse and a destination are found: insert a new `households`
  row — `race` taken from the *initiating* resident (the one whose
  formation roll fired, not the spouse candidate — resolves the ambiguity
  when the two are different races) and `family_name` drawn the same way
  `build_households_and_residents` draws one, `draw_surname(rng, race)`
  against that same race; update both residents' `household_id` to the
  new household and `home_building_id` to the destination building.
  Neither resident's `occupation`/`workplace_building_id` changes.
- If either is missing, the resident stays put this year — this is the
  soft cap: formation slows/pauses under housing or match scarcity rather
  than overflowing capacity or growing the town.

## Job Market (`town_db/job_market.py`)

```python
def fill_job_vacancies(conn, seed, year_start: date) -> None
```

Vacancies considered, in this order:

1. **Deaths this year** that vacated an `(building_id, occupation)` slot —
   queried from `deaths` joined to `residents` for `death_date` within the
   simulated year, filtered to residents who had a non-null `occupation`.
2. **Newly-adult residents** (crossed `ADULT_AGE_RANGE[0]` this year) with
   `occupation IS NULL` — these aren't really "vacancies" at a specific
   building, but are matched against any open slot below.

For each vacancy from (1):

- **Apprentice succession first**: reuse `town_db/edits.py`'s
  `_primary_occupation_info`/`_promote_apprentice` (already scoped to
  primary/owner-type roles in `SHOP_BUILDING_TYPES | {"arcane_shop",
  "blacksmith"}`). These two helpers move from `edits.py` to a shared
  location (`town_db/succession.py`) so both `edits.py` and
  `job_market.py` import the same implementation rather than duplicating
  it; `edits.py`'s public behavior is unchanged.
- **Labor-market fallback**, only if no apprentice exists or the vacancy
  isn't a promotable primary role: candidate pool = every living adult
  with `occupation IS NULL` (covers both existing non-working dependents
  and this year's newly-adult residents from (2) alike — the model has no
  concept of a resident "becoming unemployed" other than by dying, so this
  pool doesn't grow from deaths, only from aging). Weight candidates by SES
  match: compute
  the vacancy's occupation's current modal SES across all living residents
  town-wide who hold that occupation (excluding the vacancy itself); if a
  majority tier exists, weight `rng.choices` 3:1 toward candidates whose
  own household SES matches it; if no current holders of that occupation
  exist anywhere (first-ever fill), select uniformly. If the candidate
  pool is empty, the vacancy goes unfilled — normal economic slack, not an
  error (consistent with the soft-cap decision).
- A selected candidate has `occupation` and `workplace_building_id`
  updated to the vacancy; their `home_building_id`/`household_id` are
  unaffected.

## Relationship Re-Sync (`town_relationships/generate.py`)

`derive_relationships` currently states in its own docstring that it is
"Safe to call at most once per database: does not check for or clean up
pre-existing rows" — confirmed by reading it directly: a plain per-call
`INSERT` loop into `relationships`/`shop_relationships`, no clearing.
Since every derivation is already a pure function of current `town_db`
state (no RNG involved anywhere in `town_relationships`), the fix is:

```python
conn.execute("DELETE FROM relationships")
conn.execute("DELETE FROM shop_relationships")
```

added at the start of `derive_relationships`, before re-deriving. The
docstring is updated to state it is now idempotent/safely re-runnable.
This closes the precondition gap `edits.py`'s module docstring already
flagged (capability 3, first slice) as a known limitation — `edits.py`
itself needs no changes; the same fix benefits any future re-run after an
`edits.py` mutation too, not just `advance_town`.

## Error Handling & Edge Cases

- `advance_town` on a `db_path` with no `town_state` row (a database
  created before this slice) raises a clear error rather than guessing a
  start date — this only affects pre-slice-1 databases, none of which are
  in active use.
- Household formation with zero eligible adults, zero available spouse
  candidates, or zero vacant housing in a given year: no formations occur
  that year, not an error.
- Job market fill with an empty candidate pool: vacancy stays unfilled,
  not an error.
- `years <= 0` raises `ValueError` — there's nothing meaningful to
  simulate.
- `derive_relationships`'s new `DELETE` statements are a no-op (delete
  zero rows) on a database where it's never been called before — first
  call behaves identically to today.

## Testing Strategy

Per this project's established practice (single-seed tests hid real
geometry bugs in D1b) — probabilistic, multi-mechanic logic here gets seed
sweeps, not one seed:

- **`town_state` persistence**: `generate_town_database` writes the
  initial row correctly; `advance_town` updates it after each simulated
  year; reading a database with no row raises.
- **Household formation**: eligibility matches `family.py`'s structural
  spouse definition exactly (unit test cross-checks against
  `derive_family_relationships`'s own output on the same fixture); across
  a seed sweep, formation rate roughly tracks `HOUSEHOLD_FORMATION_RATE`
  when housing/candidates aren't scarce; formation count drops to zero
  when no vacant housing exists (soft-cap verification); no resident's
  `occupation`/`workplace_building_id` changes as a side effect of moving.
- **Job market**: apprentice succession still behaves exactly as
  `edits.py`'s existing tests describe after the `succession.py` move (a
  regression guard, not new behavior); labor-market fallback only selects
  from `occupation IS NULL` residents; across a seed sweep, SES-weighting
  measurably skews fills toward the matching tier without ever excluding
  the other tier entirely; empty candidate pool leaves the vacancy
  unfilled without raising.
- **Relationship re-sync**: calling `derive_relationships` twice on
  unchanged data produces identical row counts (idempotency); calling it
  after an `advance_town` year produces relationships consistent with the
  new state (e.g. a newly-formed household's members show as `spouse`,
  not `household_member`).
- **Integration, seed-swept**: generate a town, `advance_town(years=5)`,
  and assert data-integrity invariants across the whole run — no
  purchase/tax dated after its resident's own death, every living
  resident's age is consistent with `birth_date` as of `town_state`, no
  duplicate relationship rows, `PRAGMA foreign_key_check` clean.
- **Determinism**: same seed and `years` produce byte-identical resulting
  database state across two independent runs from the same starting DB.
- **Backward compatibility**: `generate_town_database` with no
  `advance_town` call ever made reproduces current exact behavior for a
  fixed seed (the only change is the additional `town_state` row, not any
  existing table's content).

## Out of Scope for This Spec

- Any new event type — disease overhaul, natural disaster, war (slices
  2-5 of capability 2).
- The town's physical footprint changing (new/demolished buildings) —
  logged as a deferred gap in `docs/narrative-gaps.md` (2026-08-28 entry).
- Job-switching for already-employed residents (labor-market fallback
  only ever pulls from the unemployed pool).
- Making `HOUSEHOLD_FORMATION_RATE` a `TownParameters`-level input.
- Any creative-mode (`town_db/edits.py`) behavior change beyond the
  `succession.py` extraction (a refactor, not a behavior change) and
  benefiting from the same relationship-re-sync idempotency fix.
