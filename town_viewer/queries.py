import json
import sqlite3
from typing import Any, Dict, Optional


def get_map_data(conn: sqlite3.Connection) -> Dict[str, Any]:
    districts = [
        {"id": row[0], "zone_type": row[1], "polygon": json.loads(row[2])}
        for row in conn.execute("SELECT id, zone_type, polygon FROM districts")
    ]
    buildings = [
        {
            "id": row[0], "district_id": row[1], "zone_type": row[2], "building_type": row[3],
            "x": row[4], "y": row[5], "name": row[6],
            "width": row[7], "height": row[8], "rotation": row[9],
            "footprint": json.loads(row[10]) if row[10] else None,
        }
        for row in conn.execute(
            "SELECT id, district_id, zone_type, building_type, x, y, name, width, height, rotation, footprint "
            "FROM buildings"
        )
    ]
    water_features = [
        {"id": row[0], "kind": row[1], "polygon": json.loads(row[2])}
        for row in conn.execute("SELECT id, kind, polygon FROM water_features")
    ]
    road_nodes = [
        {"id": row[0], "x": row[1], "y": row[2]}
        for row in conn.execute("SELECT id, x, y FROM road_nodes")
    ]
    road_edges = [
        {"from_node_id": row[0], "to_node_id": row[1], "road_type": row[2]}
        for row in conn.execute("SELECT from_node_id, to_node_id, road_type FROM road_edges")
    ]
    return {
        "districts": districts, "buildings": buildings, "water_features": water_features,
        "roads": {"nodes": road_nodes, "edges": road_edges},
    }


def get_building_detail(conn: sqlite3.Connection, building_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT id, district_id, zone_type, building_type, x, y, capacity, name, width, height, rotation, footprint "
        "FROM buildings WHERE id = ?",
        (building_id,),
    ).fetchone()
    if row is None:
        return None

    building = {
        "id": row[0], "district_id": row[1], "zone_type": row[2], "building_type": row[3],
        "x": row[4], "y": row[5], "capacity": row[6], "name": row[7],
        "width": row[8], "height": row[9], "rotation": row[10],
        "footprint": json.loads(row[11]) if row[11] else None,
    }
    residents = [
        {
            "id": r[0], "first_name": r[1], "last_name": r[2],
            "lives_here": r[3] == building_id, "works_here": r[4] == building_id,
        }
        for r in conn.execute(
            "SELECT id, first_name, last_name, home_building_id, workplace_building_id "
            "FROM residents WHERE home_building_id = ? OR workplace_building_id = ? ORDER BY id",
            (building_id, building_id),
        )
    ]
    building["residents"] = residents
    return building


def search_residents(
    conn: sqlite3.Connection, query: str = "", page: int = 1, page_size: int = 50
) -> Dict[str, Any]:
    offset = (page - 1) * page_size
    like = f"%{query}%"
    total = conn.execute(
        "SELECT COUNT(*) FROM residents WHERE first_name LIKE ? OR last_name LIKE ?", (like, like)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT id, first_name, last_name, occupation FROM residents "
        "WHERE first_name LIKE ? OR last_name LIKE ? ORDER BY last_name, first_name LIMIT ? OFFSET ?",
        (like, like, page_size, offset),
    ).fetchall()
    residents = [{"id": r[0], "first_name": r[1], "last_name": r[2], "occupation": r[3]} for r in rows]
    return {"residents": residents, "total": total, "page": page, "page_size": page_size}


def get_resident_detail(conn: sqlite3.Connection, resident_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT id, household_id, first_name, last_name, gender, race, birth_date, death_date, "
        "ses, occupation, home_building_id, workplace_building_id FROM residents WHERE id = ?",
        (resident_id,),
    ).fetchone()
    if row is None:
        return None

    resident = {
        "id": row[0], "household_id": row[1], "first_name": row[2], "last_name": row[3],
        "gender": row[4], "race": row[5], "birth_date": row[6], "death_date": row[7],
        "ses": row[8], "occupation": row[9], "home_building_id": row[10], "workplace_building_id": row[11],
    }

    household_row = conn.execute(
        "SELECT id, family_name, race, wealth FROM households WHERE id = ?", (resident["household_id"],)
    ).fetchone()
    resident["household"] = {
        "id": household_row[0], "family_name": household_row[1],
        "race": household_row[2], "wealth": household_row[3],
    }

    relationship_rows = conn.execute(
        """
        SELECT * FROM (
            SELECT resident_b_id, res.first_name, res.last_name, relationship_type, 'a'
            FROM relationships JOIN residents res ON res.id = relationships.resident_b_id
            WHERE resident_a_id = ?
            UNION ALL
            SELECT resident_a_id, res.first_name, res.last_name, relationship_type, 'b'
            FROM relationships JOIN residents res ON res.id = relationships.resident_a_id
            WHERE resident_b_id = ?
        )
        ORDER BY CASE relationship_type
            WHEN 'spouse' THEN 0
            WHEN 'parent' THEN 1
            WHEN 'sibling' THEN 2
            WHEN 'household_member' THEN 3
            ELSE 4
        END
        """,
        (resident_id, resident_id),
    ).fetchall()
    resident["relationships"] = [
        {"resident_id": r[0], "first_name": r[1], "last_name": r[2], "relationship_type": r[3], "role": r[4]}
        for r in relationship_rows
    ]

    shopping_rows = conn.execute(
        "SELECT shop_building_id, purchase_count, total_spent, is_primary "
        "FROM shop_relationships WHERE resident_id = ? ORDER BY total_spent DESC",
        (resident_id,),
    ).fetchall()
    resident["shopping"] = [
        {
            "shop_building_id": r[0], "purchase_count": r[1],
            "total_spent": r[2], "is_primary": bool(r[3]),
        }
        for r in shopping_rows
    ]

    return resident
