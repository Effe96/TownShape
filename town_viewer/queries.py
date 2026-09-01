import json
import sqlite3
from typing import Any, Dict, Optional


def get_map_data(conn: sqlite3.Connection) -> Dict[str, Any]:
    districts = [
        {"id": row[0], "zone_type": row[1], "polygon": json.loads(row[2])}
        for row in conn.execute("SELECT id, zone_type, polygon FROM districts")
    ]
    buildings = [
        {"id": row[0], "district_id": row[1], "zone_type": row[2], "building_type": row[3], "x": row[4], "y": row[5]}
        for row in conn.execute(
            "SELECT id, district_id, zone_type, building_type, x, y FROM buildings"
        )
    ]
    water_features = [
        {"id": row[0], "kind": row[1], "polygon": json.loads(row[2])}
        for row in conn.execute("SELECT id, kind, polygon FROM water_features")
    ]
    return {"districts": districts, "buildings": buildings, "water_features": water_features}


def get_building_detail(conn: sqlite3.Connection, building_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT id, district_id, zone_type, building_type, x, y, capacity FROM buildings WHERE id = ?",
        (building_id,),
    ).fetchone()
    if row is None:
        return None

    building = {
        "id": row[0], "district_id": row[1], "zone_type": row[2], "building_type": row[3],
        "x": row[4], "y": row[5], "capacity": row[6],
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
