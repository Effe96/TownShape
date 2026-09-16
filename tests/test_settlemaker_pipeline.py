from shapely.geometry import Polygon as ShapelyPolygon

from settlemaker_bridge.pipeline import (
    _center_of_bounds,
    _clip_water_to_land,
    _reclassify_landlocked_port_districts,
    _translate_water_features,
)
from town_shaper.models import Anchor, Building, District, WaterFeature, ZoneType

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _water(ring=SQUARE, kind="coastline", feature_id=1):
    return WaterFeature(id=feature_id, kind=kind, polygon=ShapelyPolygon(ring))


def _district(zone_type, x, y, district_id=1, buildings=None):
    return District(
        id=district_id,
        zone_type=zone_type,
        anchor=Anchor(id=district_id, zone_type=zone_type, x=x, y=y),
        polygon_parts=[[(x - 1, y - 1), (x + 1, y - 1), (x + 1, y + 1), (x - 1, y + 1)]],
        buildings=buildings or [],
    )


def _building(zone_type, building_id=1):
    return Building(
        id=building_id, district_id=1, district_zone_type=zone_type,
        x=0.0, y=0.0, building_type="workshop", capacity=0,
    )


def test_center_of_bounds_is_the_midpoint():
    assert _center_of_bounds({"min_x": -10.0, "max_x": 30.0, "min_y": 0.0, "max_y": 20.0}) == (10.0, 10.0)


def test_translate_water_features_shifts_every_coordinate():
    [translated] = _translate_water_features([_water()], dx=5.0, dy=-3.0)
    assert list(translated.polygon.exterior.coords)[:-1] == [
        (5.0, -3.0), (15.0, -3.0), (15.0, 7.0), (5.0, 7.0),
    ]


def test_translate_water_features_preserves_id_and_kind():
    [translated] = _translate_water_features([_water(kind="river", feature_id=7)], dx=1.0, dy=1.0)
    assert translated.id == 7
    assert translated.kind == "river"


def test_translate_water_features_zero_delta_is_a_no_op_returning_the_same_list():
    features = [_water()]
    assert _translate_water_features(features, dx=0.0, dy=0.0) is features


def test_translate_water_features_handles_holes():
    outer = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)]
    hole = [(5.0, 5.0), (15.0, 5.0), (15.0, 15.0), (5.0, 15.0)]
    feature = WaterFeature(id=1, kind="lake", polygon=ShapelyPolygon(outer, holes=[hole]))

    [translated] = _translate_water_features([feature], dx=2.0, dy=3.0)

    assert list(translated.polygon.exterior.coords)[:-1] == [
        (2.0, 3.0), (22.0, 3.0), (22.0, 23.0), (2.0, 23.0),
    ]
    assert len(translated.polygon.interiors) == 1
    assert list(translated.polygon.interiors[0].coords)[:-1] == [
        (7.0, 8.0), (17.0, 8.0), (17.0, 18.0), (7.0, 18.0),
    ]


def test_translate_water_features_empty_list_returns_empty_list():
    assert _translate_water_features([], dx=1.0, dy=1.0) == []


def test_clip_water_to_land_removes_the_part_over_a_district():
    # Water square (0,0)-(10,10); a district square (4,4)-(6,6) sits
    # entirely inside it -- clipping must remove that inner square.
    water = _water(ring=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    district = _district(ZoneType.CIVIC, x=5.0, y=5.0)  # polygon_parts: (4,4)-(6,6)

    [clipped] = _clip_water_to_land([water], [district])

    assert clipped.polygon.area == 100.0 - 4.0
    assert not clipped.polygon.intersects(ShapelyPolygon(district.polygon_parts[0]).buffer(-0.01))


def test_clip_water_to_land_drops_a_feature_fully_covered_by_land():
    water = _water(ring=[(4.5, 4.5), (5.5, 4.5), (5.5, 5.5), (4.5, 5.5)])  # tiny, inside the district below
    district = _district(ZoneType.CIVIC, x=5.0, y=5.0)  # (4,4)-(6,6), fully covers the water above

    assert _clip_water_to_land([water], [district]) == []


def test_clip_water_to_land_keeps_the_largest_piece_when_split_in_two():
    # A water strip exactly as tall as the district square (y: 4..6) --
    # the district (x: 8..10) cuts all the way across it, genuinely
    # splitting it into a disjoint left piece and right piece. The left one
    # is deliberately narrower so "largest piece" has a real answer to check.
    water = _water(ring=[(0.0, 4.0), (20.0, 4.0), (20.0, 6.0), (0.0, 6.0)])
    district = _district(ZoneType.CIVIC, x=9.0, y=5.0)  # (8,4)-(10,6)

    [clipped] = _clip_water_to_land([water], [district])

    # Right piece (x: 10..20, area 20) is larger than the left piece
    # (x: 0..8, area 16) -- the kept piece must be the right one.
    assert clipped.polygon.area == 20.0
    assert clipped.polygon.bounds[0] == 10.0


def test_clip_water_to_land_no_districts_returns_the_input_unchanged():
    features = [_water()]
    assert _clip_water_to_land(features, []) is features


def test_reclassify_landlocked_port_districts_reclassifies_a_far_district():
    water = _water(ring=[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)])  # near (0,0)
    building = _building(ZoneType.PORT)
    district = _district(ZoneType.PORT, x=100.0, y=100.0, buildings=[building])  # far from water

    _reclassify_landlocked_port_districts([district], [water], max_distance=10.0)

    assert district.zone_type == ZoneType.MERCHANT
    assert district.anchor.zone_type == ZoneType.MERCHANT
    assert building.district_zone_type == ZoneType.MERCHANT


def test_reclassify_landlocked_port_districts_leaves_a_coastal_district_alone():
    water = _water(ring=[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)])
    building = _building(ZoneType.PORT)
    district = _district(ZoneType.PORT, x=3.0, y=1.0, buildings=[building])  # 1 unit from water

    _reclassify_landlocked_port_districts([district], [water], max_distance=10.0)

    assert district.zone_type == ZoneType.PORT
    assert building.district_zone_type == ZoneType.PORT


def test_reclassify_landlocked_port_districts_ignores_non_port_districts():
    water = _water(ring=[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)])
    district = _district(ZoneType.FARMLAND_EDGE, x=1000.0, y=1000.0)

    _reclassify_landlocked_port_districts([district], [water], max_distance=10.0)

    assert district.zone_type == ZoneType.FARMLAND_EDGE


def test_reclassify_landlocked_port_districts_no_water_is_a_no_op():
    district = _district(ZoneType.PORT, x=1000.0, y=1000.0)
    _reclassify_landlocked_port_districts([district], [], max_distance=10.0)
    assert district.zone_type == ZoneType.PORT
