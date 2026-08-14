from datetime import date

from town_shaper.seeding import rng_for
from town_db.ages import (
    ADULT_AGE_RANGE,
    CHILD_AGE_RANGE,
    PARENT_AGE_RANGE,
    age_on,
    birth_date_from_age,
    draw_age,
)


def test_draw_age_stays_within_bracket_ranges():
    rng = rng_for(("town", 1), "test-ages")
    for _ in range(100):
        adult_age = draw_age(rng, "adult")
        assert ADULT_AGE_RANGE[0] <= adult_age <= ADULT_AGE_RANGE[1]
        child_age = draw_age(rng, "child")
        assert CHILD_AGE_RANGE[0] <= child_age <= CHILD_AGE_RANGE[1]


def test_draw_age_is_weighted_toward_younger_ages():
    rng = rng_for(("town", 1), "test-ages-weight")
    ages = [draw_age(rng, "adult") for _ in range(500)]
    young = sum(1 for a in ages if a < 40)
    old = sum(1 for a in ages if a >= 70)
    assert young > old


def test_birth_date_from_age_subtracts_years():
    reference = date(1300, 1, 1)
    assert birth_date_from_age(reference, 25) == date(1275, 1, 1)
    assert birth_date_from_age(reference, 0) == date(1300, 1, 1)


def test_age_on_computes_whole_years_elapsed():
    assert age_on(date(1275, 6, 15), date(1300, 1, 1)) == 24
    assert age_on(date(1275, 1, 1), date(1300, 1, 1)) == 25
    assert age_on(date(1300, 1, 1), date(1300, 1, 1)) == 0


def test_draw_age_with_is_parent_stays_inside_the_parent_plausible_range():
    rng = rng_for(("town", 1), "test-parent-ages")
    for _ in range(300):
        age = draw_age(rng, "adult", is_parent=True)
        assert PARENT_AGE_RANGE[0] <= age <= PARENT_AGE_RANGE[1]


def test_draw_age_ignores_is_parent_for_children():
    rng = rng_for(("town", 1), "test-parent-child-ages")
    for _ in range(100):
        age = draw_age(rng, "child", is_parent=True)
        assert CHILD_AGE_RANGE[0] <= age <= CHILD_AGE_RANGE[1]


def test_birth_date_from_age_clamps_feb_29_reference_in_non_leap_birth_years():
    reference = date(1304, 2, 29)  # 1304 is a leap year
    # age 4 -> target year 1300, which is NOT a leap year (1300 % 100 == 0, 1300 % 400 != 0)
    result = birth_date_from_age(reference, 4)
    assert result == date(1300, 2, 28)
    # age 8 -> target year 1296, which IS a leap year -> no clamping needed
    assert birth_date_from_age(reference, 8) == date(1296, 2, 29)
