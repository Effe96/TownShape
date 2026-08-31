import sqlite3

import pytest

from town_db.generate import generate_town_database
from town_db.simulation import advance_town


def test_advance_town_updates_town_state(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=300, db_path=db_path)

    advance_town(db_path, seed=("town", 1), years=1)

    conn = sqlite3.connect(db_path)
    row = conn.execute('SELECT year_start, "current_date" FROM town_state WHERE id = 1').fetchone()
    assert row == ("1300-01-01", "1302-01-01")


def test_advance_town_two_years_advances_current_date_twice(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=300, db_path=db_path)

    advance_town(db_path, seed=("town", 1), years=2)

    conn = sqlite3.connect(db_path)
    current_date = conn.execute('SELECT "current_date" FROM town_state WHERE id = 1').fetchone()[0]
    assert current_date == "1303-01-01"


def test_advance_town_raises_on_non_positive_years(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=300, db_path=db_path)

    with pytest.raises(ValueError):
        advance_town(db_path, seed=("town", 1), years=0)


def test_advance_town_raises_when_town_state_row_missing(tmp_path):
    from town_db.schema import connect, create_schema
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.commit()

    with pytest.raises(ValueError):
        advance_town(db_path, seed=("town", 1), years=1)


def test_advance_town_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=300, db_path=db_path)

    advance_town(db_path, seed=("town", 1), years=1)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_advance_town_produces_new_purchases_and_relationships(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=300, db_path=db_path)
    conn = sqlite3.connect(db_path)
    purchases_before = conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0]

    advance_town(db_path, seed=("town", 1), years=1)

    conn = sqlite3.connect(db_path)
    purchases_after = conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0]
    relationship_count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    assert purchases_after > purchases_before
    assert relationship_count > 0
