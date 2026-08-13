# tests/test_seeding.py
from town_shaper.seeding import derive_seed, rng_for


def test_derive_seed_is_deterministic():
    assert derive_seed(("town", 1), "anchors") == derive_seed(("town", 1), "anchors")


def test_derive_seed_differs_by_path():
    assert derive_seed(("town", 1), "anchors") != derive_seed(("town", 1), "buildings")


def test_rng_for_produces_identical_sequences_for_same_path():
    rng1 = rng_for(("town", 1), "anchors", 3)
    rng2 = rng_for(("town", 1), "anchors", 3)
    assert [rng1.random() for _ in range(5)] == [rng2.random() for _ in range(5)]


def test_rng_for_produces_different_sequences_for_different_paths():
    rng1 = rng_for(("town", 1), "anchors", 3)
    rng2 = rng_for(("town", 1), "anchors", 4)
    assert [rng1.random() for _ in range(5)] != [rng2.random() for _ in range(5)]


def test_rng_for_does_not_touch_global_random_state():
    import random
    random.seed(12345)
    expected = random.random()
    random.seed(12345)
    rng_for(("town", 1), "anchors")
    assert random.random() == expected
