# town_db/economy.py
from typing import Any, Dict, List, Optional, Tuple

from town_shaper.seeding import rng_for

from town_db.succession import primary_occupation_info

YEAR_LENGTH_DAYS = 365

INCOME_TIER_BY_ROLE = {"unemployed": 0.5, "apprentice": 1.0, "primary": 2.5, "noble": 5.0}
SES_INCOME_MULTIPLIER = {"rich": 1.3, "poor": 1.0}
INCOME_VARIATION_RANGE: Tuple[float, float] = (0.7, 1.3)
STARTING_WEALTH_BY_SES = {"rich": 500.0, "poor": 50.0}


def daily_income(
    seed,
    resident_id: int,
    occupation: Optional[str],
    building_type: Optional[str],
    ses: str,
    is_noble: bool,
) -> float:
    if is_noble:
        tier = "noble"
    elif occupation is None:
        tier = "unemployed"
    else:
        is_primary, _ = primary_occupation_info(building_type, occupation)
        tier = "primary" if is_primary else "apprentice"
    variation = rng_for(seed, "db", "income", resident_id).uniform(*INCOME_VARIATION_RANGE)
    return INCOME_TIER_BY_ROLE[tier] * SES_INCOME_MULTIPLIER.get(ses, 1.0) * variation


def compute_household_income(
    seed,
    household_resident_rows: List[Dict[str, Any]],
    building_type_by_id: Dict[int, str],
) -> float:
    total = 0.0
    for row in household_resident_rows:
        if row.get("death_date") is not None or row.get("age_bracket") != "adult":
            continue
        workplace_id = row.get("workplace_building_id")
        building_type = building_type_by_id.get(workplace_id) if workplace_id is not None else None
        total += daily_income(
            seed, row["db_id"], row.get("occupation"), building_type, row["ses"], bool(row.get("is_noble")),
        )
    return total * YEAR_LENGTH_DAYS


def household_ses(household_resident_rows: List[Dict[str, Any]]) -> str:
    counts: Dict[str, int] = {}
    for row in household_resident_rows:
        counts[row["ses"]] = counts.get(row["ses"], 0) + 1
    if not counts:
        return "poor"
    # Highest count wins; ties (including the empty-vs-nonzero non-issue above) break toward
    # "poor" -- the safer default -- via sort key (False < True, so "poor" sorts first on a tie).
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0] != "poor"))[0][0]


def starting_wealth_by_ses(ses: str) -> float:
    return STARTING_WEALTH_BY_SES.get(ses, STARTING_WEALTH_BY_SES["poor"])
