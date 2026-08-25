import pytest

from town_shaper.anchors import MIN_ANCHORS, ZONE_PROPORTIONS, compute_anchor_counts, place_anchors
from town_shaper.models import ZoneType


def test_compute_anchor_counts_sums_to_total():
    counts = compute_anchor_counts(target_population=3000)
    assert sum(counts.values()) >= MIN_ANCHORS
    assert set(counts.keys()) == set(ZoneType) - {ZoneType.PORT}


def test_compute_anchor_counts_respects_minimum_for_tiny_towns():
    counts = compute_anchor_counts(target_population=1)
    assert sum(counts.values()) == MIN_ANCHORS


def test_compute_anchor_counts_rejects_nonpositive_population():
    with pytest.raises(ValueError):
        compute_anchor_counts(target_population=0)


def test_compute_anchor_counts_has_at_least_one_of_each_non_port_zone_type():
    # PORT is deliberately excluded from compute_anchor_counts' proportional
    # system -- its anchor (if any) is added separately by place_anchors,
    # always exactly one, only when has_port=True.
    counts = compute_anchor_counts(target_population=3000)
    assert ZoneType.PORT not in counts
    for zone_type in ZoneType:
        if zone_type == ZoneType.PORT:
            continue
        assert counts[zone_type] >= 1


def test_place_anchors_is_deterministic():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors1 = place_anchors(("town", 1), 3000, bounds)
    anchors2 = place_anchors(("town", 1), 3000, bounds)
    assert [(a.id, a.zone_type, a.x, a.y) for a in anchors1] == \
           [(a.id, a.zone_type, a.x, a.y) for a in anchors2]


def test_place_anchors_stays_within_bounds():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    for anchor in anchors:
        assert bounds[0] <= anchor.x <= bounds[2]
        assert bounds[1] <= anchor.y <= bounds[3]


def test_place_anchors_produces_counts_matching_compute_anchor_counts():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    counts = compute_anchor_counts(3000)
    actual_counts = {}
    for anchor in anchors:
        actual_counts[anchor.zone_type] = actual_counts.get(anchor.zone_type, 0) + 1
    assert actual_counts == counts


def test_place_anchors_without_port_has_no_port_anchor():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    assert all(a.zone_type != ZoneType.PORT for a in anchors)


def test_place_anchors_has_port_without_water_raises():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    with pytest.raises(ValueError):
        place_anchors(("town", 1), 3000, bounds, has_port=True)


def test_place_anchors_adds_exactly_one_port_anchor():
    from shapely.geometry import Polygon

    bounds = (-100.0, -100.0, 100.0, 100.0)
    water_polygon = Polygon([(-100.0, -20.0), (100.0, -20.0), (100.0, 20.0), (-100.0, 20.0)])
    anchors = place_anchors(("town", 1), 3000, bounds, water_polygon=water_polygon, has_port=True)
    port_anchors = [a for a in anchors if a.zone_type == ZoneType.PORT]
    assert len(port_anchors) == 1


def test_place_anchors_port_anchor_does_not_change_other_zone_counts():
    from shapely.geometry import Polygon

    bounds = (-100.0, -100.0, 100.0, 100.0)
    water_polygon = Polygon([(-100.0, -20.0), (100.0, -20.0), (100.0, 20.0), (-100.0, 20.0)])
    without_port = place_anchors(("town", 1), 3000, bounds)
    with_port = place_anchors(("town", 1), 3000, bounds, water_polygon=water_polygon, has_port=True)

    without_counts = {}
    for a in without_port:
        without_counts[a.zone_type] = without_counts.get(a.zone_type, 0) + 1
    with_counts = {}
    for a in with_port:
        if a.zone_type == ZoneType.PORT:
            continue
        with_counts[a.zone_type] = with_counts.get(a.zone_type, 0) + 1
    assert without_counts == with_counts


def test_place_anchors_avoids_water_polygon():
    from shapely.geometry import Point, Polygon

    bounds = (-100.0, -100.0, 100.0, 100.0)
    water_polygon = Polygon([(-100.0, -5.0), (100.0, -5.0), (100.0, 5.0), (-100.0, 5.0)])
    anchors = place_anchors(("town", 1), 3000, bounds, water_polygon=water_polygon)
    for anchor in anchors:
        assert not water_polygon.contains(Point(anchor.x, anchor.y))
