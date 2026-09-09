from town_shaper.geometry import distance, point_in_polygon, polygon_area


def test_polygon_area_of_unit_square():
    square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert polygon_area(square) == 1.0


def test_point_in_polygon_inside_and_outside():
    square = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    assert point_in_polygon((1.0, 1.0), square) is True
    assert point_in_polygon((3.0, 1.0), square) is False


def test_distance_of_3_4_5_triangle():
    assert distance((0.0, 0.0), (3.0, 4.0)) == 5.0
