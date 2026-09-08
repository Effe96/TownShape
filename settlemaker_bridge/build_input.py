"""Build settlemaker's AzgaarBurgInput from a TownParameters-like input.

Per the design's Data Model / Risks sections: fields TownShape has no
current equivalent for (`culture`, `elevation`, `temperature`, `trade`,
`biome`, `citadel`, `roadBearings`) are left unset rather than guessed --
`town_narrative` gaining opinions about them is a separate, future
proposal.
"""
from typing import Any, Dict


def build_azgaar_burg_input(
    seed: Any,
    target_population: int,
    has_port: bool = False,
) -> Dict[str, Any]:
    """The population/port-derived fields only -- coastlineGeometry is
    attached separately by pipeline.generate_via_settlemaker, once the
    settlement's local coordinate scale is known (see that module's
    docstring for why this can't be computed up front)."""
    return {
        "name": str(seed),
        "population": target_population,
        "port": has_port,
        "citadel": False,
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
