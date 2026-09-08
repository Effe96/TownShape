"""Parse settlemaker's GeoJSON output into TownShape's District/Building
models. See docs/superpowers/specs/2026-09-08-settlemaker-integration-design.md,
"Data Model" and "Architecture" sections for the mapping this implements.
"""
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import Polygon as ShapelyPolygon

from town_shaper.buildings import BUILDING_HOME_CAPACITY, BUILDING_NAME_POOLS
from town_shaper.generate import BUILDING_ID_STRIDE
from town_shaper.models import Anchor, Building, District, ZoneType
from town_shaper.seeding import rng_for

# First pass, per the spec's Data Model table -- validated visually, not
# just by name similarity, at Phase 1's checkpoint.
WARD_TYPE_TO_ZONE_TYPE: Dict[str, ZoneType] = {
    "administration": ZoneType.CIVIC,
    "cathedral": ZoneType.CIVIC,
    "merchant": ZoneType.MERCHANT,
    "market": ZoneType.MERCHANT,
    "slum": ZoneType.POOR_RESIDENTIAL,
    "craftsmen": ZoneType.POOR_RESIDENTIAL,
    "patriciate": ZoneType.RICH_RESIDENTIAL,
    "harbour": ZoneType.PORT,
    "gate": ZoneType.PORT,
    "farm": ZoneType.FARMLAND_EDGE,
    # NOT in the spec's original table -- discovered when Phase 1's first
    # real (walled + port) town run hit the raise below. Provisional only,
    # to unblock a visual checkpoint render; needs the same explicit
    # user sign-off the spec already calls for on castle/park before
    # Phase 2 treats it as decided.
    "military": ZoneType.CIVIC,
    # `park` WAS named in the spec as a known-deferred ward type, with two
    # options offered ("fold into civic, or add [it] as new ZoneType
    # values"). Provisionally taking the fold-into-civic option here, same
    # caveat as `military` above -- needs real user sign-off, not just this
    # placeholder, before Phase 2.
    "park": ZoneType.CIVIC,
}
# Not buildable area -- skipped, never raise. Everything else unmapped
# (castle, park, and -- discovered while implementing this, not in the
# spec's original table -- military) raises loudly per the plan's Phase 1
# task 3, so an actual generated town surfaces whether they show up in
# practice before Phase 2 has to decide their fate for real.
SKIPPABLE_WARD_TYPES = {"empty", "water"}

# Small renaming pass per the spec's Data Model section, reusing
# town_shaper.buildings' existing name-pool/job-vacancy tables rather than
# inventing a parallel naming system. A first-pass judgment call for kinds
# with no close equivalent (stable, bathhouse, mill, well): left unmapped,
# which falls through to plain zone infill below, not a crash -- only
# WardType has the "raise loudly" requirement, poi.kind does not.
POI_KIND_TO_BUILDING_TYPE: Dict[str, str] = {
    "inn": "tavern",
    "tavern": "tavern",
    "temple": "temple",
    "cathedral": "temple",
    "chapel": "temple",
    "smithy": "blacksmith",
    "shop": "shop",
    "market": "market_stall",
    "guardhouse": "guard_post",
    "guildhall": "town_hall",
    "warehouse": "warehouse",
    "pier": "dock",
}

# Mirrors the established `BUILDING_HOME_CAPACITY.get(building_type, 0)`
# convention already used throughout town_shaper (blocks.py, countryside.py):
# only home building types carry an occupant capacity, everything else is 0.
INFILL_BUILDING_TYPE_BY_ZONE: Dict[ZoneType, str] = {
    ZoneType.CIVIC: "workshop",
    ZoneType.MERCHANT: "workshop",
    ZoneType.POOR_RESIDENTIAL: "residence",
    ZoneType.RICH_RESIDENTIAL: "manor",
    ZoneType.FARMLAND_EDGE: "farmstead",
    ZoneType.PORT: "workshop",
}


def _centroid(ring: List[List[float]]) -> Tuple[float, float]:
    if len(ring) < 3:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    centroid = ShapelyPolygon(ring).buffer(0).centroid
    return (centroid.x, centroid.y)


def _building_name(seed: Any, building_type: str, building_id: int) -> Any:
    pool = BUILDING_NAME_POOLS.get(building_type)
    if not pool:
        return None
    rng = rng_for(seed, "settlemaker_building_name", building_id)
    return rng.choice(pool)


def parse_settlemaker_geojson(
    geojson: Dict[str, Any], seed: Any,
) -> Tuple[List[District], List[Building]]:
    """Group settlemaker's flat feature list by properties.layer, and map
    ward/building/poi features onto District/Building rows.

    Ward<->building association is NOT carried by an explicit id in the
    geojson -- a `building` feature only carries `wardType`, not which
    specific ward instance it belongs to, and multiple wards can share a
    type. It relies instead on emission order: settlemaker's
    generateGeoJson (src/output/geojson-builder.ts) iterates
    `model.patches`, and for each one pushes that patch's `ward` feature
    immediately followed by every one of its `building` features, before
    moving to the next patch. So every `building` feature belongs to the
    most recently emitted `ward` feature. This is an implementation detail
    of the pinned commit, not a documented contract -- safe only because
    the dependency is pinned to an exact SHA (see the spec's Version
    Pinning section) and re-verified if that pin ever moves.
    """
    districts: List[District] = []
    buildings: List[Building] = []

    current_district: Optional[District] = None
    next_district_id = 0

    poi_by_building_id: Dict[str, Dict[str, Any]] = {
        f["properties"]["building_id"]: f["properties"]
        for f in geojson["features"]
        if f["properties"]["layer"] == "poi" and f["properties"].get("building_id")
    }

    for feature in geojson["features"]:
        props = feature["properties"]
        layer = props["layer"]

        if layer == "ward":
            ward_type = props["wardType"]
            if ward_type in SKIPPABLE_WARD_TYPES:
                current_district = None
                continue
            if ward_type not in WARD_TYPE_TO_ZONE_TYPE:
                raise ValueError(
                    f"settlemaker ward type {ward_type!r} has no ZoneType mapping yet -- "
                    "see the design spec's Data Model / Risks sections (castle/park were "
                    "known-deferred; anything else showing up here is new)."
                )
            zone_type = WARD_TYPE_TO_ZONE_TYPE[ward_type]
            ring = [tuple(p) for p in feature["geometry"]["coordinates"][0]]
            cx, cy = _centroid(ring)
            district = District(
                id=next_district_id,
                zone_type=zone_type,
                anchor=Anchor(id=next_district_id, zone_type=zone_type, x=cx, y=cy),
                polygon_parts=[ring],
            )
            next_district_id += 1
            districts.append(district)
            current_district = district
            continue

        if layer == "building":
            if current_district is None:
                # Building belongs to a skipped (water/empty) ward -- not
                # buildable area, so the building itself is dropped too.
                continue
            ring = [tuple(p) for p in feature["geometry"]["coordinates"][0]]
            cx, cy = _centroid(ring)
            building_id = current_district.id * BUILDING_ID_STRIDE + len(current_district.buildings)

            poi = poi_by_building_id.get(props.get("building_id"))
            building_type = None
            if poi is not None:
                building_type = POI_KIND_TO_BUILDING_TYPE.get(poi["kind"])
            if building_type is None:
                building_type = INFILL_BUILDING_TYPE_BY_ZONE[current_district.zone_type]

            building = Building(
                id=building_id,
                district_id=current_district.id,
                district_zone_type=current_district.zone_type,
                x=cx, y=cy,
                building_type=building_type,
                capacity=BUILDING_HOME_CAPACITY.get(building_type, 0),
                name=_building_name(seed, building_type, building_id),
                footprint=ring,
            )
            current_district.buildings.append(building)
            buildings.append(building)
            continue

        # street / wall / tower / entrance / pier: no TownShape equivalent
        # consumed in Phase 1 -- render_town doesn't draw roads (see its own
        # comment), and walls are re-derived from district zone_type, not
        # from settlemaker's wall geometry (Data Model / Rendering sections).

    return districts, buildings
