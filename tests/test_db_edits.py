# tests/test_db_edits.py
from datetime import date

from town_db.edits import create_disease_event, kill_resident, mark_resident_ill, scope_disease_event
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


def test_kill_resident_raises_on_unknown_resident_id(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.commit()
    conn.close()

    try:
        kill_resident(db_path, resident_id=999, death_date=date(1300, 6, 1), cause="accident")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_kill_resident_reassign_rechecks_candidate_liveness_per_purchase(tmp_path):
    # Reproduces the bug fixed by re-filtering candidates per purchase date: A is killed, leaving B
    # as the household's only other living adult at the moment of A's death. B then dies partway
    # through the reassignment window. A's purchases dated before B's death should still go to B,
    # but A's purchases dated on/after B's own death_date must NOT be reassigned to B -- with B as
    # the only candidate and already dead by then, those purchases should be deleted instead.
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)  # A, will be killed
    _insert_resident(conn, 2, 1, death_date="1300-07-01")  # B, dies partway through the window
    _insert_good_and_shop(conn)
    _insert_purchase(conn, 1, resident_id=1, purchase_date="1300-05-01")  # before B's death
    _insert_purchase(conn, 2, resident_id=1, purchase_date="1300-09-01")  # after B's death
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 1, 1), cause="accident")

    conn = connect(db_path)
    before_b_death = conn.execute("SELECT resident_id FROM purchases WHERE id = 1").fetchone()
    after_b_death = conn.execute("SELECT resident_id FROM purchases WHERE id = 2").fetchone()
    assert before_b_death == (2,)  # reassigned to B while B was still alive on that date
    assert after_b_death is None  # B was the only candidate but already dead by this date -> deleted


def _insert_blacksmith_building(conn, building_id, district_id=1):
    conn.execute(
        "INSERT OR IGNORE INTO districts (id, zone_type, polygon) VALUES (?, 'merchant', '[]')",
        (district_id,),
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (?, ?, 'merchant', 'blacksmith', 0, 0, 3)",
        (building_id, district_id),
    )


def test_kill_resident_promotes_apprentice_when_requested(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_household(conn, 2)
    _insert_blacksmith_building(conn, building_id=1)
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) VALUES (1, 1, 'A', 'B', 'male', 'human', '1260-01-01', 'poor', 1, 'blacksmith')"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) VALUES (2, 2, 'C', 'D', 'male', 'human', '1280-01-01', 'poor', 1, 'smith_apprentice')"
    )
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident", promote_replacement=True)

    conn = connect(db_path)
    promoted_occupation = conn.execute("SELECT occupation FROM residents WHERE id = 2").fetchone()[0]
    assert promoted_occupation == "blacksmith"


def test_kill_resident_leaves_position_vacant_when_no_apprentice_exists(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_blacksmith_building(conn, building_id=1)
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) VALUES (1, 1, 'A', 'B', 'male', 'human', '1260-01-01', 'poor', 1, 'blacksmith')"
    )
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident", promote_replacement=True)

    conn = connect(db_path)
    workplace = conn.execute("SELECT workplace_building_id FROM residents WHERE id = 1").fetchone()[0]
    assert workplace is None


def test_kill_resident_shop_ramp_uses_lower_ceiling_when_replacement_promoted(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_household(conn, 2)
    _insert_household(conn, 3)
    _insert_blacksmith_building(conn, building_id=1)
    conn.execute(
        "INSERT INTO goods (id, name, category, typical_price, sv) VALUES (1, 'sword', 'weapons', 10.0, 350)"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) VALUES (1, 1, 'A', 'B', 'male', 'human', '1260-01-01', 'poor', 1, 'blacksmith')"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) VALUES (2, 2, 'C', 'D', 'male', 'human', '1280-01-01', 'poor', 1, 'smith_apprentice')"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses) "
        "VALUES (3, 3, 'E', 'F', 'male', 'human', '1270-01-01', 'poor')"
    )
    # 200 far-future purchases at the shop by an unrelated customer (resident 3). This is the only
    # blacksmith building in the test, so _apply_shop_reputation_ramp has no other_shops to redirect
    # to and every hit takes the DELETE branch -- this test exercises pure loss, not redirection.
    # The volume just gives the fixed-seed ceiling difference (0.30 vs 0.65) room to show up as a
    # clear statistical difference in how many purchases remain.
    for i in range(200):
        conn.execute(
            "INSERT INTO purchases (id, resident_id, shop_building_id, good_id, quantity, unit_price, total_price, purchase_date) "
            "VALUES (?, 3, 1, 1, 1, 10.0, 10.0, '1300-11-01')",
            (i + 1,),
        )
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident", promote_replacement=True)

    conn = connect(db_path)
    remaining_at_shop = conn.execute(
        "SELECT COUNT(*) FROM purchases WHERE shop_building_id = 1 AND purchase_date = '1300-11-01'"
    ).fetchone()[0]
    # 153 days after a 1300-06-01 death exceeds the 120-day ramp, so the chance is pinned at the
    # ceiling for every purchase. With the fixed seed _apply_shop_reputation_ramp derives for this
    # resident/death_date, running the actual RNG sequence gives exactly 136 of 200 remaining at
    # the 0.30 (replaced) ceiling -- versus 73 remaining if the 0.65 (vacant) ceiling had applied
    # instead, confirming promote_replacement genuinely changes which ceiling is used.
    assert remaining_at_shop == 136


def test_kill_resident_manor_noble_is_not_promotable(tmp_path):
    # manor is a rich-residential building, not a shop-like building, so it must not be treated as
    # promotable: a dead noble's servant should not be promoted into the noble role, and no shop
    # reputation ramp should apply. This exercises the _PROMOTABLE_BUILDING_TYPES gating.
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_household(conn, 2)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'rich_residential', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'rich_residential', 'manor', 0, 0, 4)"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) VALUES (1, 1, 'A', 'B', 'male', 'human', '1260-01-01', 'rich', 1, 'noble')"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) VALUES (2, 2, 'C', 'D', 'male', 'human', '1280-01-01', 'poor', 1, 'servant')"
    )
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident", promote_replacement=True)

    conn = connect(db_path)
    workplace = conn.execute("SELECT workplace_building_id FROM residents WHERE id = 1").fetchone()[0]
    servant_occupation = conn.execute("SELECT occupation FROM residents WHERE id = 2").fetchone()[0]
    assert workplace is None
    assert servant_occupation == "servant"  # not promoted to noble


def test_kill_resident_skirmish_death_reports_to_guard_post_not_temple(tmp_path):
    # TownShape's generator reports skirmish deaths via guard_post/garrison, distinct from the
    # temple/healer resolution used for illness/disease deaths. _reporting_building_id must use the
    # guard_post/garrison resolution specifically when skirmish_event_id is provided.
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'temple', 0, 0, 1)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (2, 1, 'civic', 'guard_post', 0, 0, 1)"
    )
    conn.execute(
        "INSERT INTO skirmish_events (id, name, skirmish_date, severity) VALUES (1, 'raid', '1300-06-01', 0.5)"
    )
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="skirmish", skirmish_event_id=1)

    conn = connect(db_path)
    reported_by = conn.execute(
        "SELECT reported_by_building_id FROM deaths WHERE resident_id = 1"
    ).fetchone()[0]
    assert reported_by == 2  # guard_post, not the temple (id 1)


def test_scope_disease_event_sets_affected_zone_type(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO disease_events (id, name, start_date, end_date, affected_zone_type, severity) "
        "VALUES (1, 'fever', '1300-03-01', '1300-04-01', NULL, 0.5)"
    )
    conn.commit()
    conn.close()

    scope_disease_event(db_path, event_id=1, zone_type="merchant")

    conn = connect(db_path)
    assert conn.execute("SELECT affected_zone_type FROM disease_events WHERE id = 1").fetchone()[0] == "merchant"


def test_scope_disease_event_raises_on_nonexistent_event_id(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.commit()
    conn.close()

    try:
        scope_disease_event(db_path, event_id=999, zone_type="merchant")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_create_disease_event_inserts_and_returns_new_id(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.commit()
    conn.close()

    event_id = create_disease_event(
        db_path, zone_type="poor_residential", start_date=date(1300, 5, 1), end_date=date(1300, 6, 1), severity=0.7
    )

    conn = connect(db_path)
    row = conn.execute(
        "SELECT start_date, end_date, affected_zone_type, severity FROM disease_events WHERE id = ?", (event_id,)
    ).fetchone()
    assert row == ("1300-05-01", "1300-06-01", "poor_residential", 0.7)
