# Building Footprints & Lot Placement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every building a real rectangular footprint (width/height/rotation) instead of a bare point, and place "urban" zone buildings (civic/merchant/rich_residential/poor_residential/port) on real street-fronting lots carved out of recursively-subdivided city blocks — replacing today's Poisson-disc dot placement for those zones.

**Architecture:** A new `town_shaper/blocks.py` module recursively splits each urban district polygon into blocks (cutting along the polygon's own minimum-rotated-rectangle longer axis, via a new single-line polygon-clip helper extracted from existing rectangle-clip code), then walks each block's boundary carving fixed-frontage lots and placing one building per lot, reusing the exact building-type-selection logic `town_shaper/buildings.py` already has (extracted into a shared function). `farmland_edge` districts are untouched — they keep today's Poisson-disc point placement, just with a fixed default footprint size added so every building always has one. Local streets cut during block subdivision are persisted as ordinary rows in the *existing* `road_nodes`/`road_edges` tables from the road network feature (a new `road_type="local"` value — no schema change needed there). Both renderers draw non-landmark buildings as rotated rectangles from their real footprint data; landmark buildings keep their existing distinct marker/color rendering unchanged (this plan does not touch that legend system).

**Architectural deviation from the spec, noted for transparency:** the spec described the farmland/non-farmland dispatch as living inside `town_shaper/buildings.py`'s `fill_district_buildings`. This plan instead puts the dispatch in `town_shaper/generate.py`'s existing per-district loop (calling `fill_district_buildings` only for `farmland_edge`, and a new `town_shaper.blocks.generate_blocks_and_buildings` for every other zone). Same behavior, same interfaces at the `Town`/DB level, but it means `fill_district_buildings`'s signature and every existing test that calls it directly never changes, and `town_shaper/blocks.py` never needs to import `town_shaper/buildings.py`'s dispatch back into itself — no circular import to work around (unlike the precedent in `LOG.md` for `town_db/economy.py`/`purchases.py`, which needed a local-import workaround; this design avoids needing one at all).

**Tech Stack:** Python, `shapely` (already a dependency — `minimum_rotated_rectangle`), SQLite, Flask + vanilla JS canvas. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-02-building-footprints-design.md`

## Global Constraints

- No new dependencies.
- Only `civic`, `merchant`, `rich_residential`, `poor_residential`, and `port` zones get block/lot subdivision. `farmland_edge` keeps today's Poisson-disc point placement.
- Every building — urban or farmland — ends up with a non-zero `width`/`height` at generation time. Never leave a building at the dataclass default of `0.0`.
- Footprints are plain rectangles (width, height, rotation). No polygons, no L-shapes.
- A block's leftover partial frontage shorter than one lot width is left empty — no corner-wrapping.
- Determinism: all new randomness draws from `rng_for(town_seed, "blocks", district.id, ...)`, following the existing per-purpose-and-id seeding convention. No global/module-level `random` calls.
- Landmark-type buildings' existing marker/color rendering (both renderers) is unchanged — this plan only changes how *non-landmark* buildings render.

---

### Task 1: Extract `clip_polygon_by_line` in `geometry.py`

**Files:**
- Modify: `town_shaper/geometry.py`
- Test: `tests/test_geometry.py`

**Interfaces:**
- Produces: `clip_polygon_by_line(polygon: Polygon, edge_start: Point, edge_end: Point) -> Polygon` — Sutherland-Hodgman single-edge clip; keeps only the part of `polygon` on the inside (left, per the existing `_is_inside_edge` convention) of the directed line `edge_start -> edge_end`.

This is a pure refactor — `clip_polygon_to_bounds`'s behavior must not change. `town_shaper/blocks.py` (Task 3 onward) will call `clip_polygon_by_line` directly to cut a polygon along one line, instead of the four-line rectangle clip.

- [ ] **Step 1: Write failing tests for the new helper**

Add to `tests/test_geometry.py`:

```python
from town_shaper.geometry import clip_polygon_by_line


def test_clip_polygon_by_line_keeps_the_left_half_of_a_square():
    square = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    # Directed line straight up through x=2 -- "left" of (2,0)->(2,4) is x<2.
    left_half = clip_polygon_by_line(square, (2.0, 0.0), (2.0, 4.0))
    assert math.isclose(polygon_area(left_half), 8.0, rel_tol=1e-9)
    for x, _y in left_half:
        assert x <= 2.0 + 1e-9


def test_clip_polygon_by_line_fully_outside_returns_empty():
    triangle = [(10.0, 10.0), (12.0, 10.0), (11.0, 12.0)]
    # Directed line far to the left of the triangle -- nothing is on its left side.
    assert clip_polygon_by_line(triangle, (0.0, -1.0), (0.0, 1.0)) == []


def test_clip_polygon_by_line_two_opposite_halves_sum_to_original_area():
    square = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    left_half = clip_polygon_by_line(square, (2.0, 0.0), (2.0, 4.0))
    right_half = clip_polygon_by_line(square, (2.0, 4.0), (2.0, 0.0))
    assert math.isclose(polygon_area(left_half) + polygon_area(right_half), 16.0, rel_tol=1e-9)
```

Add `polygon_area` to the existing import line at the top of `tests/test_geometry.py` if it isn't already imported (it already is, per the current file).

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_geometry.py::test_clip_polygon_by_line_keeps_the_left_half_of_a_square tests/test_geometry.py::test_clip_polygon_by_line_fully_outside_returns_empty tests/test_geometry.py::test_clip_polygon_by_line_two_opposite_halves_sum_to_original_area -v`
Expected: FAIL with `ImportError: cannot import name 'clip_polygon_by_line'`

- [ ] **Step 3: Extract `clip_polygon_by_line` and refactor `clip_polygon_to_bounds` to use it**

In `town_shaper/geometry.py`, replace:

```python
def clip_polygon_to_bounds(polygon: Polygon, bounds: Tuple[float, float, float, float]) -> Polygon:
    """Sutherland-Hodgman clip of `polygon` against the rectangle `bounds`."""
    min_x, min_y, max_x, max_y = bounds
    clip_polygon = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]

    output = list(polygon)
    for i in range(len(clip_polygon)):
        if not output:
            break
        edge_start = clip_polygon[i]
        edge_end = clip_polygon[(i + 1) % len(clip_polygon)]
        input_list = output
        output = []
        s = input_list[-1]
        for e in input_list:
            e_inside = _is_inside_edge(e, edge_start, edge_end)
            s_inside = _is_inside_edge(s, edge_start, edge_end)
            if e_inside:
                if not s_inside:
                    output.append(_line_intersection(s, e, edge_start, edge_end))
                output.append(e)
            elif s_inside:
                output.append(_line_intersection(s, e, edge_start, edge_end))
            s = e
    return output
```

with:

```python
def clip_polygon_by_line(polygon: Polygon, edge_start: Point, edge_end: Point) -> Polygon:
    """Sutherland-Hodgman single-edge clip: keep only the part of `polygon`
    on the inside (left) of the directed line edge_start -> edge_end."""
    output: Polygon = []
    if not polygon:
        return output
    s = polygon[-1]
    for e in polygon:
        e_inside = _is_inside_edge(e, edge_start, edge_end)
        s_inside = _is_inside_edge(s, edge_start, edge_end)
        if e_inside:
            if not s_inside:
                output.append(_line_intersection(s, e, edge_start, edge_end))
            output.append(e)
        elif s_inside:
            output.append(_line_intersection(s, e, edge_start, edge_end))
        s = e
    return output


def clip_polygon_to_bounds(polygon: Polygon, bounds: Tuple[float, float, float, float]) -> Polygon:
    """Sutherland-Hodgman clip of `polygon` against the rectangle `bounds`."""
    min_x, min_y, max_x, max_y = bounds
    clip_edges = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]

    output = list(polygon)
    for i in range(len(clip_edges)):
        if not output:
            break
        edge_start = clip_edges[i]
        edge_end = clip_edges[(i + 1) % len(clip_edges)]
        output = clip_polygon_by_line(output, edge_start, edge_end)
    return output
```

- [ ] **Step 4: Run the full geometry test suite to confirm no regression**

Run: `pytest tests/test_geometry.py -v`
Expected: all tests PASS, including the three new ones.

- [ ] **Step 5: Commit**

```bash
git add town_shaper/geometry.py tests/test_geometry.py
git commit -m "refactor: extract clip_polygon_by_line helper from clip_polygon_to_bounds

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

### Task 2: `Building` gains a footprint; farmland gets a fixed default

**Files:**
- Modify: `town_shaper/models.py`
- Modify: `town_shaper/buildings.py`
- Test: `tests/test_buildings.py`

**Interfaces:**
- Produces: `Building` dataclass gains `width: float = 0.0`, `height: float = 0.0`, `rotation: float = 0.0` fields. `town_shaper/buildings.py` gains `FARMLAND_BUILDING_WIDTH = 6.0`, `FARMLAND_BUILDING_HEIGHT = 6.0` constants; every `Building` `fill_district_buildings` creates now has `width=FARMLAND_BUILDING_WIDTH, height=FARMLAND_BUILDING_HEIGHT, rotation=0.0`.

At this point in the plan, `fill_district_buildings` is still called for every zone type (the farmland/non-farmland dispatch doesn't exist until Task 5) — so this task's test correctly asserts every zone gets the fixed footprint for now. Task 5 changes the caller (`generate_town`) to only invoke `fill_district_buildings` for `farmland_edge` going forward; this task's code in `buildings.py` does not change again after that.

- [ ] **Step 1: Add the fields to `Building`**

In `town_shaper/models.py`, change:

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
```

to:

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
    rotation: float = 0.0
```

- [ ] **Step 2: Write a failing test for the default footprint**

Add to `tests/test_buildings.py`:

```python
def test_fill_district_buildings_gives_every_building_a_default_footprint():
    from town_shaper.buildings import FARMLAND_BUILDING_HEIGHT, FARMLAND_BUILDING_WIDTH

    district = _square_district(ZoneType.FARMLAND_EDGE)
    for building in fill_district_buildings(district, ("town", 1), next_building_id=0):
        assert building.width == FARMLAND_BUILDING_WIDTH
        assert building.height == FARMLAND_BUILDING_HEIGHT
        assert building.rotation == 0.0
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_buildings.py::test_fill_district_buildings_gives_every_building_a_default_footprint -v`
Expected: FAIL with `ImportError: cannot import name 'FARMLAND_BUILDING_WIDTH'`

- [ ] **Step 4: Add the constants and assign the footprint**

In `town_shaper/buildings.py`, add near `BUILDING_HOME_CAPACITY`:

```python
FARMLAND_BUILDING_WIDTH = 6.0
FARMLAND_BUILDING_HEIGHT = 6.0
```

In `fill_district_buildings`, change the `Building(...)` construction:

```python
        buildings.append(Building(
            id=building_id,
            district_id=district.id,
            district_zone_type=district.zone_type,
            x=x,
            y=y,
            building_type=building_type,
            capacity=capacity,
            vacancies=vacancies,
            name=name,
            width=FARMLAND_BUILDING_WIDTH,
            height=FARMLAND_BUILDING_HEIGHT,
            rotation=0.0,
        ))
```

- [ ] **Step 5: Run the test to verify it passes, then the full buildings suite**

Run: `pytest tests/test_buildings.py -v`
Expected: all PASS, including the new test.

- [ ] **Step 6: Commit**

```bash
git add town_shaper/models.py town_shaper/buildings.py tests/test_buildings.py
git commit -m "feat: add footprint fields to Building, default footprint for fill_district_buildings

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

### Task 3: Block subdivision (`town_shaper/blocks.py`)

**Files:**
- Create: `town_shaper/blocks.py`
- Test: `tests/test_blocks.py` (new)

**Interfaces:**
- Consumes: `clip_polygon_by_line`, `distance`, `point_in_polygon`, `polygon_area` (`town_shaper.geometry`); `RoadNode`, `RoadEdge`, `ZoneType` (`town_shaper.models`); `rng_for` (`town_shaper.seeding`); `shapely.geometry.Polygon`.
- Produces: `TARGET_BLOCK_AREA_BY_ZONE: Dict[ZoneType, float]`, `LOCAL_STREET_WIDTH: float`, `MAX_SPLIT_DEPTH: int` module constants; `subdivide_into_blocks(polygon_part: List[Tuple[float, float]], zone_type: ZoneType, rng, next_node_id: int, next_edge_id: int) -> Tuple[List[List[Tuple[float, float]]], List[RoadNode], List[RoadEdge], int, int]` (this task only — lot placement is Task 4, in the same file).

- [ ] **Step 1: Write failing tests for block subdivision**

Create `tests/test_blocks.py`:

```python
import math

from town_shaper.blocks import TARGET_BLOCK_AREA_BY_ZONE, subdivide_into_blocks
from town_shaper.geometry import polygon_area
from town_shaper.models import ZoneType
from town_shaper.seeding import rng_for


def _square(side: float):
    return [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]


def test_subdivide_into_blocks_returns_original_when_already_small():
    small_square = _square(5.0)  # area 25, well under any zone's target
    rng = rng_for(("town", 1), "blocks-test", 1)

    blocks, nodes, edges, next_node_id, next_edge_id = subdivide_into_blocks(
        small_square, ZoneType.MERCHANT, rng, next_node_id=0, next_edge_id=0,
    )

    assert blocks == [small_square]
    assert nodes == []
    assert edges == []
    assert next_node_id == 0
    assert next_edge_id == 0


def test_subdivide_into_blocks_respects_target_area():
    large_square = _square(100.0)  # area 10000
    target_area = TARGET_BLOCK_AREA_BY_ZONE[ZoneType.MERCHANT]
    rng = rng_for(("town", 1), "blocks-test", 2)

    blocks, nodes, edges, _next_node_id, _next_edge_id = subdivide_into_blocks(
        large_square, ZoneType.MERCHANT, rng, next_node_id=0, next_edge_id=0,
    )

    assert len(blocks) > 1
    for block in blocks:
        assert polygon_area(block) <= target_area


def test_subdivide_into_blocks_conserves_area_within_street_gaps():
    large_square = _square(100.0)
    rng = rng_for(("town", 1), "blocks-test", 3)

    blocks, _nodes, _edges, _next_node_id, _next_edge_id = subdivide_into_blocks(
        large_square, ZoneType.MERCHANT, rng, next_node_id=0, next_edge_id=0,
    )

    original_area = polygon_area(large_square)
    total_block_area = sum(polygon_area(b) for b in blocks)
    assert total_block_area <= original_area
    # This is a gross-error guard (catches e.g. an inverted clip direction
    # silently discarding whole blocks), not a precise gap-area budget --
    # the exact fraction street gaps consume depends on how many splits a
    # 10000-area square takes to reach a 600-area target, which this test
    # doesn't hand-compute. If this fails after a correct implementation
    # legitimately consumes more than 40% to street gaps, loosen the
    # tolerance rather than treating it as a bug.
    assert total_block_area >= original_area * 0.6


def test_subdivide_into_blocks_produces_one_local_edge_per_split():
    large_square = _square(100.0)
    rng = rng_for(("town", 1), "blocks-test", 4)

    blocks, nodes, edges, _next_node_id, _next_edge_id = subdivide_into_blocks(
        large_square, ZoneType.MERCHANT, rng, next_node_id=0, next_edge_id=0,
    )

    num_splits = len(blocks) - 1  # each split adds exactly one more block
    assert len(edges) == num_splits
    assert len(nodes) == num_splits * 2
    for edge in edges:
        assert edge.road_type == "local"
    node_ids = {n.id for n in nodes}
    for edge in edges:
        assert edge.from_node_id in node_ids
        assert edge.to_node_id in node_ids


def test_subdivide_into_blocks_ids_are_threaded_without_collision():
    large_square = _square(100.0)
    rng = rng_for(("town", 1), "blocks-test", 5)

    _blocks, nodes, edges, next_node_id, next_edge_id = subdivide_into_blocks(
        large_square, ZoneType.MERCHANT, rng, next_node_id=100, next_edge_id=200,
    )

    assert all(n.id >= 100 for n in nodes)
    assert all(e.id >= 200 for e in edges)
    assert next_node_id == 100 + len(nodes)
    assert next_edge_id == 200 + len(edges)


def test_subdivide_into_blocks_is_deterministic():
    large_square = _square(100.0)

    rng1 = rng_for(("town", 1), "blocks-test", 6)
    blocks1, nodes1, edges1, _n1, _e1 = subdivide_into_blocks(
        large_square, ZoneType.MERCHANT, rng1, next_node_id=0, next_edge_id=0,
    )
    rng2 = rng_for(("town", 1), "blocks-test", 6)
    blocks2, nodes2, edges2, _n2, _e2 = subdivide_into_blocks(
        large_square, ZoneType.MERCHANT, rng2, next_node_id=0, next_edge_id=0,
    )

    assert [sorted(b) for b in blocks1] == [sorted(b) for b in blocks2]
    assert [(n.x, n.y) for n in nodes1] == [(n.x, n.y) for n in nodes2]
    assert [(e.from_node_id, e.to_node_id) for e in edges1] == [(e.from_node_id, e.to_node_id) for e in edges2]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_blocks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_shaper.blocks'`

- [ ] **Step 3: Implement block subdivision**

Create `town_shaper/blocks.py`:

```python
import math
from typing import Dict, List, Tuple

from shapely.geometry import Polygon as ShapelyPolygon

from town_shaper.geometry import clip_polygon_by_line, distance, polygon_area
from town_shaper.models import RoadEdge, RoadNode, ZoneType

TARGET_BLOCK_AREA_BY_ZONE: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 2000.0,
    ZoneType.MERCHANT: 600.0,
    ZoneType.RICH_RESIDENTIAL: 1500.0,
    ZoneType.POOR_RESIDENTIAL: 250.0,
    ZoneType.PORT: 600.0,
}
LOCAL_STREET_WIDTH = 4.0
MAX_SPLIT_DEPTH = 8

Point = Tuple[float, float]
Polygon = List[Point]


def _longer_axis_direction(polygon: Polygon) -> Point:
    """Unit vector along the longer axis of polygon's minimum rotated rectangle."""
    obb = ShapelyPolygon(polygon).minimum_rotated_rectangle
    corners = list(obb.exterior.coords)[:-1]
    if len(corners) < 4:
        return (1.0, 0.0)  # degenerate (near-zero-area) polygon -- any axis works
    edge_a = distance(corners[0], corners[1])
    edge_b = distance(corners[1], corners[2])
    p1, p2 = (corners[0], corners[1]) if edge_a >= edge_b else (corners[1], corners[2])
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length else (1.0, 0.0)


def _polygon_centroid(polygon: Polygon) -> Point:
    return (sum(p[0] for p in polygon) / len(polygon), sum(p[1] for p in polygon) / len(polygon))


def _split_polygon(polygon: Polygon, rng) -> Tuple[Polygon, Polygon, Tuple[Point, Point]]:
    """Split `polygon` into two halves along its longer OBB axis, offset by
    LOCAL_STREET_WIDTH, plus the unoffset cut line's two endpoints."""
    axis_dir = _longer_axis_direction(polygon)
    split_dir = (-axis_dir[1], axis_dir[0])  # perpendicular to the longer axis
    cx, cy = _polygon_centroid(polygon)

    span = max((distance(p, q) for p in polygon for q in polygon), default=0.0) + 1.0
    split_fraction = rng.uniform(0.4, 0.6)
    offset_along_axis = (split_fraction - 0.5) * span
    center = (cx + axis_dir[0] * offset_along_axis, cy + axis_dir[1] * offset_along_axis)

    line_start = (center[0] - split_dir[0] * span, center[1] - split_dir[1] * span)
    line_end = (center[0] + split_dir[0] * span, center[1] + split_dir[1] * span)

    half_width = LOCAL_STREET_WIDTH / 2.0
    offset_a = (axis_dir[0] * half_width, axis_dir[1] * half_width)
    offset_b = (-offset_a[0], -offset_a[1])

    side_a = clip_polygon_by_line(
        polygon,
        (line_start[0] + offset_a[0], line_start[1] + offset_a[1]),
        (line_end[0] + offset_a[0], line_end[1] + offset_a[1]),
    )
    side_b = clip_polygon_by_line(
        polygon,
        (line_end[0] + offset_b[0], line_end[1] + offset_b[1]),
        (line_start[0] + offset_b[0], line_start[1] + offset_b[1]),
    )
    return side_a, side_b, (line_start, line_end)


def subdivide_into_blocks(
    polygon_part: Polygon, zone_type: ZoneType, rng, next_node_id: int, next_edge_id: int,
) -> Tuple[List[Polygon], List[RoadNode], List[RoadEdge], int, int]:
    """Recursively split `polygon_part` into blocks for `zone_type`.

    Returns (blocks, local_road_nodes, local_road_edges, next_node_id,
    next_edge_id) -- the last two are the counters incremented past whatever
    this call consumed, threaded the same way generate.py already threads
    next_building_id across districts.
    """
    return _subdivide(
        polygon_part, TARGET_BLOCK_AREA_BY_ZONE[zone_type], rng, next_node_id, next_edge_id, depth=0,
    )


def _subdivide(
    polygon_part: Polygon, target_area: float, rng, next_node_id: int, next_edge_id: int, depth: int,
) -> Tuple[List[Polygon], List[RoadNode], List[RoadEdge], int, int]:
    if len(polygon_part) < 3 or polygon_area(polygon_part) <= target_area or depth >= MAX_SPLIT_DEPTH:
        return [polygon_part], [], [], next_node_id, next_edge_id

    side_a, side_b, (line_start, line_end) = _split_polygon(polygon_part, rng)
    if len(side_a) < 3 or len(side_b) < 3:
        # Degenerate split (e.g. a sliver too thin for the street gap) -- stop here.
        return [polygon_part], [], [], next_node_id, next_edge_id

    node_a = RoadNode(id=next_node_id, kind="junction", x=line_start[0], y=line_start[1])
    node_b = RoadNode(id=next_node_id + 1, kind="junction", x=line_end[0], y=line_end[1])
    edge = RoadEdge(id=next_edge_id, from_node_id=node_a.id, to_node_id=node_b.id, road_type="local")
    next_node_id += 2
    next_edge_id += 1

    blocks_a, nodes_a, edges_a, next_node_id, next_edge_id = _subdivide(
        side_a, target_area, rng, next_node_id, next_edge_id, depth + 1,
    )
    blocks_b, nodes_b, edges_b, next_node_id, next_edge_id = _subdivide(
        side_b, target_area, rng, next_node_id, next_edge_id, depth + 1,
    )
    return (
        blocks_a + blocks_b,
        [node_a, node_b] + nodes_a + nodes_b,
        [edge] + edges_a + edges_b,
        next_node_id, next_edge_id,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_blocks.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add town_shaper/blocks.py tests/test_blocks.py
git commit -m "feat: add recursive block subdivision for urban districts

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

### Task 4: Lot subdivision and building placement (`town_shaper/blocks.py`)

**Files:**
- Modify: `town_shaper/blocks.py`
- Modify: `town_shaper/buildings.py`
- Test: `tests/test_blocks.py`, `tests/test_buildings.py`

**Interfaces:**
- Consumes: `subdivide_into_blocks` (Task 3, unchanged); `point_in_polygon` (`town_shaper.geometry`); `District` (`town_shaper.models`); `BUILDING_HOME_CAPACITY`, `BUILDING_NAME_POOLS`, `JOB_VACANCIES_BY_BUILDING_TYPE`, and the new `resolve_building_type_weights` (`town_shaper.buildings`, extracted this task).
- Produces: `LOT_FRONTAGE_BY_ZONE: Dict[ZoneType, float]`, `LOT_DEPTH_BY_ZONE: Dict[ZoneType, float]`, `FOOTPRINT_FILL_FRACTION: float` constants in `town_shaper/blocks.py`; `place_buildings_in_block(block_polygon, district, rng, next_building_id, target_population, magic_prevalence, density_multiplier=1.0) -> List[Building]`. `town_shaper.buildings.resolve_building_type_weights(zone_type, target_population, magic_prevalence, rng) -> Dict[str, float]` (public, extracted from `fill_district_buildings`'s existing inline logic — behavior unchanged).

- [ ] **Step 1: Extract `resolve_building_type_weights` in `buildings.py` (pure refactor first)**

In `town_shaper/buildings.py`, replace the inline block inside `fill_district_buildings`:

```python
    type_weights = dict(BUILDING_TYPES_BY_ZONE[district.zone_type])
    if district.zone_type == ZoneType.CIVIC and "university" in type_weights:
        university_eligible = (
            target_population >= UNIVERSITY_MIN_POPULATION and rng.random() < UNIVERSITY_CHANCE
        )
        if not university_eligible:
            del type_weights["university"]
    if district.zone_type == ZoneType.MERCHANT and magic_prevalence > 0:
        type_weights["arcane_shop"] = magic_prevalence * ARCANE_SHOP_WEIGHT_SCALE
    subtypes = list(type_weights.keys())
    weights = list(type_weights.values())
```

with a call to a new module-level function, added just above `fill_district_buildings`:

```python
def resolve_building_type_weights(
    zone_type: ZoneType, target_population: int, magic_prevalence: float, rng,
) -> Dict[str, float]:
    type_weights = dict(BUILDING_TYPES_BY_ZONE[zone_type])
    if zone_type == ZoneType.CIVIC and "university" in type_weights:
        university_eligible = (
            target_population >= UNIVERSITY_MIN_POPULATION and rng.random() < UNIVERSITY_CHANCE
        )
        if not university_eligible:
            del type_weights["university"]
    if zone_type == ZoneType.MERCHANT and magic_prevalence > 0:
        type_weights["arcane_shop"] = magic_prevalence * ARCANE_SHOP_WEIGHT_SCALE
    return type_weights
```

and inside `fill_district_buildings`, replace the six lines above with:

```python
    type_weights = resolve_building_type_weights(district.zone_type, target_population, magic_prevalence, rng)
    subtypes = list(type_weights.keys())
    weights = list(type_weights.values())
```

Run `pytest tests/test_buildings.py tests/test_generate.py -v` now — expected: all PASS, no behavior change (this step is a pure refactor; do not commit yet, continue to Step 2).

- [ ] **Step 2: Write failing tests for lot placement**

Add to `tests/test_blocks.py`:

```python
from shapely.geometry import Polygon as ShapelyPolygon

from town_shaper.blocks import LOT_FRONTAGE_BY_ZONE, place_buildings_in_block
from town_shaper.models import Anchor, District


def _rectangle(width: float, height: float):
    return [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)]


def _district(zone_type):
    anchor = Anchor(id=1, zone_type=zone_type, x=0.0, y=0.0)
    return District(id=1, zone_type=zone_type, anchor=anchor, polygon_parts=[])


def _footprint_shape(building):
    hw, hh = building.width / 2.0, building.height / 2.0
    cos_r, sin_r = math.cos(building.rotation), math.sin(building.rotation)
    corners = [
        (building.x + lx * cos_r - ly * sin_r, building.y + lx * sin_r + ly * cos_r)
        for lx, ly in [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    ]
    return ShapelyPolygon(corners)


def test_place_buildings_in_block_footprints_stay_within_the_block():
    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 10)

    buildings = place_buildings_in_block(block, district, rng, 0, target_population=3000, magic_prevalence=0.0)

    assert len(buildings) > 0
    block_shape = ShapelyPolygon(block).buffer(0.5)  # small tolerance for footprints flush on the boundary
    for building in buildings:
        assert block_shape.contains(_footprint_shape(building))


def test_place_buildings_in_block_footprints_dont_overlap():
    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 11)

    buildings = place_buildings_in_block(block, district, rng, 0, target_population=3000, magic_prevalence=0.0)

    shapes = [_footprint_shape(b) for b in buildings]
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            assert shapes[i].intersection(shapes[j]).area < 1e-6


def test_place_buildings_in_block_rotation_matches_frontage_edge():
    # A 40x20 rectangle has two horizontal edges (bottom/top) and two
    # vertical edges (left/right) -- every building's rotation should land
    # in one of exactly two buckets, and both buckets should be populated
    # (not just one, which would mean rotation isn't actually tracking the
    # edge it was placed against).
    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 12)

    buildings = place_buildings_in_block(block, district, rng, 0, target_population=3000, magic_prevalence=0.0)

    horizontal = [b for b in buildings if math.isclose(abs(b.rotation) % math.pi, 0.0, abs_tol=1e-6)]
    vertical = [b for b in buildings if math.isclose(abs(b.rotation) % math.pi, math.pi / 2, abs_tol=1e-6)]
    assert horizontal
    assert vertical
    assert len(horizontal) + len(vertical) == len(buildings)


def test_place_buildings_in_block_is_deterministic():
    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)

    rng1 = rng_for(("town", 1), "blocks-test", 13)
    b1 = place_buildings_in_block(block, district, rng1, 0, target_population=3000, magic_prevalence=0.0)
    rng2 = rng_for(("town", 1), "blocks-test", 13)
    b2 = place_buildings_in_block(block, district, rng2, 0, target_population=3000, magic_prevalence=0.0)

    key = lambda buildings: [(b.x, b.y, b.width, b.height, b.rotation, b.building_type) for b in buildings]
    assert key(b1) == key(b2)


def test_place_buildings_in_block_density_multiplier_scales_lot_size():
    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)

    rng_sparse = rng_for(("town", 1), "blocks-test", 14)
    sparse = place_buildings_in_block(
        block, district, rng_sparse, 0, target_population=3000, magic_prevalence=0.0, density_multiplier=0.5,
    )
    rng_dense = rng_for(("town", 1), "blocks-test", 14)
    dense = place_buildings_in_block(
        block, district, rng_dense, 0, target_population=3000, magic_prevalence=0.0, density_multiplier=2.0,
    )

    assert len(dense) > len(sparse)
```

Add `import math` to the top of `tests/test_blocks.py` alongside the existing imports if not already present (it's needed starting with these tests).

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_blocks.py -v`
Expected: FAIL with `ImportError: cannot import name 'place_buildings_in_block'`

- [ ] **Step 4: Implement lot subdivision and placement**

In `town_shaper/blocks.py`, add the imports needed (extend the existing import lines):

```python
from town_shaper.buildings import (
    BUILDING_HOME_CAPACITY, BUILDING_NAME_POOLS, JOB_VACANCIES_BY_BUILDING_TYPE,
    resolve_building_type_weights,
)
from town_shaper.geometry import clip_polygon_by_line, distance, point_in_polygon, polygon_area
from town_shaper.models import Building, District, JobVacancy, RoadEdge, RoadNode, ZoneType
```

(this replaces the Task 3 import line for `town_shaper.geometry` — add `point_in_polygon`; and replaces the Task 3 import line for `town_shaper.models` — add `Building`, `District`, `JobVacancy`.)

Add the new constants near `TARGET_BLOCK_AREA_BY_ZONE`:

```python
LOT_FRONTAGE_BY_ZONE: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 15.0,
    ZoneType.MERCHANT: 8.0,
    ZoneType.RICH_RESIDENTIAL: 12.0,
    ZoneType.POOR_RESIDENTIAL: 5.0,
    ZoneType.PORT: 8.0,
}
LOT_DEPTH_BY_ZONE: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 18.0,
    ZoneType.MERCHANT: 10.0,
    ZoneType.RICH_RESIDENTIAL: 15.0,
    ZoneType.POOR_RESIDENTIAL: 6.0,
    ZoneType.PORT: 10.0,
}
FOOTPRINT_FILL_FRACTION = 0.8
```

Add the placement functions at the bottom of the file:

```python
def _perpendicular_into_polygon(edge_start: Point, edge_end: Point, polygon: Polygon) -> Point:
    dx, dy = edge_end[0] - edge_start[0], edge_end[1] - edge_start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return (0.0, 0.0)
    direction = (dx / length, dy / length)
    candidate_a = (-direction[1], direction[0])
    midpoint = ((edge_start[0] + edge_end[0]) / 2.0, (edge_start[1] + edge_end[1]) / 2.0)
    probe = (midpoint[0] + candidate_a[0] * 0.1, midpoint[1] + candidate_a[1] * 0.1)
    return candidate_a if point_in_polygon(probe, polygon) else (-candidate_a[0], -candidate_a[1])


def place_buildings_in_block(
    block_polygon: Polygon, district: District, rng,
    next_building_id: int, target_population: int, magic_prevalence: float,
    density_multiplier: float = 1.0,
) -> List[Building]:
    zone_type = district.zone_type
    frontage = LOT_FRONTAGE_BY_ZONE[zone_type] / density_multiplier
    depth = LOT_DEPTH_BY_ZONE[zone_type] / density_multiplier

    buildings: List[Building] = []
    building_id = next_building_id
    n = len(block_polygon)
    for i in range(n):
        edge_start = block_polygon[i]
        edge_end = block_polygon[(i + 1) % n]
        edge_length = distance(edge_start, edge_end)
        num_lots = int(edge_length // frontage)
        if num_lots == 0:
            continue
        dx = (edge_end[0] - edge_start[0]) / edge_length
        dy = (edge_end[1] - edge_start[1]) / edge_length
        inward = _perpendicular_into_polygon(edge_start, edge_end, block_polygon)
        rotation = math.atan2(dy, dx)

        for lot_index in range(num_lots):
            along = frontage * (lot_index + 0.5)
            lot_center_x = edge_start[0] + dx * along + inward[0] * (depth / 2.0)
            lot_center_y = edge_start[1] + dy * along + inward[1] * (depth / 2.0)

            type_weights = resolve_building_type_weights(zone_type, target_population, magic_prevalence, rng)
            subtypes = list(type_weights.keys())
            weights = list(type_weights.values())
            building_type = rng.choices(subtypes, weights=weights, k=1)[0]
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
                x=lot_center_x,
                y=lot_center_y,
                building_type=building_type,
                capacity=capacity,
                vacancies=vacancies,
                name=name,
                width=frontage * FOOTPRINT_FILL_FRACTION,
                height=depth * FOOTPRINT_FILL_FRACTION,
                rotation=rotation,
            ))
            building_id += 1

    return buildings
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_blocks.py tests/test_buildings.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add town_shaper/blocks.py town_shaper/buildings.py tests/test_blocks.py tests/test_buildings.py
git commit -m "feat: add lot subdivision and building placement within blocks

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

### Task 5: Wire block/lot generation into `generate_town`

**Files:**
- Modify: `town_shaper/blocks.py`
- Modify: `town_shaper/generate.py`
- Test: `tests/test_blocks.py`, `tests/test_generate.py`

**Interfaces:**
- Consumes: `subdivide_into_blocks`, `place_buildings_in_block` (Tasks 3-4); `road_network` (from `generate_road_network`, already wired into `generate_town`).
- Produces: `town_shaper.blocks.generate_blocks_and_buildings(district, town_seed, next_building_id, next_node_id, next_edge_id, target_population=0, density_multiplier=1.0, magic_prevalence=0.0) -> Tuple[List[Building], List[RoadNode], List[RoadEdge], int, int]`. `generate_town` now calls `fill_district_buildings` only for `ZoneType.FARMLAND_EDGE` districts, and `generate_blocks_and_buildings` for every other zone, merging the returned local road nodes/edges into `road_network`.

- [ ] **Step 1: Write a failing test for the per-district orchestration function**

Add to `tests/test_blocks.py`:

```python
from town_shaper.blocks import generate_blocks_and_buildings


def _multi_part_district(zone_type, polygon_parts):
    anchor = Anchor(id=1, zone_type=zone_type, x=0.0, y=0.0)
    return District(id=1, zone_type=zone_type, anchor=anchor, polygon_parts=polygon_parts)


def test_generate_blocks_and_buildings_covers_every_polygon_part():
    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(40.0, 20.0), _rectangle(30.0, 15.0)])

    buildings, nodes, edges, next_node_id, next_edge_id = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, next_node_id=0, next_edge_id=0,
        target_population=3000, magic_prevalence=0.0,
    )

    assert len(buildings) > 0
    building_ids = [b.id for b in buildings]
    assert building_ids == sorted(building_ids)
    assert building_ids == list(range(len(buildings)))  # sequential, starting at next_building_id
    assert next_node_id >= 0
    assert next_edge_id >= 0
    # nodes/edges may be empty if both parts are already under target area,
    # but the counters must never regress.
    assert next_node_id >= len(nodes)
    assert next_edge_id >= len(edges)
```

Add to `tests/test_generate.py`:

```python
def test_generate_town_places_footprint_buildings_in_urban_zones():
    town = generate_town(("town", 1), target_population=3000)

    urban_buildings = [
        b for d in town.districts for b in d.buildings
        if d.zone_type != ZoneType.FARMLAND_EDGE
    ]
    assert urban_buildings
    for building in urban_buildings:
        assert building.width > 0
        assert building.height > 0

    farmland_buildings = [
        b for d in town.districts for b in d.buildings
        if d.zone_type == ZoneType.FARMLAND_EDGE
    ]
    from town_shaper.buildings import FARMLAND_BUILDING_HEIGHT, FARMLAND_BUILDING_WIDTH
    for building in farmland_buildings:
        assert building.width == FARMLAND_BUILDING_WIDTH
        assert building.height == FARMLAND_BUILDING_HEIGHT


def test_generate_town_road_network_includes_local_streets():
    town = generate_town(("town", 1), target_population=5000)  # larger town, more urban blocks to split

    local_edges = [e for e in town.road_network.edges if e.road_type == "local"]
    assert local_edges  # at least one urban district was large enough to subdivide
```

Add `ZoneType` to `tests/test_generate.py`'s existing imports from `town_shaper.models` if not already imported there (check the file first — if `ZoneType` isn't imported, add it to whatever import line already pulls from `town_shaper.models`, or add a new `from town_shaper.models import ZoneType` line).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_blocks.py::test_generate_blocks_and_buildings_covers_every_polygon_part tests/test_generate.py::test_generate_town_places_footprint_buildings_in_urban_zones tests/test_generate.py::test_generate_town_road_network_includes_local_streets -v`
Expected: `test_generate_blocks_and_buildings_covers_every_polygon_part` FAILS with `ImportError`; the other two FAIL with `AssertionError` (every building still has `width == FARMLAND_BUILDING_WIDTH` regardless of zone, since dispatch doesn't exist yet).

- [ ] **Step 3: Implement `generate_blocks_and_buildings`**

In `town_shaper/blocks.py`, add `from town_shaper.seeding import rng_for` to the top-of-file imports (alongside the existing `town_shaper.buildings`/`town_shaper.geometry`/`town_shaper.models` imports), then add this function at the bottom of the file:

```python
def generate_blocks_and_buildings(
    district: District, town_seed, next_building_id: int, next_node_id: int, next_edge_id: int,
    target_population: int = 0, density_multiplier: float = 1.0, magic_prevalence: float = 0.0,
) -> Tuple[List[Building], List[RoadNode], List[RoadEdge], int, int]:
    rng = rng_for(town_seed, "blocks", district.id)
    buildings: List[Building] = []
    local_nodes: List[RoadNode] = []
    local_edges: List[RoadEdge] = []
    building_id = next_building_id

    for part in district.polygon_parts:
        blocks, part_nodes, part_edges, next_node_id, next_edge_id = subdivide_into_blocks(
            part, district.zone_type, rng, next_node_id, next_edge_id,
        )
        local_nodes.extend(part_nodes)
        local_edges.extend(part_edges)
        for block in blocks:
            block_buildings = place_buildings_in_block(
                block, district, rng, building_id, target_population, magic_prevalence, density_multiplier,
            )
            buildings.extend(block_buildings)
            building_id += len(block_buildings)

    return buildings, local_nodes, local_edges, next_node_id, next_edge_id
```

- [ ] **Step 4: Wire the dispatch into `generate_town`**

In `town_shaper/generate.py`, add to the imports:

```python
from town_shaper.blocks import generate_blocks_and_buildings
from town_shaper.models import Town, ZoneType
```

(`ZoneType` joins the existing `Town` import from `town_shaper.models` — merge into the existing import line rather than adding a duplicate.)

Replace the existing per-district loop:

```python
    for district in districts:
        next_building_id = district.id * BUILDING_ID_STRIDE
        buildings = fill_district_buildings(
            district, seed, next_building_id,
            target_population=target_population, density_multiplier=density_multiplier,
            magic_prevalence=magic_prevalence,
        )
        district.buildings = buildings
```

with:

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

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_blocks.py tests/test_generate.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: all tests PASS. This is the task that touches the shared `generate_town` orchestrator, so the full suite is the real regression guard — pay particular attention to any existing test that asserted something about building counts or types for non-farmland zones (e.g. `test_generate_town_with_magic_prevalence_can_produce_arcane_shops`), since the placement algorithm changed even though the type-selection logic (`resolve_building_type_weights`) did not.

- [ ] **Step 7: Commit**

```bash
git add town_shaper/blocks.py town_shaper/generate.py tests/test_blocks.py tests/test_generate.py
git commit -m "feat: wire block/lot building placement into generate_town for urban zones

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

### Task 6: Schema and persistence

**Files:**
- Modify: `town_db/schema.py`
- Modify: `town_db/generate.py`
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Consumes: `Building.width`/`.height`/`.rotation` (Task 2).
- Produces: `buildings` table gains `width`/`height`/`rotation` columns, populated by `generate_town_database`.

- [ ] **Step 1: Write a failing round-trip test**

Add to `tests/test_db_schema.py`:

```python
def test_generate_town_database_persists_building_footprints(tmp_path):
    from town_db.generate import generate_town_database

    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path)

    conn = connect(db_path)
    rows = conn.execute("SELECT width, height, rotation FROM buildings").fetchall()
    conn.close()

    assert len(rows) > 0
    assert all(row[0] > 0 and row[1] > 0 for row in rows)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_db_schema.py::test_generate_town_database_persists_building_footprints -v`
Expected: FAIL with `sqlite3.OperationalError: no such column: width`

- [ ] **Step 3: Add the columns to the schema**

In `town_db/schema.py`, change the `buildings` table definition:

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

- [ ] **Step 4: Insert the new columns**

In `town_db/generate.py`, change the buildings insert:

```python
            conn.execute(
                "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, name, "
                "width, height, rotation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (building.id, district.id, district.zone_type.value, building.building_type,
                 building.x, building.y, building.capacity, building.name,
                 building.width, building.height, building.rotation),
            )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_db_schema.py::test_generate_town_database_persists_building_footprints -v`
Expected: PASS.

- [ ] **Step 6: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add town_db/schema.py town_db/generate.py tests/test_db_schema.py
git commit -m "feat: persist building footprint columns (width, height, rotation)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

### Task 7: Static PNG rendering

**Files:**
- Modify: `town_db/render.py`
- Test: `tests/test_db_render.py`

**Interfaces:**
- Consumes: `buildings.width`/`.height`/`.rotation` (Task 6).
- Produces: no new public function — non-landmark buildings render as rotated-rectangle footprints instead of a uniform scatter dot. Landmark buildings (`LANDMARK_BUILDING_TYPES`) are completely unchanged — this task does not touch that code path.

- [ ] **Step 1: Write a failing test**

Add to `tests/test_db_render.py`:

```python
def test_render_town_draws_rotated_building_footprints(tmp_path):
    db_path = str(tmp_path / "town.db")
    output_path = str(tmp_path / "town.png")

    conn = connect(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'poor_residential', ?)",
        (json.dumps([[[0.0, 0.0], [40.0, 0.0], [40.0, 40.0], [0.0, 40.0]]]),),
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, width, height, rotation) "
        "VALUES (1, 1, 'poor_residential', 'residence', 20.0, 20.0, 6, 5.0, 6.0, 0.7853981633974483)"
    )
    conn.commit()
    conn.close()

    render_town(db_path, output_path)  # must not raise

    with open(output_path, "rb") as f:
        header = f.read(8)
    assert header == b"\x89PNG\r\n\x1a\n"
```

- [ ] **Step 2: Run the test to confirm today's baseline**

Run: `pytest tests/test_db_render.py::test_render_town_draws_rotated_building_footprints -v`
Expected: PASS — `render_town` already draws this building as a generic scatter dot today (it ignores `width`/`height`/`rotation` entirely, and `width`/`height`/`rotation` aren't even selected by its current query). That's expected; this test becomes a real regression guard once Step 3 makes it draw the rotated footprint instead — it must not crash on the exact column shape Task 6 added.

- [ ] **Step 3: Draw non-landmark buildings as rotated footprints**

In `town_db/render.py`, add `import math` at the top (alongside the existing `import json`/`import sqlite3`).

Change the buildings query:

```python
    buildings = conn.execute(
        "SELECT x, y, building_type, width, height, rotation FROM buildings"
    ).fetchall()
```

Add a helper near the other module-level functions are not present in this file today (there are none — add it directly above `render_town`):

```python
def _rotated_rect_corners(cx: float, cy: float, width: float, height: float, rotation: float):
    hw, hh = width / 2.0, height / 2.0
    cos_r, sin_r = math.cos(rotation), math.sin(rotation)
    return [
        (cx + lx * cos_r - ly * sin_r, cy + lx * sin_r + ly * cos_r)
        for lx, ly in [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    ]
```

Replace the buildings-drawing block:

```python
    generic_x: List[float] = []
    generic_y: List[float] = []
    landmark_points: Dict[str, List[Tuple[float, float]]] = {}
    for x, y, building_type in buildings:
        if building_type in LANDMARK_BUILDING_TYPES:
            landmark_points.setdefault(building_type, []).append((x, y))
        else:
            generic_x.append(x)
            generic_y.append(y)

    if generic_x:
        ax.scatter(generic_x, generic_y, s=4, c=GENERIC_BUILDING_COLOR, zorder=3)
```

with:

```python
    landmark_points: Dict[str, List[Tuple[float, float]]] = {}
    for x, y, building_type, width, height, rotation in buildings:
        if building_type in LANDMARK_BUILDING_TYPES:
            landmark_points.setdefault(building_type, []).append((x, y))
        else:
            corners = _rotated_rect_corners(x, y, width, height, rotation)
            ax.add_patch(MplPolygon(
                corners, closed=True, facecolor=GENERIC_BUILDING_COLOR, edgecolor="none", zorder=3,
            ))
```

(The `landmark_points` collection and the landmark-drawing loop further down, which uses `ax.scatter(..., marker=marker, ...)`, are completely unchanged — landmarks still render exactly as before.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_db_render.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add town_db/render.py tests/test_db_render.py
git commit -m "feat: render non-landmark buildings as rotated footprints in the static PNG

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

- [ ] **Step 7: Manual verification**

Run `python scripts/generate_town.py` then `python scripts/render_town.py my_town.db my_town.png` and open `my_town.png`. Confirm: non-landmark buildings (residences, manors, farmsteads, market stalls, blacksmiths, warehouses, docks) now render as small rotated rectangles roughly following street lines in urban districts, while landmark buildings (temples, shops, taverns, etc.) still show their existing distinct marker shapes/colors and legend, unchanged.

---

### Task 8: Viewer API

**Files:**
- Modify: `town_viewer/queries.py`
- Test: `tests/test_viewer_queries.py`

**Interfaces:**
- Consumes: `buildings.width`/`.height`/`.rotation` (Task 6).
- Produces: `get_map_data`'s and `get_building_detail`'s building dicts gain `width`, `height`, `rotation` keys.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_viewer_queries.py`:

```python
def test_get_map_data_includes_building_footprints(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', ?)",
        (json.dumps([[[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]]]),),
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, width, height, rotation) "
        "VALUES (1, 1, 'civic', 'temple', 10.0, 10.0, 0, 12.0, 14.4, 0.0)"
    )
    conn.commit()

    data = get_map_data(conn)
    conn.close()

    building = data["buildings"][0]
    assert building["width"] == 12.0
    assert building["height"] == 14.4
    assert building["rotation"] == 0.0


def test_get_building_detail_includes_footprint(tmp_path):
    db_path = str(tmp_path / "town.db")
    from tests.town_viewer_fixtures import build_full_town
    build_full_town(db_path)

    conn = connect(db_path)
    conn.execute("UPDATE buildings SET width = 5.0, height = 6.0, rotation = 1.5 WHERE id = 4")
    conn.commit()
    building = get_building_detail(conn, 4)
    conn.close()

    assert building["width"] == 5.0
    assert building["height"] == 6.0
    assert building["rotation"] == 1.5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_viewer_queries.py::test_get_map_data_includes_building_footprints tests/test_viewer_queries.py::test_get_building_detail_includes_footprint -v`
Expected: FAIL — the inserted rows are missing `width`/`height`/`rotation` keys in the returned dicts (`KeyError` in the assertions).

- [ ] **Step 3: Add the fields**

In `town_viewer/queries.py`, change `get_map_data`'s buildings list:

```python
    buildings = [
        {
            "id": row[0], "district_id": row[1], "zone_type": row[2], "building_type": row[3],
            "x": row[4], "y": row[5], "name": row[6],
            "width": row[7], "height": row[8], "rotation": row[9],
        }
        for row in conn.execute(
            "SELECT id, district_id, zone_type, building_type, x, y, name, width, height, rotation FROM buildings"
        )
    ]
```

Change `get_building_detail`:

```python
    row = conn.execute(
        "SELECT id, district_id, zone_type, building_type, x, y, capacity, name, width, height, rotation "
        "FROM buildings WHERE id = ?",
        (building_id,),
    ).fetchone()
    if row is None:
        return None

    building = {
        "id": row[0], "district_id": row[1], "zone_type": row[2], "building_type": row[3],
        "x": row[4], "y": row[5], "capacity": row[6], "name": row[7],
        "width": row[8], "height": row[9], "rotation": row[10],
    }
```

- [ ] **Step 4: Fix the pre-existing exact-dict-equality test, then run everything**

Adding `width`/`height`/`rotation` to `get_map_data`'s building dicts breaks
`test_get_map_data_returns_districts_buildings_and_water`'s exact-equality
assertion on `data["buildings"]` (it doesn't set those columns in its
fixture insert, so the schema's `DEFAULT 0` applies — SQLite's REAL column
affinity stores and returns that as `0.0`, not `0`). Update it:

```python
    assert data["buildings"] == [
        {
            "id": 1, "district_id": 1, "zone_type": "civic", "building_type": "temple",
            "x": 10.0, "y": 10.0, "name": None,
            "width": 0.0, "height": 0.0, "rotation": 0.0,
        }
    ]
```

Run: `pytest tests/test_viewer_queries.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add town_viewer/queries.py tests/test_viewer_queries.py
git commit -m "feat: expose building footprints in the viewer API

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

### Task 9: Viewer frontend rendering

**Files:**
- Modify: `town_viewer/static/app.js`

**Interfaces:**
- Consumes: `building.width`/`.height`/`.rotation` (Task 8's `/api/map` and `/api/buildings/<id>` response shapes).
- Produces: no new exported function — `draw()` renders every building as its real rotated footprint (replacing the old fixed-size `LANDMARK_SIZE`/`GENERIC_SIZE` square), and `findBuildingAt` does rotated-rectangle hit-testing. No automated test — same no-JS-test-infra situation as the road network's viewer task; verify manually per Step 4.

- [ ] **Step 1: Remove the fixed-size building sizing, keep color lookup**

In `town_viewer/static/app.js`, remove:

```javascript
const LANDMARK_SIZE = 10;
const GENERIC_SIZE = 5;

function buildingHalfSize(buildingType) {
  return (buildingType in LANDMARK_COLORS ? LANDMARK_SIZE : GENERIC_SIZE) / 2;
}
```

Keep `buildingColor(buildingType)` exactly as-is — every building (landmark or not) is still colored by type via `ALL_TYPED_COLORS`/`GENERIC_BUILDING_COLOR`, just no longer sized by a fixed constant now that real footprint data exists for every building.

- [ ] **Step 2: Draw every building as its real rotated footprint**

Replace the buildings-drawing loop in `draw()`:

```javascript
  for (const building of mapData.buildings) {
    const half = buildingHalfSize(building.building_type);
    const { sx, sy } = worldToScreen(building.x - half, building.y - half);
    const screenSize = half * 2 * view.scale;
    ctx.fillStyle = buildingColor(building.building_type);
    ctx.fillRect(sx, sy, screenSize, screenSize);
  }
```

with:

```javascript
  for (const building of mapData.buildings) {
    const { sx, sy } = worldToScreen(building.x, building.y);
    ctx.save();
    ctx.translate(sx, sy);
    ctx.rotate(building.rotation);
    const screenWidth = building.width * view.scale;
    const screenHeight = building.height * view.scale;
    ctx.fillStyle = buildingColor(building.building_type);
    ctx.fillRect(-screenWidth / 2, -screenHeight / 2, screenWidth, screenHeight);
    ctx.restore();
  }
```

`world` coordinates already map to canvas coordinates with no axis flip (`worldToScreen` scales and translates `x`/`y` identically, no sign inversion), so `ctx.rotate(building.rotation)` uses the rotation value directly — no sign negation needed, since both the world-space rotation (`atan2(dy, dx)` computed in `blocks.py` using the same coordinate sense) and canvas's rotation direction agree.

Also update the highlighted-building outline block, which uses the same old sizing:

```javascript
  for (const buildingId of highlightedBuildingIds) {
    const building = mapData.buildings.find((b) => b.id === buildingId);
    if (!building) continue;
    const half = buildingHalfSize(building.building_type);
    const { sx, sy } = worldToScreen(building.x - half, building.y - half);
    ctx.strokeStyle = "#ff2222";
    ctx.lineWidth = 3;
    ctx.strokeRect(sx, sy, half * 2 * view.scale, half * 2 * view.scale);
  }
```

to:

```javascript
  for (const buildingId of highlightedBuildingIds) {
    const building = mapData.buildings.find((b) => b.id === buildingId);
    if (!building) continue;
    const { sx, sy } = worldToScreen(building.x, building.y);
    ctx.save();
    ctx.translate(sx, sy);
    ctx.rotate(building.rotation);
    const screenWidth = building.width * view.scale;
    const screenHeight = building.height * view.scale;
    ctx.strokeStyle = "#ff2222";
    ctx.lineWidth = 3;
    ctx.strokeRect(-screenWidth / 2, -screenHeight / 2, screenWidth, screenHeight);
    ctx.restore();
  }
```

- [ ] **Step 3: Rotated-rectangle click hit-testing**

Replace `findBuildingAt`:

```javascript
function findBuildingAt(worldX, worldY) {
  for (const building of mapData.buildings) {
    const half = buildingHalfSize(building.building_type);
    if (
      worldX >= building.x - half && worldX <= building.x + half &&
      worldY >= building.y - half && worldY <= building.y + half
    ) {
      return building;
    }
  }
  return null;
}
```

with:

```javascript
function findBuildingAt(worldX, worldY) {
  for (const building of mapData.buildings) {
    const dx = worldX - building.x;
    const dy = worldY - building.y;
    const cosR = Math.cos(-building.rotation);
    const sinR = Math.sin(-building.rotation);
    const localX = dx * cosR - dy * sinR;
    const localY = dx * sinR + dy * cosR;
    if (Math.abs(localX) <= building.width / 2 && Math.abs(localY) <= building.height / 2) {
      return building;
    }
  }
  return null;
}
```

(This rotates the click point by `-building.rotation` into the building's own unrotated local frame, then does the same simple half-width/half-height box check as before — the inverse of the `+building.rotation` transform Step 2 draws with.)

- [ ] **Step 4: Manual verification**

Regenerate and start the viewer:

```bash
python scripts/generate_town.py
python scripts/serve_town_viewer.py my_town.db --port 5050
```

Open `http://127.0.0.1:5050/`. Confirm: buildings in urban districts (merchant, residential, civic, port) show as small rotated rectangles rather than uniform squares, visually following street-like rows; clicking directly on a rotated building's footprint (not just its old axis-aligned bounding square) opens its detail panel; clicking a resident and having their home/workplace highlighted still draws a correctly-rotated outline around the right building; panning/zooming still works. Stop the server when done.

- [ ] **Step 5: Commit**

```bash
git add town_viewer/static/app.js
git commit -m "feat: render building footprints as rotated rectangles in the viewer

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01C5SJjXFzhu28RY3ynrk9MU"
```

---

## Post-plan follow-up (not part of this plan)

Once this lands, update `docs/visual-interface-ideas.md`'s "Map should read as an actual city" follow-up entry to mark it done — both halves (road network and building footprints) of the original ask are now complete. Building-type icons (the other still-open follow-up) remains a separate, independent piece of work.
