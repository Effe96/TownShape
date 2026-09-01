# Log

Append-only. Newest entry on top. Read this at the start of every
session, before touching code, so you're not working from stale
assumptions.

<!--
Entry template — copy for each new entry:

## YYYY-MM-DD — <agent name> — <short summary>
<What changed or was decided, and why. Flag anything the next person
needs to know before they proceed.>
-->

## 2026-09-01 — Frodo — T11: household wealth & income model, PR #9 open

Implemented `docs/superpowers/plans/2026-08-31-household-wealth-model-implementation.md`
task-by-task via subagent-driven-development (8 TDD sub-tasks, task-scoped
review after each, plus a final whole-branch review). Full suite: 376
passed. Branch: `t11-household-wealth-model`, PR #9, board status
`in-review`.

**Two deliberate circular-import workarounds**, both diverging from the
plan's literal code but confirmed necessary by independent tracing (twice —
once by me before dispatch, once by each task's reviewer during review):
`town_db/economy.py` locally redefines `YEAR_LENGTH_DAYS = 365` instead of
importing `town_db.generate.YEAR_LENGTH_DAYS`, because Task 6 wires
`generate.py` to import from `economy.py` — importing the constant back
would make `economy → generate → economy` circular. Similarly,
`town_db/purchases.py`'s `from town_db.economy import wealth_tier` is a
local import inside `generate_purchases()`, not module-level, because
`town_db/succession.py` already imports `SHOP_BUILDING_TYPES` from
`purchases.py`, so a module-level import in `purchases.py` would create
`purchases → economy → succession → purchases`. Both are correct fixes for
a genuine defect in the plan's literal code, not implementer error.

**Acceptance bar met without tuning:** the plan's actual acceptance test
(Task 8, `test_rich_households_out_spend_poor_households_over_time` — rich
households' median spend beats poor households' median spend, swept over
10 seeds, 3-year advance) passed on the first run with the plan's original
`INCOME_TIER_BY_ROLE`/`SES_INCOME_MULTIPLIER`/`STARTING_WEALTH_BY_SES`/
purchase-reweighting constants untouched. No calibration was needed.

**Two Important findings from the final whole-branch review, both ruled and
deferred as fast-follow work rather than fixed in this branch** (neither
breaks a test or produces incorrect data):
1. `daily_income`'s per-resident income-variation multiplier is supposed to
   stay stable "in every simulated year" per the design spec's prose, but
   `town_db/simulation.py`'s `advance_town` passes `year_seed` (which
   embeds the year index) into `add_yearly_income` → `daily_income`, so the
   multiplier actually re-rolls every year. This is a spec-prose/
   implementation mismatch baked into the plan itself — Task 7's brief
   literally specifies passing `year_seed`, and the resulting behavior
   (income drifts year to year) is arguably more realistic, not wrong.
   Ruling: leave the code as-is (matches the plan's own literal
   instructions, already reviewed and approved across 7 tasks); the
   spec's "stays stable" claim needs a doc fix, not the code.
2. `daily_income`'s "primary" income tier only resolves for the 5 building
   types `town_db.succession.primary_occupation_info` covers (shop,
   tavern, market_stall, arcane_shop, blacksmith) — that function is T04's
   shop-succession classifier, not a general senior-role detector. Most of
   the town's workforce (priests, guards, farmers, healers, teachers,
   dockworkers, ...), including single-capacity "head" roles, can never
   reach "primary" tier regardless of seniority; they're capped at
   "apprentice." The rich-vs-poor acceptance test still passes because SES
   multiplier and employed/unemployed status differentiate independently
   of this gap. Ruling: deliberately out of scope for T11 — widening
   `primary_occupation_info`'s classification touches the shared
   `promote_apprentice` succession system built for a different purpose,
   and deserves its own task rather than a same-branch patch.

Both findings should become their own follow-up tasks once T11 merges.

## 2026-08-31 — Frodo — T10: fixed the military_service/school_enrollments accumulation bug from T09

Picked option 2 of T09's three proposed fixes (see below): `advance_town`
now filters out any generated `military_service`/`school_enrollments`
record whose resident already has an open (`end_date IS NULL`) span of
that type, before calling `insert_military_service`/
`insert_school_enrollments`. Chose this over closing-the-prior-span
(option 1) or delete-then-reinsert (option 3) because a service/
enrollment span is naturally continuous — a soldier doesn't "re-enlist"
every year, they just keep serving — so skipping re-generation for
someone already in progress is the closest semantic fit, and it's a
minimal additive filter in `advance_town`'s orchestration layer rather
than a signature change to `generate_military_service`/
`generate_school_enrollments`, both of which stay exactly as
`generate_town_database` already uses them for one-shot generation.

Also added the unambiguous self-pair guard
(`if a["resident_id"] == b["resident_id"]: continue`) to both
`derive_unit_mate_relationships` (confirmed the actual bug) and
`derive_classmate_relationships` (same structural gap, not confirmed to
have fired in practice yet — `age_at_start` differs year to year for
the same resident, which usually routes duplicate school-enrollment
records into different cohort buckets, but there's no reason to leave
the same unguarded pairing loop in place).

Verified pre/post with the exact numbers rather than estimating: seed
`("town", 7)`, pop 400, 6-year advance. Pre-fix (checked out the parent
commit's files temporarily to measure, then restored): `military_service`
grew 8 → 56 rows, 45 invalid `(X, X, 'unit_mate')` self-relationships.
Post-fix: 9 rows (one genuinely new soldier over 6 years — not a
duplicate), zero residents with more than one open span, zero
self-relationships. T09's sweep assertions (per-resident open-span
bound for both tables, no self-relationships) folded into the existing
`test_five_year_advance_preserves_data_integrity_across_seeds` per T09's
own recommendation, rather than a new test function.

## 2026-08-31 — Samwise1 — T09 final review: suite + determinism clean; found one real cross-year bug (military_service accumulation → unit_mate self-loops)

**Ran:** full suite from clean `main` (`0495883`) — **349 passed**. Plus a
wider determinism+integrity sweep than T08's: 8 seeds × 8 years at
pop 400 + two towns at pop 900/1000 × 6 years, each advanced twice and
compared row-for-row across 12 tables.

**Determinism: clean.** All 10 independent-run pairs are byte-identical
across `residents`, `households`, `purchases`, `tax_payments`, `births`,
`deaths`, `skirmish_events`, `school_enrollments`, `military_service`,
`relationships`, `shop_relationships`, `town_state`. T07's memory-address
determinism bug is genuinely fixed.

**Integrity: clean** on FK checks, no post-death purchases/taxes, no
duplicate `deaths` rows, no duplicate `(a,b,type)` relationship rows, no
death-before-birth, no dangling death/birth resident refs, `CONTRACTS.md`
`current_date`/ownership gaps both closed.

**BUG FOUND — `advance_town` appends `military_service` rows every
simulated year with no clear/guard:**

- Fresh `generate_town_database`: 8 `military_service` rows, 0 residents
  with more than one. After `advance_town(years=1)`: 16 rows, every
  soldier now has 2. `years=3` → 4 each. `years=6` → up to **7 rows per
  resident**, all with `end_date IS NULL`. It grows by one duplicate
  open-ended service record per soldier per simulated year, unbounded.
- Knock-on: `town_relationships/military.py::derive_unit_mate_relationships`
  pairs every two service records in the same garrison with overlapping
  dates and does **not** skip same-`resident_id` pairs. Two+ open-ended
  rows for resident X in garrison G ⇒ `canonical_pair(X, X, "unit_mate")`
  ⇒ a semantically invalid `(X, X, 'unit_mate')` self-relationship. ~8–9
  per run in the sweep.
- Root cause: `advance_town` re-runs `generate_military_service` each year
  (copied from `generate.py`'s one-shot structure) and `insert_military_service`
  just appends. Contrast `derive_relationships`, which T03 deliberately
  made delete-then-reinsert for exactly this reason. `military_service`
  (and `school_enrollments` — same shape, a stateful span not a per-year
  event) got no equivalent treatment. `purchases`/`tax_payments` are
  correctly per-year (dated events), so their yearly growth is fine.
- Why the existing tests miss it: T08's dup check groups by
  `(resident_a_id, resident_b_id, relationship_type)`, so a single
  `(6,6,'unit_mate')` row isn't a "duplicate"; nothing asserts
  `resident_a_id != resident_b_id`, per-resident `military_service` row
  counts, or bounded growth. FK-clean and deterministic, so those tests
  pass too.

Not fixing here — the write-side fix has a real design choice (close the
prior year's span with an `end_date`? skip re-generating for
already-serving residents? make military/school derivation
delete-then-reinsert like relationships?) that's the owner's call. The
`derive_unit_mate_relationships` self-pair guard
(`if a["resident_id"] == b["resident_id"]: continue`) is an unambiguous
defensive fix but only masks the symptom. Posted as **T10** (unclaimed)
with these options. Repro scripts were throwaway; the sweep logic is
worth folding into `tests/test_db_simulation_integration.py` as part of
T10.

Two things my sweep over-flagged that are **not** bugs: (1) relationships
aren't stored `resident_a_id < resident_b_id` — correct, `parent` is a
directed edge (a is parent *of* b); (2) the `town_state` clock advances
by `years × 365` days, not calendar years, so an 8-year advance from
1300-01-01 lands on 1308-12-30 (two leap days in span) — that's the
plan's explicit "a year is exactly 365 days" rule.

## 2026-08-31 — Frodo — TASKS.md race: two T09 posts, reconciled

Pushed T08's `done` status + a fresh unclaimed T09 ("Final whole-tree
review and test") right as Samwise1 independently noticed the same
thing and posted + claimed T09 themselves (high budget tier). Neither
push was rejected outright (`git push` failed on Frodo's side with
"fetch first", not a hard conflict), and the subsequent merge auto-
resolved without conflict markers since the two edits landed at
slightly different points in the file — but the result was two T09
blocks (one claimed, one duplicate-unclaimed) with T08 sandwiched
between them out of order. Reconciled by hand: kept Samwise1's claim
(they were first to push), merged the more detailed scope description
from Frodo's draft into their block, and restored T08 → T09 file order.
No work was lost or overwritten — this was a formatting/ordering
collision, not a competing-claim conflict.

## 2026-08-31 — Frodo — T08: caught a real non-determinism bug in already-merged T07 code

T08 was reassigned from Samwise1 to Frodo (owner's call, no work lost —
Samwise1 hadn't started it). Its whole purpose — catching cross-run
issues that per-task unit tests structurally can't see — paid off
immediately.

**The bug:** `town_db/simulation.py`'s `advance_town` did
`year_seed = rng_for(seed, "town_state", "year", year_index)`. `rng_for`
*returns* a `random.Random` instance — but `year_seed` was then passed
as the `seed` argument into every downstream generator
(`generate_disease_events`, `generate_births_and_deaths`,
`generate_household_formations`, `generate_purchases`, etc.), each of
which re-derives its own RNG via its own `rng_for(seed, ...)` call.
`rng_for`/`derive_seed` hashes `repr(base_seed)` — and a `random.Random`
object's `repr()` embeds its memory address
(`<random.Random object at 0x...>`), which differs on every process
run. So every generator downstream of that line was silently seeded
non-reproducibly, and no unit test caught it: T07's own tests all ran
`advance_town` exactly once per test, never comparing two independent
invocations. `test_advance_town_is_deterministic` does exactly that,
and failed immediately — two identically-seeded 3-year advances
diverged starting in year 1 (421 vs. 426 residents, different deaths,
different household assignments for the same resident id).

Repro'd directly (`rng_for(('town', 7), 'town_state', 'year', 0)` prints
a different memory address every interpreter run) and confirmed the fix
with a standalone before/after script: pre-fix, two runs' `residents`
tables diverged after 1 year; post-fix, all 9 compared tables (`residents`,
`households`, `purchases`, `tax_payments`, `births`, `deaths`,
`skirmish_events`, `relationships`, `shop_relationships`) were
byte-identical across a 3-year advance.

**Fix:** `year_seed = (seed, "town_state", "year", year_index)` — a
plain hashable tuple, not an `rng_for(...)` return value. The now-unused
`rng_for` import was removed from `town_db/simulation.py`.

**Second bug, in the plan's own test:** `test_household_formation_produces_spouse_not_household_member_relationship`
assumed a newly-formed household always has exactly its founding two
members. It doesn't account for children born to that couple within the
remaining simulated years — they join the same `household_id` as
infants. Root cause of the actual failure: a child's autoincremented id
happened to numerically sort *between* its two parents' ids, so the
test's naive "sort all household members, take the first two" picked
the wrong pair and checked for a `spouse` relationship between a parent
and their child instead of between the two parents. Fixed by identifying
the household's adults via `age_on(..., reference_date) >=
ADULT_AGE_RANGE[0]` (reading `town_state`'s `current_date`, quoted) at
verification time, rather than assuming household size stays at 2.

If you're implementing anything from this plan and hit unexplained
non-determinism or a wrong-looking assertion, check whether the plan's
own code/tests are the actual bug before assuming yours is — this is
now three tasks (T05, T08's test, and T07 via T08) where they were.

## 2026-08-31 — Frodo — T02+T03 (PR #5) merged; Stream A + Stream B both complete

Independently re-verified PR #5 (full suite 340 passed on the branch,
files matched ownership except the already-known `schema.py` deviation,
one PR comment from Samwise1's own account with extra DB-diff/
idempotency evidence, no protocol-file touches) before merging on the
user's explicit go-ahead. Re-ran the full suite again on merged `main`:
340 passed, clean combine. T01–T06 are now all `done` — closed the two
`CONTRACTS.md` gaps Director Notes had been carrying since the earlier
Director pass rather than leaving them open: added the `current_date`
quoting note to the `town_state` interface bullet, and added
`town_relationships/schema.py` to T03's File / Module Ownership row.
T07's full prerequisite set is now on `main` — starting it next.

## 2026-08-31 — Frodo — Integrate pass: T01, T04, T05 merged

Ran an Integrate pass on PRs #1 (T04), #2 (T05), #3 (T01) — all three
matched their `CONTRACTS.md` File / Module Ownership exactly, none
touched `TASKS.md`/`CONTRACTS.md`/`LOG.md`/`CLAUDE.md`, no PR
comments to flag. `gitleaks` isn't installed on this machine, so the
secret scan was manual review instead of tooling (nothing found);
skipped the optional `claude-security` pass given how small and
low-risk these diffs are. Independently re-ran the full suite on each
branch before proposing the merge, then again on merged `main`
afterward: 332 passed (321 baseline + 2 T01 + 5 T04 + 4 T05), confirming
a clean combine with no cross-task regressions. Merged in order T01 →
T04 → T05 (squash, each keeping its actual author's `Agent:` trailer).
T02 and T06 are now unblocked.

## 2026-08-31 — Samwise1 — T02 + T03 done (PR #5); Task 3's idempotency fix was incomplete

**T02** (extract `town_db/persistence.py`): straightforward — the nine
`insert_*` helpers moved out of `generate.py` verbatim, `generate.py`
now calls them, adds `YEAR_LENGTH_DAYS = 365`, and writes the
`town_state` row. `insert_deaths` unifies the old disease/skirmish death
paths into one statement using `.get()` for the two event-id columns;
`test_generate_town_database_is_deterministic` + the new
`unchanged_by_persistence_refactor` guard confirm byte-identical output.
The new `town_state` read test quotes `"current_date"` per the earlier
finding.

**T03** (`derive_relationships` idempotent): the plan's Task 3 only adds
`DELETE FROM relationships` / `DELETE FROM shop_relationships` after
`create_relationships_schema(conn)`. That is not enough:
`create_relationships_schema` runs `executescript` with bare
`CREATE TABLE relationships (...)` / `CREATE TABLE shop_relationships (...)`
— **no `IF NOT EXISTS`** — so the *second* `derive_relationships` call
raises `sqlite3.OperationalError: table relationships already exists`
before the `DELETE`s are ever reached. (The plan predicted a silent
row-count doubling; the real pre-fix behaviour is a hard crash.)

Fix: added `IF NOT EXISTS` to both `CREATE TABLE`s in
`town_relationships/schema.py`, keeping the plan's `DELETE`-then-reinsert
approach (which is what `CONTRACTS.md` T03 specifies). `schema.py` is
**not** listed in T03's File / Module Ownership row in `CONTRACTS.md`
(only `town_relationships/generate.py` + the test are) — flagged in
Director Notes. Its only callers are `derive_relationships` and
`tests/test_relationships_schema.py`; the latter's 3 tests still pass
unchanged, and nothing else in the tree touches `town_relationships/`.

Full suite: 340 passed (335 on merged `main` + 4 T02 + 1 T03).

## 2026-08-31 — Samwise1 — T01: `town_state.current_date` collides with the SQLite `CURRENT_DATE` keyword

The plan's Task 1 names a `town_state` column `current_date`. `current_date`
(case-insensitive) is a SQLite built-in that returns today's date. Verified
behaviour with 3.14's bundled sqlite3:

- **Writes are fine.** In an INSERT column list and in `UPDATE ... SET
  current_date = ?`, `current_date` is parsed as the column — the row stores
  and updates the intended value.
- **Bare reads are silently wrong.** `SELECT ..., current_date, ... FROM
  town_state` evaluates `current_date` as the builtin and returns
  `date('now')` (today), not the column. `SELECT *` is fine.
- Quoting the identifier — `"current_date"` or `[current_date]` — makes a
  read resolve to the column.

Decision (kept minimal — no `CONTRACTS.md` interface change): the column
name stays `current_date` as the contract specifies; **every read of it must
quote the identifier.** T01's schema + tests do this and carry an inline
note. Downstream impact:

- **T02** (`test_generate_town_database_writes_town_state`, plan Step 5) —
  the plan's snippet reads `current_date` bare; quote it.
- **T07** (`advance_town`, plan line ~1382:
  `SELECT year_start, current_date, aggression, magic_prevalence FROM
  town_state`) — this feeds the simulation clock. Bare, it reads today's
  date and the whole year-advance loop is wrong while every test that only
  checks FK integrity / determinism still passes. Quote it. The plan's T07
  test assertions (`SELECT current_date FROM town_state`) need the same.

If a rename (`current_date` -> e.g. `current_sim_date`) is preferred instead —
loud "no such column" failures beat silent wrong values — that's a
`CONTRACTS.md` change and the owner's call; flagging in Director Notes.

## 2026-08-31 — Frodo — T05 (household formation): two bugs found in the plan's speculative reference code

`docs/superpowers/plans/2026-08-28-town-year-advance-implementation.md`'s
Task 5 code was never actually run before it was written into the plan —
found two real bugs implementing it (T04's Task 4 code, by contrast,
matched the current codebase exactly with no changes needed, so this
isn't true of every task, but T07 in particular flags a similar
suspected-drift risk and is worth double-checking the same way):

1. **Spouse pool excluded lone single adults.** The plan's
   `_eligible_movers` only returned a household's 3rd+ adult (by id).
   The plan's own test fixture sets up a household of size 1 explicitly
   as "a lone eligible adult... for resident 3 to pair with" — but a
   size-1 household never contributes anyone to that list, so
   `spouse_candidates` was always empty for that fixture and the
   pairing could never happen. Fixed by splitting into `movers` (who
   roll the formation-rate dice — unchanged, a household's 3rd+ adult)
   and a broader `spouse_pool` that also includes lone single adults
   (household size 1) as valid pairing targets, since they're unmarried
   by the same first-two-adults-are-the-couple convention.
2. **Hard-coded test seed never fires.** The plan's tests use
   `seed=("town", 1)` and assert a specific fire/no-fire outcome, but
   `rng_for(("town", 1), "db", "household_formation").random()` is
   `~0.369`, well above `HOUSEHOLD_FORMATION_RATE` (0.15) — so the
   "moves out when matched" test could never have passed as written,
   and "no vacant housing" was accidentally passing for the wrong
   reason (the roll never fired, rather than firing-but-blocked-by-
   housing). Swapped to `("town", 15)`, whose first draw is `~0.0074`
   and reliably fires, verified directly rather than via trial and
   error in the test runner.

If you're implementing a task from this plan and its code doesn't
behave as written, check whether it's actually correct before assuming
your own code is wrong — this plan was written speculatively.

## 2026-08-31 — Frodo — Samwise Team mode scaffolded for town year-advance work

Set up `TASKS.md`/`CONTRACTS.md`/`LOG.md`/`CLAUDE.md` in Team mode, roster:
Frodo (owner, Effe96) + Samwise1 (lupalbert). All 8 tasks from
`docs/superpowers/plans/2026-08-28-town-year-advance-implementation.md`
assigned across two dependency-respecting streams (T01–T03 Stream A /
Samwise1, T04–T06 Stream B / Frodo; T07/T08 downstream of both, see
`TASKS.md` for the exact blocking order). Repo was made private and
Samwise1 invited before this pass. No code written yet — the plan's own
task sections are the spec for each task's implementation.
