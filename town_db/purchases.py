from datetime import date, timedelta
from typing import Any, Dict, List

from town_shaper.seeding import rng_for

from town_db.goods import GOODS_CATALOG

SHOP_BUILDING_TYPES = {"shop", "tavern", "market_stall"}
WEEKLY_PURCHASE_COUNT_WEIGHTS = [40, 30, 20, 10]  # for 0, 1, 2, 3 purchases


def generate_purchases(
    seed,
    household_rows: List[Dict[str, Any]],
    resident_rows: List[Dict[str, Any]],
    goods_ids: Dict[str, int],
    shop_building_ids: List[int],
    year_start: date,
    weeks: int = 52,
) -> List[Dict[str, Any]]:
    if not shop_building_ids or not goods_ids:
        return []

    rng = rng_for(seed, "db", "purchases")

    sv_by_name = {g["name"]: g["sv"] for g in GOODS_CATALOG if g["name"] in goods_ids}
    price_by_name = {g["name"]: g["typical_price"] for g in GOODS_CATALOG if g["name"] in goods_ids}
    goods_names = list(sv_by_name.keys())
    # SV is the population needed to support one business of this type, so a
    # HIGHER sv means the good is bought more often (bread constantly, jewelry
    # rarely) -- weight directly by sv, not by its reciprocal.
    good_weights = [float(sv_by_name[name]) for name in goods_names]

    residents_by_household: Dict[int, List[Dict[str, Any]]] = {}
    for row in resident_rows:
        if row.get("age_bracket") == "adult":
            residents_by_household.setdefault(row["household_id"], []).append(row)

    purchases: List[Dict[str, Any]] = []
    for week in range(weeks):
        week_start = year_start + timedelta(weeks=week)
        for household in household_rows:
            all_buyers = residents_by_household.get(household["id"], [])
            # A resident who has already died cannot shop this week.
            buyers = [
                r for r in all_buyers
                if r.get("death_date") is None
                or date.fromisoformat(r["death_date"]) >= week_start
            ]
            if not buyers:
                continue
            count = rng.choices([0, 1, 2, 3], weights=WEEKLY_PURCHASE_COUNT_WEIGHTS, k=1)[0]
            for _ in range(count):
                buyer = rng.choice(buyers)
                good_name = rng.choices(goods_names, weights=good_weights, k=1)[0]
                shop_id = rng.choice(shop_building_ids)
                # Expensive goods are bought one at a time; cheap staples in bulk.
                quantity = 1 if price_by_name[good_name] >= 1.0 else rng.randint(1, 5)
                unit_price = round(price_by_name[good_name] * rng.uniform(0.85, 1.15), 2)
                # Cap the within-week day so a buyer who dies mid-week never
                # shops after their own death date.
                max_day_offset = 6
                if buyer.get("death_date") is not None:
                    days_left = (date.fromisoformat(buyer["death_date"]) - week_start).days
                    max_day_offset = min(6, max(0, days_left))
                day_offset = rng.randint(0, max_day_offset)
                purchase_date = week_start + timedelta(days=day_offset)

                purchases.append({
                    "resident_db_id": buyer["db_id"],
                    "shop_building_id": shop_id,
                    "good_id": goods_ids[good_name],
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "total_price": round(unit_price * quantity, 2),
                    "purchase_date": purchase_date.isoformat(),
                })

    return purchases
