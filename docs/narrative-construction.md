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

### `add_buildings(db_path, count, where="roads", building_type="residence", near=None)`

CLI: `python scripts/add_buildings.py <db> <count> [--where roads|perimeter] [--type residence] [--near PLACE]`

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

`near` builds as close as possible to a named place instead of the town
centre. It accepts a building id; a building name ("The Rusty Anvil") or
type ("temple"), case-insensitive; `"<compass direction> gate"` ("north
gate", "southwest gate" -- the gate within 60° of that bearing);
`"river"`, `"coast"`/`"sea"`, `"harbour"`, `"water"`; or a landscape glyph,
`"mill"`/`"windmill"`, `"well"`, `"market cross"`. Several matches -> the
one nearest the town centre (pass an id to pick a specific one). Lanes
opened for it steer toward the place, so a place no road reaches gets a
track out to it with the houses at its end. Construction still never goes
inside the built-up area: "near the temple" in the old town means the
nearest free land outside it. Unknown place -> `ValueError` listing what's
accepted.

`building_type` is any key of `town_shaper.buildings.JOB_VACANCIES_BY_BUILDING_TYPE`
(`residence`, `workshop`, `tavern`, `farmstead`, ...).

### Editing an existing building

CLI: `python scripts/edit_building.py <db> demolish|resize|reshape ...` (see
its usage line). Find the building id first (the viewer shows it when you
click a building; or query `buildings` by `building_type`/`name`).

- `demolish_building(db, id, ruin=False)` — `ruin=False`: cleared off the
  map (type `demolished`, its land free for new construction).
  `ruin=True`: left standing as a ruin, drawn faded with a broken outline,
  type `ruin`, renamed "Ruins of …". Either way the row stays and capacity
  becomes 0 — residents/workers still pointing at it are the people layer's
  to re-home.
- `resize_building(db, id, area_factor, absorb_neighbors=False)` — grow
  (`> 1`) or shrink (`< 1`) about its centre, keeping its shape. Growth stays
  in its district, off roads/walls/water, and stops at neighbours: in a
  packed block a 2× request may only reach ~1.1×. `absorb_neighbors=True`
  builds across the whole lot of every same-district neighbour it overlaps
  (they're demolished), so the result can exceed the request. Returns
  `{"building_id", "absorbed", "area_factor_achieved"}` — report the
  achieved size back rather than assuming the request was met.
- `reshape_building(db, id, "rectangle"|"square"|"round", area_factor=1.0,
  absorb_neighbors=False)` — rebuild with that footprint, same centre,
  aligned with its long side; clipped like resize (a round tower in a packed
  block comes out flattened where it meets neighbours).

## Narrative language → call

| Narrative | Call |
|---|---|
| "a few new houses have gone up outside the gates" | `add_buildings(db, 5-15, "roads")` |
| "the town is spilling out along the roads" | `add_buildings(db, 30-60, "roads")` |
| "a new suburb / faubourg has grown up outside the walls" | `roads` pass, then one or more `perimeter` passes |
| "new lanes of houses are eating into the farmland" | `add_buildings(db, N, "perimeter")` |
| "a tavern opened by the north gate" | `add_buildings(db, 1, building_type="tavern", near="north gate")` |
| "cottages went up out by the mill" | `add_buildings(db, 6-12, "perimeter", near="mill")` |
| "fishermen's huts along the river" | `add_buildings(db, N, "perimeter", near="river")` |
| "the tavern burned down" | `demolish_building(db, tavern_id, ruin=True)` |
| "they pulled the old house down" | `demolish_building(db, house_id)` |
| "the temple was enlarged" | `resize_building(db, temple_id, 1.5–2)`; if it's boxed in and the story allows, `absorb_neighbors=True` |
| "the lord rebuilt his hall as a round tower" | `reshape_building(db, hall_id, "round")` |

Count guide: a settlemaker house holds ~6 people (`BUILDING_HOME_CAPACITY`),
so "room for ~120 newcomers" ≈ 20 residences.

## Not yet supported

Moving a building, and the generation-time layout changes settlemaker can't express yet (castle
size/shape, star-shaped walls, symmetry). A cathedral is one `temple` building
drawn as several pieces: resizing keeps its pieces and cloister courtyard
(each piece scaled with the whole); reshaping redraws it as one outline.
