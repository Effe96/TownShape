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
    geojson = {"features": [_ward("administration", SQUARE)]}
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
