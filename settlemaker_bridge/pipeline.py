"""Phase 1 end-to-end: TownParameters -> settlemaker -> (District, Building)
rows AND settlemaker's own themed SVG, via the Node bridge. See
docs/superpowers/plans/2026-09-08-settlemaker-integration.md, Phase 1 tasks
1-4.

**Coordinate scale, and why this makes two bridge calls per town.**
settlemaker's `coastlineGeometry` input must be supplied "in burg-local
coordinates ... same scale as the generated mesh" (azgaar-input.d.ts) --
but that scale (`metadata.local_bounds` / `scale.diameter_local` in its
geojson output) is a function of the generated model's actual patch
geometry, not a closed form over population alone (measured directly:
population 3000 and 8000 produce meters-per-unit of 8.82 and 9.60
respectively, not a constant ratio; the village engine, used below
VILLAGE_POP_CEILING, uses yet another convention where meters_per_unit is
always 1). There is no exported helper to compute it up front. So: call
settlemaker once with no water input to learn this town's actual local
scale, then scale town_shaper's own water polygons (which live in
town_shaper.generate.compute_town_bounds' AREA_PER_RESIDENT-derived units)
into that frame, then call settlemaker again for real. Two ~150ms calls,
not one -- an acceptable cost at this project's generation volume (see the
design spec's "why a subprocess" rationale, which already accepted
per-call subprocess overhead on the same grounds).

**Why the water also gets re-centered after the real call, not just scaled
before it.** The dry call's frame isn't just a scale reference -- its
*center* was silently assumed to carry over to the real call too, and it
doesn't: handing settlemaker a real coastline measurably shifts where it
lays out the burg's mesh (measured directly: a population-8000 coastal
town shifted its frame's center by ~42 units between the dry and real
calls, on a ~210-unit-tall town -- port buildings ended up tens of units
from the water polygon they were supposed to be built next to). Fixed by
translating the already-scaled water features, after the real call, by the
delta between the dry and real calls' local_bounds centers -- corrects the
position without another subprocess call. Not a scale correction (the real
call's frame can also be a different aspect ratio than the dry call's, not
just offset) -- a translation is the smallest fix that visibly closes the
gap without a third settlemaker call.
"""
from typing import Any, Dict, List, Tuple

from shapely.geometry import Polygon as ShapelyPolygon

from town_db.generate import _water_feature_rings
from town_shaper.generate import compute_town_bounds
from town_shaper.models import Building, District, WaterFeature
from town_shaper.seeding import derive_seed
from town_shaper.water import generate_water_features

from settlemaker_bridge.bridge import call_settlemaker
from settlemaker_bridge.build_input import build_azgaar_burg_input
from settlemaker_bridge.parse_geojson import parse_settlemaker_geojson

SETTLEMAKER_SEED_MODULUS = 2 ** 31 - 1


def _settlemaker_seed(seed: Any) -> int:
    # Keeps this project's existing hash-based seeding backbone
    # (town_shaper.seeding) as the source of the number handed to
    # settlemaker, rather than introducing a second, parallel seeding
    # scheme -- capped well under JS's 2**53 float-safe-integer limit.
    return derive_seed(seed, "settlemaker") % SETTLEMAKER_SEED_MODULUS


def _local_radius_from_bounds(local_bounds: dict) -> float:
    # Conservative on purpose: the smaller of the two extents, halved, so a
    # scaled-in water polygon can't overshoot the narrower dimension of the
    # frame settlemaker actually reports.
    width = local_bounds["max_x"] - local_bounds["min_x"]
    height = local_bounds["max_y"] - local_bounds["min_y"]
    return min(width, height) / 2.0


def _center_of_bounds(local_bounds: dict) -> Tuple[float, float]:
    return (
        (local_bounds["min_x"] + local_bounds["max_x"]) / 2.0,
        (local_bounds["min_y"] + local_bounds["max_y"]) / 2.0,
    )


def _scale_water_features(
    water_features: List[WaterFeature], town_bounds_half: float, local_radius: float,
) -> List[WaterFeature]:
    """Rescale every water feature into settlemaker's own local frame,
    returning real WaterFeature objects (not a bespoke tuple shape) so
    town_db.generate's existing _water_feature_rings(feature) call -- which
    expects a WaterFeature with a real shapely .polygon -- keeps working
    completely unmodified. Used for BOTH the coastlineGeometry input (so
    settlemaker classifies patches against the right shape) and
    Town.water_features (so the persisted water lines up with the
    buildings/districts settlemaker just emitted, which are already in
    that frame -- inserting town_shaper's original, unscaled water
    polygons alongside settlemaker's local-unit buildings would draw two
    features at wildly different scales on the same axes)."""
    scale = local_radius / town_bounds_half
    scaled: List[WaterFeature] = []
    for feature in water_features:
        rings = _water_feature_rings(feature)
        # Y flip: settlemaker's coordinate system is Y-down (SVG
        # convention, per geojson-builder.ts's own doc comment);
        # town_shaper's is plain Cartesian Y-up. Orientation is otherwise
        # arbitrary here (no compass tie-in on either side), so this only
        # needs to be a *consistent* convention, not a geographically
        # meaningful one.
        exterior = [(x * scale, -y * scale) for x, y in rings[0]]
        holes = [[(x * scale, -y * scale) for x, y in ring] for ring in rings[1:]]
        scaled.append(WaterFeature(
            id=feature.id, kind=feature.kind,
            polygon=ShapelyPolygon(exterior, holes=holes),
        ))
    return scaled


def _translate_water_features(
    water_features: List[WaterFeature], dx: float, dy: float,
) -> List[WaterFeature]:
    """Shift already-scaled water features by (dx, dy) in the same frame
    their coordinates already live in. Used to correct for the real
    (with-coastline) settlemaker call landing its burg mesh at a different
    center than the dry (no-water) call used to derive the scale in
    _scale_water_features -- see generate_via_settlemaker's docstring."""
    if dx == 0.0 and dy == 0.0:
        return water_features
    translated: List[WaterFeature] = []
    for feature in water_features:
        rings = _water_feature_rings(feature)
        exterior = [(x + dx, y + dy) for x, y in rings[0]]
        holes = [[(x + dx, y + dy) for x, y in ring] for ring in rings[1:]]
        translated.append(WaterFeature(
            id=feature.id, kind=feature.kind,
            polygon=ShapelyPolygon(exterior, holes=holes),
        ))
    return translated


def generate_via_settlemaker(
    seed: Any,
    target_population: int,
    area_per_resident_multiplier: float = 1.0,
    num_rivers: int = 0,
    has_coastline: bool = False,
    has_port: bool = False,
) -> Tuple[List[District], List[Building], List[WaterFeature], str, Dict[str, float]]:
    """Returns (districts, buildings, scaled_water_features, svg, local_bounds).
    `local_bounds` is settlemaker's own metadata.local_bounds for this call,
    passed through unmodified (keys: min_x, min_y, max_x, max_y) -- see
    docs/superpowers/specs/2026-09-09-town-viewer-svg-overlay-design.md for
    what it's for. `svg` is
    settlemaker's own themed output for this exact town -- see the design
    spec's Rendering section: this project's real rendering path persists
    that SVG rather than reconstructing footprints in matplotlib, which
    Phase 1's checkpoint found throws away most of what makes settlemaker's
    output good (streets, farmland texture, plaza fill, proper wall/tower
    styling)."""
    bounds = compute_town_bounds(target_population, area_per_resident_multiplier)
    town_bounds_half = (bounds[2] - bounds[0]) / 2.0

    water_features = generate_water_features(
        seed, bounds, num_rivers=num_rivers, has_coastline=has_coastline,
    )

    burg = build_azgaar_burg_input(seed, target_population, has_port=has_port)
    settlemaker_seed = _settlemaker_seed(seed)

    scaled_water_features: List[WaterFeature] = []
    dry_bounds: dict = {}
    if water_features:
        dry_result = call_settlemaker(burg, settlemaker_seed)
        dry_bounds = dry_result["geojson"]["metadata"]["local_bounds"]
        local_radius = _local_radius_from_bounds(dry_bounds)
        scaled_water_features = _scale_water_features(water_features, town_bounds_half, local_radius)
        burg = dict(burg, coastlineGeometry=[
            [{"x": x, "y": y} for x, y in ring]
            for feature in scaled_water_features
            for ring in _water_feature_rings(feature)
        ])

    result = call_settlemaker(burg, settlemaker_seed)
    districts, buildings = parse_settlemaker_geojson(result["geojson"], seed, target_population)
    local_bounds = result["geojson"]["metadata"]["local_bounds"]

    if water_features:
        dry_center = _center_of_bounds(dry_bounds)
        real_center = _center_of_bounds(local_bounds)
        scaled_water_features = _translate_water_features(
            scaled_water_features, real_center[0] - dry_center[0], real_center[1] - dry_center[1],
        )

    return districts, buildings, scaled_water_features, result["svg"], local_bounds
