import json
import sqlite3
from datetime import date
from typing import Any, Dict, List

from town_shaper.assignment import DEFAULT_RICH_PROPORTION
from town_shaper.generate import generate_town

from town_db.enrollment import generate_school_enrollments
from town_db.goods import insert_goods
from town_db.households import DEFAULT_INTERMARRIAGE_RATE, build_households_and_residents
from town_db.military import generate_military_service
from town_db.names import RACE_WEIGHTS
from town_db.purchases import SHOP_BUILDING_TYPES, generate_purchases
from town_db.schema import connect, create_schema
from town_db.taxes import generate_tax_payments
from town_db.vital_records import (
    DEFAULT_BIRTH_RATE,
    DEFAULT_DEATH_RATE_BY_AGE,
    generate_births_and_deaths,
    generate_disease_events,
)

DEFAULT_YEAR_START = date(1300, 1, 1)


def generate_town_database(
    seed,
    target_population: int,
    db_path: str,
    year_start: date = DEFAULT_YEAR_START,
    race_weights: Dict[str, float] = RACE_WEIGHTS,
    intermarriage_rate: float = DEFAULT_INTERMARRIAGE_RATE,
    birth_rate: float = DEFAULT_BIRTH_RATE,
    death_rate_by_age: Dict[str, float] = DEFAULT_DEATH_RATE_BY_AGE,
    area_per_resident_multiplier: float = 1.0,
    density_multiplier: float = 1.0,
    rich_proportion: float = DEFAULT_RICH_PROPORTION,
) -> None:
    town = generate_town(
        seed, target_population,
        area_per_resident_multiplier=area_per_resident_multiplier,
        density_multiplier=density_multiplier,
        rich_proportion=rich_proportion,
    )

    conn = connect(db_path)
    create_schema(conn)

    zone_type_by_building_id: Dict[int, str] = {}
    for district in town.districts:
        conn.execute(
            "INSERT INTO districts (id, zone_type, polygon) VALUES (?, ?, ?)",
            (district.id, district.zone_type.value, json.dumps(district.polygon)),
        )
        for building in district.buildings:
            conn.execute(
                "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (building.id, district.id, district.zone_type.value, building.building_type,
                 building.x, building.y, building.capacity),
            )
            zone_type_by_building_id[building.id] = district.zone_type.value

    household_rows, resident_rows = build_households_and_residents(
        town, seed, year_start, race_weights, intermarriage_rate,
    )
    for row in resident_rows:
        row["home_zone_type"] = zone_type_by_building_id.get(row["home_building_id"])

    for household in household_rows:
        conn.execute(
            "INSERT INTO households (id, family_name, race) VALUES (?, ?, ?)",
            (household["id"], household["family_name"], household["race"]),
        )

    _insert_residents(conn, resident_rows)

    # Vital records run BEFORE purchases and taxes so that residents who die
    # partway through the year stop shopping and paying tax on their death
    # date, rather than transacting for the whole year regardless.
    disease_rows = generate_disease_events(seed, year_start)
    for d in disease_rows:
        cursor = conn.execute(
            "INSERT INTO disease_events (name, start_date, end_date, affected_zone_type, severity) VALUES (?, ?, ?, ?, ?)",
            (d["name"], d["start_date"], d["end_date"], d["affected_zone_type"], d["severity"]),
        )
        d["_db_id"] = cursor.lastrowid

    temple_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "temple"), None)
    healer_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "healer"), None)

    births, deaths, new_resident_rows = generate_births_and_deaths(
        seed, household_rows, resident_rows, disease_rows, year_start,
        temple_id, healer_id, birth_rate, death_rate_by_age,
    )
    _insert_residents(conn, new_resident_rows)
    for birth, new_row in zip(births, new_resident_rows):
        conn.execute(
            "INSERT INTO births (child_resident_id, mother_resident_id, father_resident_id, birth_date, reported_by_building_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (new_row["db_id"], birth["_mother_db_id"], birth["_father_db_id"],
             birth["birth_date"], birth["reported_by_building_id"]),
        )
    for death in deaths:
        conn.execute(
            "INSERT INTO deaths (resident_id, death_date, cause, disease_event_id, reported_by_building_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (death["resident_db_id"], death["death_date"], death["cause"],
             death["disease_event_id"], death["reported_by_building_id"]),
        )
        conn.execute(
            "UPDATE residents SET death_date = ? WHERE id = ?",
            (death["death_date"], death["resident_db_id"]),
        )

    goods_ids = insert_goods(conn)

    shop_building_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type in SHOP_BUILDING_TYPES
    ]
    purchases = generate_purchases(
        seed, household_rows, resident_rows, goods_ids, shop_building_ids, year_start,
    )
    for p in purchases:
        conn.execute(
            "INSERT INTO purchases (resident_id, shop_building_id, good_id, quantity, unit_price, total_price, purchase_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (p["resident_db_id"], p["shop_building_id"], p["good_id"], p["quantity"],
             p["unit_price"], p["total_price"], p["purchase_date"]),
        )

    tax_payments = generate_tax_payments(seed, household_rows, resident_rows, year_start)
    for t in tax_payments:
        conn.execute(
            "INSERT INTO tax_payments (resident_id, tax_type, amount, period, payment_date) VALUES (?, ?, ?, ?, ?)",
            (t["resident_db_id"], t["tax_type"], t["amount"], t["period"], t["payment_date"]),
        )

    all_resident_rows = resident_rows + new_resident_rows

    school_ids = [b.id for d in town.districts for b in d.buildings if b.building_type == "school"]
    university_ids = [b.id for d in town.districts for b in d.buildings if b.building_type == "university"]
    enrollments = generate_school_enrollments(seed, all_resident_rows, school_ids, university_ids, year_start)
    for e in enrollments:
        conn.execute(
            "INSERT INTO school_enrollments (resident_id, school_building_id, enrollment_type, start_date, end_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (e["resident_db_id"], e["school_building_id"], e["enrollment_type"], e["start_date"], e["end_date"]),
        )

    garrison_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type in {"garrison", "guard_post"}
    ]
    military = generate_military_service(all_resident_rows, garrison_ids, year_start)
    for m in military:
        conn.execute(
            "INSERT INTO military_service (resident_id, garrison_building_id, rank, start_date, end_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (m["resident_db_id"], m["garrison_building_id"], m["rank"], m["start_date"], m["end_date"]),
        )

    conn.commit()
    conn.close()


def _insert_residents(conn: sqlite3.Connection, resident_rows: List[Dict[str, Any]]) -> None:
    for row in resident_rows:
        cursor = conn.execute(
            "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, death_date, "
            "ses, is_noble, home_building_id, workplace_building_id, occupation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["household_id"], row["first_name"], row["last_name"], row["gender"], row["race"],
             row["birth_date"], row["death_date"], row["ses"], int(row["is_noble"]),
             row["home_building_id"], row["workplace_building_id"], row["occupation"]),
        )
        row["db_id"] = cursor.lastrowid
