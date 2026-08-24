import pytest

from town_narrative.parameters import TownParameters


def test_defaults_match_current_hardcoded_behavior():
    params = TownParameters(seed="town-1", target_population=1000)
    assert params.area_per_resident_multiplier == 1.0
    assert params.density_multiplier == 1.0
    assert params.rich_proportion == 0.05


def test_valid_parameters_construct_successfully():
    params = TownParameters(
        seed="town-1", target_population=1000,
        area_per_resident_multiplier=2.0, density_multiplier=0.5, rich_proportion=0.2,
    )
    assert params.target_population == 1000
    assert params.area_per_resident_multiplier == 2.0
    assert params.density_multiplier == 0.5
    assert params.rich_proportion == 0.2


def test_non_positive_target_population_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=0)
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=-5)


def test_non_positive_area_multiplier_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, area_per_resident_multiplier=0.0)
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, area_per_resident_multiplier=-1.0)


def test_non_positive_density_multiplier_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, density_multiplier=0.0)
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, density_multiplier=-1.0)


def test_rich_proportion_out_of_range_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, rich_proportion=1.5)
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, rich_proportion=-0.1)


def test_rich_proportion_boundary_values_are_valid():
    TownParameters(seed="town-1", target_population=1000, rich_proportion=0.0)
    TownParameters(seed="town-1", target_population=1000, rich_proportion=1.0)
