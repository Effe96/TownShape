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

**Why the persisted water is scaled and positioned a second time, after the
real call, instead of just reusing the dry-run-scaled version.** The dry
call's frame is only ever a *prediction* of the real call's frame, used
because `coastlineGeometry` must be supplied before the real call exists to
measure -- and the prediction is wrong on both axes, not just one: handing
settlemaker a real coastline measurably shifts where it lays out the burg's
mesh (a population-8000 coastal town moved its frame's center by ~42 units)
*and* shrinks it (measured on the same town: dry radius 127.1, real radius
104.8 -- 17.5% smaller). A first version of this fix only corrected the
center, reusing the dry run's scale for the persisted water -- that made
port buildings' *position* relative to the water roughly right, while the
water polygon itself stayed sized for a frame 17.5% bigger than the one it
was actually being placed into, so it visibly overspilled onto dry land.
Fixed by recomputing the persisted water from `water_features` (the
original, unscaled town_shaper polygons) a second time, scaled by the
*real* call's own local_radius and centered on the *real* call's own
center -- the dry-run-scaled version is now used for exactly one thing,
the coastlineGeometry input, and never returned.

**Two more corrections, both downstream of the same root cause: predicting
`coastlineGeometry` from the dry call is a real scale/position, not a
perfect one, so nothing downstream of it can just trust it blindly.**

1. **Water is clipped to real land, not just repositioned.** Even correctly
   scaled and centered, `town_shaper`'s coastline "sea box" (deliberately
   oversized -- see `town_shaper.water._generate_coastline`) is shaped
   relative to `compute_town_bounds`' own square frame, which has no
   guaranteed relationship to settlemaker's actual (independently sized)
   burg footprint. Measured directly: with position+scale corrected but
   *not* clipped, 197 of 356 non-port buildings on a real town ended up
   geometrically inside the water polygon -- a strictly worse visible bug
   than the original misalignment, because now the water polygon was
   honestly positioned right on top of buildings that are not, in fact,
   underwater. Fixed by subtracting every district's real polygon (known
   only after the real call) from the water polygon -- water can never
   visually cover a building or district, regardless of how good or bad
   the scale/position prediction was for this particular town.
2. **PORT-zone districts whose classification the water clip disagrees
   with get reclassified.** `coastlineGeometry`'s imprecision doesn't only
   affect where we draw water -- it's also the input settlemaker itself
   classified "harbour" wards against, so a district settlemaker called
   PORT can genuinely not be near the water we now know is real (not
   fixable by correcting our own water rendering, since settlemaker
   already made this classification decision downstream of the same bad
   input). Districts whose anchor ends up implausibly far from the
   corrected water get folded into MERCHANT instead -- see
   `_reclassify_landlocked_port_districts`. (Historical note: this used to
   also clean up "gate" wards, which settlemaker_bridge.parse_geojson
   mapped to PORT alongside "harbour" -- moved to POOR_RESIDENTIAL
   2026-09-16, since GateWard is ordinary CommonWard housing, not port
   infrastructure, and that misclassification was zeroing out 24-51% of a
   town's buildings. This function is now a safety net for a mispredicted
   *harbour* position specifically, not the routine cleanup it used to run.)
"""
from typing import Any, Dict, List, Tuple

from shapely.geometry import MultiPolygon
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.ops import unary_union

from town_db.generate import _water_feature_rings
from town_shaper.generate import compute_town_bounds
from town_shaper.models import Building, District, WaterFeature, ZoneType
from town_shaper.seeding import derive_seed
from town_shaper.water import generate_water_features

from settlemaker_bridge.bridge import call_settlemaker
from settlemaker_bridge.build_input import build_azgaar_burg_input
from settlemaker_bridge.parse_geojson import parse_settlemaker_geojson

SETTLEMAKER_SEED_MODULUS = 2 ** 31 - 1

# A district's polygon within this many map units of the corrected water
# reads as genuinely adjacent to it ("touching," allowing for floating-point/
# geometry-simplification slack) -- not a fraction of town scale. Measured
# across several real towns (pop 3000 and 8000, back when "gate" wards were
# still routed through PORT -- see this module's docstring): districts that
# are actually coastal sit at distance 0.0 (their ward polygon touches or
# overlaps the water); the next-closest non-coastal ward in every sample was
# 8+ units away, with the bulk spread from there out to 60-70% of the town's
# own radius -- a wide, clearly separated gap, not a borderline call this
# constant is tuned to. A percentage-of-town-size threshold was tried first
# and rejected: it let clearly-inland districts through at generous
# percentages (test seed ("town", 1), pop 3000 -- every one of its 5 gate
# wards, PORT-classified at the time, sat 22-61% of the town's radius from
# water), while a real touching ward stays close in *absolute* terms
# regardless of town size, since it's a geometric-adjacency question, not
# one of proportion. Now that "gate" is no longer PORT, this almost never
# fires in practice -- kept as a safety net for a mispredicted harbour.
PORT_DISTRICT_WATER_ADJACENCY_TOLERANCE = 2.0


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


def _clip_water_to_land(
    water_features: List[WaterFeature], districts: List[District],
) -> List[WaterFeature]:
    """Subtract every district's real polygon from each water feature, so
    water can never visually cover a building or district regardless of
    how accurate the scale/position prediction in _scale_water_features
    turned out to be for this particular town -- see this module's
    docstring. A feature that comes out fully covered by land is dropped;
    one that splits into several disjoint pieces keeps only the largest
    (the others are slivers too small to read as water on the map)."""
    if not districts:
        return water_features
    # .buffer(0) repairs self-intersecting ward polygons before unioning --
    # same idiom settlemaker_bridge.parse_geojson._centroid already relies
    # on for the same underlying reason (settlemaker's emitted ward
    # geometry isn't always simple).
    land = unary_union([
        ShapelyPolygon(part).buffer(0) for district in districts for part in district.polygon_parts
        if len(part) >= 3
    ])
    if land.is_empty:
        return water_features

    clipped: List[WaterFeature] = []
    for feature in water_features:
        remaining = feature.polygon.difference(land)
        if remaining.is_empty:
            continue
        if isinstance(remaining, MultiPolygon):
            remaining = max(remaining.geoms, key=lambda p: p.area)
        clipped.append(WaterFeature(id=feature.id, kind=feature.kind, polygon=remaining))
    return clipped


def _reclassify_landlocked_port_districts(
    districts: List[District], water_features: List[WaterFeature], max_distance: float,
) -> None:
    """Mutates districts (and each of their buildings' denormalized
    district_zone_type copy) in place. A district settlemaker classified
    PORT (a "harbour"/"gate" ward) whose own polygon is farther than
    max_distance from the real, corrected water almost certainly isn't
    actually coastal -- the classification was made against
    coastlineGeometry's dry-run-predicted position (see this module's
    docstring), not the real one, and correcting our own water rendering
    after the fact can't retroactively change a decision settlemaker
    already made from bad input. Distance is measured from the district's
    own polygon, not its anchor point: a large ward's anchor (roughly its
    centroid) can sit tens of units from an edge that's genuinely on the
    water, understating how coastal it actually is. Reclassified to
    MERCHANT, not left PORT or reset to CIVIC: "workshop" is already the
    zone infill both PORT and MERCHANT fall back to (see
    settlemaker_bridge.parse_geojson.INFILL_BUILDING_TYPE_BY_ZONE), so no
    building's own building_type needs to change, only its zone."""
    if not water_features:
        return
    water_union = unary_union([wf.polygon for wf in water_features])
    if water_union.is_empty:
        return

    for district in districts:
        if district.zone_type is not ZoneType.PORT:
            continue
        district_polygon = unary_union([
            ShapelyPolygon(part).buffer(0) for part in district.polygon_parts if len(part) >= 3
        ])
        if district_polygon.is_empty or district_polygon.distance(water_union) <= max_distance:
            continue
        district.zone_type = ZoneType.MERCHANT
        district.anchor.zone_type = ZoneType.MERCHANT
        for building in district.buildings:
            building.district_zone_type = ZoneType.MERCHANT


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

    persisted_water_features: List[WaterFeature] = []
    if water_features:
        dry_result = call_settlemaker(burg, settlemaker_seed)
        dry_radius = _local_radius_from_bounds(dry_result["geojson"]["metadata"]["local_bounds"])
        # Dry-run-scaled water is used for exactly this: the coastlineGeometry
        # input to the real call below. It is never returned -- see this
        # module's docstring for why a second, real-radius scaling replaces
        # it once the real call's own local_bounds are known.
        input_water_features = _scale_water_features(water_features, town_bounds_half, dry_radius)
        burg = dict(burg, coastlineGeometry=[
            [{"x": x, "y": y} for x, y in ring]
            for feature in input_water_features
            for ring in _water_feature_rings(feature)
        ])

    result = call_settlemaker(burg, settlemaker_seed)
    districts, buildings = parse_settlemaker_geojson(result["geojson"], seed, target_population)
    local_bounds = result["geojson"]["metadata"]["local_bounds"]

    if water_features:
        real_radius = _local_radius_from_bounds(local_bounds)
        real_center = _center_of_bounds(local_bounds)
        persisted_water_features = _scale_water_features(water_features, town_bounds_half, real_radius)
        persisted_water_features = _translate_water_features(
            persisted_water_features, real_center[0], real_center[1],
        )
        persisted_water_features = _clip_water_to_land(persisted_water_features, districts)
        _reclassify_landlocked_port_districts(
            districts, persisted_water_features, PORT_DISTRICT_WATER_ADJACENCY_TOLERANCE,
        )

    return districts, buildings, persisted_water_features, result["svg"], local_bounds
