from typing import List, Tuple

from town_shaper.models import Household
from town_shaper.seeding import rng_for

AVERAGE_HOUSEHOLD_SIZE = 3.5
SPOUSE_CHANCE = 0.7
CHILD_COUNT_WEIGHTS = [20, 30, 15, 10, 10, 15]  # for 0, 1, 2, 3, 4, 5 children


def _sample_child_count(rng) -> int:
    return rng.choices(range(len(CHILD_COUNT_WEIGHTS)), weights=CHILD_COUNT_WEIGHTS, k=1)[0]


def generate_households(town_seed, target_population: int) -> List[Household]:
    rng = rng_for(town_seed, "households")
    target_household_count = max(1, round(target_population / AVERAGE_HOUSEHOLD_SIZE))

    households: List[Household] = []
    total_members = 0
    household_id = 0
    while household_id < target_household_count and total_members < target_population:
        has_spouse = rng.random() < SPOUSE_CHANCE
        child_count = _sample_child_count(rng)
        households.append(Household(id=household_id, has_spouse=has_spouse, child_count=child_count))
        total_members += 1 + (1 if has_spouse else 0) + child_count
        household_id += 1

    return households


def estimate_household_counts(target_population: int, rich_proportion: float) -> Tuple[int, int]:
    """Analytical (non-random) estimate of (poor_count, rich_count)
    households, using the same AVERAGE_HOUSEHOLD_SIZE-based total
    generate_households() derives internally, so building generation can
    size residential lots against real demand before any household or
    resident object exists. This is an ESTIMATE, not an exact prediction
    of what generate_households() will produce: real household sizes vary
    (spouse/child counts) and that function can stop slightly early once
    target_population is reached, so its actual household count can come
    in a bit under this formula's total -- callers that use this for
    sizing (town_shaper/blocks.py) already apply their own slack margin
    to absorb that, so an exact match isn't required here."""
    target_household_count = max(1, round(target_population / AVERAGE_HOUSEHOLD_SIZE))
    rich_count = round(target_household_count * rich_proportion)
    poor_count = target_household_count - rich_count
    return poor_count, rich_count
