# town_db/simulation.py
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from town_shaper.seeding import rng_for

from town_db.ages import ADULT_AGE_RANGE, age_on
from town_db.generate import YEAR_LENGTH_DAYS
from town_db.household_formation import generate_household_formations
from town_db.job_market import fill_job_vacancies
from town_db.enrollment import generate_school_enrollments
from town_db.military import generate_military_service
from town_db.persistence import (
    insert_births,
    insert_deaths,
    insert_disease_events,
    insert_military_service,
    insert_purchases,
    insert_residents,
    insert_school_enrollments,
    insert_skirmish_events,
    insert_tax_payments,
)
from town_db.purchases import SHOP_BUILDING_TYPES, generate_purchases
from town_db.schema import connect
from town_db.taxes import generate_tax_payments
from town_db.unrest import generate_skirmish_casualties, generate_skirmish_events
from town_db.vital_records import generate_births_and_deaths, generate_disease_events

from town_relationships.generate import derive_relationships


def _age_bracket(age: int) -> str:
    return "child" if age < ADULT_AGE_RANGE[0] else "adult"


def _load_household_rows(conn) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT id, family_name, race FROM households").fetchall()
    return [{"id": r[0], "family_name": r[1], "race": r[2]} for r in rows]


def _load_resident_rows(conn, year_start: date) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT r.id, r.household_id, r.gender, r.race, r.birth_date, r.death_date, r.ses, r.is_noble, "
        "r.home_building_id, r.workplace_building_id, r.occupation, b.zone_type "
        "FROM residents r LEFT JOIN buildings b ON b.id = r.home_building_id"
    ).fetchall()
    result: List[Dict[str, Any]] = []
    for (resident_id, household_id, gender, race, birth_date, death_date, ses, is_noble,
         home_building_id, workplace_building_id, occupation, home_zone_type) in rows:
        age = age_on(date.fromisoformat(birth_date), year_start)
        result.append({
            "db_id": resident_id,
            "household_id": household_id,
            "gender": gender,
            "race": race,
            "birth_date": birth_date,
            "death_date": death_date,
            "ses": ses,
            "is_noble": bool(is_noble),
            "home_building_id": home_building_id,
            "home_zone_type": home_zone_type,
            "workplace_building_id": workplace_building_id,
            "occupation": occupation,
            "age_bracket": _age_bracket(age),
        })
    return result


def _building_ids(conn, building_type: str) -> List[int]:
    return [r[0] for r in conn.execute("SELECT id FROM buildings WHERE building_type = ?", (building_type,)).fetchall()]


def _first_building_id(conn, building_type: str) -> Optional[int]:
    row = conn.execute("SELECT id FROM buildings WHERE building_type = ? ORDER BY id LIMIT 1", (building_type,)).fetchone()
    return row[0] if row else None


def _goods_ids(conn) -> Dict[str, int]:
    return {name: good_id for good_id, name in conn.execute("SELECT id, name FROM goods").fetchall()}


def advance_town(db_path: str, seed, years: int = 1) -> None:
    if years <= 0:
        raise ValueError("years must be a positive integer")

    conn = connect(db_path)
    try:
        # `current_date` collides with SQLite's CURRENT_DATE keyword -- a bare read returns
        # today's date, not the column. Must be quoted. See CONTRACTS.md / LOG.md.
        state_row = conn.execute(
            'SELECT year_start, "current_date", aggression, magic_prevalence FROM town_state WHERE id = 1'
        ).fetchone()
        if state_row is None:
            raise ValueError(f"{db_path} has no town_state row -- was it generated with capability-2 slice 1 or later?")
        original_year_start = date.fromisoformat(state_row[0])
        current_date = date.fromisoformat(state_row[1])
        aggression = state_row[2]
        magic_prevalence = state_row[3]

        for _ in range(years):
            year_start = current_date
            year_end = year_start + timedelta(days=YEAR_LENGTH_DAYS)
            year_index = (year_start - original_year_start).days // YEAR_LENGTH_DAYS
            year_seed = rng_for(seed, "town_state", "year", year_index)

            household_rows = _load_household_rows(conn)
            resident_rows = _load_resident_rows(conn, year_start)

            disease_rows = generate_disease_events(year_seed, year_start)
            insert_disease_events(conn, disease_rows)

            temple_id = _first_building_id(conn, "temple")
            healer_id = _first_building_id(conn, "healer")
            births, deaths, new_resident_rows = generate_births_and_deaths(
                year_seed, household_rows, resident_rows, disease_rows, year_start, temple_id, healer_id,
            )
            insert_residents(conn, new_resident_rows)
            insert_births(conn, births, new_resident_rows)
            insert_deaths(conn, deaths)

            guard_post_id = _first_building_id(conn, "guard_post")
            garrison_id = _first_building_id(conn, "garrison")
            reporting_building_id = guard_post_id if guard_post_id is not None else garrison_id
            skirmish_rows = generate_skirmish_events(year_seed, year_start, aggression)
            insert_skirmish_events(conn, skirmish_rows)
            skirmish_deaths = generate_skirmish_casualties(year_seed, resident_rows, skirmish_rows, reporting_building_id)
            insert_deaths(conn, skirmish_deaths)

            generate_household_formations(conn, year_seed, year_start, year_end)
            fill_job_vacancies(conn, year_seed, year_start, year_end)

            all_household_rows = _load_household_rows(conn)
            all_resident_rows = _load_resident_rows(conn, year_start)

            goods_ids = _goods_ids(conn)
            shop_building_ids = [b_id for bt in SHOP_BUILDING_TYPES for b_id in _building_ids(conn, bt)]
            arcane_shop_building_ids = _building_ids(conn, "arcane_shop")
            blacksmith_building_ids = _building_ids(conn, "blacksmith")
            purchases = generate_purchases(
                year_seed, all_household_rows, all_resident_rows, goods_ids, shop_building_ids, year_start,
                magic_prevalence=magic_prevalence, arcane_shop_building_ids=arcane_shop_building_ids,
                blacksmith_building_ids=blacksmith_building_ids,
            )
            insert_purchases(conn, purchases)

            tax_payments = generate_tax_payments(year_seed, all_household_rows, all_resident_rows, year_start)
            insert_tax_payments(conn, tax_payments)

            school_ids = _building_ids(conn, "school")
            university_ids = _building_ids(conn, "university")
            enrollments = generate_school_enrollments(year_seed, all_resident_rows, school_ids, university_ids, year_start)
            insert_school_enrollments(conn, enrollments)

            garrison_ids = _building_ids(conn, "garrison") + _building_ids(conn, "guard_post")
            military = generate_military_service(all_resident_rows, garrison_ids, year_start)
            insert_military_service(conn, military)

            conn.execute('UPDATE town_state SET "current_date" = ? WHERE id = 1', (year_end.isoformat(),))
            conn.commit()

            derive_relationships(db_path, reference_date=year_end)
            current_date = year_end
    finally:
        conn.close()
