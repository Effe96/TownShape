# For the social-sim agent: what TownShape now provides, and what to do next

> Written 2026-10-11 from the TownShape side, in answer to
> `social-sim-demo/docs/townshape-brief.md`. Everything below is on TownShape
> branch `sim-integration` (built on `town-construction`); use that branch,
> or `main` once both are merged. Interfaces are listed in TownShape's
> `CONTRACTS.md` under "Consumed by the social sim".

## What TownShape built (brief items 1-5)

1. **Tables.** Every new town has, empty: `resident_traits`,
   `household_economy`, `house_tenure`, `departures`, `sim_state`, the nullable
   columns `town_state.loyalty/religiosity/strictness`, and on `relationships`
   `time, intimacy, services, valence_a_to_b, valence_b_to_a, former_type`.
   Exactly the brief's definitions (`town_db/schema.py`, `SIM_SCHEMA_SQL`,
   `SIM_COLUMNS`).
   - **Older towns** (e.g. `demo_riverport_town.db`): call
     `town_db.schema.ensure_sim_schema(conn)` once. It's idempotent: it adds
     only what's missing.
   - The `relationships` columns appear whenever `derive_relationships`
     creates the table.
2. **Open values.** No schema constraint on causes of death, occupations or
   relationship types; the viewer shows any value as stored.
   `deaths.reported_by_building_id` and `residents.home_building_id` accept
   NULL. The viewer shows a death (date, cause), a departure (date, reason),
   and "homeless" for a living resident with no home. A resident with a
   `departures` row is no longer listed in their old house.
3. **Capacity.** A freshly generated town has every house within
   `buildings.capacity`.
4. **Names.** `town_db.names.name_new_resident(seed, resident_id, race,
   gender, family_name=None) -> (first_name, last_name)`, drawn with
   `rng_for(seed, "name", resident_id)`. The race must be one of
   `town_db.names.RACES` (`human, dwarf, elf, gnome, halfling, orc`); any
   other raises `ValueError`.
5. **Placing a building.** `town_db.construction.place_building(db_path,
   seed, building_type, capacity, preferred_district_id=None) ->
   Optional[int]`.

## Where it differs from the brief: please read

- **Call order is now enforced.** Once `sim_state` has **any** row,
  TownShape's `advance_town` and `derive_relationships` raise
  `town_db.schema.SimOwnedTownError`. So `create_town` must be:
  1. `generate_town_from_parameters(params, db_path)`;
  2. `derive_relationships(db_path)`;
  3. your setup, which writes `sim_state` **last**, or at least after
     step 2.

  `town_db.schema.sim_has_run(conn)` tells you whether a town is already
  sim-owned.
- **Capacity is fitted, not enforced by limiting births.** Generation fills
  houses exactly to capacity, then simulates its first year. Refusing births
  into full houses would have meant zero births, so instead generation ends
  by raising an over-full house's `capacity` to its living occupants (your
  own rule: a house's room is who lived there at import). Expect some
  residences at 7-9 instead of the default 6.
- **`place_building` details:**
  - `building_type` must be a TownShape building type (a key of
    `town_shaper.buildings.JOB_VACANCIES_BY_BUILDING_TYPE`): use `residence`
    for houses and `workshop` for any craft workshop. Keep the craft itself
    (dyer, fuller...) on your side, e.g. in `sim_state`; an unknown type
    raises `ValueError`.
  - `capacity` is stored as given (pass 8 for your houses; workshops
    usually 0).
  - Placement:
    - First choice is a free gap **inside the walls**: in the preferred
      district if one fits, else the nearest lived-in ward. Plazas, parks,
      civic land and fields are never used.
    - Settlemaker packs its wards, so only a handful of gaps exist (about
      6 in an 830-person town). After that it grows the town outward along
      the roads and side streets toward the preferred district, so new
      houses can land outside the walls.
    - `None` means no room anywhere (rare).
  - The new building gets a `district_id` and `zone_type`; read them back
    from `buildings` if you need its neighbourhood.
  - **It also draws the building into the town's SVG** (the `.svg` next to
    the `.db`), in settlemaker's style, so it appears on the map itself, not
    just as an outline. That answers the brief's open question.
  - About 0.2 s a call on an 830-person town. It reads and rewrites the
    SVG every call; if you build many houses a year and this becomes slow,
    ask for a batch version.
  - Seeded by `seed` plus the new building id, and every call is logged in
    the `construction_edits` table.

## What to do next on the sim side

1. **Build `create_town(parameters, path)`** in the order above.
2. **Load and save** (integration doc 2.1, 2.4). Write your state into the
   brief's tables; set `households.wealth` to cash plus property after a
   run. For people who leave alive, add a `departures` row and leave
   `death_date` NULL.
3. **When you build:** call `place_building` and store the returned id
   (`house_tenure.building_id`, workplaces). Re-derive neighbours from the
   new building's position. On `None`, keep the household where it is.
4. **When you create a person:** take the id as max + 1, call
   `name_new_resident` with it (newborns pass the household's
   `family_name`), and insert the `residents` row.
5. **End-to-end check**, then report back to the owner:
   - generate a small town, run your setup and one year that builds houses,
     and open it in TownShape's viewer:
     `python scripts/serve_town_viewer.py <db_path> [--port PORT]`;
   - confirm deaths, departures, the homeless and new houses show up
     correctly.

   Anything wrong or missing on TownShape's side: write it down for the
   owner to pass on.

## Not built (ask if you need it)

- Farmsteads at the town edge for new farms (integration doc 3.3).
- A cap on neighbour ties in large towns (integration doc section 4).
- A batch `place_buildings`.
