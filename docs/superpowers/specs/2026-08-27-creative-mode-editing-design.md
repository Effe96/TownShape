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
    promote_replacement: bool = False,
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
2. **Workplace and replacement staffing (resolved before the purchase
   cascade below, since it changes that cascade's ceiling)**: if
   `promote_replacement=True` and the deceased held a workplace's
   primary occupation (`blacksmith`, `mage` — the buildings' single
   capacity-1 role per `town_shaper/buildings.py`), the apprentice with
   the lowest `id` among residents sharing that `workplace_building_id`
   is promoted into the primary occupation (`occupation` updated
   directly; no seniority/hire-date field exists, so lowest id is used
   as a deterministic proxy). Otherwise, or if no apprentice exists,
   `workplace_building_id` is set to `NULL` and the position stays
   vacant.
3. **Purchases**: every `purchases` row where this resident is the
   buyer and `purchase_date >= death_date` is reassigned to another
   living adult in the same household (seeded random pick among
   residents sharing `household_id` with `death_date IS NULL` as of
   that date) if one exists, else deleted. Reassignment (not deletion)
   is deliberate — the household's demand for bread doesn't vanish
   just because this particular buyer is gone. **Separately**, if the
   deceased was a shop's primary occupant: purchases *at that shop*
   after the death date follow a reduced-ceiling redirect ramp if a
   replacement was promoted (partial falloff, reflecting reduced
   skill/reputation) or the existing full-redirect ramp if the position
   stayed vacant (total loss) — reusing scenario 2's ramp shape from
   `shop-mystery-game`, now as a first-class TownShape primitive
   instead of a private script.

   **Amended 2026-08-27, post-implementation review**: this ramp
   applies to every purchase at the shop, including ones made by the
   deceased's own household (the "buyer unrelated to the household"
   framing in an earlier draft of this line was aspirational, not
   implemented, and the final whole-branch review caught the mismatch).
   In practice this means a household purchase can be touched twice —
   once by the buyer-reassignment step above (which may move it to
   another household member), then again by this ramp (which may
   redirect or delete it regardless of buyer). Left as-is deliberately:
   the shop-level function has no household awareness today, adding it
   would be new complexity for a benign, arguably realistic outcome (a
   grieving household's own purchases at the family shop are just as
   exposed to the shop's decline as anyone else's), and no test or
   consumer currently depends on the old framing.
4. **Tax payments**: every `tax_payments` row for this resident with
   `payment_date >= death_date` deleted (an individual obligation, not
   household demand — no reassignment).
5. **Military/school records**: any `military_service` or
   `school_enrollments` row for this resident with `end_date IS NULL`
   gets `end_date = death_date`.

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

## Flagged decisions — resolved 2026-08-27

Per standing project guidance: the most realistic option is named
alongside the recommended default in every case where they diverge, so
the choice is made deliberately rather than defaulted into silently.
Both decisions below were raised and resolved before implementation:

**Decision 1 — does `scope_disease_event` cascade to the whole zone?**
**Resolved: no, deferred — out of scope for this slice.** The
realistic version (an outbreak suppressing purchases and elevating
death risk for every resident/building in a zone, not just the one
entity being edited) turned out to be the seed of a much larger
interest: a *general* mechanism for how an event's effects propagate
across many entities consistently, of which disease is only one
instance — natural disaster and war were named as other instances.
That is now its own separate, larger architectural project (tracked
outside this spec, likely superseding/absorbing the roadmap's
capability 2 "safe-mode simulation" rather than living under
capability 3), including its own visualization-layer needs. This
slice's `scope_disease_event`/`create_disease_event` ship with no
automatic cascade, unchanged from the original recommendation, so that
this slice can ship without waiting on that larger project.

**Decision 2 — does a dead shop-owner's position get filled?**
**Resolved: yes, included in this slice.** `kill_resident` gains the
optional `promote_replacement` behavior described above. Cheap
relative to Decision 1 — reuses the same redirect-ramp mechanism
already needed for the total-loss case, and every current building
type has only two occupation tiers, so there's no recursive-vacancy
concern.

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
- `promote_replacement`: both branches — an apprentice exists (promoted,
  partial-falloff ramp applies) and none exists (vacancy, full-redirect
  ramp applies, same as `promote_replacement=False`).
- Idempotency/error cases: killing an already-dead resident, illness
  windows that overlap an existing illness, a `disease_event_id` that
  doesn't exist.

## Out of scope, restated

New-entity backfill, zone-wide cascades (Decision 1 — now tracked as
its own separate, larger project), and any live/forward simulation
remain out of scope for this slice. Replacement staffing (Decision 2)
is in scope, per the resolution above.
