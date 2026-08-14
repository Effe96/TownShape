from datetime import date
from typing import Any, Dict, List

from town_shaper.seeding import rng_for

SCHOOL_AGE_RANGE = (6, 12)
UNIVERSITY_AGE_RANGE = (18, 22)
UNIVERSITY_ENROLLMENT_CHANCE = 0.3


def generate_school_enrollments(
    seed,
    resident_rows: List[Dict[str, Any]],
    school_building_ids: List[int],
    university_building_ids: List[int],
    year_start: date,
) -> List[Dict[str, Any]]:
    rng = rng_for(seed, "db", "enrollment")
    enrollments: List[Dict[str, Any]] = []

    for row in resident_rows:
        if row["death_date"] is not None:
            continue
        birth_date = date.fromisoformat(row["birth_date"])
        age = year_start.year - birth_date.year

        if school_building_ids and SCHOOL_AGE_RANGE[0] <= age <= SCHOOL_AGE_RANGE[1]:
            enrollments.append({
                "resident_db_id": row["db_id"],
                "school_building_id": rng.choice(school_building_ids),
                "enrollment_type": "school",
                "start_date": year_start.isoformat(),
                "end_date": None,
            })
        elif university_building_ids and UNIVERSITY_AGE_RANGE[0] <= age <= UNIVERSITY_AGE_RANGE[1]:
            if rng.random() < UNIVERSITY_ENROLLMENT_CHANCE:
                enrollments.append({
                    "resident_db_id": row["db_id"],
                    "school_building_id": rng.choice(university_building_ids),
                    "enrollment_type": "university",
                    "start_date": year_start.isoformat(),
                    "end_date": None,
                })

    return enrollments
