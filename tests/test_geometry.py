import math

from town_shaper.geometry import clip_polygon_to_bounds, distance, point_in_polygon, polygon_area


def test_polygon_area_of_unit_square():
    square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert polygon_area(square) == 1.0


def test_point_in_polygon_inside_and_outside():
    square = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    assert point_in_polygon((1.0, 1.0), square) is True
    assert point_in_polygon((3.0, 1.0), square) is False


def test_clip_polygon_to_bounds_clips_overhanging_square():
    square = [(-1.0, -1.0), (3.0, -1.0), (3.0, 3.0), (-1.0, 3.0)]
    bounds = (0.0, 0.0, 2.0, 2.0)
    clipped = clip_polygon_to_bounds(square, bounds)
    assert math.isclose(polygon_area(clipped), 4.0, rel_tol=1e-9)


def test_clip_polygon_fully_outside_bounds_returns_empty():
    triangle = [(10.0, 10.0), (12.0, 10.0), (11.0, 12.0)]
    bounds = (0.0, 0.0, 2.0, 2.0)
    assert clip_polygon_to_bounds(triangle, bounds) == []


def test_distance_of_3_4_5_triangle():
    assert distance((0.0, 0.0), (3.0, 4.0)) == 5.0
