from shapely.geometry import LineString

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


def test_generate_water_features_river_polygons_stay_within_bounds():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    features = generate_water_features(("town", 1), bounds, num_rivers=5, has_coastline=False)
    for feature in features:
        minx, miny, maxx, maxy = feature.polygon.bounds
        margin = RIVER_WIDTH  # buffering can push the polygon slightly past the exact edge point
        assert minx >= bounds[0] - margin
        assert miny >= bounds[1] - margin
        assert maxx <= bounds[2] + margin
        assert maxy <= bounds[3] + margin


def test_generate_water_features_river_is_curved_not_straight():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    rng = rng_for(("town", 1), "water", "river", 0)
    start_edge, end_edge = rng.sample(_EDGES, 2)
    start = _point_on_edge(start_edge, bounds, rng)
    end = _point_on_edge(end_edge, bounds, rng)
    straight_strip = LineString([start, end]).buffer(RIVER_WIDTH / 2.0)

    features = generate_water_features(("town", 1), bounds, num_rivers=1, has_coastline=False)
    river_polygon = features[0].polygon

    # A curved path between the same two endpoints sweeps strictly more area
    # than the straight buffered line between them -- this is the "must
    # curve, not be straight" requirement, verified geometrically rather
    # than by inspecting internal waypoints.
    assert river_polygon.area > straight_strip.area * 1.03


def test_generate_water_features_coastline_extends_past_its_chosen_edge():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    features = generate_water_features(("town", 1), bounds, num_rivers=0, has_coastline=True)
    coastline_polygon = features[0].polygon
    minx, miny, maxx, maxy = coastline_polygon.bounds
    extends_past_an_edge = (
        maxx > bounds[2] + 1.0 or minx < bounds[0] - 1.0
        or maxy > bounds[3] + 1.0 or miny < bounds[1] - 1.0
    )
    assert extends_past_an_edge
