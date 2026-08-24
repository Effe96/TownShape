from typing import Any, Dict, List, Tuple

from town_shaper.geometry import distance

STAPLE_CATEGORIES = {"food", "drink", "household", "clothing"}
LUXURY_CATEGORIES = {"luxury"}
TOOLS_CATEGORIES = {"tools"}
POOR_LUXURY_MULTIPLIER = 0.1


def _household_stats(residents: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    stats: Dict[int, Dict[str, Any]] = {}
    for resident in residents:
        household_id = resident["household_id"]
        entry = stats.setdefault(household_id, {"size": 0, "working_adults": 0, "ses": resident["ses"]})
        entry["size"] += 1
        if resident.get("occupation") is not None:
            entry["working_adults"] += 1
    return stats


def _need_weight(stats: Dict[str, Any], category: str) -> float:
    if category in STAPLE_CATEGORIES:
        return float(stats["size"])
    if category in LUXURY_CATEGORIES:
        multiplier = 1.0 if stats["ses"] == "rich" else POOR_LUXURY_MULTIPLIER
        return stats["size"] * multiplier
    if category in TOOLS_CATEGORIES:
        return float(stats["working_adults"])
    return 0.0


def derive_shop_relationships(
    residents: List[Dict[str, Any]], purchases: List[Dict[str, Any]], buildings: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    household_stats = _household_stats(residents)
    household_by_resident = {r["id"]: r["household_id"] for r in residents}
    home_building_by_resident = {
        r["id"]: r["home_building_id"] for r in residents if r.get("home_building_id") is not None
    }
    building_coords = {b["id"]: (b["x"], b["y"]) for b in buildings}

    aggregated: Dict[Tuple[int, int], Dict[str, float]] = {}
    for purchase in purchases:
        resident_id = purchase["resident_id"]
        if resident_id not in home_building_by_resident:
            continue
        key = (resident_id, purchase["shop_building_id"])
        entry = aggregated.setdefault(key, {"purchase_count": 0, "total_spent": 0.0, "weighted_spend": 0.0})
        entry["purchase_count"] += 1
        entry["total_spent"] += purchase["total_price"]
        stats = household_stats[household_by_resident[resident_id]]
        entry["weighted_spend"] += purchase["total_price"] * _need_weight(stats, purchase["category"])

    rows_by_resident: Dict[int, List[Dict[str, Any]]] = {}
    best_by_resident: Dict[int, Tuple[float, int]] = {}

    for (resident_id, shop_building_id), entry in aggregated.items():
        home_coords = building_coords[home_building_by_resident[resident_id]]
        shop_coords = building_coords[shop_building_id]
        dist = distance(home_coords, shop_coords)
        need_score = entry["weighted_spend"]
        customer_score = need_score / (1 + dist)

        row = {
            "resident_id": resident_id,
            "shop_building_id": shop_building_id,
            "purchase_count": entry["purchase_count"],
            "total_spent": entry["total_spent"],
            "distance": dist,
            "need_score": need_score,
            "customer_score": customer_score,
            "is_primary": 0,
        }
        rows_by_resident.setdefault(resident_id, []).append(row)

        current_best = best_by_resident.get(resident_id)
        if current_best is None or customer_score > current_best[0] or (
            customer_score == current_best[0] and shop_building_id < current_best[1]
        ):
            best_by_resident[resident_id] = (customer_score, shop_building_id)

    relationships: List[Dict[str, Any]] = []
    for resident_id, rows in rows_by_resident.items():
        _, best_shop = best_by_resident[resident_id]
        for row in rows:
            row["is_primary"] = 1 if row["shop_building_id"] == best_shop else 0
            relationships.append(row)

    return relationships
