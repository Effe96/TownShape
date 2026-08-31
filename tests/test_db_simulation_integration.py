import sqlite3
from datetime import date

from town_db.ages import ADULT_AGE_RANGE, age_on
from town_db.generate import generate_town_database
from town_db.simulation import advance_town

SEEDS = [("town", n) for n in range(1, 11)]


def test_five_year_advance_preserves_data_integrity_across_seeds(tmp_path):
    for seed in SEEDS:
        db_path = str(tmp_path / f"town_{seed[1]}.db")
        generate_town_database(seed, target_population=400, db_path=db_path)

        advance_town(db_path, seed=seed, years=5)

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == [], f"seed {seed}"

        # No purchase dated after its buyer's own death.
        late_purchases = conn.execute(
            "SELECT COUNT(*) FROM purchases p JOIN residents r ON r.id = p.resident_id "
            "WHERE r.death_date IS NOT NULL AND p.purchase_date > r.death_date"
        ).fetchone()[0]
        assert late_purchases == 0, f"seed {seed}"

        # No tax payment dated after its payer's own death.
        late_taxes = conn.execute(
            "SELECT COUNT(*) FROM tax_payments t JOIN residents r ON r.id = t.resident_id "
            "WHERE r.death_date IS NOT NULL AND t.payment_date > r.death_date"
        ).fetchone()[0]
        assert late_taxes == 0, f"seed {seed}"

        # No duplicate relationship rows after repeated re-derivation.
        dup_relationships = conn.execute(
            "SELECT resident_a_id, resident_b_id, relationship_type, COUNT(*) c FROM relationships "
            "GROUP BY resident_a_id, resident_b_id, relationship_type HAVING c > 1"
        ).fetchall()
        assert dup_relationships == [], f"seed {seed}"

        # No resident has more than one deaths row.
        dup_deaths = conn.execute(
            "SELECT resident_id, COUNT(*) c FROM deaths GROUP BY resident_id HAVING c > 1"
        ).fetchall()
        assert dup_deaths == [], f"seed {seed}"

        # No resident should ever accumulate more than one *open* (still-ongoing) military
        # service or school enrollment span -- advance_town must not re-issue a new span for a
        # resident who already has one in progress.
        open_military = conn.execute(
            "SELECT resident_id, COUNT(*) c FROM military_service WHERE end_date IS NULL "
            "GROUP BY resident_id HAVING c > 1"
        ).fetchall()
        assert open_military == [], f"seed {seed}"

        open_enrollments = conn.execute(
            "SELECT resident_id, COUNT(*) c FROM school_enrollments WHERE end_date IS NULL "
            "GROUP BY resident_id HAVING c > 1"
        ).fetchall()
        assert open_enrollments == [], f"seed {seed}"

        # No relationship row should ever pair a resident with themselves.
        self_relationships = conn.execute(
            "SELECT COUNT(*) FROM relationships WHERE resident_a_id = resident_b_id"
        ).fetchone()[0]
        assert self_relationships == 0, f"seed {seed}"


def test_advance_town_is_deterministic(tmp_path):
    db_path_1 = str(tmp_path / "town1.db")
    db_path_2 = str(tmp_path / "town2.db")
    generate_town_database(("town", 7), target_population=400, db_path=db_path_1)
    generate_town_database(("town", 7), target_population=400, db_path=db_path_2)

    advance_town(db_path_1, seed=("town", 7), years=3)
    advance_town(db_path_2, seed=("town", 7), years=3)

    conn1 = sqlite3.connect(db_path_1)
    conn2 = sqlite3.connect(db_path_2)
    for table in ["residents", "households", "purchases", "tax_payments", "births", "deaths",
                  "skirmish_events", "relationships", "shop_relationships"]:
        rows1 = conn1.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        rows2 = conn2.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        assert rows1 == rows2, table


def test_household_formation_produces_spouse_not_household_member_relationship(tmp_path):
    # Runs a higher-population, higher-year-count town to make formation events likely, then
    # checks that any newly-formed household (more than 2 members starting at a household id
    # beyond the original generation range) is reflected as 'spouse' by the re-derived
    # relationships, not 'household_member'.
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 3), target_population=800, db_path=db_path)
    conn = sqlite3.connect(db_path)
    max_original_household_id = conn.execute("SELECT MAX(id) FROM households").fetchone()[0]

    advance_town(db_path, seed=("town", 3), years=5)

    conn = sqlite3.connect(db_path)
    # `current_date` collides with SQLite's CURRENT_DATE keyword -- must be quoted on read.
    reference_date = date.fromisoformat(
        conn.execute('SELECT "current_date" FROM town_state WHERE id = 1').fetchone()[0]
    )
    new_households = conn.execute(
        "SELECT id FROM households WHERE id > ?", (max_original_household_id,)
    ).fetchall()
    assert new_households, "expected at least one new household to have formed over 5 years at this population"

    for (household_id,) in new_households:
        # A freshly-formed household starts as exactly a couple (household_formation always
        # creates a brand-new household id per pairing, never reuses one) -- any additional
        # living members gained over the remaining simulated years can only be their children,
        # born as infants, so the couple should still be the household's only adults.
        members = conn.execute(
            "SELECT id, birth_date FROM residents WHERE household_id = ? AND death_date IS NULL", (household_id,)
        ).fetchall()
        adult_ids = [
            resident_id for resident_id, birth_date_str in members
            if age_on(date.fromisoformat(birth_date_str), reference_date) >= ADULT_AGE_RANGE[0]
        ]
        assert len(adult_ids) == 2, (household_id, members)
        a, b = sorted(adult_ids)
        rel_type = conn.execute(
            "SELECT relationship_type FROM relationships WHERE resident_a_id = ? AND resident_b_id = ?", (a, b)
        ).fetchone()
        assert rel_type == ("spouse",), household_id
