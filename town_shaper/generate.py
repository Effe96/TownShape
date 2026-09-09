import math
from typing import Tuple

from town_shaper.assignment import DEFAULT_RICH_PROPORTION, assign_residents
from town_shaper.households import generate_households
from town_shaper.models import RoadNetwork, Town

AREA_PER_RESIDENT = 150.0  # square map-units of town area assumed per resident
BUILDING_ID_STRIDE = 100_000  # still read by settlemaker_bridge.parse_geojson for building id derivation


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
    # Lazy import: settlemaker_bridge.pipeline imports compute_town_bounds
    # from this module, so a top-level import here would be circular.
    from settlemaker_bridge.pipeline import generate_via_settlemaker

    bounds = compute_town_bounds(target_population, area_per_resident_multiplier)

    # density_multiplier and magic_prevalence have no settlemaker equivalent
    # (Owner decision 2026-09-08, Phase 2 kickoff -- see this plan's Global
    # Constraints): settlemaker now owns ward/building layout entirely, so
    # neither parameter influences generated geometry any more. Both stay
    # accepted here (and in generate_town_database/TownParameters) purely
    # for API compatibility.
    districts, buildings, water_features, svg = generate_via_settlemaker(
        seed, target_population,
        area_per_resident_multiplier=area_per_resident_multiplier,
        num_rivers=num_rivers, has_coastline=has_coastline, has_port=has_port,
    )

    households = generate_households(seed, target_population)
    residents = assign_residents(seed, households, districts, rich_proportion=rich_proportion)

    town = Town(seed=seed, target_population=target_population, bounds=bounds)
    town.districts = districts
    town.residents = residents
    town.water_features = water_features
    # settlemaker's `street` layer isn't mapped onto RoadNode/RoadEdge (see
    # the design spec's "What this deletes" section) -- an empty network,
    # not None, so town_db.generate's road_nodes/road_edges insert loops
    # (which iterate .nodes/.edges) don't need a None-guard.
    town.road_network = RoadNetwork()
    town.svg = svg
    return town
