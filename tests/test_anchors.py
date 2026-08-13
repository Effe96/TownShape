import pytest

from town_shaper.anchors import MIN_ANCHORS, ZONE_PROPORTIONS, compute_anchor_counts, place_anchors
from town_shaper.models import ZoneType


def test_compute_anchor_counts_sums_to_total():
    counts = compute_anchor_counts(target_population=3000)
    assert sum(counts.values()) >= MIN_ANCHORS
    assert set(counts.keys()) == set(ZoneType)


def test_compute_anchor_counts_respects_minimum_for_tiny_towns():
    counts = compute_anchor_counts(target_population=1)
    assert sum(counts.values()) == MIN_ANCHORS


def test_compute_anchor_counts_rejects_nonpositive_population():
    with pytest.raises(ValueError):
        compute_anchor_counts(target_population=0)


def test_compute_anchor_counts_has_at_least_one_of_each_zone_type():
    counts = compute_anchor_counts(target_population=3000)
    for zone_type in ZoneType:
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
