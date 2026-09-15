import shutil

import pytest
from shapely.geometry import Point

from settlemaker_bridge.bridge import BRIDGE_DIR
from settlemaker_bridge.pipeline import generate_via_settlemaker

_BRIDGE_READY = shutil.which("node") is not None and (BRIDGE_DIR / "node_modules" / "settlemaker").is_dir()

pytestmark = pytest.mark.skipif(
    not _BRIDGE_READY,
    reason="node and/or settlemaker_bridge/node_modules/settlemaker not present -- "
           "run `npm install` in settlemaker_bridge/ first (see docs/superpowers/specs/"
           "2026-09-08-settlemaker-integration-design.md's Risks section for a known "
           "sandboxed-npm caveat)",
)


def test_bridge_round_trip_produces_districts_buildings_and_svg():
    districts, buildings, water_features, svg, local_bounds = generate_via_settlemaker(
        "bridge-integration-test", 3000, num_rivers=1, has_coastline=True, has_port=True,
    )
    assert len(districts) > 0
    assert len(buildings) > 0
    assert len(water_features) == 2
    assert "<svg" in svg
    assert "min_x" in local_bounds and "min_y" in local_bounds
    assert "max_x" in local_bounds and "max_y" in local_bounds


def test_bridge_round_trip_is_deterministic():
    result1 = generate_via_settlemaker("bridge-integration-test", 3000, num_rivers=1, has_coastline=True)
    result2 = generate_via_settlemaker("bridge-integration-test", 3000, num_rivers=1, has_coastline=True)

    districts1, buildings1, _water1, svg1, bounds1 = result1
    districts2, buildings2, _water2, svg2, bounds2 = result2

    key = lambda b: (b.id, b.district_id, b.building_type, b.x, b.y, b.footprint)
    assert sorted(map(key, buildings1)) == sorted(map(key, buildings2))
    assert svg1 == svg2
    assert bounds1 == bounds2


def test_port_buildings_end_up_near_the_water_they_were_built_next_to():
    # Regression for a real bug: the real (with-coastline) settlemaker call
    # lays out its burg mesh at a different center than the dry (no-water)
    # call used to scale the water polygon -- water that's only scaled, not
    # re-centered to match, lands tens of units from where port buildings
    # actually are. Measured directly on this exact scenario before the fix:
    # median distance ~24.9 (11.9% of the town's shorter dimension); after:
    # ~4.3 (2.0%). 10% is a threshold with real margin on both sides, not
    # tuned to the measured value.
    districts, buildings, water_features, _svg, local_bounds = generate_via_settlemaker(
        "riverport-demo", 8000, num_rivers=1, has_coastline=True, has_port=True,
    )
    port_buildings = [b for b in buildings if b.district_zone_type.value == "port"]
    assert len(port_buildings) > 0

    distances = sorted(
        min(Point(b.x, b.y).distance(wf.polygon) for wf in water_features)
        for b in port_buildings
    )
    median_distance = distances[len(distances) // 2]

    town_scale = min(
        local_bounds["max_x"] - local_bounds["min_x"],
        local_bounds["max_y"] - local_bounds["min_y"],
    )
    assert median_distance < 0.1 * town_scale
