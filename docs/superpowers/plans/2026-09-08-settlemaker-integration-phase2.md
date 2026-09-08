# Settlemaker Integration Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `town_shaper`'s hand-built district/road/wall/building geometry pipeline with the settlemaker bridge built in Phase 1, delete the superseded code, and make settlemaker's own SVG the real rendering output in place of `town_db/render.py`.

**Architecture:** `town_shaper.generate.generate_town()` calls `settlemaker_bridge.pipeline.generate_via_settlemaker()` instead of the old `anchors -> districts -> blocks/countryside -> roads` chain, returning the same `Town` dataclass shape (plus one new `svg` field) that `town_db`, `town_relationships`, and `town_narrative` already consume unchanged. `town_db.generate.generate_town_database()` persists that SVG alongside the SQLite database instead of calling a separate renderer.

**Tech Stack:** Python (existing stack: shapely, pytest), the Node/settlemaker bridge from Phase 1 (`settlemaker_bridge/`).

## Global Constraints

- Every geometry-affecting random draw that stays Python-side keeps going through `town_shaper.seeding.rng_for` — unchanged from today (per the design spec and Phase 1 plan's Global Constraints).
- `settlemaker` stays pinned to the exact commit SHA validated in Phase 1 (`af6741127086762fc0d73bdec374dcfcd373d5be`) — never a floating branch.
- Nothing under `town_relationships/` or `town_narrative/` changes in this plan. `town_db/` changes only where explicitly listed below (SVG persistence; nothing else).
- Full test suite (`~/venvs/townshape/bin/python -m pytest tests/ -q`, or `python -m pytest tests/ -q` in an environment with `requirements.txt` installed) stays the acceptance bar after every task.
- **Decided 2026-09-08 (Phase 1 checkpoint + Phase 2 kickoff):** `area_per_resident_multiplier`, `density_multiplier`, and `magic_prevalence` have no settlemaker equivalent and no longer influence generated geometry — accept this gap rather than approximating it or removing the parameters. They stay in `TownParameters`/`generate_town`/`generate_town_database`'s signatures for API compatibility. `rich_proportion` is unaffected (it only ever drove downstream resident wealth-tier assignment via `assign_residents`, which is unchanged).
- **Ward -> zone-type mapping is CONFIRMED** (not provisional): `administration`/`cathedral`/`military`/`park` -> `civic`, `merchant`/`market` -> `merchant`, `slum`/`craftsmen` -> `poor_residential`, `patriciate` -> `rich_residential`, `harbour`/`gate` -> `port`, `farm` -> `farmland_edge`. `castle` remains genuinely unresolved (never appeared in any Phase 1 run) and still raises loudly in `parse_settlemaker_geojson` rather than silently defaulting.

---

## File Structure

**Modify:**
- `settlemaker_bridge/parse_geojson.py` — strip the closing-duplicate vertex GeoJSON polygons carry (matches this codebase's existing ring convention), populate `Building.vacancies` (currently always empty — see Task 1).
- `settlemaker_bridge/pipeline.py` — return real `WaterFeature` objects instead of a bespoke tuple shape, so `town_db.generate`'s existing water-insert code keeps working unmodified.
- `town_shaper/models.py` — add `Town.svg: str = ""`.
- `town_shaper/generate.py` — replace `generate_town()`'s body to call the settlemaker bridge; `compute_town_bounds` is unchanged.
- `town_db/generate.py` — `generate_town_database()` persists `town.svg` to a `.svg` file alongside the database.
- `town_shaper/geometry.py` — delete the seven functions only the doomed modules used; keep the four real survivors.
- `tests/test_generate.py`, `tests/test_db_schema.py`, `tests/test_db_generate.py`, `tests/test_assignment.py`, `tests/test_geometry.py` — updated for the above (exact diffs in each task).
- `README.md`, `requirements.txt` — Node.js/settlemaker setup note, drop `matplotlib`, fix now-dead references to `render_town.py`.

**Delete:**
- `scripts/generate_town_settlemaker.py` (Phase 1's throwaway checkpoint script, superseded).
- `town_db/render.py`, `scripts/render_town.py`, `tests/test_db_render.py`.
- `town_shaper/anchors.py`, `town_shaper/districts.py`, `town_shaper/roads.py`, `town_shaper/blocks.py`, `town_shaper/countryside.py`.
- `tests/test_anchors.py`, `tests/test_districts.py`, `tests/test_roads.py`, `tests/test_blocks.py`.

**New:**
- `tests/test_settlemaker_parse_geojson.py` — unit tests against fixed, hand-built GeoJSON fixtures (design spec's Determinism & Testing section).
- `tests/test_settlemaker_bridge_integration.py` — one real subprocess call against the pinned commit, skipped if Node/the bridge isn't available.

---

## Task 1: Fix settlemaker_bridge's output correctness, retire the Phase 1 throwaway script

Phase 1's checkpoint never exercised `assign_residents` or a second insert into a real product DB, so two shape bugs in the Phase 1 code went unnoticed: `Building.vacancies` is always empty (breaks job assignment silently — `assign_residents` reads `building.vacancies` directly, it does not look occupations up itself), and every stored polygon ring carries GeoJSON's redundant closing vertex (every other ring in this codebase, e.g. `town_db.generate._water_feature_rings`, drops it). `pipeline.py` also currently returns water as a bespoke `(kind, rings)` tuple instead of a real `WaterFeature`, which would break `town_db.generate`'s existing insert code the moment Task 2 wires this in for real.

**Files:**
- Modify: `settlemaker_bridge/parse_geojson.py`
- Modify: `settlemaker_bridge/pipeline.py`
- Delete: `scripts/generate_town_settlemaker.py`
- Create: `tests/test_settlemaker_parse_geojson.py`

**Interfaces:**
- Produces: `parse_settlemaker_geojson(geojson: dict, seed) -> (List[District], List[Building])` — same signature as before, `Building.vacancies` now populated, ring coordinates no longer carry a closing duplicate.
- Produces: `generate_via_settlemaker(...) -> (List[District], List[Building], List[WaterFeature], str)` — third element's type changes from `List[Tuple[str, List[List[Tuple[float,float]]]]]` to `List[WaterFeature]` (from `town_shaper.models`).

- [ ] **Step 1: Fix ring extraction and populate vacancies in `parse_geojson.py`**

Change the import block at the top of `settlemaker_bridge/parse_geojson.py`:

```python
from town_shaper.buildings import BUILDING_HOME_CAPACITY, BUILDING_NAME_POOLS, JOB_VACANCIES_BY_BUILDING_TYPE
from town_shaper.generate import BUILDING_ID_STRIDE
from town_shaper.models import Anchor, Building, District, JobVacancy, ZoneType
```

(adds `JOB_VACANCIES_BY_BUILDING_TYPE` to the first import and `JobVacancy` to the second.)

Both ring-extraction lines currently read:

```python
            ring = [tuple(p) for p in feature["geometry"]["coordinates"][0]]
```

(one in the `layer == "ward"` branch, one in the `layer == "building"` branch). Change **both** to drop the closing duplicate vertex GeoJSON polygons always carry (settlemaker's own `polygonToGeoJson` closes every ring by repeating vertex 0 — see `geojson-builder.js`):

```python
            ring = [tuple(p) for p in feature["geometry"]["coordinates"][0][:-1]]
```

In the `layer == "building"` branch, immediately before the `building = Building(...)` call, add:

```python
            vacancies = [
                JobVacancy(building_id=building_id, occupation=occupation)
                for occupation, count in JOB_VACANCIES_BY_BUILDING_TYPE[building_type]
                for _ in range(count)
            ]
```

Then add `vacancies=vacancies,` as a new argument to the `Building(...)` call (any position — dataclass fields are keyword here).

- [ ] **Step 2: Fix `pipeline.py` to return real `WaterFeature` objects**

Add `ShapelyPolygon` to the imports and change `_scale_water_features` and `generate_via_settlemaker`'s water handling. Replace the whole `_scale_water_features` function:

```python
def _scale_water_features(
    water_features: List[WaterFeature], town_bounds_half: float, local_radius: float,
) -> List[WaterFeature]:
    """Rescale every water feature into settlemaker's own local frame,
    returning real WaterFeature objects (not a bespoke tuple shape) so
    town_db.generate's existing _water_feature_rings(feature) call -- which
    expects a WaterFeature with a real shapely .polygon -- keeps working
    completely unmodified. Used for BOTH the coastlineGeometry input (so
    settlemaker classifies patches against the right shape) and
    Town.water_features (so the persisted water lines up with the
    buildings/districts settlemaker just emitted, which are already in
    that frame -- inserting town_shaper's original, unscaled water
    polygons alongside settlemaker's local-unit buildings would draw two
    features at wildly different scales on the same axes)."""
    scale = local_radius / town_bounds_half
    scaled: List[WaterFeature] = []
    for feature in water_features:
        rings = _water_feature_rings(feature)
        # Y flip: settlemaker's coordinate system is Y-down (SVG
        # convention, per geojson-builder.ts's own doc comment);
        # town_shaper's is plain Cartesian Y-up. Orientation is otherwise
        # arbitrary here (no compass tie-in on either side), so this only
        # needs to be a *consistent* convention, not a geographically
        # meaningful one.
        exterior = [(x * scale, -y * scale) for x, y in rings[0]]
        holes = [[(x * scale, -y * scale) for x, y in ring] for ring in rings[1:]]
        scaled.append(WaterFeature(
            id=feature.id, kind=feature.kind,
            polygon=ShapelyPolygon(exterior, holes=holes),
        ))
    return scaled
```

Add the import at the top of the file:

```python
from shapely.geometry import Polygon as ShapelyPolygon
```

In `generate_via_settlemaker`, change the type hints and the `coastlineGeometry`-building comprehension:

```python
def generate_via_settlemaker(
    seed: Any,
    target_population: int,
    area_per_resident_multiplier: float = 1.0,
    num_rivers: int = 0,
    has_coastline: bool = False,
    has_port: bool = False,
) -> Tuple[List[District], List[Building], List[WaterFeature], str]:
    """Returns (districts, buildings, scaled_water_features, svg). `svg` is
    settlemaker's own themed output for this exact town -- see the design
    spec's Rendering section: this project's real rendering path persists
    that SVG rather than reconstructing footprints in matplotlib, which
    Phase 1's checkpoint found throws away most of what makes settlemaker's
    output good (streets, farmland texture, plaza fill, proper wall/tower
    styling)."""
    bounds = compute_town_bounds(target_population, area_per_resident_multiplier)
    town_bounds_half = (bounds[2] - bounds[0]) / 2.0

    water_features = generate_water_features(
        seed, bounds, num_rivers=num_rivers, has_coastline=has_coastline,
    )

    burg = build_azgaar_burg_input(seed, target_population, has_port=has_port)
    settlemaker_seed = _settlemaker_seed(seed)

    scaled_water_features: List[WaterFeature] = []
    if water_features:
        dry_result = call_settlemaker(burg, settlemaker_seed)
        local_radius = _local_radius_from_bounds(dry_result["geojson"]["metadata"]["local_bounds"])
        scaled_water_features = _scale_water_features(water_features, town_bounds_half, local_radius)
        burg = dict(burg, coastlineGeometry=[
            [{"x": x, "y": y} for x, y in ring]
            for feature in scaled_water_features
            for ring in _water_feature_rings(feature)
        ])

    result = call_settlemaker(burg, settlemaker_seed)
    districts, buildings = parse_settlemaker_geojson(result["geojson"], seed)
    return districts, buildings, scaled_water_features, result["svg"]
```

- [ ] **Step 3: Delete the Phase 1 throwaway script**

```bash
rm scripts/generate_town_settlemaker.py
```

It depended on the old `(kind, rings)` tuple shape from `pipeline.py` and is fully superseded once Task 2 wires settlemaker into `generate_town()` for real — `scripts/generate_town.py` will do everything it did, automatically, from here on.

- [ ] **Step 4: Write `tests/test_settlemaker_parse_geojson.py`**

```python
import pytest

from settlemaker_bridge.parse_geojson import parse_settlemaker_geojson
from town_shaper.buildings import BUILDING_HOME_CAPACITY, JOB_VACANCIES_BY_BUILDING_TYPE
from town_shaper.models import ZoneType

# Closed rings (first point repeated), matching settlemaker's own
# polygonToGeoJson convention -- the parser is expected to drop the
# duplicate (see Task 1, Step 1).
SQUARE = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
SQUARE_2 = [[20.0, 0.0], [30.0, 0.0], [30.0, 10.0], [20.0, 10.0], [20.0, 0.0]]


def _ward(ward_type, ring):
    return {
        "type": "Feature",
        "properties": {
            "layer": "ward", "wardType": ward_type, "label": ward_type,
            "withinCity": True, "withinWalls": True,
        },
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def _building(ward_type, ring, building_id):
    return {
        "type": "Feature",
        "properties": {"layer": "building", "wardType": ward_type, "building_id": building_id},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def _poi(kind, ward_type, building_id, poi_id):
    return {
        "type": "Feature",
        "properties": {
            "layer": "poi", "poi_id": poi_id, "kind": kind,
            "ward_type": ward_type, "building_id": building_id,
        },
        "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
    }


def test_ward_maps_to_zone_type():
    geojson = {"features": [_ward("merchant", SQUARE)]}
    districts, _buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert len(districts) == 1
    assert districts[0].zone_type == ZoneType.MERCHANT


def test_ward_ring_drops_geojson_closing_duplicate():
    geojson = {"features": [_ward("civic", SQUARE)]}
    districts, _buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert districts[0].polygon_parts == [[tuple(p) for p in SQUARE[:-1]]]


def test_confirmed_ward_mappings():
    for ward_type, expected in [
        ("administration", ZoneType.CIVIC), ("cathedral", ZoneType.CIVIC),
        ("military", ZoneType.CIVIC), ("park", ZoneType.CIVIC),
        ("merchant", ZoneType.MERCHANT), ("market", ZoneType.MERCHANT),
        ("slum", ZoneType.POOR_RESIDENTIAL), ("craftsmen", ZoneType.POOR_RESIDENTIAL),
        ("patriciate", ZoneType.RICH_RESIDENTIAL),
        ("harbour", ZoneType.PORT), ("gate", ZoneType.PORT),
        ("farm", ZoneType.FARMLAND_EDGE),
    ]:
        geojson = {"features": [_ward(ward_type, SQUARE)]}
        districts, _buildings = parse_settlemaker_geojson(geojson, seed="s")
        assert districts[0].zone_type == expected, ward_type


def test_skippable_ward_types_produce_no_district():
    geojson = {"features": [_ward("water", SQUARE), _ward("empty", SQUARE_2)]}
    districts, _buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert districts == []


def test_unmapped_ward_type_raises_loudly():
    geojson = {"features": [_ward("castle", SQUARE)]}
    with pytest.raises(ValueError, match="castle"):
        parse_settlemaker_geojson(geojson, seed="s")


def test_building_after_skipped_ward_is_dropped():
    geojson = {"features": [_ward("water", SQUARE), _building("water", SQUARE, "b1")]}
    _districts, buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert buildings == []


def test_building_associates_with_most_recent_ward_by_emission_order():
    geojson = {"features": [
        _ward("merchant", SQUARE), _building("merchant", SQUARE, "b1"),
        _ward("slum", SQUARE_2), _building("slum", SQUARE_2, "b2"),
    ]}
    districts, _buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert len(districts) == 2
    assert districts[0].zone_type == ZoneType.MERCHANT
    assert districts[0].buildings[0].district_id == districts[0].id
    assert districts[1].zone_type == ZoneType.POOR_RESIDENTIAL
    assert districts[1].buildings[0].district_id == districts[1].id


def test_poi_maps_building_to_named_type_with_vacancies_and_name():
    geojson = {"features": [
        _ward("civic", SQUARE), _building("civic", SQUARE, "b1"),
        _poi("temple", "civic", "b1", "p1"),
    ]}
    _districts, buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert len(buildings) == 1
    building = buildings[0]
    assert building.building_type == "temple"
    assert building.name is not None
    expected = sorted(occ for occ, count in JOB_VACANCIES_BY_BUILDING_TYPE["temple"] for _ in range(count))
    assert sorted(v.occupation for v in building.vacancies) == expected
    assert all(v.building_id == building.id for v in building.vacancies)


def test_unmapped_poi_kind_falls_through_to_zone_infill():
    geojson = {"features": [
        _ward("slum", SQUARE), _building("slum", SQUARE, "b1"),
        _poi("well", "slum", "b1", "p1"),  # "well" has no POI_KIND_TO_BUILDING_TYPE entry
    ]}
    _districts, buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert buildings[0].building_type == "residence"


def test_building_without_poi_gets_zone_infill_type_and_capacity():
    geojson = {"features": [_ward("farm", SQUARE), _building("farm", SQUARE, "b1")]}
    _districts, buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert buildings[0].building_type == "farmstead"
    assert buildings[0].capacity == BUILDING_HOME_CAPACITY["farmstead"]
    # JOB_VACANCIES_BY_BUILDING_TYPE["farmstead"] == [("farmer", 1), ("farmhand", 3)] -> 4 vacancy slots
    assert len(buildings[0].vacancies) == 4


def test_building_footprint_and_centroid():
    geojson = {"features": [_ward("civic", SQUARE), _building("civic", SQUARE, "b1")]}
    _districts, buildings = parse_settlemaker_geojson(geojson, seed="s")
    building = buildings[0]
    assert building.footprint == [tuple(p) for p in SQUARE[:-1]]
    assert building.x == pytest.approx(5.0)
    assert building.y == pytest.approx(5.0)


def test_district_anchor_is_synthesized_at_centroid():
    geojson = {"features": [_ward("civic", SQUARE)]}
    districts, _buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert districts[0].anchor.x == pytest.approx(5.0)
    assert districts[0].anchor.y == pytest.approx(5.0)
    assert districts[0].anchor.zone_type == ZoneType.CIVIC


def test_parse_is_deterministic_for_same_seed():
    geojson = {"features": [
        _ward("civic", SQUARE), _building("civic", SQUARE, "b1"),
        _poi("temple", "civic", "b1", "p1"),
    ]}
    _d1, b1 = parse_settlemaker_geojson(geojson, seed="fixed-seed")
    _d2, b2 = parse_settlemaker_geojson(geojson, seed="fixed-seed")
    assert b1[0].name == b2[0].name
```

- [ ] **Step 5: Run the new tests, then the full suite**

```bash
python -m pytest tests/test_settlemaker_parse_geojson.py -v
python -m pytest tests/ -q
```

Expected: all new tests pass; full suite still at its pre-Task-1 count (this task adds tests but doesn't change any generation code path anything else exercises yet).

- [ ] **Step 6: Commit**

```bash
git add settlemaker_bridge/parse_geojson.py settlemaker_bridge/pipeline.py tests/test_settlemaker_parse_geojson.py
git rm scripts/generate_town_settlemaker.py
git commit -m "fix: settlemaker_bridge ring/vacancy/water-feature output shapes"
```

---

## Task 2: Wire settlemaker into generate_town(), persist SVG, fix directly-broken tests

**Files:**
- Modify: `town_shaper/models.py`
- Modify: `town_shaper/generate.py`
- Modify: `town_db/generate.py`
- Modify: `tests/test_generate.py`
- Modify: `tests/test_db_schema.py`
- Modify: `tests/test_db_generate.py`

**Interfaces:**
- Consumes: `settlemaker_bridge.pipeline.generate_via_settlemaker(seed, target_population, area_per_resident_multiplier=..., num_rivers=..., has_coastline=..., has_port=...) -> (List[District], List[Building], List[WaterFeature], str)` (Task 1's fixed signature).
- Produces: `town_shaper.generate.generate_town(...) -> Town` — same signature as before, `Town.road_network` is now always an empty `RoadNetwork()` (never `None`, never populated), `Town.svg: str` is new.
- Produces: `town_db.generate.generate_town_database(..., svg_path: Optional[str] = None) -> None` — writes `svg_path` (default: `db_path` with its extension replaced by `.svg`) in addition to its existing SQLite writes.

- [ ] **Step 1: Add `Town.svg`**

In `town_shaper/models.py`, add a field to the `Town` dataclass (after `road_network`):

```python
@dataclass
class Town:
    seed: tuple
    target_population: int
    bounds: Tuple[float, float, float, float]
    districts: List[District] = field(default_factory=list)
    residents: List[ResidentSlot] = field(default_factory=list)
    water_features: List[WaterFeature] = field(default_factory=list)
    road_network: Optional[RoadNetwork] = None
    svg: str = ""
```

- [ ] **Step 2: Rewrite `town_shaper/generate.py`**

Replace the whole file:

```python
import math
from typing import Tuple

from town_shaper.assignment import DEFAULT_RICH_PROPORTION, assign_residents
from town_shaper.households import generate_households
from town_shaper.models import RoadNetwork, Town

AREA_PER_RESIDENT = 150.0  # square map-units of town area assumed per resident
BUILDING_ID_STRIDE = 100_000  # still read by settlemaker_bridge.parse_geojson for building id derivation


def compute_town_bounds(
    target_population: int, area_per_resident_multiplier: float = 1.0
) -> Tuple[float, float, float, float]:
    area = target_population * AREA_PER_RESIDENT * area_per_resident_multiplier
    side = math.sqrt(area)
    half = side / 2.0
    return (-half, -half, half, half)


def generate_town(
    seed, target_population: int,
    area_per_resident_multiplier: float = 1.0,
    density_multiplier: float = 1.0,
    rich_proportion: float = DEFAULT_RICH_PROPORTION,
    num_rivers: int = 0,
    has_coastline: bool = False,
    has_port: bool = False,
    magic_prevalence: float = 0.0,
) -> Town:
    # Lazy import: settlemaker_bridge.pipeline imports compute_town_bounds
    # from this module, so a top-level import here would be circular.
    from settlemaker_bridge.pipeline import generate_via_settlemaker

    bounds = compute_town_bounds(target_population, area_per_resident_multiplier)

    # density_multiplier and magic_prevalence have no settlemaker equivalent
    # (Owner decision 2026-09-08, Phase 2 kickoff -- see this plan's Global
    # Constraints): settlemaker now owns ward/building layout entirely, so
    # neither parameter influences generated geometry any more. Both stay
    # accepted here (and in generate_town_database/TownParameters) purely
    # for API compatibility.
    districts, buildings, water_features, svg = generate_via_settlemaker(
        seed, target_population,
        area_per_resident_multiplier=area_per_resident_multiplier,
        num_rivers=num_rivers, has_coastline=has_coastline, has_port=has_port,
    )

    households = generate_households(seed, target_population)
    residents = assign_residents(seed, households, districts, rich_proportion=rich_proportion)

    town = Town(seed=seed, target_population=target_population, bounds=bounds)
    town.districts = districts
    town.residents = residents
    town.water_features = water_features
    # settlemaker's `street` layer isn't mapped onto RoadNode/RoadEdge (see
    # the design spec's "What this deletes" section) -- an empty network,
    # not None, so town_db.generate's road_nodes/road_edges insert loops
    # (which iterate .nodes/.edges) don't need a None-guard.
    town.road_network = RoadNetwork()
    town.svg = svg
    return town
```

Note this drops the `buildings` return value from `generate_via_settlemaker` on the ground — `parse_settlemaker_geojson` (Task 1's fixed version) already appends each `Building` onto its owning `District.buildings` as it parses, so `districts` alone already carries every building; the flat `buildings` list is redundant for this call site (it's used by `settlemaker_bridge.pipeline`'s own callers that need a flat list, e.g. tests).

- [ ] **Step 3: Persist SVG in `town_db/generate.py`**

Add to the imports at the top of `town_db/generate.py`:

```python
import os
from typing import Dict, Optional
```

(replaces the existing `from typing import Dict`).

Change `generate_town_database`'s signature and add the SVG write right after `town = generate_town(...)`:

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
    magic_prevalence: float = 0.0,
    aggression: float = 0.0,
    svg_path: Optional[str] = None,
) -> None:
    town = generate_town(
        seed, target_population,
        area_per_resident_multiplier=area_per_resident_multiplier,
        density_multiplier=density_multiplier,
        rich_proportion=rich_proportion,
        num_rivers=num_rivers,
        has_coastline=has_coastline,
        has_port=has_port,
        magic_prevalence=magic_prevalence,
    )

    if svg_path is None:
        svg_path = os.path.splitext(db_path)[0] + ".svg"
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(town.svg)

    conn = connect(db_path)
    create_schema(conn)
    # ... rest of the function is unchanged from here on ...
```

(The `# ... rest of the function is unchanged ...` marker is a plan-authoring note, not something to leave in the file — everything below `create_schema(conn)` in the current file stays exactly as-is.)

- [ ] **Step 4: Fix `tests/test_generate.py`**

Delete `test_generate_town_populates_road_network` entirely (its whole function body, lines 196-204 as of this plan's writing — search for the function name, it won't have moved far):

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

Replace `test_generate_town_has_no_local_road_edges`:

```python
def test_generate_town_has_no_local_road_edges():
    town = generate_town(("town", 1), target_population=3000)
    assert all(e.road_type != "local" for e in town.road_network.edges)
```

with:

```python
def test_generate_town_road_network_is_empty():
    # settlemaker's `street` layer isn't mapped onto RoadNode/RoadEdge (see
    # the design spec's "What this deletes" section) -- town.road_network
    # is a deliberately-empty placeholder now, not populated at all.
    town = generate_town(("town", 1), target_population=3000)
    assert town.road_network.nodes == []
    assert town.road_network.edges == []
```

Replace `test_generate_town_area_multiplier_grows_bounds_independent_of_district_count`:

```python
def test_generate_town_area_multiplier_grows_bounds_independent_of_district_count():
    compact = generate_town(("town", 1), target_population=3000, area_per_resident_multiplier=0.5)
    sprawling = generate_town(("town", 1), target_population=3000, area_per_resident_multiplier=2.0)

    compact_area = (compact.bounds[2] - compact.bounds[0]) * (compact.bounds[3] - compact.bounds[1])
    sprawling_area = (sprawling.bounds[2] - sprawling.bounds[0]) * (sprawling.bounds[3] - sprawling.bounds[1])
    assert sprawling_area > compact_area
    assert len(compact.districts) == len(sprawling.districts)
```

with:

```python
def test_generate_town_area_multiplier_no_longer_affects_district_count():
    # area_per_resident_multiplier has no settlemaker equivalent (Owner
    # decision 2026-09-08, see this plan's Global Constraints): district
    # layout is now entirely population-driven. town.bounds still grows
    # with the multiplier (compute_town_bounds is unchanged, still used for
    # the water-scaling frame in settlemaker_bridge.pipeline), it just no
    # longer bounds where districts/buildings actually sit -- those live in
    # settlemaker's own local coordinate frame.
    compact = generate_town(("town", 1), target_population=3000, area_per_resident_multiplier=0.5)
    sprawling = generate_town(("town", 1), target_population=3000, area_per_resident_multiplier=2.0)

    compact_area = (compact.bounds[2] - compact.bounds[0]) * (compact.bounds[3] - compact.bounds[1])
    sprawling_area = (sprawling.bounds[2] - sprawling.bounds[0]) * (sprawling.bounds[3] - sprawling.bounds[1])
    assert sprawling_area > compact_area
    assert len(compact.districts) == len(sprawling.districts)
```

(The assertions are identical — only the name/docstring changed, to stop implying compute_town_bounds independence was ever about geometry placement. `len(districts)` is population-driven either way, so this was already going to pass; it's flagged here so the *reason* it passes is documented correctly.)

Replace `test_generate_town_density_multiplier_changes_total_building_count`:

```python
def test_generate_town_density_multiplier_changes_total_building_count():
    sparse = generate_town(("town", 1), target_population=3000, density_multiplier=0.5)
    dense = generate_town(("town", 1), target_population=3000, density_multiplier=2.0)

    sparse_count = sum(len(d.buildings) for d in sparse.districts)
    dense_count = sum(len(d.buildings) for d in dense.districts)
    assert dense_count > sparse_count
```

with:

```python
def test_generate_town_density_multiplier_no_longer_affects_building_count():
    # density_multiplier has no settlemaker equivalent (Owner decision
    # 2026-09-08, see this plan's Global Constraints) -- accepted gap,
    # building count is now purely population/seed-driven.
    sparse = generate_town(("town", 1), target_population=3000, density_multiplier=0.5)
    dense = generate_town(("town", 1), target_population=3000, density_multiplier=2.0)

    sparse_count = sum(len(d.buildings) for d in sparse.districts)
    dense_count = sum(len(d.buildings) for d in dense.districts)
    assert dense_count == sparse_count
```

Replace `test_generate_town_with_magic_prevalence_can_produce_arcane_shops`:

```python
def test_generate_town_with_magic_prevalence_can_produce_arcane_shops():
    found = False
    for seed_index in range(20):
        town = generate_town(("town", seed_index), target_population=5000, magic_prevalence=0.8)
        all_types = [b.building_type for d in town.districts for b in d.buildings]
        if "arcane_shop" in all_types:
            found = True
            break
    assert found
```

with:

```python
def test_generate_town_magic_prevalence_no_longer_produces_arcane_shops():
    # magic_prevalence has no settlemaker equivalent (Owner decision
    # 2026-09-08, see this plan's Global Constraints):
    # settlemaker_bridge.parse_geojson.POI_KIND_TO_BUILDING_TYPE has no
    # arcane_shop mapping, so the type can never appear regardless of this
    # parameter's value -- accepted gap, not a bug.
    for seed_index in range(5):
        town = generate_town(("town", seed_index), target_population=5000, magic_prevalence=0.8)
        all_types = [b.building_type for d in town.districts for b in d.buildings]
        assert "arcane_shop" not in all_types
```

(20 seeds dropped to 5 -- the old test needed 20 tries to *find* an occurrence; this one is asserting absence across every seed it tries, so a handful is enough to catch a regression without slowing the suite down for no benefit.)

Leave every other test in the file untouched — including `test_generate_town_with_no_magic_prevalence_matches_previous_behavior` (still true, no code change needed) and `test_generate_town_threads_target_population_into_building_fill` (still true: settlemaker never produces `"university"` at pop 3000 either, since Phase 1's `parse_geojson.py` has no university mapping at all regardless of population — leave its comment as-is, it's still an accurate statement even if the *mechanism* changed).

- [ ] **Step 5: Fix `tests/test_db_schema.py`**

Replace `test_generate_town_database_persists_road_network`:

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
        assert edge[3] in ("artery", "boundary", "spur")
```

with:

```python
def test_generate_town_database_road_tables_are_empty(tmp_path):
    # road_nodes/road_edges stay in the schema (design spec's Data Model
    # section: no schema changes) but town.road_network is now always an
    # empty RoadNetwork() -- see town_shaper/generate.py's generate_town.
    from town_db.generate import generate_town_database

    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path)

    conn = connect(db_path)
    node_count = conn.execute("SELECT COUNT(*) FROM road_nodes").fetchone()[0]
    edge_count = conn.execute("SELECT COUNT(*) FROM road_edges").fetchone()[0]
    conn.close()

    assert node_count == 0
    assert edge_count == 0
```

Add a new test for SVG persistence right after it:

```python
def test_generate_town_database_writes_svg_file(tmp_path):
    from town_db.generate import generate_town_database

    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path)

    svg_path = str(tmp_path / "town.svg")
    with open(svg_path, encoding="utf-8") as f:
        content = f.read()
    assert "<svg" in content


def test_generate_town_database_honors_explicit_svg_path(tmp_path):
    from town_db.generate import generate_town_database

    db_path = str(tmp_path / "town.db")
    svg_path = str(tmp_path / "custom_name.svg")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path, svg_path=svg_path)

    with open(svg_path, encoding="utf-8") as f:
        content = f.read()
    assert "<svg" in content
```

- [ ] **Step 6: Fix `tests/test_db_generate.py`**

Replace `test_generate_town_database_threads_area_multiplier_into_building_placement`:

```python
def test_generate_town_database_threads_area_multiplier_into_building_placement(tmp_path):
    db_path_small = str(tmp_path / "small.db")
    db_path_large = str(tmp_path / "large.db")
    generate_town_database(
        ("town", 1), target_population=1500, db_path=db_path_small, area_per_resident_multiplier=0.5
    )
    generate_town_database(
        ("town", 1), target_population=1500, db_path=db_path_large, area_per_resident_multiplier=2.0
    )

    conn_small = sqlite3.connect(db_path_small)
    conn_large = sqlite3.connect(db_path_large)
    small_max_x = conn_small.execute("SELECT MAX(x) FROM buildings").fetchone()[0]
    large_max_x = conn_large.execute("SELECT MAX(x) FROM buildings").fetchone()[0]
    assert large_max_x > small_max_x
```

with:

```python
def test_generate_town_database_area_multiplier_no_longer_affects_building_placement(tmp_path):
    # area_per_resident_multiplier has no settlemaker equivalent (Owner
    # decision 2026-09-08, see docs/superpowers/plans/2026-09-08-
    # settlemaker-integration-phase2.md's Global Constraints) -- building
    # coordinates now live entirely in settlemaker's own local coordinate
    # frame, unrelated to this multiplier.
    db_path_small = str(tmp_path / "small.db")
    db_path_large = str(tmp_path / "large.db")
    generate_town_database(
        ("town", 1), target_population=1500, db_path=db_path_small, area_per_resident_multiplier=0.5
    )
    generate_town_database(
        ("town", 1), target_population=1500, db_path=db_path_large, area_per_resident_multiplier=2.0
    )

    conn_small = sqlite3.connect(db_path_small)
    conn_large = sqlite3.connect(db_path_large)
    small_max_x = conn_small.execute("SELECT MAX(x) FROM buildings").fetchone()[0]
    large_max_x = conn_large.execute("SELECT MAX(x) FROM buildings").fetchone()[0]
    assert small_max_x == pytest.approx(large_max_x)
```

This file's `sqlite3` import needs `pytest` added if it isn't already imported at the top — check the existing import block first; if `import pytest` is already there (it's used by other tests in the same file per Phase 1's own read of this file's neighbors), no change needed.

- [ ] **Step 7: Run the affected tests, then the full suite**

```bash
python -m pytest tests/test_generate.py tests/test_db_schema.py tests/test_db_generate.py -v
python -m pytest tests/ -q
```

Expected: every listed test passes. Full suite will still show failures from `tests/test_assignment.py` (imports `town_shaper.anchors`/`town_shaper.districts`, both untouched so far — that's Task 4, not this one) and from `tests/test_anchors.py`/`test_districts.py`/`test_roads.py`/`test_blocks.py`/`test_db_render.py` if any of THEIR assertions happen to exercise `generate_town` indirectly — check the actual failure list rather than assuming; if any of those five files fail here, it's collateral from this task's `generate_town`/`Town` changes, not a reason to touch those files yet (Tasks 3-4 delete them outright).

Two tests need real scrutiny, not just a run-and-hope: `test_generate_town_residential_building_counts_are_proportional_to_households` and `test_generate_town_houses_nearly_all_target_population` in `tests/test_generate.py` (unchanged by this task's edits, but their bounds were calibrated against the *old* pipeline's household-driven building counts). If either fails, don't guess new bound constants — print `residence_count`/`manor_count`/`len(town.residents)` from a real `generate_town(("town", 1), target_population=5000, rich_proportion=0.05)` call and calibrate the assertion's multiplier against what settlemaker actually produces, the same way the original bounds were derived from a real measured run (per that test's own comment: "a real test town had 10,436 residence buildings for 1,372 households").

- [ ] **Step 8: Commit**

```bash
git add town_shaper/models.py town_shaper/generate.py town_db/generate.py \
  tests/test_generate.py tests/test_db_schema.py tests/test_db_generate.py
git commit -m "feat: wire settlemaker into generate_town, persist SVG instead of matplotlib render"
```

---

## Task 3: Delete the old rendering path

**Files:**
- Delete: `town_db/render.py`, `scripts/render_town.py`, `tests/test_db_render.py`

**Interfaces:** None — pure deletion, nothing else imports these three files (verified in this plan's own research pass; `scripts/generate_town.py` never imported `town_db.render` directly).

- [ ] **Step 1: Confirm no remaining references**

```bash
grep -rn "town_db\.render\|from town_db import.*render\|render_town" --include="*.py" . \
  --exclude-dir=.claude --exclude-dir=.worktrees --exclude-dir=node_modules
```

Expected: no matches outside the three files being deleted (and this plan document's own prose, which `grep --include="*.py"` won't match anyway).

- [ ] **Step 2: Delete the files**

```bash
git rm town_db/render.py scripts/render_town.py tests/test_db_render.py
```

- [ ] **Step 3: Run the full suite**

```bash
python -m pytest tests/ -q
```

Expected: same pass count as Task 2's end, minus `test_db_render.py`'s 6 tests.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: delete the matplotlib renderer, superseded by settlemaker's own SVG"
```

---

## Task 4: Delete the superseded town_shaper geometry-pipeline modules, fix test_assignment.py

**Files:**
- Delete: `town_shaper/anchors.py`, `town_shaper/districts.py`, `town_shaper/roads.py`, `town_shaper/blocks.py`, `town_shaper/countryside.py`
- Delete: `tests/test_anchors.py`, `tests/test_districts.py`, `tests/test_roads.py`, `tests/test_blocks.py`
- Modify: `tests/test_assignment.py`

**Interfaces:**
- Produces: `tests/test_assignment.py`'s `_build_town_pieces(seed, target_population=3000) -> (List[District], List[Household])` — same signature, rebuilt to construct two hand-placed rectangular residential districts directly instead of running the deleted anchors/districts pipeline.

- [ ] **Step 1: Confirm no remaining references to the five doomed modules**

```bash
grep -rln "town_shaper\.\(anchors\|districts\|blocks\|roads\|countryside\)\b" --include="*.py" . \
  --exclude-dir=.claude --exclude-dir=.worktrees --exclude-dir=node_modules
```

Expected: only the five modules themselves and their four dedicated test files, plus `tests/test_assignment.py` (fixed in Step 3 below) and `town_db/schema.py`'s `road_nodes`/`road_edges` table DDL (a string match on "roads", not an import — ignore it, it's unrelated).

- [ ] **Step 2: Delete the five modules and their four dedicated test files**

```bash
git rm town_shaper/anchors.py town_shaper/districts.py town_shaper/roads.py \
  town_shaper/blocks.py town_shaper/countryside.py \
  tests/test_anchors.py tests/test_districts.py tests/test_roads.py tests/test_blocks.py
```

- [ ] **Step 3: Rewrite `tests/test_assignment.py`'s fixture helper**

Replace the top of the file (imports through the end of `_build_town_pieces`):

```python
from town_shaper.assignment import ZONE_TYPE_BY_SES, assign_residents
from town_shaper.buildings import fill_district_buildings
from town_shaper.generate import compute_town_bounds, generate_town
from town_shaper.households import generate_households
from town_shaper.models import Anchor, Building, District, Household, SES, ZoneType


def _build_town_pieces(seed, target_population=3000):
    # town_shaper.anchors/districts are gone (settlemaker owns ward layout
    # now -- see docs/superpowers/specs/2026-09-08-settlemaker-integration-
    # design.md). assign_residents doesn't care how a District's polygon or
    # buildings came to exist, so this hand-builds two big rectangular
    # residential districts directly (one poor, one rich) instead of
    # running the deleted anchors/districts Voronoi pipeline. Sized off
    # compute_town_bounds, same as the old fixture, so
    # fill_district_buildings' BUILDING_DENSITY_PER_AREA calibration still
    # produces enough capacity to house target_population.
    bounds = compute_town_bounds(target_population)
    half_width = (bounds[2] - bounds[0]) / 2.0

    poor_polygon = [(-half_width, -half_width), (0.0, -half_width), (0.0, half_width), (-half_width, half_width)]
    rich_polygon = [(0.0, -half_width), (half_width, -half_width), (half_width, half_width), (0.0, half_width)]

    poor_district = District(
        id=1, zone_type=ZoneType.POOR_RESIDENTIAL,
        anchor=Anchor(id=1, zone_type=ZoneType.POOR_RESIDENTIAL, x=-half_width / 2, y=0.0),
        polygon_parts=[poor_polygon],
    )
    rich_district = District(
        id=2, zone_type=ZoneType.RICH_RESIDENTIAL,
        anchor=Anchor(id=2, zone_type=ZoneType.RICH_RESIDENTIAL, x=half_width / 2, y=0.0),
        polygon_parts=[rich_polygon],
    )

    next_id = 0
    for district in (poor_district, rich_district):
        buildings = fill_district_buildings(district, seed, next_id, target_population=target_population)
        district.buildings = buildings
        next_id += len(buildings)

    districts = [poor_district, rich_district]
    households = generate_households(seed, target_population)
    return districts, households
```

Every test function below this in the file is unchanged — they all call `_build_town_pieces(...)` and `assign_residents(...)` without touching anchors/districts internals directly, so the new fixture is a drop-in replacement. `test_assign_residents_ses_drift_is_observable` calls `generate_town` directly (not `_build_town_pieces`) and is unaffected either way — it exercises the real (now settlemaker-backed) pipeline as a black box.

- [ ] **Step 4: Run test_assignment.py, then the full suite**

```bash
python -m pytest tests/test_assignment.py -v
python -m pytest tests/ -q
```

Expected: every `test_assignment.py` test passes, including `test_assign_residents_high_rich_proportion_produces_majority_rich_residents` and `test_assign_residents_zero_rich_proportion_produces_no_rich_residents` (both need the fixture's rich/poor districts to actually have adequate building capacity -- if either fails, the district rectangles are too small for `target_population`; widen `half_width`'s effective area or check `fill_district_buildings`'s `BUILDING_DENSITY_PER_AREA` inputs rather than guessing). Full suite should now be down to just Task 5's geometry.py cleanup remaining as a source of dead code (not failures — nothing currently fails because of unused functions, this is a pure tidiness task).

- [ ] **Step 5: Commit**

```bash
git add tests/test_assignment.py
git commit -m "chore: delete superseded town_shaper geometry-pipeline modules"
```

---

## Task 5: Clean up town_shaper/geometry.py

**Files:**
- Modify: `town_shaper/geometry.py`
- Modify: `tests/test_geometry.py`

**Interfaces:**
- Produces: `town_shaper/geometry.py` keeps only `polygon_area`, `point_in_polygon`, `distance`, `chaikin_smooth` — all four have real surviving callers (`town_shaper/buildings.py`, `town_relationships/neighbors.py`, `town_relationships/shops.py`, `town_shaper/water.py`). **Do not delete these four** — the design spec's original "everything else... goes with it" claim about `chaikin_smooth` being the sole survivor was wrong; verified by grepping every caller of every function in the file across the whole repo, excluding the five modules Task 4 already deleted.

- [ ] **Step 1: Confirm the survivor list**

```bash
grep -rn "polygon_area\|point_in_polygon\|distance(\|chaikin_smooth\|rotated_rect_corners\|clip_polygon_by_line\|clip_polygon_to_bounds\|inset_polygon\|jaggify_polygon" \
  --include="*.py" town_shaper/ town_db/ town_relationships/ town_narrative/ tests/ \
  | grep -v "town_shaper/geometry.py\|tests/test_geometry.py"
```

Expected: `polygon_area` in `town_shaper/buildings.py`; `point_in_polygon` in `town_shaper/buildings.py` and `tests/test_buildings.py`; `distance` in `town_shaper/buildings.py`, `town_relationships/neighbors.py`, `town_relationships/shops.py`; `chaikin_smooth` in `town_shaper/water.py`. Nothing else.

- [ ] **Step 2: Delete the seven dead functions from `town_shaper/geometry.py`**

Delete `rotated_rect_corners`, `_is_inside_edge`, `_line_intersection`, `clip_polygon_by_line`, `clip_polygon_to_bounds`, `inset_polygon`, `jaggify_polygon` and any now-unused imports at the top of the file those functions needed (check each remaining function's own imports still resolve — `polygon_area`/`point_in_polygon`/`distance`/`chaikin_smooth` likely only need `math` and/or nothing beyond stdlib; verify by running the file's own tests in Step 4 rather than guessing which imports are now dead).

- [ ] **Step 3: Trim `tests/test_geometry.py`**

Delete every test function for the seven removed functions (their names all start with `test_clip_polygon_`, `test_inset_polygon_`, or `test_jaggify_polygon_`). Keep `test_polygon_area_of_unit_square`, `test_point_in_polygon_inside_and_outside`, `test_distance_of_3_4_5_triangle`, and any `test_chaikin_smooth_*` functions untouched.

- [ ] **Step 4: Run the tests, then the full suite**

```bash
python -m pytest tests/test_geometry.py -v
python -m pytest tests/ -q
```

Expected: `test_geometry.py` down to its four survivors (plus any chaikin tests), all passing. Full suite green.

- [ ] **Step 5: Commit**

```bash
git add town_shaper/geometry.py tests/test_geometry.py
git commit -m "chore: delete geometry.py functions only the deleted block-cutting pipeline used"
```

---

## Task 6: Add a real-subprocess integration smoke test for the bridge

**Files:**
- Create: `tests/test_settlemaker_bridge_integration.py`

**Interfaces:**
- Consumes: `settlemaker_bridge.pipeline.generate_via_settlemaker` (Task 1's fixed version), `settlemaker_bridge.bridge.BRIDGE_DIR`.

- [ ] **Step 1: Write the test**

```python
import shutil
from pathlib import Path

import pytest

from settlemaker_bridge.bridge import BRIDGE_DIR
from settlemaker_bridge.pipeline import generate_via_settlemaker

_BRIDGE_READY = shutil.which("node") is not None and (BRIDGE_DIR / "node_modules" / "settlemaker").is_dir()

pytestmark = pytest.mark.skipif(
    not _BRIDGE_READY,
    reason="node and/or settlemaker_bridge/node_modules/settlemaker not present -- "
           "run `npm install` in settlemaker_bridge/ first (see docs/superpowers/specs/"
           "2026-09-08-settlemaker-integration-design.md's Risks section for a known "
           "sandboxed-npm caveat)",
)


def test_bridge_round_trip_produces_districts_buildings_and_svg():
    districts, buildings, water_features, svg = generate_via_settlemaker(
        "bridge-integration-test", 3000, num_rivers=1, has_coastline=True, has_port=True,
    )
    assert len(districts) > 0
    assert len(buildings) > 0
    assert len(water_features) == 2
    assert "<svg" in svg


def test_bridge_round_trip_is_deterministic():
    result1 = generate_via_settlemaker("bridge-integration-test", 3000, num_rivers=1, has_coastline=True)
    result2 = generate_via_settlemaker("bridge-integration-test", 3000, num_rivers=1, has_coastline=True)

    districts1, buildings1, _water1, svg1 = result1
    districts2, buildings2, _water2, svg2 = result2

    key = lambda b: (b.id, b.district_id, b.building_type, b.x, b.y, b.footprint)
    assert sorted(map(key, buildings1)) == sorted(map(key, buildings2))
    assert svg1 == svg2
```

- [ ] **Step 2: Run it**

```bash
python -m pytest tests/test_settlemaker_bridge_integration.py -v
```

Expected: both tests pass in this session (the bridge is already set up here). In an environment without Node/the bridge, expect both to skip with the reason string above, not fail.

- [ ] **Step 3: Run the full suite one more time**

```bash
python -m pytest tests/ -q
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_settlemaker_bridge_integration.py
git commit -m "test: add a real-subprocess integration smoke test for settlemaker_bridge"
```

---

## Task 7: Final pass — docs, requirements, attribution

**Files:**
- Modify: `README.md`
- Modify: `requirements.txt`

- [ ] **Step 1: Drop `matplotlib` from `requirements.txt`**

`matplotlib` was only ever imported by `town_db/render.py` (deleted in Task 3) and the Phase 1 throwaway script (deleted in Task 1) — confirm with:

```bash
grep -rln "matplotlib" --include="*.py" . --exclude-dir=.claude --exclude-dir=.worktrees --exclude-dir=node_modules
```

Expected: no matches. Remove the `matplotlib>=3.8` line from `requirements.txt`.

- [ ] **Step 2: Update README.md**

In the `## Requirements` section, change:

```markdown
- Python 3.10+
- `pip install -r requirements.txt` (numpy, scipy, shapely, matplotlib,
  pytest)
```

to:

```markdown
- Python 3.10+
- `pip install -r requirements.txt` (numpy, scipy, shapely, pytest)
- Node.js (any recent LTS) and `npm install` run once inside
  `settlemaker_bridge/` — town generation shells out to
  [settlemaker](https://github.com/barrulus/settlemaker) (pinned to a
  specific commit in `settlemaker_bridge/package.json`) for all
  district/building/wall geometry and the rendered SVG. See
  `docs/superpowers/specs/2026-09-08-settlemaker-integration-design.md`
  for the full integration design, including a known npm caveat under
  some sandboxed CI environments.
```

In `## Quick start`, change:

```markdown
```bash
python scripts/generate_town.py    # edit the constants at the top of the file first
python scripts/render_town.py my_town.db
```

`scripts/generate_town.py` is a plain editable-variables script (not a
CLI with flags) — open it and change `SEED`, `TARGET_POPULATION`, and
the other `TownParameters` fields at the top, then run it. It builds
the town, derives relationships, and prints a resident count and
stress readout. `scripts/render_town.py <db_path> [output_path]` then
renders that database to a PNG.
```

to:

```markdown
```bash
python scripts/generate_town.py    # edit the constants at the top of the file first
```

`scripts/generate_town.py` is a plain editable-variables script (not a
CLI with flags) — open it and change `SEED`, `TARGET_POPULATION`, and
the other `TownParameters` fields at the top, then run it. It builds the
town, derives relationships, prints a resident count and stress readout,
and writes both a `.db` file and a `.svg` file (settlemaker's own themed
render of the generated town) next to each other.
```

In `## Repo layout`, change:

```markdown
- `town_db/` — SQLite database generation (residents, history, goods,
  purchases, stats, rendering)
```

to:

```markdown
- `town_db/` — SQLite database generation (residents, history, goods,
  purchases, stats)
- `settlemaker_bridge/` — the Node bridge to
  [settlemaker](https://github.com/barrulus/settlemaker) (district/
  building/wall geometry and SVG rendering) and the Python-side parser
  that maps its output onto `town_shaper`'s `District`/`Building` models
```

and change:

```markdown
- `scripts/` — small runnable entry points (`generate_town.py`,
  `render_town.py`)
```

to:

```markdown
- `scripts/` — small runnable entry points (`generate_town.py`)
```

- [ ] **Step 3: Commit**

```bash
git add README.md requirements.txt
git commit -m "docs: update README/requirements for the settlemaker integration"
```

- [ ] **Step 4: Final full-suite run and sign-off checkpoint**

```bash
python -m pytest tests/ -q
```

Expected: full green suite. Report the final pass count to the user alongside a summary of what changed, and treat this as the natural point to ask whether they want a real generated town (via `scripts/generate_town.py`) shown before considering Phase 2 fully done — the same "show, don't just assert" standard Phase 1's checkpoint used.

## Self-Review

**Spec coverage** — every Phase 2 bullet from `docs/superpowers/plans/2026-09-08-settlemaker-integration.md`'s Phase 2 section is covered: wiring (Task 2), deletions including `render.py` (Tasks 3-4), `District.anchor` handling (already satisfied by Phase 1's `parse_geojson.py` synthesizing a centroid `Anchor` — verified, no task needed), `castle`/`military`/`park` ward-type resolution (confirmed in Global Constraints, `castle` still raises loudly on purpose), `test_blocks.py` rewrite (Task 4 — turned out to be a clean deletion, not a rewrite, since every one of its 46 tests exercises deleted functionality directly), new `parse_settlemaker_geojson` tests + integration smoke test (Tasks 1 and 6), full suite green (every task's own step + Task 7's final run).

**Placeholder scan** — no TBD/TODO/"add appropriate handling" patterns; every step shows real code or an exact command with its expected output.

**Type consistency** — `generate_via_settlemaker`'s return type (`Tuple[List[District], List[Building], List[WaterFeature], str]`) is consistent from Task 1 (where it's fixed) through Task 2 (where it's consumed) through Task 6 (where it's tested again). `Town.svg: str` is added once (Task 2, Step 1) and consumed once (Task 2, Step 2) — no drift.
