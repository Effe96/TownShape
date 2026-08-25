# Town Water & Port Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add rivers and a coastline as real geometry that carves unbuildable space out of Town Shaper's districts, plus a `PORT` zone with dock/warehouse buildings, threaded end-to-end through `TownParameters` → `generate_town_from_parameters`.

**Architecture:** A new `town_shaper/water.py` module generates curved, buffered-strip river/coastline geometry as Shapely polygons (`WaterFeature`). `place_anchors` gains water-avoidance resampling for existing zones plus a new water-boundary-relative placement path for a single additive `PORT` anchor. `District.polygon` is generalized to `District.polygon_parts` (a list of rings) so `build_districts` can subtract water via Shapely `.difference()`, and `fill_district_buildings` splits its building-count target proportionally across the resulting parts. `generate_town`, `generate_town_database`, and `generate_town_from_parameters` each gain three new optional parameters (`num_rivers`, `has_coastline`, `has_port`) that default to "no water," reproducing today's exact behavior.

**Tech Stack:** Python 3.12. New dependency: **Shapely** (`shapely>=2.0`) for polygon buffering, union, and difference — the existing hand-rolled `geometry.py` clipper only handles convex rectangle clips and can't do line-buffering or non-convex polygon subtraction.

**Spec:** `docs/superpowers/specs/2026-08-25-town-water-port-design.md`

## Global Constraints

- Every new parameter (`num_rivers`, `has_coastline`, `has_port`) is optional with a default that reproduces today's exact behavior (`0`, `False`, `False` — no water generated) — no existing call site or test outside the files this plan touches should require changes.
- `ZoneType.PORT` is **additive**, not part of the existing 5-zone proportional system (`ZONE_PROPORTIONS`/`ZONE_RADIUS_BANDS`/`_ZONE_ORDER` in `town_shaper/anchors.py`, which must keep summing to 1.0). Exactly one `PORT` anchor is added when `has_port=True`, regardless of population.
- `District.polygon: List[Tuple[float, float]]` is renamed to `District.polygon_parts: List[List[Tuple[float, float]]]` — a breaking, internal-only format change (confirmed via repo-wide grep: only `town_shaper/buildings.py`, `town_db/generate.py`, and this repo's own tests read the field; no external consumer). The `districts.polygon` DB column keeps its name but its JSON shape changes from a flat point list to a list of rings.
- `TownParameters.__post_init__` raises `ValueError` when `has_port=True` and neither `num_rivers > 0` nor `has_coastline` — a port needs water to sit on. No upper bound on `num_rivers`; extreme values degrade gracefully (very small/empty districts) rather than raising, matching this project's existing tolerance for extreme `density_multiplier`/`area_per_resident_multiplier` combinations.
- Bridges and landmass connectivity are out of scope — `town_shaper/assignment.py` assigns residents to homes/workplaces purely by capacity, with no spatial pathing, so a river splitting the town has no simulation effect.
- Test files for the new `town_shaper/water.py` module go to `tests/test_water.py`, matching the project's one-file-per-module convention; changes to existing modules are tested by appending to their existing test files.

---

## Task 1: Shapely dependency, `WaterFeature` model, and water generation

**Files:**
- Modify: `requirements.txt`
- Modify: `town_shaper/models.py:1-3` (imports) and end of file (new dataclass)
- Create: `town_shaper/water.py`
- Test: `tests/test_water.py`

**Interfaces:**
- Consumes: `town_shaper.seeding.rng_for(base_seed, *parts) -> random.Random` (existing)
- Produces: `WaterFeature` dataclass (`id: int`, `kind: str`, `polygon: shapely.geometry.Polygon`) in `town_shaper/models.py`; `generate_water_features(seed, bounds: Tuple[float, float, float, float], num_rivers: int = 0, has_coastline: bool = False) -> List[WaterFeature]` in `town_shaper/water.py`. Module constants `RIVER_WIDTH`, `_EDGES`, and helper `_point_on_edge(edge, bounds, rng)` are used directly by Task 2's tests.

- [ ] **Step 1: Install Shapely and pin it**

Run: `pip install "shapely>=2.0"`
Expected: installs successfully.

Append to `requirements.txt`:
```
shapely>=2.0
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_water.py`:

```python
import math

from shapely.geometry import LineString

from town_shaper.seeding import rng_for
from town_shaper.water import RIVER_WIDTH, _EDGES, _point_on_edge, generate_water_features


def test_generate_water_features_returns_empty_list_with_no_water_requested():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    features = generate_water_features(("town", 1), bounds, num_rivers=0, has_coastline=False)
    assert features == []


def test_generate_water_features_river_count_matches_num_rivers():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    features = generate_water_features(("town", 1), bounds, num_rivers=3, has_coastline=False)
    assert [f.kind for f in features] == ["river", "river", "river"]
    assert [f.id for f in features] == [0, 1, 2]


def test_generate_water_features_coastline_adds_exactly_one_feature():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    features = generate_water_features(("town", 1), bounds, num_rivers=0, has_coastline=True)
    assert [f.kind for f in features] == ["coastline"]


def test_generate_water_features_rivers_and_coastline_combine():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    features = generate_water_features(("town", 1), bounds, num_rivers=2, has_coastline=True)
    assert [f.kind for f in features] == ["river", "river", "coastline"]


def test_generate_water_features_is_deterministic():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    first = generate_water_features(("town", 1), bounds, num_rivers=2, has_coastline=True)
    second = generate_water_features(("town", 1), bounds, num_rivers=2, has_coastline=True)
    for f1, f2 in zip(first, second):
        assert f1.id == f2.id
        assert f1.kind == f2.kind
        assert f1.polygon.equals(f2.polygon)


def test_generate_water_features_river_polygons_stay_within_bounds():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    features = generate_water_features(("town", 1), bounds, num_rivers=5, has_coastline=False)
    for feature in features:
        minx, miny, maxx, maxy = feature.polygon.bounds
        margin = RIVER_WIDTH  # buffering can push the polygon slightly past the exact edge point
        assert minx >= bounds[0] - margin
        assert miny >= bounds[1] - margin
        assert maxx <= bounds[2] + margin
        assert maxy <= bounds[3] + margin


def test_generate_water_features_river_is_curved_not_straight():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    rng = rng_for(("town", 1), "water", "river", 0)
    start_edge, end_edge = rng.sample(_EDGES, 2)
    start = _point_on_edge(start_edge, bounds, rng)
    end = _point_on_edge(end_edge, bounds, rng)
    straight_strip = LineString([start, end]).buffer(RIVER_WIDTH / 2.0)

    features = generate_water_features(("town", 1), bounds, num_rivers=1, has_coastline=False)
    river_polygon = features[0].polygon

    # A curved path between the same two endpoints sweeps strictly more area
    # than the straight buffered line between them -- this is the "must
    # curve, not be straight" requirement, verified geometrically rather
    # than by inspecting internal waypoints.
    assert river_polygon.area > straight_strip.area * 1.03


def test_generate_water_features_coastline_touches_its_chosen_edge():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    features = generate_water_features(("town", 1), bounds, num_rivers=0, has_coastline=True)
    coastline_polygon = features[0].polygon
    minx, miny, maxx, maxy = coastline_polygon.bounds
    touches_an_edge = (
        math.isclose(maxx, bounds[2], abs_tol=1.0) or math.isclose(minx, bounds[0], abs_tol=1.0)
        or math.isclose(maxy, bounds[3], abs_tol=1.0) or math.isclose(miny, bounds[1], abs_tol=1.0)
    )
    assert touches_an_edge
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_water.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_shaper.water'`

- [ ] **Step 4: Add `WaterFeature` to the models module**

In `town_shaper/models.py`, change the import block (lines 1-3) from:

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple
```

to:

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from shapely.geometry import Polygon
```

Append to the end of the file (after the `Town` dataclass):

```python


@dataclass
class WaterFeature:
    id: int
    kind: str
    polygon: Polygon
```

- [ ] **Step 5: Write `town_shaper/water.py`**

```python
# town_shaper/water.py
import math
from typing import List, Tuple

from shapely.geometry import LineString, Polygon

from town_shaper.models import WaterFeature
from town_shaper.seeding import rng_for

RIVER_WIDTH = 8.0
RIVER_WAYPOINT_JITTER = 0.15  # fraction of straight-line edge-to-edge distance
COASTLINE_DEPTH_FRACTION = 0.12  # fraction of the shorter bounds dimension
COASTLINE_JITTER = 0.08  # fraction of the shorter bounds dimension

_EDGES = ["north", "south", "east", "west"]


def _point_on_edge(edge: str, bounds: Tuple[float, float, float, float], rng) -> Tuple[float, float]:
    min_x, min_y, max_x, max_y = bounds
    if edge == "north":
        return (rng.uniform(min_x, max_x), max_y)
    if edge == "south":
        return (rng.uniform(min_x, max_x), min_y)
    if edge == "east":
        return (max_x, rng.uniform(min_y, max_y))
    return (min_x, rng.uniform(min_y, max_y))  # "west"


def _curved_strip(start: Tuple[float, float], end: Tuple[float, float], rng, width: float) -> Polygon:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return LineString([start, end]).buffer(width / 2.0)

    perp = (-dy / length, dx / length)  # unit vector perpendicular to start->end
    waypoint_count = rng.randint(2, 3)

    points = [start]
    for i in range(1, waypoint_count + 1):
        t = i / (waypoint_count + 1)
        base_x = start[0] + dx * t
        base_y = start[1] + dy * t
        jitter = rng.uniform(-RIVER_WAYPOINT_JITTER, RIVER_WAYPOINT_JITTER) * length
        points.append((base_x + perp[0] * jitter, base_y + perp[1] * jitter))
    points.append(end)

    return LineString(points).buffer(width / 2.0)


def _generate_coastline(seed, bounds: Tuple[float, float, float, float]) -> Polygon:
    rng = rng_for(seed, "water", "coastline")
    min_x, min_y, max_x, max_y = bounds
    edge = rng.choice(_EDGES)
    short_dimension = min(max_x - min_x, max_y - min_y)
    depth = short_dimension * COASTLINE_DEPTH_FRACTION
    jitter = short_dimension * COASTLINE_JITTER

    if edge in ("north", "south"):
        base_y = max_y - depth if edge == "north" else min_y + depth
        start = (min_x, base_y + rng.uniform(-jitter, jitter))
        end = (max_x, base_y + rng.uniform(-jitter, jitter))
    else:
        base_x = max_x - depth if edge == "east" else min_x + depth
        start = (base_x + rng.uniform(-jitter, jitter), min_y)
        end = (base_x + rng.uniform(-jitter, jitter), max_y)

    strip = _curved_strip(start, end, rng, depth * 2.0)

    # Extend the strip past the chosen edge so the full area between the
    # strip and the map boundary is water, not just a buffered line near it.
    sea_box_bounds = {
        "north": (min_x - depth, max_y - depth, max_x + depth, max_y + depth * 4),
        "south": (min_x - depth, min_y - depth * 4, max_x + depth, min_y + depth),
        "east": (max_x - depth, min_y - depth, max_x + depth * 4, max_y + depth),
        "west": (min_x - depth * 4, min_y - depth, min_x + depth, max_y + depth),
    }[edge]
    sea_box = Polygon.from_bounds(*sea_box_bounds)
    return strip.union(sea_box)


def generate_water_features(
    seed, bounds: Tuple[float, float, float, float],
    num_rivers: int = 0, has_coastline: bool = False,
) -> List[WaterFeature]:
    features: List[WaterFeature] = []
    feature_id = 0

    for i in range(num_rivers):
        rng = rng_for(seed, "water", "river", i)
        start_edge, end_edge = rng.sample(_EDGES, 2)
        start = _point_on_edge(start_edge, bounds, rng)
        end = _point_on_edge(end_edge, bounds, rng)
        polygon = _curved_strip(start, end, rng, RIVER_WIDTH)
        features.append(WaterFeature(id=feature_id, kind="river", polygon=polygon))
        feature_id += 1

    if has_coastline:
        polygon = _generate_coastline(seed, bounds)
        features.append(WaterFeature(id=feature_id, kind="coastline", polygon=polygon))
        feature_id += 1

    return features
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_water.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add requirements.txt town_shaper/models.py town_shaper/water.py tests/test_water.py
git commit -m "feat: add water feature generation (curved rivers, coastline)"
```

---

## Task 2: `ZoneType.PORT`, port building types, and water-aware anchor placement

**Files:**
- Modify: `town_shaper/models.py` (add `PORT` to the `ZoneType` enum)
- Modify: `town_shaper/buildings.py` (port entries in the four zone-keyed dicts)
- Modify: `town_shaper/anchors.py` (`place_anchors` gains water-avoidance + port placement)
- Modify: `tests/test_models.py` (fix the now-stale 5-member assertion)
- Modify: `tests/test_anchors.py` (fix the now-stale exhaustive-zone-type test; append new tests)
- Modify: `tests/test_buildings.py` (append port building tests)

**Interfaces:**
- Consumes: `WaterFeature`/Shapely (Task 1)
- Produces: `ZoneType.PORT` member; `place_anchors(town_seed, target_population, bounds, water_polygon=None, has_port=False) -> List[Anchor]` — raises `ValueError` if `has_port=True` and `water_polygon is None`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_models.py`, replace the `test_zone_type_has_five_members` function (lines 7-10):

```python
def test_zone_type_has_five_members():
    assert {z.value for z in ZoneType} == {
        "civic", "merchant", "rich_residential", "poor_residential", "farmland_edge",
    }
```

with:

```python
def test_zone_type_has_six_members():
    assert {z.value for z in ZoneType} == {
        "civic", "merchant", "rich_residential", "poor_residential", "farmland_edge", "port",
    }
```

In `tests/test_anchors.py`, replace `test_compute_anchor_counts_has_at_least_one_of_each_zone_type` (lines 23-26):

```python
def test_compute_anchor_counts_has_at_least_one_of_each_zone_type():
    counts = compute_anchor_counts(target_population=3000)
    for zone_type in ZoneType:
        assert counts[zone_type] >= 1
```

with:

```python
def test_compute_anchor_counts_has_at_least_one_of_each_non_port_zone_type():
    # PORT is deliberately excluded from compute_anchor_counts' proportional
    # system -- its anchor (if any) is added separately by place_anchors,
    # always exactly one, only when has_port=True.
    counts = compute_anchor_counts(target_population=3000)
    assert ZoneType.PORT not in counts
    for zone_type in ZoneType:
        if zone_type == ZoneType.PORT:
            continue
        assert counts[zone_type] >= 1
```

Append to `tests/test_anchors.py`:

```python
def test_place_anchors_without_port_has_no_port_anchor():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    assert all(a.zone_type != ZoneType.PORT for a in anchors)


def test_place_anchors_has_port_without_water_raises():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    with pytest.raises(ValueError):
        place_anchors(("town", 1), 3000, bounds, has_port=True)


def test_place_anchors_adds_exactly_one_port_anchor():
    from shapely.geometry import Polygon

    bounds = (-100.0, -100.0, 100.0, 100.0)
    water_polygon = Polygon([(-100.0, -20.0), (100.0, -20.0), (100.0, 20.0), (-100.0, 20.0)])
    anchors = place_anchors(("town", 1), 3000, bounds, water_polygon=water_polygon, has_port=True)
    port_anchors = [a for a in anchors if a.zone_type == ZoneType.PORT]
    assert len(port_anchors) == 1


def test_place_anchors_port_anchor_does_not_change_other_zone_counts():
    from shapely.geometry import Polygon

    bounds = (-100.0, -100.0, 100.0, 100.0)
    water_polygon = Polygon([(-100.0, -20.0), (100.0, -20.0), (100.0, 20.0), (-100.0, 20.0)])
    without_port = place_anchors(("town", 1), 3000, bounds)
    with_port = place_anchors(("town", 1), 3000, bounds, water_polygon=water_polygon, has_port=True)

    without_counts = {}
    for a in without_port:
        without_counts[a.zone_type] = without_counts.get(a.zone_type, 0) + 1
    with_counts = {}
    for a in with_port:
        if a.zone_type == ZoneType.PORT:
            continue
        with_counts[a.zone_type] = with_counts.get(a.zone_type, 0) + 1
    assert without_counts == with_counts


def test_place_anchors_avoids_water_polygon():
    from shapely.geometry import Point, Polygon

    bounds = (-100.0, -100.0, 100.0, 100.0)
    water_polygon = Polygon([(-100.0, -5.0), (100.0, -5.0), (100.0, 5.0), (-100.0, 5.0)])
    anchors = place_anchors(("town", 1), 3000, bounds, water_polygon=water_polygon)
    for anchor in anchors:
        assert not water_polygon.contains(Point(anchor.x, anchor.y))
```

Append to `tests/test_buildings.py`:

```python
def test_port_zone_building_types_have_no_home_capacity():
    from town_shaper.buildings import BUILDING_HOME_CAPACITY, BUILDING_TYPES_BY_ZONE
    for building_type in BUILDING_TYPES_BY_ZONE[ZoneType.PORT]:
        assert building_type not in BUILDING_HOME_CAPACITY


def test_fill_district_buildings_port_zone_produces_expected_building_types():
    district = _square_district(ZoneType.PORT, side=200.0)
    buildings = fill_district_buildings(district, ("town", 1), next_building_id=0)
    assert len(buildings) > 0
    assert all(b.building_type in {"dock", "warehouse", "harbormaster_office"} for b in buildings)


def test_port_building_vacancies_match_job_table():
    from town_shaper.buildings import JOB_VACANCIES_BY_BUILDING_TYPE
    district = _square_district(ZoneType.PORT, side=200.0)
    buildings = fill_district_buildings(district, ("town", 1), next_building_id=0)
    for building in buildings:
        expected = JOB_VACANCIES_BY_BUILDING_TYPE[building.building_type]
        expected_total = sum(count for _, count in expected)
        assert len(building.vacancies) == expected_total
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_models.py tests/test_anchors.py tests/test_buildings.py -v`
Expected: FAIL — `test_zone_type_has_six_members` (no `PORT` member yet), the port-anchor tests (`TypeError: place_anchors() got an unexpected keyword argument 'water_polygon'`), and the port-building tests (`KeyError: <ZoneType.PORT...>` from `BUILDING_TYPES_BY_ZONE`).

- [ ] **Step 3: Add `PORT` to `ZoneType`**

In `town_shaper/models.py`, change the `ZoneType` enum from:

```python
class ZoneType(Enum):
    CIVIC = "civic"
    MERCHANT = "merchant"
    RICH_RESIDENTIAL = "rich_residential"
    POOR_RESIDENTIAL = "poor_residential"
    FARMLAND_EDGE = "farmland_edge"
```

to:

```python
class ZoneType(Enum):
    CIVIC = "civic"
    MERCHANT = "merchant"
    RICH_RESIDENTIAL = "rich_residential"
    POOR_RESIDENTIAL = "poor_residential"
    FARMLAND_EDGE = "farmland_edge"
    PORT = "port"
```

- [ ] **Step 4: Add port building types to `town_shaper/buildings.py`**

Change the four zone-keyed dicts (lines 8-49) — add a `ZoneType.PORT` entry to each of the first three, and three new keys to `JOB_VACANCIES_BY_BUILDING_TYPE`:

```python
BUILDING_DENSITY_PER_AREA: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 1 / 550,
    ZoneType.MERCHANT: 1 / 220,
    ZoneType.RICH_RESIDENTIAL: 1 / 500,
    ZoneType.POOR_RESIDENTIAL: 1 / 1000,
    ZoneType.FARMLAND_EDGE: 1 / 600,
    ZoneType.PORT: 1 / 250,
}

MIN_BUILDING_SPACING: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 15.0,
    ZoneType.MERCHANT: 8.0,
    ZoneType.RICH_RESIDENTIAL: 12.0,
    ZoneType.POOR_RESIDENTIAL: 5.0,
    ZoneType.FARMLAND_EDGE: 20.0,
    ZoneType.PORT: 8.0,
}

BUILDING_TYPES_BY_ZONE: Dict[ZoneType, Dict[str, float]] = {
    ZoneType.CIVIC: {
        "temple": 0.25, "town_hall": 0.1, "school": 0.15, "guard_post": 0.25,
        "garrison": 0.1, "healer": 0.1, "university": 0.05,
    },
    ZoneType.MERCHANT: {"shop": 0.5, "tavern": 0.2, "market_stall": 0.3},
    ZoneType.RICH_RESIDENTIAL: {"manor": 1.0},
    ZoneType.POOR_RESIDENTIAL: {"residence": 1.0},
    ZoneType.FARMLAND_EDGE: {"farmstead": 1.0},
    ZoneType.PORT: {"dock": 0.4, "warehouse": 0.35, "harbormaster_office": 0.25},
}

JOB_VACANCIES_BY_BUILDING_TYPE: Dict[str, List[Tuple[str, int]]] = {
    "temple": [("priest", 1), ("acolyte", 2)],
    "town_hall": [("clerk", 3)],
    "school": [("teacher", 2)],
    "guard_post": [("guard", 4)],
    "garrison": [("soldier", 6)],
    "healer": [("healer", 1)],
    "university": [("scholar", 3)],
    "shop": [("shopkeep", 1), ("shop_staff", 2)],
    "tavern": [("barkeep", 1), ("tavern_staff", 2)],
    "market_stall": [("trader", 1)],
    "manor": [("noble", 1), ("servant", 3)],
    "residence": [],
    "farmstead": [("farmer", 1), ("farmhand", 3)],
    "dock": [("dockworker", 3)],
    "warehouse": [("warehouse_clerk", 1), ("laborer", 2)],
    "harbormaster_office": [("harbormaster", 1), ("customs_clerk", 2)],
}
```

No `BUILDING_HOME_CAPACITY` entries are added for `dock`/`warehouse`/`harbormaster_office` — none of these are housing, same treatment as `shop`/`tavern`.

- [ ] **Step 5: Update `place_anchors` in `town_shaper/anchors.py`**

Add the import at the top of the file (after the existing imports):

```python
from shapely.geometry import Point
```

Add these module constants after `_ZONE_ORDER`:

```python
MAX_WATER_RESAMPLE_ATTEMPTS = 20
PORT_BOUNDARY_SAMPLE_COUNT = 40
PORT_LAND_NUDGE_DISTANCE = 10.0
```

Replace `place_anchors` (lines 68-92) with:

```python
def _clamp_to_bounds(x: float, y: float, bounds: Tuple[float, float, float, float]) -> Tuple[float, float]:
    min_x, min_y, max_x, max_y = bounds
    return min(max(x, min_x), max_x), min(max(y, min_y), max_y)


def _draw_anchor_point(
    rng, band_min: float, band_max: float,
    center_x: float, center_y: float, half_width: float, half_height: float,
    bounds: Tuple[float, float, float, float],
) -> Tuple[float, float]:
    angle = rng.uniform(0.0, 2.0 * math.pi)
    radius_fraction = rng.uniform(band_min, band_max)
    x = center_x + math.cos(angle) * radius_fraction * half_width
    y = center_y + math.sin(angle) * radius_fraction * half_height
    return _clamp_to_bounds(x, y, bounds)


def _place_port_anchor(town_seed, water_polygon, bounds, next_anchor_id: int) -> Anchor:
    rng = rng_for(town_seed, "anchors", "port")
    boundary = water_polygon.exterior
    min_x, min_y, max_x, max_y = bounds

    def _on_bounds_edge(x: float, y: float) -> bool:
        return (
            math.isclose(x, min_x, abs_tol=1e-6) or math.isclose(x, max_x, abs_tol=1e-6)
            or math.isclose(y, min_y, abs_tol=1e-6) or math.isclose(y, max_y, abs_tol=1e-6)
        )

    candidate = None
    for _ in range(PORT_BOUNDARY_SAMPLE_COUNT):
        fraction = rng.uniform(0.0, 1.0)
        point = boundary.interpolate(fraction, normalized=True)
        if _on_bounds_edge(point.x, point.y):
            continue
        candidate = (point.x, point.y)
        break

    if candidate is None:
        # Every sampled boundary point was on the map edge (e.g. a coastline
        # dominating the water shape) -- fall back to the boundary point
        # closest to the water body's own centroid.
        centroid = water_polygon.centroid
        nearest = boundary.interpolate(boundary.project(centroid))
        candidate = (nearest.x, nearest.y)

    centroid = water_polygon.centroid
    dx = candidate[0] - centroid.x
    dy = candidate[1] - centroid.y
    length = math.hypot(dx, dy)
    nudge = (0.0, 0.0) if length == 0 else (
        dx / length * PORT_LAND_NUDGE_DISTANCE, dy / length * PORT_LAND_NUDGE_DISTANCE
    )

    x, y = _clamp_to_bounds(candidate[0] + nudge[0], candidate[1] + nudge[1], bounds)
    return Anchor(id=next_anchor_id, zone_type=ZoneType.PORT, x=x, y=y)


def place_anchors(
    town_seed, target_population: int, bounds: Tuple[float, float, float, float],
    water_polygon=None, has_port: bool = False,
) -> List[Anchor]:
    if has_port and water_polygon is None:
        raise ValueError("has_port requires a water_polygon")

    counts = compute_anchor_counts(target_population)
    min_x, min_y, max_x, max_y = bounds
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    half_width = (max_x - min_x) / 2.0
    half_height = (max_y - min_y) / 2.0

    anchors: List[Anchor] = []
    anchor_id = 0
    for zone_type in _ZONE_ORDER:
        band_min, band_max = ZONE_RADIUS_BANDS[zone_type]
        for index in range(counts[zone_type]):
            rng = rng_for(town_seed, "anchors", zone_type.value, index)
            x, y = _draw_anchor_point(rng, band_min, band_max, center_x, center_y, half_width, half_height, bounds)
            if water_polygon is not None:
                attempts = 0
                while water_polygon.contains(Point(x, y)) and attempts < MAX_WATER_RESAMPLE_ATTEMPTS:
                    x, y = _draw_anchor_point(
                        rng, band_min, band_max, center_x, center_y, half_width, half_height, bounds
                    )
                    attempts += 1
                if water_polygon.contains(Point(x, y)):
                    nearest = water_polygon.exterior.interpolate(water_polygon.exterior.project(Point(x, y)))
                    x, y = _clamp_to_bounds(nearest.x, nearest.y, bounds)
            anchors.append(Anchor(id=anchor_id, zone_type=zone_type, x=x, y=y))
            anchor_id += 1

    if has_port:
        anchors.append(_place_port_anchor(town_seed, water_polygon, bounds, anchor_id))

    return anchors
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py tests/test_anchors.py tests/test_buildings.py tests/test_districts.py -v`
Expected: PASS (the `test_districts.py` re-run is a regression check — `place_anchors`'s new optional parameters must not change its no-water call sites)

- [ ] **Step 7: Commit**

```bash
git add town_shaper/models.py town_shaper/buildings.py town_shaper/anchors.py tests/test_models.py tests/test_anchors.py tests/test_buildings.py
git commit -m "feat: add PORT zone type with water-aware anchor placement"
```

---

## Task 3: `District.polygon` → `District.polygon_parts` (pure rename, no behavior change)

**Files:**
- Modify: `town_shaper/models.py` (`District` dataclass field)
- Modify: `town_shaper/districts.py:37` (wrap the result)
- Modify: `town_shaper/buildings.py` (`fill_district_buildings` reads the renamed field)
- Modify: `town_db/generate.py:53-54` (serialize the renamed field)
- Modify: `tests/test_models.py`, `tests/test_districts.py`, `tests/test_buildings.py`

**Interfaces:**
- Produces: `District.polygon_parts: List[List[Tuple[float, float]]]` (always exactly one part after this task — `build_districts` doesn't split anything yet; that's Task 4).

- [ ] **Step 1: Update the tests to use the new field name**

In `tests/test_models.py`, change `test_district_defaults_to_empty_buildings` (line 26-29) from:

```python
def test_district_defaults_to_empty_buildings():
    anchor = Anchor(id=1, zone_type=ZoneType.CIVIC, x=0.0, y=0.0)
    district = District(id=1, zone_type=ZoneType.CIVIC, anchor=anchor, polygon=[(0.0, 0.0)])
    assert district.buildings == []
```

to:

```python
def test_district_defaults_to_empty_buildings():
    anchor = Anchor(id=1, zone_type=ZoneType.CIVIC, x=0.0, y=0.0)
    district = District(id=1, zone_type=ZoneType.CIVIC, anchor=anchor, polygon_parts=[[(0.0, 0.0)]])
    assert district.buildings == []
```

In `tests/test_districts.py`, change `test_build_districts_partitions_bounding_box_area` (lines 17-24) from:

```python
def test_build_districts_partitions_bounding_box_area():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    districts = build_districts(anchors, bounds)

    box_area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
    total_district_area = sum(polygon_area(d.polygon) for d in districts)
    assert math.isclose(total_district_area, box_area, rel_tol=1e-6)
```

to:

```python
def test_build_districts_partitions_bounding_box_area():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    districts = build_districts(anchors, bounds)

    box_area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
    total_district_area = sum(polygon_area(part) for d in districts for part in d.polygon_parts)
    assert math.isclose(total_district_area, box_area, rel_tol=1e-6)
```

And `test_build_districts_each_polygon_contains_its_own_anchor` (lines 27-33) from:

```python
def test_build_districts_each_polygon_contains_its_own_anchor():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    districts = build_districts(anchors, bounds)

    for district in districts:
        assert point_in_polygon((district.anchor.x, district.anchor.y), district.polygon)
```

to:

```python
def test_build_districts_each_polygon_contains_its_own_anchor():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    districts = build_districts(anchors, bounds)

    for district in districts:
        assert len(district.polygon_parts) == 1
        assert point_in_polygon((district.anchor.x, district.anchor.y), district.polygon_parts[0])
```

In `tests/test_buildings.py`, change the `_square_district` helper (lines 8-11) from:

```python
def _square_district(zone_type, side=40.0, district_id=1):
    anchor = Anchor(id=district_id, zone_type=zone_type, x=side / 2, y=side / 2)
    polygon = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
    return District(id=district_id, zone_type=zone_type, anchor=anchor, polygon=polygon)
```

to:

```python
def _square_district(zone_type, side=40.0, district_id=1):
    anchor = Anchor(id=district_id, zone_type=zone_type, x=side / 2, y=side / 2)
    polygon = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
    return District(id=district_id, zone_type=zone_type, anchor=anchor, polygon_parts=[polygon])
```

And `test_fill_district_buildings_places_buildings_inside_district` (lines 34-42) from:

```python
def test_fill_district_buildings_places_buildings_inside_district():
    district = _square_district(ZoneType.POOR_RESIDENTIAL)
    buildings = fill_district_buildings(district, ("town", 1), next_building_id=0)

    assert len(buildings) > 0
    for building in buildings:
        assert point_in_polygon((building.x, building.y), district.polygon)
        assert building.district_id == district.id
        assert building.district_zone_type == ZoneType.POOR_RESIDENTIAL
```

to:

```python
def test_fill_district_buildings_places_buildings_inside_district():
    district = _square_district(ZoneType.POOR_RESIDENTIAL)
    buildings = fill_district_buildings(district, ("town", 1), next_building_id=0)

    assert len(buildings) > 0
    for building in buildings:
        assert point_in_polygon((building.x, building.y), district.polygon_parts[0])
        assert building.district_id == district.id
        assert building.district_zone_type == ZoneType.POOR_RESIDENTIAL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_models.py tests/test_districts.py tests/test_buildings.py -v`
Expected: FAIL with `TypeError: District.__init__() got an unexpected keyword argument 'polygon_parts'` (the dataclass field hasn't been renamed yet)

- [ ] **Step 3: Rename the field in `town_shaper/models.py`**

Change the `District` dataclass from:

```python
@dataclass
class District:
    id: int
    zone_type: ZoneType
    anchor: Anchor
    polygon: List[Tuple[float, float]]
    buildings: List[Building] = field(default_factory=list)
```

to:

```python
@dataclass
class District:
    id: int
    zone_type: ZoneType
    anchor: Anchor
    polygon_parts: List[List[Tuple[float, float]]]
    buildings: List[Building] = field(default_factory=list)
```

- [ ] **Step 4: Update `town_shaper/districts.py`**

Change the last line of the loop body in `build_districts` (line 37) from:

```python
        districts.append(District(id=anchor.id, zone_type=anchor.zone_type, anchor=anchor, polygon=polygon))
```

to:

```python
        districts.append(District(id=anchor.id, zone_type=anchor.zone_type, anchor=anchor, polygon_parts=[polygon]))
```

- [ ] **Step 5: Update `town_shaper/buildings.py`**

Change the start of `fill_district_buildings` (lines 82-92) from:

```python
def fill_district_buildings(
    district: District, town_seed, next_building_id: int,
    target_population: int = 0, density_multiplier: float = 1.0,
) -> List[Building]:
    rng = rng_for(town_seed, "buildings", district.id)
    area = polygon_area(district.polygon)
    density = BUILDING_DENSITY_PER_AREA[district.zone_type] * density_multiplier
    target_count = max(1, round(area * density))
    spacing = MIN_BUILDING_SPACING[district.zone_type] / density_multiplier

    points = poisson_disc_fill(district.polygon, target_count, spacing, rng)
```

to:

```python
def fill_district_buildings(
    district: District, town_seed, next_building_id: int,
    target_population: int = 0, density_multiplier: float = 1.0,
) -> List[Building]:
    rng = rng_for(town_seed, "buildings", district.id)
    polygon = district.polygon_parts[0]
    area = polygon_area(polygon)
    density = BUILDING_DENSITY_PER_AREA[district.zone_type] * density_multiplier
    target_count = max(1, round(area * density))
    spacing = MIN_BUILDING_SPACING[district.zone_type] / density_multiplier

    points = poisson_disc_fill(polygon, target_count, spacing, rng)
```

The rest of the function (from `type_weights = dict(...)` onward) is unchanged.

- [ ] **Step 6: Update `town_db/generate.py`**

Change line 53-54 from:

```python
        conn.execute(
            "INSERT INTO districts (id, zone_type, polygon) VALUES (?, ?, ?)",
            (district.id, district.zone_type.value, json.dumps(district.polygon)),
        )
```

to:

```python
        conn.execute(
            "INSERT INTO districts (id, zone_type, polygon) VALUES (?, ?, ?)",
            (district.id, district.zone_type.value, json.dumps(district.polygon_parts)),
        )
```

- [ ] **Step 7: Run the full suite to verify nothing else references the old field**

Run: `python -m pytest tests/ -v`
Expected: PASS for every test (this task is a pure rename — no test's expected values change, only field access syntax)

- [ ] **Step 8: Commit**

```bash
git add town_shaper/models.py town_shaper/districts.py town_shaper/buildings.py town_db/generate.py tests/test_models.py tests/test_districts.py tests/test_buildings.py
git commit -m "refactor: generalize District.polygon to polygon_parts (a list of rings)"
```

---

## Task 4: Water subtraction in `build_districts`, proportional multi-part building fill

**Files:**
- Modify: `town_shaper/districts.py`
- Modify: `town_shaper/buildings.py`
- Test: `tests/test_districts.py` (append)
- Test: `tests/test_buildings.py` (append)

**Interfaces:**
- Consumes: `District.polygon_parts` (Task 3), Shapely (Task 1)
- Produces: `build_districts(anchors, bounds, water_polygon=None) -> List[District]` — when `water_polygon` is given, each district's `polygon_parts` is the Voronoi cell minus water (0, 1, or many parts). `fill_district_buildings` unchanged signature, now correctly handles multi-part and zero-area districts.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_districts.py`:

```python
def test_build_districts_water_polygon_splits_a_district_into_multiple_parts():
    from shapely.geometry import Point, Polygon as ShapelyPolygon

    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    # A thin horizontal band crossing the whole map is virtually guaranteed
    # to bisect at least one district's Voronoi cell.
    water_polygon = ShapelyPolygon([(-100.0, -2.0), (100.0, -2.0), (100.0, 2.0), (-100.0, 2.0)])
    districts = build_districts(anchors, bounds, water_polygon=water_polygon)

    assert any(len(d.polygon_parts) > 1 for d in districts)
    for district in districts:
        for part in district.polygon_parts:
            assert len(part) >= 3
            for point in part:
                assert not water_polygon.contains(Point(point))


def test_build_districts_water_polygon_reduces_total_land_area():
    from shapely.geometry import Polygon as ShapelyPolygon

    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    water_polygon = ShapelyPolygon([(-100.0, -20.0), (100.0, -20.0), (100.0, 20.0), (-100.0, 20.0)])
    districts = build_districts(anchors, bounds, water_polygon=water_polygon)

    total_land_area = sum(polygon_area(part) for d in districts for part in d.polygon_parts)
    box_area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
    assert total_land_area == pytest.approx(box_area - water_polygon.area, rel=1e-3)


def test_build_districts_district_fully_inside_water_produces_no_parts():
    from shapely.geometry import Polygon as ShapelyPolygon

    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    districts_no_water = build_districts(anchors, bounds)
    target = districts_no_water[0]

    # buffer(positive) on a valid polygon always yields a strict superset,
    # so this water polygon is guaranteed to fully cover the target
    # district's own (unchanged, since Voronoi doesn't depend on water) cell.
    water_polygon = ShapelyPolygon(target.polygon_parts[0]).buffer(5.0)
    districts_with_water = build_districts(anchors, bounds, water_polygon=water_polygon)
    rebuilt_target = next(d for d in districts_with_water if d.id == target.id)

    assert rebuilt_target.polygon_parts == []


def test_build_districts_without_water_polygon_matches_previous_behavior():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    with_none = build_districts(anchors, bounds, water_polygon=None)
    without_arg = build_districts(anchors, bounds)
    key = lambda ds: [(d.id, d.polygon_parts) for d in ds]
    assert key(with_none) == key(without_arg)
```

Append to `tests/test_buildings.py`:

```python
def test_fill_district_buildings_zero_area_district_returns_no_buildings():
    anchor = Anchor(id=1, zone_type=ZoneType.POOR_RESIDENTIAL, x=0.0, y=0.0)
    district = District(id=1, zone_type=ZoneType.POOR_RESIDENTIAL, anchor=anchor, polygon_parts=[])
    buildings = fill_district_buildings(district, ("town", 1), next_building_id=0)
    assert buildings == []


def test_fill_district_buildings_multi_part_with_zero_count_second_part_matches_single_part():
    anchor = Anchor(id=1, zone_type=ZoneType.POOR_RESIDENTIAL, x=50.0, y=50.0)
    big_part = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    tiny_part = [(200.0, 200.0), (201.0, 200.0), (201.0, 201.0), (200.0, 201.0)]
    multi_part_district = District(
        id=1, zone_type=ZoneType.POOR_RESIDENTIAL, anchor=anchor, polygon_parts=[big_part, tiny_part],
    )
    single_part_district = District(
        id=1, zone_type=ZoneType.POOR_RESIDENTIAL, anchor=anchor, polygon_parts=[big_part],
    )

    multi_part_buildings = fill_district_buildings(multi_part_district, ("town", 1), next_building_id=0)
    single_part_buildings = fill_district_buildings(single_part_district, ("town", 1), next_building_id=0)

    key = lambda buildings: [(b.id, b.x, b.y, b.building_type) for b in buildings]
    assert key(multi_part_buildings) == key(single_part_buildings)


def test_fill_district_buildings_multi_part_splits_proportionally_to_area():
    anchor = Anchor(id=1, zone_type=ZoneType.POOR_RESIDENTIAL, x=0.0, y=0.0)
    large_part = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    small_part = [(200.0, 0.0), (250.0, 0.0), (250.0, 50.0), (200.0, 50.0)]
    district = District(
        id=1, zone_type=ZoneType.POOR_RESIDENTIAL, anchor=anchor, polygon_parts=[large_part, small_part],
    )

    buildings = fill_district_buildings(district, ("town", 1), next_building_id=0)
    large_part_buildings = [b for b in buildings if point_in_polygon((b.x, b.y), large_part)]
    small_part_buildings = [b for b in buildings if point_in_polygon((b.x, b.y), small_part)]

    assert len(large_part_buildings) == 10
    assert len(small_part_buildings) == 2
    assert len(large_part_buildings) + len(small_part_buildings) == len(buildings)
```

`tests/test_buildings.py` doesn't currently import `Anchor`/`District` at module scope for standalone use outside `_square_district` — check the top of the file: it already has `from town_shaper.models import Anchor, District, ZoneType`, so no import changes are needed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_districts.py tests/test_buildings.py -v -k "water_polygon or zero_area or multi_part"`
Expected: FAIL — `build_districts() got an unexpected keyword argument 'water_polygon'`, and the zero-area test fails because today's `target_count = max(1, round(...))` forces a phantom minimum of 1 against an empty `polygon_parts` list (`IndexError` from `polygon_parts[0]` on an empty list).

- [ ] **Step 3: Update `town_shaper/districts.py`**

Add imports at the top:

```python
from shapely.geometry import Polygon as ShapelyPolygon
```

Add a helper and update `build_districts`:

```python
def _polygon_to_parts(shapely_geom) -> List[List[Tuple[float, float]]]:
    if shapely_geom.is_empty:
        return []
    if shapely_geom.geom_type == "Polygon":
        return [list(shapely_geom.exterior.coords)[:-1]]
    if shapely_geom.geom_type == "MultiPolygon":
        return [list(part.exterior.coords)[:-1] for part in shapely_geom.geoms]
    return []  # a degenerate difference (e.g. a LineString sliver) contributes no land


def build_districts(
    anchors: List[Anchor], bounds: Tuple[float, float, float, float], water_polygon=None
) -> List[District]:
    if len(anchors) < 4:
        raise ValueError("At least 4 anchors are required to compute a stable Voronoi diagram")

    anchor_points = np.array([(a.x, a.y) for a in anchors])
    all_points = _mirrored_points(anchor_points, bounds)
    vor = Voronoi(all_points)

    districts: List[District] = []
    for i, anchor in enumerate(anchors):
        region_index = vor.point_region[i]
        region = vor.regions[region_index]
        if -1 in region or len(region) == 0:
            raise ValueError(f"Anchor {anchor.id} produced an unbounded Voronoi region")
        raw_polygon = [tuple(vor.vertices[v]) for v in region]
        polygon = clip_polygon_to_bounds(raw_polygon, bounds)

        if water_polygon is not None:
            land = ShapelyPolygon(polygon).difference(water_polygon)
            polygon_parts = _polygon_to_parts(land)
        else:
            polygon_parts = [polygon]

        districts.append(District(id=anchor.id, zone_type=anchor.zone_type, anchor=anchor, polygon_parts=polygon_parts))

    return districts
```

- [ ] **Step 4: Update `town_shaper/buildings.py`**

Add `import math` at the top of the file (it currently has none).

Add a helper and rewrite the start of `fill_district_buildings`:

```python
def _split_count_by_area(total_count: int, part_areas: List[float]) -> List[int]:
    total_area = sum(part_areas)
    if total_area <= 0:
        return [0 for _ in part_areas]

    raw = [total_count * (area / total_area) for area in part_areas]
    counts = [math.floor(r) for r in raw]
    remainder = total_count - sum(counts)

    remainders_sorted = sorted(range(len(part_areas)), key=lambda i: raw[i] - math.floor(raw[i]), reverse=True)
    i = 0
    while remainder > 0:
        counts[remainders_sorted[i % len(remainders_sorted)]] += 1
        remainder -= 1
        i += 1

    return counts


def fill_district_buildings(
    district: District, town_seed, next_building_id: int,
    target_population: int = 0, density_multiplier: float = 1.0,
) -> List[Building]:
    rng = rng_for(town_seed, "buildings", district.id)
    parts = district.polygon_parts
    part_areas = [polygon_area(part) for part in parts]
    total_area = sum(part_areas)

    if total_area <= 0:
        return []

    density = BUILDING_DENSITY_PER_AREA[district.zone_type] * density_multiplier
    total_target_count = max(1, round(total_area * density))
    spacing = MIN_BUILDING_SPACING[district.zone_type] / density_multiplier

    part_counts = _split_count_by_area(total_target_count, part_areas)
    points: List[Tuple[float, float]] = []
    for part, part_count in zip(parts, part_counts):
        points.extend(poisson_disc_fill(part, part_count, spacing, rng))
```

The rest of the function (from `type_weights = dict(...)` onward) is unchanged — it already just iterates whatever `points` contains.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_districts.py tests/test_buildings.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: PASS for every test — confirms the single-part (no-water) path is still byte-identical to before this task.

- [ ] **Step 7: Commit**

```bash
git add town_shaper/districts.py town_shaper/buildings.py tests/test_districts.py tests/test_buildings.py
git commit -m "feat: subtract water from district polygons and split building fill proportionally"
```

---

## Task 5: `generate_town` threads water generation end-to-end

**Files:**
- Modify: `town_shaper/models.py` (`Town` gains `water_features`)
- Modify: `town_shaper/generate.py`
- Test: `tests/test_generate.py` (append)

**Interfaces:**
- Consumes: `generate_water_features` (Task 1), `place_anchors(..., water_polygon, has_port)` (Task 2), `build_districts(..., water_polygon)` (Task 4)
- Produces: `generate_town(seed, target_population, area_per_resident_multiplier=1.0, density_multiplier=1.0, rich_proportion=DEFAULT_RICH_PROPORTION, num_rivers=0, has_coastline=False, has_port=False) -> Town`; `Town.water_features: List[WaterFeature]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_generate.py`:

```python
def test_generate_town_with_no_water_params_matches_previous_behavior():
    town_default = generate_town(("town", 1), target_population=3000)
    town_explicit = generate_town(
        ("town", 1), target_population=3000, num_rivers=0, has_coastline=False, has_port=False,
    )
    resident_key = lambda r: (r.id, r.household_id, r.ses, r.home_building_id, r.workplace_building_id, r.occupation)
    assert [resident_key(r) for r in town_default.residents] == [resident_key(r) for r in town_explicit.residents]
    assert town_default.water_features == []
    assert town_explicit.water_features == []


def test_generate_town_with_rivers_populates_water_features():
    town = generate_town(("town", 1), target_population=3000, num_rivers=2)
    assert len(town.water_features) == 2
    assert all(f.kind == "river" for f in town.water_features)


def test_generate_town_with_coastline_populates_water_features():
    town = generate_town(("town", 1), target_population=3000, has_coastline=True)
    assert len(town.water_features) == 1
    assert town.water_features[0].kind == "coastline"


def test_generate_town_with_port_adds_port_district_with_buildings():
    town = generate_town(("town", 1), target_population=3000, has_coastline=True, has_port=True)
    port_districts = [d for d in town.districts if d.zone_type.value == "port"]
    assert len(port_districts) == 1
    assert len(port_districts[0].buildings) > 0


def test_generate_town_is_fully_deterministic_with_water():
    town1 = generate_town(("town", 1), target_population=3000, num_rivers=1, has_coastline=True, has_port=True)
    town2 = generate_town(("town", 1), target_population=3000, num_rivers=1, has_coastline=True, has_port=True)

    resident_key = lambda r: (r.id, r.household_id, r.ses, r.home_building_id, r.workplace_building_id, r.occupation)
    assert [resident_key(r) for r in town1.residents] == [resident_key(r) for r in town2.residents]

    building_key = lambda b: (b.id, b.x, b.y, b.building_type)
    buildings1 = [building_key(b) for d in town1.districts for b in d.buildings]
    buildings2 = [building_key(b) for d in town2.districts for b in d.buildings]
    assert buildings1 == buildings2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_generate.py -v -k "water or port"`
Expected: FAIL with `TypeError: generate_town() got an unexpected keyword argument 'num_rivers'`

- [ ] **Step 3: Add `water_features` to `Town`**

In `town_shaper/models.py`, change the `Town` dataclass from:

```python
@dataclass
class Town:
    seed: tuple
    target_population: int
    bounds: Tuple[float, float, float, float]
    districts: List[District] = field(default_factory=list)
    residents: List[ResidentSlot] = field(default_factory=list)
```

to:

```python
@dataclass
class Town:
    seed: tuple
    target_population: int
    bounds: Tuple[float, float, float, float]
    districts: List[District] = field(default_factory=list)
    residents: List[ResidentSlot] = field(default_factory=list)
    water_features: List[WaterFeature] = field(default_factory=list)
```

- [ ] **Step 4: Update `town_shaper/generate.py`**

Change the imports (lines 1-9) from:

```python
import math
from typing import Tuple

from town_shaper.anchors import place_anchors
from town_shaper.assignment import DEFAULT_RICH_PROPORTION, assign_residents
from town_shaper.buildings import fill_district_buildings
from town_shaper.districts import build_districts
from town_shaper.households import generate_households
from town_shaper.models import Town
```

to:

```python
import math
from typing import Tuple

from shapely.ops import unary_union

from town_shaper.anchors import place_anchors
from town_shaper.assignment import DEFAULT_RICH_PROPORTION, assign_residents
from town_shaper.buildings import fill_district_buildings
from town_shaper.districts import build_districts
from town_shaper.households import generate_households
from town_shaper.models import Town
from town_shaper.water import generate_water_features
```

Replace `generate_town` (lines 24-49) with:

```python
def generate_town(
    seed, target_population: int,
    area_per_resident_multiplier: float = 1.0,
    density_multiplier: float = 1.0,
    rich_proportion: float = DEFAULT_RICH_PROPORTION,
    num_rivers: int = 0,
    has_coastline: bool = False,
    has_port: bool = False,
) -> Town:
    bounds = compute_town_bounds(target_population, area_per_resident_multiplier)

    water_features = generate_water_features(seed, bounds, num_rivers=num_rivers, has_coastline=has_coastline)
    water_polygon = unary_union([f.polygon for f in water_features]) if water_features else None

    anchors = place_anchors(seed, target_population, bounds, water_polygon=water_polygon, has_port=has_port)
    districts = build_districts(anchors, bounds, water_polygon=water_polygon)

    for district in districts:
        next_building_id = district.id * BUILDING_ID_STRIDE
        buildings = fill_district_buildings(
            district, seed, next_building_id,
            target_population=target_population, density_multiplier=density_multiplier,
        )
        district.buildings = buildings

    households = generate_households(seed, target_population)
    residents = assign_residents(seed, households, districts, rich_proportion=rich_proportion)

    town = Town(seed=seed, target_population=target_population, bounds=bounds)
    town.districts = districts
    town.residents = residents
    town.water_features = water_features
    return town
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_generate.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: PASS for every test

- [ ] **Step 7: Commit**

```bash
git add town_shaper/models.py town_shaper/generate.py tests/test_generate.py
git commit -m "feat: thread water/port generation through generate_town"
```

---

## Task 6: DB schema — `water_features` table and `generation_parameters` columns

**Files:**
- Modify: `town_db/schema.py`
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Produces: `water_features` table; `generation_parameters` gains `num_rivers INTEGER NOT NULL`, `has_coastline INTEGER NOT NULL`, `has_port INTEGER NOT NULL`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_db_schema.py`, add `"water_features"` to `EXPECTED_TABLES`:

```python
EXPECTED_TABLES = {
    "districts", "buildings", "households", "residents", "goods",
    "purchases", "tax_payments", "disease_events", "births", "deaths",
    "school_enrollments", "military_service", "generation_parameters",
    "water_features",
}
```

Replace `test_generation_parameters_accepts_a_row` (lines 64-77):

```python
def test_generation_parameters_accepts_a_row(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute(
        "INSERT INTO generation_parameters (seed, target_population, area_per_resident_multiplier, "
        "density_multiplier, rich_proportion) VALUES (?, ?, ?, ?, ?)",
        ("('town', 1)", 1500, 1.0, 1.0, 0.05),
    )
    conn.commit()
    row = conn.execute(
        "SELECT seed, target_population, area_per_resident_multiplier, density_multiplier, rich_proportion "
        "FROM generation_parameters"
    ).fetchone()
    assert row == ("('town', 1)", 1500, 1.0, 1.0, 0.05)
```

with:

```python
def test_generation_parameters_accepts_a_row(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute(
        "INSERT INTO generation_parameters (seed, target_population, area_per_resident_multiplier, "
        "density_multiplier, rich_proportion, num_rivers, has_coastline, has_port) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("('town', 1)", 1500, 1.0, 1.0, 0.05, 1, 1, 1),
    )
    conn.commit()
    row = conn.execute(
        "SELECT seed, target_population, area_per_resident_multiplier, density_multiplier, rich_proportion, "
        "num_rivers, has_coastline, has_port FROM generation_parameters"
    ).fetchone()
    assert row == ("('town', 1)", 1500, 1.0, 1.0, 0.05, 1, 1, 1)


def test_water_features_accepts_a_row(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute(
        "INSERT INTO water_features (id, kind, polygon) VALUES (?, ?, ?)",
        (1, "river", "[[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0]]"),
    )
    conn.commit()
    row = conn.execute("SELECT id, kind, polygon FROM water_features").fetchone()
    assert row == (1, "river", "[[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0]]")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: FAIL — `test_create_schema_creates_every_table` fails its subset assertion; `test_generation_parameters_accepts_a_row` fails with `sqlite3.OperationalError: table generation_parameters has no column named num_rivers`; `test_water_features_accepts_a_row` fails with `sqlite3.OperationalError: no such table: water_features`

- [ ] **Step 3: Update `town_db/schema.py`**

Change the `generation_parameters` table definition (lines 115-122) from:

```sql
CREATE TABLE generation_parameters (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    seed TEXT NOT NULL,
    target_population INTEGER NOT NULL,
    area_per_resident_multiplier REAL NOT NULL,
    density_multiplier REAL NOT NULL,
    rich_proportion REAL NOT NULL
);
```

to:

```sql
CREATE TABLE generation_parameters (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    seed TEXT NOT NULL,
    target_population INTEGER NOT NULL,
    area_per_resident_multiplier REAL NOT NULL,
    density_multiplier REAL NOT NULL,
    rich_proportion REAL NOT NULL,
    num_rivers INTEGER NOT NULL,
    has_coastline INTEGER NOT NULL,
    has_port INTEGER NOT NULL
);

CREATE TABLE water_features (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    polygon TEXT NOT NULL
);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_db/schema.py tests/test_db_schema.py
git commit -m "feat: add water_features table and generation_parameters water columns"
```

---

## Task 7: `generate_town_database` threads water parameters and persists `water_features`

**Files:**
- Modify: `town_db/generate.py`
- Test: `tests/test_db_generate.py` (append)

**Interfaces:**
- Consumes: `generate_town(..., num_rivers, has_coastline, has_port)` (Task 5), `water_features` table (Task 6)
- Produces: `generate_town_database(..., num_rivers: int = 0, has_coastline: bool = False, has_port: bool = False) -> None`, now also writing one `water_features` row per `WaterFeature`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db_generate.py`:

```python
def test_generate_town_database_default_water_params_match_previous_behavior(tmp_path):
    db_path_a = str(tmp_path / "a.db")
    db_path_b = str(tmp_path / "b.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_a)
    generate_town_database(
        ("town", 1), target_population=1500, db_path=db_path_b,
        num_rivers=0, has_coastline=False, has_port=False,
    )

    conn_a = sqlite3.connect(db_path_a)
    conn_b = sqlite3.connect(db_path_b)
    for table in ["residents", "buildings"]:
        rows_a = conn_a.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        rows_b = conn_b.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        assert rows_a == rows_b

    assert conn_a.execute("SELECT COUNT(*) FROM water_features").fetchone()[0] == 0


def test_generate_town_database_persists_water_features_and_port_buildings(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(
        ("town", 1), target_population=1500, db_path=db_path,
        num_rivers=1, has_coastline=True, has_port=True,
    )
    conn = sqlite3.connect(db_path)
    kinds = sorted(row[0] for row in conn.execute("SELECT kind FROM water_features").fetchall())
    assert kinds == ["coastline", "river"]

    port_building_count = conn.execute(
        "SELECT COUNT(*) FROM buildings WHERE zone_type = 'port'"
    ).fetchone()[0]
    assert port_building_count > 0


def test_generate_town_database_with_water_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(
        ("town", 1), target_population=1500, db_path=db_path,
        num_rivers=1, has_coastline=True, has_port=True,
    )
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_generate.py -v -k "water"`
Expected: FAIL with `TypeError: generate_town_database() got an unexpected keyword argument 'num_rivers'`

- [ ] **Step 3: Update `town_db/generate.py`**

Change the function signature (lines 27-45) from:

```python
def generate_town_database(
    seed,
    target_population: int,
    db_path: str,
    year_start: date = DEFAULT_YEAR_START,
    race_weights: Dict[str, float] = RACE_WEIGHTS,
    intermarriage_rate: float = DEFAULT_INTERMARRIAGE_RATE,
    birth_rate: float = DEFAULT_BIRTH_RATE,
    death_rate_by_age: Dict[str, float] = DEFAULT_DEATH_RATE_BY_AGE,
    area_per_resident_multiplier: float = 1.0,
    density_multiplier: float = 1.0,
    rich_proportion: float = DEFAULT_RICH_PROPORTION,
) -> None:
    town = generate_town(
        seed, target_population,
        area_per_resident_multiplier=area_per_resident_multiplier,
        density_multiplier=density_multiplier,
        rich_proportion=rich_proportion,
    )

    conn = connect(db_path)
    create_schema(conn)

    zone_type_by_building_id: Dict[int, str] = {}
    for district in town.districts:
```

to:

```python
def generate_town_database(
    seed,
    target_population: int,
    db_path: str,
    year_start: date = DEFAULT_YEAR_START,
    race_weights: Dict[str, float] = RACE_WEIGHTS,
    intermarriage_rate: float = DEFAULT_INTERMARRIAGE_RATE,
    birth_rate: float = DEFAULT_BIRTH_RATE,
    death_rate_by_age: Dict[str, float] = DEFAULT_DEATH_RATE_BY_AGE,
    area_per_resident_multiplier: float = 1.0,
    density_multiplier: float = 1.0,
    rich_proportion: float = DEFAULT_RICH_PROPORTION,
    num_rivers: int = 0,
    has_coastline: bool = False,
    has_port: bool = False,
) -> None:
    town = generate_town(
        seed, target_population,
        area_per_resident_multiplier=area_per_resident_multiplier,
        density_multiplier=density_multiplier,
        rich_proportion=rich_proportion,
        num_rivers=num_rivers,
        has_coastline=has_coastline,
        has_port=has_port,
    )

    conn = connect(db_path)
    create_schema(conn)

    for feature in town.water_features:
        conn.execute(
            "INSERT INTO water_features (id, kind, polygon) VALUES (?, ?, ?)",
            (feature.id, feature.kind, json.dumps(list(feature.polygon.exterior.coords)[:-1])),
        )

    zone_type_by_building_id: Dict[int, str] = {}
    for district in town.districts:
```

(Only the signature, the `generate_town(...)` call, and the new `water_features` insert loop are added — every line after the `zone_type_by_building_id` declaration is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_generate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_db/generate.py tests/test_db_generate.py
git commit -m "feat: thread water/port parameters through generate_town_database"
```

---

## Task 8: `TownParameters` gains water fields; `generate_town_from_parameters` wiring

**Files:**
- Modify: `town_narrative/parameters.py`
- Modify: `town_narrative/generate.py`
- Test: `tests/test_narrative_parameters.py` (append)
- Test: `tests/test_narrative_generate.py` (append)

**Interfaces:**
- Produces: `TownParameters` gains `num_rivers: int = 0`, `has_coastline: bool = False`, `has_port: bool = False` — `__post_init__` raises `ValueError` for `num_rivers < 0` or `has_port=True` with no water. `generate_town_from_parameters` passes these through and records them in `generation_parameters`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_narrative_parameters.py`:

```python
def test_water_defaults_are_no_water():
    params = TownParameters(seed="town-1", target_population=1000)
    assert params.num_rivers == 0
    assert params.has_coastline is False
    assert params.has_port is False


def test_negative_num_rivers_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, num_rivers=-1)


def test_zero_num_rivers_is_valid():
    TownParameters(seed="town-1", target_population=1000, num_rivers=0)


def test_has_port_without_water_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, has_port=True)
    with pytest.raises(ValueError):
        TownParameters(
            seed="town-1", target_population=1000, has_port=True, num_rivers=0, has_coastline=False,
        )


def test_has_port_with_river_is_valid():
    TownParameters(seed="town-1", target_population=1000, has_port=True, num_rivers=1)


def test_has_port_with_coastline_is_valid():
    TownParameters(seed="town-1", target_population=1000, has_port=True, has_coastline=True)
```

Append to `tests/test_narrative_generate.py`:

```python
def test_generate_town_from_parameters_records_water_params(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(
        seed=("town", 1), target_population=1500, num_rivers=2, has_coastline=True, has_port=True,
    )
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT num_rivers, has_coastline, has_port FROM generation_parameters").fetchone()
    assert row == (2, 1, 1)
    assert conn.execute("SELECT COUNT(*) FROM water_features").fetchone()[0] == 3


def test_generate_town_from_parameters_with_water_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(
        seed=("town", 1), target_population=1500, num_rivers=1, has_coastline=True, has_port=True,
    )
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_narrative_parameters.py tests/test_narrative_generate.py -v -k "water or port or river"`
Expected: FAIL with `TypeError: TownParameters.__init__() got an unexpected keyword argument 'num_rivers'`

- [ ] **Step 3: Update `town_narrative/parameters.py`**

Replace the whole file:

```python
from dataclasses import dataclass
from typing import Any

from town_shaper.assignment import DEFAULT_RICH_PROPORTION


@dataclass(frozen=True)
class TownParameters:
    seed: Any
    target_population: int
    area_per_resident_multiplier: float = 1.0
    density_multiplier: float = 1.0
    rich_proportion: float = DEFAULT_RICH_PROPORTION
    num_rivers: int = 0
    has_coastline: bool = False
    has_port: bool = False

    def __post_init__(self) -> None:
        if self.target_population <= 0:
            raise ValueError("target_population must be positive")
        if self.area_per_resident_multiplier <= 0:
            raise ValueError("area_per_resident_multiplier must be positive")
        if self.density_multiplier <= 0:
            raise ValueError("density_multiplier must be positive")
        if not (0.0 <= self.rich_proportion <= 1.0):
            raise ValueError("rich_proportion must be between 0.0 and 1.0")
        if self.num_rivers < 0:
            raise ValueError("num_rivers must be non-negative")
        if self.has_port and not (self.num_rivers > 0 or self.has_coastline):
            raise ValueError("has_port requires num_rivers > 0 or has_coastline to be True")
```

- [ ] **Step 4: Update `town_narrative/generate.py`**

Replace the whole file:

```python
from town_db.generate import generate_town_database
from town_db.schema import connect

from town_narrative.parameters import TownParameters


def generate_town_from_parameters(params: TownParameters, db_path: str) -> None:
    generate_town_database(
        params.seed,
        params.target_population,
        db_path,
        area_per_resident_multiplier=params.area_per_resident_multiplier,
        density_multiplier=params.density_multiplier,
        rich_proportion=params.rich_proportion,
        num_rivers=params.num_rivers,
        has_coastline=params.has_coastline,
        has_port=params.has_port,
    )

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO generation_parameters (id, seed, target_population, area_per_resident_multiplier, "
        "density_multiplier, rich_proportion, num_rivers, has_coastline, has_port) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, str(params.seed), params.target_population, params.area_per_resident_multiplier,
         params.density_multiplier, params.rich_proportion, params.num_rivers,
         int(params.has_coastline), int(params.has_port)),
    )
    conn.commit()
    conn.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_narrative_parameters.py tests/test_narrative_generate.py -v`
Expected: PASS

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS for every test

- [ ] **Step 7: Commit**

```bash
git add town_narrative/parameters.py town_narrative/generate.py tests/test_narrative_parameters.py tests/test_narrative_generate.py
git commit -m "feat: add num_rivers/has_coastline/has_port to TownParameters"
```

---

## Task 9: Narrative-mapping doc and skill update

**Files:**
- Modify: `docs/narrative-town-parameters.md`
- Modify: `.claude/skills/generate-town-from-narrative/SKILL.md`

**Interfaces:**
- Consumes: `TownParameters` (Task 8)
- Produces: updated agent-neutral reference documentation and Claude Code skill wrapper.

- [ ] **Step 1: Update the reference doc**

In `docs/narrative-town-parameters.md`, after the `rich_proportion` bullet in the `## Fields` section (after the line ending `"Richness" of the town overall.`), insert:

```markdown
- **`num_rivers`** (default `0`) — how many rivers run through the town.
  Each is generated as an independent, gently curved strip of water
  crossing the town, carving real unbuildable space out of whatever
  district it passes through.
- **`has_coastline`** (default `false`) — whether one side of the town
  borders open water (a sea/lake edge), as opposed to an interior river.
- **`has_port`** (default `false`) — whether the town has a dedicated
  port district (docks, warehouses, a harbormaster's office). Requires
  `num_rivers > 0` or `has_coastline` — raises otherwise, since a port
  needs water to sit on.
```

Add rows to the `## Narrative language → value` table (after the `rich_proportion` rows, before the closing paragraph):

```markdown
| "a river runs through it", "on the river", "riverside" | `num_rivers` | 1 |
| "where two rivers meet", "at the confluence" | `num_rivers` | 2 |
| (no river cue) | `num_rivers` | 0 (default) |
| "coastal", "seaside", "on the coast/sea" | `has_coastline` | `true` |
| (no coastal cue) | `has_coastline` | `false` (default) |
| "port town", "trading port", "harbor" | `has_port` | `true` — also set `has_coastline=true` as the implied water source, unless the narrative specifies a river port instead |
```

- [ ] **Step 2: Update the skill file**

In `.claude/skills/generate-town-from-narrative/SKILL.md`, change step 2 of the procedure from:

```markdown
2. **Map narrative language onto `TownParameters` fields** using
   `docs/narrative-town-parameters.md` as the reference table. Fields
   available today: `seed`, `target_population`,
   `area_per_resident_multiplier`, `density_multiplier`,
   `rich_proportion`.
```

to:

```markdown
2. **Map narrative language onto `TownParameters` fields** using
   `docs/narrative-town-parameters.md` as the reference table. Fields
   available today: `seed`, `target_population`,
   `area_per_resident_multiplier`, `density_multiplier`,
   `rich_proportion`, `num_rivers`, `has_coastline`, `has_port`.
```

Change the example `TownParameters(...)` construction in step 5 from:

```python
   params = TownParameters(
       seed=<a stable seed derived from the campaign/town name>,
       target_population=<int>,
       area_per_resident_multiplier=<float>,
       density_multiplier=<float>,
       rich_proportion=<float>,
   )
```

to:

```python
   params = TownParameters(
       seed=<a stable seed derived from the campaign/town name>,
       target_population=<int>,
       area_per_resident_multiplier=<float>,
       density_multiplier=<float>,
       rich_proportion=<float>,
       num_rivers=<int>,
       has_coastline=<bool>,
       has_port=<bool>,
   )
```

- [ ] **Step 3: Verify both files are internally consistent**

Run: `python -c "import pathlib; text = pathlib.Path('docs/narrative-town-parameters.md').read_text(); assert 'num_rivers' in text and 'has_coastline' in text and 'has_port' in text; skill = pathlib.Path('.claude/skills/generate-town-from-narrative/SKILL.md').read_text(); assert 'num_rivers' in skill and 'has_port' in skill; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add docs/narrative-town-parameters.md .claude/skills/generate-town-from-narrative/SKILL.md
git commit -m "docs: document water/port narrative-mapping fields"
```
