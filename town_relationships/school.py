import json
from typing import Any, Dict, List

from town_relationships.overlap import dates_overlap
from town_relationships.pairs import canonical_pair


def derive_classmate_relationships(school_enrollments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_school: Dict[int, List[Dict[str, Any]]] = {}
    for record in school_enrollments:
        by_school.setdefault(record["school_building_id"], []).append(record)

    relationships: List[Dict[str, Any]] = []
    seen_pairs = set()
    for records in by_school.values():
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                a, b = records[i], records[j]
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
