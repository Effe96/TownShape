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


def test_generate_town_from_parameters_threads_density_multiplier_into_building_count(tmp_path):
    db_path_sparse = str(tmp_path / "sparse.db")
    db_path_dense = str(tmp_path / "dense.db")
    generate_town_from_parameters(
        TownParameters(seed=("town", 1), target_population=1500, density_multiplier=0.5), db_path_sparse
    )
    generate_town_from_parameters(
        TownParameters(seed=("town", 1), target_population=1500, density_multiplier=2.0), db_path_dense
    )

    conn_sparse = sqlite3.connect(db_path_sparse)
    conn_dense = sqlite3.connect(db_path_dense)
    sparse_count = conn_sparse.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
    dense_count = conn_dense.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
    assert dense_count > sparse_count


def test_generate_town_from_parameters_threads_rich_proportion_into_resident_ses(tmp_path):
    db_path_poor = str(tmp_path / "poor.db")
    db_path_rich = str(tmp_path / "rich.db")
    generate_town_from_parameters(
        TownParameters(seed=("town", 1), target_population=1500, rich_proportion=0.01), db_path_poor
    )
    generate_town_from_parameters(
        TownParameters(seed=("town", 1), target_population=1500, rich_proportion=0.9), db_path_rich
    )

    conn_poor = sqlite3.connect(db_path_poor)
    conn_rich = sqlite3.connect(db_path_rich)
    poor_rich_count = conn_poor.execute("SELECT COUNT(*) FROM residents WHERE ses = 'rich'").fetchone()[0]
    rich_rich_count = conn_rich.execute("SELECT COUNT(*) FROM residents WHERE ses = 'rich'").fetchone()[0]
    assert rich_rich_count > poor_rich_count


def test_generate_town_from_parameters_records_water_params(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(
        seed=("town", 1), target_population=1500, num_rivers=2, has_coastline=True, has_port=True,
    )
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT num_rivers, has_coastline, has_port FROM generation_parameters").fetchone()
    assert row == (2, 1, 1)
    assert conn.execute("SELECT COUNT(*) FROM water_features").fetchone()[0] == 3


def test_generate_town_from_parameters_with_water_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(
        seed=("town", 1), target_population=1500, num_rivers=1, has_coastline=True, has_port=True,
    )
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []


def test_generate_town_from_parameters_records_magic_prevalence(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(seed=("town", 1), target_population=1500, magic_prevalence=0.4)
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT magic_prevalence FROM generation_parameters").fetchone()
    assert row == (0.4,)


def test_generate_town_from_parameters_with_magic_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(seed=("town", 1), target_population=5000, magic_prevalence=0.8)
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []
