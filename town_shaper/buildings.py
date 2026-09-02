# town_shaper/buildings.py
import math
from typing import Dict, List, Tuple

from town_shaper.geometry import distance, point_in_polygon, polygon_area
from town_shaper.models import Building, District, JobVacancy, ZoneType
from town_shaper.seeding import rng_for

BUILDING_DENSITY_PER_AREA: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 1 / 550,
    ZoneType.MERCHANT: 1 / 220,
    ZoneType.RICH_RESIDENTIAL: 1 / 500,
    ZoneType.POOR_RESIDENTIAL: 1 / 1000,
    ZoneType.FARMLAND_EDGE: 1 / 600,
    ZoneType.PORT: 1 / 250,
}

MIN_BUILDING_SPACING: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 15.0,
    ZoneType.MERCHANT: 8.0,
    ZoneType.RICH_RESIDENTIAL: 12.0,
    ZoneType.POOR_RESIDENTIAL: 5.0,
    ZoneType.FARMLAND_EDGE: 20.0,
    ZoneType.PORT: 8.0,
}

BUILDING_TYPES_BY_ZONE: Dict[ZoneType, Dict[str, float]] = {
    ZoneType.CIVIC: {
        "temple": 0.25, "town_hall": 0.1, "school": 0.15, "guard_post": 0.25,
        "garrison": 0.1, "healer": 0.1, "university": 0.05,
    },
    ZoneType.MERCHANT: {"shop": 0.4, "tavern": 0.2, "market_stall": 0.25, "blacksmith": 0.15},
    ZoneType.RICH_RESIDENTIAL: {"manor": 1.0},
    ZoneType.POOR_RESIDENTIAL: {"residence": 1.0},
    ZoneType.FARMLAND_EDGE: {"farmstead": 1.0},
    ZoneType.PORT: {"dock": 0.4, "warehouse": 0.35, "harbormaster_office": 0.25},
}

JOB_VACANCIES_BY_BUILDING_TYPE: Dict[str, List[Tuple[str, int]]] = {
    "temple": [("priest", 1), ("acolyte", 2)],
    "town_hall": [("clerk", 3)],
    "school": [("teacher", 2)],
    "guard_post": [("guard", 4)],
    "garrison": [("soldier", 6)],
    "healer": [("healer", 1)],
    "university": [("scholar", 3)],
    "shop": [("shopkeep", 1), ("shop_staff", 2)],
    "tavern": [("barkeep", 1), ("tavern_staff", 2)],
    "blacksmith": [("blacksmith", 1), ("smith_apprentice", 2)],
    "market_stall": [("trader", 1)],
    "manor": [("noble", 1), ("servant", 3)],
    "residence": [],
    "farmstead": [("farmer", 1), ("farmhand", 3)],
    "dock": [("dockworker", 3)],
    "warehouse": [("warehouse_clerk", 1), ("laborer", 2)],
    "harbormaster_office": [("harbormaster", 1), ("customs_clerk", 2)],
    "arcane_shop": [("mage", 1), ("apprentice", 2)],
}

BUILDING_NAME_POOLS: Dict[str, List[str]] = {
    "temple": ["Shrine of the Dawn", "Temple of Light", "Sanctum of Silver Stars", "House of the Faithful"],
    "town_hall": ["Town Hall", "Hall of Records", "Council House"],
    "school": ["Old Schoolhouse", "Hall of Letters", "Learning House"],
    "guard_post": ["Watch Post", "Guardhouse", "Sentry Post"],
    "garrison": ["The Garrison", "Barracks of the Watch", "Iron Company Hall"],
    "healer": ["Healer's House", "House of Mending", "Herbalist's Rest"],
    "university": ["University", "College of Scholars", "Hall of Higher Learning"],
    "shop": ["General Goods", "The Trading Post", "Corner Market", "Old Wares Shop"],
    "tavern": ["The Rusty Anvil", "The Prancing Pony", "The Gilded Mug", "The Weary Traveler"],
    "blacksmith": ["The Iron Forge", "Anvil & Ember", "Hammer & Steel"],
    "market_stall": ["Market Stall", "Trader's Cart", "Wayside Stall"],
    "arcane_shop": ["The Curious Cauldron", "Arcane Emporium", "Sorcerer's Nook"],
    "dock": ["Dockside", "Harbor Pier", "Old Wharf"],
    "warehouse": ["Storehouse", "Old Warehouse", "Freight Hall"],
    "harbormaster_office": ["Harbormaster's Office", "Port Authority House"],
}

UNIVERSITY_MIN_POPULATION = 8000
UNIVERSITY_CHANCE = 0.15
ARCANE_SHOP_WEIGHT_SCALE = 0.5

BUILDING_HOME_CAPACITY: Dict[str, int] = {
    "manor": 10,
    "residence": 6,
    "farmstead": 8,
}


def poisson_disc_fill(polygon, target_count, min_spacing, rng, max_attempts_per_point=30):
    min_x = min(p[0] for p in polygon)
    max_x = max(p[0] for p in polygon)
    min_y = min(p[1] for p in polygon)
    max_y = max(p[1] for p in polygon)

    points: List[Tuple[float, float]] = []
    attempts = 0
    max_total_attempts = max(1, target_count) * max_attempts_per_point
    while len(points) < target_count and attempts < max_total_attempts:
        attempts += 1
        x = rng.uniform(min_x, max_x)
        y = rng.uniform(min_y, max_y)
        candidate = (x, y)
        if not point_in_polygon(candidate, polygon):
            continue
        if all(distance(candidate, p) >= min_spacing for p in points):
            points.append(candidate)
    return points


def _split_count_by_area(total_count: int, part_areas: List[float]) -> List[int]:
    total_area = sum(part_areas)
    if total_area <= 0:
        return [0 for _ in part_areas]

    raw = [total_count * (area / total_area) for area in part_areas]
    counts = [math.floor(r) for r in raw]
    remainder = total_count - sum(counts)

    remainders_sorted = sorted(range(len(part_areas)), key=lambda i: raw[i] - math.floor(raw[i]), reverse=True)
    i = 0
    while remainder > 0:
        counts[remainders_sorted[i % len(remainders_sorted)]] += 1
        remainder -= 1
        i += 1

    return counts


def fill_district_buildings(
    district: District, town_seed, next_building_id: int,
    target_population: int = 0, density_multiplier: float = 1.0,
    magic_prevalence: float = 0.0,
) -> List[Building]:
    rng = rng_for(town_seed, "buildings", district.id)
    parts = district.polygon_parts
    part_areas = [polygon_area(part) for part in parts]
    total_area = sum(part_areas)

    if total_area <= 0:
        return []

    density = BUILDING_DENSITY_PER_AREA[district.zone_type] * density_multiplier
    total_target_count = max(1, round(total_area * density))
    spacing = MIN_BUILDING_SPACING[district.zone_type] / density_multiplier

    part_counts = _split_count_by_area(total_target_count, part_areas)
    points: List[Tuple[float, float]] = []
    for part, part_count in zip(parts, part_counts):
        points.extend(poisson_disc_fill(part, part_count, spacing, rng))

    type_weights = dict(BUILDING_TYPES_BY_ZONE[district.zone_type])
    if district.zone_type == ZoneType.CIVIC and "university" in type_weights:
        university_eligible = (
            target_population >= UNIVERSITY_MIN_POPULATION and rng.random() < UNIVERSITY_CHANCE
        )
        if not university_eligible:
            del type_weights["university"]
    if district.zone_type == ZoneType.MERCHANT and magic_prevalence > 0:
        type_weights["arcane_shop"] = magic_prevalence * ARCANE_SHOP_WEIGHT_SCALE
    subtypes = list(type_weights.keys())
    weights = list(type_weights.values())

    buildings: List[Building] = []
    building_id = next_building_id
    for x, y in points:
        building_type = rng.choices(subtypes, weights=weights, k=1)[0]
        capacity = BUILDING_HOME_CAPACITY.get(building_type, 0)
        vacancies = [
            JobVacancy(building_id=building_id, occupation=occupation)
            for occupation, count in JOB_VACANCIES_BY_BUILDING_TYPE[building_type]
            for _ in range(count)
        ]
        name_pool = BUILDING_NAME_POOLS.get(building_type)
        name = rng.choice(name_pool) if name_pool else None
        buildings.append(Building(
            id=building_id,
            district_id=district.id,
            district_zone_type=district.zone_type,
            x=x,
            y=y,
            building_type=building_type,
            capacity=capacity,
            vacancies=vacancies,
            name=name,
        ))
        building_id += 1

    return buildings
