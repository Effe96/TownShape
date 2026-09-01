# town_db/simulation.py
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from town_db.ages import ADULT_AGE_RANGE, age_on
from town_db.economy import add_yearly_income, subtract_yearly_spend
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
    update_household_wealth,
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
    rows = conn.execute("SELECT id, family_name, race, wealth FROM households").fetchall()
    return [{"id": r[0], "family_name": r[1], "race": r[2], "wealth": r[3]} for r in rows]


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


def _building_type_by_id(conn) -> Dict[int, str]:
    return {r[0]: r[1] for r in conn.execute("SELECT id, building_type FROM buildings").fetchall()}


def _append_new_households(conn, household_rows: List[Dict[str, Any]]) -> None:
    """generate_household_formations inserts new households directly via SQL, bypassing this
    in-memory list -- append any the list doesn't know about yet, without touching existing
    entries (which already carry this year's added income, computed above, and must not be
    overwritten by a stale DB re-read of their pre-income wealth). A newly-formed household has
    no wealth of its own yet this year -- its movers' income was already added to their *old*
    households before generate_household_formations ran -- so it starts at the schema default
    (0.0), same as any other freshly-inserted household row."""
    known_ids = {h["id"] for h in household_rows}
    for row in conn.execute("SELECT id, family_name, race, wealth FROM households").fetchall():
        if row[0] not in known_ids:
            household_rows.append({"id": row[0], "family_name": row[1], "race": row[2], "wealth": row[3]})


def _residents_with_open_span(conn, table: str) -> set:
    return {
        row[0] for row in conn.execute(f"SELECT resident_id FROM {table} WHERE end_date IS NULL").fetchall()
    }


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
            # A plain hashable value, not an rng_for(...) Random instance -- every downstream
            # generator treats this as a base seed and re-derives via its own rng_for(seed, ...)
            # call, which hashes repr(seed). A Random object's repr embeds its memory address,
            # which differs across process runs and silently breaks determinism.
            year_seed = (seed, "town_state", "year", year_index)

            household_rows = _load_household_rows(conn)
            resident_rows = _load_resident_rows(conn, year_start)

            building_type_by_id = _building_type_by_id(conn)
            add_yearly_income(year_seed, household_rows, resident_rows, building_type_by_id)

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

            _append_new_households(conn, household_rows)
            all_household_rows = household_rows
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

            subtract_yearly_spend(household_rows, all_resident_rows, purchases, tax_payments)
            update_household_wealth(conn, household_rows)

            # A resident already in an open (still-ongoing) span keeps it rather than getting a
            # new duplicate row every simulated year -- generate_school_enrollments/
            # generate_military_service have no notion of "already enrolled/serving" since they
            # were written for one-shot generation, where nothing pre-exists.
            school_ids = _building_ids(conn, "school")
            university_ids = _building_ids(conn, "university")
            enrollments = generate_school_enrollments(year_seed, all_resident_rows, school_ids, university_ids, year_start)
            already_enrolled = _residents_with_open_span(conn, "school_enrollments")
            enrollments = [e for e in enrollments if e["resident_db_id"] not in already_enrolled]
            insert_school_enrollments(conn, enrollments)

            garrison_ids = _building_ids(conn, "garrison") + _building_ids(conn, "guard_post")
            military = generate_military_service(all_resident_rows, garrison_ids, year_start)
            already_serving = _residents_with_open_span(conn, "military_service")
            military = [m for m in military if m["resident_db_id"] not in already_serving]
            insert_military_service(conn, military)

            conn.execute('UPDATE town_state SET "current_date" = ? WHERE id = 1', (year_end.isoformat(),))
            conn.commit()

            derive_relationships(db_path, reference_date=year_end)
            current_date = year_end
    finally:
        conn.close()
