from datetime import date

from town_db.taxes import HEAD_TAX_AMOUNT, generate_tax_payments

YEAR_START = date(1300, 1, 1)


def _resident(db_id, household_id, is_noble=False, age_bracket="adult", ses="poor"):
    return {
        "db_id": db_id, "household_id": household_id, "age_bracket": age_bracket,
        "ses": ses, "is_noble": is_noble,
    }


def test_head_tax_charged_once_per_adult_and_never_to_nobles_or_children():
    households = [{"id": 1, "family_name": "Smith", "race": "human"}]
    residents = [
        _resident(1, 1),                       # regular adult -> taxed
        _resident(2, 1, is_noble=True),         # noble -> exempt
        _resident(3, 1, age_bracket="child"),   # child -> exempt
    ]
    payments = generate_tax_payments(("town", 1), households, residents, YEAR_START)
    head_taxes = [p for p in payments if p["tax_type"] == "head_tax"]
    assert len(head_taxes) == 1
    assert head_taxes[0]["resident_db_id"] == 1
    assert head_taxes[0]["amount"] == HEAD_TAX_AMOUNT


def test_property_tax_charged_quarterly_per_household_and_scaled_by_ses():
    households = [{"id": 1, "family_name": "Rich", "race": "human"}, {"id": 2, "family_name": "Poor", "race": "human"}]
    residents = [
        _resident(1, 1, ses="rich"),
        _resident(2, 2, ses="poor"),
    ]
    payments = generate_tax_payments(("town", 1), households, residents, YEAR_START)
    property_taxes = [p for p in payments if p["tax_type"] == "property_tax"]
    assert len(property_taxes) == 8  # 2 households x 4 quarters

    rich_amount = next(p["amount"] for p in property_taxes if p["resident_db_id"] == 1)
    poor_amount = next(p["amount"] for p in property_taxes if p["resident_db_id"] == 2)
    assert rich_amount > poor_amount


def test_household_with_no_adults_pays_no_property_tax():
    households = [{"id": 1, "family_name": "Orphans", "race": "human"}]
    residents = [_resident(1, 1, age_bracket="child")]
    payments = generate_tax_payments(("town", 1), households, residents, YEAR_START)
    assert payments == []


def test_generate_tax_payments_is_deterministic():
    households = [{"id": 1, "family_name": "Smith", "race": "human"}]
    residents = [_resident(1, 1)]
    p1 = generate_tax_payments(("town", 1), households, residents, YEAR_START)
    p2 = generate_tax_payments(("town", 1), households, residents, YEAR_START)
    assert p1 == p2
