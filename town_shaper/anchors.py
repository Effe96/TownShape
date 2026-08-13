import math
from typing import Dict, List, Tuple

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


def place_anchors(town_seed, target_population: int, bounds: Tuple[float, float, float, float]) -> List[Anchor]:
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
            angle = rng.uniform(0.0, 2.0 * math.pi)
            radius_fraction = rng.uniform(band_min, band_max)
            x = center_x + math.cos(angle) * radius_fraction * half_width
            y = center_y + math.sin(angle) * radius_fraction * half_height
            x = min(max(x, min_x), max_x)
            y = min(max(y, min_y), max_y)
            anchors.append(Anchor(id=anchor_id, zone_type=zone_type, x=x, y=y))
            anchor_id += 1

    return anchors
