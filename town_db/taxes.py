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
        # A resident who dies partway through the year can only have paid
        # their head tax on or before their death date.
        max_day_offset = 364
        if row.get("death_date") is not None:
            days_alive = (date.fromisoformat(row["death_date"]) - year_start).days
            if days_alive < 0:
                continue
            max_day_offset = min(max_day_offset, days_alive)
        day_offset = rng.randint(0, max_day_offset)
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
        payer_death_date = (
            date.fromisoformat(payer["death_date"]) if payer.get("death_date") else None
        )
        for quarter in range(4):
            quarter_start = year_start + timedelta(days=quarter * 91)
            # A payer who died before the quarter began pays nothing for it;
            # one who dies mid-quarter can only pay up to their death date.
            if payer_death_date is not None and quarter_start > payer_death_date:
                continue
            max_day_offset = 90
            if payer_death_date is not None:
                days_into_quarter = (payer_death_date - quarter_start).days
                max_day_offset = min(max_day_offset, max(0, days_into_quarter))
            day_offset = rng.randint(0, max_day_offset)
            payments.append({
                "resident_db_id": payer["db_id"],
                "tax_type": "property_tax",
                "amount": rate,
                "period": f"{year_start.year}-Q{quarter + 1}",
                "payment_date": (quarter_start + timedelta(days=day_offset)).isoformat(),
            })

    return payments
