from shapely.geometry import Polygon as ShapelyPolygon

from settlemaker_bridge.pipeline import (
    _coastline_rings,
    _reclassify_landlocked_port_districts,
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


def test_coastline_rings_merge_a_river_running_into_the_sea():
    # settlemaker reads the rings even-odd; overlapping rings would turn the
    # river mouth into land.
    sea = WaterFeature(id=0, kind="coastline", polygon=ShapelyPolygon([(0, 0), (10, 0), (10, 10), (0, 10)]))
    river = WaterFeature(id=1, kind="river", polygon=ShapelyPolygon([(8, 4), (20, 4), (20, 6), (8, 6)]))
    rings = _coastline_rings([sea, river])
    assert len(rings) == 1
    assert ShapelyPolygon([(p["x"], p["y"]) for p in rings[0]]).area == 100 + 20
