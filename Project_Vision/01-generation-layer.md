# Generation Layer

### Procedural spatial layout — districts, water, and building footprints. Lives in `town_shaper/` (orchestration, water, households, name/job tables, resident assignment) and `settlemaker_bridge/` (the actual geometry engine). The part of the codebase responsible for *where everything is*, before any resident or history exists.

**2026-09-09 — replaced, not just refactored.** Everything below used to be
a hand-built Voronoi/block-cutting pipeline (`town_shaper/anchors.py`,
`districts.py`, `blocks.py`, `roads.py`, `countryside.py` — all now
deleted, ~2,800 lines). It's now a thin Python parser
(`settlemaker_bridge/parse_geojson.py`) over the real output of
[`settlemaker`](https://github.com/barrulus/settlemaker), an external
Node library invoked as a subprocess. See `docs/superpowers/specs/`
and `docs/superpowers/plans/`'s `2026-09-08-settlemaker-integration*`
files for the full design/rollout history (P001 in `00-proposals.md`
is the proposal that started this). **License note:** `settlemaker` is
GPL-3.0-only, itself a TypeScript reimplementation of watabou (Oleg
Dolya)'s `TownGeneratorOS`/Medieval Fantasy City Generator — the same
GPL-3.0 project this file used to cite as a *technique-only* reference
before the port. TownShape invokes it as a separate subprocess (JSON
over stdin/stdout, pinned to an exact commit SHA in
`settlemaker_bridge/package.json`) rather than linking or copying its
source, so TownShape's own license is unaffected — see the README's
Acknowledgments section for the full chain of credit.

## Current State

### The bridge

`town_shaper.generate.generate_town()` builds `TownParameters`-derived
water features locally (unchanged — see Water below), then calls
`settlemaker_bridge.pipeline.generate_via_settlemaker(seed,
target_population, ...)`, which shells out to settlemaker's
`generateSettlement` via a small Node wrapper (`settlemaker_bridge/
generate.mjs`) and gets back GeoJSON + settlemaker's own themed SVG.
`settlemaker_bridge/parse_geojson.py` turns that GeoJSON into the same
`District`/`Building` dataclasses (`town_shaper/models.py`) every
downstream package (`town_db`, `town_relationships`, `town_narrative`)
already consumed before the migration — no schema or downstream-API
change. `Town.svg` is new: settlemaker's SVG is persisted verbatim
alongside the SQLite database (see the visualization layer doc).

Two real engines exist behind that one call, chosen by settlemaker
itself off `target_population` against its own hardcoded
`VILLAGE_POP_CEILING` (1000) — TownShape doesn't choose:

- **≥1000 — the "burg" engine.** Ward-subdivided (`ward` GeoJSON layer,
  mapped to `ZoneType` via `WARD_TYPE_TO_ZONE_TYPE` — administration/
  cathedral/military/park → civic, merchant/market → merchant, slum/
  craftsmen → poor_residential, patriciate → rich_residential, harbour/
  gate → port, farm → farmland_edge; `castle` → civic with `garrison`
  buildings since 2026-10-09 — see Parser fixes below).
  Buildings carry a `poi.kind` (inn, smithy, shop, guardhouse, ...)
  mapped to TownShape's own `building_type` vocabulary
  (`POI_KIND_TO_BUILDING_TYPE`) when one exists, falling back to a
  plain zone-appropriate infill type (`residence`, `manor`, `workshop`,
  `farmstead`) otherwise.
- **<1000 — the "village" engine.** A structurally different generator
  with no ward layer at all — added to the parser 2026-09-09, after an
  earlier gap where calls in this range silently returned an empty
  town. Every building is a generic house (capacity from the feature's
  own `occupancy`, not a fixed constant); the only POI kinds it can
  ever emit are `well`/`stone-circle`/`boathouse` (verified against
  settlemaker's own `village/types.d.ts`) — **a village can never
  contain a shop, tavern, temple, or any job-bearing building.**
  Parsed into one synthesized `POOR_RESIDENTIAL` district covering the
  whole settlement.

### Water

Unchanged in spirit, still `town_shaper/water.py` (`generate_water_features`,
Chaikin-smoothed centerlines buffered into strips, real polygons-with-holes).
What changed: these polygons are computed in TownShape's own coordinate
frame first, then rescaled into settlemaker's local frame (a per-town,
non-constant meters-per-unit ratio settlemaker only reports *after* one
throwaway call — see `pipeline.py`'s module docstring for why this costs
two subprocess calls per watered town) before being handed to settlemaker
as `coastlineGeometry`, so settlemaker's own patch classifier keeps
buildings off the same water TownShape persists.

### Districts, blocks, roads, countryside

Gone as TownShape concepts. Settlemaker owns ward layout, block/lot
subdivision, building placement, and wall/tower/gate geometry entirely.
`town_shaper/roads.py` is deleted; `Town.road_network` is always an
empty `RoadNetwork()` now (never `None`, never populated) — settlemaker's
own `street` GeoJSON layer isn't mapped onto TownShape's `RoadNode`/
`RoadEdge` models, so the `road_nodes`/`road_edges` tables are empty at
generation (since 2026-10-09 they only ever hold side streets added by
`town_db/construction.py`, `road_type='street'`). (`town_viewer/`'s road-drawing code still reads those tables —
harmless, since they're empty, but it's dead weight now; see the
visualization layer doc.)

### Layout knobs for random towns (2026-10-09)

`TownParameters` gained `river_bearings` (river i flows in from that compass
bearing and leaves opposite, crossing near the centre, meandering half as
much as a random river), `has_citadel` (settlemaker's castle ward; parsed as
civic land with `garrison` buildings), and `road_bearings` (settlemaker puts
a gate within a few degrees of each; the road's course outside the walls
still follows field edges). Recorded in `generation_parameters`. Mapped from
narrative in `docs/narrative-town-parameters.md`.

### Parser fixes (2026-10-09/10)

- `castle` wards (reachable via `has_citadel`) → civic + `garrison` (the old
  "raises loudly" item below is resolved).
- Park lawns are settlemaker "buildings" with stray `shop` POIs pinned on
  some — POIs on park wards are now ignored (lawns stay `garden`).
- A cathedral ward (~5-15 pieces, one typed `temple`, the rest `workshop`)
  now merges into **one** `temple` building whose footprint is the union.
- Towns generated before these fixes keep the old typing until regenerated.

### Construction edits on an existing town (2026-10-09/10)

`town_db/construction.py` (+ `scripts/add_buildings.py`,
`scripts/edit_building.py`, agent guide `docs/narrative-construction.md`):
physical-layer-only edits, decoupled from residents/`advance_town` (the
*why* of growth belongs to a separate project of the owner's).

- `add_buildings(count, where="roads"|"perimeter", building_type, near=)`:
  ribbon houses along approach roads (capped at 1.6 town radii), overflow on
  wandering side streets that branch through reserved lane gaps and join
  other roads (deliberately irregular — straight perpendicular lanes read as
  "modern American"); near-terraced frontage with gable-end plots; taverns/
  shops at the most central road lot; `near` = building id/name/type,
  "<compass> gate", water, or a glyph ("mill"), with lanes steering toward it.
- Fields new construction cuts into are trimmed (cut part → new
  `poor_residential` district) or converted if mostly lost; lost field area
  is re-sown outside the farmland belt, widening the SVG frame/`town_state`
  bounds when needed.
- `demolish_building` (cleared or `ruin`), `resize_building`,
  `reshape_building`; rows of demolished buildings are kept (capacity 0).
- Settlemaker's roads/walls/glyphs exist only in the SVG, so they're parsed
  from it; new geometry is appended to settlemaker's own SVG groups;
  settlemaker buildings are matched to their drawn shape(s) by geometry.
  Every edit is logged in `construction_edits`.

### Determinism

Still holds, on both sides of the boundary: TownShape's own water-feature
generation still flows through `rng_for(seed, *path_parts)`; settlemaker
gets a plain numeric seed derived via `town_shaper.seeding.derive_seed`,
and the bridge's own integration test
(`tests/test_settlemaker_bridge_integration.py`) asserts byte-identical
output (buildings and SVG both) for two calls with the same seed.

### Generation speed

Roughly **100x faster** than the deleted pipeline — settlemaker resolves
in ~150ms per call versus the old pipeline's 13-16s at population 3000
(measured during the original spike, P001 in `00-proposals.md`).
Resolves the "Generation time is growing with visual quality" item that
used to live in Feedback below.

## Feedback & Future Ideas

### Duplicate tavern (and other) building names within one town

**Status:** Open (still applies — the mechanism moved, not the gap)

`BUILDING_NAME_POOLS["tavern"]` (`town_shaper/buildings.py`) still has
only 4 names, still drawn via `rng.choice(name_pool)` with replacement —
now from `settlemaker_bridge/parse_geojson.py`'s `_building_name` instead
of the deleted `blocks.py`. A town with more than a handful of taverns
still produces duplicates as a structural certainty. Candidates
unchanged: a bigger name pool, sampling without replacement with a
disambiguating-suffix fallback, or folding it into whatever future
population-scaled-cap work touches this table next.

### Village-scale towns have no economy and can't grow

**Status:** Open — a real product question, not decided here

Confirmed structural, not a bug: the village engine can never emit a
job-bearing building (see Current State above), so a village-scale town
has zero purchases, zero wealth change, and zero workplace assignment,
ever. Separately, its housing capacity is sized by settlemaker to almost
exactly match `target_population` (measured: 802 capacity for 802
residents, zero vacant buildings) — `household_formation.py`'s
`_vacant_home_building()` can never find anywhere to move a new
household into, at any village-range population. Whether/how village
residents should get jobs, relationships, and narrative treatment the
way town residents do is an open design question, not an engineering
one.

### `castle` ward type remains unresolved

**Status:** Addressed 2026-10-09 — `has_citadel` made it reachable; mapped
to civic with `garrison` buildings (`settlemaker_bridge/parse_geojson.py`).


### The town's structure should follow the narrative (P002)

**Status:** Planned — `docs/superpowers/specs/2026-10-10-narrative-layout-engine-design.md`

The agent writes a *layout spec* (shapes, walls, water, roads, districts,
open spaces, landmarks with any footprint, symmetry) from the narrative;
TownShape builds that structure and settlemaker — in a fork with a
"structured" entry point — fills the rest in its own style; the agent reviews
a render and a fidelity report and revises. Phase 0 is a 2-3 day spike
proving settlemaker's wards can fill regions TownShape defines. Random towns
keep today's path. Awaiting owner decisions D1-D4 in the spec.

### Construction edits: known gaps

**Status:** Open

- Moving a building isn't supported.
- A cathedral reshaped to rectangle/square/round loses its inner pieces
  (resize keeps them).
- New houses sit on field-striping only where fields weren't trimmed;
  re-sown fields are Voronoi-shaped, a bit more angular than settlemaker's.
- `generate_town_from_parameters` doesn't derive relationships (the viewer
  copes since 2026-10-09, but the entry point could run that step).
- `demo_riverport_town.svg` is stale vs. its `.db` and needs regenerating.
