import time

import pytest

from town_shaper.buildings import fill_district_buildings
from town_shaper.generate import BUILDING_ID_STRIDE, compute_town_bounds, generate_town
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

    target_district = town.districts[min(2, len(town.districts) - 1)]
    next_id = target_district.id * BUILDING_ID_STRIDE
    recomputed = fill_district_buildings(target_district, seed, next_building_id=next_id)

    original_ids = [b.id for b in target_district.buildings]
    recomputed_ids = [b.id for b in recomputed]
    assert original_ids == recomputed_ids

    original_types = [b.building_type for b in target_district.buildings]
    recomputed_types = [b.building_type for b in recomputed]
    assert original_types == recomputed_types


def test_generate_town_completes_within_time_budget_at_low_thousands_scale():
    start = time.monotonic()
    generate_town(("town", 1), target_population=3000)
    elapsed = time.monotonic() - start
    assert elapsed < 10.0


def test_generate_town_threads_target_population_into_building_fill():
    # A pop-3000 town (below UNIVERSITY_MIN_POPULATION) must never contain
    # a university, proving target_population reaches fill_district_buildings.
    town = generate_town(("town", 1), target_population=3000)
    all_types = [b.building_type for d in town.districts for b in d.buildings]
    assert "university" not in all_types


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
