# Organic Town Rendering — Design

## Context

`IDEAS.md`'s standing visualization feedback: the town map "does not
look like an organic city at all, it mostly looks like random thick
lines being thrown around," compared against
[watabou's Medieval Fantasy City Generator](https://watabou.itch.io/medieval-fantasy-city-generator)
and its published source, `TownGeneratorOS`. This was checked against a
throwaway mockup (built from a real generated town's district data,
compared side-by-side against today's actual render) before this spec
was written, per the user's standing instruction to mock up
visualization changes before writing real code — the mockup was
approved as the target look.

Reading `TownGeneratorOS` (`Model.hx`, `Ward.hx`, `Cutter.hx`) turned up
the actual mechanism responsible for the reference's organic look, which
this spec reproduces:

- **Streets inside the urban core are never drawn as a line layer.**
  `Ward.getCityBlock()` insets a district's own polygon inward by a
  street-width amount; the street is simply the negative space left
  between two neighboring insets. There's no separate line object that
  can visually cut across a building.
- **Buildings fully tile the inset block** via recursive polygon
  bisection, not a fixed-size lot placed with gaps around it.
- **Roads that do need to be drawn** (in the reference: outside the
  city walls) are graph shortest-paths along real boundary edges,
  smoothed afterward — never a straight line from an arbitrary center
  point through unrelated geometry.

TownShape's current implementation does the opposite of all three: its
`radial` road type (`town_shaper/roads.py`) draws a dead-straight line
from a single hub anchor to every other anchor in the town regardless
of what's between them — the literal source of "lines thrown around."
Its block/lot building placement (`town_shaper/blocks.py`, from
`2026-09-02-building-footprints.md`) places buildings in a frontage
strip around a block's perimeter, leaving the interior empty and gaps
between lots, rather than tiling.

**Scope-affecting finding surfaced during design:** naively tiling
every block's full interior would multiply building counts 2-4x over
today, which would make an already-logged problem worse, not better —
`docs/narrative-gaps.md` already documents a 10,000-population test
town producing 91 taverns and 202 shops from a name pool of 4 tavern
names, explicitly called out by the user as "not usable as a DM tool."
This spec therefore also introduces a population-scaled cap on how many
tiles become real named businesses (Scope, below) — full tiling is
still visual, but only a bounded subset of tiles carry a real
`building_type`/name/job-vacancy record.

## Scope

In scope:

- Replace `radial` road generation with graph shortest-paths along the
  existing district-boundary edge graph, smoothed into a curve, drawn
  only where they cross into a zone with no block-inset (i.e. reaching
  `farmland_edge`) — never drawn between two already block-inset urban
  districts, since that gap is already visually a street.
- Inset each urban district's own polygon before block subdivision, so
  gaps between *neighboring* districts read as streets without any
  drawn line.
- Replace `place_buildings_in_block`'s frontage-strip lot placement
  with recursive interior bisection so buildings fully tile the block.
- Cap how many tiles become real named/job-bearing buildings per
  `building_type`, population-scaled; the rest render as a generic,
  unnamed infill building.
- Update both renderers' road-style tables for the new/removed
  `road_type` values. (Building-drawing code in both renderers is
  unchanged — see Rendering.)

Out of scope (raised and explicitly deferred during design — see
`IDEAS.md` / `docs/visual-interface-ideas.md` for where each lives):

- Building-type icons in the viewer (`visual-interface-ideas.md`
  follow-up #4) — separate, viewer-only, shares no code with this spec.
- Schools not scaling in count with population
  (`narrative-gaps.md`) — opposite problem (needs more of a type, not
  fewer named ones), different zone, different fix.
- The public multi-town website / donjon-style hosting
  (`visual-interface-ideas.md` Open questions) — unrelated, much larger
  initiative; this spec doesn't block or inform it beyond making the
  map worth looking at.
- `farmland_edge` building placement — stays on today's Poisson-disc
  point placement, per the original building-footprints plan; only
  gets a fixed default footprint, as it already does.
- Per-edge variable street width (a plaza-adjacent edge insets more
  than an ordinary one, as in the reference). This spec uses a single
  uniform inset distance per district — it matched the approved mockup,
  and per-edge variation is a refinement to layer on later if the
  uniform version reads as monotonous in practice.

### Rejected alternative: shrink district/block target area instead of capping business counts

Considered making blocks smaller (lower `TARGET_BLOCK_AREA_BY_ZONE`) to
reduce building counts. Rejected: under full tiling, total building
count is `total zone area ÷ footprint area`, independent of how that
area is divided into blocks — more, smaller blocks covering the same
total area tile to the same total building count. The only real lever
on total building count is total zone area itself, which is
population-driven on purpose (the job market and purchase generation
need that much real shop capacity) — shrinking it to control visual
building count would shrink the town's actual economic capacity as a
side effect. Capping which tiles become *named* buildings, independent
of the total tile count, avoids that coupling entirely.

## Data Model

No schema changes. `buildings` already has `width`/`height`/`rotation`
(from `2026-09-02-building-footprints.md`); `road_nodes`/`road_edges`
keep their existing shape.

- `road_edges.road_type`: `"radial"` is removed; a new `"artery"` value
  replaces it, but only for the farmland-reaching last-mile segments
  described above (far fewer rows than today's one-radial-per-anchor).
  `"local"` is removed entirely — `subdivide_into_blocks` stops
  emitting `RoadNode`/`RoadEdge` rows for its internal splits (the gap
  it already creates in the block geometry is enough; drawing a line
  through it was always just to make that gap visible before buildings
  tiled up to its edge). `"boundary"` and `"spur"` are unchanged.
- `buildings`: the new generic infill building type (one new
  `building_type` string value per applicable zone, e.g. `"workshop"`
  for merchant — residential zones already have this role filled by
  `residence`/`manor`, which have no name pool and needed no change)
  gets ordinary rows: `capacity=0`, no job vacancies, `name=NULL`.
  Nothing downstream (job market, purchases, click-to-inspect) needs to
  special-case it — an empty-capacity building with no name already
  behaves correctly everywhere that reads `buildings` today.

## Algorithm

### `town_shaper/geometry.py` — one new helper

`inset_polygon(polygon: Polygon, distance: float) -> Polygon` — insets
every edge of `polygon` inward by `distance`, built from the existing
`clip_polygon_by_line` primitive: offset each edge's line inward along
its inward normal by `distance`, then clip the polygon against that
offset line in sequence (the same "clip against N edges in turn"
pattern `clip_polygon_to_bounds` already uses against a rectangle's 4
edges — this generalizes it to an arbitrary polygon's own edges instead
of a bounding rectangle). Pure refactor-adjacent addition; no existing
function's behavior changes.

### `town_shaper/roads.py` — arterial routing

Replace `_choose_hub_anchor` + straight `radial` edges with:

1. Build an undirected graph from the `boundary` edges already computed
   (junction-node-to-junction-node, one graph node per Voronoi ridge
   vertex plus the anchor nodes reachable via `spur` edges).
2. For each anchor, run a shortest path (`networkx`-free — plain BFS,
   the existing `boundary`/`spur` graph is small and unweighted is fine
   for this) to the hub anchor along that graph.
3. Smooth the resulting polyline with a simple corner-cutting pass
   (Chaikin's algorithm, 1-2 iterations — no new dependency, same
   spirit as `Model.smoothStreet`'s `smoothVertexEq` in the reference).
4. Walk the smoothed path and only emit `RoadNode`/`RoadEdge` rows
   (`road_type="artery"`) for the segment(s) that cross into a zone
   with no block-inset (`farmland_edge` today — determined by checking
   which district each path segment's endpoints fall in). Segments
   that run entirely between two already-inset urban districts are
   dropped; that gap is already a street by construction.

`boundary` and `spur` edge generation is unchanged.

### `town_shaper/blocks.py` — district inset and sub-block splitting

Before `generate_blocks_and_buildings` calls `subdivide_into_blocks` on
a district's polygon parts, inset each part via the new
`inset_polygon()` with a uniform `STREET_HALF_WIDTH` (matches the
mockup's value, `~2.0`) — this is what makes neighboring districts read
as separated by a street without any drawn line.

`subdivide_into_blocks`'s internal splitting logic (`_split_polygon`,
`_subdivide`) is unchanged — it already produces a real `LOCAL_STREET_WIDTH`
gap between the two halves of every split. It stops returning
`RoadNode`/`RoadEdge` lists (its return signature drops those two
elements); callers (`generate_blocks_and_buildings`, `generate_town`)
simplify accordingly — no more threading `next_local_node_id`/
`next_local_edge_id` or merging local nodes/edges into the road
network.

### `town_shaper/blocks.py` — building placement (the main rewrite)

Replace `place_buildings_in_block`'s frontage-strip-around-the-perimeter
placement with recursive interior bisection:

- Reuse the same longer-OBB-axis-cut-with-jitter approach
  `subdivide_into_blocks` already uses internally, applied to the block
  polygon itself rather than the district: cut along a line
  perpendicular to the block's longer axis, with a small party-wall gap
  (`~0.3-0.5`, enough to read as separate buildings, not a street —
  much smaller than `LOCAL_STREET_WIDTH`) instead of a street-width
  gap, and no node/edge output.
- Recurse until a piece's area is at or below
  `LOT_FRONTAGE_BY_ZONE[zone] × LOT_DEPTH_BY_ZONE[zone]` (same constants
  as today, now used as a target *leaf* size instead of a fixed lot
  footprint) — that leaf polygon becomes one building's footprint
  (`x`/`y` = its centroid, `width`/`height` from its own bounding
  rectangle, `rotation` from its longer axis — same derivation
  `place_buildings_in_block` already does today, just from a
  differently-produced polygon).
- Building-type/name/job-vacancy assignment (`resolve_building_type_weights`,
  `BUILDING_NAME_POOLS`, `JOB_VACANCIES_BY_BUILDING_TYPE`) is unchanged
  in mechanism — only gated by the new density cap below before being
  applied to a given leaf.

### `town_shaper/buildings.py` — business density cap

New module-level constants:

```python
NOTABLE_BUILDING_CAP_RATIO: Dict[str, float] = {
    "tavern": 1 / 1000,   # population ÷ 1000, per user guidance
}
DEFAULT_NOTABLE_BUILDING_CAP_RATIO = 1 / 2000  # any named type with no explicit ratio above
NOTABLE_BUILDING_FLAT_CAP: Dict[str, int] = {
    "shop": 100,
    "town_hall": 1,
    "harbormaster_office": 1,
}
INFILL_BUILDING_TYPE_BY_ZONE: Dict[ZoneType, str] = {
    ZoneType.MERCHANT: "workshop",
    ZoneType.PORT: "workshop",
    ZoneType.CIVIC: "workshop",  # placeholder pending a civic-specific infill type, see below
}
```

A type counts as "notable" (subject to a cap) if it has an entry in
`BUILDING_NAME_POOLS`. Its cap is `NOTABLE_BUILDING_FLAT_CAP[type]` if
present, else `max(1, round(target_population * NOTABLE_BUILDING_CAP_RATIO.get(type, DEFAULT_NOTABLE_BUILDING_CAP_RATIO)))`.

A running per-`building_type` count is threaded through
`generate_town`'s per-district loop the same way `next_building_id`
already is. When a leaf's weighted type draw
(`resolve_building_type_weights`) picks a type at or past its cap, that
leaf becomes the zone's `INFILL_BUILDING_TYPE_BY_ZONE` entry instead —
generic shape, no name (`BUILDING_NAME_POOLS` lookup skipped), no job
vacancies (`JOB_VACANCIES_BY_BUILDING_TYPE` lookup skipped,
`capacity=0`). The zone's *other*, still-under-cap types are not
re-rolled into — capping tavern doesn't inflate shop's count as a side
effect.

`farmland_edge` is untouched (`fill_district_buildings`'s own path,
never routed through this cap — it doesn't produce block-tiled
buildings at all).

Placeholder note: civic zone doesn't yet have a natural "background"
building type the way merchant/port get `workshop` — using `workshop`
there too for now (a generic civic outbuilding) since it's the least
disruptive default; worth a fresh look if a more fitting civic infill
type (e.g. `"tenement"` or similar) comes up in practice.

### `town_shaper/generate.py` — wiring simplification

The per-district loop's call to `generate_blocks_and_buildings` drops
the `next_local_node_id`/`next_local_edge_id` threading (per the
`blocks.py` section above) and gains the notable-building running-count
dict, threaded the same way.

## Rendering

Both `town_db/render.py` and `town_viewer/static/app.js` draw buildings
generically from `x`/`y`/`width`/`height`/`rotation` already — that
code path needs **no changes** at all, since this spec changes what
real generation produces, not how either renderer draws it.

The only change in both: their `ROAD_STYLE` tables drop the `local`
entry (never produced) and rename/restyle `radial` → `artery` — thin,
low-contrast (it's now only ever a short last-mile stretch into
farmland, not a line running through the city).

## Determinism & Testing

RNG threading is unchanged in shape — `rng_for(seed, "blocks",
district.id, ...)` still the single source of randomness for block/
building placement; the new per-type running-count is deterministic
because districts are still processed in the same fixed order they
already are.

Tests requiring substantial rewrite (TDD, red→green, per this
project's usual practice — not enumerated task-by-task here, that's
the implementation plan's job):

- `tests/test_roads.py` — every test asserting a direct hub→anchor
  `radial` edge needs replacing with shortest-path/connectivity/
  smoothing assertions; add coverage for "no artery edge is emitted
  between two urban districts."
- `tests/test_blocks.py` — `place_buildings_in_block`'s frontage/lot
  assertions replaced with tiling/contiguity/no-overlap assertions
  (similar shape to the mockup's own checks: footprints stay within
  the block, don't overlap each other); `subdivide_into_blocks`'s
  node/edge-count assertions updated for the simplified return shape;
  new tests for the notable-building cap (a capped type's count never
  exceeds its cap across a full district; capping one type doesn't
  starve or inflate another).
- `tests/test_generate.py`, `tests/test_db_render.py`,
  `tests/test_viewer_queries.py` — drop any `road_type == "local"`
  assertions; confirm urban buildings still all get positive
  width/height (unchanged expectation, now via a different code path).
- Full suite + a determinism sweep (advance/regenerate comparison, same
  shape as every prior plan's final task) before this is considered
  done.

**Performance note, not a design decision:** full tiling plus the
density cap still means noticeably more `buildings` rows per town than
today (most of them capacity-0 infill). Worth a quick sanity check
during implementation that generation time and DB size stay reasonable
at the existing test town sizes (targets already exercised elsewhere in
the suite, e.g. pop 5000-10000) — not expected to be a real problem,
but not verified yet either.
