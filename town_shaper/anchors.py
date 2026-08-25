import math
from typing import Dict, List, Tuple

from shapely.geometry import Point

from town_shaper.models import Anchor, ZoneType
from town_shaper.seeding import rng_for

MIN_ANCHORS = 8
ANCHOR_POPULATION_DIVISOR = 150

# Must sum to 1.0 — enforced by test_compute_anchor_counts_sums_to_total via
# the largest-remainder rounding below always consuming the full total.
ZONE_PROPORTIONS: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 0.05,
    ZoneType.MERCHANT: 0.15,
    ZoneType.RICH_RESIDENTIAL: 0.15,
    ZoneType.POOR_RESIDENTIAL: 0.45,
    ZoneType.FARMLAND_EDGE: 0.20,
}

# (min_radius_fraction, max_radius_fraction) of the bounding box half-extent,
# per zone type — determines how anchors are biased from town center to edge.
ZONE_RADIUS_BANDS: Dict[ZoneType, Tuple[float, float]] = {
    ZoneType.CIVIC: (0.0, 0.15),
    ZoneType.MERCHANT: (0.1, 0.4),
    ZoneType.RICH_RESIDENTIAL: (0.15, 0.45),
    ZoneType.POOR_RESIDENTIAL: (0.35, 0.75),
    ZoneType.FARMLAND_EDGE: (0.65, 0.95),
}

# Stable tie-break order for largest-remainder rounding.
_ZONE_ORDER = [
    ZoneType.CIVIC,
    ZoneType.MERCHANT,
    ZoneType.RICH_RESIDENTIAL,
    ZoneType.POOR_RESIDENTIAL,
    ZoneType.FARMLAND_EDGE,
]

MAX_WATER_RESAMPLE_ATTEMPTS = 20
PORT_BOUNDARY_SAMPLE_COUNT = 40
PORT_LAND_NUDGE_DISTANCE = 10.0


def compute_anchor_counts(target_population: int) -> Dict[ZoneType, int]:
    if target_population <= 0:
        raise ValueError("target_population must be positive")

    total = max(MIN_ANCHORS, round(target_population / ANCHOR_POPULATION_DIVISOR))
    # Guarantee at least one anchor per zone type without exceeding total.
    total = max(total, len(ZoneType))

    raw = {zt: ZONE_PROPORTIONS[zt] * total for zt in _ZONE_ORDER}
    counts = {zt: max(1, math.floor(raw[zt])) for zt in _ZONE_ORDER}

    remainder = total - sum(counts.values())
    remainders_sorted = sorted(_ZONE_ORDER, key=lambda zt: raw[zt] - math.floor(raw[zt]), reverse=True)
    i = 0
    while remainder > 0:
        counts[remainders_sorted[i % len(remainders_sorted)]] += 1
        remainder -= 1
        i += 1
    while remainder < 0:
        zt = remainders_sorted[i % len(remainders_sorted)]
        if counts[zt] > 1:
            counts[zt] -= 1
            remainder += 1
        i += 1

    return counts


def _clamp_to_bounds(x: float, y: float, bounds: Tuple[float, float, float, float]) -> Tuple[float, float]:
    min_x, min_y, max_x, max_y = bounds
    return min(max(x, min_x), max_x), min(max(y, min_y), max_y)


def _draw_anchor_point(
    rng, band_min: float, band_max: float,
    center_x: float, center_y: float, half_width: float, half_height: float,
    bounds: Tuple[float, float, float, float],
) -> Tuple[float, float]:
    angle = rng.uniform(0.0, 2.0 * math.pi)
    radius_fraction = rng.uniform(band_min, band_max)
    x = center_x + math.cos(angle) * radius_fraction * half_width
    y = center_y + math.sin(angle) * radius_fraction * half_height
    return _clamp_to_bounds(x, y, bounds)


def _place_port_anchor(town_seed, water_polygon, bounds, next_anchor_id: int) -> Anchor:
    rng = rng_for(town_seed, "anchors", "port")
    boundary = water_polygon.exterior
    min_x, min_y, max_x, max_y = bounds

    def _on_bounds_edge(x: float, y: float) -> bool:
        return (
            math.isclose(x, min_x, abs_tol=1e-6) or math.isclose(x, max_x, abs_tol=1e-6)
            or math.isclose(y, min_y, abs_tol=1e-6) or math.isclose(y, max_y, abs_tol=1e-6)
        )

    candidate = None
    for _ in range(PORT_BOUNDARY_SAMPLE_COUNT):
        fraction = rng.uniform(0.0, 1.0)
        point = boundary.interpolate(fraction, normalized=True)
        if _on_bounds_edge(point.x, point.y):
            continue
        candidate = (point.x, point.y)
        break

    if candidate is None:
        # Every sampled boundary point was on the map edge (e.g. a coastline
        # dominating the water shape) -- fall back to the boundary point
        # closest to the water body's own centroid.
        centroid = water_polygon.centroid
        nearest = boundary.interpolate(boundary.project(centroid))
        candidate = (nearest.x, nearest.y)

    centroid = water_polygon.centroid
    dx = candidate[0] - centroid.x
    dy = candidate[1] - centroid.y
    length = math.hypot(dx, dy)
    nudge = (0.0, 0.0) if length == 0 else (
        dx / length * PORT_LAND_NUDGE_DISTANCE, dy / length * PORT_LAND_NUDGE_DISTANCE
    )

    x, y = _clamp_to_bounds(candidate[0] + nudge[0], candidate[1] + nudge[1], bounds)
    return Anchor(id=next_anchor_id, zone_type=ZoneType.PORT, x=x, y=y)


def place_anchors(
    town_seed, target_population: int, bounds: Tuple[float, float, float, float],
    water_polygon=None, has_port: bool = False,
) -> List[Anchor]:
    if has_port and water_polygon is None:
        raise ValueError("has_port requires a water_polygon")

    counts = compute_anchor_counts(target_population)
    min_x, min_y, max_x, max_y = bounds
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    half_width = (max_x - min_x) / 2.0
    half_height = (max_y - min_y) / 2.0

    anchors: List[Anchor] = []
    anchor_id = 0
    for zone_type in _ZONE_ORDER:
        band_min, band_max = ZONE_RADIUS_BANDS[zone_type]
        for index in range(counts[zone_type]):
            rng = rng_for(town_seed, "anchors", zone_type.value, index)
            x, y = _draw_anchor_point(rng, band_min, band_max, center_x, center_y, half_width, half_height, bounds)
            if water_polygon is not None:
                attempts = 0
                while water_polygon.contains(Point(x, y)) and attempts < MAX_WATER_RESAMPLE_ATTEMPTS:
                    x, y = _draw_anchor_point(
                        rng, band_min, band_max, center_x, center_y, half_width, half_height, bounds
                    )
                    attempts += 1
                if water_polygon.contains(Point(x, y)):
                    nearest = water_polygon.exterior.interpolate(water_polygon.exterior.project(Point(x, y)))
                    x, y = _clamp_to_bounds(nearest.x, nearest.y, bounds)
            anchors.append(Anchor(id=anchor_id, zone_type=zone_type, x=x, y=y))
            anchor_id += 1

    if has_port:
        anchors.append(_place_port_anchor(town_seed, water_polygon, bounds, anchor_id))

    return anchors
