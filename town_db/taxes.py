from datetime import date, timedelta
from typing import Any, Dict, List

from town_shaper.seeding import rng_for

HEAD_TAX_AMOUNT = 0.5
PROPERTY_TAX_RATE_BY_SES = {"rich": 5.0, "poor": 1.0}


def generate_tax_payments(
    seed,
    household_rows: List[Dict[str, Any]],
    resident_rows: List[Dict[str, Any]],
    year_start: date,
) -> List[Dict[str, Any]]:
    rng = rng_for(seed, "db", "taxes")
    payments: List[Dict[str, Any]] = []

    for row in resident_rows:
        if row.get("age_bracket") != "adult" or row.get("is_noble"):
            continue
        day_offset = rng.randint(0, 364)
        payments.append({
            "resident_db_id": row["db_id"],
            "tax_type": "head_tax",
            "amount": HEAD_TAX_AMOUNT,
            "period": f"{year_start.year}",
            "payment_date": (year_start + timedelta(days=day_offset)).isoformat(),
        })

    residents_by_household: Dict[int, List[Dict[str, Any]]] = {}
    for row in resident_rows:
        if row.get("age_bracket") == "adult":
            residents_by_household.setdefault(row["household_id"], []).append(row)

    for household in household_rows:
        payers = residents_by_household.get(household["id"], [])
        if not payers:
            continue
        payer = rng.choice(payers)
        rate = PROPERTY_TAX_RATE_BY_SES.get(payer["ses"], PROPERTY_TAX_RATE_BY_SES["poor"])
        for quarter in range(4):
            quarter_start = year_start + timedelta(days=quarter * 91)
            day_offset = rng.randint(0, 90)
            payments.append({
                "resident_db_id": payer["db_id"],
                "tax_type": "property_tax",
                "amount": rate,
                "period": f"{year_start.year}-Q{quarter + 1}",
                "payment_date": (quarter_start + timedelta(days=day_offset)).isoformat(),
            })

    return payments
