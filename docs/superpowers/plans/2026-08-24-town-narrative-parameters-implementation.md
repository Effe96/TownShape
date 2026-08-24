# Town Narrative Parameters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `town_narrative`, a package providing a `TownParameters` schema and a `generate_town_from_parameters(params, db_path)` entry point, and promote three of `town_shaper`'s currently-hardcoded generation constants (physical town size, building density, SES richness) to optional parameters threaded through the whole pipeline.

**Architecture:** `TownParameters` (new, `town_narrative/parameters.py`) is a validated dataclass. Three existing `town_shaper` functions (`compute_town_bounds`, `fill_district_buildings`, `assign_residents`) and `town_shaper.generate.generate_town` each gain new *optional* parameters whose defaults reproduce today's exact hardcoded behavior — existing callers and tests need no changes. `town_db.generate.generate_town_database` passes the same three parameters straight through. `town_narrative.generate.generate_town_from_parameters` composes `generate_town_database` with a new `generation_parameters` table insert (one row per generated database, recording what was chosen). A narrative-mapping reference doc and a Claude Code skill wrap this in the conversational workflow described in the spec.

**Tech Stack:** Python 3.12, stdlib only (`dataclasses`, `sqlite3`) — no new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-08-24-town-narrative-parameters-design.md`

## Global Constraints

- Every new parameter (`area_per_resident_multiplier`, `density_multiplier`, `rich_proportion`) is optional with a default that reproduces today's exact hardcoded behavior (`1.0`, `1.0`, `0.05` respectively) — no existing call site or test in `town_shaper`'s or `town_db`'s own suites should require changes.
- No embedded LLM call anywhere in this package — narrative interpretation is done by the agent (Claude Code, in-session) driving `TownParameters`, not by code in this repo.
- `TownParameters.__post_init__` validates: `target_population > 0`, `area_per_resident_multiplier > 0`, `density_multiplier > 0`, `0.0 <= rich_proportion <= 1.0` — raising `ValueError` on violation, matching the existing `compute_anchor_counts` precedent in `town_shaper/anchors.py`.
- A low-density, small-area, high-population combination that leaves some residents unhoused is not an error — `town_shaper/assignment.py` already tolerates this gracefully (`_find_home_with_capacity` returns `None`, the resident is silently skipped for that pass) and this plan adds no new validation against it.
- Editing an already-generated town from narrative input (creative mode) is out of scope for this plan.
- Test files live in the shared top-level `tests/` directory with the `test_narrative_` filename prefix for new files, matching the project's `test_db_`/`test_relationships_` convention; changes to existing `town_shaper`/`town_db` behavior are tested by appending to the existing test files for the modules touched.

---

## Task 1: Package scaffolding and `TownParameters`

**Files:**
- Create: `town_narrative/__init__.py`
- Create: `town_narrative/parameters.py`
- Test: `tests/test_narrative_parameters.py`

**Interfaces:**
- Produces: `TownParameters` dataclass — `seed: Any`, `target_population: int`, `area_per_resident_multiplier: float = 1.0`, `density_multiplier: float = 1.0`, `rich_proportion: float = 0.05`. Raises `ValueError` from `__post_init__` for any invalid field.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_narrative_parameters.py
import pytest

from town_narrative.parameters import TownParameters


def test_defaults_match_current_hardcoded_behavior():
    params = TownParameters(seed="town-1", target_population=1000)
    assert params.area_per_resident_multiplier == 1.0
    assert params.density_multiplier == 1.0
    assert params.rich_proportion == 0.05


def test_valid_parameters_construct_successfully():
    params = TownParameters(
        seed="town-1", target_population=1000,
        area_per_resident_multiplier=2.0, density_multiplier=0.5, rich_proportion=0.2,
    )
    assert params.target_population == 1000
    assert params.area_per_resident_multiplier == 2.0
    assert params.density_multiplier == 0.5
    assert params.rich_proportion == 0.2


def test_non_positive_target_population_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=0)
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=-5)


def test_non_positive_area_multiplier_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, area_per_resident_multiplier=0.0)
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, area_per_resident_multiplier=-1.0)


def test_non_positive_density_multiplier_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, density_multiplier=0.0)
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, density_multiplier=-1.0)


def test_rich_proportion_out_of_range_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, rich_proportion=1.5)
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, rich_proportion=-0.1)


def test_rich_proportion_boundary_values_are_valid():
    TownParameters(seed="town-1", target_population=1000, rich_proportion=0.0)
    TownParameters(seed="town-1", target_population=1000, rich_proportion=1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_narrative_parameters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_narrative'`

- [ ] **Step 3: Write the package files**

```python
# town_narrative/__init__.py
```

```python
# town_narrative/parameters.py
from dataclasses import dataclass
from typing import Any


@dataclass
class TownParameters:
    seed: Any
    target_population: int
    area_per_resident_multiplier: float = 1.0
    density_multiplier: float = 1.0
    rich_proportion: float = 0.05

    def __post_init__(self) -> None:
        if self.target_population <= 0:
            raise ValueError("target_population must be positive")
        if self.area_per_resident_multiplier <= 0:
            raise ValueError("area_per_resident_multiplier must be positive")
        if self.density_multiplier <= 0:
            raise ValueError("density_multiplier must be positive")
        if not (0.0 <= self.rich_proportion <= 1.0):
            raise ValueError("rich_proportion must be between 0.0 and 1.0")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_narrative_parameters.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_narrative/__init__.py town_narrative/parameters.py tests/test_narrative_parameters.py
git commit -m "feat: add town_narrative package scaffolding and TownParameters"
```

---

## Task 2: `compute_town_bounds` gains `area_per_resident_multiplier`

**Files:**
- Modify: `town_shaper/generate.py:15-19`
- Test: `tests/test_generate.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: `compute_town_bounds(target_population: int, area_per_resident_multiplier: float = 1.0) -> Tuple[float, float, float, float]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_generate.py`:

```python
def test_compute_town_bounds_scales_with_area_multiplier_independent_of_population():
    baseline = compute_town_bounds(target_population=1000)
    doubled = compute_town_bounds(target_population=1000, area_per_resident_multiplier=2.0)
    baseline_area = (baseline[2] - baseline[0]) * (baseline[3] - baseline[1])
    doubled_area = (doubled[2] - doubled[0]) * (doubled[3] - doubled[1])
    assert doubled_area == pytest.approx(baseline_area * 2.0)


def test_compute_town_bounds_default_multiplier_matches_no_multiplier():
    assert compute_town_bounds(target_population=1000) == compute_town_bounds(
        target_population=1000, area_per_resident_multiplier=1.0
    )
```

Add `import pytest` to the top of `tests/test_generate.py` (it currently has no top-level blank-line-separated third-party import block — insert it as the first import, before `import time`, matching the `import <stdlib>` then blank line then `import pytest` then blank line then `from town_shaper...` ordering used in `tests/test_districts.py`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_generate.py -v -k area_multiplier`
Expected: FAIL with `TypeError: compute_town_bounds() got an unexpected keyword argument 'area_per_resident_multiplier'`

- [ ] **Step 3: Modify the implementation**

Replace `town_shaper/generate.py` lines 15-19 with:

```python
def compute_town_bounds(
    target_population: int, area_per_resident_multiplier: float = 1.0
) -> Tuple[float, float, float, float]:
    area = target_population * AREA_PER_RESIDENT * area_per_resident_multiplier
    side = math.sqrt(area)
    half = side / 2.0
    return (-half, -half, half, half)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_generate.py -v`
Expected: PASS (all tests in the file, including the two new ones and the pre-existing `test_compute_town_bounds_grows_with_population`)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/generate.py tests/test_generate.py
git commit -m "feat: promote AREA_PER_RESIDENT to an optional multiplier parameter"
```

---

## Task 3: `fill_district_buildings` gains `density_multiplier`

**Files:**
- Modify: `town_shaper/buildings.py:82-125`
- Test: `tests/test_buildings.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: `fill_district_buildings(district, town_seed, next_building_id: int, target_population: int = 0, density_multiplier: float = 1.0) -> List[Building]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_buildings.py`:

```python
def test_fill_district_buildings_higher_density_multiplier_increases_building_count():
    district = _square_district(ZoneType.POOR_RESIDENTIAL, side=200.0)
    baseline = fill_district_buildings(district, ("town", 1), next_building_id=0)
    denser = fill_district_buildings(district, ("town", 1), next_building_id=0, density_multiplier=2.0)
    assert len(denser) > len(baseline)


def test_fill_district_buildings_lower_density_multiplier_increases_spacing():
    from town_shaper.buildings import MIN_BUILDING_SPACING

    district = _square_district(ZoneType.POOR_RESIDENTIAL, side=200.0)
    sparse = fill_district_buildings(district, ("town", 1), next_building_id=0, density_multiplier=0.5)
    expected_min_spacing = MIN_BUILDING_SPACING[ZoneType.POOR_RESIDENTIAL] / 0.5

    for i, a in enumerate(sparse):
        for b in sparse[i + 1:]:
            assert distance((a.x, a.y), (b.x, b.y)) >= expected_min_spacing


def test_fill_district_buildings_default_density_multiplier_matches_previous_behavior():
    district = _square_district(ZoneType.MERCHANT, side=100.0)
    baseline = fill_district_buildings(district, ("town", 1), next_building_id=0)
    explicit = fill_district_buildings(district, ("town", 1), next_building_id=0, density_multiplier=1.0)
    assert [(b.id, b.x, b.y, b.building_type) for b in baseline] == \
           [(b.id, b.x, b.y, b.building_type) for b in explicit]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_buildings.py -v -k density_multiplier`
Expected: FAIL with `TypeError: fill_district_buildings() got an unexpected keyword argument 'density_multiplier'`

- [ ] **Step 3: Modify the implementation**

Replace `town_shaper/buildings.py` lines 82-91 (the function signature and the density/spacing/points computation, up through the `poisson_disc_fill` call) with:

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

The rest of the function (from `type_weights = dict(...)` onward) is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_buildings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_shaper/buildings.py tests/test_buildings.py
git commit -m "feat: promote building density/spacing to an optional multiplier parameter"
```

---

## Task 4: `assign_residents` gains `rich_proportion`; retire `SES_PROPORTIONS`

**Files:**
- Modify: `town_shaper/assignment.py:1-15,62-76`
- Test: `tests/test_assignment.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: `assign_residents(town_seed, households: List[Household], districts: List[District], rich_proportion: float = 0.05) -> List[ResidentSlot]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_assignment.py` (add `SES` to the existing `from town_shaper.models import ...` line so it reads `from town_shaper.models import Anchor, Building, District, Household, SES, ZoneType`):

```python
def test_assign_residents_default_rich_proportion_matches_previous_hardcoded_value():
    seed = ("town", 1)
    districts1, households1 = _build_town_pieces(seed, target_population=3000)
    residents_default = assign_residents(seed, households1, districts1)

    districts2, households2 = _build_town_pieces(seed, target_population=3000)
    residents_explicit = assign_residents(seed, households2, districts2, rich_proportion=0.05)

    key = lambda r: (r.id, r.household_id, r.ses, r.age_bracket, r.home_building_id, r.workplace_building_id, r.occupation)
    assert [key(r) for r in residents_default] == [key(r) for r in residents_explicit]


def test_assign_residents_high_rich_proportion_produces_majority_rich_residents():
    seed = ("town", 1)
    districts, households = _build_town_pieces(seed, target_population=3000)
    residents = assign_residents(seed, households, districts, rich_proportion=0.9)
    rich_count = sum(1 for r in residents if r.ses == SES.RICH)
    assert rich_count > 0.5 * len(residents)


def test_assign_residents_zero_rich_proportion_produces_no_rich_residents():
    seed = ("town", 1)
    districts, households = _build_town_pieces(seed, target_population=3000)
    residents = assign_residents(seed, households, districts, rich_proportion=0.0)
    assert all(r.ses == SES.POOR for r in residents)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_assignment.py -v -k rich_proportion`
Expected: FAIL with `TypeError: assign_residents() got an unexpected keyword argument 'rich_proportion'`

- [ ] **Step 3: Modify the implementation**

Replace `town_shaper/assignment.py` line 6 (`SES_PROPORTIONS: Dict[SES, float] = {SES.RICH: 0.05, SES.POOR: 0.95}`) — delete it entirely.

Replace lines 14-15:

```python
def _draw_household_ses(rng) -> SES:
    return SES.RICH if rng.random() < SES_PROPORTIONS[SES.RICH] else SES.POOR
```

with:

```python
def _draw_household_ses(rng, rich_proportion: float) -> SES:
    return SES.RICH if rng.random() < rich_proportion else SES.POOR
```

Replace the `assign_residents` signature (line 62) and its `_draw_household_ses` call site (line 75):

```python
def assign_residents(
    town_seed, households: List[Household], districts: List[District], rich_proportion: float = 0.05
) -> List[ResidentSlot]:
```

```python
        ses = _draw_household_ses(rng, rich_proportion)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_assignment.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_shaper/assignment.py tests/test_assignment.py
git commit -m "feat: promote SES_PROPORTIONS to an optional rich_proportion parameter"
```

---

## Task 5: `generate_town` threads all three parameters

**Files:**
- Modify: `town_shaper/generate.py:22-39`
- Test: `tests/test_generate.py` (append)

**Interfaces:**
- Consumes: `compute_town_bounds(target_population, area_per_resident_multiplier=1.0)` (Task 2), `fill_district_buildings(..., density_multiplier=1.0)` (Task 3), `assign_residents(..., rich_proportion=0.05)` (Task 4)
- Produces: `generate_town(seed, target_population: int, area_per_resident_multiplier: float = 1.0, density_multiplier: float = 1.0, rich_proportion: float = 0.05) -> Town`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_generate.py`:

```python
def test_generate_town_defaults_match_previous_hardcoded_behavior():
    town_default = generate_town(("town", 1), target_population=3000)
    town_explicit = generate_town(
        ("town", 1), target_population=3000,
        area_per_resident_multiplier=1.0, density_multiplier=1.0, rich_proportion=0.05,
    )

    resident_key = lambda r: (r.id, r.household_id, r.ses, r.home_building_id, r.workplace_building_id, r.occupation)
    assert [resident_key(r) for r in town_default.residents] == [resident_key(r) for r in town_explicit.residents]

    building_key = lambda b: (b.id, b.x, b.y, b.building_type)
    buildings_default = [building_key(b) for d in town_default.districts for b in d.buildings]
    buildings_explicit = [building_key(b) for d in town_explicit.districts for b in d.buildings]
    assert buildings_default == buildings_explicit


def test_generate_town_area_multiplier_grows_bounds_independent_of_district_count():
    compact = generate_town(("town", 1), target_population=3000, area_per_resident_multiplier=0.5)
    sprawling = generate_town(("town", 1), target_population=3000, area_per_resident_multiplier=2.0)

    compact_area = (compact.bounds[2] - compact.bounds[0]) * (compact.bounds[3] - compact.bounds[1])
    sprawling_area = (sprawling.bounds[2] - sprawling.bounds[0]) * (sprawling.bounds[3] - sprawling.bounds[1])
    assert sprawling_area > compact_area
    assert len(compact.districts) == len(sprawling.districts)


def test_generate_town_density_multiplier_changes_total_building_count():
    sparse = generate_town(("town", 1), target_population=3000, density_multiplier=0.5)
    dense = generate_town(("town", 1), target_population=3000, density_multiplier=2.0)

    sparse_count = sum(len(d.buildings) for d in sparse.districts)
    dense_count = sum(len(d.buildings) for d in dense.districts)
    assert dense_count > sparse_count
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_generate.py -v -k "defaults_match_previous or area_multiplier_grows or density_multiplier_changes"`
Expected: FAIL with `TypeError: generate_town() got an unexpected keyword argument 'area_per_resident_multiplier'`

- [ ] **Step 3: Modify the implementation**

Replace `town_shaper/generate.py` lines 22-39 with:

```python
def generate_town(
    seed, target_population: int,
    area_per_resident_multiplier: float = 1.0,
    density_multiplier: float = 1.0,
    rich_proportion: float = 0.05,
) -> Town:
    bounds = compute_town_bounds(target_population, area_per_resident_multiplier)

    anchors = place_anchors(seed, target_population, bounds)
    districts = build_districts(anchors, bounds)

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
    return town
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_generate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_shaper/generate.py tests/test_generate.py
git commit -m "feat: thread area/density/richness parameters through generate_town"
```

---

## Task 6: `generation_parameters` table

**Files:**
- Modify: `town_db/schema.py`
- Test: `tests/test_db_schema.py` (modify)

**Interfaces:**
- Consumes: nothing new
- Produces: a `generation_parameters` table in `SCHEMA_SQL`, created by the existing `create_schema(conn)`

- [ ] **Step 1: Write the failing tests**

In `tests/test_db_schema.py`, add `"generation_parameters"` to the `EXPECTED_TABLES` set (so `test_create_schema_creates_every_table` covers it), and append:

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

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: FAIL — `test_create_schema_creates_every_table` fails its subset assertion, and `test_generation_parameters_accepts_a_row` fails with `sqlite3.OperationalError: no such table: generation_parameters`

- [ ] **Step 3: Modify the implementation**

In `town_db/schema.py`, append a new `CREATE TABLE` statement to `SCHEMA_SQL`, immediately after the existing `military_service` table definition and before the closing `"""`:

```sql

CREATE TABLE generation_parameters (
    seed TEXT NOT NULL,
    target_population INTEGER NOT NULL,
    area_per_resident_multiplier REAL NOT NULL,
    density_multiplier REAL NOT NULL,
    rich_proportion REAL NOT NULL
);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_db/schema.py tests/test_db_schema.py
git commit -m "feat: add generation_parameters table"
```

---

## Task 7: `generate_town_database` threads the three parameters

**Files:**
- Modify: `town_db/generate.py:26-36`
- Test: `tests/test_db_generate.py` (append)

**Interfaces:**
- Consumes: `generate_town(seed, target_population, area_per_resident_multiplier=1.0, density_multiplier=1.0, rich_proportion=0.05)` (Task 5)
- Produces: `generate_town_database(seed, target_population, db_path, year_start=DEFAULT_YEAR_START, race_weights=RACE_WEIGHTS, intermarriage_rate=DEFAULT_INTERMARRIAGE_RATE, birth_rate=DEFAULT_BIRTH_RATE, death_rate_by_age=DEFAULT_DEATH_RATE_BY_AGE, area_per_resident_multiplier: float = 1.0, density_multiplier: float = 1.0, rich_proportion: float = 0.05) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db_generate.py`:

```python
def test_generate_town_database_default_new_parameters_match_previous_behavior(tmp_path):
    db_path_a = str(tmp_path / "a.db")
    db_path_b = str(tmp_path / "b.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_a)
    generate_town_database(
        ("town", 1), target_population=1500, db_path=db_path_b,
        area_per_resident_multiplier=1.0, density_multiplier=1.0, rich_proportion=0.05,
    )

    conn_a = sqlite3.connect(db_path_a)
    conn_b = sqlite3.connect(db_path_b)
    for table in ["residents", "buildings"]:
        rows_a = conn_a.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        rows_b = conn_b.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        assert rows_a == rows_b


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

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_generate.py -v -k "default_new_parameters or threads_area_multiplier"`
Expected: FAIL with `TypeError: generate_town_database() got an unexpected keyword argument 'area_per_resident_multiplier'`

- [ ] **Step 3: Modify the implementation**

Replace `town_db/generate.py` lines 26-36 with:

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
    rich_proportion: float = 0.05,
) -> None:
    town = generate_town(
        seed, target_population,
        area_per_resident_multiplier=area_per_resident_multiplier,
        density_multiplier=density_multiplier,
        rich_proportion=rich_proportion,
    )
```

(Only the signature and the `generate_town(...)` call change — every line after it in the function body is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_generate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_db/generate.py tests/test_db_generate.py
git commit -m "feat: thread area/density/richness parameters through generate_town_database"
```

---

## Task 8: `town_narrative.generate.generate_town_from_parameters`

**Files:**
- Create: `town_narrative/generate.py`
- Test: `tests/test_narrative_generate.py`

**Interfaces:**
- Consumes: `TownParameters` (Task 1), `town_db.generate.generate_town_database(..., area_per_resident_multiplier, density_multiplier, rich_proportion)` (Task 7), `town_db.schema.connect` (existing), `generation_parameters` table (Task 6)
- Produces: `generate_town_from_parameters(params: TownParameters, db_path: str) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_narrative_generate.py
import sqlite3

from town_narrative.generate import generate_town_from_parameters
from town_narrative.parameters import TownParameters


def test_generate_town_from_parameters_creates_a_populated_db(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(seed=("town", 1), target_population=1500)
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    resident_count = conn.execute("SELECT COUNT(*) FROM residents").fetchone()[0]
    assert resident_count > 0


def test_generate_town_from_parameters_records_one_generation_parameters_row(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(
        seed=("town", 1), target_population=1500,
        area_per_resident_multiplier=1.5, density_multiplier=0.7, rich_proportion=0.12,
    )
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT seed, target_population, area_per_resident_multiplier, density_multiplier, rich_proportion "
        "FROM generation_parameters"
    ).fetchall()
    assert rows == [("('town', 1)", 1500, 1.5, 0.7, 0.12)]


def test_generate_town_from_parameters_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(seed=("town", 1), target_population=1500)
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_narrative_generate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_narrative.generate'`

- [ ] **Step 3: Write the implementation**

```python
# town_narrative/generate.py
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
    )

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO generation_parameters (seed, target_population, area_per_resident_multiplier, "
        "density_multiplier, rich_proportion) VALUES (?, ?, ?, ?, ?)",
        (str(params.seed), params.target_population, params.area_per_resident_multiplier,
         params.density_multiplier, params.rich_proportion),
    )
    conn.commit()
    conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_narrative_generate.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS for every test (152 pre-existing + this plan's new tests)

- [ ] **Step 6: Commit**

```bash
git add town_narrative/generate.py tests/test_narrative_generate.py
git commit -m "feat: add generate_town_from_parameters orchestrator"
```

---

## Task 9: Narrative-mapping reference doc and Claude Code skill

**Files:**
- Create: `docs/narrative-town-parameters.md`
- Create: `.claude/skills/generate-town-from-narrative/SKILL.md`

**Interfaces:**
- Consumes: `TownParameters` (Task 1), `generate_town_from_parameters` (Task 8)
- Produces: agent-neutral reference documentation, plus a Claude-Code-specific invocable skill wrapping it

- [ ] **Step 1: Write the reference doc**

```markdown
# Narrative → Town Parameters

Reference for mapping narrative town descriptions onto
`town_narrative.parameters.TownParameters` fields. Written to be
agent-neutral: any agent driving town generation from narrative input can
use this table, not just Claude Code (see
`.claude/skills/generate-town-from-narrative/SKILL.md` for the
Claude-Code-specific invocation wrapper around this content).

**Rule: when narrative input doesn't clearly resolve to a value or
range, ask the user directly.** State your recommended default and why,
rather than silently guessing.

## Fields

- **`seed`** — any stable, reproducible value (e.g. the town's name).
  The same seed + parameters always regenerate the same town.
- **`target_population`** — headcount. No narrative-language table below;
  ask directly if not stated numerically or as a clear size descriptor
  ("a small village," "a large city").
- **`area_per_resident_multiplier`** (default `1.0`) — physical town
  footprint, independent of population. "How large the city is,"
  physically, as distinct from headcount — a modest population can be
  sprawled across an old, oversized city, or a huge population packed
  into a small one.
- **`density_multiplier`** (default `1.0`) — how tightly buildings are
  packed within whatever area exists, independent of size. Low density
  at a large size reads as "a small village in a large town." Low
  density at a *small* size can leave some residents unhoused —
  overcrowding/slums, a legitimate narrative outcome, not an error.
- **`rich_proportion`** (default `0.05`) — fraction of households that
  are SES-rich; the rest are poor (there is no third tier). "Richness"
  of the town overall.

## Narrative language → value

| Narrative language | Field | Suggested value |
|---|---|---|
| "sprawling", "spread out", physically large | `area_per_resident_multiplier` | 1.5 – 2.5 |
| "compact", "walled", small footprint | `area_per_resident_multiplier` | 0.4 – 0.7 |
| (no size cue) | `area_per_resident_multiplier` | 1.0 (default) |
| "cramped", "crowded", "packed" | `density_multiplier` | 1.3 – 2.0 |
| "sparse", "spread thin", "a village in a large town" | `density_multiplier` | 0.3 – 0.6 |
| (no density cue) | `density_multiplier` | 1.0 (default) |
| "wealthy", "prosperous", "opulent" | `rich_proportion` | 0.15 – 0.3 |
| "poor", "impoverished", "destitute" | `rich_proportion` | 0.01 – 0.03 |
| (no wealth cue) | `rich_proportion` | 0.05 (default) |

These ranges are starting points, open to tuning as they're used against
real campaign input — same spirit as the empirically-set constants
elsewhere in this project (e.g. Town DB's disease/birth-rate constants).
```

- [ ] **Step 2: Write the skill file**

```markdown
---
name: generate-town-from-narrative
description: Generate a new medieval town database from narrative input (a short description or a longer campaign-wiki document) by mapping it onto TownParameters, confirming with the user, then calling town_narrative.generate.generate_town_from_parameters.
---

# Generate Town From Narrative

Use when asked to create a new town/city for a D&D campaign from
narrative input — a short description ("kinda large, sparse, poor
town") or a path to a longer document.

## Procedure

1. **Read the input.** If given a file path, read it in full. If given
   inline text, use it directly.
2. **Map narrative language onto `TownParameters` fields** using
   `docs/narrative-town-parameters.md` as the reference table. Fields
   available today: `seed`, `target_population`,
   `area_per_resident_multiplier`, `density_multiplier`,
   `rich_proportion`.
3. **When the input doesn't clearly resolve a field, don't guess
   silently** — state your recommended default and reasoning, and ask
   the user to confirm or override it.
4. **Present the filled-in parameters to the user before generating**,
   and confirm.
5. **Generate:**

   ```python
   from town_narrative.generate import generate_town_from_parameters
   from town_narrative.parameters import TownParameters

   params = TownParameters(
       seed=<a stable seed derived from the campaign/town name>,
       target_population=<int>,
       area_per_resident_multiplier=<float>,
       density_multiplier=<float>,
       rich_proportion=<float>,
   )
   generate_town_from_parameters(params, db_path="<destination path>.db")
   ```

See `docs/narrative-town-parameters.md` for the full mapping table and
the reasoning behind each field.
```

- [ ] **Step 3: Verify both files exist and the doc's table matches the plan**

Run: `python -c "import pathlib; assert pathlib.Path('docs/narrative-town-parameters.md').exists(); assert pathlib.Path('.claude/skills/generate-town-from-narrative/SKILL.md').exists(); print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add docs/narrative-town-parameters.md .claude/skills/generate-town-from-narrative/SKILL.md
git commit -m "docs: add narrative-to-parameters mapping guide and Claude Code skill"
```
