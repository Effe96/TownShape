import math

import pytest

from town_shaper.anchors import place_anchors
from town_shaper.districts import build_districts
from town_shaper.geometry import point_in_polygon, polygon_area
from town_shaper.models import Anchor, ZoneType


def test_build_districts_requires_at_least_four_anchors():
    anchors = [Anchor(id=i, zone_type=ZoneType.CIVIC, x=float(i), y=0.0) for i in range(3)]
    with pytest.raises(ValueError):
        build_districts(anchors, bounds=(-10.0, -10.0, 10.0, 10.0))


def test_build_districts_partitions_bounding_box_area():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    districts = build_districts(anchors, bounds)

    box_area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
    total_district_area = sum(polygon_area(part) for d in districts for part in d.polygon_parts)
    assert math.isclose(total_district_area, box_area, rel_tol=1e-6)


def test_build_districts_each_polygon_contains_its_own_anchor():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    districts = build_districts(anchors, bounds)

    for district in districts:
        assert len(district.polygon_parts) == 1
        assert point_in_polygon((district.anchor.x, district.anchor.y), district.polygon_parts[0])


def test_build_districts_preserves_zone_type_from_anchor():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    districts = build_districts(anchors, bounds)

    by_id = {d.id: d for d in districts}
    for anchor in anchors:
        assert by_id[anchor.id].zone_type == anchor.zone_type


def test_build_districts_water_polygon_splits_a_district_into_multiple_parts():
    from shapely.geometry import Point, Polygon as ShapelyPolygon

    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    # A thin horizontal band crossing the whole map is virtually guaranteed
    # to bisect at least one district's Voronoi cell.
    water_polygon = ShapelyPolygon([(-100.0, -2.0), (100.0, -2.0), (100.0, 2.0), (-100.0, 2.0)])
    districts = build_districts(anchors, bounds, water_polygon=water_polygon)

    assert any(len(d.polygon_parts) > 1 for d in districts)
    for district in districts:
        for part in district.polygon_parts:
            assert len(part) >= 3
            for point in part:
                assert not water_polygon.contains(Point(point))


def test_build_districts_water_polygon_reduces_total_land_area():
    from shapely.geometry import Polygon as ShapelyPolygon

    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    water_polygon = ShapelyPolygon([(-100.0, -20.0), (100.0, -20.0), (100.0, 20.0), (-100.0, 20.0)])
    districts = build_districts(anchors, bounds, water_polygon=water_polygon)

    total_land_area = sum(polygon_area(part) for d in districts for part in d.polygon_parts)
    box_area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
    assert total_land_area == pytest.approx(box_area - water_polygon.area, rel=1e-3)


def test_build_districts_district_fully_inside_water_produces_no_parts():
    from shapely.geometry import Polygon as ShapelyPolygon

    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    districts_no_water = build_districts(anchors, bounds)
    target = districts_no_water[0]

    # buffer(positive) on a valid polygon always yields a strict superset,
    # so this water polygon is guaranteed to fully cover the target
    # district's own (unchanged, since Voronoi doesn't depend on water) cell.
    water_polygon = ShapelyPolygon(target.polygon_parts[0]).buffer(5.0)
    districts_with_water = build_districts(anchors, bounds, water_polygon=water_polygon)
    rebuilt_target = next(d for d in districts_with_water if d.id == target.id)

    assert rebuilt_target.polygon_parts == []


def test_build_districts_without_water_polygon_matches_previous_behavior():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    with_none = build_districts(anchors, bounds, water_polygon=None)
    without_arg = build_districts(anchors, bounds)
    key = lambda ds: [(d.id, d.polygon_parts) for d in ds]
    assert key(with_none) == key(without_arg)


def test_build_districts_with_realistic_water_never_crashes():
    from shapely.ops import unary_union
    from town_shaper.water import generate_water_features

    bounds = (-100.0, -100.0, 100.0, 100.0)
    for seed_index in range(300):
        seed = ("town", seed_index)
        anchors = place_anchors(seed, 3000, bounds)
        features = generate_water_features(seed, bounds, num_rivers=2, has_coastline=True)
        water_polygon = unary_union([f.polygon for f in features])
        build_districts(anchors, bounds, water_polygon=water_polygon)  # must not raise
