"""Phase 1 checkpoint script -- generate one town through the settlemaker
bridge, for a side-by-side comparison against the existing pipeline's
port_test.png. Persists settlemaker's own SVG (not town_db.render.render_town)
per the Phase 1 checkpoint finding that render_town's matplotlib output
throws away most of what makes settlemaker's output good -- see
settlemaker_bridge/pipeline.py's generate_via_settlemaker docstring. See
docs/superpowers/plans/2026-09-08-settlemaker-integration.md, Phase 1 task 4.

Run: python scripts/generate_town_settlemaker.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from town_db.schema import connect, create_schema
from settlemaker_bridge.pipeline import generate_via_settlemaker

# Matches this session's port_test.png as closely as the original run's
# exact parameters can be reconstructed (not recoverable verbatim -- see
# Project-Memory/2026-09-08-handoff-wsl-agent-settlemaker-phase1.md): a
# population in the low thousands, walled, with both a river and a
# coastline, port-enabled.
SEED = "port_test"
TARGET_POPULATION = 3000
NUM_RIVERS = 1
HAS_COASTLINE = True
HAS_PORT = True

DB_PATH = "port_test_settlemaker.db"
SVG_PATH = "port_test_settlemaker.svg"

if __name__ == "__main__":
    districts, buildings, water_features, svg = generate_via_settlemaker(
        SEED, TARGET_POPULATION,
        num_rivers=NUM_RIVERS, has_coastline=HAS_COASTLINE, has_port=HAS_PORT,
    )

    with open(SVG_PATH, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"Wrote {SVG_PATH}")

    conn = connect(DB_PATH)
    create_schema(conn)

    conn.executemany(
        "INSERT INTO water_features (id, kind, polygon) VALUES (?, ?, ?)",
        [(i, kind, json.dumps(rings)) for i, (kind, rings) in enumerate(water_features)],
    )
    conn.executemany(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (?, ?, ?)",
        [(d.id, d.zone_type.value, json.dumps(d.polygon_parts)) for d in districts],
    )
    conn.executemany(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, name, "
        "width, height, rotation, footprint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(b.id, b.district_id, b.district_zone_type.value, b.building_type, b.x, b.y, b.capacity,
          b.name, b.width, b.height, b.rotation, json.dumps(b.footprint) if b.footprint else None)
         for d in districts for b in d.buildings],
    )
    conn.commit()
    conn.close()

    print(f"Generated {DB_PATH}: {len(districts)} districts, {len(buildings)} buildings, "
          f"{len(water_features)} water features")
