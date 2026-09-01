import sqlite3
from typing import Any, Dict, List


def insert_residents(conn: sqlite3.Connection, resident_rows: List[Dict[str, Any]]) -> None:
    for row in resident_rows:
        cursor = conn.execute(
            "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, death_date, "
            "ses, is_noble, has_magical_talent, home_building_id, workplace_building_id, occupation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["household_id"], row["first_name"], row["last_name"], row["gender"], row["race"],
             row["birth_date"], row["death_date"], row["ses"], int(row["is_noble"]),
             int(row.get("has_magical_talent", False)),
             row["home_building_id"], row["workplace_building_id"], row["occupation"]),
        )
        row["db_id"] = cursor.lastrowid


def insert_disease_events(conn: sqlite3.Connection, disease_rows: List[Dict[str, Any]]) -> None:
    for d in disease_rows:
        cursor = conn.execute(
            "INSERT INTO disease_events (name, start_date, end_date, affected_zone_type, severity) "
            "VALUES (?, ?, ?, ?, ?)",
            (d["name"], d["start_date"], d["end_date"], d["affected_zone_type"], d["severity"]),
        )
        d["_db_id"] = cursor.lastrowid


def insert_skirmish_events(conn: sqlite3.Connection, skirmish_rows: List[Dict[str, Any]]) -> None:
    for s in skirmish_rows:
        cursor = conn.execute(
            "INSERT INTO skirmish_events (name, skirmish_date, severity) VALUES (?, ?, ?)",
            (s["name"], s["skirmish_date"], s["severity"]),
        )
        s["_db_id"] = cursor.lastrowid


def insert_births(conn: sqlite3.Connection, births: List[Dict[str, Any]], new_resident_rows: List[Dict[str, Any]]) -> None:
    for birth, new_row in zip(births, new_resident_rows):
        conn.execute(
            "INSERT INTO births (child_resident_id, mother_resident_id, father_resident_id, birth_date, "
            "reported_by_building_id) VALUES (?, ?, ?, ?, ?)",
            (new_row["db_id"], birth["_mother_db_id"], birth["_father_db_id"],
             birth["birth_date"], birth["reported_by_building_id"]),
        )


def insert_deaths(conn: sqlite3.Connection, deaths: List[Dict[str, Any]]) -> None:
    # A single unified statement for both disease-caused and skirmish-caused deaths -- each death
    # dict only ever populates one of disease_event_id/skirmish_event_id, so .get() gives the
    # other column NULL exactly as the old two separate call sites did implicitly.
    for death in deaths:
        conn.execute(
            "INSERT INTO deaths (resident_id, death_date, cause, disease_event_id, skirmish_event_id, "
            "reported_by_building_id) VALUES (?, ?, ?, ?, ?, ?)",
            (death["resident_db_id"], death["death_date"], death["cause"],
             death.get("disease_event_id"), death.get("skirmish_event_id"), death["reported_by_building_id"]),
        )
        conn.execute(
            "UPDATE residents SET death_date = ? WHERE id = ?",
            (death["death_date"], death["resident_db_id"]),
        )


def insert_purchases(conn: sqlite3.Connection, purchases: List[Dict[str, Any]]) -> None:
    for p in purchases:
        conn.execute(
            "INSERT INTO purchases (resident_id, shop_building_id, good_id, quantity, unit_price, total_price, "
            "purchase_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (p["resident_db_id"], p["shop_building_id"], p["good_id"], p["quantity"],
             p["unit_price"], p["total_price"], p["purchase_date"]),
        )


def insert_tax_payments(conn: sqlite3.Connection, tax_payments: List[Dict[str, Any]]) -> None:
    for t in tax_payments:
        conn.execute(
            "INSERT INTO tax_payments (resident_id, tax_type, amount, period, payment_date) VALUES (?, ?, ?, ?, ?)",
            (t["resident_db_id"], t["tax_type"], t["amount"], t["period"], t["payment_date"]),
        )


def insert_school_enrollments(conn: sqlite3.Connection, enrollments: List[Dict[str, Any]]) -> None:
    for e in enrollments:
        conn.execute(
            "INSERT INTO school_enrollments (resident_id, school_building_id, enrollment_type, start_date, "
            "end_date) VALUES (?, ?, ?, ?, ?)",
            (e["resident_db_id"], e["school_building_id"], e["enrollment_type"], e["start_date"], e["end_date"]),
        )


def insert_military_service(conn: sqlite3.Connection, records: List[Dict[str, Any]]) -> None:
    for m in records:
        conn.execute(
            "INSERT INTO military_service (resident_id, garrison_building_id, rank, start_date, end_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (m["resident_db_id"], m["garrison_building_id"], m["rank"], m["start_date"], m["end_date"]),
        )


def update_household_wealth(conn: sqlite3.Connection, household_rows: List[Dict[str, Any]]) -> None:
    for row in household_rows:
        conn.execute("UPDATE households SET wealth = ? WHERE id = ?", (row["wealth"], row["id"]))
