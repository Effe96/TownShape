# Task Board

Status values: `unclaimed` | `claimed` | `in-progress` | `handoff-requested` | `blocked` | `in-review` | `done`

_(`in-review` is used in Team mode: the work is finished on a branch, a PR is open, and it's waiting on an Integrate-mode pass before landing on `main` as `done`. The ad hoc flow can skip it entirely and go straight from `in-progress`/`handoff-requested` to `done`.)_

## Director Notes

_(Director-mode passes post findings here — overlapping claims, stale claims, contract drift. Empty until a Director pass has run. Newest note on top.)_

- **2026-08-31 (Samwise1, from T01):** `town_state.current_date` is a SQLite
  keyword collision — bare reads return today's date, not the column (writes
  are unaffected). T01 (PR #3) keeps the contract's column name and quotes
  the identifier in every read. **Frodo, before T07:** the plan's
  `advance_town` reads `current_date` bare (plan line ~1382) — must be quoted
  or the sim clock silently reads `2026-08-31`. Full analysis + the rename
  alternative (a `CONTRACTS.md` change, owner's call) in `LOG.md`.

## Tasks

<!--
Copy this block for each new task. Keep each task in its own delimited
block, with a blank line before and after — this is what keeps git
merge conflicts on this file small and localized when two people edit
it at once.

### T<NN>: <short task title>

- **Status:** unclaimed
- **Owner:** —
- **Handoff Notes:** —
-->

All 8 tasks below implement `docs/superpowers/plans/2026-08-28-town-year-advance-implementation.md`
(capability 2, slice 1 — town year-advance). Each task's Handoff Notes point at
that plan's matching `## Task N` section, which already has the exact files,
code, and tests to write — treat it as the spec, follow it TDD-style
(red → green → commit), and flag drift from it in `LOG.md` rather than
silently deviating. Branch per task: `t<NN>-<slug>` off `main`.

Two independent streams run in parallel (no file overlap — see
`CONTRACTS.md`'s File / Module Ownership):

- **Stream A** (T01 → T02 → T03): schema + persistence + idempotent
  relationships. Sequential — T02 needs T01's `town_state` table, T03 is
  independent but bundled here to keep one branch owner per stream.
- **Stream B** (T04 → T05, T06): succession extraction, then household
  formation and job market (T06 needs T04's `succession.py`; T05 doesn't
  depend on T04 and can be done in either order relative to it).

T07 and T08 are downstream of *both* streams — don't start T07 until T01,
T02, T03, T05, and T06 are all merged to `main`; don't start T08 until T07
is merged.

### T01: `town_state` schema table

- **Status:** in-review
- **Owner:** Samwise1
- **Handoff Notes:** Done — PR #3 open
  (https://github.com/Effe96/TownShape/pull/3, branch
  `t01-town-state-schema`). `town_state` singleton table added to
  `town_db/schema.py`; `EXPECTED_TABLES` + 2 new tests in
  `tests/test_db_schema.py`. Full suite 323 passed. One plan-drift finding
  (`current_date` SQLite keyword collision) — see `LOG.md` + Director Notes;
  reads must quote the identifier. Unblocks T02 once merged.

### T02: Extract `town_db/persistence.py`, wire `town_state` into `generate_town_database`

- **Status:** claimed
- **Owner:** Samwise1
- **Handoff Notes:** Plan section "Task 2". Depends on T01 being merged
  first (needs the `town_state` table). Create `town_db/persistence.py`,
  modify `town_db/generate.py` (full replacement given in the plan), add
  `tests/test_db_persistence.py`, extend `tests/test_db_generate.py`. This
  is the biggest regression-risk task in Stream A — run the *entire*
  suite (`python -m pytest tests/ -v`) before opening the PR, not just
  the new test files, since every other `town_db` test transitively
  depends on `generate_town_database`.

### T03: Make `derive_relationships` idempotent

- **Status:** claimed
- **Owner:** Samwise1
- **Handoff Notes:** Plan section "Task 3". Independent of T01/T02's
  content (touches `town_relationships/generate.py` only) but keep it on
  the same branch/PR sequence as T01→T02 to avoid a second Stream-A
  owner. Small — two `DELETE` statements plus a test.

### T04: Extract `town_db/succession.py`

- **Status:** in-review
- **Owner:** Frodo
- **Handoff Notes:** Done — PR open at
  https://github.com/Effe96/TownShape/pull/1 (branch
  `t04-succession-extract`). `town_db/succession.py` created,
  `town_db/edits.py` now imports `primary_occupation_info`/
  `promote_apprentice` from it under the same private names. All 18
  existing `test_db_edits.py` tests + 5 new `test_db_succession.py`
  tests pass; full suite (326 tests) green. Waiting on Frodo's own
  Integrate-mode pass before this can be set to `done` — T06 can start
  once it merges.

### T05: Household formation (`town_db/household_formation.py`)

- **Status:** in-review
- **Owner:** Frodo
- **Handoff Notes:** Done — PR open at
  https://github.com/Effe96/TownShape/pull/2 (branch
  `t05-household-formation`). Two real bugs found and fixed in the
  plan's own speculative reference code along the way — see `LOG.md`
  for the full writeup, short version: the spouse-candidate pool
  excluded lone single adults (making the plan's own test fixture
  unsatisfiable) and the plan's hard-coded test seed never actually
  fires the formation roll for this call path. All 4 new tests +
  full suite (325 on this branch's pre-T04 base) pass. Waiting on
  Integrate mode before `done`.

### T06: Job market (`town_db/job_market.py`)

- **Status:** claimed
- **Owner:** Frodo
- **Handoff Notes:** Plan section "Task 6". Depends on T04
  (`town_db.succession.primary_occupation_info` / `promote_apprentice`)
  being merged first. Add `tests/test_db_job_market.py`.

### T07: Orchestrator (`town_db/simulation.py`)

- **Status:** claimed
- **Owner:** Frodo
- **Handoff Notes:** Plan section "Task 7". **Blocked until T01, T02,
  T03, T05, and T06 are all merged to `main`** — this ties every other
  task's output together (`town_state`, the `insert_*`/`YEAR_LENGTH_DAYS`
  helpers, idempotent `derive_relationships`, `generate_household_formations`,
  `fill_job_vacancies`). Before starting, double-check the plan's
  `generate_births_and_deaths` call in this task's sample code against
  the actual current signature in `town_db/vital_records.py` — the plan
  was written speculatively and this call site is a known place it may
  have drifted (missing `birth_rate`/`death_rate_by_age` kwargs that
  `generate.py` passes elsewhere). Add `tests/test_db_simulation.py`, run
  the full suite before opening the PR.

### T08: Integration tests — seed sweep, determinism, data integrity

- **Status:** claimed
- **Owner:** Samwise1
- **Handoff Notes:** Plan section "Task 8". **Blocked until T07 is
  merged.** Add `tests/test_db_simulation_integration.py` — seed-swept
  multi-year `advance_town` runs checking FK integrity, no post-death
  purchases/taxes, no duplicate relationships/deaths. If the household-
  formation spouse-relationship test doesn't reliably trigger a formation
  at the given population/seed/year-count, raise `target_population`
  and/or `years` per the plan's note rather than weakening the assertion.
  Last task — once merged, post the "Final whole-tree review and test"
  task per `CLAUDE.md`'s Team-mode protocol.
