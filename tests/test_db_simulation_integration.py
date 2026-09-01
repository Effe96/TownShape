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


def test_rich_households_out_spend_poor_households_over_time(tmp_path):
    # The regression this plan exists to fix: a test town previously showed its single highest
    # individual spender for the year was poor, out-spending every rich resident. This asserts
    # the opposite now holds, at the household level, across a seed sweep and multiple years.
    rich_medians = []
    poor_medians = []
    for seed in SEEDS:
        db_path = str(tmp_path / f"wealth_{seed[1]}.db")
        generate_town_database(seed, target_population=600, db_path=db_path)
        advance_town(db_path, seed=seed, years=3)

        conn = sqlite3.connect(db_path)
        # A household's ses for this comparison: the modal ses among its living residents,
        # same definition town_db.economy.household_ses uses internally.
        household_ses_rows = conn.execute(
            "SELECT household_id, ses, COUNT(*) c FROM residents WHERE death_date IS NULL "
            "GROUP BY household_id, ses"
        ).fetchall()
        modal_ses_by_household: dict = {}
        best_count: dict = {}
        for household_id, ses, count in household_ses_rows:
            if household_id not in best_count or count > best_count[household_id]:
                best_count[household_id] = count
                modal_ses_by_household[household_id] = ses

        spend_by_household = dict(conn.execute(
            "SELECT household_id, total FROM ("
            "  SELECT r.household_id AS household_id, SUM(p.total_price) AS total "
            "  FROM purchases p JOIN residents r ON r.id = p.resident_id GROUP BY r.household_id"
            ")"
        ).fetchall())

        rich_spends = [
            spend_by_household.get(hh_id, 0.0)
            for hh_id, ses in modal_ses_by_household.items() if ses == "rich"
        ]
        poor_spends = [
            spend_by_household.get(hh_id, 0.0)
            for hh_id, ses in modal_ses_by_household.items() if ses == "poor"
        ]
        if rich_spends and poor_spends:
            rich_medians.append(sorted(rich_spends)[len(rich_spends) // 2])
            poor_medians.append(sorted(poor_spends)[len(poor_spends) // 2])

    assert rich_medians and poor_medians, "expected both rich and poor households in every swept seed"
    seeds_where_rich_wins = sum(1 for r, p in zip(rich_medians, poor_medians) if r > p)
    assert seeds_where_rich_wins == len(rich_medians), (
        f"expected rich median spend > poor median spend in every seed; "
        f"rich={rich_medians}, poor={poor_medians}"
    )


def test_household_wealth_never_goes_negative_across_seeds_and_years(tmp_path):
    for seed in SEEDS:
        db_path = str(tmp_path / f"wealthfloor_{seed[1]}.db")
        generate_town_database(seed, target_population=400, db_path=db_path)
        advance_town(db_path, seed=seed, years=5)
        conn = sqlite3.connect(db_path)
        negative = conn.execute("SELECT COUNT(*) FROM households WHERE wealth < 0").fetchone()[0]
        assert negative == 0, f"seed {seed}"
