# For the social sim: saving `town_events` (2026-10-13)

> From TownShape's side, in reply to `social-sim-demo/docs/townshape-brief-events-2026-10-13.md`.
> The owner passes this on. The sim's code is yours to change; nothing here
> has been changed in the sim repo.

## What TownShape built (commit `6746474`, on `main`)

```
town_events
  id                  INTEGER PRIMARY KEY
  event_date          TEXT NOT NULL   -- same format as deaths.death_date
  kind                TEXT NOT NULL   -- open list, no CHECK
  building_id         INTEGER NULL REFERENCES buildings(id)
  district_id         INTEGER NULL REFERENCES districts(id)
  actor_resident_id   INTEGER NULL REFERENCES residents(id)
  target_resident_id  INTEGER NULL REFERENCES residents(id)
  detail              TEXT NULL
```

- It's your suggested shape, unchanged except that `event_date` and `kind` are NOT NULL.
- It's in `town_db.schema.SIM_SCHEMA_SQL`, so `ensure_sim_schema(conn)` (which
  your save already calls) creates it in older towns.
- It's in TownShape's `CONTRACTS.md`, next to the other tables the sim writes.
  TownShape only reads it.
- `skirmish_events` stays separate. It's TownShape's own history, written by
  `advance_town`, which the sim locks out.
- Foreign keys are on in your save, so every building, district and resident
  ID you write must exist. A building TownShape didn't place (id below zero)
  should be written as NULL, the same as `_placed()` does for homes.
- Where the viewer marks an event: on its building when `building_id` is set,
  on its district (tinted) when only `district_id` is set. Rows with neither
  are listed nowhere on the map.

## What the sim needs to do

What we found reading the sim at `51ea294`; the choices are yours:

1. **Keep events between runs.** `Town.run` gets `result.events` and drops
   them, and nothing in the snapshot holds them. "Delete and rewrite on every
   save" needs the whole history in hand, e.g. a list on `Town` kept in the
   pickled snapshot (`load_town` reading it back, empty for older snapshots).
2. **Write the table in `Town.save`**, as with `departures`:
   `DELETE FROM town_events`, then one row each, with the date from `on_day(day)`.
3. **Map kinds.** The brief's kinds are `killing`, `hired_assassination`,
   `group_killing`, `theft`, `riot`. The sim's events are `violence`,
   `hired_assassination`, `group_violence`, `theft`, `riot`. Whichever names
   you choose, the viewer shows them as stored. Unknown kinds draw grey.
4. **Gaps in the events themselves:**
   - `group_violence`'s `Event` has no `place`, though the brief says killings
     happen at a building. `crime_place(graph, edge, victim)` with the
     ringleader's tie would match the other killings.
   - The `riot` event names its district only in its detail text. The district
     is in `_active_riot["district"]`, but `Event` has no field for it.
5. **Detail.** The brief wants a theft's detail to say whether it was noticed.
   A noticed theft is followed by a `caught` event the same day, with victim
   and thief swapped. A caught killer gives `killer_hanged`/`killer_banished`
   with the victim as `resident_b`, so a killing's detail can say that too.
6. **Actor and target.** Residents as in the `Event`. For a riot,
   `participants[0]` is bookkeeping only, so NULL may be the better choice.

## Checking it

- One year of an 800-person TownShape town (with a draft of the above) gave
  about 66 thefts and 3 killings a year, all within the foreign keys.
- To view: `python scripts/serve_town_viewer.py <town.db>` from TownShape.
  A building's panel lists its events newest first. The legend's **Events**
  block toggles kinds and filters by year.
