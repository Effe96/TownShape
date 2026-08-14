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
    good_weights = [1.0 / sv_by_name[name] for name in goods_names]

    residents_by_household: Dict[int, List[Dict[str, Any]]] = {}
    for row in resident_rows:
        if row.get("age_bracket") == "adult":
            residents_by_household.setdefault(row["household_id"], []).append(row)

    purchases: List[Dict[str, Any]] = []
    for week in range(weeks):
        week_start = year_start + timedelta(weeks=week)
        for household in household_rows:
            buyers = residents_by_household.get(household["id"], [])
            if not buyers:
                continue
            count = rng.choices([0, 1, 2, 3], weights=WEEKLY_PURCHASE_COUNT_WEIGHTS, k=1)[0]
            for _ in range(count):
                buyer = rng.choice(buyers)
                good_name = rng.choices(goods_names, weights=good_weights, k=1)[0]
                shop_id = rng.choice(shop_building_ids)
                quantity = rng.randint(1, 5)
                unit_price = round(price_by_name[good_name] * rng.uniform(0.85, 1.15), 2)
                day_offset = rng.randint(0, 6)
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
