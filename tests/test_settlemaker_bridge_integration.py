import shutil

import pytest

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
    districts, buildings, water_features, svg = generate_via_settlemaker(
        "bridge-integration-test", 3000, num_rivers=1, has_coastline=True, has_port=True,
    )
    assert len(districts) > 0
    assert len(buildings) > 0
    assert len(water_features) == 2
    assert "<svg" in svg


def test_bridge_round_trip_is_deterministic():
    result1 = generate_via_settlemaker("bridge-integration-test", 3000, num_rivers=1, has_coastline=True)
    result2 = generate_via_settlemaker("bridge-integration-test", 3000, num_rivers=1, has_coastline=True)

    districts1, buildings1, _water1, svg1 = result1
    districts2, buildings2, _water2, svg2 = result2

    key = lambda b: (b.id, b.district_id, b.building_type, b.x, b.y, b.footprint)
    assert sorted(map(key, buildings1)) == sorted(map(key, buildings2))
    assert svg1 == svg2
