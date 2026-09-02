# Building Footprints & Lot Placement — Design

## Context

This is the second, dependent half of the "organic city rendering" viewer
follow-up (`docs/visual-interface-ideas.md`), explicitly deferred by
`docs/superpowers/specs/2026-09-02-town-road-network-design.md`'s Context
section: "Building footprints and placement... is an explicitly separate,
follow-on spec that depends on this one landing first — buildings need
something to front onto." The road network (radial/boundary/spur roads
between districts) is now merged to `main`.

Today, `town_shaper/buildings.py`'s `fill_district_buildings` places every
building as a bare `(x, y)` point via Poisson-disc sampling inside a
district polygon — no size, no orientation, no relationship to a street.
This spec gives buildings a real rectangular footprint (width, height,
rotation) and places them along actual local streets inside each district,
so the map reads as a city instead of scattered dots.

**Scope boundary, confirmed during brainstorming:** this only applies to
"urban" zone types — `civic`, `merchant`, `rich_residential`,
`poor_residential`, `port`. `farmland_edge` keeps today's Poisson-disc
point placement unchanged (a lot fronting a street doesn't fit sparse
farmsteads on open land) — farmland buildings do still get a small fixed
default footprint (see Data Model) so both renderers can treat every
building uniformly.

## Scope

New module `town_shaper/blocks.py`: district-polygon → block subdivision
(recursive OBB split, producing block polygons and "local" road edges)
and block → lot → building placement (walking each block's boundary,
carving lots, placing one building per lot). New `geometry.py` helper
generalizing the existing rectangle-clip machinery to clip a polygon
against one arbitrary line. Changes to `town_shaper/buildings.py`
(dispatch: farmland keeps its existing path plus a default footprint;
other zones route through the new module), `town_shaper/models.py`
(`Building` gains `width`/`height`/`rotation`), `town_db/schema.py`/
`town_db/generate.py` (three new `buildings` columns, matching insert),
`town_db/render.py` and `town_viewer/` (draw footprints as rotated
rectangles instead of points/small squares; local streets in `ROAD_STYLE`).

Out of scope:
- **Farmland block/lot subdivision.** Explicitly deferred per the scope
  boundary above.
- **Corner-wrapping lots.** A block's leftover partial frontage at each
  corner (shorter than one lot width) is simply left empty, not merged
  into an adjoining edge's lot run. Cosmetic gap, not a placement bug.
- **True architectural building shapes.** Every footprint is a plain
  rectangle. No L-shapes, no shared walls, no varying roof styles.
- **Editing/moving footprints.** Read-only generation output, same as
  every other geometry this project produces.
- **Re-deriving footprints for creative-mode edits.** `town_db/edits.py`
  already documents that its mutations leave derived data
  (`relationships`/`shop_relationships`) stale with no re-derive path;
  footprints are generation-time-only in the same spirit — an edit that
  adds/moves a building (if one is ever added) is a future concern.

## Data Model

### `town_shaper/models.py` — `Building` gains three fields

```python
@dataclass
class Building:
    id: int
    district_id: int
    district_zone_type: ZoneType
    x: float
    y: float
    building_type: str
    capacity: int
    vacancies: List[JobVacancy] = field(default_factory=list)
    resident_ids: List[int] = field(default_factory=list)
    name: Optional[str] = None
    width: float = 0.0
    height: float = 0.0
    rotation: float = 0.0   # radians; footprint is a rectangle centered on (x, y)
```

Every building, urban or farmland, ends up with a non-zero `width`/
`height` at generation time — farmland buildings get a fixed constant
(see Algorithm) rather than a lot-derived size, but the field is never
left at its dataclass default of `0.0` in generated output.

### Schema (`town_db/schema.py`) — `buildings` table gains three columns

```sql
CREATE TABLE buildings (
    id INTEGER PRIMARY KEY,
    district_id INTEGER NOT NULL REFERENCES districts(id),
    zone_type TEXT NOT NULL,
    building_type TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    capacity INTEGER NOT NULL,
    name TEXT,
    width REAL NOT NULL DEFAULT 0,
    height REAL NOT NULL DEFAULT 0,
    rotation REAL NOT NULL DEFAULT 0
);
```

### Road network reuse — no schema change there at all

Local streets (the recursive split lines from block subdivision) are
persisted as ordinary rows in the *existing* `road_nodes`/`road_edges`
tables from the road network feature: new `kind="junction"` nodes at each
cut line's endpoints, new `road_type="local"` edges between them. Both
columns are plain `TEXT`, so this needs zero migration — it's exactly the
same reuse relationship `RoadEdge`already has for `"radial"`/`"boundary"`/
`"spur"`.

## Algorithm

### `town_shaper/geometry.py` — one new helper

Generalize the existing rectangle-clip's inner loop (`clip_polygon_to_bounds`
already runs a Sutherland-Hodgman pass per rectangle edge using
`_is_inside_edge`/`_line_intersection`, both of which already take
arbitrary `edge_start`/`edge_end` points, not hardcoded rectangle
corners) into a standalone public function:

```python
def clip_polygon_by_line(polygon: Polygon, edge_start: Point, edge_end: Point) -> Polygon:
    """Keep only the part of `polygon` on the left side of the directed
    line edge_start -> edge_end (Sutherland-Hodgman, single edge)."""
```

This is the same inner-loop body `clip_polygon_to_bounds` already has for
one rectangle edge, extracted so block subdivision can clip against an
arbitrary cut line instead of a fixed rectangle's four sides.

### `town_shaper/blocks.py` — block subdivision

`subdivide_into_blocks(polygon_part, zone_type, rng) -> List[Polygon]`,
called once per `district.polygon_parts` entry (mirroring how
`fill_district_buildings` already treats water-split parts independently),
returns the list of final block polygons plus the list of `(RoadNode,
RoadEdge)` pairs for the local streets it cut.

Recursive step, given a polygon part:
1. If `polygon_area(part) <= TARGET_BLOCK_AREA_BY_ZONE[zone_type]` or the
   recursion has hit `MAX_SPLIT_DEPTH` (safety cap against pathological
   thin slivers), stop: this part is a finished block.
2. Otherwise, compute `shapely.geometry.Polygon(part).minimum_rotated_rectangle`
   and find its longer pair of parallel edges — that's the split axis.
3. Pick a split fraction `rng.uniform(0.4, 0.6)` along that axis through
   the polygon's centroid (not always an exact half, for organic size
   variety — the same reasoning `place_anchors` already applies via
   `_draw_anchor_point`'s randomized radius). Build the infinite cut line
   perpendicular to the split axis at that point.
4. Clip the part twice with `clip_polygon_by_line`, offsetting the cut
   line by half `LOCAL_STREET_WIDTH` to each side, producing two child
   polygons with a real street-width gap between them (no `buffer()`
   needed — two offset clips does the same job with machinery already in
   place).
5. Record one `RoadNode`/`RoadEdge` pair for the *unoffset* cut line's
   intersection with the original part's boundary (`road_type="local"`).
6. Recurse on both children.

### `town_shaper/blocks.py` — lot subdivision and building placement

`place_buildings_in_block(block_polygon, district, rng, next_building_id, target_population, magic_prevalence) -> List[Building]`:

Walk the block polygon's edges in order. For each edge (`edge_start` →
`edge_end`, length `L`, direction `d`):
1. `num_lots = floor(L / LOT_FRONTAGE_BY_ZONE[zone_type])`.
2. For lot index `i` in `range(num_lots)`: the lot spans
   `[edge_start + i*frontage*d, edge_start + (i+1)*frontage*d]` along the
   edge, extended `LOT_DEPTH_BY_ZONE[zone_type]` inward. "Inward" is
   whichever of the edge's two perpendicular directions puts a test point
   inside `block_polygon` per the existing `point_in_polygon` helper —
   robust regardless of the polygon's winding order, so no new assumption
   about vertex ordering is introduced.
3. Choose `building_type` via the *same* zone-weighted selection
   `fill_district_buildings` already uses (university/arcane_shop
   special-casing included) — extracted into a small shared helper so
   this module and `buildings.py`'s farmland path call one function
   instead of duplicating the conditional logic.
4. Footprint: `width = frontage * FOOTPRINT_FILL_FRACTION`,
   `height = depth * FOOTPRINT_FILL_FRACTION` (0.8 — leaves a visible gap
   between neighboring buildings), `rotation = angle_of(d)` (the
   building's width axis aligns with the street it fronts), position =
   the lot rectangle's centroid.
5. A leftover partial-frontage remainder at the end of each edge (shorter
   than one `LOT_FRONTAGE_BY_ZONE[zone_type]`) is simply not built on —
   see the corner-wrapping exclusion in Scope.

A block whose every edge is shorter than one `LOT_FRONTAGE_BY_ZONE[zone_type]`
(possible for a small leftover sliver near the target-area threshold) simply
gets zero buildings — an empty block is an acceptable, if rare, outcome, not
a bug to special-case.

### `town_shaper/buildings.py` — dispatch

`fill_district_buildings` gains a branch at the top: if
`district.zone_type == ZoneType.FARMLAND_EDGE`, run exactly today's
Poisson-disc code path unchanged, except every created `Building` also
gets a fixed constant footprint (`FARMLAND_BUILDING_WIDTH`,
`FARMLAND_BUILDING_HEIGHT`, `rotation=0.0`) — not lot-derived, just a
flat default so the renderer never has to special-case a zero-size
building. Every other zone type routes to
`town_shaper.blocks.subdivide_into_blocks` + `place_buildings_in_block`
instead of `poisson_disc_fill`.

### `town_shaper/generate.py` — wiring, and local-street id numbering

`subdivide_into_blocks` accepts `next_node_id`/`next_edge_id` starting
integers and returns them incremented past whatever it consumed —
mirroring the existing `next_building_id` threading `generate_town`
already does per district (`BUILDING_ID_STRIDE`). `generate_town` seeds
the first district's counters to `max(n.id for n in road_network.nodes) +
1` / `max(e.id for e in road_network.edges) + 1` (the town-level network
`generate_road_network` already produced), then threads the running
counters forward across the existing per-district loop, same as
`next_building_id`. This avoids any id collision between the town-level
network's nodes/edges and the per-district local-street ones without
introducing a new id-space convention. The local-street `RoadNode`/
`RoadEdge` pairs collected this way are appended to
`road_network.nodes`/`road_network.edges` before `road_network` is
attached to the `Town`.

### `density_multiplier` carries over the same way it does today

`fill_district_buildings`'s existing `density_multiplier` currently scales
building spacing directly (`spacing = MIN_BUILDING_SPACING[zone_type] /
density_multiplier`). The new path applies it the same way, to the same
kind of constant: `LOT_FRONTAGE_BY_ZONE[zone_type] / density_multiplier`
and `LOT_DEPTH_BY_ZONE[zone_type] / density_multiplier`, keeping
`FOOTPRINT_FILL_FRACTION` constant — a higher multiplier means narrower,
more numerous lots, exactly analogous to today's tighter point spacing.
`TARGET_BLOCK_AREA_BY_ZONE` is unaffected by `density_multiplier` (it only
controls how finely districts split into blocks, not how densely each
block fills with lots).

### Determinism and zone-specific constants

All new randomness (split fraction, split order) draws from
`rng_for(town_seed, "blocks", district.id, <recursion path>)`, following
the project's existing per-purpose-and-id seeding convention. New
per-zone constant dicts in `town_shaper/blocks.py`:

```python
TARGET_BLOCK_AREA_BY_ZONE: Dict[ZoneType, float]   # smaller for merchant/civic, larger for residential
LOT_FRONTAGE_BY_ZONE: Dict[ZoneType, float]
LOT_DEPTH_BY_ZONE: Dict[ZoneType, float]
LOCAL_STREET_WIDTH = <constant>
MAX_SPLIT_DEPTH = <constant, e.g. 8>
FOOTPRINT_FILL_FRACTION = 0.8
```

exact values are the implementation plan's call, tuned against the same
kind of visual/scale sanity check `MIN_BUILDING_SPACING` already used.

## Rendering

### Static PNG (`town_db/render.py`)

Replace the buildings-drawing block's `ax.scatter`/marker calls with: for
each building, compute its 4 rotated rectangle corners from
`(x, y, width, height, rotation)` and draw via `MplPolygon` — the exact
same patch type already used for districts/water, just with per-building
corners instead of a shared ring. Landmark vs. generic color logic is
unchanged, just applied to the rectangle's `facecolor` instead of a
scatter marker's color.

`ROAD_STYLE` gains a fourth entry:

```python
"local": {"width": 0.5, "color": "#9a9a9a"},
```

(thinnest and lightest of all four road types — these are minor internal
streets).

### Town viewer

`town_viewer/queries.py`'s `get_map_data`/`get_building_detail` add
`width`, `height`, `rotation` to the buildings they return.
`town_viewer/static/app.js`'s `draw()` replaces the buildings loop's
`ctx.fillRect` (an axis-aligned square) with a rotated draw: `ctx.save()`,
translate to the building's screen position, `ctx.rotate(rotation)`,
`ctx.fillRect(-w/2, -h/2, w, h)`, `ctx.restore()` — the standard canvas
rotated-rectangle technique. `ROAD_STYLE` in JS gets the matching
`"local"` entry. Building click hit-testing (`findBuildingAt`) needs to
test against the rotated rectangle instead of the current axis-aligned
box — rotate the click point into the building's local frame (inverse
rotation) before the existing half-width/half-height bounds check, rather
than switching to a general point-in-polygon test.

## Testing

`tests/test_blocks.py` (new):
- `subdivide_into_blocks` on a simple square district: recursion
  terminates (no infinite loop) within `MAX_SPLIT_DEPTH`; every returned
  block's area is at or under the zone's target; total block area plus
  the street-gap area recovered from the local-street cuts approximately
  equals the original polygon's area (mirrors
  `test_build_districts_partitions_bounding_box_area`'s total-area check).
- Determinism: same seed in → same blocks and same local-street edges,
  run twice.
- `place_buildings_in_block` on a simple rectangular block: every
  building's footprint corners stay within the block polygon (or within
  a small tolerance for the fill fraction); no two buildings' footprints
  overlap (shapely polygon intersection check) for a sample block; every
  building's `rotation` matches the frontage edge it was placed against.
- `clip_polygon_by_line`: clipping a square by a line through its center
  produces two triangles/halves whose areas sum to the original
  (unit-style test, independent of the recursive subdivision using it).

`tests/test_buildings.py` (extend): farmland buildings get the fixed
constant footprint (`width`/`height` equal to the constants, `rotation ==
0.0`); non-farmland buildings from `fill_district_buildings` have
`width > 0` and `height > 0` (regression guard that the dispatch branch
actually routes through the new code path).

`tests/test_db_schema.py`/`tests/test_db_render.py`/
`tests/test_viewer_queries.py` (extend, same pattern as the road network
work): new columns round-trip through the DB; `render_town` doesn't crash
on rotated footprints; `get_map_data`/`get_building_detail` include the
new fields; any pre-existing exact-dict-equality assertions on a
building's shape get updated to include the three new keys (same pattern
already used when `name` was added).
