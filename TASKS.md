# Task Board

Status values: `unclaimed` | `claimed` | `in-progress` | `handoff-requested` | `blocked` | `in-review` | `done`

_(`in-review` is used in Team mode: the work is finished on a branch, a PR is open, and it's waiting on an Integrate-mode pass before landing on `main` as `done`. The ad hoc flow can skip it entirely and go straight from `in-progress`/`handoff-requested` to `done`.)_

## Director Notes

_(Director-mode passes post findings here — overlapping claims, stale claims, contract drift. Empty until a Director pass has run. Newest note on top.)_

- **2026-08-31 (Director pass):** Reviewed `TASKS.md`, `CONTRACTS.md`, and
  commits through `9f7d592`. No overlapping claims, no stale
  `claimed`/`in-progress` tasks, no stuck `handoff-requested` tasks. All
  three open PRs (#1 T04, #2 T05, #3 T01) are freshly opened this session —
  not stale, just queued for Integrate mode. Two findings:
  1. **Confirmed Samwise1's `current_date` keyword-collision finding**
     (independently re-verified against this repo's `sqlite3` — bare
     `SELECT current_date FROM town_state` returns today's date, not the
     column; `SELECT "current_date"` and `SELECT *` are both correct; writes
     are unaffected either way). T01's own PR #3 already quotes its read
     correctly. Grepped the plan doc for every remaining **bare** read
     nobody's fixed yet: T02 must fix its own copy of the plan's snippet at
     plan lines 47 and 299 (`test_generate_town_database_writes_town_state`
     and its regression-guard counterpart); T07 must fix plan lines 1225,
     1236, and 1382 (`test_advance_town_updates_town_state`,
     `test_advance_town_two_years_advances_current_date_twice`, and
     `advance_town` itself). All the plan's *writes* (INSERT/UPDATE, lines
     41/56/62/502/1449) are unaffected and need no change.
  2. **`CONTRACTS.md` drift:** the Interfaces & Data Shapes entry for
     `town_state` lists the column name but not the quoting requirement —
     a real implementor reading only `CONTRACTS.md` (not `LOG.md`) would
     miss this landmine. Director mode can only edit `TASKS.md`, so
     flagging rather than fixing: recommend Frodo add a one-line note to
     `CONTRACTS.md`'s `town_state` bullet (e.g. "reads of `current_date`
     must quote the identifier — it collides with SQLite's `CURRENT_DATE`
     keyword") next time `main` is touched. The rename alternative Samwise1
     raised (`current_date` -> `current_sim_date`) remains an option but is
     the owner's call, not decided here.

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

- **Status:** done
- **Owner:** Samwise1
- **Handoff Notes:** Merged via PR #3 (squash, `Agent: Samwise1`). `town_state`
  singleton table in `town_db/schema.py`. Plan-drift finding
  (`current_date` SQLite keyword collision — reads must quote the
  identifier) stands, see `LOG.md` + Director Notes. T02 is now unblocked.

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

- **Status:** done
- **Owner:** Frodo
- **Handoff Notes:** Merged via PR #1 (squash, `Agent: Frodo`).
  `town_db/succession.py` created; `town_db/edits.py` imports
  `primary_occupation_info`/`promote_apprentice` from it under the same
  private names. T06 is now unblocked.

### T05: Household formation (`town_db/household_formation.py`)

- **Status:** done
- **Owner:** Frodo
- **Handoff Notes:** Merged via PR #2 (squash, `Agent: Frodo`).
  `town_db/household_formation.py` — two real bugs fixed vs. the plan's
  speculative reference code (spouse-eligibility gap, dead test seed),
  see `LOG.md` for the full writeup.

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
