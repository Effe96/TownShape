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


def test_water_defaults_are_no_water():
    params = TownParameters(seed="town-1", target_population=1000)
    assert params.num_rivers == 0
    assert params.has_coastline is False
    assert params.has_port is False


def test_negative_num_rivers_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, num_rivers=-1)


def test_zero_num_rivers_is_valid():
    TownParameters(seed="town-1", target_population=1000, num_rivers=0)


def test_has_port_without_water_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, has_port=True)
    with pytest.raises(ValueError):
        TownParameters(
            seed="town-1", target_population=1000, has_port=True, num_rivers=0, has_coastline=False,
        )


def test_has_port_with_river_is_valid():
    TownParameters(seed="town-1", target_population=1000, has_port=True, num_rivers=1)


def test_has_port_with_coastline_is_valid():
    TownParameters(seed="town-1", target_population=1000, has_port=True, has_coastline=True)


def test_magic_prevalence_default_is_zero():
    params = TownParameters(seed="town-1", target_population=1000)
    assert params.magic_prevalence == 0.0


def test_magic_prevalence_out_of_range_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, magic_prevalence=1.5)
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, magic_prevalence=-0.1)


def test_magic_prevalence_boundary_values_are_valid():
    TownParameters(seed="town-1", target_population=1000, magic_prevalence=0.0)
    TownParameters(seed="town-1", target_population=1000, magic_prevalence=1.0)


def test_aggression_default_is_zero():
    params = TownParameters(seed="town-1", target_population=1000)
    assert params.aggression == 0.0


def test_aggression_out_of_range_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, aggression=1.5)
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, aggression=-0.1)


def test_aggression_boundary_values_are_valid():
    TownParameters(seed="town-1", target_population=1000, aggression=0.0)
    TownParameters(seed="town-1", target_population=1000, aggression=1.0)
