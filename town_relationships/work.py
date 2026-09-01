import itertools
from typing import Any, Dict, List

from town_relationships.pairs import canonical_pair


def derive_coworker_relationships(residents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    residents_by_workplace: Dict[int, List[int]] = {}
    for resident in residents:
        workplace_id = resident.get("workplace_building_id")
        if workplace_id is not None:
            residents_by_workplace.setdefault(workplace_id, []).append(resident["id"])

    relationships: List[Dict[str, Any]] = []
    for resident_ids in residents_by_workplace.values():
        resident_ids = sorted(resident_ids)
        for a, b in itertools.combinations(resident_ids, 2):
            relationships.append(canonical_pair(a, b, "coworker"))
    return relationships
