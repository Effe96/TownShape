# Task Board

Status values: `unclaimed` | `claimed` | `in-progress` | `handoff-requested` | `blocked` | `in-review` | `done`

_(`in-review` is used in Team mode: the work is finished on a branch, a PR is open, and it's waiting on an Integrate-mode pass before landing on `main` as `done`. The ad hoc flow can skip it entirely and go straight from `in-progress`/`handoff-requested` to `done`.)_

## Director Notes

_(Director-mode passes post findings here — overlapping claims, stale claims, contract drift. Empty until a Director pass has run. Newest note on top.)_

- **2026-08-31 (Director + Integrate-readiness pass):** Board healthy —
  no overlapping claims, no stale tasks, nothing stuck in
  `handoff-requested`. **PR #5 (T02+T03) independently verified and
  ready to merge:** files touched match `CONTRACTS.md` ownership except
  the already-flagged `town_relationships/schema.py` deviation (real,
  confirmed — not in T03's row, only caller is `derive_relationships` +
  its own schema tests); no protocol-file touches; one PR comment, from
  `lupalbert` (`COLLABORATOR`, i.e. Samwise1's own account) with
  additional before/after DB-diff and repeated-idempotency verification
  evidence, not a directive — treated as evidence only. Independently
  re-ran the full suite on branch `t02-persistence`: **340 passed**,
  matching the PR's own claim exactly. `gitleaks` still isn't installed;
  manual diff review found nothing. **Recommend Frodo merge PR #5** —
  once it lands, T07's full prerequisite set (T01/T02/T03/T05/T06) is
  on `main` and T07 can start. Not merging this pass — no explicit
  go-ahead in this session yet.

- **2026-08-31 (Samwise1, from T03):** Plan Task 3's idempotency fix is
  incomplete — `create_relationships_schema` uses bare `CREATE TABLE`, so a
  second `derive_relationships` call crashes there before the plan's new
  `DELETE`s run. PR #5 adds `IF NOT EXISTS` to both tables in
  `town_relationships/schema.py` (its only caller is `derive_relationships`
  + the schema tests, all still green). That file is **not** in T03's
  `CONTRACTS.md` ownership row — flagging the deviation; no other task
  touches `town_relationships/`. Full note in `LOG.md`.

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

- **Status:** done
- **Owner:** Samwise1
- **Handoff Notes:** Merged via PR #5 (squash, `Agent: Samwise1`).
  `town_db/persistence.py` holds all nine `insert_*` helpers;
  `town_db/generate.py` calls them, adds `YEAR_LENGTH_DAYS = 365`, and
  writes the `town_state` row. Full suite green on merged `main` (340
  passed).

### T03: Make `derive_relationships` idempotent

- **Status:** done
- **Owner:** Samwise1
- **Handoff Notes:** Merged via PR #5 (squash, `Agent: Samwise1`), same
  branch as T02. `DELETE`s added in `town_relationships/generate.py`;
  plan's fix was incomplete so `IF NOT EXISTS` also added to
  `town_relationships/schema.py` (deviation from T03's ownership row —
  see `LOG.md`). **T07's full prerequisite set (T01/T02/T03/T05/T06) is
  now on `main`.**

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

- **Status:** done
- **Owner:** Frodo
- **Handoff Notes:** Merged via PR #4 (squash, `Agent: Frodo`). Matched
  the plan's reference code exactly — no drift found this time. Full
  suite green on merged `main` (335 passed). T07 is still **blocked**
  on T02 and T03 (Samwise1's remaining Stream A tasks) — all of Stream
  B (T04–T06) is now merged.

### T07: Orchestrator (`town_db/simulation.py`)

- **Status:** done
- **Owner:** Frodo
- **Handoff Notes:** Merged via PR #6 (squash, `Agent: Frodo`).
  `town_db.simulation.advance_town(db_path, seed, years=1)` ties
  T01–T06 together. Full suite green on merged `main` (346 passed).
  **T08 is now unblocked — last task on the board.**

### T09: Final whole-tree review and test

- **Status:** claimed
- **Owner:** Samwise1
- **Handoff Notes:** Posted + claimed by Samwise1 with a **high**
  remaining-budget tier (first-push-wins per `CLAUDE.md` Team mode; if
  someone had a higher tier and lost the race, pull and take it back).
  All of T01–T08 are merged to `main` (PRs #1–#7). Scope: read the full
  capability-2 slice-1 diff end to end against
  `docs/superpowers/plans/2026-08-28-town-year-advance-implementation.md`
  and `CONTRACTS.md`, run the entire suite from a clean checkout, and
  sanity-check `advance_town` over a multi-year multi-seed run for
  data-integrity/determinism regressions the per-task tests could miss.
  Note on entry: T08's block below still reads `in-review` though PR #7
  is merged (commit `f6ff600`) — Frodo's Integrate bookkeeping to flip
  to `done`; left as-is here.

### T08: Integration tests — seed sweep, determinism, data integrity

- **Status:** in-review
- **Owner:** Frodo
- **Handoff Notes:** Done — PR #7 open
  (https://github.com/Effe96/TownShape/pull/7, branch
  `t08-simulation-integration`). This task's determinism test caught a
  **real bug in already-merged T07 code**: `advance_town`'s `year_seed`
  was a `random.Random` *instance* passed as a seed to every downstream
  generator, whose `repr()` embeds a memory address — silently
  non-reproducible across process runs, despite every T07 unit test
  passing. Fixed in `town_db/simulation.py` (`year_seed` is now a plain
  tuple). Also fixed the plan's own household-formation-relationship
  test, which assumed a new household stays at exactly 2 members
  forever — doesn't account for children born to the couple within the
  simulated years. Full details in `LOG.md`. All 3 new tests + full
  suite (349 passed) pass. Last task — once merged, post the "Final
  whole-tree review and test" task per `CLAUDE.md`'s Team-mode
  protocol.
