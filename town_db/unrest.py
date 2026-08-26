# town_db/unrest.py
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from town_shaper.seeding import rng_for

from town_db.military import MILITARY_OCCUPATIONS

SKIRMISH_WEEKLY_CHANCE_SCALE = 0.1
POOR_CASUALTY_RATE_SCALE = 0.002
GUARD_CASUALTY_RATE_SCALE = 0.01
SKIRMISH_NAME = "a clash between the poor quarter and the city guard"


def generate_skirmish_events(
    seed, year_start: date, aggression: float, weeks: int = 52,
) -> List[Dict[str, Any]]:
    rng = rng_for(seed, "db", "unrest_events")
    events: List[Dict[str, Any]] = []
    if aggression <= 0:
        return events

    for week in range(weeks):
        week_start = year_start + timedelta(weeks=week)
        if rng.random() >= aggression * SKIRMISH_WEEKLY_CHANCE_SCALE:
            continue
        day_offset = rng.randint(0, 6)
        skirmish_date = week_start + timedelta(days=day_offset)
        events.append({
            "name": SKIRMISH_NAME,
            "skirmish_date": skirmish_date.isoformat(),
            "severity": round(rng.uniform(0.2, 1.0), 2),
        })
    return events


def generate_skirmish_casualties(
    seed,
    resident_rows: List[Dict[str, Any]],
    skirmish_rows: List[Dict[str, Any]],
    reporting_building_id: Optional[int],
) -> List[Dict[str, Any]]:
    if reporting_building_id is None:
        return []

    rng = rng_for(seed, "db", "unrest_casualties")
    deaths: List[Dict[str, Any]] = []

    for skirmish in skirmish_rows:
        severity = skirmish["severity"]
        for row in resident_rows:
            if row["death_date"] is not None:
                continue
            is_guard = row.get("occupation") in MILITARY_OCCUPATIONS
            is_poor_adult = row.get("ses") == "poor" and row.get("age_bracket") == "adult"
            if is_guard:
                rate = severity * GUARD_CASUALTY_RATE_SCALE
            elif is_poor_adult:
                rate = severity * POOR_CASUALTY_RATE_SCALE
            else:
                continue
            if rng.random() >= rate:
                continue

            row["death_date"] = skirmish["skirmish_date"]
            deaths.append({
                "resident_db_id": row["db_id"],
                "death_date": skirmish["skirmish_date"],
                "cause": "skirmish",
                "skirmish_event_id": skirmish["_db_id"],
                "reported_by_building_id": reporting_building_id,
            })

    return deaths
