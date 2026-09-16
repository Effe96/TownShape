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
    # Regression for a real bug, fixed in two rounds. Round 1 (position
    # only): the real (with-coastline) settlemaker call lays out its burg
    # mesh at a different center than the dry (no-water) call used to scale
    # the water polygon -- median port-to-water distance dropped from ~24.9
    # (11.9% of the town's shorter dimension) to ~4.3 (2.0%), but reusing
    # the dry call's *scale* for the persisted water (17.5% too big on this
    # town) made the water polygon itself overspill onto land. Round 2
    # (scale + clip + reclassify): persisted water is now scaled by the
    # *real* call's own radius and clipped to real district geometry (see
    # test_no_building_ever_ends_up_inside_the_water_polygon below), and
    # PORT districts too far from the corrected water are reclassified (see
    # _reclassify_landlocked_port_districts). Remaining port buildings sit
    # even closer: median ~6.6 (6.3%). 10% is a threshold with real margin
    # on both sides, not tuned to the measured value.
    #
    # 2026-09-16: this test's port_buildings list was non-empty even before
    # build_input.py's harbourSize fix, but only because "gate" wards were
    # then misclassified as PORT too (settlemaker never actually placed a
    # real 'harbour' ward for this seed without harbourSize set -- see
    # build_input.py's doc comment). Now that both bugs are fixed, PORT
    # comes from a genuine harbour ward, with real port buildings in it.
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


def test_no_building_ever_ends_up_inside_the_water_polygon():
    # Regression for the bug round 1 introduced: correctly repositioning
    # water (without also correcting its scale) made an honestly-placed but
    # oversized water polygon swallow real buildings -- 197 of 356 non-port
    # buildings on this exact town, a strictly worse and more visible bug
    # than the original misalignment. Water is now clipped to real district
    # geometry after the real call, so this must be zero regardless of how
    # good or bad the scale/position prediction was for a given town.
    _districts, buildings, water_features, _svg, _local_bounds = generate_via_settlemaker(
        "riverport-demo", 8000, num_rivers=1, has_coastline=True, has_port=True,
    )
    underwater = [
        b for b in buildings
        if any(wf.polygon.contains(Point(b.x, b.y)) for wf in water_features)
    ]
    assert underwater == []
