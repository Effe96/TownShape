# town_shaper/buildings.py
from typing import Dict, List, Tuple

from town_shaper.geometry import distance, point_in_polygon, polygon_area
from town_shaper.models import Building, District, JobVacancy, ZoneType
from town_shaper.seeding import rng_for

BUILDING_DENSITY_PER_AREA: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 1 / 400,
    ZoneType.MERCHANT: 1 / 150,
    ZoneType.RICH_RESIDENTIAL: 1 / 300,
    ZoneType.POOR_RESIDENTIAL: 1 / 100,
    ZoneType.FARMLAND_EDGE: 1 / 600,
}

MIN_BUILDING_SPACING: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 15.0,
    ZoneType.MERCHANT: 8.0,
    ZoneType.RICH_RESIDENTIAL: 12.0,
    ZoneType.POOR_RESIDENTIAL: 5.0,
    ZoneType.FARMLAND_EDGE: 20.0,
}

BUILDING_TYPES_BY_ZONE: Dict[ZoneType, Dict[str, float]] = {
    ZoneType.CIVIC: {"temple": 0.3, "town_hall": 0.1, "school": 0.2, "guard_post": 0.4},
    ZoneType.MERCHANT: {"shop": 0.5, "tavern": 0.2, "market_stall": 0.3},
    ZoneType.RICH_RESIDENTIAL: {"manor": 1.0},
    ZoneType.POOR_RESIDENTIAL: {"residence": 1.0},
    ZoneType.FARMLAND_EDGE: {"farmstead": 1.0},
}

JOB_VACANCIES_BY_BUILDING_TYPE: Dict[str, List[Tuple[str, int]]] = {
    "temple": [("priest", 1), ("acolyte", 2)],
    "town_hall": [("clerk", 3)],
    "school": [("teacher", 2)],
    "guard_post": [("guard", 4)],
    "shop": [("shopkeep", 1), ("shop_staff", 2)],
    "tavern": [("barkeep", 1), ("tavern_staff", 2)],
    "market_stall": [("trader", 1)],
    "manor": [("noble", 1), ("servant", 3)],
    "residence": [],
    "farmstead": [("farmer", 1), ("farmhand", 3)],
}

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


def fill_district_buildings(district: District, town_seed, next_building_id: int) -> List[Building]:
    rng = rng_for(town_seed, "buildings", district.id)
    area = polygon_area(district.polygon)
    density = BUILDING_DENSITY_PER_AREA[district.zone_type]
    target_count = max(1, round(area * density))
    spacing = MIN_BUILDING_SPACING[district.zone_type]

    points = poisson_disc_fill(district.polygon, target_count, spacing, rng)

    type_weights = BUILDING_TYPES_BY_ZONE[district.zone_type]
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
        buildings.append(Building(
            id=building_id,
            district_id=district.id,
            district_zone_type=district.zone_type,
            x=x,
            y=y,
            building_type=building_type,
            capacity=capacity,
            vacancies=vacancies,
        ))
        building_id += 1

    return buildings
