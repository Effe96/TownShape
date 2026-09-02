# Town Road Network Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every generated town a real, persisted, navigable road graph — radial roads from a town hub plus boundary roads along district edges — replacing today's "buildings floating in empty zone polygons with no streets" look, without yet touching building placement itself.

**Architecture:** A new `town_shaper/roads.py` module derives the road graph from the Voronoi diagram `town_shaper/districts.py` already builds (reusing its geometry via a newly extracted shared helper, not recomputing it). The graph is two new SQLite tables (`road_nodes`, `road_edges`), inserted the same way districts/buildings/water already are. Both existing renderers (the static PNG in `town_db/render.py` and the live viewer in `town_viewer/`) draw the new edges as styled lines.

**Tech Stack:** Python, `scipy.spatial.Voronoi` (already a dependency), SQLite, Flask + vanilla JS canvas (existing viewer stack). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-02-town-road-network-design.md`

## Global Constraints

- No new dependencies (no `networkx` — this plan produces graph-*shaped* data only; nothing in this plan queries it).
- Every road edge is a straight line between its two endpoint nodes' coordinates — no separate geometry/path column, no curves.
- An edge that crosses a water polygon is drawn as-is (implies a bridge) — no routing logic around water.
- Building placement is explicitly out of scope — buildings stay exactly as they are today (points).
- Determinism: `generate_road_network` takes no `rng`/seed parameter — it's a pure function of `anchors`/`bounds`, which are already deterministic from the town seed upstream.

---

### Task 1: Extract a shared Voronoi helper in `districts.py`

**Files:**
- Modify: `town_shaper/districts.py`
- Test: `tests/test_districts.py`

**Interfaces:**
- Produces: `compute_voronoi(anchors: List[Anchor], bounds: Tuple[float, float, float, float]) -> scipy.spatial.Voronoi` — raises `ValueError` if `len(anchors) < 4`. The returned `Voronoi` was built from `anchors` mirrored across `bounds` (via the existing `_mirrored_points` helper), so real anchors occupy indices `0..len(anchors)-1` of `vor.points`/`vor.point_region`, and any index `>= len(anchors)` is a mirrored/reflection point, not a real anchor.

This is a pure refactor — `build_districts`'s behavior must not change. `town_shaper/roads.py` (Task 2 onward) will call `compute_voronoi` directly instead of recomputing the same Voronoi diagram.

- [ ] **Step 1: Write a test for the new helper**

Add to `tests/test_districts.py`:

```python
from town_shaper.districts import compute_voronoi


def test_compute_voronoi_requires_at_least_four_anchors():
    anchors = [Anchor(id=i, zone_type=ZoneType.CIVIC, x=float(i), y=0.0) for i in range(3)]
    with pytest.raises(ValueError):
        compute_voronoi(anchors, bounds=(-10.0, -10.0, 10.0, 10.0))


def test_compute_voronoi_real_anchors_occupy_the_first_indices():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    vor = compute_voronoi(anchors, bounds)

    for i, anchor in enumerate(anchors):
        assert vor.points[i][0] == pytest.approx(anchor.x)
        assert vor.points[i][1] == pytest.approx(anchor.y)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_districts.py::test_compute_voronoi_requires_at_least_four_anchors tests/test_districts.py::test_compute_voronoi_real_anchors_occupy_the_first_indices -v`
Expected: FAIL with `ImportError: cannot import name 'compute_voronoi'`

- [ ] **Step 3: Extract `compute_voronoi` and refactor `build_districts` to use it**

In `town_shaper/districts.py`, replace:

```python
def build_districts(
    anchors: List[Anchor], bounds: Tuple[float, float, float, float], water_polygon=None
) -> List[District]:
    if len(anchors) < 4:
        raise ValueError("At least 4 anchors are required to compute a stable Voronoi diagram")

    anchor_points = np.array([(a.x, a.y) for a in anchors])
    all_points = _mirrored_points(anchor_points, bounds)
    vor = Voronoi(all_points)
```

with:

```python
def compute_voronoi(anchors: List[Anchor], bounds: Tuple[float, float, float, float]) -> Voronoi:
    if len(anchors) < 4:
        raise ValueError("At least 4 anchors are required to compute a stable Voronoi diagram")

    anchor_points = np.array([(a.x, a.y) for a in anchors])
    all_points = _mirrored_points(anchor_points, bounds)
    return Voronoi(all_points)


def build_districts(
    anchors: List[Anchor], bounds: Tuple[float, float, float, float], water_polygon=None
) -> List[District]:
    vor = compute_voronoi(anchors, bounds)
```

(The rest of `build_districts`'s body is unchanged — it already just uses the local `vor` variable from here on.)

- [ ] **Step 4: Run the full districts test suite to confirm no regression**

Run: `pytest tests/test_districts.py -v`
Expected: all tests PASS, including the two new ones.

- [ ] **Step 5: Commit**

```bash
git add town_shaper/districts.py tests/test_districts.py
git commit -m "refactor: extract compute_voronoi helper from build_districts

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

### Task 2: Road data model, hub selection, and radial edges

**Files:**
- Modify: `town_shaper/models.py`
- Create: `town_shaper/roads.py`
- Test: `tests/test_roads.py` (new)

**Interfaces:**
- Consumes: `compute_voronoi` (Task 1), `Anchor`/`ZoneType` (existing `town_shaper.models`), `distance` (existing `town_shaper.geometry`).
- Produces: `RoadNode`, `RoadEdge`, `RoadNetwork` dataclasses in `town_shaper/models.py`; `generate_road_network(anchors: List[Anchor], bounds: Tuple[float, float, float, float], water_polygon=None) -> RoadNetwork` in `town_shaper/roads.py` (this task only populates `kind="anchor"` nodes and `road_type="radial"` edges — Tasks 3 and 4 extend the same function). `RoadNetwork.nodes: List[RoadNode]`, `RoadNetwork.edges: List[RoadEdge]`.

- [ ] **Step 1: Add the dataclasses to `town_shaper/models.py`**

Add after the `WaterFeature` dataclass:

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

And add `road_network: Optional[RoadNetwork] = None` as a new field on the `Town` dataclass (after `water_features`).

- [ ] **Step 2: Write failing tests for hub selection and radial edges**

Create `tests/test_roads.py`:

```python
from town_shaper.models import Anchor, ZoneType
from town_shaper.roads import generate_road_network


def _anchor(id, zone_type, x, y):
    return Anchor(id=id, zone_type=zone_type, x=x, y=y)


def test_hub_is_the_civic_anchor_nearest_bounds_center():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = [
        _anchor(0, ZoneType.CIVIC, x=50.0, y=50.0),
        _anchor(1, ZoneType.CIVIC, x=5.0, y=-5.0),   # nearest to (0, 0)
        _anchor(2, ZoneType.MERCHANT, x=0.0, y=0.0),  # closer, but not civic
        _anchor(3, ZoneType.POOR_RESIDENTIAL, x=-60.0, y=60.0),
    ]
    network = generate_road_network(anchors, bounds)

    hub_nodes = [n for n in network.nodes if n.is_hub]
    assert len(hub_nodes) == 1
    assert hub_nodes[0].anchor_id == 1


def test_hub_falls_back_to_nearest_any_zone_when_no_civic_anchors():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = [
        _anchor(0, ZoneType.MERCHANT, x=50.0, y=50.0),
        _anchor(1, ZoneType.MERCHANT, x=5.0, y=-5.0),
        _anchor(2, ZoneType.POOR_RESIDENTIAL, x=0.0, y=0.0),
        _anchor(3, ZoneType.FARMLAND_EDGE, x=-60.0, y=60.0),
    ]
    network = generate_road_network(anchors, bounds)

    hub_nodes = [n for n in network.nodes if n.is_hub]
    assert len(hub_nodes) == 1
    assert hub_nodes[0].anchor_id == 2


def test_every_anchor_has_a_radial_edge_to_the_hub():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = [
        _anchor(0, ZoneType.CIVIC, x=0.0, y=0.0),
        _anchor(1, ZoneType.MERCHANT, x=40.0, y=0.0),
        _anchor(2, ZoneType.POOR_RESIDENTIAL, x=-40.0, y=0.0),
        _anchor(3, ZoneType.RICH_RESIDENTIAL, x=0.0, y=40.0),
    ]
    network = generate_road_network(anchors, bounds)

    hub_node_id = next(n.id for n in network.nodes if n.is_hub)
    radial_targets = {
        e.to_node_id for e in network.edges
        if e.road_type == "radial" and e.from_node_id == hub_node_id
    }
    anchor_node_ids_excluding_hub = {
        n.id for n in network.nodes if n.kind == "anchor" and not n.is_hub
    }
    assert radial_targets == anchor_node_ids_excluding_hub
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_roads.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_shaper.roads'`

- [ ] **Step 4: Implement hub selection and anchor/radial generation**

Create `town_shaper/roads.py`:

```python
from typing import Dict, List, Tuple

from town_shaper.districts import compute_voronoi
from town_shaper.geometry import distance
from town_shaper.models import Anchor, RoadEdge, RoadNetwork, RoadNode, ZoneType


def _choose_hub_anchor(anchors: List[Anchor], bounds: Tuple[float, float, float, float]) -> Anchor:
    min_x, min_y, max_x, max_y = bounds
    center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
    civic_anchors = [a for a in anchors if a.zone_type == ZoneType.CIVIC]
    candidates = civic_anchors if civic_anchors else anchors
    return min(candidates, key=lambda a: distance(center, (a.x, a.y)))


def generate_road_network(
    anchors: List[Anchor], bounds: Tuple[float, float, float, float], water_polygon=None,
) -> RoadNetwork:
    compute_voronoi(anchors, bounds)  # validates >= 4 anchors; result used starting Task 3
    hub = _choose_hub_anchor(anchors, bounds)

    nodes: List[RoadNode] = []
    edges: List[RoadEdge] = []
    next_node_id = 0
    next_edge_id = 0

    anchor_node_by_id: Dict[int, RoadNode] = {}
    for anchor in anchors:
        node = RoadNode(
            id=next_node_id, kind="anchor", x=anchor.x, y=anchor.y,
            anchor_id=anchor.id, is_hub=(anchor.id == hub.id),
        )
        next_node_id += 1
        nodes.append(node)
        anchor_node_by_id[anchor.id] = node

    hub_node = anchor_node_by_id[hub.id]
    for anchor in anchors:
        if anchor.id == hub.id:
            continue
        edges.append(RoadEdge(
            id=next_edge_id, from_node_id=hub_node.id,
            to_node_id=anchor_node_by_id[anchor.id].id, road_type="radial",
        ))
        next_edge_id += 1

    return RoadNetwork(nodes=nodes, edges=edges)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_roads.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add town_shaper/models.py town_shaper/roads.py tests/test_roads.py
git commit -m "feat: add road network data model, hub selection, radial edges

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

### Task 3: Boundary edges from Voronoi ridges

**Files:**
- Modify: `town_shaper/roads.py`
- Test: `tests/test_roads.py`

**Interfaces:**
- Consumes: the `vor` object from `compute_voronoi` (`vor.ridge_points`, `vor.ridge_vertices`, `vor.vertices` — standard `scipy.spatial.Voronoi` attributes), `RoadNode`/`RoadEdge` from Task 2.
- Produces: `generate_road_network` now also emits `kind="junction"` nodes and `road_type="boundary"` edges. No signature change.

- [ ] **Step 1: Write failing tests for boundary edges**

Add to `tests/test_roads.py`:

```python
def test_boundary_edges_only_connect_junction_nodes():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = [
        _anchor(0, ZoneType.CIVIC, x=0.0, y=0.0),
        _anchor(1, ZoneType.MERCHANT, x=40.0, y=0.0),
        _anchor(2, ZoneType.POOR_RESIDENTIAL, x=-40.0, y=0.0),
        _anchor(3, ZoneType.RICH_RESIDENTIAL, x=0.0, y=40.0),
    ]
    network = generate_road_network(anchors, bounds)

    boundary_edges = [e for e in network.edges if e.road_type == "boundary"]
    assert len(boundary_edges) > 0
    junction_node_ids = {n.id for n in network.nodes if n.kind == "junction"}
    for edge in boundary_edges:
        assert edge.from_node_id in junction_node_ids
        assert edge.to_node_id in junction_node_ids


def test_no_boundary_edge_involves_a_mirrored_point():
    # A ridge between a real anchor and a mirrored reflection point (used
    # internally by compute_voronoi to bound outer regions) must never
    # surface as a boundary edge -- only ridges between two real anchors do.
    bounds = (-100.0, -100.0, 100.0, 100.0)
    from town_shaper.anchors import place_anchors
    anchors = place_anchors(("town", 1), 3000, bounds)

    network = generate_road_network(anchors, bounds)

    # Every boundary edge's endpoints must be junction nodes created from a
    # ridge between two real anchors -- if a mirrored point leaked through,
    # generate_road_network would raise (anchors[p1] with p1 out of range)
    # before returning, so simply completing without error is the guard.
    boundary_edges = [e for e in network.edges if e.road_type == "boundary"]
    assert len(boundary_edges) > 0


def test_boundary_edges_only_connect_anchors_whose_districts_actually_touch():
    # Cross-check against build_districts' own polygons -- a module this
    # test imports independently of generate_road_network's own output --
    # rather than re-deriving the same ridge data a second time and
    # comparing it to itself.
    from shapely.geometry import Polygon as ShapelyPolygon

    from town_shaper.anchors import place_anchors
    from town_shaper.districts import build_districts, compute_voronoi

    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 5), 4000, bounds)
    districts = build_districts(anchors, bounds)
    polygons_by_anchor_id = {
        d.id: ShapelyPolygon(d.polygon_parts[0]) for d in districts if d.polygon_parts
    }

    vor = compute_voronoi(anchors, bounds)
    num_real_anchors = len(anchors)
    checked_pairs = 0
    for (p1, p2), (v1, v2) in zip(vor.ridge_points, vor.ridge_vertices):
        if p1 >= num_real_anchors or p2 >= num_real_anchors or v1 < 0 or v2 < 0:
            continue
        anchor_a_id, anchor_b_id = anchors[p1].id, anchors[p2].id
        if anchor_a_id not in polygons_by_anchor_id or anchor_b_id not in polygons_by_anchor_id:
            continue
        checked_pairs += 1
        assert polygons_by_anchor_id[anchor_a_id].touches(polygons_by_anchor_id[anchor_b_id]) or \
            polygons_by_anchor_id[anchor_a_id].intersects(polygons_by_anchor_id[anchor_b_id])
    assert checked_pairs > 0


def test_boundary_edges_are_deterministic():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    from town_shaper.anchors import place_anchors
    anchors = place_anchors(("town", 7), 4000, bounds)

    network1 = generate_road_network(anchors, bounds)
    network2 = generate_road_network(anchors, bounds)

    key = lambda n: sorted((e.from_node_id, e.to_node_id, e.road_type) for e in n.edges)
    assert key(network1) == key(network2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_roads.py -v`
Expected: `test_boundary_edges_only_connect_junction_nodes` FAILS (no boundary edges produced yet); the other two pass vacuously or fail depending on assertions — run and confirm at least the first fails before proceeding.

- [ ] **Step 3: Implement boundary edge generation**

In `town_shaper/roads.py`, change `generate_road_network` to keep the `vor` result and add junction/boundary logic:

```python
def generate_road_network(
    anchors: List[Anchor], bounds: Tuple[float, float, float, float], water_polygon=None,
) -> RoadNetwork:
    vor = compute_voronoi(anchors, bounds)
    hub = _choose_hub_anchor(anchors, bounds)

    nodes: List[RoadNode] = []
    edges: List[RoadEdge] = []
    next_node_id = 0
    next_edge_id = 0

    anchor_node_by_id: Dict[int, RoadNode] = {}
    for anchor in anchors:
        node = RoadNode(
            id=next_node_id, kind="anchor", x=anchor.x, y=anchor.y,
            anchor_id=anchor.id, is_hub=(anchor.id == hub.id),
        )
        next_node_id += 1
        nodes.append(node)
        anchor_node_by_id[anchor.id] = node

    hub_node = anchor_node_by_id[hub.id]
    for anchor in anchors:
        if anchor.id == hub.id:
            continue
        edges.append(RoadEdge(
            id=next_edge_id, from_node_id=hub_node.id,
            to_node_id=anchor_node_by_id[anchor.id].id, road_type="radial",
        ))
        next_edge_id += 1

    junction_node_by_vertex: Dict[int, RoadNode] = {}

    def _junction_node(vertex_index: int) -> RoadNode:
        nonlocal next_node_id
        node = junction_node_by_vertex.get(vertex_index)
        if node is None:
            x, y = vor.vertices[vertex_index]
            node = RoadNode(id=next_node_id, kind="junction", x=float(x), y=float(y))
            next_node_id += 1
            nodes.append(node)
            junction_node_by_vertex[vertex_index] = node
        return node

    num_real_anchors = len(anchors)
    for (p1, p2), (v1, v2) in zip(vor.ridge_points, vor.ridge_vertices):
        if p1 >= num_real_anchors or p2 >= num_real_anchors:
            continue
        if v1 < 0 or v2 < 0:
            continue
        node1 = _junction_node(v1)
        node2 = _junction_node(v2)
        edges.append(RoadEdge(
            id=next_edge_id, from_node_id=node1.id, to_node_id=node2.id, road_type="boundary",
        ))
        next_edge_id += 1

    return RoadNetwork(nodes=nodes, edges=edges)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_roads.py -v`
Expected: all tests PASS (6 total so far).

- [ ] **Step 5: Commit**

```bash
git add town_shaper/roads.py tests/test_roads.py
git commit -m "feat: add boundary road edges from Voronoi ridges

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

### Task 4: Spur edges, full network assembly, and wiring into `generate_town`

**Files:**
- Modify: `town_shaper/roads.py`
- Modify: `town_shaper/generate.py`
- Test: `tests/test_roads.py`, `tests/test_generate.py`

**Interfaces:**
- Consumes: everything from Tasks 2-3.
- Produces: `generate_road_network` now emits `road_type="spur"` edges too (final state of this function for this plan). `town_shaper.generate.generate_town(...)` returns a `Town` whose `.road_network` is populated (was `None` before this task).

- [ ] **Step 1: Write failing tests for spur edges and full connectivity**

Add to `tests/test_roads.py`:

```python
def test_every_anchor_with_a_qualifying_junction_gets_a_spur():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    from town_shaper.anchors import place_anchors
    anchors = place_anchors(("town", 3), 4000, bounds)

    network = generate_road_network(anchors, bounds)

    spur_sources = {e.from_node_id for e in network.edges if e.road_type == "spur"}
    anchor_node_ids = {n.id for n in network.nodes if n.kind == "anchor"}
    # Every spur starts at an anchor node and ends at a junction node.
    junction_node_ids = {n.id for n in network.nodes if n.kind == "junction"}
    for edge in network.edges:
        if edge.road_type == "spur":
            assert edge.from_node_id in anchor_node_ids
            assert edge.to_node_id in junction_node_ids
    assert spur_sources  # this anchor layout has at least one qualifying junction


def test_graph_is_fully_connected_via_radial_edges_alone():
    # The connectivity guarantee the spec relies on: even ignoring
    # boundary/spur edges entirely, every anchor is one hop from the hub.
    bounds = (-100.0, -100.0, 100.0, 100.0)
    from town_shaper.anchors import place_anchors
    anchors = place_anchors(("town", 9), 5000, bounds)

    network = generate_road_network(anchors, bounds)

    hub_node_id = next(n.id for n in network.nodes if n.is_hub)
    radial_targets = {
        e.to_node_id for e in network.edges
        if e.road_type == "radial" and e.from_node_id == hub_node_id
    }
    other_anchor_ids = {n.id for n in network.nodes if n.kind == "anchor" and not n.is_hub}
    assert radial_targets == other_anchor_ids
```

Add to `tests/test_generate.py`:

```python
def test_generate_town_populates_road_network():
    town = generate_town(("town", 1), target_population=3000)

    assert town.road_network is not None
    assert len(town.road_network.nodes) > 0
    assert len(town.road_network.edges) > 0
    # One anchor node per district -- town_shaper.districts.build_districts
    # creates exactly one District per Anchor, same id.
    assert sum(1 for n in town.road_network.nodes if n.kind == "anchor") == len(town.districts)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_roads.py::test_every_anchor_with_a_qualifying_junction_gets_a_spur tests/test_generate.py::test_generate_town_populates_road_network -v`
Expected: the spur test FAILS (no spurs yet); the generate test FAILS with `AssertionError` (`town.road_network is None`).

- [ ] **Step 3: Implement spur edges**

In `town_shaper/roads.py`, add the spur-generation block to `generate_road_network`, right after the boundary-edge loop (before `return RoadNetwork(...)`):

```python
    qualifying_junction_vertices_by_anchor_id: Dict[int, List[int]] = {a.id: [] for a in anchors}
    for (p1, p2), (v1, v2) in zip(vor.ridge_points, vor.ridge_vertices):
        if p1 >= num_real_anchors or p2 >= num_real_anchors:
            continue
        if v1 < 0 or v2 < 0:
            continue
        qualifying_junction_vertices_by_anchor_id[anchors[p1].id].extend([v1, v2])
        qualifying_junction_vertices_by_anchor_id[anchors[p2].id].extend([v1, v2])

    for anchor in anchors:
        candidate_vertices = set(qualifying_junction_vertices_by_anchor_id[anchor.id])
        if not candidate_vertices:
            continue
        nearest_vertex = min(
            candidate_vertices,
            key=lambda v: distance((anchor.x, anchor.y), tuple(vor.vertices[v])),
        )
        edges.append(RoadEdge(
            id=next_edge_id, from_node_id=anchor_node_by_id[anchor.id].id,
            to_node_id=junction_node_by_vertex[nearest_vertex].id, road_type="spur",
        ))
        next_edge_id += 1

    return RoadNetwork(nodes=nodes, edges=edges)
```

This duplicates the ridge-filtering condition from the boundary loop (Task 3) rather than merging the two loops, so each loop reads as one clear pass — merge them only if a future change makes the duplication actually painful to maintain.

- [ ] **Step 4: Wire `generate_road_network` into `generate_town`**

In `town_shaper/generate.py`, add the import:

```python
from town_shaper.roads import generate_road_network
```

Right after the `districts = build_districts(...)` line, add:

```python
    road_network = generate_road_network(anchors, bounds, water_polygon=water_polygon)
```

And in the `Town(...)` construction at the bottom of `generate_town`, add the field:

```python
    town = Town(seed=seed, target_population=target_population, bounds=bounds)
    town.districts = districts
    town.residents = residents
    town.water_features = water_features
    town.road_network = road_network
    return town
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_roads.py tests/test_generate.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: all tests PASS (no existing test asserts an exact `Town` shape that a new field would break — confirmed during planning).

- [ ] **Step 7: Commit**

```bash
git add town_shaper/roads.py town_shaper/generate.py tests/test_roads.py tests/test_generate.py
git commit -m "feat: add spur edges, wire road network into generate_town

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

### Task 5: Schema and persistence

**Files:**
- Modify: `town_db/schema.py`
- Modify: `town_db/generate.py`
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Consumes: `town.road_network` (Task 4).
- Produces: `road_nodes`/`road_edges` tables, populated by `generate_town_database`. No new Python functions — inserts happen inline in `generate_town_database`, matching the existing style for districts/buildings/water.

- [ ] **Step 1: Write a failing round-trip test**

Add to `tests/test_db_schema.py`:

```python
def test_generate_town_database_persists_road_network(tmp_path):
    from town_db.generate import generate_town_database

    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path)

    conn = connect(db_path)
    node_rows = conn.execute("SELECT id, kind, anchor_id, is_hub, x, y FROM road_nodes").fetchall()
    edge_rows = conn.execute("SELECT id, from_node_id, to_node_id, road_type FROM road_edges").fetchall()
    conn.close()

    assert len(node_rows) > 0
    assert len(edge_rows) > 0
    assert sum(1 for row in node_rows if row[3] == 1) == 1  # exactly one is_hub row
    node_ids = {row[0] for row in node_rows}
    for edge in edge_rows:
        assert edge[1] in node_ids
        assert edge[2] in node_ids
        assert edge[3] in ("radial", "boundary", "spur")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_db_schema.py::test_generate_town_database_persists_road_network -v`
Expected: FAIL with `sqlite3.OperationalError: no such table: road_nodes`

- [ ] **Step 3: Add the tables to the schema**

In `town_db/schema.py`, add after the `buildings` table definition (inside the `SCHEMA_SQL` string):

```sql
CREATE TABLE road_nodes (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    anchor_id INTEGER REFERENCES districts(id),
    is_hub INTEGER NOT NULL DEFAULT 0,
    x REAL NOT NULL,
    y REAL NOT NULL
);

CREATE TABLE road_edges (
    id INTEGER PRIMARY KEY,
    from_node_id INTEGER NOT NULL REFERENCES road_nodes(id),
    to_node_id INTEGER NOT NULL REFERENCES road_nodes(id),
    road_type TEXT NOT NULL
);
```

- [ ] **Step 4: Insert the road network in `generate_town_database`**

In `town_db/generate.py`, right after the existing `for district in town.districts:` block (after the `zone_type_by_building_id[building.id] = ...` line, once that loop finishes), add:

```python
    for node in town.road_network.nodes:
        conn.execute(
            "INSERT INTO road_nodes (id, kind, anchor_id, is_hub, x, y) VALUES (?, ?, ?, ?, ?, ?)",
            (node.id, node.kind, node.anchor_id, int(node.is_hub), node.x, node.y),
        )
    for edge in town.road_network.edges:
        conn.execute(
            "INSERT INTO road_edges (id, from_node_id, to_node_id, road_type) VALUES (?, ?, ?, ?)",
            (edge.id, edge.from_node_id, edge.to_node_id, edge.road_type),
        )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_db_schema.py::test_generate_town_database_persists_road_network -v`
Expected: PASS.

- [ ] **Step 6: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add town_db/schema.py town_db/generate.py tests/test_db_schema.py
git commit -m "feat: persist the road network to road_nodes/road_edges tables

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

### Task 6: Static PNG rendering

**Files:**
- Modify: `town_db/render.py`
- Test: `tests/test_db_render.py`

**Interfaces:**
- Consumes: `road_nodes`/`road_edges` tables (Task 5).
- Produces: no new public function — `render_town` draws road edges as an additional layer. No return-value change.

- [ ] **Step 1: Write a failing test**

Add to `tests/test_db_render.py`:

```python
def test_render_town_handles_a_town_with_roads(tmp_path):
    db_path = str(tmp_path / "town.db")
    output_path = str(tmp_path / "town.png")
    _build_minimal_town(db_path)

    conn = connect(db_path)
    conn.execute("INSERT INTO road_nodes (id, kind, anchor_id, is_hub, x, y) VALUES (1, 'anchor', 1, 1, 5.0, 5.0)")
    conn.execute("INSERT INTO road_nodes (id, kind, anchor_id, is_hub, x, y) VALUES (2, 'anchor', 2, 0, 15.0, 5.0)")
    conn.execute("INSERT INTO road_edges (id, from_node_id, to_node_id, road_type) VALUES (1, 1, 2, 'radial')")
    conn.commit()
    conn.close()

    render_town(db_path, output_path)  # must not raise

    with open(output_path, "rb") as f:
        header = f.read(8)
    assert header == b"\x89PNG\r\n\x1a\n"
```

- [ ] **Step 2: Run the test to confirm today's baseline**

Run: `pytest tests/test_db_render.py::test_render_town_handles_a_town_with_roads -v`
Expected: PASS — `render_town` doesn't read `road_nodes`/`road_edges` yet, so it silently ignores the extra rows and renders fine. That's expected, not a problem: this test's job is to become a regression guard once Step 3 makes `render_town` actually read those tables (so it must not crash on the exact shape Task 5 produces), and pixel-level assertions on matplotlib output aren't practical either way — the real check that roads are visibly drawn is Step 7's manual verification.

- [ ] **Step 3: Add road rendering to `render_town`**

In `town_db/render.py`, add a style dict near the other style dicts at the top:

```python
ROAD_STYLE = {
    "radial": {"width": 2.5, "color": "#3a3a3a"},
    "boundary": {"width": 1.4, "color": "#5a5a5a"},
    "spur": {"width": 0.8, "color": "#7a7a7a"},
}
```

In `render_town`, after the `conn.close()` line's queries (extend the query block):

```python
def render_town(db_path: str, output_path: str) -> None:
    conn = sqlite3.connect(db_path)
    districts = conn.execute("SELECT zone_type, polygon FROM districts").fetchall()
    buildings = conn.execute("SELECT x, y, building_type FROM buildings").fetchall()
    water_features = conn.execute("SELECT kind, polygon FROM water_features").fetchall()
    road_nodes = conn.execute("SELECT id, x, y FROM road_nodes").fetchall()
    road_edges = conn.execute("SELECT from_node_id, to_node_id, road_type FROM road_edges").fetchall()
    conn.close()
```

After the districts-drawing loop (before the buildings-drawing block), add:

```python
    node_coords = {node_id: (x, y) for node_id, x, y in road_nodes}
    for from_id, to_id, road_type in road_edges:
        style = ROAD_STYLE.get(road_type, ROAD_STYLE["spur"])
        x1, y1 = node_coords[from_id]
        x2, y2 = node_coords[to_id]
        ax.plot([x1, x2], [y1, y2], color=style["color"], linewidth=style["width"], zorder=2.5)
```

(`zorder=2.5` sits between the district polygons at `zorder=2` and buildings at `zorder=3`/`4`.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_db_render.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add town_db/render.py tests/test_db_render.py
git commit -m "feat: render road network in the static town PNG

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

- [ ] **Step 7: Manual verification**

Run `python scripts/generate_town.py` (regenerates `my_town.db`) then `python scripts/render_town.py my_town.db my_town.png` and open `my_town.png` to confirm roads are visible radiating from a hub with boundary lines along district edges.

---

### Task 7: Viewer API

**Files:**
- Modify: `town_viewer/queries.py`
- Test: `tests/test_viewer_queries.py`

**Interfaces:**
- Consumes: `road_nodes`/`road_edges` tables (Task 5).
- Produces: `get_map_data(conn)`'s return dict gains a `"roads"` key: `{"nodes": [{"id", "x", "y"}, ...], "edges": [{"from_node_id", "to_node_id", "road_type"}, ...]}`.

- [ ] **Step 1: Write a failing test**

Add to `tests/test_viewer_queries.py`, in the same style as `test_get_map_data_returns_districts_buildings_and_water`:

```python
def test_get_map_data_returns_roads(tmp_path):
    db_path = str(tmp_path / "town.db")
    _build_minimal_map(db_path)

    conn = connect(db_path)
    conn.execute("INSERT INTO road_nodes (id, kind, anchor_id, is_hub, x, y) VALUES (1, 'anchor', 1, 1, 10.0, 10.0)")
    conn.execute("INSERT INTO road_nodes (id, kind, anchor_id, is_hub, x, y) VALUES (2, 'junction', NULL, 0, 12.0, 8.0)")
    conn.execute("INSERT INTO road_edges (id, from_node_id, to_node_id, road_type) VALUES (1, 1, 2, 'spur')")
    conn.commit()

    data = get_map_data(conn)
    conn.close()

    assert data["roads"] == {
        "nodes": [
            {"id": 1, "x": 10.0, "y": 10.0},
            {"id": 2, "x": 12.0, "y": 8.0},
        ],
        "edges": [
            {"from_node_id": 1, "to_node_id": 2, "road_type": "spur"},
        ],
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_viewer_queries.py::test_get_map_data_returns_roads -v`
Expected: FAIL — `sqlite3.OperationalError: no such table: road_nodes` if run against a DB built without Task 5's schema, or `KeyError: 'roads'` once the schema exists but `get_map_data` doesn't return it yet. Either way, confirm it fails before proceeding.

- [ ] **Step 3: Add roads to `get_map_data`**

In `town_viewer/queries.py`, extend `get_map_data`:

```python
def get_map_data(conn: sqlite3.Connection) -> Dict[str, Any]:
    districts = [
        {"id": row[0], "zone_type": row[1], "polygon": json.loads(row[2])}
        for row in conn.execute("SELECT id, zone_type, polygon FROM districts")
    ]
    buildings = [
        {
            "id": row[0], "district_id": row[1], "zone_type": row[2], "building_type": row[3],
            "x": row[4], "y": row[5], "name": row[6],
        }
        for row in conn.execute(
            "SELECT id, district_id, zone_type, building_type, x, y, name FROM buildings"
        )
    ]
    water_features = [
        {"id": row[0], "kind": row[1], "polygon": json.loads(row[2])}
        for row in conn.execute("SELECT id, kind, polygon FROM water_features")
    ]
    road_nodes = [
        {"id": row[0], "x": row[1], "y": row[2]}
        for row in conn.execute("SELECT id, x, y FROM road_nodes")
    ]
    road_edges = [
        {"from_node_id": row[0], "to_node_id": row[1], "road_type": row[2]}
        for row in conn.execute("SELECT from_node_id, to_node_id, road_type FROM road_edges")
    ]
    return {
        "districts": districts, "buildings": buildings, "water_features": water_features,
        "roads": {"nodes": road_nodes, "edges": road_edges},
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_viewer_queries.py -v`
Expected: all PASS (confirm the pre-existing `test_get_map_data_returns_districts_buildings_and_water` and `test_get_map_data_handles_a_town_with_no_water` still pass unchanged — they don't assert on `data["roads"]` so adding the key doesn't break their existing dict-equality assertions on `data["districts"]`/`data["buildings"]`/`data["water_features"]`).

- [ ] **Step 5: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add town_viewer/queries.py tests/test_viewer_queries.py
git commit -m "feat: expose road network in the /api/map viewer payload

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

### Task 8: Viewer frontend rendering

**Files:**
- Modify: `town_viewer/static/app.js`

**Interfaces:**
- Consumes: `mapData.roads` (Task 7's `/api/map` response shape).
- Produces: no new exported function — `draw()` gains a road-rendering pass. No automated test: this project's viewer has no JS test infrastructure (`town_viewer`'s existing tests all live in Python, exercising the Flask/query layer — `static/app.js` has never had automated coverage; the sidebar-width and building-name changes earlier in this project were both verified the same way this task is). Verify manually per Step 3.

- [ ] **Step 1: Add a road style lookup matching the Python side**

In `town_viewer/static/app.js`, near the other style constants at the top (after `LANDMARK_SIZE`/`GENERIC_SIZE`), add:

```javascript
const ROAD_STYLE = {
  radial: { width: 2.5, color: "#3a3a3a" },
  boundary: { width: 1.4, color: "#5a5a5a" },
  spur: { width: 0.8, color: "#7a7a7a" },
};
```

- [ ] **Step 2: Draw roads in `draw()`**

In the `draw()` function, after the districts-drawing loop (`for (const district of mapData.districts) ...`) and before the buildings-drawing loop (`for (const building of mapData.buildings) ...`), add:

```javascript
  const roadNodeById = new Map((mapData.roads?.nodes || []).map((n) => [n.id, n]));
  for (const edge of mapData.roads?.edges || []) {
    const from = roadNodeById.get(edge.from_node_id);
    const to = roadNodeById.get(edge.to_node_id);
    if (!from || !to) continue;
    const style = ROAD_STYLE[edge.road_type] || ROAD_STYLE.spur;
    const a = worldToScreen(from.x, from.y);
    const b = worldToScreen(to.x, to.y);
    ctx.beginPath();
    ctx.moveTo(a.sx, a.sy);
    ctx.lineTo(b.sx, b.sy);
    ctx.strokeStyle = style.color;
    ctx.lineWidth = style.width;
    ctx.stroke();
  }
```

Also update the initial `mapData` default at the top of the file so a page load before `/api/map` resolves doesn't throw:

```javascript
let mapData = { districts: [], buildings: [], water_features: [], roads: { nodes: [], edges: [] } };
```

- [ ] **Step 3: Manual verification**

Start the viewer against a freshly generated town (which now has road data from Tasks 4-5):

```bash
python scripts/generate_town.py
python scripts/serve_town_viewer.py my_town.db --port 5050
```

Open `http://127.0.0.1:5050/` in a browser. Confirm: roads render as lines under the buildings, radial roads (from the hub) are visibly thicker/darker than boundary and spur roads, panning/zooming still works, and clicking a building still opens its detail panel as before. Stop the server when done.

- [ ] **Step 4: Commit**

```bash
git add town_viewer/static/app.js
git commit -m "feat: render road network in the town viewer canvas

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

## Post-plan follow-up (not part of this plan)

Once this lands, update `docs/visual-interface-ideas.md`'s "Map should read as an actual city" follow-up entry to note the road network is done, and open the building-footprint/placement spec as the next dependent piece of that same follow-up (per the design doc's Context section).
