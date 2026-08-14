from datetime import date
from typing import Tuple

ADULT_AGE_RANGE: Tuple[int, int] = (18, 90)
CHILD_AGE_RANGE: Tuple[int, int] = (0, 17)
# Adults who actually live with children are drawn from a parent-plausible
# band instead of the full adult pyramid, so households with children reliably
# contain a fertile-age parent.
PARENT_AGE_RANGE: Tuple[int, int] = (20, 55)
AGE_DECAY_RATE = 0.97


def _weighted_age(rng, min_age: int, max_age: int, decay_rate: float = AGE_DECAY_RATE) -> int:
    ages = list(range(min_age, max_age + 1))
    weights = [decay_rate ** (age - min_age) for age in ages]
    return rng.choices(ages, weights=weights, k=1)[0]


def draw_age(rng, age_bracket: str, is_parent: bool = False) -> int:
    if age_bracket == "child":
        return _weighted_age(rng, *CHILD_AGE_RANGE)
    if is_parent:
        return _weighted_age(rng, *PARENT_AGE_RANGE)
    return _weighted_age(rng, *ADULT_AGE_RANGE)


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def birth_date_from_age(reference_date: date, age: int) -> date:
    target_year = reference_date.year - age
    month = reference_date.month
    day = reference_date.day
    if month == 2 and day == 29 and not _is_leap_year(target_year):
        day = 28
    return date(target_year, month, day)


def age_on(birth_date: date, on_date: date) -> int:
    age = on_date.year - birth_date.year
    if (on_date.month, on_date.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age
