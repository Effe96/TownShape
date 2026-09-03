# Organic Town Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the town map's straight hub-and-spoke arterial roads and frontage-only lot placement with organic, boundary-following streets and fully-tiled buildings — matching a user-approved mockup — while capping how many buildings become real named businesses so the rewrite doesn't multiply an already-known duplicate-name/unmanageable-count problem.

**Architecture:** Streets inside the urban core become implicit — the gap left between two neighboring districts'/blocks' own inward-inset polygons — instead of a drawn line layer. Arterial roads are rerouted as shortest paths along the real district-boundary graph (smoothed into a curve) and only actually drawn where they cross into `farmland_edge`, which has no inset. Buildings are placed by recursively bisecting each block's polygon until pieces reach a target footprint size, instead of a fixed-size lot strip around the perimeter. A population-scaled cap limits how many tiles become real named/job-bearing buildings per type; the rest render as a generic unnamed infill building.

**Tech Stack:** Python, `shapely` (already a dependency), SQLite, Flask + vanilla JS canvas. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-04-organic-town-rendering-design.md`

## Global Constraints

- No new dependencies.
- `farmland_edge` building placement is untouched — stays on `fill_district_buildings`'s Poisson-disc point placement.
- Determinism: all randomness draws from `rng_for(town_seed, "blocks", district.id, ...)`, the existing per-district seeding convention. The new artery-routing algorithm in `town_shaper/roads.py` is pure geometry (BFS + smoothing) with no randomness at all — it must produce identical output for identical input with no seed involved.
- Business density caps: `tavern` = `population ÷ 1000`; `shop`, `town_hall`, `harbormaster_office` = flat caps (100, 1, 1); every other named type (has a `BUILDING_NAME_POOLS` entry) defaults to `population ÷ 2000`. All caps are `max(1, round(...))`.
- Landmark-type buildings' existing marker/color rendering (both renderers) is unchanged by this plan — building-drawing code isn't touched at all, only the road-style tables.

---

### Task 1: `inset_polygon` helper in `geometry.py`

**Files:**
- Modify: `town_shaper/geometry.py`
- Test: `tests/test_geometry.py`

**Interfaces:**
- Produces: `inset_polygon(polygon: Polygon, distance: float) -> Polygon` — insets every edge of `polygon` inward by `distance`, built from the existing `clip_polygon_by_line` primitive. Used by `town_shaper/blocks.py` (Task 6) to create street gaps between neighboring districts.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_geometry.py`:

```python
from town_shaper.geometry import inset_polygon


def test_inset_polygon_shrinks_a_square_by_twice_the_distance_per_side():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    result = inset_polygon(square, 2.0)
    assert math.isclose(polygon_area(result), 6.0 * 6.0, rel_tol=1e-9)
    for x, y in result:
        assert 2.0 - 1e-9 <= x <= 8.0 + 1e-9
        assert 2.0 - 1e-9 <= y <= 8.0 + 1e-9


def test_inset_polygon_returns_empty_when_distance_exceeds_the_polygon():
    small_square = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    assert inset_polygon(small_square, 10.0) == []


def test_inset_polygon_zero_distance_returns_the_same_shape():
    triangle = [(0.0, 0.0), (10.0, 0.0), (5.0, 8.0)]
    result = inset_polygon(triangle, 0.0)
    assert math.isclose(polygon_area(result), polygon_area(triangle), rel_tol=1e-9)
```

Check `tests/test_geometry.py`'s existing imports — `math` and `polygon_area` are already imported for other tests in this file; add `inset_polygon` to the existing `from town_shaper.geometry import ...` line rather than a new import line.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_geometry.py::test_inset_polygon_shrinks_a_square_by_twice_the_distance_per_side tests/test_geometry.py::test_inset_polygon_returns_empty_when_distance_exceeds_the_polygon tests/test_geometry.py::test_inset_polygon_zero_distance_returns_the_same_shape -v`
Expected: FAIL with `ImportError: cannot import name 'inset_polygon'`

- [ ] **Step 3: Implement `inset_polygon`**

In `town_shaper/geometry.py`, add after `clip_polygon_to_bounds`:

```python
def inset_polygon(polygon: Polygon, distance: float) -> Polygon:
    """Insets every edge of `polygon` inward by `distance` -- same
    Sutherland-Hodgman pattern clip_polygon_to_bounds uses against a
    rectangle's 4 edges, generalized to polygon's own N edges. Each edge's
    line is shifted along its own inward (left-of-the-directed-edge, per
    _is_inside_edge's convention) normal, then the polygon is clipped
    against that shifted line in turn."""
    n = len(polygon)
    offset_edges: List[Tuple[Point, Point]] = []
    for i in range(n):
        v0 = polygon[i]
        v1 = polygon[(i + 1) % n]
        dx, dy = v1[0] - v0[0], v1[1] - v0[1]
        length = math.hypot(dx, dy)
        if length == 0:
            offset_edges.append((v0, v1))
            continue
        nx, ny = (-dy / length) * distance, (dx / length) * distance
        offset_edges.append(((v0[0] + nx, v0[1] + ny), (v1[0] + nx, v1[1] + ny)))

    output = list(polygon)
    for edge_start, edge_end in offset_edges:
        if not output:
            break
        output = clip_polygon_by_line(output, edge_start, edge_end)
    return output
```

- [ ] **Step 4: Run the tests to verify they pass, then the full geometry suite**

Run: `pytest tests/test_geometry.py -v`
Expected: all PASS, including the three new ones.

- [ ] **Step 5: Commit**

```bash
git add town_shaper/geometry.py tests/test_geometry.py
git commit -m "feat: add inset_polygon helper for street-gap generation

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KXcw4JjtMgv8z8tZf7cLHC"
```

---

### Task 2: Replace straight `radial` arterial roads with boundary-following `artery` paths

**Files:**
- Modify: `town_shaper/roads.py`
- Modify: `town_shaper/models.py:99-103` (`RoadEdge.road_type` docstring comment)
- Test: `tests/test_roads.py`

**Interfaces:**
- Consumes: `ZoneType.FARMLAND_EDGE` (`town_shaper.models`).
- Produces: `generate_road_network` (signature unchanged) now emits `road_type="artery"` instead of `"radial"`, only for path segments that cross into a zone with no block-inset (`farmland_edge`). `boundary` and `spur` edge generation is unchanged. No new public functions.

- [ ] **Step 1: Update the `RoadEdge` docstring comment**

In `town_shaper/models.py`, change:

```python
@dataclass
class RoadEdge:
    id: int
    from_node_id: int
    to_node_id: int
    road_type: str                  # "radial" | "boundary" | "spur"
```

to:

```python
@dataclass
class RoadEdge:
    id: int
    from_node_id: int
    to_node_id: int
    road_type: str                  # "artery" | "boundary" | "spur"
```

- [ ] **Step 2: Write failing tests**

In `tests/test_roads.py`, **delete** `test_every_anchor_has_a_radial_edge_to_the_hub` and `test_graph_is_fully_connected_via_radial_edges_alone` (they test the straight-hub-to-every-anchor mechanism being removed). Keep every other existing test unchanged. Add:

```python
def test_no_artery_edges_when_all_anchors_are_urban():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = [
        _anchor(0, ZoneType.CIVIC, x=0.0, y=0.0),
        _anchor(1, ZoneType.MERCHANT, x=40.0, y=0.0),
        _anchor(2, ZoneType.POOR_RESIDENTIAL, x=-40.0, y=0.0),
        _anchor(3, ZoneType.RICH_RESIDENTIAL, x=0.0, y=40.0),
    ]
    network = generate_road_network(anchors, bounds)

    artery_edges = [e for e in network.edges if e.road_type == "artery"]
    assert artery_edges == []


def test_artery_edges_reach_a_farmland_anchor():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = [
        _anchor(0, ZoneType.CIVIC, x=0.0, y=0.0),
        _anchor(1, ZoneType.MERCHANT, x=40.0, y=0.0),
        _anchor(2, ZoneType.POOR_RESIDENTIAL, x=-40.0, y=0.0),
        _anchor(3, ZoneType.FARMLAND_EDGE, x=0.0, y=40.0),
    ]
    network = generate_road_network(anchors, bounds)

    artery_edges = [e for e in network.edges if e.road_type == "artery"]
    assert artery_edges

    hub_node_id = next(n.id for n in network.nodes if n.is_hub)
    farmland_node_id = next(n.id for n in network.nodes if n.kind == "anchor" and n.anchor_id == 3)

    adjacency = {}
    for e in network.edges:
        if e.road_type in ("artery", "boundary", "spur"):
            adjacency.setdefault(e.from_node_id, []).append(e.to_node_id)
            adjacency.setdefault(e.to_node_id, []).append(e.from_node_id)
    visited = {hub_node_id}
    frontier = [hub_node_id]
    while frontier:
        current = frontier.pop()
        for neighbor in adjacency.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                frontier.append(neighbor)
    assert farmland_node_id in visited


def test_no_artery_edge_runs_between_two_urban_anchors():
    # An artery edge should only ever appear on the tail of a path that
    # touches farmland -- never as a redundant line drawn between two
    # already block-inset urban districts (that gap is already a street).
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = [
        _anchor(0, ZoneType.CIVIC, x=0.0, y=0.0),
        _anchor(1, ZoneType.MERCHANT, x=40.0, y=0.0),
        _anchor(2, ZoneType.MERCHANT, x=-40.0, y=0.0),
        _anchor(3, ZoneType.FARMLAND_EDGE, x=0.0, y=40.0),
    ]
    network = generate_road_network(anchors, bounds)

    urban_anchor_node_ids = {
        n.id for n in network.nodes
        if n.kind == "anchor" and n.anchor_id in (0, 1, 2)
    }
    for edge in network.edges:
        if edge.road_type == "artery":
            assert not (edge.from_node_id in urban_anchor_node_ids and edge.to_node_id in urban_anchor_node_ids)


def test_artery_routing_is_deterministic():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    from town_shaper.anchors import place_anchors
    anchors = place_anchors(("town", 4), 4000, bounds)

    network1 = generate_road_network(anchors, bounds)
    network2 = generate_road_network(anchors, bounds)

    key = lambda n: sorted((e.from_node_id, e.to_node_id, e.road_type) for e in n.edges)
    assert key(network1) == key(network2)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_roads.py -v`
Expected: the two new farmland/artery tests FAIL (no `artery` road_type exists yet); `test_no_artery_edges_when_all_anchors_are_urban` incorrectly PASSES for the wrong reason (no `radial` edges are `artery` either, since that type doesn't exist) -- this is expected and will become a real assertion once Step 4 lands.

- [ ] **Step 4: Replace radial generation with BFS + smoothed artery routing**

In `town_shaper/roads.py`, replace the whole file:

```python
import math
from collections import deque
from typing import Dict, FrozenSet, List, Optional, Tuple

from town_shaper.districts import compute_voronoi
from town_shaper.geometry import distance
from town_shaper.models import Anchor, RoadEdge, RoadNetwork, RoadNode, ZoneType


def _choose_hub_anchor(anchors: List[Anchor], bounds: Tuple[float, float, float, float]) -> Anchor:
    min_x, min_y, max_x, max_y = bounds
    center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
    civic_anchors = [a for a in anchors if a.zone_type == ZoneType.CIVIC]
    candidates = civic_anchors if civic_anchors else anchors
    return min(candidates, key=lambda a: distance(center, (a.x, a.y)))


def _bfs_path(adjacency: Dict[int, List[int]], start: int, goal: int) -> Optional[List[int]]:
    if start == goal:
        return [start]
    visited = {start}
    parent: Dict[int, int] = {}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            parent[neighbor] = current
            if neighbor == goal:
                path = [goal]
                while path[-1] != start:
                    path.append(parent[path[-1]])
                path.reverse()
                return path
            queue.append(neighbor)
    return None


def _chaikin_smooth(points: List[Tuple[float, float]], iterations: int = 2) -> List[Tuple[float, float]]:
    """Corner-cutting smoothing that keeps the first and last point fixed
    (an anchor's own position shouldn't move), same spirit as the
    reference generator's post-routing street smoothing."""
    for _ in range(iterations):
        if len(points) < 3:
            return points
        smoothed = [points[0]]
        for i in range(len(points) - 1):
            p0, p1 = points[i], points[i + 1]
            smoothed.append((0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]))
            smoothed.append((0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]))
        smoothed.append(points[-1])
        points = smoothed
    return points


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

    # Adjacency graph of boundary+spur edges only -- what artery routing
    # (below) paths through -- plus, per hop, whether either side touches
    # a zone with no block-inset (farmland_edge), which decides whether
    # that hop needs an actual drawn line.
    adjacency: Dict[int, List[int]] = {}
    hop_touches_farmland: Dict[FrozenSet[int], bool] = {}

    def _add_adjacency(a: int, b: int, touches_farmland: bool) -> None:
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
        hop_touches_farmland[frozenset((a, b))] = touches_farmland

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
        touches_farmland = (
            anchors[p1].zone_type == ZoneType.FARMLAND_EDGE or anchors[p2].zone_type == ZoneType.FARMLAND_EDGE
        )
        _add_adjacency(node1.id, node2.id, touches_farmland)

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
        anchor_node = anchor_node_by_id[anchor.id]
        junction_node = junction_node_by_vertex[nearest_vertex]
        edges.append(RoadEdge(
            id=next_edge_id, from_node_id=anchor_node.id,
            to_node_id=junction_node.id, road_type="spur",
        ))
        next_edge_id += 1
        _add_adjacency(anchor_node.id, junction_node.id, anchor.zone_type == ZoneType.FARMLAND_EDGE)

    # Artery routing -- replaces straight radial edges. Drawn only for the
    # tail of a path that actually touches farmland_edge; everywhere else
    # the gap between inset urban blocks already reads as a street.
    #
    # Known limitation: two nearby farmland anchors routed via a shared
    # urban gateway will each draw their own full tail from that gateway,
    # which can produce a short overlapping stretch rather than a single
    # shared one. Cosmetic (renders as a slightly thicker stretch, not a
    # wrong one), not fixed in this pass.
    hub_node = anchor_node_by_id[hub.id]
    node_by_id: Dict[int, RoadNode] = {n.id: n for n in nodes}

    for anchor in anchors:
        if anchor.id == hub.id:
            continue
        target_node = anchor_node_by_id[anchor.id]
        path = _bfs_path(adjacency, hub_node.id, target_node.id)
        if path is None or len(path) < 2:
            continue

        tail_start_index = None
        for i in range(len(path) - 1):
            if hop_touches_farmland.get(frozenset((path[i], path[i + 1]))):
                tail_start_index = i
                break
        if tail_start_index is None:
            continue

        tail_node_ids = path[tail_start_index:]
        tail_points = [(node_by_id[nid].x, node_by_id[nid].y) for nid in tail_node_ids]
        smoothed_points = _chaikin_smooth(tail_points, iterations=2)

        artery_node_ids = [tail_node_ids[0]]
        for point in smoothed_points[1:-1]:
            new_node = RoadNode(id=next_node_id, kind="junction", x=point[0], y=point[1])
            next_node_id += 1
            nodes.append(new_node)
            artery_node_ids.append(new_node.id)
        artery_node_ids.append(tail_node_ids[-1])

        for a, b in zip(artery_node_ids, artery_node_ids[1:]):
            edges.append(RoadEdge(id=next_edge_id, from_node_id=a, to_node_id=b, road_type="artery"))
            next_edge_id += 1

    return RoadNetwork(nodes=nodes, edges=edges)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_roads.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: `tests/test_generate.py::test_generate_town_road_network_includes_local_streets` is the only failure (it tests the `local` road type, which Task 3 removes) -- confirm no other test fails. If anything else fails, stop and investigate before continuing.

- [ ] **Step 7: Commit**

```bash
git add town_shaper/roads.py town_shaper/models.py tests/test_roads.py
git commit -m "feat: route arterial roads along district boundaries instead of straight hub-and-spoke lines

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KXcw4JjtMgv8z8tZf7cLHC"
```

---

### Task 3: Simplify `subdivide_into_blocks` -- drop local road generation

**Files:**
- Modify: `town_shaper/blocks.py`
- Test: `tests/test_blocks.py`

**Interfaces:**
- Produces: `subdivide_into_blocks(polygon_part: Polygon, zone_type: ZoneType, rng) -> List[Polygon]` (was `Tuple[List[Polygon], List[RoadNode], List[RoadEdge], int, int]`) -- the gap between two split halves is still real geometry (`_split_polygon`'s existing offset cut), it just no longer gets a `RoadNode`/`RoadEdge` pair drawn through it.

- [ ] **Step 1: Update failing/obsolete tests**

In `tests/test_blocks.py`, **delete** `test_subdivide_into_blocks_produces_one_local_edge_per_split`, `test_subdivide_into_blocks_ids_are_threaded_without_collision`, `test_subdivide_into_blocks_local_street_endpoints_stay_near_the_polygon`, and `test_local_street_endpoints_handles_non_convex_polygons` (they test node/edge production and `_local_street_endpoints`, both removed this task).

Replace the three remaining `subdivide_into_blocks` tests (`test_subdivide_into_blocks_returns_original_when_already_small`, `test_subdivide_into_blocks_respects_target_area`, `test_subdivide_into_blocks_conserves_area_within_street_gaps`, `test_subdivide_into_blocks_is_deterministic`) with:

```python
def test_subdivide_into_blocks_returns_original_when_already_small():
    small_square = _square(5.0)  # area 25, well under any zone's target
    rng = rng_for(("town", 1), "blocks-test", 1)

    blocks = subdivide_into_blocks(small_square, ZoneType.MERCHANT, rng)

    assert blocks == [small_square]


def test_subdivide_into_blocks_respects_target_area():
    large_square = _square(100.0)  # area 10000
    target_area = TARGET_BLOCK_AREA_BY_ZONE[ZoneType.MERCHANT]
    rng = rng_for(("town", 1), "blocks-test", 2)

    blocks = subdivide_into_blocks(large_square, ZoneType.MERCHANT, rng)

    assert len(blocks) > 1
    for block in blocks:
        assert polygon_area(block) <= target_area


def test_subdivide_into_blocks_conserves_area_within_street_gaps():
    large_square = _square(100.0)
    rng = rng_for(("town", 1), "blocks-test", 3)

    blocks = subdivide_into_blocks(large_square, ZoneType.MERCHANT, rng)

    original_area = polygon_area(large_square)
    total_block_area = sum(polygon_area(b) for b in blocks)
    assert total_block_area <= original_area
    assert total_block_area >= original_area * 0.6


def test_subdivide_into_blocks_is_deterministic():
    large_square = _square(100.0)

    rng1 = rng_for(("town", 1), "blocks-test", 6)
    blocks1 = subdivide_into_blocks(large_square, ZoneType.MERCHANT, rng1)
    rng2 = rng_for(("town", 1), "blocks-test", 6)
    blocks2 = subdivide_into_blocks(large_square, ZoneType.MERCHANT, rng2)

    assert [sorted(b) for b in blocks1] == [sorted(b) for b in blocks2]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_blocks.py -v -k subdivide_into_blocks`
Expected: FAIL (`subdivide_into_blocks` still returns a 5-tuple, unpacking into 1 variable raises `TypeError`).

- [ ] **Step 3: Simplify `_split_polygon` and `subdivide_into_blocks`**

In `town_shaper/blocks.py`, update the top-of-file import line -- `RoadEdge`/`RoadNode` are no longer constructed anywhere in this module once this task's changes land:

```python
from town_shaper.models import Building, District, JobVacancy, ZoneType
```

Replace `_split_polygon` (drop the returned cut-line, generalize the hardcoded `LOCAL_STREET_WIDTH` to a `gap` parameter so Task 5 can reuse it for building subdivision with a different gap):

```python
def _split_polygon(polygon: Polygon, rng, gap: float) -> Tuple[Polygon, Polygon]:
    """Split `polygon` into two halves along its longer OBB axis, offset by `gap`."""
    axis_dir = _longer_axis_direction(polygon)
    split_dir = (-axis_dir[1], axis_dir[0])  # perpendicular to the longer axis
    cx, cy = _polygon_centroid(polygon)

    span = max((distance(p, q) for p in polygon for q in polygon), default=0.0) + 1.0
    split_fraction = rng.uniform(0.4, 0.6)
    offset_along_axis = (split_fraction - 0.5) * span
    center = (cx + axis_dir[0] * offset_along_axis, cy + axis_dir[1] * offset_along_axis)

    line_start = (center[0] - split_dir[0] * span, center[1] - split_dir[1] * span)
    line_end = (center[0] + split_dir[0] * span, center[1] + split_dir[1] * span)

    half_gap = gap / 2.0
    offset_a = (axis_dir[0] * half_gap, axis_dir[1] * half_gap)
    offset_b = (-offset_a[0], -offset_a[1])

    side_a = clip_polygon_by_line(
        polygon,
        (line_start[0] + offset_b[0], line_start[1] + offset_b[1]),
        (line_end[0] + offset_b[0], line_end[1] + offset_b[1]),
    )
    side_b = clip_polygon_by_line(
        polygon,
        (line_end[0] + offset_a[0], line_end[1] + offset_a[1]),
        (line_start[0] + offset_a[0], line_start[1] + offset_a[1]),
    )
    return side_a, side_b
```

Delete `_distance_to_line` and `_local_street_endpoints` entirely (only `_local_street_endpoints` used them, and it's being removed).

Replace `subdivide_into_blocks` and `_subdivide`:

```python
def subdivide_into_blocks(polygon_part: Polygon, zone_type: ZoneType, rng) -> List[Polygon]:
    """Recursively split `polygon_part` into blocks for `zone_type`. Each
    split leaves a real LOCAL_STREET_WIDTH gap between the two halves
    (via _split_polygon's offset cut) -- that gap is the street; no
    RoadNode/RoadEdge rows are produced for it."""
    return _subdivide(polygon_part, TARGET_BLOCK_AREA_BY_ZONE[zone_type], rng, depth=0)


def _subdivide(polygon_part: Polygon, target_area: float, rng, depth: int) -> List[Polygon]:
    if len(polygon_part) < 3 or polygon_area(polygon_part) <= target_area or depth >= MAX_SPLIT_DEPTH:
        return [polygon_part]

    side_a, side_b = _split_polygon(polygon_part, rng, LOCAL_STREET_WIDTH)
    if len(side_a) < 3 or len(side_b) < 3:
        return [polygon_part]

    return _subdivide(side_a, target_area, rng, depth + 1) + _subdivide(side_b, target_area, rng, depth + 1)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_blocks.py -v -k subdivide_into_blocks`
Expected: all PASS. (`place_buildings_in_block`/`generate_blocks_and_buildings` tests further down the file will still fail -- Tasks 4-6 fix those. That's expected at this point.)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/blocks.py tests/test_blocks.py
git commit -m "refactor: subdivide_into_blocks no longer emits RoadNode/RoadEdge rows

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KXcw4JjtMgv8z8tZf7cLHC"
```

---

### Task 4: Business density cap in `town_shaper/buildings.py`

**Files:**
- Modify: `town_shaper/buildings.py`
- Test: `tests/test_buildings.py`

**Interfaces:**
- Produces: `notable_building_cap(building_type: str, target_population: int) -> int`; `pick_building_type_with_cap(zone_type: ZoneType, target_population: int, magic_prevalence: float, rng, notable_building_counts: Dict[str, int]) -> str`; module constants `NOTABLE_BUILDING_CAP_RATIO`, `DEFAULT_NOTABLE_BUILDING_CAP_RATIO`, `NOTABLE_BUILDING_FLAT_CAP`, `INFILL_BUILDING_TYPE_BY_ZONE`. Consumed by `town_shaper/blocks.py`'s `place_buildings_in_block` (Task 5).

- [ ] **Step 1: Write failing tests**

Add to `tests/test_buildings.py`:

```python
def test_notable_building_cap_uses_flat_cap_when_one_is_set():
    from town_shaper.buildings import notable_building_cap
    assert notable_building_cap("shop", target_population=50000) == 100
    assert notable_building_cap("town_hall", target_population=50000) == 1


def test_notable_building_cap_scales_tavern_with_population():
    from town_shaper.buildings import notable_building_cap
    assert notable_building_cap("tavern", target_population=5000) == 5
    assert notable_building_cap("tavern", target_population=500) == 1  # max(1, round(0.5))


def test_notable_building_cap_defaults_unlisted_named_types_to_population_over_2000():
    from town_shaper.buildings import notable_building_cap
    assert notable_building_cap("temple", target_population=6000) == 3


def test_pick_building_type_with_cap_excludes_a_type_once_its_cap_is_reached():
    from town_shaper.buildings import notable_building_cap, pick_building_type_with_cap

    rng = rng_for(("town", 1), "buildings-test", 1)
    target_population = 5000
    cap = notable_building_cap("tavern", target_population)
    notable_building_counts = {"tavern": cap}

    for _ in range(50):
        building_type = pick_building_type_with_cap(
            ZoneType.MERCHANT, target_population, magic_prevalence=0.0, rng=rng,
            notable_building_counts=notable_building_counts,
        )
        assert building_type != "tavern"


def test_pick_building_type_with_cap_falls_back_to_infill_once_every_named_type_is_capped():
    from town_shaper.buildings import (
        BUILDING_TYPES_BY_ZONE, INFILL_BUILDING_TYPE_BY_ZONE, notable_building_cap, pick_building_type_with_cap,
    )

    rng = rng_for(("town", 1), "buildings-test", 2)
    target_population = 5000
    notable_building_counts = {
        bt: notable_building_cap(bt, target_population) for bt in BUILDING_TYPES_BY_ZONE[ZoneType.MERCHANT]
    }

    building_type = pick_building_type_with_cap(
        ZoneType.MERCHANT, target_population, magic_prevalence=0.0, rng=rng,
        notable_building_counts=notable_building_counts,
    )

    assert building_type == INFILL_BUILDING_TYPE_BY_ZONE[ZoneType.MERCHANT]


def test_pick_building_type_with_cap_increments_the_running_count():
    from town_shaper.buildings import pick_building_type_with_cap

    rng = rng_for(("town", 1), "buildings-test", 3)
    notable_building_counts = {}

    building_type = pick_building_type_with_cap(
        ZoneType.RICH_RESIDENTIAL, target_population=3000, magic_prevalence=0.0, rng=rng,
        notable_building_counts=notable_building_counts,
    )

    assert building_type == "manor"  # only weighted type for this zone
    assert notable_building_counts == {}  # "manor" has no BUILDING_NAME_POOLS entry -- never counted
```

Check `tests/test_buildings.py`'s existing imports for `rng_for` and `ZoneType` -- both are already used by other tests in this file; reuse those import lines rather than adding new ones.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_buildings.py -v -k "notable_building_cap or pick_building_type_with_cap"`
Expected: FAIL with `ImportError: cannot import name 'notable_building_cap'`

- [ ] **Step 3: Implement the cap mechanism**

In `town_shaper/buildings.py`, add near `BUILDING_HOME_CAPACITY`:

```python
NOTABLE_BUILDING_CAP_RATIO: Dict[str, float] = {
    "tavern": 1 / 1000,
}
DEFAULT_NOTABLE_BUILDING_CAP_RATIO = 1 / 2000
NOTABLE_BUILDING_FLAT_CAP: Dict[str, int] = {
    "shop": 100,
    "town_hall": 1,
    "harbormaster_office": 1,
}
INFILL_BUILDING_TYPE_BY_ZONE: Dict[ZoneType, str] = {
    ZoneType.CIVIC: "workshop",
    ZoneType.MERCHANT: "workshop",
    ZoneType.PORT: "workshop",
}
```

Add `"workshop": []` to `JOB_VACANCIES_BY_BUILDING_TYPE` (the generic infill building carries no job vacancies).

Add, after `resolve_building_type_weights`:

```python
def notable_building_cap(building_type: str, target_population: int) -> int:
    if building_type in NOTABLE_BUILDING_FLAT_CAP:
        return NOTABLE_BUILDING_FLAT_CAP[building_type]
    ratio = NOTABLE_BUILDING_CAP_RATIO.get(building_type, DEFAULT_NOTABLE_BUILDING_CAP_RATIO)
    return max(1, round(target_population * ratio))


def pick_building_type_with_cap(
    zone_type: ZoneType, target_population: int, magic_prevalence: float, rng,
    notable_building_counts: Dict[str, int],
) -> str:
    """Like resolve_building_type_weights + a weighted draw, but any type
    with a BUILDING_NAME_POOLS entry ("notable") that has already reached
    its notable_building_cap is excluded from this tile's draw -- not
    re-rolled into a different type, so capping one type doesn't shift
    density onto the zone's other types. Once every weighted type for
    this zone is capped, falls back to the zone's plain infill type."""
    type_weights = resolve_building_type_weights(zone_type, target_population, magic_prevalence, rng)
    available = {
        building_type: weight for building_type, weight in type_weights.items()
        if building_type not in BUILDING_NAME_POOLS
        or notable_building_counts.get(building_type, 0) < notable_building_cap(building_type, target_population)
    }
    if not available:
        return INFILL_BUILDING_TYPE_BY_ZONE[zone_type]

    subtypes = list(available.keys())
    weights = list(available.values())
    building_type = rng.choices(subtypes, weights=weights, k=1)[0]
    if building_type in BUILDING_NAME_POOLS:
        notable_building_counts[building_type] = notable_building_counts.get(building_type, 0) + 1
    return building_type
```

- [ ] **Step 4: Run the tests to verify they pass, then the full buildings suite**

Run: `pytest tests/test_buildings.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add town_shaper/buildings.py tests/test_buildings.py
git commit -m "feat: cap named/business buildings by population, add generic infill fallback

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KXcw4JjtMgv8z8tZf7cLHC"
```

---

### Task 5: Rewrite `place_buildings_in_block` for recursive tiling

**Files:**
- Modify: `town_shaper/blocks.py`
- Test: `tests/test_blocks.py`

**Interfaces:**
- Consumes: `pick_building_type_with_cap` (Task 4); `_split_polygon` (Task 3, now takes a `gap` parameter).
- Produces: `place_buildings_in_block(block_polygon, district, rng, next_building_id, target_population, magic_prevalence, notable_building_counts=None, density_multiplier=1.0) -> List[Building]` -- buildings now fully tile the block instead of a frontage strip.

- [ ] **Step 1: Update failing/obsolete tests**

In `tests/test_blocks.py`:

Replace `test_place_buildings_in_block_footprints_stay_within_the_block`, `test_place_buildings_in_block_footprints_dont_overlap`, `test_place_buildings_in_block_is_deterministic`, `test_place_buildings_in_block_density_multiplier_scales_lot_size` with versions that pass `notable_building_counts={}` explicitly (the parameter now exists but defaults to `None`/fresh-per-call, so these are safe to leave positionally the same otherwise):

```python
def test_place_buildings_in_block_footprints_stay_within_the_block():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 10)

    buildings = place_buildings_in_block(
        block, district, rng, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )

    assert len(buildings) > 0
    block_shape = ShapelyPolygon(block).buffer(0.5)
    for building in buildings:
        assert block_shape.contains(_footprint_shape(building))


def test_place_buildings_in_block_footprints_dont_overlap():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 11)

    buildings = place_buildings_in_block(
        block, district, rng, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )

    shapes = [_footprint_shape(b) for b in buildings]
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            assert shapes[i].intersection(shapes[j]).area < 1e-6


def test_place_buildings_in_block_footprints_stay_axis_aligned_for_a_rectangular_block():
    # A recursive axis-perpendicular bisection of a rectangle should keep
    # every resulting leaf's rotation at 0 or 90 degrees relative to the
    # original block, regardless of how many times it's been split.
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 12)

    buildings = place_buildings_in_block(
        block, district, rng, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )

    assert buildings
    for b in buildings:
        remainder = abs(b.rotation) % (math.pi / 2)
        assert remainder < 1e-6 or (math.pi / 2 - remainder) < 1e-6


def test_place_buildings_in_block_is_deterministic():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)

    rng1 = rng_for(("town", 1), "blocks-test", 13)
    b1 = place_buildings_in_block(
        block, district, rng1, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )
    rng2 = rng_for(("town", 1), "blocks-test", 13)
    b2 = place_buildings_in_block(
        block, district, rng2, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )

    key = lambda buildings: [(b.x, b.y, b.width, b.height, b.rotation, b.building_type) for b in buildings]
    assert key(b1) == key(b2)


def test_place_buildings_in_block_density_multiplier_scales_building_count():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)

    rng_sparse = rng_for(("town", 1), "blocks-test", 14)
    sparse = place_buildings_in_block(
        block, district, rng_sparse, 0, target_population=3000, magic_prevalence=0.0,
        notable_building_counts={}, density_multiplier=0.5,
    )
    rng_dense = rng_for(("town", 1), "blocks-test", 14)
    dense = place_buildings_in_block(
        block, district, rng_dense, 0, target_population=3000, magic_prevalence=0.0,
        notable_building_counts={}, density_multiplier=2.0,
    )

    assert len(dense) > len(sparse)


def test_place_buildings_in_block_respects_notable_building_cap():
    from town_shaper.blocks import place_buildings_in_block
    from town_shaper.buildings import notable_building_cap

    block = _rectangle(60.0, 60.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 21)
    target_population = 3000
    cap = notable_building_cap("tavern", target_population)
    notable_building_counts = {"tavern": cap}

    buildings = place_buildings_in_block(
        block, district, rng, 0, target_population=target_population, magic_prevalence=0.0,
        notable_building_counts=notable_building_counts,
    )

    assert all(b.building_type != "tavern" for b in buildings)
    assert notable_building_counts["tavern"] == cap


def test_place_buildings_in_block_uses_infill_type_once_all_named_types_are_capped():
    from town_shaper.blocks import place_buildings_in_block
    from town_shaper.buildings import BUILDING_TYPES_BY_ZONE, INFILL_BUILDING_TYPE_BY_ZONE, notable_building_cap

    block = _rectangle(60.0, 60.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 22)
    target_population = 3000
    notable_building_counts = {
        bt: notable_building_cap(bt, target_population) for bt in BUILDING_TYPES_BY_ZONE[ZoneType.MERCHANT]
    }

    buildings = place_buildings_in_block(
        block, district, rng, 0, target_population=target_population, magic_prevalence=0.0,
        notable_building_counts=notable_building_counts,
    )

    assert buildings
    infill_type = INFILL_BUILDING_TYPE_BY_ZONE[ZoneType.MERCHANT]
    assert all(b.building_type == infill_type for b in buildings)
    assert all(b.name is None for b in buildings)
    assert all(b.capacity == 0 for b in buildings)
```

**Delete** `test_place_buildings_in_block_rotation_matches_frontage_edge` (replaced by the axis-aligned test above, which expresses the same invariant without assuming the old frontage-strip mechanism) and `test_place_buildings_in_block_skips_footprints_that_would_exit_a_narrow_block` (tested a frontage-strip-specific corner case -- the new recursive-subdivision algorithm can't produce a footprint outside its own block by construction, so this scenario no longer applies).

Add `import math` to the top of `tests/test_blocks.py` if not already present (it's already imported, used by `_footprint_shape`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_blocks.py -v -k place_buildings_in_block`
Expected: FAIL (`place_buildings_in_block` doesn't accept `notable_building_counts` yet).

- [ ] **Step 3: Implement recursive tiling**

In `town_shaper/blocks.py`, change the imports at the top:

```python
import math
from typing import Dict, List, Optional, Tuple

from shapely.geometry import Polygon as ShapelyPolygon

from town_shaper.buildings import (
    BUILDING_HOME_CAPACITY, BUILDING_NAME_POOLS, JOB_VACANCIES_BY_BUILDING_TYPE, pick_building_type_with_cap,
)
from town_shaper.geometry import clip_polygon_by_line, distance, polygon_area
from town_shaper.models import Building, District, JobVacancy, ZoneType
from town_shaper.seeding import rng_for
```

(`point_in_polygon` was only used by `_perpendicular_into_polygon`, deleted below. `resolve_building_type_weights` is no longer called directly from this file either -- `place_buildings_in_block` now goes through `pick_building_type_with_cap`, which calls `resolve_building_type_weights` internally on `buildings.py`'s side.)

Add near `LOCAL_STREET_WIDTH`:

```python
BUILDING_GAP = 0.4
```

Delete `_perpendicular_into_polygon` and `_building_footprint_polygon` entirely (perimeter-frontage placement and per-building overlap checking are both obsolete -- the new recursive partition can't produce overlapping leaves by construction).

Add, after `_split_polygon`:

```python
def _subdivide_into_buildings(block_polygon: Polygon, target_area: float, rng, depth: int = 0) -> List[Polygon]:
    if len(block_polygon) < 3 or depth >= MAX_SPLIT_DEPTH or polygon_area(block_polygon) <= target_area:
        return [block_polygon]

    side_a, side_b = _split_polygon(block_polygon, rng, BUILDING_GAP)
    if len(side_a) < 3 or len(side_b) < 3:
        return [block_polygon]

    return (
        _subdivide_into_buildings(side_a, target_area, rng, depth + 1)
        + _subdivide_into_buildings(side_b, target_area, rng, depth + 1)
    )


def _leaf_footprint(leaf: Polygon) -> Tuple[float, float, float, float, float]:
    """Center (x, y), width, height, and rotation of `leaf`'s minimum
    rotated rectangle -- same OBB approach _longer_axis_direction uses."""
    shapely_leaf = ShapelyPolygon(leaf)
    obb = shapely_leaf.minimum_rotated_rectangle
    corners = list(obb.exterior.coords)[:-1]
    if len(corners) < 4:
        cx, cy = _polygon_centroid(leaf)
        return (cx, cy, 1.0, 1.0, 0.0)
    edge_a = distance(corners[0], corners[1])
    edge_b = distance(corners[1], corners[2])
    width, height = (edge_a, edge_b) if edge_a >= edge_b else (edge_b, edge_a)
    p1, p2 = (corners[0], corners[1]) if edge_a >= edge_b else (corners[1], corners[2])
    rotation = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    center = obb.centroid
    return (center.x, center.y, width, height, rotation)
```

Replace `place_buildings_in_block`:

```python
def place_buildings_in_block(
    block_polygon: Polygon, district: District, rng,
    next_building_id: int, target_population: int, magic_prevalence: float,
    notable_building_counts: Optional[Dict[str, int]] = None,
    density_multiplier: float = 1.0,
) -> List[Building]:
    if notable_building_counts is None:
        notable_building_counts = {}

    zone_type = district.zone_type
    target_area = (
        (LOT_FRONTAGE_BY_ZONE[zone_type] / density_multiplier)
        * (LOT_DEPTH_BY_ZONE[zone_type] / density_multiplier)
    )

    leaves = _subdivide_into_buildings(block_polygon, target_area, rng)

    buildings: List[Building] = []
    building_id = next_building_id
    for leaf in leaves:
        if polygon_area(leaf) < 1.0:
            continue  # sliver left over from a degenerate cut, not worth a building

        cx, cy, width, height, rotation = _leaf_footprint(leaf)
        building_type = pick_building_type_with_cap(
            zone_type, target_population, magic_prevalence, rng, notable_building_counts,
        )
        capacity = BUILDING_HOME_CAPACITY.get(building_type, 0)
        vacancies = [
            JobVacancy(building_id=building_id, occupation=occupation)
            for occupation, count in JOB_VACANCIES_BY_BUILDING_TYPE[building_type]
            for _ in range(count)
        ]
        name_pool = BUILDING_NAME_POOLS.get(building_type)
        name = rng.choice(name_pool) if name_pool else None

        buildings.append(Building(
            id=building_id,
            district_id=district.id,
            district_zone_type=zone_type,
            x=cx,
            y=cy,
            building_type=building_type,
            capacity=capacity,
            vacancies=vacancies,
            name=name,
            width=width,
            height=height,
            rotation=rotation,
        ))
        building_id += 1

    return buildings
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_blocks.py -v -k place_buildings_in_block`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add town_shaper/blocks.py tests/test_blocks.py
git commit -m "feat: tile buildings across a block via recursive subdivision instead of frontage lots

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KXcw4JjtMgv8z8tZf7cLHC"
```

---

### Task 6: Wire district inset + notable-count threading into `generate_blocks_and_buildings`

**Files:**
- Modify: `town_shaper/blocks.py`
- Test: `tests/test_blocks.py`

**Interfaces:**
- Consumes: `inset_polygon` (Task 1); `subdivide_into_blocks` (Task 3, new signature); `place_buildings_in_block` (Task 5, new signature).
- Produces: `generate_blocks_and_buildings(district, town_seed, next_building_id, target_population=0, density_multiplier=1.0, magic_prevalence=0.0, notable_building_counts=None) -> List[Building]` (was `Tuple[List[Building], List[RoadNode], List[RoadEdge], int, int]`).

- [ ] **Step 1: Update failing/obsolete test, add a new inset test**

In `tests/test_blocks.py`, replace `test_generate_blocks_and_buildings_covers_every_polygon_part` and add a new inset test:

```python
def test_generate_blocks_and_buildings_covers_every_polygon_part():
    from town_shaper.blocks import generate_blocks_and_buildings

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(40.0, 20.0), _rectangle(30.0, 15.0)])

    buildings = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, target_population=3000, magic_prevalence=0.0,
    )

    assert len(buildings) > 0
    building_ids = [b.id for b in buildings]
    assert building_ids == sorted(building_ids)
    assert building_ids == list(range(len(buildings)))


def test_generate_blocks_and_buildings_insets_away_from_the_district_boundary():
    from shapely.geometry import Point, Polygon as ShapelyPolygon

    from town_shaper.blocks import DISTRICT_INSET_DISTANCE, generate_blocks_and_buildings

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(60.0, 60.0)])

    buildings = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, target_population=3000, magic_prevalence=0.0,
    )

    assert buildings
    original_boundary = ShapelyPolygon(_rectangle(60.0, 60.0)).boundary
    for building in buildings:
        assert Point(building.x, building.y).distance(original_boundary) >= DISTRICT_INSET_DISTANCE - 0.5


def test_generate_blocks_and_buildings_shares_notable_building_counts_across_parts():
    from town_shaper.blocks import generate_blocks_and_buildings
    from town_shaper.buildings import notable_building_cap

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(60.0, 60.0), _rectangle(60.0, 60.0)])
    target_population = 3000
    notable_building_counts = {}

    buildings = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, target_population=target_population,
        magic_prevalence=0.0, notable_building_counts=notable_building_counts,
    )

    assert buildings
    tavern_count = sum(1 for b in buildings if b.building_type == "tavern")
    assert tavern_count <= notable_building_cap("tavern", target_population)
    assert notable_building_counts.get("tavern", 0) == tavern_count
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_blocks.py -v -k generate_blocks_and_buildings`
Expected: FAIL (`generate_blocks_and_buildings` still returns a 5-tuple and doesn't inset).

- [ ] **Step 3: Implement**

In `town_shaper/blocks.py`, add the import and constant:

```python
from town_shaper.geometry import clip_polygon_by_line, distance, inset_polygon, polygon_area
```

Add near `LOCAL_STREET_WIDTH`:

```python
DISTRICT_INSET_DISTANCE = 2.0
```

Replace `generate_blocks_and_buildings`:

```python
def generate_blocks_and_buildings(
    district: District, town_seed, next_building_id: int,
    target_population: int = 0, density_multiplier: float = 1.0, magic_prevalence: float = 0.0,
    notable_building_counts: Optional[Dict[str, int]] = None,
) -> List[Building]:
    rng = rng_for(town_seed, "blocks", district.id)
    if notable_building_counts is None:
        notable_building_counts = {}

    buildings: List[Building] = []
    building_id = next_building_id

    for part in district.polygon_parts:
        inset_part = inset_polygon(part, DISTRICT_INSET_DISTANCE)
        if len(inset_part) < 3:
            continue
        blocks = subdivide_into_blocks(inset_part, district.zone_type, rng)
        for block in blocks:
            block_buildings = place_buildings_in_block(
                block, district, rng, building_id, target_population, magic_prevalence,
                notable_building_counts, density_multiplier,
            )
            buildings.extend(block_buildings)
            building_id += len(block_buildings)

    return buildings
```

- [ ] **Step 4: Run the tests to verify they pass, then the full blocks suite**

Run: `pytest tests/test_blocks.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add town_shaper/blocks.py tests/test_blocks.py
git commit -m "feat: inset districts before block subdivision, thread notable-building counts

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KXcw4JjtMgv8z8tZf7cLHC"
```

---

### Task 7: Wire the simplified pipeline into `generate_town`

**Files:**
- Modify: `town_shaper/generate.py`
- Test: `tests/test_generate.py`

**Interfaces:**
- Consumes: `generate_blocks_and_buildings` (Task 6, new signature).

- [ ] **Step 1: Update failing/obsolete test**

In `tests/test_generate.py`, **delete** `test_generate_town_road_network_includes_local_streets` (tests the removed `local` road type). Keep `test_generate_town_places_footprint_buildings_in_urban_zones` unchanged -- its assertions (every building has positive width/height) hold under the new algorithm too.

Add:

```python
def test_generate_town_has_no_local_road_edges():
    town = generate_town(("town", 1), target_population=3000)
    assert all(e.road_type != "local" for e in town.road_network.edges)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_generate.py -v -k "no_local_road_edges or places_footprint_buildings"`
Expected: `test_generate_town_has_no_local_road_edges` FAILS (local edges are still produced -- `generate_town` hasn't been updated yet); `test_generate_town_places_footprint_buildings_in_urban_zones` FAILS too, since `generate_blocks_and_buildings`'s new 1-value return breaks the current 5-value unpacking in `generate_town`.

- [ ] **Step 3: Simplify the per-district loop**

In `town_shaper/generate.py`, replace:

```python
    next_local_node_id = max((n.id for n in road_network.nodes), default=-1) + 1
    next_local_edge_id = max((e.id for e in road_network.edges), default=-1) + 1

    for district in districts:
        next_building_id = district.id * BUILDING_ID_STRIDE
        if district.zone_type == ZoneType.FARMLAND_EDGE:
            buildings = fill_district_buildings(
                district, seed, next_building_id,
                target_population=target_population, density_multiplier=density_multiplier,
                magic_prevalence=magic_prevalence,
            )
        else:
            buildings, district_nodes, district_edges, next_local_node_id, next_local_edge_id = (
                generate_blocks_and_buildings(
                    district, seed, next_building_id, next_local_node_id, next_local_edge_id,
                    target_population=target_population, density_multiplier=density_multiplier,
                    magic_prevalence=magic_prevalence,
                )
            )
            road_network.nodes.extend(district_nodes)
            road_network.edges.extend(district_edges)
        district.buildings = buildings
```

with:

```python
    notable_building_counts: Dict[str, int] = {}

    for district in districts:
        next_building_id = district.id * BUILDING_ID_STRIDE
        if district.zone_type == ZoneType.FARMLAND_EDGE:
            buildings = fill_district_buildings(
                district, seed, next_building_id,
                target_population=target_population, density_multiplier=density_multiplier,
                magic_prevalence=magic_prevalence,
            )
        else:
            buildings = generate_blocks_and_buildings(
                district, seed, next_building_id,
                target_population=target_population, density_multiplier=density_multiplier,
                magic_prevalence=magic_prevalence, notable_building_counts=notable_building_counts,
            )
        district.buildings = buildings
```

Add `Dict` to the file's imports (`from typing import Dict, Tuple` -- currently just `Tuple`).

- [ ] **Step 4: Run the tests to verify they pass, then the full generate suite**

Run: `pytest tests/test_generate.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: all PASS except `town_db`/`town_viewer` tests that construct a `'radial'`/`'local'` `road_edges` row as an arbitrary literal string in a fixture (`tests/test_db_render.py`, `tests/test_viewer_queries.py`) -- those aren't testing generation and don't need to change (the schema doesn't constrain `road_type` to specific values), but confirm they still pass as-is before continuing; if anything else fails, stop and investigate.

- [ ] **Step 6: Commit**

```bash
git add town_shaper/generate.py tests/test_generate.py
git commit -m "feat: wire simplified block/artery generation into generate_town

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KXcw4JjtMgv8z8tZf7cLHC"
```

---

### Task 8: Update road styling in both renderers

**Files:**
- Modify: `town_db/render.py`
- Modify: `town_viewer/static/app.js`

**Interfaces:**
- No new interfaces -- building-drawing code in both files is unchanged. Only the `ROAD_STYLE` table changes.

- [ ] **Step 1: Update `town_db/render.py`**

Replace:

```python
ROAD_STYLE = {
    "radial": {"width": 2.5, "color": "#3a3a3a"},
    "boundary": {"width": 1.4, "color": "#5a5a5a"},
    "spur": {"width": 0.8, "color": "#7a7a7a"},
    "local": {"width": 0.5, "color": "#9a9a9a"},
}
```

with:

```python
ROAD_STYLE = {
    "artery": {"width": 1.2, "color": "#6b5d4f"},
    "boundary": {"width": 1.4, "color": "#5a5a5a"},
    "spur": {"width": 0.8, "color": "#7a7a7a"},
}
```

`render_town`'s fallback for an unrecognized `road_type` already reads `ROAD_STYLE.get(road_type, ROAD_STYLE["spur"])` -- no change needed there.

- [ ] **Step 2: Update `town_viewer/static/app.js`**

Replace:

```javascript
const ROAD_STYLE = {
  radial: { width: 2.5, color: "#3a3a3a" },
  boundary: { width: 1.4, color: "#5a5a5a" },
  spur: { width: 0.8, color: "#7a7a7a" },
  local: { width: 0.5, color: "#9a9a9a" },
};
```

with:

```javascript
const ROAD_STYLE = {
  artery: { width: 1.2, color: "#6b5d4f" },
  boundary: { width: 1.4, color: "#5a5a5a" },
  spur: { width: 0.8, color: "#7a7a7a" },
};
```

`draw()`'s fallback (`ROAD_STYLE[edge.road_type] || ROAD_STYLE.spur`) already handles an unrecognized type -- no other change needed.

- [ ] **Step 3: Manually verify -- regenerate and render a town**

Run:

```bash
python scripts/generate_town.py
python scripts/render_town.py my_town.db my_town.png
```

Open `my_town.png` and confirm: no straight lines cutting across districts/buildings, buildings tile their blocks contiguously, and any road lines visible only reach toward `farmland_edge` (green) areas. This is the same check the mockup comparison used earlier in the session -- compare against it if useful.

- [ ] **Step 4: Commit**

```bash
git add town_db/render.py town_viewer/static/app.js
git commit -m "style: update road styling for artery roads, drop unused local style

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KXcw4JjtMgv8z8tZf7cLHC"
```

---

### Task 9: Full suite, determinism sweep, and doc updates

**Files:**
- Modify: `docs/visual-interface-ideas.md`
- Modify: `IDEAS.md`

**Interfaces:** None -- verification and documentation only.

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: all PASS.

- [ ] **Step 2: Determinism + integrity sweep**

Run a quick standalone check (throwaway script, not committed) generating the same seed twice at a couple of population sizes and diffing `buildings`/`road_edges`/`road_nodes` row-for-row, same shape as prior plans' final-task sweeps in this project (see `LOG.md` for examples). Confirm byte-identical output across two independent runs at, e.g., `("town", 1)` pop 3000 and `("town", 7)` pop 8000.

- [ ] **Step 3: Sanity-check generation time and building count at a realistic population**

Run `python scripts/generate_town.py` at the default population (5000) and note the reported resident count plus a quick `SELECT COUNT(*) FROM buildings` against the resulting `my_town.db`. Compare against the pre-change baseline from earlier in this session (5,155 residents / a smaller building count under frontage-only placement) -- confirm generation still completes in a reasonable time (well under a minute) and the building count increase is bounded, not runaway.

- [ ] **Step 4: Update `docs/visual-interface-ideas.md`**

In the "Follow-ups from using the MVP" section, mark item 3 resolved, matching the existing style used for items 1 and 2:

```markdown
3. ~~**Map should read as an actual city, not scattered squares.**~~ **Fixed 2026-09-04:**
   real footprints now tile every block via recursive subdivision, streets
   are the implicit gap between inset district/block polygons, and
   arterial roads follow the real district-boundary graph instead of
   straight lines from a hub. See
   `docs/superpowers/specs/2026-09-04-organic-town-rendering-design.md`.
```

- [ ] **Step 5: Update `IDEAS.md`**

In the "Visualization Features" `#### Feedback` section, add a resolution note under the existing item 1 entry (don't delete the original feedback -- append below the existing "Status check" paragraph):

```markdown
   **Resolved 2026-09-04:** implemented per
   `docs/superpowers/specs/2026-09-04-organic-town-rendering-design.md` /
   `docs/superpowers/plans/2026-09-04-organic-town-rendering.md`. Streets
   inside the urban core are now the implicit gap between inset block
   polygons (no drawn line), arterial roads follow the real district
   boundary graph instead of straight hub-and-spoke lines, and buildings
   fully tile each block via recursive subdivision. A population-scaled
   cap keeps named/business building counts (taverns, shops, etc.)
   bounded so this doesn't worsen the duplicate-tavern-name issue logged
   above under "Backend > Population Generation > Feedback" (item 1).
```

- [ ] **Step 6: Commit**

```bash
git add docs/visual-interface-ideas.md IDEAS.md
git commit -m "docs: mark organic town rendering follow-up resolved

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KXcw4JjtMgv8z8tZf7cLHC"
```
