# Creative-Mode Editing (Capability 3, First Slice) — Design

## Context

The roadmap (`Agent_Control_Doc.md`) names three capabilities for the
narrative-D&D tool built on top of Town Shaper (A) and Town DB (B):
capability 1 (narrative-to-parameters generation, done) and two not yet
started — capability 2 (safe-mode simulation) and capability 3
("creative-mode narrative editing": the author asserts a story fact
mid-session and the agent retroactively backfills consistent world
state without breaking what already exists).

This surfaced from the private `shop-mystery-game` project (a SQL
practice game built on top of TownShape, kept out of this repo — see
its own `docs/design.md`). Building that game's scenario 2 ("the shop's
staff member died") required *selecting* an already-generated town
where a suitable death happened to occur naturally, retrying generation
with new seeds until one did. That's backwards: the actual need is to
directly assert "this resident is dead, on this date" against a town
that already exists, and have the town's other data stay consistent
with that fact — without regenerating anything. That is exactly
capability 3, scoped down to its most concrete, immediately useful
form.

## Scope

**In scope**: direct, on-demand mutation of entities that already exist
in an already-generated `town_db` database, with automatic downstream
consistency. Three primitives:

1. `kill_resident` — mark a resident dead on a chosen date, with a
   cause.
2. `mark_resident_ill` — mark a resident as having had an illness
   episode (with a start and end date — the resident may or may not
   recover; a fatal case is expressed by *also* calling
   `kill_resident`, not by `mark_resident_ill` alone).
3. `scope_disease_event` / `create_disease_event` — retag or create a
   `disease_events` row's `affected_zone_type`, since TownShape's own
   generator (`town_db/vital_records.py`) always writes `NULL`
   (town-wide) and never actually scopes an outbreak to a district.

**Out of scope for this slice** (explicitly deferred, not forgotten):

- Backfilling **new** entities from a narrative fact (e.g. "the tavern
  owner has ten kids", which needs new residents/households/history
  created and woven in) — the harder half of the original capability-3
  vision. This slice only edits entities that already exist.
- A zone-wide cascade when scoping a disease event to a district (see
  "Flagged decision 1" below) — deliberately deferred, not silently
  dropped.
- Automatic replacement-staffing when a shop's primary occupant dies
  (see "Flagged decision 2" below) — same deal.
- Any live/forward-simulating behavior. This remains post-hoc editing
  of a static, already-complete simulated year, same as generation
  itself — capability 2 (safe-mode simulation, town evolving on its
  own over time) is a separate, later concern.

## Why cascades are hand-authored, not a re-run of the real generators

The obvious-sounding alternative — after killing a resident, just
re-invoke `town_db.purchases.generate_purchases` etc. for the affected
slice — does not actually work. Every domain generator
(`purchases.py`, `taxes.py`, ...) draws from a single sequential RNG
stream per domain (e.g. `rng_for(seed, "db", "purchases")`), consumed
household-by-household, week-by-week, in a fixed loop. Removing one
household's buyer from that sequence shifts every subsequent random
draw for every *other* household from that point on. A "narrow re-run"
would silently rewrite unrelated households' purchases too — worse
than not touching them.

Making a literal re-run surgically correct would require refactoring
every domain generator's RNG to be keyed per-entity
(e.g. `rng_for(seed, "purchases", household_id, week)` instead of one
draw-in-order stream) — a real, invasive change to already-merged,
tested generation code, for a form of fidelity ("byte-identical to what
generation would have produced if it had known upfront") this feature
does not actually need.

Instead, each mutation primitive applies a small, fixed, hand-authored
set of per-table consistency rules, touching only the affected
entity's own rows, using its own dedicated seeded RNG for any choice it
needs to make (e.g. which household member absorbs a reassigned
purchase). This is not a claim of "what the original generator would
have produced" — it is a separate, principled consistency layer on top
of already-generated data.

## Schema addition

```sql
CREATE TABLE illnesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    disease_event_id INTEGER REFERENCES disease_events(id),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    severity REAL NOT NULL
);
```

Added to `town_db/schema.py`'s `SCHEMA_SQL`, so every newly generated
town has this table from now on (empty unless creative-mode editing is
used against it) — unlike `shop-mystery-game`'s private `opened_date`
column, which is bolted on after the fact via `ALTER TABLE` because it
lives outside this repo. Mirrors the existing `disease_events`/
`skirmish_events` pattern (a dedicated events table, not a status flag
on `residents`) so a resident can have more than one illness episode
over time, and each can optionally trace back to a real
`disease_events` row.

## Module and API

New module `town_db/edits.py` — placed in `town_db`, not
`town_narrative`, because every cascade rule operates purely on tables
`town_db` already owns (`purchases`, `tax_payments`, `military_service`,
`school_enrollments`, `deaths`, `illnesses`) and has no dependency on
`town_shaper` or narrative parameters, the same reasoning that put
`town_relationships` outside `town_narrative`. If capability 3 later
grows into full entity-backfill (out of scope here), that may justify
its own top-level package at that point — not decided now.

```python
def kill_resident(
    db_path: str, resident_id: int, death_date: date, cause: str,
    disease_event_id: Optional[int] = None,
    skirmish_event_id: Optional[int] = None,
) -> None: ...

def mark_resident_ill(
    db_path: str, resident_id: int, start_date: date, end_date: date,
    severity: float, disease_event_id: Optional[int] = None,
) -> None: ...

def scope_disease_event(db_path: str, event_id: int, zone_type: str) -> None: ...

def create_disease_event(
    db_path: str, zone_type: str, start_date: date, end_date: date, severity: float,
) -> int: ...  # returns the new disease_events id
```

### `kill_resident` cascade

1. `residents.death_date` set; a `deaths` row inserted (`cause`,
   optional `disease_event_id`/`skirmish_event_id`,
   `reported_by_building_id` resolved the same way generation does —
   the town's temple if one exists, else its healer, else `None` if
   neither exists; not proximity-based).
2. **Purchases**: every `purchases` row where this resident is the
   buyer and `purchase_date >= death_date` is reassigned to another
   living adult in the same household (seeded random pick among
   residents sharing `household_id` with `death_date IS NULL` as of
   that date) if one exists, else deleted. Reassignment (not deletion)
   is deliberate — the household's demand for bread doesn't vanish
   just because this particular buyer is gone.
3. **Tax payments**: every `tax_payments` row for this resident with
   `payment_date >= death_date` deleted (an individual obligation, not
   household demand — no reassignment).
4. **Military/school records**: any `military_service` or
   `school_enrollments` row for this resident with `end_date IS NULL`
   gets `end_date = death_date`.
5. **Workplace**: `workplace_building_id` set to `NULL`. See "Flagged
   decision 2" for what happens to the vacancy itself.

### `mark_resident_ill` cascade

1. Inserts the `illnesses` row.
2. Every `purchases` row where this resident is the buyer, inside
   `[start_date, end_date)`, is reassigned to another living household
   adult (same mechanism as death) or deleted if none exists. Nothing
   else changes — behavior resumes normally after `end_date`, no
   `residents` row is touched, since illness alone is not death.

### `scope_disease_event` / `create_disease_event`

Sets/creates the row only. See "Flagged decision 1" for why no
automatic per-resident/per-building cascade ships in this slice.

## Flagged decisions (realism vs. cost — not decided in this doc)

Per standing project guidance: the most realistic option is named
alongside the recommended default in every case where they diverge, so
the choice is made deliberately rather than defaulted into silently.

**Decision 1 — does `scope_disease_event` cascade to the whole zone?**
- *Recommended default (this slice)*: no automatic cascade. Only the
  specific entity you separately edit (e.g. one shop, via a `kill_` or
  `mark_ill` call) is affected. Cheap, bounded, matches what
  `shop-mystery-game`'s scenario 3 actually needed.
- *More realistic alternative*: scoping a disease event to a zone
  automatically suppresses purchases and elevates death risk for
  *every* resident and building in that zone — a real outbreak doesn't
  confine itself to whichever one shop is being investigated. Real
  cost: a district can hold hundreds of buildings/thousands of
  residents, so this touches far more rows, needs its own retry/
  consistency handling, and its runtime scales with zone population.

**Decision 2 — does a dead shop-owner's position get filled?**
- *Recommended default (this slice)*: the workplace is simply vacated
  (`workplace_building_id = NULL`). The shop has no active primary
  staffer until something else fills it.
- *More realistic alternative*: `kill_resident` gains an optional
  `promote_replacement=True` behavior — if the deceased was a shop's
  primary occupant (e.g. `blacksmith`, `mage`) and a same-workplace
  apprentice exists, the senior remaining apprentice is promoted into
  the primary occupation, and the purchase cascade becomes partial
  falloff (reduced trade, reflecting reduced skill/reputation) instead
  of a full loss. More realistic and narratively richer, but adds a
  second cascade shape (partial vs. total) and a decision about who
  counts as "senior" among apprentices (no seniority/hire-date concept
  exists in `town_db` today — would need one, even if just "lowest
  resident id" as a proxy).

Both are left as **not implemented, not decided** in this first slice;
this spec's plan should treat them as explicit optional follow-on
tasks the user can choose to include or skip.

## Testing

Per project convention (see prior D1b geometry work), randomized
cascade logic gets tested across multiple seeds, not one fixture — a
single lucky/unlucky seed has previously hidden real bugs in this
project. For each primitive:

- FK integrity (`PRAGMA foreign_key_check`) holds after the cascade.
- The core fact lands correctly (`death_date`/`deaths` row;
  `illnesses` row; `disease_events.affected_zone_type`).
- Purchases/tax/military/school cascades touch only rows for the
  affected date range and resident/household — a broad seed sweep
  asserting no *other* resident's rows changed.
- Reassignment-vs-deletion branches: a synthetic household with >1
  living adult exercises reassignment; a synthetic household with
  exactly 1 living adult exercises deletion.
- Idempotency/error cases: killing an already-dead resident, illness
  windows that overlap an existing illness, a `disease_event_id` that
  doesn't exist.

## Out of scope, restated

New-entity backfill, zone-wide cascades (Decision 1), replacement
staffing (Decision 2), and any live/forward simulation remain out of
scope for this slice unless the user opts into Decision 1/2's
realistic alternative during planning.
