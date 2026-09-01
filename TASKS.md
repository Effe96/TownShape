# Task Board

Status values: `unclaimed` | `claimed` | `in-progress` | `handoff-requested` | `blocked` | `in-review` | `done`

_(`in-review` is used in Team mode: the work is finished on a branch, a PR is open, and it's waiting on an Integrate-mode pass before landing on `main` as `done`. The ad hoc flow can skip it entirely and go straight from `in-progress`/`handoff-requested` to `done`.)_

## Director Notes

_(Director-mode passes post findings here — overlapping claims, stale claims, contract drift. Empty until a Director pass has run. Newest note on top.)_

- **2026-08-31 (Samwise1, T09 final review):** Full suite 349 passed;
  determinism + integrity clean across a 10-config sweep wider than T08's
  (8 seeds × 8 years pop 400, + pop 900/1000 × 6 years, each advanced
  twice and compared row-for-row over 12 tables). **One real bug found:**
  `advance_town` re-runs `generate_military_service` every simulated year
  and `insert_military_service` just appends — soldiers accumulate one
  duplicate open-ended `military_service` row per year (up to 7 after a
  6-year advance), and `derive_unit_mate_relationships` (no
  same-`resident_id` guard) turns those into invalid
  `(X, X, 'unit_mate')` self-relationships (~8–9 per run).
  `school_enrollments` shares the append-without-guard shape (no bad data
  seen only because those seeds produced no enrollments). Not caught by
  T08 — its dup check groups by `(a,b,type)` so a lone `(6,6,...)` isn't
  a "duplicate", and nothing asserts `a != b` or bounded
  `military_service` growth. Full analysis + repro in `LOG.md`. Posted as
  **T10** (`unclaimed`); write-side fix approach is the owner's call.
  Not a merge-blocker for what's landed, but slice 1 isn't clean until
  T10 lands.

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

### T08: Integration tests — seed sweep, determinism, data integrity

- **Status:** done
- **Owner:** Frodo
- **Handoff Notes:** Merged via PR #7 (squash, `Agent: Frodo`). Caught
  and fixed a real determinism bug in already-merged T07 code
  (`advance_town`'s `year_seed` was a `random.Random` instance, not a
  plain hashable value — see `LOG.md` for the full writeup). Full suite
  green on merged `main` (349 passed). **All 8 tasks (T01–T08) are now
  `done`.**

### T09: Final whole-tree review and test

- **Status:** done
- **Owner:** Samwise1
- **Handoff Notes:** Posted + claimed by Samwise1 with a **high**
  remaining-budget tier, per `CLAUDE.md`'s Team-mode protocol
  (first-push-wins race with an equivalent draft Frodo posted at nearly
  the same moment — merged/reconciled here into one block; Samwise1's
  claim stands). All 8 tasks (T01–T08) merged to `main` (PRs #1–#7),
  full suite green (349 passed). Scope: a whole-tree review of the
  merged capability-2-slice-1 work, not just a suite re-run (already
  green) — read the full diff end to end against
  `docs/superpowers/plans/2026-08-28-town-year-advance-implementation.md`,
  `docs/superpowers/specs/2026-08-28-town-year-advance-design.md`, and
  `CONTRACTS.md`; sanity-check that the plan-drift fixes scattered
  across `LOG.md` are consistent with each other and with
  `CONTRACTS.md` (the `current_date` keyword collision, T05's
  spouse-pool fix, T03's `schema.py` deviation, T07/T08's determinism
  fix); and run `advance_town` over a multi-year multi-seed sweep
  outside the fixed test seeds, watching for data-integrity or
  determinism regressions the per-task tests could miss.

  **Result (Samwise1):** Full suite **349 passed** from clean `main`.
  Determinism+integrity sweep wider than T08's — 8 seeds × 8 years
  pop 400, + pop 900/1000 × 6 years, each town advanced twice and
  compared row-for-row over 12 tables: **determinism clean** (T07's
  memory-address bug genuinely fixed), **integrity clean** on FK,
  post-death txns, duplicate deaths, duplicate `(a,b,type)`
  relationships, death-before-birth, dangling refs. `CONTRACTS.md`
  `current_date`/ownership gaps both closed; the scattered plan-drift
  fixes in `LOG.md` are mutually consistent. **One real bug found** →
  posted as **T10**: `advance_town` accumulates duplicate open-ended
  `military_service` rows (one per soldier per simulated year) →
  invalid `(X,X,'unit_mate')` self-relationships; full analysis in
  `LOG.md` + Director Notes. Two sweep over-flags that are NOT bugs:
  relationships aren't stored `a<b` (`parent` is a directed edge), and
  the clock advances 365-day years not calendar years (per spec).
  Closed out by Frodo now that T10 (the bug it found) has landed.

### T10: Fix `military_service`/`school_enrollments` accumulation in `advance_town`

- **Status:** done
- **Owner:** Frodo
- **Handoff Notes:** Merged via PR #8 (squash, `Agent: Frodo`). Went
  with option 2 (skip residents who already have an open span) —
  `advance_town` now filters out any generated `military_service`/
  `school_enrollments` record whose resident already has an open
  (`end_date IS NULL`) span before inserting. Added the self-pair guard
  to both `derive_unit_mate_relationships` and
  `derive_classmate_relationships`. Verified directly (seed
  `("town", 7)`, pop 400, 6-year advance): before, `military_service`
  grew 8 → 56 rows with 45 invalid self-relationships; after, 9 rows
  (one genuinely new soldier), zero residents with >1 open span, zero
  self-relationships. Full suite green on merged `main` (349 passed).
  **Capability-2 slice-1 (town year-advance) is now fully complete —
  T01–T10 all `done`.**

### T11: Household wealth & income model

- **Status:** in-review
- **Owner:** Frodo
- **Handoff Notes:** PR #9 (`t11-household-wealth-model` → `main`), awaiting
  an Integrate-mode pass. Implements
  `docs/superpowers/plans/2026-08-31-household-wealth-model-implementation.md`
  (spec: `docs/superpowers/specs/2026-08-31-household-wealth-model-design.md`),
  the highest-priority gap in `docs/narrative-gaps.md` (SES has no effect
  on spending — a poor resident was empirically out-spending every rich
  one). New `town_db/economy.py` (income tiers, yearly wealth cycle);
  changes to `town_db/schema.py` (`households.wealth` column),
  `town_db/purchases.py` (wealth-tier reweighting), `town_db/persistence.py`
  (`update_household_wealth`), `town_db/generate.py` and
  `town_db/simulation.py` (wire the income → purchases/taxes → spend
  cycle into both one-shot generation and `advance_town`). Built task-by-task
  via subagent-driven-development (8 sequential sub-tasks, TDD, task-scoped
  review after each) plus a final whole-branch review. Full suite: **376
  passed**. Plan's Task 8 acceptance bar
  (`test_rich_households_out_spend_poor_households_over_time`: rich median
  household spend > poor median, swept over 10 seeds) passed on the first
  run — no constant tuning was needed.

  **Two Important findings from the final review, both deliberately deferred
  as fast-follow work, not fixed in this PR** (no test/correctness impact —
  see `LOG.md` for full detail once posted): (1) `daily_income`'s
  per-resident variation multiplier isn't year-stable in `advance_town` as
  the design spec's prose claims — a spec-doc/implementation mismatch, not a
  code bug, since the code faithfully matches the plan's own literal Task 7
  instructions; (2) the "primary" income tier only reaches the 5 building
  types `town_db.succession.primary_occupation_info` covers, so most
  non-retail occupations (priests, guards, farmers, healers, ...) cap at
  "apprentice" tier regardless of seniority — a real scope limitation,
  deliberately left out of this branch since widening `succession.py`'s
  classifier touches the shared promotion system. Both should become their
  own follow-up tasks once T11 lands.
