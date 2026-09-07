import math
from typing import Dict, List, Tuple

from shapely.ops import unary_union

from town_shaper.anchors import place_anchors
from town_shaper.assignment import DEFAULT_RICH_PROPORTION, assign_residents
from town_shaper.blocks import (
    DEFAULT_HARD_CAP_AREA, HARD_CAP_AREA_MULTIPLIER, LOT_DEPTH_BY_ZONE, LOT_FRONTAGE_BY_ZONE, RESIDENTIAL_SLACK,
    Polygon, compute_district_blocks, generate_blocks_and_buildings,
)
from town_shaper.buildings import BUILDING_HOME_CAPACITY, fill_district_buildings
from town_shaper.districts import build_districts
from town_shaper.geometry import polygon_area
from town_shaper.households import AVERAGE_HOUSEHOLD_SIZE, estimate_household_counts, generate_households
from town_shaper.models import Town, ZoneType
from town_shaper.roads import generate_road_network
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
    road_network = generate_road_network(anchors, bounds, water_polygon=water_polygon)

    notable_building_counts: Dict[str, int] = {}

    # Pass 1: block geometry + total area for every residential district
    # (cached, not recomputed in pass 2) -- lets the leaf target area be
    # derived from real household demand instead of a fixed lot constant.
    residential_zone_types = (ZoneType.POOR_RESIDENTIAL, ZoneType.RICH_RESIDENTIAL)
    blocks_by_district_id: Dict[int, List[Polygon]] = {}
    block_area_by_zone: Dict[ZoneType, float] = {zt: 0.0 for zt in residential_zone_types}
    for district in districts:
        if district.zone_type in residential_zone_types:
            # skip_block_subdivision=True: residential blocks are already
            # smaller than the demand-driven leaf target_area computed below,
            # so subdividing into blocks here first would leave
            # organic_subdivide nothing to do -- each block would become
            # exactly one leaf/building, and count would collapse to block
            # count, disconnected from household demand. One "block" per
            # polygon part (inset+jaggified only) instead, and let
            # organic_subdivide (with the real target_area) do the real
            # subdivision work.
            district_blocks = compute_district_blocks(district, seed, skip_block_subdivision=True)
            blocks_by_district_id[district.id] = district_blocks
            block_area_by_zone[district.zone_type] += sum(polygon_area(b) for b in district_blocks)

    poor_household_count, rich_household_count = estimate_household_counts(target_population, rich_proportion)
    # Higher density_multiplier means more, smaller buildings (matches the
    # non-residential path's LOT_FRONTAGE_BY_ZONE[zone]/density_multiplier,
    # which shrinks target_area -- and so raises count -- as density rises).
    # Multiplying (not dividing) here raises poor/rich_target_count as
    # density rises, which lowers residential_target_area below -- consistent.
    effective_slack = RESIDENTIAL_SLACK * density_multiplier
    # household counts are households, but BUILDING_HOME_CAPACITY is a
    # resident-slot (person) count -- convert households to residents first,
    # or capacity is under-provisioned by ~AVERAGE_HOUSEHOLD_SIZE.
    poor_target_count = max(1, math.ceil(
        poor_household_count * AVERAGE_HOUSEHOLD_SIZE * effective_slack / BUILDING_HOME_CAPACITY["residence"]))
    rich_target_count = max(1, math.ceil(
        rich_household_count * AVERAGE_HOUSEHOLD_SIZE * effective_slack / BUILDING_HOME_CAPACITY["manor"]))

    poor_min_leaf_area = LOT_FRONTAGE_BY_ZONE[ZoneType.POOR_RESIDENTIAL] * LOT_DEPTH_BY_ZONE[ZoneType.POOR_RESIDENTIAL]
    rich_min_leaf_area = LOT_FRONTAGE_BY_ZONE[ZoneType.RICH_RESIDENTIAL] * LOT_DEPTH_BY_ZONE[ZoneType.RICH_RESIDENTIAL]
    residential_target_area = {
        ZoneType.POOR_RESIDENTIAL: max(poor_min_leaf_area, block_area_by_zone[ZoneType.POOR_RESIDENTIAL] / poor_target_count),
        ZoneType.RICH_RESIDENTIAL: max(rich_min_leaf_area, block_area_by_zone[ZoneType.RICH_RESIDENTIAL] / rich_target_count),
    }

    for district in districts:
        next_building_id = district.id * BUILDING_ID_STRIDE
        if district.zone_type == ZoneType.FARMLAND_EDGE:
            buildings = fill_district_buildings(
                district, seed, next_building_id,
                target_population=target_population, density_multiplier=density_multiplier,
                magic_prevalence=magic_prevalence,
            )
        elif district.zone_type in residential_zone_types:
            buildings = generate_blocks_and_buildings(
                district, seed, next_building_id,
                target_population=target_population, density_multiplier=density_multiplier,
                magic_prevalence=magic_prevalence, notable_building_counts=notable_building_counts,
                blocks=blocks_by_district_id[district.id],
                target_area=residential_target_area[district.zone_type],
                # DEFAULT_HARD_CAP_AREA (sized off POOR_RESIDENTIAL's fixed lot
                # constant) can be smaller than the demand-driven target_area
                # above once a zone's real household count is low relative to
                # its block area -- a fixed hard cap below the soft target
                # forces organic_subdivide's hard-cap branch to dominate on
                # every leaf, silently discarding the household-driven sizing
                # this whole pass exists to compute. Scale the cap off the
                # actual target instead, at the same ratio DEFAULT_HARD_CAP_AREA
                # itself uses.
                hard_cap_area=max(
                    DEFAULT_HARD_CAP_AREA, residential_target_area[district.zone_type] * HARD_CAP_AREA_MULTIPLIER,
                ),
            )
        else:
            buildings = generate_blocks_and_buildings(
                district, seed, next_building_id,
                target_population=target_population, density_multiplier=density_multiplier,
                magic_prevalence=magic_prevalence, notable_building_counts=notable_building_counts,
            )
        district.buildings = buildings

    households = generate_households(seed, target_population)
    residents = assign_residents(seed, households, districts, rich_proportion=rich_proportion)

    town = Town(seed=seed, target_population=target_population, bounds=bounds)
    town.districts = districts
    town.residents = residents
    town.water_features = water_features
    town.road_network = road_network
    return town
