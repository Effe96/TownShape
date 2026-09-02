# tests/test_buildings.py
from town_shaper.buildings import fill_district_buildings, poisson_disc_fill
from town_shaper.geometry import distance, point_in_polygon
from town_shaper.models import Anchor, District, ZoneType
from town_shaper.seeding import rng_for


def _square_district(zone_type, side=40.0, district_id=1):
    anchor = Anchor(id=district_id, zone_type=zone_type, x=side / 2, y=side / 2)
    polygon = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
    return District(id=district_id, zone_type=zone_type, anchor=anchor, polygon_parts=[polygon])


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
        assert point_in_polygon((building.x, building.y), district.polygon_parts[0])
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


def test_fill_district_buildings_names_flavor_types_but_not_homes():
    from town_shaper.buildings import BUILDING_NAME_POOLS

    merchant_district = _square_district(ZoneType.MERCHANT)
    for building in fill_district_buildings(merchant_district, ("town", 1), next_building_id=0):
        assert building.name in BUILDING_NAME_POOLS[building.building_type]

    residential_district = _square_district(ZoneType.POOR_RESIDENTIAL, district_id=2)
    for building in fill_district_buildings(residential_district, ("town", 1), next_building_id=0):
        assert building.building_type == "residence"
        assert building.name is None


def test_fill_district_buildings_is_deterministic():
    district = _square_district(ZoneType.RICH_RESIDENTIAL)
    first = fill_district_buildings(district, ("town", 1), next_building_id=0)
    second = fill_district_buildings(district, ("town", 1), next_building_id=0)
    assert [(b.id, b.x, b.y, b.building_type) for b in first] == \
           [(b.id, b.x, b.y, b.building_type) for b in second]


def test_civic_zone_includes_garrison_and_healer():
    from town_shaper.buildings import BUILDING_TYPES_BY_ZONE
    from town_shaper.models import ZoneType
    civic_types = BUILDING_TYPES_BY_ZONE[ZoneType.CIVIC]
    assert "garrison" in civic_types
    assert "healer" in civic_types
    assert "university" in civic_types


def test_university_never_appears_below_min_population():
    district = _square_district(ZoneType.CIVIC, side=200.0)
    for seed_index in range(20):
        buildings = fill_district_buildings(
            district, ("town", seed_index), next_building_id=0, target_population=1000
        )
        assert all(b.building_type != "university" for b in buildings)


def test_university_can_appear_above_min_population():
    district = _square_district(ZoneType.CIVIC, side=200.0)
    found = False
    for seed_index in range(50):
        buildings = fill_district_buildings(
            district, ("town", seed_index), next_building_id=0, target_population=20000
        )
        if any(b.building_type == "university" for b in buildings):
            found = True
            break
    assert found


def test_garrison_and_healer_create_expected_vacancies():
    from town_shaper.buildings import JOB_VACANCIES_BY_BUILDING_TYPE
    assert JOB_VACANCIES_BY_BUILDING_TYPE["garrison"] == [("soldier", 6)]
    assert JOB_VACANCIES_BY_BUILDING_TYPE["healer"] == [("healer", 1)]
    assert JOB_VACANCIES_BY_BUILDING_TYPE["university"] == [("scholar", 3)]


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


def test_arcane_shop_never_appears_at_zero_magic_prevalence():
    district = _square_district(ZoneType.MERCHANT, side=200.0)
    for seed_index in range(20):
        buildings = fill_district_buildings(district, ("town", seed_index), next_building_id=0)
        assert all(b.building_type != "arcane_shop" for b in buildings)


def test_arcane_shop_appears_more_often_at_higher_magic_prevalence():
    district = _square_district(ZoneType.MERCHANT, side=200.0)
    low_count = 0
    high_count = 0
    trials = 30
    for seed_index in range(trials):
        low_buildings = fill_district_buildings(
            district, ("town", seed_index), next_building_id=0, magic_prevalence=0.05,
        )
        high_buildings = fill_district_buildings(
            district, ("town", seed_index), next_building_id=0, magic_prevalence=0.9,
        )
        low_count += sum(1 for b in low_buildings if b.building_type == "arcane_shop")
        high_count += sum(1 for b in high_buildings if b.building_type == "arcane_shop")
    assert high_count > low_count


def test_arcane_shop_job_vacancies_match_job_table():
    from town_shaper.buildings import JOB_VACANCIES_BY_BUILDING_TYPE
    assert JOB_VACANCIES_BY_BUILDING_TYPE["arcane_shop"] == [("mage", 1), ("apprentice", 2)]


def test_arcane_shop_has_no_home_capacity():
    from town_shaper.buildings import BUILDING_HOME_CAPACITY
    assert "arcane_shop" not in BUILDING_HOME_CAPACITY


def test_fill_district_buildings_default_magic_prevalence_matches_previous_behavior():
    district = _square_district(ZoneType.MERCHANT, side=100.0)
    baseline = fill_district_buildings(district, ("town", 1), next_building_id=0)
    explicit = fill_district_buildings(district, ("town", 1), next_building_id=0, magic_prevalence=0.0)
    assert [(b.id, b.x, b.y, b.building_type) for b in baseline] == \
           [(b.id, b.x, b.y, b.building_type) for b in explicit]


def test_blacksmith_appears_in_merchant_zone():
    district = _square_district(ZoneType.MERCHANT, side=200.0)
    shop_count = 0
    blacksmith_count = 0
    total = 0
    trials = 30
    for seed_index in range(trials):
        buildings = fill_district_buildings(district, ("town", seed_index), next_building_id=0)
        shop_count += sum(1 for b in buildings if b.building_type == "shop")
        blacksmith_count += sum(1 for b in buildings if b.building_type == "blacksmith")
        total += len(buildings)
    assert blacksmith_count > 0
    assert shop_count > blacksmith_count
    # Tighten frequency assertion: blacksmith should appear at ~15% of merchant buildings
    assert 0.12 < blacksmith_count / total < 0.18


def test_blacksmith_does_not_crowd_out_existing_merchant_building_types():
    district = _square_district(ZoneType.MERCHANT, side=200.0)
    seen_types = set()
    for seed_index in range(30):
        buildings = fill_district_buildings(district, ("town", seed_index), next_building_id=0)
        seen_types.update(b.building_type for b in buildings)
    assert {"shop", "tavern", "market_stall", "blacksmith"} <= seen_types


def test_blacksmith_job_vacancies_match_job_table():
    from town_shaper.buildings import JOB_VACANCIES_BY_BUILDING_TYPE
    assert JOB_VACANCIES_BY_BUILDING_TYPE["blacksmith"] == [("blacksmith", 1), ("smith_apprentice", 2)]


def test_blacksmith_has_no_home_capacity():
    from town_shaper.buildings import BUILDING_HOME_CAPACITY
    assert "blacksmith" not in BUILDING_HOME_CAPACITY
