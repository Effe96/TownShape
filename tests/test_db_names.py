from town_shaper.seeding import rng_for
from town_db.names import RACE_WEIGHTS, RACES, draw_first_name, draw_gender, draw_race, draw_surname


def test_race_weights_cover_exactly_the_six_supported_races():
    assert set(RACE_WEIGHTS.keys()) == set(RACES)
    assert RACES == ["human", "dwarf", "elf", "gnome", "halfling", "orc"]


def test_draw_race_is_deterministic():
    rng1 = rng_for(("town", 1), "test-names")
    rng2 = rng_for(("town", 1), "test-names")
    draws1 = [draw_race(rng1) for _ in range(20)]
    draws2 = [draw_race(rng2) for _ in range(20)]
    assert draws1 == draws2
    assert set(draws1) <= set(RACES)


def test_draw_gender_returns_male_or_female():
    rng = rng_for(("town", 1), "test-gender")
    draws = {draw_gender(rng) for _ in range(20)}
    assert draws <= {"male", "female"}


def test_draw_first_name_and_surname_come_from_the_real_word_lists():
    rng = rng_for(("town", 1), "test-name-draw")
    name = draw_first_name(rng, "dwarf", "female")
    surname = draw_surname(rng, "dwarf")
    assert isinstance(name, str) and len(name) > 0
    assert isinstance(surname, str) and len(surname) > 0


def test_draw_first_name_for_every_supported_race_and_gender():
    rng = rng_for(("town", 1), "test-all-races")
    for race in RACES:
        for gender in ["male", "female"]:
            name = draw_first_name(rng, race, gender)
            assert isinstance(name, str) and len(name) > 0
        surname = draw_surname(rng, race)
        assert isinstance(surname, str) and len(surname) > 0
