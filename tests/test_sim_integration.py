"""TownShape's side of the social-sim integration (social-sim-demo/docs/townshape-brief.md)."""
import json
import sqlite3

import pytest

from town_db.names import name_new_resident
from town_db.schema import SimOwnedTownError, connect, create_schema, ensure_sim_schema
from town_db.simulation import advance_town
from town_relationships.generate import derive_relationships
from town_viewer.queries import get_building_detail, get_resident_detail


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _town(db_path):
    conn = connect(db_path)
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', ?)", (json.dumps([[[0, 0], [9, 0], [9, 9]]]),))
    conn.execute("INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) VALUES (1, 1, 'civic', 'residence', 1, 1, 4)")
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Oak', 'human')")
    conn.execute("INSERT INTO town_state (id, year_start, current_date, aggression, magic_prevalence) VALUES (1, '1000-01-01', '1000-01-01', 0.1, 0.1)")
    for rid, home in ((1, 1), (2, None), (3, 1), (4, 1)):
        conn.execute(
            "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, home_building_id) "
            "VALUES (?, 1, 'A', 'Oak', 'male', 'human', '0980-01-01', 'lower', ?)", (rid, home))
    conn.execute("INSERT INTO deaths (resident_id, death_date, cause) VALUES (3, '1000-05-01', 'pneumonic plague')")
    conn.execute("UPDATE residents SET death_date = '1000-05-01' WHERE id = 3")
    conn.execute("INSERT INTO departures (resident_id, departure_date, reason) VALUES (4, '1000-06-01', 'banished')")
    conn.commit()
    return conn


def test_new_towns_have_the_sims_tables_and_columns(tmp_path):
    conn = _town(str(tmp_path / "t.db"))
    for table in ("resident_traits", "household_economy", "house_tenure", "departures", "sim_state"):
        assert _columns(conn, table)
    assert {"loyalty", "religiosity", "strictness"} <= _columns(conn, "town_state")


def test_an_older_town_is_brought_up_to_date(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "old.db"))
    conn.execute("CREATE TABLE town_state (id INTEGER PRIMARY KEY, aggression REAL)")
    conn.execute("CREATE TABLE relationships (id INTEGER PRIMARY KEY, relationship_type TEXT)")
    ensure_sim_schema(conn)
    ensure_sim_schema(conn)  # idempotent
    assert {"loyalty", "strictness"} <= _columns(conn, "town_state")
    assert {"intimacy", "valence_b_to_a", "former_type"} <= _columns(conn, "relationships")
    assert _columns(conn, "sim_state")


def test_relationships_get_the_sims_columns_and_derivation_stops_once_the_sim_runs(tmp_path):
    db_path = str(tmp_path / "t.db")
    _town(db_path).close()
    derive_relationships(db_path)  # fine before the sim takes over
    conn = connect(db_path)
    assert {"time", "services", "valence_a_to_b"} <= _columns(conn, "relationships")
    conn.execute("INSERT INTO sim_state (key, value) VALUES ('clock', '0')")
    conn.commit()
    conn.close()
    with pytest.raises(SimOwnedTownError):
        derive_relationships(db_path)
    with pytest.raises(SimOwnedTownError):
        advance_town(db_path, "seed")
    (tmp_path / "t.db").unlink()  # both closed their connection, so the file isn't locked


def test_name_new_resident_depends_only_on_the_resident():
    first, last = name_new_resident("seed", 42, "dwarf", "female")
    assert (first, last) == name_new_resident("seed", 42, "dwarf", "female")
    assert name_new_resident("seed", 42, "dwarf", "female", family_name="Oak") == (first, "Oak")
    assert len({name_new_resident("seed", i, "human", "male") for i in range(20)}) > 10
    with pytest.raises(ValueError):
        name_new_resident("seed", 1, "dragon", "male")


def test_viewer_shows_deaths_departures_and_the_homeless(tmp_path):
    conn = _town(str(tmp_path / "t.db"))
    assert get_resident_detail(conn, 2)["home_building_id"] is None
    assert get_resident_detail(conn, 3)["death"] == {"date": "1000-05-01", "cause": "pneumonic plague"}
    assert get_resident_detail(conn, 4)["departure"] == {"date": "1000-06-01", "reason": "banished"}
    assert get_resident_detail(conn, 1)["death"] is None and get_resident_detail(conn, 1)["departure"] is None
    # the dead and whoever has left town no longer show as living in their old house
    assert [r["id"] for r in get_building_detail(conn, 1)["residents"]] == [1]
