"""Parse settlemaker's GeoJSON output into TownShape's District/Building
models. See docs/superpowers/specs/2026-09-08-settlemaker-integration-design.md,
"Data Model" and "Architecture" sections for the mapping this implements.
"""
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import Polygon as ShapelyPolygon

from town_shaper.buildings import BUILDING_HOME_CAPACITY, BUILDING_NAME_POOLS, JOB_VACANCIES_BY_BUILDING_TYPE
from town_shaper.generate import BUILDING_ID_STRIDE
from town_shaper.models import Anchor, Building, District, JobVacancy, ZoneType
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

# Below settlemaker's own VILLAGE_POP_CEILING (1000, settlemaker/dist/village/
# village-model.js) it runs an entirely different generator with no ward layer
# at all -- every building is a generic house (no wardType/poi-kind pairing),
# and the only POI kinds it can ever emit are well/stone-circle/boathouse
# (village/types.d.ts's PoiKind union) -- never shop/tavern/temple/etc. So a
# village town structurally has no commercial or job-bearing building, ever;
# it's modeled as a single POOR_RESIDENTIAL district of "residence" buildings.
VILLAGE_BUILDING_TYPE = "residence"

# Population tiers a village's business/vacancy curation activates over --
# see docs/superpowers/specs/2026-09-09-village-economy-design.md. Starting
# points, not calibrated against real feedback yet -- easy to retune later,
# nothing else depends on their exact values.
VILLAGE_BUSINESS_MIN_POPULATION = 75   # below this, a village is houses only
VILLAGE_SHOP_MIN_POPULATION = 300      # below this, at most a tavern
VILLAGE_RESERVED_VACANCY_DIVISOR = 100 # ~1 reserved house per this many residents


def _curate_village_economy(buildings: List[Building], population: int, seed: Any) -> None:
    """Mutates a subset of `buildings` in place: reclassifies a few houses
    into businesses, reserves a few more as initially-vacant (so
    town_shaper.assignment.assign_residents' reserved_vacant filter leaves
    them empty for household_formation to grow into later). No-op below
    VILLAGE_BUSINESS_MIN_POPULATION -- a small enough village is just
    houses, no businesses and no reserved slack either."""
    if population < VILLAGE_BUSINESS_MIN_POPULATION or not buildings:
        return

    business_types = ["tavern"] if population < VILLAGE_SHOP_MIN_POPULATION else ["tavern", "shop"]
    reserved_count = max(1, population // VILLAGE_RESERVED_VACANCY_DIVISOR)

    rng = rng_for(seed, "village_economy")
    pool = sorted(buildings, key=lambda b: b.id)
    rng.shuffle(pool)

    for building, new_type in zip(pool, business_types):
        building.building_type = new_type
        building.capacity = BUILDING_HOME_CAPACITY.get(new_type, 0)
        building.vacancies = [
            JobVacancy(building_id=building.id, occupation=occupation)
            for occupation, count in JOB_VACANCIES_BY_BUILDING_TYPE[new_type]
            for _ in range(count)
        ]
        building.name = _building_name(seed, new_type, building.id)

    for building in pool[len(business_types):len(business_types) + reserved_count]:
        building.reserved_vacant = True


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


def _parse_village_geojson(
    geojson: Dict[str, Any], seed: Any,
) -> Tuple[List[District], List[Building]]:
    """Village-engine output (see VILLAGE_BUILDING_TYPE's comment above):
    no ward layer, so there's no per-building zone to key off of -- every
    building becomes a "residence" in one synthesized POOR_RESIDENTIAL
    district covering the whole settlement (anchored at metadata.local_bounds'
    centroid, since there's no ward polygon to derive one from either).
    Capacity comes from the feature's own `occupancy` field -- settlemaker
    already varies this per house glyph (a large house sleeps more than a
    small one), more faithful than the fixed BUILDING_HOME_CAPACITY constant
    every other (ward-driven) path falls back to. poi/street/green/field
    layers have no TownShape equivalent and are silently skipped, same
    treatment the ward path gives street/wall/tower/entrance/pier."""
    building_features = [f for f in geojson["features"] if f["properties"]["layer"] == "building"]
    if not building_features:
        return [], []

    bounds = geojson["metadata"]["local_bounds"]
    rect = [
        (bounds["min_x"], bounds["min_y"]), (bounds["max_x"], bounds["min_y"]),
        (bounds["max_x"], bounds["max_y"]), (bounds["min_x"], bounds["max_y"]),
    ]
    zone_type = ZoneType.POOR_RESIDENTIAL
    district = District(
        id=0,
        zone_type=zone_type,
        anchor=Anchor(
            id=0, zone_type=zone_type,
            x=(bounds["min_x"] + bounds["max_x"]) / 2.0,
            y=(bounds["min_y"] + bounds["max_y"]) / 2.0,
        ),
        polygon_parts=[rect],
    )

    buildings: List[Building] = []
    for feature in building_features:
        props = feature["properties"]
        ring = [tuple(p) for p in feature["geometry"]["coordinates"][0][:-1]]
        bx, by = _centroid(ring)
        building_id = district.id * BUILDING_ID_STRIDE + len(district.buildings)
        vacancies = [
            JobVacancy(building_id=building_id, occupation=occupation)
            for occupation, count in JOB_VACANCIES_BY_BUILDING_TYPE[VILLAGE_BUILDING_TYPE]
            for _ in range(count)
        ]
        building = Building(
            id=building_id,
            district_id=district.id,
            district_zone_type=zone_type,
            x=bx, y=by,
            building_type=VILLAGE_BUILDING_TYPE,
            capacity=int(props["occupancy"]),
            name=_building_name(seed, VILLAGE_BUILDING_TYPE, building_id),
            footprint=ring,
            vacancies=vacancies,
        )
        district.buildings.append(building)
        buildings.append(building)

    return [district], buildings


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
    if geojson.get("metadata", {}).get("settlement_generation_version") == "village":
        return _parse_village_geojson(geojson, seed)

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
            ring = [tuple(p) for p in feature["geometry"]["coordinates"][0][:-1]]
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
            ring = [tuple(p) for p in feature["geometry"]["coordinates"][0][:-1]]
            cx, cy = _centroid(ring)
            building_id = current_district.id * BUILDING_ID_STRIDE + len(current_district.buildings)

            poi = poi_by_building_id.get(props.get("building_id"))
            building_type = None
            if poi is not None:
                building_type = POI_KIND_TO_BUILDING_TYPE.get(poi["kind"])
            if building_type is None:
                building_type = INFILL_BUILDING_TYPE_BY_ZONE[current_district.zone_type]

            vacancies = [
                JobVacancy(building_id=building_id, occupation=occupation)
                for occupation, count in JOB_VACANCIES_BY_BUILDING_TYPE[building_type]
                for _ in range(count)
            ]

            building = Building(
                id=building_id,
                district_id=current_district.id,
                district_zone_type=current_district.zone_type,
                x=cx, y=cy,
                building_type=building_type,
                capacity=BUILDING_HOME_CAPACITY.get(building_type, 0),
                name=_building_name(seed, building_type, building_id),
                footprint=ring,
                vacancies=vacancies,
            )
            current_district.buildings.append(building)
            buildings.append(building)
            continue

        # street / wall / tower / entrance / pier: no TownShape equivalent
        # consumed in Phase 1 -- render_town doesn't draw roads (see its own
        # comment), and walls are re-derived from district zone_type, not
        # from settlemaker's wall geometry (Data Model / Rendering sections).

    return districts, buildings
