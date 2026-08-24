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
        for i in range(len(resident_ids)):
            for j in range(i + 1, len(resident_ids)):
                relationships.append(canonical_pair(resident_ids[i], resident_ids[j], "coworker"))
    return relationships
