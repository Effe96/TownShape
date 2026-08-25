import math
from typing import Tuple

from shapely.ops import unary_union

from town_shaper.anchors import place_anchors
from town_shaper.assignment import DEFAULT_RICH_PROPORTION, assign_residents
from town_shaper.buildings import fill_district_buildings
from town_shaper.districts import build_districts
from town_shaper.households import generate_households
from town_shaper.models import Town
from town_shaper.water import generate_water_features

AREA_PER_RESIDENT = 150.0  # square map-units of town area assumed per resident
BUILDING_ID_STRIDE = 100_000


def compute_town_bounds(
    target_population: int, area_per_resident_multiplier: float = 1.0
) -> Tuple[float, float, float, float]:
    area = target_population * AREA_PER_RESIDENT * area_per_resident_multiplier
    side = math.sqrt(area)
    half = side / 2.0
    return (-half, -half, half, half)


def generate_town(
    seed, target_population: int,
    area_per_resident_multiplier: float = 1.0,
    density_multiplier: float = 1.0,
    rich_proportion: float = DEFAULT_RICH_PROPORTION,
    num_rivers: int = 0,
    has_coastline: bool = False,
    has_port: bool = False,
    magic_prevalence: float = 0.0,
) -> Town:
    bounds = compute_town_bounds(target_population, area_per_resident_multiplier)

    water_features = generate_water_features(seed, bounds, num_rivers=num_rivers, has_coastline=has_coastline)
    water_polygon = unary_union([f.polygon for f in water_features]) if water_features else None

    anchors = place_anchors(seed, target_population, bounds, water_polygon=water_polygon, has_port=has_port)
    districts = build_districts(anchors, bounds, water_polygon=water_polygon)

    for district in districts:
        next_building_id = district.id * BUILDING_ID_STRIDE
        buildings = fill_district_buildings(
            district, seed, next_building_id,
            target_population=target_population, density_multiplier=density_multiplier,
            magic_prevalence=magic_prevalence,
        )
        district.buildings = buildings

    households = generate_households(seed, target_population)
    residents = assign_residents(seed, households, districts, rich_proportion=rich_proportion)

    town = Town(seed=seed, target_population=target_population, bounds=bounds)
    town.districts = districts
    town.residents = residents
    town.water_features = water_features
    return town
