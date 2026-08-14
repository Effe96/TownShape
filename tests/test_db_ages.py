from datetime import date

from town_shaper.seeding import rng_for
from town_db.ages import ADULT_AGE_RANGE, CHILD_AGE_RANGE, age_on, birth_date_from_age, draw_age


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
