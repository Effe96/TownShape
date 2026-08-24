import sqlite3

from town_narrative.generate import generate_town_from_parameters
from town_narrative.parameters import TownParameters


def test_generate_town_from_parameters_creates_a_populated_db(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(seed=("town", 1), target_population=1500)
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    resident_count = conn.execute("SELECT COUNT(*) FROM residents").fetchone()[0]
    assert resident_count > 0


def test_generate_town_from_parameters_records_one_generation_parameters_row(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(
        seed=("town", 1), target_population=1500,
        area_per_resident_multiplier=1.5, density_multiplier=0.7, rich_proportion=0.12,
    )
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT seed, target_population, area_per_resident_multiplier, density_multiplier, rich_proportion "
        "FROM generation_parameters"
    ).fetchall()
    assert rows == [("('town', 1)", 1500, 1.5, 0.7, 0.12)]


def test_generate_town_from_parameters_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(seed=("town", 1), target_population=1500)
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []
