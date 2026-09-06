import math

from town_shaper.geometry import clip_polygon_by_line, clip_polygon_to_bounds, distance, inset_polygon, jaggify_polygon, point_in_polygon, polygon_area
from town_shaper.seeding import rng_for


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


def test_clip_polygon_by_line_keeps_the_left_half_of_a_square():
    square = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    # Directed line straight up through x=2 -- "left" of (2,0)->(2,4) is x<2.
    left_half = clip_polygon_by_line(square, (2.0, 0.0), (2.0, 4.0))
    assert math.isclose(polygon_area(left_half), 8.0, rel_tol=1e-9)
    for x, _y in left_half:
        assert x <= 2.0 + 1e-9


def test_clip_polygon_by_line_fully_outside_returns_empty():
    triangle = [(10.0, 10.0), (12.0, 10.0), (11.0, 12.0)]
    # Directed line far to the left of the triangle -- nothing is on its left side.
    assert clip_polygon_by_line(triangle, (0.0, -1.0), (0.0, 1.0)) == []


def test_clip_polygon_by_line_two_opposite_halves_sum_to_original_area():
    square = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    left_half = clip_polygon_by_line(square, (2.0, 0.0), (2.0, 4.0))
    right_half = clip_polygon_by_line(square, (2.0, 4.0), (2.0, 0.0))
    assert math.isclose(polygon_area(left_half) + polygon_area(right_half), 16.0, rel_tol=1e-9)


def test_inset_polygon_shrinks_a_square_by_twice_the_distance_per_side():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    result = inset_polygon(square, 2.0)
    assert math.isclose(polygon_area(result), 6.0 * 6.0, rel_tol=1e-9)
    for x, y in result:
        assert 2.0 - 1e-9 <= x <= 8.0 + 1e-9
        assert 2.0 - 1e-9 <= y <= 8.0 + 1e-9


def test_inset_polygon_returns_empty_when_distance_exceeds_the_polygon():
    small_square = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    assert inset_polygon(small_square, 10.0) == []


def test_inset_polygon_zero_distance_returns_the_same_shape():
    triangle = [(0.0, 0.0), (10.0, 0.0), (5.0, 8.0)]
    result = inset_polygon(triangle, 0.0)
    assert math.isclose(polygon_area(result), polygon_area(triangle), rel_tol=1e-9)


def test_inset_polygon_handles_clockwise_winding():
    # CCW-wound square (standard)
    ccw_square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    # CW-wound square (same vertices, opposite direction)
    cw_square = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)]

    distance = 2.0
    ccw_result = inset_polygon(ccw_square, distance)
    cw_result = inset_polygon(cw_square, distance)

    # Both should produce non-empty results
    assert ccw_result != []
    assert cw_result != []

    # Both should produce the same area (6x6 square, area 36)
    assert math.isclose(polygon_area(ccw_result), 6.0 * 6.0, rel_tol=1e-9)
    assert math.isclose(polygon_area(cw_result), 6.0 * 6.0, rel_tol=1e-9)

    # Both results should have all vertices in the same inset bounds
    for x, y in ccw_result + cw_result:
        assert 2.0 - 1e-9 <= x <= 8.0 + 1e-9
        assert 2.0 - 1e-9 <= y <= 8.0 + 1e-9


def test_inset_polygon_handles_near_duplicate_consecutive_vertices():
    # Real-world case from seed ("town", 7): merchant district polygon with
    # floating-point artifact from Sutherland-Hodgman clip producing a
    # near-duplicate vertex (differs by ~3e-15 in x-coordinate).
    # The polygon has area ~9862.7 before inset.
    polygon_with_near_dup = [
        (-10.360584331871463, -26.92005270413165),
        (-66.38493019065697, -8.431743654278169),
        (-113.70976820275692, -150.0),
        (-24.993942322453464, -150.0),
        (-24.993942322453467, -150.0),  # Near-duplicate of previous point
    ]

    result = inset_polygon(polygon_with_near_dup, 2.0)

    # Should return a non-empty result, not collapse due to huge offset vectors
    assert result != []
    # After dedup, the polygon becomes 4 vertices with area ~9037
    assert polygon_area(result) > 8000


def test_inset_polygon_handles_non_convex_l_shape():
    # The old half-plane-intersection implementation was mathematically
    # convex-only, so a non-convex district (routine once water clipping is
    # involved) silently collapsed far inside its true inset: this L has area
    # 1200, its correct 2.0 inset has area 896 (a 36x36 square minus the 20x20
    # notch), and the old code returned 256 -- measured, not estimated.
    l_shape = [(0.0, 0.0), (40.0, 0.0), (40.0, 20.0), (20.0, 20.0), (20.0, 40.0), (0.0, 40.0)]
    result = inset_polygon(l_shape, 2.0)
    assert math.isclose(polygon_area(result), 896.0, rel_tol=1e-9)


def test_jaggify_polygon_preserves_vertex_count_doubling():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    rng = rng_for(("town", 1), "jaggify-test", 1)
    result = jaggify_polygon(square, rng, iterations=2)
    assert len(result) == len(square) * 4  # each iteration doubles vertex count


def test_jaggify_polygon_is_deterministic():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    rng1 = rng_for(("town", 1), "jaggify-test", 2)
    rng2 = rng_for(("town", 1), "jaggify-test", 2)
    assert jaggify_polygon(square, rng1) == jaggify_polygon(square, rng2)


def test_jaggify_polygon_perturbs_at_least_one_vertex_off_the_original_edges():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    rng = rng_for(("town", 1), "jaggify-test", 3)
    result = jaggify_polygon(square, rng, iterations=1, max_offset_fraction=0.3)
    # midpoints are inserted between original vertices -- at least one should
    # have moved off the square's exact boundary (a random offset of 0.0 for
    # every one of 4 edges is not plausible with this rng/seed combination).
    on_boundary = lambda p: p[0] in (0.0, 10.0) or p[1] in (0.0, 10.0)
    assert not all(on_boundary(p) for p in result)


def test_jaggify_polygon_zero_iterations_returns_the_same_shape():
    triangle = [(0.0, 0.0), (10.0, 0.0), (5.0, 8.0)]
    rng = rng_for(("town", 1), "jaggify-test", 4)
    result = jaggify_polygon(triangle, rng, iterations=0)
    assert result == triangle


def test_jaggify_polygon_respects_max_absolute_offset():
    # A huge max_offset_fraction would normally displace midpoints far off
    # the original edge -- max_absolute_offset must clamp that regardless
    # of how large the fractional request is (this is what keeps a
    # jaggified district's own boundary from bleeding past its own inset
    # margin into a neighbouring district).
    square = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    rng = rng_for(("town", 1), "jaggify-test", 5)
    result = jaggify_polygon(square, rng, iterations=1, max_offset_fraction=0.9, max_absolute_offset=1.0)
    original_edges = [
        ((0.0, 0.0), (100.0, 0.0)), ((100.0, 0.0), (100.0, 100.0)),
        ((100.0, 100.0), (0.0, 100.0)), ((0.0, 100.0), (0.0, 0.0)),
    ]

    def distance_to_segment(p, a, b):
        ax, ay = a
        bx, by = b
        px, py = p
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
        cx, cy = ax + t * dx, ay + t * dy
        return math.hypot(px - cx, py - cy)

    # Every inserted midpoint (odd-indexed vertices) must stay within
    # max_absolute_offset of the edge it was displaced from.
    for i in range(1, len(result), 2):
        edge = original_edges[(i - 1) // 2]
        assert distance_to_segment(result[i], *edge) <= 1.0 + 1e-9
