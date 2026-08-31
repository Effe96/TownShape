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
