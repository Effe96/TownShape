"""Edit the values below, then run: python scripts/generate_town.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from town_narrative.parameters import TownParameters
from town_narrative.generate import generate_town_from_parameters
from town_relationships.generate import derive_relationships
from town_db.stats import compute_stress

# --- Edit these ---
SEED = "my-town"
TARGET_POPULATION = 5000
AREA_PER_RESIDENT_MULTIPLIER = 1.0
DENSITY_MULTIPLIER = 1.0
RICH_PROPORTION = 0.05
NUM_RIVERS = 0
HAS_COASTLINE = False
HAS_PORT = False
MAGIC_PREVALENCE = 0.0
AGGRESSION = 0.0

DB_PATH = "my_town.db"
DERIVE_RELATIONSHIPS = True
# ------------------

if __name__ == "__main__":
    params = TownParameters(
        seed=SEED,
        target_population=TARGET_POPULATION,
        area_per_resident_multiplier=AREA_PER_RESIDENT_MULTIPLIER,
        density_multiplier=DENSITY_MULTIPLIER,
        rich_proportion=RICH_PROPORTION,
        num_rivers=NUM_RIVERS,
        has_coastline=HAS_COASTLINE,
        has_port=HAS_PORT,
        magic_prevalence=MAGIC_PREVALENCE,
        aggression=AGGRESSION,
    )

    generate_town_from_parameters(params, DB_PATH)
    if DERIVE_RELATIONSHIPS:
        derive_relationships(DB_PATH)

    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM residents").fetchone()[0]
    alive = conn.execute("SELECT COUNT(*) FROM residents WHERE death_date IS NULL").fetchone()[0]
    conn.close()

    print(f"Generated {DB_PATH}")
    print(f"Residents: {total} ({alive} alive)")
    print(f"Stress: {compute_stress(DB_PATH):.3f}")
