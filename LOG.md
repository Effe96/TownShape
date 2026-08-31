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
