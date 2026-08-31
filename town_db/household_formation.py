# town_db/household_formation.py
from datetime import date
from typing import Dict, List, Optional, Tuple

from town_shaper.seeding import rng_for

from town_db.ages import ADULT_AGE_RANGE, age_on
from town_db.names import draw_surname

HOUSEHOLD_FORMATION_RATE = 0.15


def _movers_and_spouse_pool(
    conn, year_start: date
) -> Tuple[List[Tuple[int, int, str]], List[Tuple[int, int, str]]]:
    """Splits living adults into (movers, spouse_pool).

    A household's first two adults (by id) are its founding couple, per
    town_relationships/family.py's own positional definition of spouse -- never eligible for
    either role. Movers are a household's 3rd+ adult: unmarried residents who roll the
    formation-rate dice each year to decide whether they move out. The spouse pool is who a
    mover can pair with -- other movers, plus any adult living alone (household size 1), who is
    unmarried by the same definition but isn't a "mover" since there's no one left behind for
    them to move out from."""
    rows = conn.execute(
        "SELECT id, household_id, race, birth_date FROM residents WHERE death_date IS NULL "
        "ORDER BY household_id, id"
    ).fetchall()

    adults_by_household: Dict[int, List[Tuple[int, str]]] = {}
    for resident_id, household_id, race, birth_date_str in rows:
        if age_on(date.fromisoformat(birth_date_str), year_start) < ADULT_AGE_RANGE[0]:
            continue
        adults_by_household.setdefault(household_id, []).append((resident_id, race))

    movers: List[Tuple[int, int, str]] = []
    spouse_pool: List[Tuple[int, int, str]] = []
    for household_id, adults in adults_by_household.items():
        if len(adults) == 1:
            resident_id, race = adults[0]
            spouse_pool.append((resident_id, household_id, race))
        else:
            for resident_id, race in adults[2:]:
                movers.append((resident_id, household_id, race))
                spouse_pool.append((resident_id, household_id, race))
    return movers, spouse_pool


def _vacant_home_building(conn) -> Optional[int]:
    row = conn.execute(
        "SELECT b.id FROM buildings b LEFT JOIN residents r "
        "ON r.home_building_id = b.id AND r.death_date IS NULL "
        "WHERE b.capacity > 0 GROUP BY b.id HAVING COUNT(r.id) < b.capacity ORDER BY b.id LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def generate_household_formations(conn, seed, year_start: date, year_end: date) -> None:
    rng = rng_for(seed, "db", "household_formation")
    movers, spouse_pool = _movers_and_spouse_pool(conn, year_start)
    paired_this_year: set = set()

    for resident_id, household_id, race in movers:
        if resident_id in paired_this_year:
            continue
        if rng.random() >= HOUSEHOLD_FORMATION_RATE:
            continue

        spouse_candidates = [
            other_id for other_id, other_household_id, _ in spouse_pool
            if other_id != resident_id
            and other_household_id != household_id
            and other_id not in paired_this_year
        ]
        if not spouse_candidates:
            continue
        spouse_id = rng.choice(spouse_candidates)

        destination_building_id = _vacant_home_building(conn)
        if destination_building_id is None:
            continue

        surname = draw_surname(rng, race)
        cursor = conn.execute("INSERT INTO households (family_name, race) VALUES (?, ?)", (surname, race))
        new_household_id = cursor.lastrowid

        conn.execute(
            "UPDATE residents SET household_id = ?, home_building_id = ? WHERE id IN (?, ?)",
            (new_household_id, destination_building_id, resident_id, spouse_id),
        )
        paired_this_year.add(resident_id)
        paired_this_year.add(spouse_id)
