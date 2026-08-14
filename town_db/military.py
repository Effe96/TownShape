from datetime import date
from typing import Any, Dict, List

MILITARY_OCCUPATIONS = {"soldier", "guard"}
RANK_BY_OCCUPATION = {"soldier": "soldier", "guard": "guard"}


def generate_military_service(
    resident_rows: List[Dict[str, Any]],
    garrison_building_ids: List[int],
    year_start: date,
) -> List[Dict[str, Any]]:
    garrison_id_set = set(garrison_building_ids)
    records: List[Dict[str, Any]] = []
    for row in resident_rows:
        if row["death_date"] is not None:
            continue
        occupation = row.get("occupation")
        workplace_id = row.get("workplace_building_id")
        if occupation in MILITARY_OCCUPATIONS and workplace_id in garrison_id_set:
            records.append({
                "resident_db_id": row["db_id"],
                "garrison_building_id": workplace_id,
                "rank": RANK_BY_OCCUPATION[occupation],
                "start_date": year_start.isoformat(),
                "end_date": None,
            })
    return records
