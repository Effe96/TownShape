# Town Shaper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, seeded generator that produces a town's spatial layout (organic Voronoi districts, buildings) and places residents in homes/jobs, as pure data (no rendering).

**Architecture:** A pipeline of pure functions — anchors → Voronoi districts → building fill (with job vacancies) → households → resident assignment — each stage seeded independently via an explicit `random.Random` instance derived from the town seed, never global `random` state. A top-level `generate_town()` orchestrates the pipeline into a `Town` object.

**Tech Stack:** Python 3.12, `numpy`/`scipy` (`scipy.spatial.Voronoi`) for geometry, `pytest` for tests. No web framework, no rendering, no database — this plan implements Town Shaper (sub-project A) only, per `docs/superpowers/specs/2026-08-13-town-shaper-spatial-generation-design.md`.

## Global Constraints

- Every generation function takes an explicit `random.Random` (or a seed to build one) and must never call module-level `random.seed()`/`random.random()`.
- Same seed must reproduce byte-identical output, both for a whole town and for an individual district/building generated in isolation via its own derived seed.
- SES has exactly two tiers, `RICH` and `POOR`, matching the two residential zone types (`RICH_RESIDENTIAL`, `POOR_RESIDENTIAL`) — no tier without a corresponding zone.
- Target scale: low-thousands population. A full `generate_town()` call at `target_population=3000` must complete in under 10 seconds on a dev machine.
- No third-party geometry dependency beyond `numpy`/`scipy` (no `shapely`) — polygon clipping and point-in-polygon tests are implemented directly.

---

## Task 1: Package scaffolding and core data model

**Files:**
- Create: `town_shaper/__init__.py`
- Create: `town_shaper/models.py`
- Create: `requirements.txt`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `ZoneType` (Enum: `CIVIC`, `MERCHANT`, `RICH_RESIDENTIAL`, `POOR_RESIDENTIAL`, `FARMLAND_EDGE`), `SES` (Enum: `RICH`, `POOR`), `Anchor(id: int, zone_type: ZoneType, x: float, y: float)`, `JobVacancy(building_id: int, occupation: str, filled_by: Optional[int] = None)`, `Building(id: int, district_id: int, district_zone_type: ZoneType, x: float, y: float, building_type: str, capacity: int, vacancies: List[JobVacancy], resident_ids: List[int])`, `District(id: int, zone_type: ZoneType, anchor: Anchor, polygon: List[Tuple[float, float]], buildings: List[Building])`, `Household(id: int, has_spouse: bool, child_count: int)`, `ResidentSlot(id: int, household_id: int, ses: SES, age_bracket: str, home_building_id: Optional[int], workplace_building_id: Optional[int], occupation: Optional[str])`, `Town(seed: tuple, target_population: int, bounds: Tuple[float, float, float, float], districts: List[District], residents: List[ResidentSlot])`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from town_shaper.models import (
    Anchor, Building, District, Household, JobVacancy,
    ResidentSlot, SES, Town, ZoneType,
)


def test_zone_type_has_five_members():
    assert {z.value for z in ZoneType} == {
        "civic", "merchant", "rich_residential", "poor_residential", "farmland_edge",
    }


def test_ses_has_exactly_two_tiers_matching_residential_zones():
    assert {s.value for s in SES} == {"rich", "poor"}


def test_building_defaults_to_empty_vacancies_and_residents():
    building = Building(
        id=1, district_id=1, district_zone_type=ZoneType.POOR_RESIDENTIAL,
        x=0.0, y=0.0, building_type="residence", capacity=6,
    )
    assert building.vacancies == []
    assert building.resident_ids == []


def test_district_defaults_to_empty_buildings():
    anchor = Anchor(id=1, zone_type=ZoneType.CIVIC, x=0.0, y=0.0)
    district = District(id=1, zone_type=ZoneType.CIVIC, anchor=anchor, polygon=[(0.0, 0.0)])
    assert district.buildings == []


def test_town_defaults_to_empty_districts_and_residents():
    town = Town(seed=(1,), target_population=100, bounds=(-10.0, -10.0, 10.0, 10.0))
    assert town.districts == []
    assert town.residents == []


def test_resident_slot_starts_unassigned():
    resident = ResidentSlot(id=1, household_id=1, ses=SES.POOR, age_bracket="adult")
    assert resident.home_building_id is None
    assert resident.workplace_building_id is None
    assert resident.occupation is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_shaper'`

- [ ] **Step 3: Write the data model**

```python
# town_shaper/__init__.py
```

```python
# town_shaper/models.py
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


class ZoneType(Enum):
    CIVIC = "civic"
    MERCHANT = "merchant"
    RICH_RESIDENTIAL = "rich_residential"
    POOR_RESIDENTIAL = "poor_residential"
    FARMLAND_EDGE = "farmland_edge"


class SES(Enum):
    RICH = "rich"
    POOR = "poor"


@dataclass
class Anchor:
    id: int
    zone_type: ZoneType
    x: float
    y: float


@dataclass
class JobVacancy:
    building_id: int
    occupation: str
    filled_by: Optional[int] = None


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


@dataclass
class District:
    id: int
    zone_type: ZoneType
    anchor: Anchor
    polygon: List[Tuple[float, float]]
    buildings: List[Building] = field(default_factory=list)


@dataclass
class Household:
    id: int
    has_spouse: bool
    child_count: int


@dataclass
class ResidentSlot:
    id: int
    household_id: int
    ses: SES
    age_bracket: str
    home_building_id: Optional[int] = None
    workplace_building_id: Optional[int] = None
    occupation: Optional[str] = None


@dataclass
class Town:
    seed: tuple
    target_population: int
    bounds: Tuple[float, float, float, float]
    districts: List[District] = field(default_factory=list)
    residents: List[ResidentSlot] = field(default_factory=list)
```

```
# requirements.txt
numpy>=1.26
scipy>=1.11
pytest>=8.0
```

- [ ] **Step 4: Install dependencies and run tests to verify they pass**

Run: `pip install -r requirements.txt && python -m pytest tests/test_models.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/__init__.py town_shaper/models.py requirements.txt tests/test_models.py
git commit -m "feat: add Town Shaper core data model"
```

---

## Task 2: Deterministic seeding helper

**Files:**
- Create: `town_shaper/seeding.py`
- Test: `tests/test_seeding.py`

**Interfaces:**
- Consumes: nothing (stdlib only)
- Produces: `derive_seed(base_seed, *parts) -> int`, `rng_for(base_seed, *parts) -> random.Random`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seeding.py
from town_shaper.seeding import derive_seed, rng_for


def test_derive_seed_is_deterministic():
    assert derive_seed(("town", 1), "anchors") == derive_seed(("town", 1), "anchors")


def test_derive_seed_differs_by_path():
    assert derive_seed(("town", 1), "anchors") != derive_seed(("town", 1), "buildings")


def test_rng_for_produces_identical_sequences_for_same_path():
    rng1 = rng_for(("town", 1), "anchors", 3)
    rng2 = rng_for(("town", 1), "anchors", 3)
    assert [rng1.random() for _ in range(5)] == [rng2.random() for _ in range(5)]


def test_rng_for_produces_different_sequences_for_different_paths():
    rng1 = rng_for(("town", 1), "anchors", 3)
    rng2 = rng_for(("town", 1), "anchors", 4)
    assert [rng1.random() for _ in range(5)] != [rng2.random() for _ in range(5)]


def test_rng_for_does_not_touch_global_random_state():
    import random
    random.seed(12345)
    expected = random.random()
    random.seed(12345)
    rng_for(("town", 1), "anchors")
    assert random.random() == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_seeding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_shaper.seeding'`

- [ ] **Step 3: Write the seeding helper**

```python
# town_shaper/seeding.py
import hashlib
import random


def derive_seed(base_seed, *parts) -> int:
    key = repr((base_seed,) + parts).encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    return int(digest[:16], 16)


def rng_for(base_seed, *parts) -> random.Random:
    return random.Random(derive_seed(base_seed, *parts))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_seeding.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/seeding.py tests/test_seeding.py
git commit -m "feat: add deterministic per-path seeding helper"
```

---

## Task 3: Geometry helpers

**Files:**
- Create: `town_shaper/geometry.py`
- Test: `tests/test_geometry.py`

**Interfaces:**
- Consumes: nothing (stdlib only)
- Produces: `polygon_area(polygon: List[Tuple[float, float]]) -> float`, `point_in_polygon(point: Tuple[float, float], polygon: List[Tuple[float, float]]) -> bool`, `clip_polygon_to_bounds(polygon: List[Tuple[float, float]], bounds: Tuple[float, float, float, float]) -> List[Tuple[float, float]]`, `distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_geometry.py
import math

from town_shaper.geometry import clip_polygon_to_bounds, distance, point_in_polygon, polygon_area


def test_polygon_area_of_unit_square():
    square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert polygon_area(square) == 1.0


def test_point_in_polygon_inside_and_outside():
    square = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    assert point_in_polygon((1.0, 1.0), square) is True
    assert point_in_polygon((3.0, 1.0), square) is False


def test_clip_polygon_to_bounds_clips_overhanging_square():
    square = [(-1.0, -1.0), (3.0, -1.0), (3.0, 3.0), (-1.0, 3.0)]
    bounds = (0.0, 0.0, 2.0, 2.0)
    clipped = clip_polygon_to_bounds(square, bounds)
    assert math.isclose(polygon_area(clipped), 4.0, rel_tol=1e-9)


def test_clip_polygon_fully_outside_bounds_returns_empty():
    triangle = [(10.0, 10.0), (12.0, 10.0), (11.0, 12.0)]
    bounds = (0.0, 0.0, 2.0, 2.0)
    assert clip_polygon_to_bounds(triangle, bounds) == []


def test_distance_of_3_4_5_triangle():
    assert distance((0.0, 0.0), (3.0, 4.0)) == 5.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_geometry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_shaper.geometry'`

- [ ] **Step 3: Write the geometry helpers**

```python
# town_shaper/geometry.py
import math
from typing import List, Tuple

Point = Tuple[float, float]
Polygon = List[Point]


def polygon_area(polygon: Polygon) -> float:
    if len(polygon) < 3:
        return 0.0
    area = 0.0
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def point_in_polygon(point: Point, polygon: Polygon) -> bool:
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_at_y = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < x_at_y:
                inside = not inside
    return inside


def distance(p1: Point, p2: Point) -> float:
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def _is_inside_edge(point: Point, edge_start: Point, edge_end: Point) -> bool:
    return (edge_end[0] - edge_start[0]) * (point[1] - edge_start[1]) - \
           (edge_end[1] - edge_start[1]) * (point[0] - edge_start[0]) >= 0


def _line_intersection(p1: Point, p2: Point, edge_start: Point, edge_end: Point) -> Point:
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = edge_start
    x4, y4 = edge_end
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if denom == 0:
        return p2
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


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

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_geometry.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/geometry.py tests/test_geometry.py
git commit -m "feat: add polygon area, point-in-polygon, and clipping helpers"
```

---

## Task 4: Anchor placement

**Files:**
- Create: `town_shaper/anchors.py`
- Test: `tests/test_anchors.py`

**Interfaces:**
- Consumes: `rng_for` from `town_shaper.seeding`; `Anchor`, `ZoneType` from `town_shaper.models`
- Produces: `MIN_ANCHORS = 8`, `ZONE_PROPORTIONS: Dict[ZoneType, float]`, `compute_anchor_counts(target_population: int) -> Dict[ZoneType, int]`, `place_anchors(town_seed, target_population: int, bounds: Tuple[float, float, float, float]) -> List[Anchor]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_anchors.py
import pytest

from town_shaper.anchors import MIN_ANCHORS, ZONE_PROPORTIONS, compute_anchor_counts, place_anchors
from town_shaper.models import ZoneType


def test_compute_anchor_counts_sums_to_total():
    counts = compute_anchor_counts(target_population=3000)
    assert sum(counts.values()) >= MIN_ANCHORS
    assert set(counts.keys()) == set(ZoneType)


def test_compute_anchor_counts_respects_minimum_for_tiny_towns():
    counts = compute_anchor_counts(target_population=1)
    assert sum(counts.values()) == MIN_ANCHORS


def test_compute_anchor_counts_rejects_nonpositive_population():
    with pytest.raises(ValueError):
        compute_anchor_counts(target_population=0)


def test_compute_anchor_counts_has_at_least_one_of_each_zone_type():
    counts = compute_anchor_counts(target_population=3000)
    for zone_type in ZoneType:
        assert counts[zone_type] >= 1


def test_place_anchors_is_deterministic():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors1 = place_anchors(("town", 1), 3000, bounds)
    anchors2 = place_anchors(("town", 1), 3000, bounds)
    assert [(a.id, a.zone_type, a.x, a.y) for a in anchors1] == \
           [(a.id, a.zone_type, a.x, a.y) for a in anchors2]


def test_place_anchors_stays_within_bounds():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    for anchor in anchors:
        assert bounds[0] <= anchor.x <= bounds[2]
        assert bounds[1] <= anchor.y <= bounds[3]


def test_place_anchors_produces_counts_matching_compute_anchor_counts():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    counts = compute_anchor_counts(3000)
    actual_counts = {}
    for anchor in anchors:
        actual_counts[anchor.zone_type] = actual_counts.get(anchor.zone_type, 0) + 1
    assert actual_counts == counts
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_anchors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_shaper.anchors'`

- [ ] **Step 3: Write the anchor placement module**

```python
# town_shaper/anchors.py
import math
from typing import Dict, List, Tuple

from town_shaper.models import Anchor, ZoneType
from town_shaper.seeding import rng_for

MIN_ANCHORS = 8
ANCHOR_POPULATION_DIVISOR = 150

# Must sum to 1.0 — enforced by test_compute_anchor_counts_sums_to_total via
# the largest-remainder rounding below always consuming the full total.
ZONE_PROPORTIONS: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 0.05,
    ZoneType.MERCHANT: 0.15,
    ZoneType.RICH_RESIDENTIAL: 0.15,
    ZoneType.POOR_RESIDENTIAL: 0.45,
    ZoneType.FARMLAND_EDGE: 0.20,
}

# (min_radius_fraction, max_radius_fraction) of the bounding box half-extent,
# per zone type — determines how anchors are biased from town center to edge.
ZONE_RADIUS_BANDS: Dict[ZoneType, Tuple[float, float]] = {
    ZoneType.CIVIC: (0.0, 0.15),
    ZoneType.MERCHANT: (0.1, 0.4),
    ZoneType.RICH_RESIDENTIAL: (0.15, 0.45),
    ZoneType.POOR_RESIDENTIAL: (0.35, 0.75),
    ZoneType.FARMLAND_EDGE: (0.65, 0.95),
}

# Stable tie-break order for largest-remainder rounding.
_ZONE_ORDER = [
    ZoneType.CIVIC,
    ZoneType.MERCHANT,
    ZoneType.RICH_RESIDENTIAL,
    ZoneType.POOR_RESIDENTIAL,
    ZoneType.FARMLAND_EDGE,
]


def compute_anchor_counts(target_population: int) -> Dict[ZoneType, int]:
    if target_population <= 0:
        raise ValueError("target_population must be positive")

    total = max(MIN_ANCHORS, round(target_population / ANCHOR_POPULATION_DIVISOR))
    # Guarantee at least one anchor per zone type without exceeding total.
    total = max(total, len(ZoneType))

    raw = {zt: ZONE_PROPORTIONS[zt] * total for zt in _ZONE_ORDER}
    counts = {zt: max(1, math.floor(raw[zt])) for zt in _ZONE_ORDER}

    remainder = total - sum(counts.values())
    remainders_sorted = sorted(_ZONE_ORDER, key=lambda zt: raw[zt] - math.floor(raw[zt]), reverse=True)
    i = 0
    while remainder > 0:
        counts[remainders_sorted[i % len(remainders_sorted)]] += 1
        remainder -= 1
        i += 1
    while remainder < 0:
        zt = remainders_sorted[i % len(remainders_sorted)]
        if counts[zt] > 1:
            counts[zt] -= 1
            remainder += 1
        i += 1

    return counts


def place_anchors(town_seed, target_population: int, bounds: Tuple[float, float, float, float]) -> List[Anchor]:
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
            angle = rng.uniform(0.0, 2.0 * math.pi)
            radius_fraction = rng.uniform(band_min, band_max)
            x = center_x + math.cos(angle) * radius_fraction * half_width
            y = center_y + math.sin(angle) * radius_fraction * half_height
            x = min(max(x, min_x), max_x)
            y = min(max(y, min_y), max_y)
            anchors.append(Anchor(id=anchor_id, zone_type=zone_type, x=x, y=y))
            anchor_id += 1

    return anchors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_anchors.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/anchors.py tests/test_anchors.py
git commit -m "feat: add zone-quota'd, structurally-biased anchor placement"
```

---

## Task 5: District computation (bounded Voronoi diagram)

**Files:**
- Create: `town_shaper/districts.py`
- Test: `tests/test_districts.py`

**Interfaces:**
- Consumes: `polygon_area`, `point_in_polygon`, `clip_polygon_to_bounds` from `town_shaper.geometry`; `Anchor`, `District` from `town_shaper.models`
- Produces: `build_districts(anchors: List[Anchor], bounds: Tuple[float, float, float, float]) -> List[District]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_districts.py
import math

import pytest

from town_shaper.anchors import place_anchors
from town_shaper.districts import build_districts
from town_shaper.geometry import point_in_polygon, polygon_area
from town_shaper.models import Anchor, ZoneType


def test_build_districts_requires_at_least_four_anchors():
    anchors = [Anchor(id=i, zone_type=ZoneType.CIVIC, x=float(i), y=0.0) for i in range(3)]
    with pytest.raises(ValueError):
        build_districts(anchors, bounds=(-10.0, -10.0, 10.0, 10.0))


def test_build_districts_partitions_bounding_box_area():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    districts = build_districts(anchors, bounds)

    box_area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
    total_district_area = sum(polygon_area(d.polygon) for d in districts)
    assert math.isclose(total_district_area, box_area, rel_tol=1e-6)


def test_build_districts_each_polygon_contains_its_own_anchor():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    districts = build_districts(anchors, bounds)

    for district in districts:
        assert point_in_polygon((district.anchor.x, district.anchor.y), district.polygon)


def test_build_districts_preserves_zone_type_from_anchor():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    districts = build_districts(anchors, bounds)

    by_id = {d.id: d for d in districts}
    for anchor in anchors:
        assert by_id[anchor.id].zone_type == anchor.zone_type
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_districts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_shaper.districts'`

- [ ] **Step 3: Write the district computation module**

```python
# town_shaper/districts.py
from typing import List, Tuple

import numpy as np
from scipy.spatial import Voronoi

from town_shaper.geometry import clip_polygon_to_bounds
from town_shaper.models import Anchor, District


def _mirrored_points(points: np.ndarray, bounds: Tuple[float, float, float, float]) -> np.ndarray:
    min_x, min_y, max_x, max_y = bounds
    reflections = []
    for x, y in points:
        reflections.append((2 * min_x - x, y))
        reflections.append((2 * max_x - x, y))
        reflections.append((x, 2 * min_y - y))
        reflections.append((x, 2 * max_y - y))
    return np.vstack([points, np.array(reflections)])


def build_districts(anchors: List[Anchor], bounds: Tuple[float, float, float, float]) -> List[District]:
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
        districts.append(District(id=anchor.id, zone_type=anchor.zone_type, anchor=anchor, polygon=polygon))

    return districts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_districts.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/districts.py tests/test_districts.py
git commit -m "feat: compute bounded Voronoi districts from anchors"
```

---

## Task 6: Building placement and job vacancies

**Files:**
- Create: `town_shaper/buildings.py`
- Test: `tests/test_buildings.py`

**Interfaces:**
- Consumes: `point_in_polygon`, `polygon_area`, `distance` from `town_shaper.geometry`; `rng_for` from `town_shaper.seeding`; `Building`, `District`, `JobVacancy`, `ZoneType` from `town_shaper.models`
- Produces: `BUILDING_DENSITY_PER_AREA`, `MIN_BUILDING_SPACING`, `BUILDING_TYPES_BY_ZONE`, `JOB_VACANCIES_BY_BUILDING_TYPE`, `BUILDING_HOME_CAPACITY`, `poisson_disc_fill(polygon, target_count, min_spacing, rng, max_attempts_per_point=30) -> List[Tuple[float, float]]`, `fill_district_buildings(district: District, town_seed, next_building_id: int) -> List[Building]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_buildings.py
from town_shaper.buildings import fill_district_buildings, poisson_disc_fill
from town_shaper.geometry import distance, point_in_polygon
from town_shaper.models import Anchor, District, ZoneType
from town_shaper.seeding import rng_for


def _square_district(zone_type, side=40.0, district_id=1):
    anchor = Anchor(id=district_id, zone_type=zone_type, x=side / 2, y=side / 2)
    polygon = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
    return District(id=district_id, zone_type=zone_type, anchor=anchor, polygon=polygon)


def test_poisson_disc_fill_respects_min_spacing_and_polygon():
    polygon = [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0)]
    rng = rng_for(("town", 1), "test-poisson")
    points = poisson_disc_fill(polygon, target_count=20, min_spacing=5.0, rng=rng)

    assert len(points) > 0
    for p in points:
        assert point_in_polygon(p, polygon)
    for i, p in enumerate(points):
        for q in points[i + 1:]:
            assert distance(p, q) >= 5.0


def test_poisson_disc_fill_returns_fewer_points_when_polygon_is_too_small():
    tiny_polygon = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    rng = rng_for(("town", 1), "test-poisson-tiny")
    points = poisson_disc_fill(tiny_polygon, target_count=100, min_spacing=5.0, rng=rng)
    assert len(points) < 100


def test_fill_district_buildings_places_buildings_inside_district():
    district = _square_district(ZoneType.POOR_RESIDENTIAL)
    buildings = fill_district_buildings(district, ("town", 1), next_building_id=0)

    assert len(buildings) > 0
    for building in buildings:
        assert point_in_polygon((building.x, building.y), district.polygon)
        assert building.district_id == district.id
        assert building.district_zone_type == ZoneType.POOR_RESIDENTIAL


def test_fill_district_buildings_creates_vacancies_matching_building_type():
    from town_shaper.buildings import JOB_VACANCIES_BY_BUILDING_TYPE

    district = _square_district(ZoneType.MERCHANT)
    buildings = fill_district_buildings(district, ("town", 1), next_building_id=0)

    for building in buildings:
        expected = JOB_VACANCIES_BY_BUILDING_TYPE[building.building_type]
        expected_total = sum(count for _, count in expected)
        assert len(building.vacancies) == expected_total
        for vacancy in building.vacancies:
            assert vacancy.building_id == building.id
            assert vacancy.filled_by is None


def test_fill_district_buildings_is_deterministic():
    district = _square_district(ZoneType.RICH_RESIDENTIAL)
    first = fill_district_buildings(district, ("town", 1), next_building_id=0)
    second = fill_district_buildings(district, ("town", 1), next_building_id=0)
    assert [(b.id, b.x, b.y, b.building_type) for b in first] == \
           [(b.id, b.x, b.y, b.building_type) for b in second]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_buildings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_shaper.buildings'`

- [ ] **Step 3: Write the building placement module**

```python
# town_shaper/buildings.py
from typing import Dict, List, Tuple

from town_shaper.geometry import distance, point_in_polygon, polygon_area
from town_shaper.models import Building, District, JobVacancy, ZoneType
from town_shaper.seeding import rng_for

BUILDING_DENSITY_PER_AREA: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 1 / 400,
    ZoneType.MERCHANT: 1 / 150,
    ZoneType.RICH_RESIDENTIAL: 1 / 300,
    ZoneType.POOR_RESIDENTIAL: 1 / 100,
    ZoneType.FARMLAND_EDGE: 1 / 600,
}

MIN_BUILDING_SPACING: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 15.0,
    ZoneType.MERCHANT: 8.0,
    ZoneType.RICH_RESIDENTIAL: 12.0,
    ZoneType.POOR_RESIDENTIAL: 5.0,
    ZoneType.FARMLAND_EDGE: 20.0,
}

BUILDING_TYPES_BY_ZONE: Dict[ZoneType, Dict[str, float]] = {
    ZoneType.CIVIC: {"temple": 0.3, "town_hall": 0.1, "school": 0.2, "guard_post": 0.4},
    ZoneType.MERCHANT: {"shop": 0.5, "tavern": 0.2, "market_stall": 0.3},
    ZoneType.RICH_RESIDENTIAL: {"manor": 1.0},
    ZoneType.POOR_RESIDENTIAL: {"residence": 1.0},
    ZoneType.FARMLAND_EDGE: {"farmstead": 1.0},
}

JOB_VACANCIES_BY_BUILDING_TYPE: Dict[str, List[Tuple[str, int]]] = {
    "temple": [("priest", 1), ("acolyte", 2)],
    "town_hall": [("clerk", 3)],
    "school": [("teacher", 2)],
    "guard_post": [("guard", 4)],
    "shop": [("shopkeep", 1), ("shop_staff", 2)],
    "tavern": [("barkeep", 1), ("tavern_staff", 2)],
    "market_stall": [("trader", 1)],
    "manor": [("noble", 1), ("servant", 3)],
    "residence": [],
    "farmstead": [("farmer", 1), ("farmhand", 3)],
}

BUILDING_HOME_CAPACITY: Dict[str, int] = {
    "manor": 10,
    "residence": 6,
    "farmstead": 8,
}


def poisson_disc_fill(polygon, target_count, min_spacing, rng, max_attempts_per_point=30):
    min_x = min(p[0] for p in polygon)
    max_x = max(p[0] for p in polygon)
    min_y = min(p[1] for p in polygon)
    max_y = max(p[1] for p in polygon)

    points: List[Tuple[float, float]] = []
    attempts = 0
    max_total_attempts = max(1, target_count) * max_attempts_per_point
    while len(points) < target_count and attempts < max_total_attempts:
        attempts += 1
        x = rng.uniform(min_x, max_x)
        y = rng.uniform(min_y, max_y)
        candidate = (x, y)
        if not point_in_polygon(candidate, polygon):
            continue
        if all(distance(candidate, p) >= min_spacing for p in points):
            points.append(candidate)
    return points


def fill_district_buildings(district: District, town_seed, next_building_id: int) -> List[Building]:
    rng = rng_for(town_seed, "buildings", district.id)
    area = polygon_area(district.polygon)
    density = BUILDING_DENSITY_PER_AREA[district.zone_type]
    target_count = max(1, round(area * density))
    spacing = MIN_BUILDING_SPACING[district.zone_type]

    points = poisson_disc_fill(district.polygon, target_count, spacing, rng)

    type_weights = BUILDING_TYPES_BY_ZONE[district.zone_type]
    subtypes = list(type_weights.keys())
    weights = list(type_weights.values())

    buildings: List[Building] = []
    building_id = next_building_id
    for x, y in points:
        building_type = rng.choices(subtypes, weights=weights, k=1)[0]
        capacity = BUILDING_HOME_CAPACITY.get(building_type, 0)
        vacancies = [
            JobVacancy(building_id=building_id, occupation=occupation)
            for occupation, count in JOB_VACANCIES_BY_BUILDING_TYPE[building_type]
            for _ in range(count)
        ]
        buildings.append(Building(
            id=building_id,
            district_id=district.id,
            district_zone_type=district.zone_type,
            x=x,
            y=y,
            building_type=building_type,
            capacity=capacity,
            vacancies=vacancies,
        ))
        building_id += 1

    return buildings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_buildings.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/buildings.py tests/test_buildings.py
git commit -m "feat: fill districts with buildings and job vacancies"
```

---

## Task 7: Household generation

**Files:**
- Create: `town_shaper/households.py`
- Test: `tests/test_households.py`

**Interfaces:**
- Consumes: `rng_for` from `town_shaper.seeding`; `Household` from `town_shaper.models`
- Produces: `AVERAGE_HOUSEHOLD_SIZE = 3.5`, `CHILD_COUNT_WEIGHTS = [20, 30, 15, 10, 10, 15]`, `generate_households(town_seed, target_population: int) -> List[Household]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_households.py
from collections import Counter

from town_shaper.households import generate_households


def test_generate_households_is_deterministic():
    first = generate_households(("town", 1), target_population=3000)
    second = generate_households(("town", 1), target_population=3000)
    assert [(h.id, h.has_spouse, h.child_count) for h in first] == \
           [(h.id, h.has_spouse, h.child_count) for h in second]


def test_generate_households_produces_at_least_one_household():
    households = generate_households(("town", 1), target_population=3000)
    assert len(households) > 0


def test_generate_households_child_counts_stay_in_expected_range():
    households = generate_households(("town", 1), target_population=3000)
    for household in households:
        assert 0 <= household.child_count <= 5


def test_generate_households_child_count_distribution_is_weighted_toward_fewer_children():
    households = generate_households(("town", 1), target_population=3000)
    counts = Counter(h.child_count for h in households)
    # 0 and 1 children combined should be the plurality, matching the
    # 20/30/15/10/10/15 weighting (mirrors popgen.py's family-size shape).
    assert counts[0] + counts[1] > counts[4] + counts[5]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_households.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_shaper.households'`

- [ ] **Step 3: Write the household generation module**

```python
# town_shaper/households.py
from typing import List

from town_shaper.models import Household
from town_shaper.seeding import rng_for

AVERAGE_HOUSEHOLD_SIZE = 3.5
SPOUSE_CHANCE = 0.7
CHILD_COUNT_WEIGHTS = [20, 30, 15, 10, 10, 15]  # for 0, 1, 2, 3, 4, 5 children


def _sample_child_count(rng) -> int:
    return rng.choices(range(len(CHILD_COUNT_WEIGHTS)), weights=CHILD_COUNT_WEIGHTS, k=1)[0]


def generate_households(town_seed, target_population: int) -> List[Household]:
    rng = rng_for(town_seed, "households")
    target_household_count = max(1, round(target_population / AVERAGE_HOUSEHOLD_SIZE))

    households: List[Household] = []
    total_members = 0
    household_id = 0
    while household_id < target_household_count and total_members < target_population:
        has_spouse = rng.random() < SPOUSE_CHANCE
        child_count = _sample_child_count(rng)
        households.append(Household(id=household_id, has_spouse=has_spouse, child_count=child_count))
        total_members += 1 + (1 if has_spouse else 0) + child_count
        household_id += 1

    return households
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_households.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/households.py tests/test_households.py
git commit -m "feat: generate households with spouse/child linkage"
```

---

## Task 8: Resident assignment (homes and jobs)

**Files:**
- Create: `town_shaper/assignment.py`
- Test: `tests/test_assignment.py`

**Interfaces:**
- Consumes: `rng_for` from `town_shaper.seeding`; `District`, `Household`, `ResidentSlot`, `SES`, `ZoneType` from `town_shaper.models`
- Produces: `SES_PROPORTIONS`, `DRIFT_CHANCE = 0.05`, `ZONE_TYPE_BY_SES`, `assign_residents(town_seed, households: List[Household], districts: List[District]) -> List[ResidentSlot]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assignment.py
from town_shaper.anchors import place_anchors
from town_shaper.assignment import assign_residents
from town_shaper.buildings import fill_district_buildings
from town_shaper.districts import build_districts
from town_shaper.households import generate_households


def _build_town_pieces(seed, target_population=3000):
    bounds = (-200.0, -200.0, 200.0, 200.0)
    anchors = place_anchors(seed, target_population, bounds)
    districts = build_districts(anchors, bounds)

    next_id = 0
    for district in districts:
        buildings = fill_district_buildings(district, seed, next_id)
        district.buildings = buildings
        next_id += len(buildings)

    households = generate_households(seed, target_population)
    return districts, households


def test_assign_residents_never_exceeds_building_capacity():
    seed = ("town", 1)
    districts, households = _build_town_pieces(seed)
    assign_residents(seed, households, districts)

    for district in districts:
        for building in district.buildings:
            if building.capacity > 0:
                assert len(building.resident_ids) <= building.capacity


def test_assign_residents_never_double_fills_a_vacancy():
    seed = ("town", 1)
    districts, households = _build_town_pieces(seed)
    residents = assign_residents(seed, households, districts)

    filled_workplaces = [r.workplace_building_id for r in residents if r.workplace_building_id is not None]
    all_vacancies = [v for d in districts for b in d.buildings for v in b.vacancies]
    filled_vacancies = [v for v in all_vacancies if v.filled_by is not None]
    assert len(filled_vacancies) == len(filled_workplaces)
    assert len({v.filled_by for v in filled_vacancies}) == len(filled_vacancies)


def test_assign_residents_working_residents_have_occupation_matching_a_real_vacancy_type():
    seed = ("town", 1)
    districts, households = _build_town_pieces(seed)
    residents = assign_residents(seed, households, districts)

    vacancy_by_building = {}
    for d in districts:
        for b in d.buildings:
            vacancy_by_building[b.id] = {v.occupation for v in b.vacancies}

    for resident in residents:
        if resident.workplace_building_id is not None:
            assert resident.occupation in vacancy_by_building[resident.workplace_building_id]


def test_assign_residents_is_deterministic():
    seed = ("town", 1)
    districts1, households1 = _build_town_pieces(seed)
    residents1 = assign_residents(seed, households1, districts1)

    districts2, households2 = _build_town_pieces(seed)
    residents2 = assign_residents(seed, households2, districts2)

    key = lambda r: (r.id, r.household_id, r.ses, r.age_bracket, r.home_building_id, r.workplace_building_id, r.occupation)
    assert [key(r) for r in residents1] == [key(r) for r in residents2]


def test_assign_residents_children_never_get_a_workplace():
    seed = ("town", 1)
    districts, households = _build_town_pieces(seed)
    residents = assign_residents(seed, households, districts)

    for resident in residents:
        if resident.age_bracket == "child":
            assert resident.workplace_building_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_assignment.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_shaper.assignment'`

- [ ] **Step 3: Write the resident assignment module**

```python
# town_shaper/assignment.py
from typing import Dict, List, Optional

from town_shaper.models import Building, District, Household, JobVacancy, ResidentSlot, SES, ZoneType
from town_shaper.seeding import rng_for

SES_PROPORTIONS: Dict[SES, float] = {SES.RICH: 0.2, SES.POOR: 0.8}
DRIFT_CHANCE = 0.05

ZONE_TYPE_BY_SES: Dict[SES, ZoneType] = {
    SES.RICH: ZoneType.RICH_RESIDENTIAL,
    SES.POOR: ZoneType.POOR_RESIDENTIAL,
}


def _draw_household_ses(rng) -> SES:
    base = SES.RICH if rng.random() < SES_PROPORTIONS[SES.RICH] else SES.POOR
    if rng.random() < DRIFT_CHANCE:
        return SES.POOR if base == SES.RICH else SES.RICH
    return base


def _find_home_with_capacity(residential_buildings: List[Building], ses: SES) -> Optional[Building]:
    preferred_zone = ZONE_TYPE_BY_SES[ses]
    for building in residential_buildings:
        if building.district_zone_type == preferred_zone and len(building.resident_ids) < building.capacity:
            return building
    for building in residential_buildings:
        if len(building.resident_ids) < building.capacity:
            return building
    return None


def _build_vacancy_pool(districts: List[District], rng) -> List[JobVacancy]:
    vacancies = [v for d in districts for b in d.buildings for v in b.vacancies]
    vacancies.sort(key=lambda v: (v.building_id, v.occupation))
    rng.shuffle(vacancies)
    return vacancies


def assign_residents(town_seed, households: List[Household], districts: List[District]) -> List[ResidentSlot]:
    rng = rng_for(town_seed, "assignment")

    residential_buildings = sorted(
        (b for d in districts for b in d.buildings if b.capacity > 0),
        key=lambda b: b.id,
    )
    vacancy_pool = _build_vacancy_pool(districts, rng)

    residents: List[ResidentSlot] = []
    resident_id = 0

    for household in households:
        ses = _draw_household_ses(rng)
        home = _find_home_with_capacity(residential_buildings, ses)
        if home is None:
            break

        member_specs = [("adult", True)]
        if household.has_spouse:
            member_specs.append(("adult", True))
        member_specs.extend([("child", False)] * household.child_count)

        for age_bracket, is_working_age in member_specs:
            if len(home.resident_ids) >= home.capacity:
                # Household no longer fits in this home; remaining members go homeless
                # for this pass rather than double-booking capacity.
                break

            resident = ResidentSlot(
                id=resident_id,
                household_id=household.id,
                ses=ses,
                age_bracket=age_bracket,
                home_building_id=home.id,
            )
            if is_working_age and vacancy_pool:
                vacancy = vacancy_pool.pop()
                resident.workplace_building_id = vacancy.building_id
                resident.occupation = vacancy.occupation
                vacancy.filled_by = resident.id

            residents.append(resident)
            home.resident_ids.append(resident.id)
            resident_id += 1

    return residents
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_assignment.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/assignment.py tests/test_assignment.py
git commit -m "feat: assign households to homes and jobs from the vacancy pool"
```

---

## Task 9: Top-level orchestrator and integration tests

**Files:**
- Create: `town_shaper/generate.py`
- Test: `tests/test_generate.py`

**Interfaces:**
- Consumes: `place_anchors` from `town_shaper.anchors`; `build_districts` from `town_shaper.districts`; `fill_district_buildings` from `town_shaper.buildings`; `generate_households` from `town_shaper.households`; `assign_residents` from `town_shaper.assignment`; `Town` from `town_shaper.models`
- Produces: `compute_town_bounds(target_population: int) -> Tuple[float, float, float, float]`, `generate_town(seed, target_population: int) -> Town`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_generate.py
import time

from town_shaper.buildings import fill_district_buildings
from town_shaper.generate import compute_town_bounds, generate_town
from town_shaper.models import Town


def test_compute_town_bounds_grows_with_population():
    small_bounds = compute_town_bounds(target_population=200)
    large_bounds = compute_town_bounds(target_population=3000)
    small_area = (small_bounds[2] - small_bounds[0]) * (small_bounds[3] - small_bounds[1])
    large_area = (large_bounds[2] - large_bounds[0]) * (large_bounds[3] - large_bounds[1])
    assert large_area > small_area


def test_generate_town_returns_populated_town():
    town = generate_town(("town", 1), target_population=3000)
    assert isinstance(town, Town)
    assert len(town.districts) > 0
    assert len(town.residents) > 0
    assert any(len(d.buildings) > 0 for d in town.districts)


def test_generate_town_is_fully_deterministic():
    town1 = generate_town(("town", 1), target_population=3000)
    town2 = generate_town(("town", 1), target_population=3000)

    resident_key = lambda r: (r.id, r.household_id, r.ses, r.home_building_id, r.workplace_building_id, r.occupation)
    assert [resident_key(r) for r in town1.residents] == [resident_key(r) for r in town2.residents]

    building_key = lambda b: (b.id, b.x, b.y, b.building_type)
    buildings1 = [building_key(b) for d in town1.districts for b in d.buildings]
    buildings2 = [building_key(b) for d in town2.districts for b in d.buildings]
    assert buildings1 == buildings2


def test_generate_town_single_district_matches_full_pipeline():
    seed = ("town", 1)
    town = generate_town(seed, target_population=3000)

    target_district = town.districts[0]
    next_id = target_district.buildings[0].id if target_district.buildings else 0
    recomputed = fill_district_buildings(target_district, seed, next_building_id=next_id)

    original_types = [b.building_type for b in target_district.buildings]
    recomputed_types = [b.building_type for b in recomputed]
    assert original_types == recomputed_types


def test_generate_town_completes_within_time_budget_at_low_thousands_scale():
    start = time.monotonic()
    generate_town(("town", 1), target_population=3000)
    elapsed = time.monotonic() - start
    assert elapsed < 10.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_generate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_shaper.generate'`

- [ ] **Step 3: Write the orchestrator**

```python
# town_shaper/generate.py
import math
from typing import Tuple

from town_shaper.anchors import place_anchors
from town_shaper.assignment import assign_residents
from town_shaper.buildings import fill_district_buildings
from town_shaper.districts import build_districts
from town_shaper.households import generate_households
from town_shaper.models import Town

AREA_PER_RESIDENT = 150.0  # square map-units of town area assumed per resident


def compute_town_bounds(target_population: int) -> Tuple[float, float, float, float]:
    area = target_population * AREA_PER_RESIDENT
    side = math.sqrt(area)
    half = side / 2.0
    return (-half, -half, half, half)


def generate_town(seed, target_population: int) -> Town:
    bounds = compute_town_bounds(target_population)

    anchors = place_anchors(seed, target_population, bounds)
    districts = build_districts(anchors, bounds)

    next_building_id = 0
    for district in districts:
        buildings = fill_district_buildings(district, seed, next_building_id)
        district.buildings = buildings
        next_building_id += len(buildings)

    households = generate_households(seed, target_population)
    residents = assign_residents(seed, households, districts)

    town = Town(seed=seed, target_population=target_population, bounds=bounds)
    town.districts = districts
    town.residents = residents
    return town
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_generate.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS (all tests across every task)

- [ ] **Step 6: Commit**

```bash
git add town_shaper/generate.py tests/test_generate.py
git commit -m "feat: add generate_town orchestrator tying the pipeline together"
```

---

## Self-Review Notes

- **Spec coverage**: scope boundary (Task 1's `ResidentSlot` carries only placeholders, no names/traits), data model (Task 1), generation pipeline steps 1-5 (Tasks 2, 4, 5, 6, 7, 8), jobs-as-resource-pool (Task 6 creates vacancies, Task 8 consumes them), determinism via explicit `random.Random` (Task 2, used throughout), error handling for Voronoi boundary clipping (Task 3, Task 5), minimum anchor count (Task 4), Poisson-disc packing shortfall (Task 6), zone proportions enforced by quota (Task 4), and the full testing strategy (determinism, geometric validity, population consistency, proportion/scale checks — Task 9) are all covered.
- **Type consistency**: `SES` was corrected to two tiers (`RICH`/`POOR`) to match the two residential `ZoneType` values, fixed before Task 1 was finalized. `Building.district_zone_type` is defined in Task 1 and populated in Task 6 so Task 8's home-matching logic has it available without a districts lookup. `ResidentSlot.age_bracket` values (`"adult"`, `"child"`) are produced consistently by Task 8's `member_specs` and consumed in Task 9's tests.
- **No placeholders**: every step above contains complete, runnable code — no TBDs or "add appropriate handling" steps.
