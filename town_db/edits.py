# town_db/edits.py
import random
from datetime import date
from typing import List, Optional, Tuple

from town_db.ages import ADULT_AGE_RANGE, age_on
from town_db.schema import connect
from town_shaper.buildings import JOB_VACANCIES_BY_BUILDING_TYPE

SHOP_LOSS_CEILING_VACANT = 0.65
SHOP_LOSS_CEILING_REPLACED = 0.30
SHOP_LOSS_RAMP_DAYS = 120


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


def _primary_occupation_info(building_type: Optional[str], occupation: Optional[str]) -> Tuple[bool, Optional[str]]:
    if building_type is None:
        return False, None
    roles = JOB_VACANCIES_BY_BUILDING_TYPE.get(building_type, [])
    primary_roles = [name for name, capacity in roles if capacity == 1]
    if len(primary_roles) != 1 or occupation != primary_roles[0]:
        return False, None
    apprentice_roles = [name for name, _ in roles if name != primary_roles[0]]
    return True, (apprentice_roles[0] if apprentice_roles else None)


def _promote_apprentice(conn, workplace_id, apprentice_occupation, primary_occupation) -> Optional[int]:
    if apprentice_occupation is None:
        return None
    candidate = conn.execute(
        "SELECT id FROM residents WHERE workplace_building_id = ? AND occupation = ? AND death_date IS NULL "
        "ORDER BY id LIMIT 1",
        (workplace_id, apprentice_occupation),
    ).fetchone()
    if candidate is None:
        return None
    promoted_id = candidate[0]
    conn.execute("UPDATE residents SET occupation = ? WHERE id = ?", (primary_occupation, promoted_id))
    return promoted_id


def _apply_shop_reputation_ramp(conn, shop_building_id, from_date, ceiling, rng) -> None:
    other_shops = [
        row[0] for row in conn.execute(
            "SELECT b2.id FROM buildings b1 JOIN buildings b2 ON b2.building_type = b1.building_type "
            "WHERE b1.id = ? AND b2.id != ?",
            (shop_building_id, shop_building_id),
        ).fetchall()
    ]
    rows = conn.execute(
        "SELECT id, purchase_date FROM purchases WHERE shop_building_id = ? AND purchase_date >= ? ORDER BY id",
        (shop_building_id, from_date.isoformat()),
    ).fetchall()
    for purchase_id, purchase_date in rows:
        days_since = (date.fromisoformat(purchase_date) - from_date).days
        chance = min(ceiling, days_since / SHOP_LOSS_RAMP_DAYS * ceiling)
        if rng.random() < chance:
            if other_shops:
                dest = rng.choice(other_shops)
                conn.execute("UPDATE purchases SET shop_building_id = ? WHERE id = ?", (dest, purchase_id))
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


def _reporting_building_id(conn) -> Optional[int]:
    temple = conn.execute(
        "SELECT id FROM buildings WHERE building_type = 'temple' ORDER BY id LIMIT 1"
    ).fetchone()
    if temple:
        return temple[0]
    healer = conn.execute(
        "SELECT id FROM buildings WHERE building_type = 'healer' ORDER BY id LIMIT 1"
    ).fetchone()
    return healer[0] if healer else None


def kill_resident(
    db_path: str,
    resident_id: int,
    death_date: date,
    cause: str,
    disease_event_id: Optional[int] = None,
    skirmish_event_id: Optional[int] = None,
    promote_replacement: bool = False,
) -> None:
    conn = connect(db_path)
    try:
        existing_death_date = conn.execute(
            "SELECT death_date FROM residents WHERE id = ?", (resident_id,)
        ).fetchone()[0]
        if existing_death_date is not None:
            raise ValueError(f"resident {resident_id} already has a death_date ({existing_death_date})")

        reporting_building_id = _reporting_building_id(conn)
        conn.execute("UPDATE residents SET death_date = ? WHERE id = ?", (death_date.isoformat(), resident_id))
        conn.execute(
            "INSERT INTO deaths (resident_id, death_date, cause, disease_event_id, skirmish_event_id, reported_by_building_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (resident_id, death_date.isoformat(), cause, disease_event_id, skirmish_event_id, reporting_building_id),
        )

        workplace_id, occupation, building_type = conn.execute(
            "SELECT r.workplace_building_id, r.occupation, b.building_type FROM residents r "
            "LEFT JOIN buildings b ON b.id = r.workplace_building_id WHERE r.id = ?",
            (resident_id,),
        ).fetchone()

        is_primary, apprentice_occupation = _primary_occupation_info(building_type, occupation)
        promoted_id = None
        if is_primary and promote_replacement:
            promoted_id = _promote_apprentice(conn, workplace_id, apprentice_occupation, occupation)

        conn.execute("UPDATE residents SET workplace_building_id = NULL WHERE id = ?", (resident_id,))

        rng = random.Random(f"kill-resident-{resident_id}-{death_date.isoformat()}")
        _reassign_or_delete_buyer_purchases(conn, resident_id, death_date, None, rng)

        if is_primary:
            shop_rng = random.Random(f"kill-resident-shop-ramp-{resident_id}-{death_date.isoformat()}")
            ceiling = SHOP_LOSS_CEILING_REPLACED if promoted_id is not None else SHOP_LOSS_CEILING_VACANT
            _apply_shop_reputation_ramp(conn, workplace_id, death_date, ceiling, shop_rng)

        conn.execute(
            "DELETE FROM tax_payments WHERE resident_id = ? AND payment_date >= ?",
            (resident_id, death_date.isoformat()),
        )
        conn.execute(
            "UPDATE military_service SET end_date = ? WHERE resident_id = ? AND end_date IS NULL",
            (death_date.isoformat(), resident_id),
        )
        conn.execute(
            "UPDATE school_enrollments SET end_date = ? WHERE resident_id = ? AND end_date IS NULL",
            (death_date.isoformat(), resident_id),
        )

        conn.commit()
    finally:
        conn.close()


def scope_disease_event(db_path: str, event_id: int, zone_type: str) -> None:
    conn = connect(db_path)
    try:
        conn.execute("UPDATE disease_events SET affected_zone_type = ? WHERE id = ?", (zone_type, event_id))
        conn.commit()
    finally:
        conn.close()


def create_disease_event(
    db_path: str, zone_type: str, start_date: date, end_date: date, severity: float
) -> int:
    conn = connect(db_path)
    try:
        cursor = conn.execute(
            "INSERT INTO disease_events (name, start_date, end_date, affected_zone_type, severity) "
            "VALUES (?, ?, ?, ?, ?)",
            ("an outbreak of fever", start_date.isoformat(), end_date.isoformat(), zone_type, severity),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()
