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
