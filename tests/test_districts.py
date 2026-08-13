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
    total_district_area = sum(polygon_area(d.polygon) for d in districts)
    assert math.isclose(total_district_area, box_area, rel_tol=1e-6)


def test_build_districts_each_polygon_contains_its_own_anchor():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    districts = build_districts(anchors, bounds)

    for district in districts:
        assert point_in_polygon((district.anchor.x, district.anchor.y), district.polygon)


def test_build_districts_preserves_zone_type_from_anchor():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    districts = build_districts(anchors, bounds)

    by_id = {d.id: d for d in districts}
    for anchor in anchors:
        assert by_id[anchor.id].zone_type == anchor.zone_type
