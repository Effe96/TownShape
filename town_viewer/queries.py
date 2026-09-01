import json
import sqlite3
from typing import Any, Dict


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
