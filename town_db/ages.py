from datetime import date
from typing import Tuple

ADULT_AGE_RANGE: Tuple[int, int] = (18, 90)
CHILD_AGE_RANGE: Tuple[int, int] = (0, 17)
AGE_DECAY_RATE = 0.97


def _weighted_age(rng, min_age: int, max_age: int, decay_rate: float = AGE_DECAY_RATE) -> int:
    ages = list(range(min_age, max_age + 1))
    weights = [decay_rate ** (age - min_age) for age in ages]
    return rng.choices(ages, weights=weights, k=1)[0]


def draw_age(rng, age_bracket: str) -> int:
    if age_bracket == "child":
        return _weighted_age(rng, *CHILD_AGE_RANGE)
    return _weighted_age(rng, *ADULT_AGE_RANGE)


def birth_date_from_age(reference_date: date, age: int) -> date:
    return date(reference_date.year - age, reference_date.month, reference_date.day)


def age_on(birth_date: date, on_date: date) -> int:
    age = on_date.year - birth_date.year
    if (on_date.month, on_date.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age
