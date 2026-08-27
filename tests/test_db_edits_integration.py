# tests/test_db_edits_integration.py
from datetime import date

import pytest

from town_db.edits import create_disease_event, kill_resident, mark_resident_ill, scope_disease_event
from town_db.generate import generate_town_database
from town_db.schema import connect


@pytest.mark.parametrize("seed_index", range(5))
def test_kill_resident_against_a_real_town_keeps_fk_integrity_and_touches_only_expected_rows(seed_index, tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("edit-integration", seed_index), target_population=2000, db_path=db_path)

    conn = connect(db_path)
    resident_id = conn.execute("SELECT id FROM residents WHERE death_date IS NULL ORDER BY id LIMIT 1").fetchone()[0]
    other_resident_purchases_before = {
        row[0]: row[1] for row in conn.execute(
            "SELECT id, resident_id FROM purchases WHERE resident_id != ?", (resident_id,)
        ).fetchall()
    }
    conn.close()

    kill_resident(db_path, resident_id=resident_id, death_date=date(1300, 6, 1), cause="accident")

    conn = connect(db_path)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("SELECT death_date FROM residents WHERE id = ?", (resident_id,)).fetchone()[0] == "1300-06-01"

    other_resident_purchases_after = {
        row[0]: row[1] for row in conn.execute(
            "SELECT id, resident_id FROM purchases WHERE id IN ({})".format(
                ",".join(str(k) for k in other_resident_purchases_before)
            )
        ).fetchall()
    } if other_resident_purchases_before else {}
    assert other_resident_purchases_after == other_resident_purchases_before


@pytest.mark.parametrize("seed_index", range(5))
def test_mark_resident_ill_against_a_real_town_keeps_fk_integrity(seed_index, tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("edit-integration-ill", seed_index), target_population=2000, db_path=db_path)

    conn = connect(db_path)
    resident_id = conn.execute("SELECT id FROM residents WHERE death_date IS NULL ORDER BY id LIMIT 1").fetchone()[0]
    conn.close()

    mark_resident_ill(db_path, resident_id=resident_id, start_date=date(1300, 3, 1), end_date=date(1300, 4, 1), severity=0.5)

    conn = connect(db_path)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("SELECT COUNT(*) FROM illnesses WHERE resident_id = ?", (resident_id,)).fetchone()[0] == 1


@pytest.mark.parametrize("seed_index", range(5))
def test_kill_resident_with_promote_replacement_against_a_real_town(seed_index, tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("edit-integration-promote", seed_index), target_population=3000, db_path=db_path)

    conn = connect(db_path)
    blacksmith = conn.execute(
        "SELECT id FROM residents WHERE occupation = 'blacksmith' AND death_date IS NULL ORDER BY id LIMIT 1"
    ).fetchone()
    conn.close()
    if blacksmith is None:
        pytest.skip("no living blacksmith in this seed's town")
    resident_id = blacksmith[0]

    kill_resident(db_path, resident_id=resident_id, death_date=date(1300, 6, 1), cause="accident", promote_replacement=True)

    conn = connect(db_path)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_scope_and_create_disease_event_against_a_real_town(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("edit-integration-disease", 0), target_population=2000, db_path=db_path)

    new_id = create_disease_event(
        db_path, zone_type="merchant", start_date=date(1300, 4, 1), end_date=date(1300, 5, 1), severity=0.4
    )
    scope_disease_event(db_path, event_id=new_id, zone_type="civic")

    conn = connect(db_path)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute(
        "SELECT affected_zone_type FROM disease_events WHERE id = ?", (new_id,)
    ).fetchone()[0] == "civic"
