# tests/test_db_edits.py
import random
from datetime import date

from town_db.edits import kill_resident, mark_resident_ill
from town_db.schema import connect, create_schema


def _insert_household(conn, household_id, family_name="Smith", race="human"):
    conn.execute(
        "INSERT INTO households (id, family_name, race) VALUES (?, ?, ?)",
        (household_id, family_name, race),
    )


def _insert_resident(conn, resident_id, household_id, birth_date="1280-01-01", death_date=None):
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, death_date, ses) "
        "VALUES (?, ?, 'A', 'B', 'male', 'human', ?, ?, 'poor')",
        (resident_id, household_id, birth_date, death_date),
    )


def _insert_good_and_shop(conn):
    # districts must be inserted before buildings -- buildings.district_id is FK-enforced
    # (connect() sets PRAGMA foreign_keys = ON) and referencing a not-yet-existing district
    # fails immediately.
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'merchant', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'merchant', 'shop', 0, 0, 1)"
    )
    conn.execute(
        "INSERT INTO goods (id, name, category, typical_price, sv) VALUES (1, 'bread', 'food', 0.05, 800)"
    )


def _insert_purchase(conn, purchase_id, resident_id, purchase_date, shop_building_id=1):
    conn.execute(
        "INSERT INTO purchases (id, resident_id, shop_building_id, good_id, quantity, unit_price, total_price, purchase_date) "
        "VALUES (?, ?, ?, 1, 1, 0.05, 0.05, ?)",
        (purchase_id, resident_id, shop_building_id, purchase_date),
    )


def test_mark_resident_ill_inserts_illness_row(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)
    conn.commit()
    conn.close()

    mark_resident_ill(db_path, resident_id=1, start_date=date(1300, 3, 1), end_date=date(1300, 3, 20), severity=0.6)

    conn = connect(db_path)
    row = conn.execute(
        "SELECT resident_id, disease_event_id, start_date, end_date, severity FROM illnesses"
    ).fetchone()
    assert row == (1, None, "1300-03-01", "1300-03-20", 0.6)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_mark_resident_ill_reassigns_purchases_in_window_to_another_household_adult(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)  # will be marked ill
    _insert_resident(conn, 2, 1)  # other living adult in the same household
    _insert_good_and_shop(conn)
    _insert_purchase(conn, 1, resident_id=1, purchase_date="1300-03-10")  # inside illness window
    _insert_purchase(conn, 2, resident_id=1, purchase_date="1300-05-01")  # outside illness window
    conn.commit()
    conn.close()

    mark_resident_ill(db_path, resident_id=1, start_date=date(1300, 3, 1), end_date=date(1300, 3, 20), severity=0.6)

    conn = connect(db_path)
    in_window_buyer = conn.execute("SELECT resident_id FROM purchases WHERE id = 1").fetchone()[0]
    outside_window_buyer = conn.execute("SELECT resident_id FROM purchases WHERE id = 2").fetchone()[0]
    assert in_window_buyer == 2  # reassigned to the other household adult
    assert outside_window_buyer == 1  # untouched, outside the illness window


def test_mark_resident_ill_deletes_purchase_when_sole_adult_in_household(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)  # sole adult, will be marked ill
    _insert_good_and_shop(conn)
    _insert_purchase(conn, 1, resident_id=1, purchase_date="1300-03-10")
    conn.commit()
    conn.close()

    mark_resident_ill(db_path, resident_id=1, start_date=date(1300, 3, 1), end_date=date(1300, 3, 20), severity=0.6)

    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] == 0


def test_mark_resident_ill_raises_on_overlapping_illness(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)
    conn.commit()
    conn.close()

    mark_resident_ill(db_path, resident_id=1, start_date=date(1300, 3, 1), end_date=date(1300, 3, 20), severity=0.6)
    try:
        mark_resident_ill(db_path, resident_id=1, start_date=date(1300, 3, 10), end_date=date(1300, 3, 25), severity=0.4)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_kill_resident_sets_death_date_and_inserts_deaths_row(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident")

    conn = connect(db_path)
    resident_death_date = conn.execute("SELECT death_date FROM residents WHERE id = 1").fetchone()[0]
    deaths_row = conn.execute("SELECT resident_id, death_date, cause FROM deaths WHERE resident_id = 1").fetchone()
    assert resident_death_date == "1300-06-01"
    assert deaths_row == (1, "1300-06-01", "accident")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_kill_resident_reassigns_own_future_purchases(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)
    _insert_resident(conn, 2, 1)
    _insert_good_and_shop(conn)
    _insert_purchase(conn, 1, resident_id=1, purchase_date="1300-07-01")  # after death
    _insert_purchase(conn, 2, resident_id=1, purchase_date="1300-05-01")  # before death
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident")

    conn = connect(db_path)
    assert conn.execute("SELECT resident_id FROM purchases WHERE id = 1").fetchone()[0] == 2
    assert conn.execute("SELECT resident_id FROM purchases WHERE id = 2").fetchone()[0] == 1


def test_kill_resident_deletes_future_tax_payments_and_closes_open_records(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'garrison', 0, 0, 1)"
    )
    conn.execute(
        "INSERT INTO tax_payments (resident_id, tax_type, amount, period, payment_date) "
        "VALUES (1, 'head_tax', 1.0, '1300-Q3', '1300-07-01')"
    )
    conn.execute(
        "INSERT INTO tax_payments (resident_id, tax_type, amount, period, payment_date) "
        "VALUES (1, 'head_tax', 1.0, '1300-Q1', '1300-02-01')"
    )
    conn.execute(
        "INSERT INTO military_service (resident_id, garrison_building_id, rank, start_date, end_date) "
        "VALUES (1, 1, 'soldier', '1298-01-01', NULL)"
    )
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident")

    conn = connect(db_path)
    remaining_tax_dates = [
        row[0] for row in conn.execute("SELECT payment_date FROM tax_payments WHERE resident_id = 1").fetchall()
    ]
    assert remaining_tax_dates == ["1300-02-01"]
    military_end_date = conn.execute(
        "SELECT end_date FROM military_service WHERE resident_id = 1"
    ).fetchone()[0]
    assert military_end_date == "1300-06-01"


def test_kill_resident_raises_if_already_dead(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1, death_date="1300-01-01")
    conn.commit()
    conn.close()

    try:
        kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident")
        assert False, "expected ValueError"
    except ValueError:
        pass
