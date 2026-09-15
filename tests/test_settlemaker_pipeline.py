from shapely.geometry import Polygon as ShapelyPolygon

from settlemaker_bridge.pipeline import _center_of_bounds, _translate_water_features
from town_shaper.models import WaterFeature

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _water(ring=SQUARE, kind="coastline", feature_id=1):
    return WaterFeature(id=feature_id, kind=kind, polygon=ShapelyPolygon(ring))


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
