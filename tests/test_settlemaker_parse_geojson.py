import pytest

from settlemaker_bridge.parse_geojson import _curate_village_economy, parse_settlemaker_geojson
from town_shaper.buildings import BUILDING_HOME_CAPACITY, JOB_VACANCIES_BY_BUILDING_TYPE
from town_shaper.models import Building, ZoneType

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
    geojson = {"features": [_ward("administration", SQUARE)]}
    districts, _buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert districts[0].polygon_parts == [[tuple(p) for p in SQUARE[:-1]]]


def test_confirmed_ward_mappings():
    for ward_type, expected in [
        ("administration", ZoneType.CIVIC), ("cathedral", ZoneType.CIVIC),
        ("military", ZoneType.CIVIC), ("park", ZoneType.PARK),
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
        _ward("administration", SQUARE), _building("administration", SQUARE, "b1"),
        _poi("temple", "administration", "b1", "p1"),
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


def test_park_ward_infills_buildings_as_garden():
    # Previously folded into ZoneType.CIVIC ("workshop" infill) -- park now
    # gets its own zone and its own infill type, decided 2026-09-15 after
    # a real generated town showed park buildings mislabeled "workshop".
    geojson = {"features": [_ward("park", SQUARE), _building("park", SQUARE, "b1")]}
    districts, buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert districts[0].zone_type == ZoneType.PARK
    assert buildings[0].building_type == "garden"
    # Gardens are decorative -- no residents, no jobs, same treatment "workshop" got.
    assert buildings[0].capacity == 0
    assert buildings[0].vacancies == []


def test_building_footprint_and_centroid():
    geojson = {"features": [_ward("administration", SQUARE), _building("administration", SQUARE, "b1")]}
    _districts, buildings = parse_settlemaker_geojson(geojson, seed="s")
    building = buildings[0]
    assert building.footprint == [tuple(p) for p in SQUARE[:-1]]
    assert building.x == pytest.approx(5.0)
    assert building.y == pytest.approx(5.0)


def test_district_anchor_is_synthesized_at_centroid():
    geojson = {"features": [_ward("administration", SQUARE)]}
    districts, _buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert districts[0].anchor.x == pytest.approx(5.0)
    assert districts[0].anchor.y == pytest.approx(5.0)
    assert districts[0].anchor.zone_type == ZoneType.CIVIC


def test_parse_is_deterministic_for_same_seed():
    geojson = {"features": [
        _ward("administration", SQUARE), _building("administration", SQUARE, "b1"),
        _poi("temple", "administration", "b1", "p1"),
    ]}
    _d1, b1 = parse_settlemaker_geojson(geojson, seed="fixed-seed")
    _d2, b2 = parse_settlemaker_geojson(geojson, seed="fixed-seed")
    assert b1[0].name == b2[0].name


# Village-engine fixtures (settlement_generation_version == "village", settlemaker's
# own VILLAGE_POP_CEILING == 1000 -- see settlemaker/dist/village/village-model.js).
# No ward layer at all; buildings carry `occupancy` instead of a `wardType`/poi-kind
# pair, and poi.kind is drawn from a disjoint, non-economic set (well/stone-circle/
# boathouse -- village/types.d.ts) with no building_id linkage to any building.
def _village_building(ring, occupancy):
    return {
        "type": "Feature",
        "properties": {"layer": "building", "building_id": "bld:x", "occupancy": occupancy},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def _village_poi(kind):
    return {
        "type": "Feature",
        "properties": {"layer": "poi", "poi_id": f"poi:{kind}", "kind": kind},
        "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
    }


def _village_geojson(features):
    return {
        "features": features,
        "metadata": {
            "settlement_generation_version": "village",
            "local_bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 30.0, "max_y": 10.0},
        },
    }


def test_village_buildings_become_a_single_poor_residential_district():
    geojson = _village_geojson([_village_building(SQUARE, 6), _village_building(SQUARE_2, 4)])
    districts, buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert len(districts) == 1
    assert districts[0].zone_type == ZoneType.POOR_RESIDENTIAL
    assert len(buildings) == 2
    assert all(b.building_type == "residence" for b in buildings)
    assert all(b.district_id == districts[0].id for b in buildings)


def test_village_building_capacity_comes_from_occupancy_not_the_fixed_constant():
    geojson = _village_geojson([_village_building(SQUARE, 6), _village_building(SQUARE_2, 4)])
    _districts, buildings = parse_settlemaker_geojson(geojson, seed="s")
    capacities = sorted(b.capacity for b in buildings)
    assert capacities == [4, 6]
    assert BUILDING_HOME_CAPACITY["residence"] != 4  # proves occupancy, not the shared constant, was used


def test_village_buildings_have_no_job_vacancies():
    geojson = _village_geojson([_village_building(SQUARE, 6)])
    _districts, buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert JOB_VACANCIES_BY_BUILDING_TYPE["residence"] == []
    assert buildings[0].vacancies == []


def test_village_pois_are_ignored_not_crashed_on():
    geojson = _village_geojson([
        _village_building(SQUARE, 6), _village_poi("well"), _village_poi("stone-circle"), _village_poi("boathouse"),
    ])
    districts, buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert len(districts) == 1
    assert len(buildings) == 1


def test_village_district_anchor_is_local_bounds_centroid():
    geojson = _village_geojson([_village_building(SQUARE, 6)])
    districts, _buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert districts[0].anchor.x == pytest.approx(15.0)  # (0 + 30) / 2
    assert districts[0].anchor.y == pytest.approx(5.0)   # (0 + 10) / 2


def test_village_with_no_buildings_returns_empty_not_a_phantom_district():
    geojson = _village_geojson([_village_poi("well")])
    districts, buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert districts == []
    assert buildings == []


def _make_houses(n):
    return [
        Building(
            id=i, district_id=0, district_zone_type=ZoneType.POOR_RESIDENTIAL,
            x=0.0, y=0.0, building_type="residence", capacity=6,
        )
        for i in range(n)
    ]


def test_curate_village_economy_below_floor_reclassifies_nothing():
    houses = _make_houses(20)
    _curate_village_economy(houses, population=74, seed="s")
    assert all(b.building_type == "residence" for b in houses)
    assert all(not b.reserved_vacant for b in houses)


def test_curate_village_economy_tavern_tier_reclassifies_exactly_one_tavern():
    houses = _make_houses(20)
    _curate_village_economy(houses, population=150, seed="s")
    types = [b.building_type for b in houses]
    assert types.count("tavern") == 1
    assert types.count("shop") == 0
    assert types.count("residence") == 19


def test_curate_village_economy_shop_tier_reclassifies_tavern_and_shop():
    houses = _make_houses(75)
    _curate_village_economy(houses, population=300, seed="s")
    types = [b.building_type for b in houses]
    assert types.count("tavern") == 1
    assert types.count("shop") == 1
    assert types.count("residence") == 73


def test_curate_village_economy_reclassified_building_has_zero_capacity_and_real_vacancies():
    houses = _make_houses(20)
    _curate_village_economy(houses, population=150, seed="s")
    tavern = next(b for b in houses if b.building_type == "tavern")
    assert tavern.capacity == 0
    assert sorted(v.occupation for v in tavern.vacancies) == ["barkeep", "tavern_staff", "tavern_staff"]
    assert tavern.name is not None


def test_curate_village_economy_reserved_count_matches_population_over_100_floor_1():
    houses = _make_houses(20)
    _curate_village_economy(houses, population=150, seed="s")
    assert sum(1 for b in houses if b.reserved_vacant) == 1

    houses = _make_houses(250)
    _curate_village_economy(houses, population=800, seed="s")
    assert sum(1 for b in houses if b.reserved_vacant) == 8


def test_curate_village_economy_reserved_buildings_are_not_also_reclassified():
    houses = _make_houses(20)
    _curate_village_economy(houses, population=150, seed="s")
    reserved = [b for b in houses if b.reserved_vacant]
    assert all(b.building_type == "residence" for b in reserved)
    assert all(b.capacity == 6 for b in reserved)


def test_curate_village_economy_is_deterministic_for_same_seed():
    houses1 = _make_houses(75)
    houses2 = _make_houses(75)
    _curate_village_economy(houses1, population=300, seed="fixed-seed")
    _curate_village_economy(houses2, population=300, seed="fixed-seed")
    assert [(b.id, b.building_type, b.reserved_vacant) for b in houses1] == \
           [(b.id, b.building_type, b.reserved_vacant) for b in houses2]


def test_curate_village_economy_at_exactly_the_business_floor_gets_a_tavern():
    houses = _make_houses(20)
    _curate_village_economy(houses, population=75, seed="s")
    types = [b.building_type for b in houses]
    assert types.count("tavern") == 1
    assert types.count("shop") == 0


def test_curate_village_economy_just_below_shop_tier_has_no_shop():
    houses = _make_houses(75)
    _curate_village_economy(houses, population=299, seed="s")
    types = [b.building_type for b in houses]
    assert types.count("tavern") == 1
    assert types.count("shop") == 0


def test_curate_village_economy_reserved_count_floor_clamps_when_population_under_100():
    houses = _make_houses(20)
    _curate_village_economy(houses, population=80, seed="s")
    # 80 // 100 == 0 -- without the max(1, ...) floor this would reserve nothing.
    assert sum(1 for b in houses if b.reserved_vacant) == 1


def test_parse_village_geojson_wires_target_population_into_curation():
    features = [_village_building(SQUARE, 6)] + [
        _village_building([[x, 0.0], [x + 10, 0.0], [x + 10, 10.0], [x, 10.0], [x, 0.0]], 6)
        for x in range(20, 20 * 20, 20)  # 19 more houses, 20 total
    ]
    geojson = _village_geojson(features)
    _districts, buildings = parse_settlemaker_geojson(geojson, seed="s", target_population=150)
    assert sum(1 for b in buildings if b.building_type == "tavern") == 1


def test_parse_village_geojson_default_target_population_curates_nothing():
    geojson = _village_geojson([_village_building(SQUARE, 6)])
    _districts, buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert buildings[0].building_type == "residence"
