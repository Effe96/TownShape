from shapely.geometry import LineString, Polygon

from town_shaper.seeding import rng_for
from town_shaper.water import RIVER_WIDTH, _EDGES, _point_on_edge, generate_water_features


def test_generate_water_features_returns_empty_list_with_no_water_requested():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    features = generate_water_features(("town", 1), bounds, num_rivers=0, has_coastline=False)
    assert features == []


def test_generate_water_features_river_count_matches_num_rivers():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    features = generate_water_features(("town", 1), bounds, num_rivers=3, has_coastline=False)
    assert [f.kind for f in features] == ["river", "river", "river"]
    assert [f.id for f in features] == [0, 1, 2]


def test_generate_water_features_coastline_adds_exactly_one_feature():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    features = generate_water_features(("town", 1), bounds, num_rivers=0, has_coastline=True)
    assert [f.kind for f in features] == ["coastline"]


def test_generate_water_features_rivers_and_coastline_combine():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    features = generate_water_features(("town", 1), bounds, num_rivers=2, has_coastline=True)
    assert [f.kind for f in features] == ["river", "river", "coastline"]


def test_generate_water_features_is_deterministic():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    first = generate_water_features(("town", 1), bounds, num_rivers=2, has_coastline=True)
    second = generate_water_features(("town", 1), bounds, num_rivers=2, has_coastline=True)
    for f1, f2 in zip(first, second):
        assert f1.id == f2.id
        assert f1.kind == f2.kind
        assert f1.polygon.equals(f2.polygon)


def test_generate_water_features_rivers_run_on_past_the_bounds_at_both_ends():
    # The map drawn around a town is wider than its bounds, so a river must
    # not stop at their edge: both ends carry on well outside them.
    bounds = (-100.0, -100.0, 100.0, 100.0)
    box = Polygon.from_bounds(*bounds)
    features = generate_water_features(("town", 1), bounds, num_rivers=5, has_coastline=False)
    for feature in features:
        outside = feature.polygon.difference(box)
        assert len(getattr(outside, "geoms", [outside])) == 2  # one piece off each end
        assert all(piece.distance(box) == 0 and piece.length > 2 * 200 for piece in outside.geoms)


def test_generate_water_features_rivers_are_reliably_curved_across_seeds():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    trials = 200
    failures = []
    for seed_index in range(trials):
        seed = ("town", seed_index)
        rng = rng_for(seed, "water", "river", 0)
        start_edge, end_edge = rng.sample(_EDGES, 2)
        start = _point_on_edge(start_edge, bounds, rng)
        end = _point_on_edge(end_edge, bounds, rng)
        straight_strip = LineString([start, end]).buffer(RIVER_WIDTH / 2.0)

        features = generate_water_features(seed, bounds, num_rivers=1, has_coastline=False)
        river_polygon = features[0].polygon
        if not (river_polygon.area > straight_strip.area * 1.03):
            failures.append(seed_index)
    assert not failures, f"{len(failures)}/{trials} seeds produced a near-straight river: {failures[:10]}"


def test_generate_water_features_coastline_fully_covers_one_map_edge():
    from shapely.geometry import LineString

    bounds = (-100.0, -100.0, 100.0, 100.0)
    min_x, min_y, max_x, max_y = bounds
    edges = [
        LineString([(min_x, max_y), (max_x, max_y)]),  # north
        LineString([(min_x, min_y), (max_x, min_y)]),  # south
        LineString([(max_x, min_y), (max_x, max_y)]),  # east
        LineString([(min_x, min_y), (min_x, max_y)]),  # west
    ]
    for seed_index in range(500):
        seed = ("town", seed_index)
        features = generate_water_features(seed, bounds, num_rivers=0, has_coastline=True)
        coastline_polygon = features[0].polygon
        assert any(coastline_polygon.covers(edge) for edge in edges), f"seed {seed_index}: no edge fully covered"


def test_river_bearing_sets_the_entry_side_and_crosses_to_the_opposite_one():
    import math
    from shapely.geometry import Point
    bounds = (-100.0, -100.0, 100.0, 100.0)
    for seed, bearing in [(s, b) for s in range(5) for b in (0.0, 45.0, 90.0, 200.0)]:
        (river,) = generate_water_features(("town", seed), bounds, num_rivers=1, river_bearings=(bearing,))
        rad = math.radians(bearing)
        # Y-up frame: a compass bearing points along (sin, cos).
        entry = (95 * math.sin(rad), 95 * math.cos(rad))
        assert river.polygon.distance(Point(entry)) < 25
        assert river.polygon.distance(Point(-entry[0], -entry[1])) < 25
        assert river.polygon.distance(Point(0, 0)) < 25  # within a quarter of the half-width of the centre


def test_rivers_beyond_the_bearing_list_stay_random():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    with_bearing = generate_water_features(("town", 1), bounds, num_rivers=2, river_bearings=(45.0,))
    without = generate_water_features(("town", 1), bounds, num_rivers=2)
    assert with_bearing[1].polygon.equals(without[1].polygon)


def test_coastline_has_no_land_holes():
    # The curved strip can bend away from the sea box and enclose a sliver
    # of land, drawn as a road-like band in the sea.
    for seed in range(40):
        (coast,) = generate_water_features(seed, (-100.0, -100.0, 100.0, 150.0), has_coastline=True)
        assert not list(coast.polygon.interiors)
