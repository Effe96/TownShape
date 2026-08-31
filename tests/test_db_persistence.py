from town_db.persistence import insert_deaths, insert_residents
from town_db.schema import connect, create_schema


def _insert_household(conn, household_id=1):
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (?, 'Smith', 'human')", (household_id,))


def test_insert_residents_sets_db_id_in_place(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    _insert_household(conn)
    rows = [{
        "household_id": 1, "first_name": "Ann", "last_name": "Smith", "gender": "female", "race": "human",
        "birth_date": "1280-01-01", "death_date": None, "ses": "poor", "is_noble": False,
        "has_magical_talent": False, "home_building_id": None, "workplace_building_id": None, "occupation": None,
    }]
    insert_residents(conn, rows)
    conn.commit()
    assert rows[0]["db_id"] is not None
    stored = conn.execute("SELECT first_name FROM residents WHERE id = ?", (rows[0]["db_id"],)).fetchone()
    assert stored == ("Ann",)


def test_insert_deaths_accepts_disease_or_skirmish_cause_and_updates_resident(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    _insert_household(conn)
    rows = [{
        "household_id": 1, "first_name": "Ann", "last_name": "Smith", "gender": "female", "race": "human",
        "birth_date": "1280-01-01", "death_date": None, "ses": "poor", "is_noble": False,
        "has_magical_talent": False, "home_building_id": None, "workplace_building_id": None, "occupation": None,
    }]
    insert_residents(conn, rows)
    conn.commit()
    resident_db_id = rows[0]["db_id"]

    insert_deaths(conn, [{
        "resident_db_id": resident_db_id, "death_date": "1300-06-01", "cause": "illness",
        "reported_by_building_id": None,
    }])
    conn.commit()

    death_row = conn.execute(
        "SELECT death_date, cause, disease_event_id, skirmish_event_id FROM deaths WHERE resident_id = ?",
        (resident_db_id,),
    ).fetchone()
    assert death_row == ("1300-06-01", "illness", None, None)
    resident_row = conn.execute("SELECT death_date FROM residents WHERE id = ?", (resident_db_id,)).fetchone()
    assert resident_row == ("1300-06-01",)
