# town_db/edits.py
import random
from datetime import date
from typing import List, Optional

from town_db.ages import ADULT_AGE_RANGE, age_on
from town_db.schema import connect


def _living_adult_household_members(conn, resident_id: int, on_date: date) -> List[int]:
    household_id = conn.execute(
        "SELECT household_id FROM residents WHERE id = ?", (resident_id,)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT id, birth_date, death_date FROM residents WHERE household_id = ? AND id != ?",
        (household_id, resident_id),
    ).fetchall()

    candidates = []
    for other_id, birth_date_str, other_death_date in rows:
        if other_death_date is not None and other_death_date <= on_date.isoformat():
            continue
        if age_on(date.fromisoformat(birth_date_str), on_date) < ADULT_AGE_RANGE[0]:
            continue
        candidates.append(other_id)
    return candidates


def _reassign_or_delete_buyer_purchases(
    conn, resident_id: int, from_date: date, until_date: Optional[date], rng: random.Random
) -> None:
    # Candidate pool is fixed once at from_date, not re-checked per purchase -- a candidate who
    # dies later in the window stays eligible for the rest of it. Deliberate simplification: exact
    # per-purchase-date liveness would require re-querying per row for marginal realism gain.
    candidates = _living_adult_household_members(conn, resident_id, from_date)

    query = "SELECT id FROM purchases WHERE resident_id = ? AND purchase_date >= ?"
    params: List = [resident_id, from_date.isoformat()]
    if until_date is not None:
        query += " AND purchase_date < ?"
        params.append(until_date.isoformat())

    rows = conn.execute(query, params).fetchall()
    for (purchase_id,) in rows:
        if candidates:
            new_buyer = rng.choice(candidates)
            conn.execute("UPDATE purchases SET resident_id = ? WHERE id = ?", (new_buyer, purchase_id))
        else:
            conn.execute("DELETE FROM purchases WHERE id = ?", (purchase_id,))


def mark_resident_ill(
    db_path: str,
    resident_id: int,
    start_date: date,
    end_date: date,
    severity: float,
    disease_event_id: Optional[int] = None,
) -> None:
    conn = connect(db_path)
    try:
        overlap = conn.execute(
            "SELECT COUNT(*) FROM illnesses WHERE resident_id = ? AND start_date < ? AND end_date > ?",
            (resident_id, end_date.isoformat(), start_date.isoformat()),
        ).fetchone()[0]
        if overlap:
            raise ValueError(f"resident {resident_id} already has an overlapping illness episode")

        conn.execute(
            "INSERT INTO illnesses (resident_id, disease_event_id, start_date, end_date, severity) "
            "VALUES (?, ?, ?, ?, ?)",
            (resident_id, disease_event_id, start_date.isoformat(), end_date.isoformat(), severity),
        )

        rng = random.Random(f"mark-ill-{resident_id}-{start_date.isoformat()}-{end_date.isoformat()}")
        _reassign_or_delete_buyer_purchases(conn, resident_id, start_date, end_date, rng)

        conn.commit()
    finally:
        conn.close()
