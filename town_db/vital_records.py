# town_db/vital_records.py
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from town_shaper.seeding import rng_for

from town_db.ages import age_on
from town_db.names import draw_first_name, draw_gender

DEFAULT_BIRTH_RATE = 0.09
DEFAULT_DEATH_RATE_BY_AGE = {
    "infant": 0.15,
    "child": 0.02,
    "adult": 0.01,
    "elderly": 0.06,
}
DISEASE_DEATH_MULTIPLIER = 4.0
DISEASE_EVENT_CHANCE = 0.3
FERTILE_AGE_RANGE = (16, 45)


def _age_category(age: int) -> str:
    if age == 0:
        return "infant"
    if age < 18:
        return "child"
    if age < 60:
        return "adult"
    return "elderly"


def generate_disease_events(
    seed, year_start: date, chance: float = DISEASE_EVENT_CHANCE
) -> List[Dict[str, Any]]:
    rng = rng_for(seed, "db", "disease_events")
    if rng.random() >= chance:
        return []
    start_offset = rng.randint(0, 300)
    duration = rng.randint(14, 90)
    start = year_start + timedelta(days=start_offset)
    return [{
        "name": "an outbreak of fever",
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=duration)).isoformat(),
        "affected_zone_type": None,
        "severity": round(rng.uniform(0.3, 1.0), 2),
    }]


def _active_disease(disease_rows: List[Dict[str, Any]], on_date: date, zone_type: Optional[str]):
    for event in disease_rows:
        start = date.fromisoformat(event["start_date"])
        end = date.fromisoformat(event["end_date"])
        if start <= on_date <= end:
            if event["affected_zone_type"] is None or event["affected_zone_type"] == zone_type:
                return event
    return None


def generate_births_and_deaths(
    seed,
    household_rows: List[Dict[str, Any]],
    resident_rows: List[Dict[str, Any]],
    disease_rows: List[Dict[str, Any]],
    year_start: date,
    temple_building_id: Optional[int],
    healer_building_id: Optional[int],
    birth_rate: float = DEFAULT_BIRTH_RATE,
    death_rate_by_age: Dict[str, float] = DEFAULT_DEATH_RATE_BY_AGE,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    rng = rng_for(seed, "db", "vital_records")
    reporting_building = temple_building_id if temple_building_id is not None else healer_building_id

    residents_by_household: Dict[int, List[Dict[str, Any]]] = {}
    for row in resident_rows:
        residents_by_household.setdefault(row["household_id"], []).append(row)

    births: List[Dict[str, Any]] = []
    new_resident_rows: List[Dict[str, Any]] = []

    if reporting_building is not None:
        for household in household_rows:
            members = residents_by_household.get(household["id"], [])
            adults = [m for m in members if m.get("age_bracket") == "adult" and m["death_date"] is None]
            mother = next(
                (m for m in adults if m["gender"] == "female"
                 and FERTILE_AGE_RANGE[0] <= age_on(date.fromisoformat(m["birth_date"]), year_start) <= FERTILE_AGE_RANGE[1]),
                None,
            )
            if mother is None or rng.random() >= birth_rate:
                continue
            father = next((m for m in adults if m is not mother), None)

            day_offset = rng.randint(0, 364)
            birth_date = year_start + timedelta(days=day_offset)
            child_race = rng.choice([mother["race"], father["race"]]) if father else mother["race"]
            child_gender = draw_gender(rng)
            child_first_name = draw_first_name(rng, child_race, child_gender)

            new_resident_rows.append({
                "household_id": household["id"],
                "first_name": child_first_name,
                "last_name": household["family_name"],
                "gender": child_gender,
                "race": child_race,
                "birth_date": birth_date.isoformat(),
                "death_date": None,
                "ses": mother["ses"],
                "is_noble": False,
                "home_building_id": mother["home_building_id"],
                "home_zone_type": mother.get("home_zone_type"),
                "workplace_building_id": None,
                "occupation": None,
                "age_bracket": "child",
            })
            births.append({
                "_mother_db_id": mother["db_id"],
                "_father_db_id": father["db_id"] if father else None,
                "birth_date": birth_date.isoformat(),
                "reported_by_building_id": reporting_building,
            })

    deaths: List[Dict[str, Any]] = []
    if reporting_building is not None:
        for row in resident_rows:
            if row["death_date"] is not None:
                continue
            age = age_on(date.fromisoformat(row["birth_date"]), year_start)
            category = _age_category(age)
            base_rate = death_rate_by_age[category]

            day_offset = rng.randint(0, 364)
            candidate_death_date = year_start + timedelta(days=day_offset)

            disease = _active_disease(disease_rows, candidate_death_date, row.get("home_zone_type"))
            rate = base_rate
            if disease is not None:
                rate = min(1.0, base_rate * DISEASE_DEATH_MULTIPLIER * disease["severity"])

            if rng.random() >= rate:
                continue

            row["death_date"] = candidate_death_date.isoformat()

            if disease is not None:
                cause = "plague"
            elif category == "elderly":
                cause = rng.choice(["old age", "illness"])
            else:
                cause = rng.choice(["illness", "accident", "childbirth"])

            deaths.append({
                "resident_db_id": row["db_id"],
                "death_date": candidate_death_date.isoformat(),
                "cause": cause,
                "disease_event_id": disease["_db_id"] if disease is not None else None,
                "reported_by_building_id": reporting_building,
            })

    return births, deaths, new_resident_rows
