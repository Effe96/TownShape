# town_db/households.py
from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Tuple

from town_shaper.seeding import rng_for

from town_db.ages import birth_date_from_age, draw_age
from town_db.names import RACE_WEIGHTS, draw_first_name, draw_gender, draw_race, draw_surname

DEFAULT_INTERMARRIAGE_RATE = 0.08
NOBLE_POPULATION_RATIO = 200


def _group_by_household(residents) -> Dict[int, List[Any]]:
    groups: Dict[int, List[Any]] = defaultdict(list)
    for r in residents:
        groups[r.household_id].append(r)
    return groups


def build_households_and_residents(
    town,
    seed,
    reference_date: date,
    race_weights: Dict[str, float] = RACE_WEIGHTS,
    intermarriage_rate: float = DEFAULT_INTERMARRIAGE_RATE,
    magic_prevalence: float = 0.0,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rng = rng_for(seed, "db", "households")

    groups = _group_by_household(town.residents)
    household_rows: List[Dict[str, Any]] = []
    resident_rows: List[Dict[str, Any]] = []

    for household_id in sorted(groups):
        members = groups[household_id]
        has_children = any(m.age_bracket == "child" for m in members)
        primary_race = draw_race(rng, race_weights)
        surname = draw_surname(rng, primary_race)
        household_rows.append({"id": household_id, "family_name": surname, "race": primary_race})

        adults = [m for m in members if m.age_bracket == "adult"]
        spouse = adults[1] if len(adults) > 1 else None
        spouse_race = primary_race
        if spouse is not None and rng.random() < intermarriage_rate:
            other_races = [r for r in race_weights if r != primary_race]
            if other_races:
                spouse_race = rng.choice(other_races)

        race_by_member_id = {}
        for member in members:
            if spouse is not None and member.id == spouse.id:
                race_by_member_id[member.id] = spouse_race
            elif member.age_bracket == "child":
                race_by_member_id[member.id] = rng.choice([primary_race, spouse_race])
            else:
                race_by_member_id[member.id] = primary_race

        for member in members:
            race = race_by_member_id[member.id]
            gender = draw_gender(rng)
            first_name = draw_first_name(rng, race, gender)
            is_parent = has_children and member.age_bracket == "adult"
            age = draw_age(rng, member.age_bracket, is_parent=is_parent)
            birth_date = birth_date_from_age(reference_date, age)

            resident_rows.append({
                "town_shaper_id": member.id,
                "household_id": household_id,
                "first_name": first_name,
                "last_name": surname,
                "gender": gender,
                "race": race,
                "birth_date": birth_date.isoformat(),
                "death_date": None,
                "ses": member.ses.value,
                "is_noble": False,
                "has_magical_talent": False,
                "home_building_id": member.home_building_id,
                "workplace_building_id": member.workplace_building_id,
                "occupation": member.occupation,
                "age_bracket": member.age_bracket,
            })

    _tag_nobility(rng, resident_rows, town.target_population)
    _tag_magical_talent(rng, resident_rows, magic_prevalence)

    return household_rows, resident_rows


def _tag_nobility(rng, resident_rows: List[Dict[str, Any]], target_population: int) -> None:
    noble_count = max(0, round(target_population / NOBLE_POPULATION_RATIO))
    eligible = [r for r in resident_rows if r["ses"] == "rich" and r["age_bracket"] == "adult"]
    rng.shuffle(eligible)
    for row in eligible[:noble_count]:
        row["is_noble"] = True


def _tag_magical_talent(rng, resident_rows: List[Dict[str, Any]], magic_prevalence: float) -> None:
    for row in resident_rows:
        row["has_magical_talent"] = rng.random() < magic_prevalence
