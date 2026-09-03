import time

import pytest

from town_shaper.buildings import fill_district_buildings
from town_shaper.generate import BUILDING_ID_STRIDE, compute_town_bounds, generate_town
from town_shaper.models import Town, ZoneType


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
    from town_shaper.blocks import generate_blocks_and_buildings

    seed = ("town", 1)
    town = generate_town(seed, target_population=3000)

    target_district = town.districts[min(2, len(town.districts) - 1)]
    next_id = target_district.id * BUILDING_ID_STRIDE

    if target_district.zone_type == ZoneType.FARMLAND_EDGE:
        recomputed = fill_district_buildings(target_district, seed, next_building_id=next_id)
    else:
        recomputed, _, _, _, _ = generate_blocks_and_buildings(
            target_district, seed, next_id, 0, 0, target_population=3000
        )

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


def test_generate_town_with_no_magic_prevalence_matches_previous_behavior():
    town_default = generate_town(("town", 1), target_population=3000)
    town_explicit = generate_town(("town", 1), target_population=3000, magic_prevalence=0.0)
    resident_key = lambda r: (r.id, r.household_id, r.ses, r.home_building_id, r.workplace_building_id, r.occupation)
    assert [resident_key(r) for r in town_default.residents] == [resident_key(r) for r in town_explicit.residents]


def test_generate_town_with_magic_prevalence_can_produce_arcane_shops():
    found = False
    for seed_index in range(20):
        town = generate_town(("town", seed_index), target_population=5000, magic_prevalence=0.8)
        all_types = [b.building_type for d in town.districts for b in d.buildings]
        if "arcane_shop" in all_types:
            found = True
            break
    assert found


def test_generate_town_populates_road_network():
    town = generate_town(("town", 1), target_population=3000)

    assert town.road_network is not None
    assert len(town.road_network.nodes) > 0
    assert len(town.road_network.edges) > 0
    # One anchor node per district -- town_shaper.districts.build_districts
    # creates exactly one District per Anchor, same id.
    assert sum(1 for n in town.road_network.nodes if n.kind == "anchor") == len(town.districts)
