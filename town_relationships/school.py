import itertools
import json
from datetime import date
from typing import Any, Dict, List, Tuple

from town_relationships.overlap import dates_overlap
from town_relationships.pairs import canonical_pair


def derive_classmate_relationships(
    school_enrollments: List[Dict[str, Any]], residents: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    birth_date_by_resident = {r["id"]: r["birth_date"] for r in residents}

    by_cohort: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    for record in school_enrollments:
        birth_date = birth_date_by_resident.get(record["resident_id"])
        if birth_date is None:
            continue
        age_at_start = date.fromisoformat(record["start_date"]).year - date.fromisoformat(birth_date).year
        cohort_key = (record["school_building_id"], age_at_start)
        by_cohort.setdefault(cohort_key, []).append(record)

    relationships: List[Dict[str, Any]] = []
    seen_pairs = set()
    for records in by_cohort.values():
        for a, b in itertools.combinations(records, 2):
            if a["resident_id"] == b["resident_id"]:
                continue
            overlap = dates_overlap(a["start_date"], a["end_date"], b["start_date"], b["end_date"])
            if overlap is None:
                continue
            lo, hi = sorted((a["resident_id"], b["resident_id"]))
            if (lo, hi) in seen_pairs:
                continue
            seen_pairs.add((lo, hi))
            overlap_start, overlap_end = overlap
            detail = json.dumps({"overlap_start": overlap_start, "overlap_end": overlap_end})
            relationships.append(canonical_pair(a["resident_id"], b["resident_id"], "classmate", detail))
    return relationships
