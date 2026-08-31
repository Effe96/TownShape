# town_db/job_market.py
from datetime import date
from typing import List, Optional, Tuple

from town_shaper.seeding import rng_for

from town_db.ages import ADULT_AGE_RANGE, age_on
from town_db.succession import primary_occupation_info, promote_apprentice

SES_MATCH_WEIGHT = 3.0


def _vacancies(conn, year_start: date, year_end: date) -> List[Tuple[int, int, str, Optional[str]]]:
    return conn.execute(
        "SELECT r.id, r.workplace_building_id, r.occupation, b.building_type FROM deaths d "
        "JOIN residents r ON r.id = d.resident_id "
        "LEFT JOIN buildings b ON b.id = r.workplace_building_id "
        "WHERE d.death_date >= ? AND d.death_date < ? "
        "AND r.workplace_building_id IS NOT NULL AND r.occupation IS NOT NULL",
        (year_start.isoformat(), year_end.isoformat()),
    ).fetchall()


def _modal_ses_for_occupation(conn, occupation: str) -> Optional[str]:
    rows = conn.execute(
        "SELECT ses, COUNT(*) c FROM residents WHERE occupation = ? AND death_date IS NULL "
        "GROUP BY ses ORDER BY c DESC, ses ASC",
        (occupation,),
    ).fetchall()
    return rows[0][0] if rows else None


def _select_candidate(conn, rng, occupation: str, year_start: date) -> Optional[int]:
    rows = conn.execute(
        "SELECT id, ses, birth_date FROM residents WHERE death_date IS NULL AND occupation IS NULL ORDER BY id"
    ).fetchall()
    candidates = [
        (resident_id, ses) for resident_id, ses, birth_date_str in rows
        if age_on(date.fromisoformat(birth_date_str), year_start) >= ADULT_AGE_RANGE[0]
    ]
    if not candidates:
        return None

    modal_ses = _modal_ses_for_occupation(conn, occupation)
    if modal_ses is None:
        return rng.choice(candidates)[0]

    weights = [SES_MATCH_WEIGHT if ses == modal_ses else 1.0 for _, ses in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0][0]


def fill_job_vacancies(conn, seed, year_start: date, year_end: date) -> None:
    rng = rng_for(seed, "db", "job_market")

    for _deceased_id, workplace_id, occupation, building_type in _vacancies(conn, year_start, year_end):
        is_primary, apprentice_occupation = primary_occupation_info(building_type, occupation)
        promoted_id = promote_apprentice(conn, workplace_id, apprentice_occupation, occupation) if is_primary else None
        if promoted_id is not None:
            continue

        candidate_id = _select_candidate(conn, rng, occupation, year_start)
        if candidate_id is None:
            continue
        conn.execute(
            "UPDATE residents SET occupation = ?, workplace_building_id = ? WHERE id = ?",
            (occupation, workplace_id, candidate_id),
        )
