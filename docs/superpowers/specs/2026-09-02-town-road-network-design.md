# Town Road Network — Design

## Context

`docs/visual-interface-ideas.md`'s post-MVP follow-ups flags "Map should
read as an actual city, not scattered squares" as the big remaining
viewer gap: buildings render as Poisson-disc-sampled points floating in
empty zone polygons, with no streets between them. That doc already
notes this "probably needs real footprint/road geometry from the
generator side, not just a viewer change."

Investigated for inspiration: a sibling repo, `city-map-poster`, which
generates map posters for real cities. It turned out to have no
procedural street or building generator to borrow — it downloads real
OSM road/building data via OSMnx and renders it. It also never draws
building footprints at all (roads + water + parks only). The one
reusable idea is stylistic: roads as a graph with hierarchy-based
width/color (motorway thick+dark → residential thin+light), rendered in
clean z-ordered layers.

TownShape has no road/street concept today. `town_shaper/districts.py`
already lays the town out as a Voronoi diagram around per-zone anchor
points (`town_shaper/anchors.py`) — the same technique classic organic
fantasy-town generators use, and a much better foundation than building
a street network from nothing: district boundaries are already
Voronoi ridges, which double naturally as streets.

This spec covers **only the road network** — a real, persisted,
navigable graph of nodes and edges, laid over the existing district
geometry, with basic hierarchy-styled rendering in both the static PNG
renderer and the town viewer. **Building footprints and placement
(making buildings actually sit against streets, replacing point
sampling) is an explicitly separate, follow-on spec** that depends on
this one landing first — buildings need something to front onto.

## Scope

New module `town_shaper/roads.py`: `generate_road_network(anchors,
bounds, water_polygon=None) -> RoadNetwork`. New `RoadNode`, `RoadEdge`,
`RoadNetwork` dataclasses in `town_shaper/models.py`; `Town` gains a
`road_network` field. New `road_nodes`/`road_edges` tables
(`town_db/schema.py`), inserted inline in `town_db/generate.py`
(matching how `districts`/`buildings`/`water_features` are already
inserted there, not via `town_db/persistence.py`'s helpers). Rendering
changes to `town_db/render.py` (static PNG) and `town_viewer`
(`queries.py`'s `/api/map` payload, `static/app.js`'s canvas draw).

Out of scope (deliberately, for this spec):
- **Building footprints/placement.** Buildings stay exactly as they are
  today (points, Poisson-disc sampled). Follow-on spec.
- **Pathfinding/query API.** This produces graph-*shaped* data (plain
  node/edge lists) that any future feature could load into a graph
  library (e.g. `networkx`) and query. It does not add `networkx` as a
  dependency or build a shortest-path function/endpoint — nothing
  consumes one yet.
- **Curved/organic-looking road paths.** Every edge is a straight
  segment between its two endpoint nodes. Real per-street curvature is
  a rendering-polish concern, not this spec's.
- **Routing around water.** An edge that crosses a water polygon is
  simply drawn as-is (implies a bridge). No path-planning around water.

## Data Model

### Node/edge model (conceptual)

Two node kinds:
- **`anchor` nodes** — one per existing `town_shaper.Anchor` (i.e. one
  per district), reusing that anchor's `id` and coordinates. Exactly one
  is flagged `is_hub`: the `civic`-zone anchor nearest the town's
  geometric bounds center (falls back to the nearest anchor of any zone
  type if the town happens to have no civic anchors).
- **`junction` nodes** — Voronoi vertices where two or more district
  boundaries meet. Only vertices that are part of at least one
  qualifying boundary edge (see below) are kept; deduplicated by the
  underlying Voronoi vertex index.

Three edge kinds, all straight segments between their two endpoint
nodes' coordinates (no separate geometry column is needed — the
endpoints *are* the geometry):
- **`radial`** — hub anchor → every other anchor node. One per
  non-hub anchor.
- **`boundary`** — junction ↔ junction, one per finite Voronoi ridge
  between two real anchors (ridges touching a mirrored/reflection point
  — the trick `districts.py` already uses to bound outer regions — are
  excluded, as are any ridge with an unbounded (`-1`) vertex).
- **`spur`** — anchor → its nearest own-cell junction node (by Euclidean
  distance), one per anchor that has at least one qualifying junction in
  its own Voronoi cell. This is what merges the radial hub-and-spoke
  layer and the boundary layer into a single connected graph — without
  it, an anchor's radial edge and its district's boundary edges would be
  two disconnected islands. If an anchor's cell has no qualifying
  junction (a small/edge-case cell), it simply gets no spur; the graph
  stays connected regardless because every anchor already has a radial
  edge straight to the hub.

This guarantees the whole graph is connected by construction: the
radial star alone reaches every anchor node, and boundary/spur edges add
shortcuts on top.

### Schema (`town_db/schema.py`)

```sql
CREATE TABLE road_nodes (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,                          -- 'anchor' | 'junction'
    anchor_id INTEGER REFERENCES districts(id),  -- set only for kind='anchor'
    is_hub INTEGER NOT NULL DEFAULT 0,
    x REAL NOT NULL,
    y REAL NOT NULL
);

CREATE TABLE road_edges (
    id INTEGER PRIMARY KEY,
    from_node_id INTEGER NOT NULL REFERENCES road_nodes(id),
    to_node_id INTEGER NOT NULL REFERENCES road_nodes(id),
    road_type TEXT NOT NULL                      -- 'radial' | 'boundary' | 'spur'
);
```

### `town_shaper/models.py` additions

```python
@dataclass
class RoadNode:
    id: int
    kind: str                       # "anchor" | "junction"
    x: float
    y: float
    anchor_id: Optional[int] = None
    is_hub: bool = False


@dataclass
class RoadEdge:
    id: int
    from_node_id: int
    to_node_id: int
    road_type: str                  # "radial" | "boundary" | "spur"


@dataclass
class RoadNetwork:
    nodes: List[RoadNode] = field(default_factory=list)
    edges: List[RoadEdge] = field(default_factory=list)
```

`Town` gains `road_network: Optional[RoadNetwork] = None`.

## Algorithm (`town_shaper/roads.py`)

`districts.py`'s `build_districts` already computes a `scipy.spatial.
Voronoi` diagram over the anchors (mirrored across `bounds` to keep
every region bounded) but only keeps the resulting region polygons —
the ridge data is discarded. Extract that Voronoi construction (the
`_mirrored_points` call + `Voronoi(...)`) into a small shared helper in
`districts.py` so it's computed once per generation and reused by both
`build_districts` and `generate_road_network`, rather than recomputed.

`generate_road_network(anchors, bounds, water_polygon=None)`:

1. Compute (or receive) the shared Voronoi diagram over `anchors`.
2. Pick the hub anchor (nearest-to-bounds-center `civic` anchor, or
   nearest overall as fallback). Create one `anchor`-kind `RoadNode` per
   anchor, coordinates from the anchor, `is_hub=True` on the chosen one.
3. Add one `radial` `RoadEdge` from the hub node to every other anchor
   node.
4. Walk `vor.ridge_points`/`vor.ridge_vertices`. For each ridge where
   both `ridge_points` indices are real (non-mirrored) anchors and both
   `ridge_vertices` are finite (`>= 0`): create (or reuse, keyed by
   Voronoi vertex index) a `junction`-kind `RoadNode` for each endpoint,
   and add one `boundary` `RoadEdge` between them.
5. For each anchor, from the junction nodes that are vertices of its own
   Voronoi region (`vor.regions[vor.point_region[i]]`) and were kept as
   qualifying junctions in step 4, pick the nearest by distance to the
   anchor and add one `spur` `RoadEdge` anchor → junction. Skip if none
   qualify.
6. Return the assembled `RoadNetwork`.

Determinism: no randomness is involved (the network is a deterministic
function of anchor positions and bounds, which are themselves already
seeded upstream) — no `rng` parameter needed.

`town_shaper/generate.py`'s `generate_town` calls
`generate_road_network` right after `build_districts` and attaches the
result to `town.road_network`.

`town_db/generate.py` inserts `road_nodes` then `road_edges` inline,
immediately after the existing districts/buildings inserts, following
the same raw-SQL-per-row style already used there.

## Rendering

### Static PNG (`town_db/render.py`)

Read `road_nodes`/`road_edges`, draw each edge as a line between its
two endpoints' coordinates, before buildings but after district
polygons (z-order between districts and buildings). Style by
`road_type` via a lookup dict, matching the existing
`ZONE_COLORS`/`LANDMARK_BUILDING_TYPES` dict-driven pattern:

```python
ROAD_STYLE = {
    "radial":   {"width": 2.5, "color": "#3a3a3a"},
    "boundary": {"width": 1.4, "color": "#5a5a5a"},
    "spur":     {"width": 0.8, "color": "#7a7a7a"},
}
```

### Town viewer

`town_viewer/queries.py`'s `get_map_data` adds a `roads` key:
`{"nodes": [{"id", "x", "y"}], "edges": [{"from_node_id", "to_node_id",
"road_type"}]}`. `town_viewer/static/app.js`'s `draw()` renders edges as
canvas lines using the same `ROAD_STYLE`-equivalent lookup (mirrored in
JS, same values as the Python dict above), drawn in the same z-order
slot (after districts/water, before buildings).

No legend changes needed for a first pass — roads are a background
layer, not something you click to inspect (no building-style detail
panel for a road in this spec).

## Testing

`tests/test_roads.py` (new, alongside the existing `test_buildings.py`,
`test_districts.py` style):
- The hub anchor is the civic anchor nearest bounds-center (construct a
  small fixed anchor set, assert the right one is picked).
- Every anchor node is reachable from the hub via `radial` edges alone
  (trivially true by construction, but assert it — this is the
  connectivity guarantee the spec relies on).
- Boundary edges only connect anchors whose Voronoi cells are actually
  adjacent (cross-check against `build_districts`' polygons for a small
  fixed layout).
- Determinism: same anchors/bounds in → same node/edge set out, run
  twice.
- No ridge involving a mirrored/reflection point ends up as a
  `boundary` edge (regression guard for the exclusion in algorithm step
  4).

`tests/test_db_schema.py`-style round-trip: generate a small town,
insert `road_nodes`/`road_edges`, read them back, assert the in-memory
`RoadNetwork` matches.

`tests/test_db_render.py` / `tests/test_viewer_queries.py`: extend
existing map-data/render tests to assert the new `roads` payload/lines
are present and don't break existing district/building assertions
(same pattern used when `name` was added to buildings — nullable/
additive fields, exact-dict-equality assertions updated, not broken).
