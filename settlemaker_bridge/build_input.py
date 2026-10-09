"""Build settlemaker's AzgaarBurgInput from a TownParameters-like input.

Per the design's Data Model / Risks sections: fields TownShape has no
current equivalent for (`culture`, `elevation`, `temperature`, `trade`,
`biome`) are left unset rather than guessed. `citadel` and `roadBearings`
come from TownParameters.has_citadel / road_bearings.
"""
from typing import Any, Dict, Sequence

# Settlemaker's own "big city" line (AzgaarBurgInput.coreCapacity's default,
# azgaar-input.d.ts) -- reused here rather than inventing a new threshold.
# harbourSize has no TownParameters equivalent of settlemaker's "major sea
# routes" concept, so population is the only signal available to pick
# 'large' vs 'small' (see harbourSize's own doc comment: "'large' for major
# sea routes + big pop, 'small' otherwise").
LARGE_HARBOUR_MIN_POPULATION = 10_000


def build_azgaar_burg_input(
    seed: Any,
    target_population: int,
    has_port: bool = False,
    has_citadel: bool = False,
    road_bearings: Sequence[float] = (),
) -> Dict[str, Any]:
    """The population/port-derived fields only -- coastlineGeometry is
    attached separately by pipeline.generate_via_settlemaker, once the
    settlement's local coordinate scale is known (see that module's
    docstring for why this can't be computed up front).

    `harbourSize` -- required alongside `port` or settlemaker never places a
    harbour ward at all: `placeHarbour()` (node_modules/settlemaker/dist/
    generator/model.js) no-ops whenever `params.harbourSize == null`, and
    `port: true` alone never sets it (dist/input/azgaar-input.js only
    forwards `burg.harbourSize` when the caller supplies one). Confirmed
    directly: before this fix, a sweep of 14 seed/population combinations
    with `has_port=True` produced zero real 'harbour' wards -- every
    previously-observed "port" building was actually a misclassified 'gate'
    ward (see settlemaker_bridge/parse_geojson.py's WARD_TYPE_TO_ZONE_TYPE
    comment), which masked this bug until that one was fixed."""
    burg: Dict[str, Any] = {
        "name": str(seed),
        "population": target_population,
        "port": has_port,
        # Settlemaker may still drop it if it can't fit one (it reports
        # that as a degraded flag rather than failing).
        "citadel": has_citadel,
        # No TownParameters equivalent yet for any of these three -- default
        # to the walled/plaza/temple look this project's own renderer already
        # assumes (town_db.render.WALLED_ZONE_TYPES draws a wall around civic/
        # merchant/rich_residential/port unconditionally; BUILDING_TYPES_BY_ZONE's
        # civic weights already include a temple at 0.25).
        "walls": True,
        "plaza": True,
        "temple": True,
        "shanty": False,
        "capital": False,
    }
    if road_bearings:
        # Compass degrees, 0 = north, clockwise -- settlemaker's own
        # convention (azgaar-input.js maps a bearing to (sin, -cos) in its
        # Y-down frame, i.e. north is up on the map).
        burg["roadBearings"] = [float(b) for b in road_bearings]
    if has_port:
        burg["harbourSize"] = "large" if target_population >= LARGE_HARBOUR_MIN_POPULATION else "small"
    return burg
