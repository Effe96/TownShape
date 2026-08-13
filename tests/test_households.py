from collections import Counter

from town_shaper.households import generate_households


def test_generate_households_is_deterministic():
    first = generate_households(("town", 1), target_population=3000)
    second = generate_households(("town", 1), target_population=3000)
    assert [(h.id, h.has_spouse, h.child_count) for h in first] == \
           [(h.id, h.has_spouse, h.child_count) for h in second]


def test_generate_households_produces_at_least_one_household():
    households = generate_households(("town", 1), target_population=3000)
    assert len(households) > 0


def test_generate_households_child_counts_stay_in_expected_range():
    households = generate_households(("town", 1), target_population=3000)
    for household in households:
        assert 0 <= household.child_count <= 5


def test_generate_households_child_count_distribution_is_weighted_toward_fewer_children():
    households = generate_households(("town", 1), target_population=3000)
    counts = Counter(h.child_count for h in households)
    # 0 and 1 children combined should be the plurality, matching the
    # 20/30/15/10/10/15 weighting (mirrors popgen.py's family-size shape).
    assert counts[0] + counts[1] > counts[4] + counts[5]
