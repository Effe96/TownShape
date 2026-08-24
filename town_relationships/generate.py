import sqlite3
from datetime import date
from typing import Any, Dict, List

from town_db.generate import DEFAULT_YEAR_START
from town_db.schema import connect

from town_relationships.family import derive_family_relationships
from town_relationships.military import derive_unit_mate_relationships
from town_relationships.neighbors import derive_neighbor_relationships
from town_relationships.schema import create_relationships_schema
from town_relationships.school import derive_classmate_relationships
from town_relationships.shops import derive_shop_relationships
from town_relationships.work import derive_coworker_relationships


def derive_relationships(db_path: str, reference_date: date = DEFAULT_YEAR_START) -> None:
    conn = connect(db_path)
    create_relationships_schema(conn)

    residents = _fetch_residents(conn)
    buildings = _fetch_buildings(conn)
    births = _fetch_births(conn)
    military_service = _fetch_military_service(conn)
    school_enrollments = _fetch_school_enrollments(conn)
    purchases = _fetch_purchases(conn)

    relationship_rows: List[Dict[str, Any]] = []
    relationship_rows += derive_family_relationships(residents, births, reference_date)
    relationship_rows += derive_coworker_relationships(residents)
    relationship_rows += derive_neighbor_relationships(residents, buildings)
    relationship_rows += derive_unit_mate_relationships(military_service)
    relationship_rows += derive_classmate_relationships(school_enrollments)

    for row in relationship_rows:
        conn.execute(
            "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type, detail) "
            "VALUES (?, ?, ?, ?)",
            (row["resident_a_id"], row["resident_b_id"], row["relationship_type"], row["detail"]),
        )

    for row in derive_shop_relationships(residents, purchases, buildings):
        conn.execute(
            "INSERT INTO shop_relationships (resident_id, shop_building_id, purchase_count, total_spent, "
            "distance, need_score, customer_score, is_primary) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (row["resident_id"], row["shop_building_id"], row["purchase_count"], row["total_spent"],
             row["distance"], row["need_score"], row["customer_score"], row["is_primary"]),
        )

    conn.commit()
    conn.close()


def _fetch_residents(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    columns = ["id", "household_id", "home_building_id", "workplace_building_id", "occupation", "birth_date", "ses"]
    rows = conn.execute(f"SELECT {', '.join(columns)} FROM residents").fetchall()
    return [dict(zip(columns, row)) for row in rows]


def _fetch_buildings(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT id, x, y FROM buildings").fetchall()
    return [{"id": r[0], "x": r[1], "y": r[2]} for r in rows]


def _fetch_births(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT child_resident_id, mother_resident_id, father_resident_id FROM births"
    ).fetchall()
    return [{"child_resident_id": r[0], "mother_resident_id": r[1], "father_resident_id": r[2]} for r in rows]


def _fetch_military_service(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT resident_id, garrison_building_id, start_date, end_date FROM military_service"
    ).fetchall()
    return [{"resident_id": r[0], "garrison_building_id": r[1], "start_date": r[2], "end_date": r[3]} for r in rows]


def _fetch_school_enrollments(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT resident_id, school_building_id, start_date, end_date FROM school_enrollments"
    ).fetchall()
    return [{"resident_id": r[0], "school_building_id": r[1], "start_date": r[2], "end_date": r[3]} for r in rows]


def _fetch_purchases(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT p.resident_id, p.shop_building_id, p.total_price, g.category "
        "FROM purchases p JOIN goods g ON g.id = p.good_id"
    ).fetchall()
    return [{"resident_id": r[0], "shop_building_id": r[1], "total_price": r[2], "category": r[3]} for r in rows]
