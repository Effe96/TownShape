# Narrative → Construction Edits

How to turn narrative feedback about an *already-generated* town's physical
shape into construction edits. Written for any LLM agent. Physical layer
only: these edits change the `buildings` table and the town's `.svg`, never
residents or households. Whatever decides *why* a town needs new buildings
(a story beat, an external simulation) calls in here.

Every edit is appended to the town DB's `construction_edits` table
(operation, params, resulting building ids), so a town's physical history
is an ordered log on top of its seed. Edits are deterministic: same DB +
same call → same buildings.

## Operations

### `add_buildings(db_path, count, where="roads", building_type="residence")`

CLI: `python scripts/add_buildings.py <db> <count> [--where roads|perimeter] [--type residence]`

Builds up to `count` new buildings *outside* the existing built-up area
(every non-farmland district, the walls, and every building), on the town's
fields. Returns the new building ids; fewer than `count` means the map frame
ran out of room. House sizes are sampled from the town's own existing
buildings of that type, so new construction matches its grain.

- `where="roads"` — ribbon development: houses front the approach roads,
  nearest the gates first, up to ~1.6 town radii out; the rest goes onto
  side streets. The default; this is how real medieval towns grew.
- `where="perimeter"` — side streets only: new lanes branch off the roads
  (and off each other) through gaps the ribbons leave every 12–28 units,
  wander like old field tracks, and join other roads into a connected
  warren rather than dead-ending. Frontage is near-terraced with uneven
  setbacks, ~40% of houses gable-end to the street, thinning toward a
  lane's far end. Repeated calls extend the warren outward. Use after a
  `roads` pass to thicken ribbons into suburbs.
- Taverns, shops, workshops (capacity-0 types) ignore `where` and take the
  most central free lot on a road, i.e. by the gates.

Side effects, all automatic:
- New side streets are drawn into the SVG's road layer (read back as roads
  by every later edit) and stored in `road_nodes`/`road_edges`
  (`road_type='street'`).
- Fields new houses/streets cut into are trimmed back around them in soft
  curves; the cut-off part becomes a new `poor_residential` district. A
  field more than half lost is converted outright (district turns
  `poor_residential`, plot removed). The lost field area is re-sown as new
  plots just outside the farmland belt (new `farmland_edge` districts), and
  the map frame (SVG viewBox + `town_state` svg bounds) widens if needed.
- The edit's `construction_edits.params` records `streets`,
  `converted_district_ids`, `trimmed_district_ids`, `living_district_ids`
  and `new_field_district_ids`.

`building_type` is any key of `town_shaper.buildings.JOB_VACANCIES_BY_BUILDING_TYPE`
(`residence`, `workshop`, `tavern`, `farmstead`, ...).

## Narrative language → call

| Narrative | Call |
|---|---|
| "a few new houses have gone up outside the gates" | `add_buildings(db, 5-15, "roads")` |
| "the town is spilling out along the roads" | `add_buildings(db, 30-60, "roads")` |
| "a new suburb / faubourg has grown up outside the walls" | `roads` pass, then one or more `perimeter` passes |
| "new lanes of houses are eating into the farmland" | `add_buildings(db, N, "perimeter")` |
| "a tavern opened by the north road" | `add_buildings(db, 1, "roads", "tavern")` |

Count guide: a settlemaker house holds ~6 people (`BUILDING_HOME_CAPACITY`),
so "room for ~120 newcomers" ≈ 20 residences.

## Not yet supported

Reshaping or demolishing existing buildings, and generation-time layout
changes (river direction, citadel/castle shape, star-shaped walls,
symmetry). See `docs/narrative-gaps.md`.
