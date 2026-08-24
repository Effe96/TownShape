from datetime import date
from typing import Any, Dict, List

from town_relationships.pairs import canonical_pair

ADULT_MIN_AGE = 18


def _age_on(birth_date: date, on_date: date) -> int:
    age = on_date.year - birth_date.year
    if (on_date.month, on_date.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def derive_family_relationships(
    residents: List[Dict[str, Any]], births: List[Dict[str, Any]], reference_date: date
) -> List[Dict[str, Any]]:
    residents_by_household: Dict[int, List[Dict[str, Any]]] = {}
    for resident in sorted(residents, key=lambda r: r["id"]):
        residents_by_household.setdefault(resident["household_id"], []).append(resident)

    birth_parents: Dict[int, List[int]] = {}
    for birth in births:
        parents = [birth["mother_resident_id"]]
        if birth["father_resident_id"] is not None:
            parents.append(birth["father_resident_id"])
        birth_parents[birth["child_resident_id"]] = parents

    relationships: List[Dict[str, Any]] = []

    for members in residents_by_household.values():
        adults, children = [], []
        for member in members:
            birth_date = date.fromisoformat(member["birth_date"])
            (adults if _age_on(birth_date, reference_date) >= ADULT_MIN_AGE else children).append(member)

        parent_candidates = adults[:2]
        extra_adults = adults[2:]

        if len(parent_candidates) == 2:
            relationships.append(
                canonical_pair(parent_candidates[0]["id"], parent_candidates[1]["id"], "spouse")
            )

        # Track which (parent, child) pairs are established via birth records
        asserted_parent_pairs: set = set()

        for child in children:
            if child["id"] in birth_parents:
                for parent_id in birth_parents[child["id"]]:
                    relationships.append({
                        "resident_a_id": parent_id, "resident_b_id": child["id"],
                        "relationship_type": "parent", "detail": None,
                    })
                    asserted_parent_pairs.add((parent_id, child["id"]))
            else:
                for parent in parent_candidates:
                    relationships.append({
                        "resident_a_id": parent["id"], "resident_b_id": child["id"],
                        "relationship_type": "parent", "detail": None,
                    })

        for i in range(len(children)):
            for j in range(i + 1, len(children)):
                relationships.append(canonical_pair(children[i]["id"], children[j]["id"], "sibling"))

        non_extra = parent_candidates + children
        for extra in extra_adults:
            for other in non_extra:
                # Skip household_member if this pair is an asserted parent-child relationship
                if (extra["id"], other["id"]) not in asserted_parent_pairs and (other["id"], extra["id"]) not in asserted_parent_pairs:
                    relationships.append(canonical_pair(extra["id"], other["id"], "household_member"))
        for i in range(len(extra_adults)):
            for j in range(i + 1, len(extra_adults)):
                relationships.append(
                    canonical_pair(extra_adults[i]["id"], extra_adults[j]["id"], "household_member")
                )

    return relationships
