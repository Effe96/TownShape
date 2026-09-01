from town_db.economy import (
    add_yearly_income,
    compute_household_income,
    daily_income,
    household_ses,
    seed_starting_wealth,
    starting_wealth_by_ses,
    subtract_yearly_spend,
    wealth_tier,
)


def test_daily_income_is_deterministic_for_the_same_resident():
    a = daily_income(("town", 1), resident_id=42, occupation="shopkeep", building_type="shop",
                      ses="poor", is_noble=False)
    b = daily_income(("town", 1), resident_id=42, occupation="shopkeep", building_type="shop",
                      ses="poor", is_noble=False)
    assert a == b


def test_daily_income_varies_between_different_residents_in_the_same_role():
    incomes = {
        daily_income(("town", 1), resident_id=rid, occupation="shopkeep", building_type="shop",
                      ses="poor", is_noble=False)
        for rid in range(1, 21)
    }
    assert len(incomes) > 1, "expected variation between residents in the identical role"


def test_daily_income_unemployed_is_lower_than_apprentice_is_lower_than_primary():
    unemployed = daily_income(("town", 1), 1, occupation=None, building_type=None, ses="poor", is_noble=False)
    apprentice = daily_income(("town", 1), 1, occupation="shop_staff", building_type="shop", ses="poor", is_noble=False)
    primary = daily_income(("town", 1), 1, occupation="shopkeep", building_type="shop", ses="poor", is_noble=False)
    assert unemployed < apprentice < primary


def test_daily_income_noble_outearns_everyone_regardless_of_occupation():
    noble = daily_income(("town", 1), 1, occupation=None, building_type=None, ses="poor", is_noble=True)
    primary_non_noble = daily_income(("town", 1), 1, occupation="shopkeep", building_type="shop",
                                      ses="rich", is_noble=False)
    assert noble > primary_non_noble


def test_daily_income_rich_ses_outearns_poor_ses_in_the_same_role():
    # Average over many resident_ids to cancel out the per-resident variation multiplier.
    def avg(ses):
        return sum(
            daily_income(("town", 1), rid, occupation="shopkeep", building_type="shop", ses=ses, is_noble=False)
            for rid in range(1, 101)
        ) / 100
    assert avg("rich") > avg("poor")


def test_compute_household_income_sums_only_living_adults_with_a_workplace():
    residents = [
        {"db_id": 1, "age_bracket": "adult", "death_date": None, "occupation": "shopkeep",
         "workplace_building_id": 10, "ses": "poor", "is_noble": False},
        {"db_id": 2, "age_bracket": "adult", "death_date": "1300-06-01", "occupation": "shopkeep",
         "workplace_building_id": 10, "ses": "poor", "is_noble": False},  # dead -- excluded
        {"db_id": 3, "age_bracket": "child", "death_date": None, "occupation": None,
         "workplace_building_id": None, "ses": "poor", "is_noble": False},  # child -- excluded
        {"db_id": 4, "age_bracket": "adult", "death_date": None, "occupation": None,
         "workplace_building_id": None, "ses": "poor", "is_noble": False},  # unemployed -- still contributes
    ]
    building_type_by_id = {10: "shop"}
    income = compute_household_income(("town", 1), residents, building_type_by_id)
    expected = (
        daily_income(("town", 1), 1, "shopkeep", "shop", "poor", False)
        + daily_income(("town", 1), 4, None, None, "poor", False)
    ) * 365
    assert income == expected


def test_household_ses_is_the_modal_ses_among_members():
    residents = [{"ses": "rich"}, {"ses": "rich"}, {"ses": "poor"}]
    assert household_ses(residents) == "rich"


def test_household_ses_ties_break_toward_poor():
    residents = [{"ses": "rich"}, {"ses": "poor"}]
    assert household_ses(residents) == "poor"


def test_household_ses_defaults_to_poor_when_empty():
    assert household_ses([]) == "poor"


def test_starting_wealth_by_ses_rich_exceeds_poor():
    assert starting_wealth_by_ses("rich") > starting_wealth_by_ses("poor")


def test_seed_starting_wealth_sets_wealth_by_household_ses():
    households = [{"id": 1}, {"id": 2}]
    residents = [
        {"household_id": 1, "ses": "rich"},
        {"household_id": 2, "ses": "poor"},
    ]
    seed_starting_wealth(households, residents)
    assert households[0]["wealth"] == starting_wealth_by_ses("rich")
    assert households[1]["wealth"] == starting_wealth_by_ses("poor")


def test_add_yearly_income_increases_wealth_by_computed_income():
    households = [{"id": 1, "wealth": 100.0}]
    residents = [{
        "db_id": 1, "household_id": 1, "age_bracket": "adult", "death_date": None,
        "occupation": "shopkeep", "workplace_building_id": 10, "ses": "poor", "is_noble": False,
    }]
    building_type_by_id = {10: "shop"}
    add_yearly_income(("town", 1), households, residents, building_type_by_id)
    expected_income = compute_household_income(("town", 1), residents, building_type_by_id)
    assert households[0]["wealth"] == 100.0 + expected_income


def test_add_yearly_income_defaults_missing_wealth_to_zero():
    households = [{"id": 1}]  # no "wealth" key yet
    residents = [{
        "db_id": 1, "household_id": 1, "age_bracket": "adult", "death_date": None,
        "occupation": None, "workplace_building_id": None, "ses": "poor", "is_noble": False,
    }]
    add_yearly_income(("town", 1), households, residents, {})
    assert households[0]["wealth"] >= 0.0


def test_subtract_yearly_spend_reduces_wealth_by_purchases_and_taxes():
    households = [{"id": 1, "wealth": 100.0}]
    residents = [{"db_id": 1, "household_id": 1}]
    purchases = [{"resident_db_id": 1, "total_price": 20.0}, {"resident_db_id": 1, "total_price": 5.0}]
    tax_payments = [{"resident_db_id": 1, "amount": 10.0}]
    subtract_yearly_spend(households, residents, purchases, tax_payments)
    assert households[0]["wealth"] == 100.0 - 20.0 - 5.0 - 10.0


def test_subtract_yearly_spend_floors_at_zero():
    households = [{"id": 1, "wealth": 10.0}]
    residents = [{"db_id": 1, "household_id": 1}]
    purchases = [{"resident_db_id": 1, "total_price": 500.0}]
    subtract_yearly_spend(households, residents, purchases, [])
    assert households[0]["wealth"] == 0.0


def test_wealth_tier_orders_poor_below_comfortable_below_wealthy():
    tiers = [wealth_tier(0.0), wealth_tier(500.0), wealth_tier(5000.0)]
    assert tiers == ["poor", "comfortable", "wealthy"]
