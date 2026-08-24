from typing import Dict, List, Optional

from town_shaper.models import Building, District, Household, JobVacancy, ResidentSlot, SES, ZoneType
from town_shaper.seeding import rng_for

DRIFT_CHANCE = 0.05
DEFAULT_RICH_PROPORTION = 0.05

ZONE_TYPE_BY_SES: Dict[SES, ZoneType] = {
    SES.RICH: ZoneType.RICH_RESIDENTIAL,
    SES.POOR: ZoneType.POOR_RESIDENTIAL,
}

def _draw_household_ses(rng, rich_proportion: float) -> SES:
    return SES.RICH if rng.random() < rich_proportion else SES.POOR


def _preferred_zones(ses: SES, rng) -> List[ZoneType]:
    """Zones a household of this SES tier would like to live in, in preference order.

    Drift affects WHERE a household of a given SES lives, not the SES tier
    itself (the tier recorded on ResidentSlot.ses is always the true, undrifted
    value). Poor households that are not drifting also consider farmland-edge
    as a secondary preferred zone.
    """
    drifted = rng.random() < DRIFT_CHANCE
    if ses == SES.POOR:
        if drifted:
            return [ZONE_TYPE_BY_SES[SES.RICH]]
        return [ZONE_TYPE_BY_SES[SES.POOR], ZoneType.FARMLAND_EDGE]
    # ses == SES.RICH
    if drifted:
        return [ZONE_TYPE_BY_SES[SES.POOR], ZoneType.FARMLAND_EDGE]
    return [ZONE_TYPE_BY_SES[SES.RICH]]


def _find_home_with_capacity(
    residential_buildings: List[Building], preferred_zones: List[ZoneType], needed: int
) -> Optional[Building]:
    """Find a building with at least `needed` free slots.

    Tries each zone in `preferred_zones` in order first, then falls back to
    any building (any zone) with enough room.
    """
    for zone in preferred_zones:
        for building in residential_buildings:
            if building.district_zone_type == zone and building.capacity - len(building.resident_ids) >= needed:
                return building
    for building in residential_buildings:
        if building.capacity - len(building.resident_ids) >= needed:
            return building
    return None


def _build_vacancy_pool(districts: List[District], rng) -> List[JobVacancy]:
    vacancies = [v for d in districts for b in d.buildings for v in b.vacancies]
    vacancies.sort(key=lambda v: (v.building_id, v.occupation))
    rng.shuffle(vacancies)
    return vacancies


def assign_residents(
    town_seed,
    households: List[Household],
    districts: List[District],
    rich_proportion: float = DEFAULT_RICH_PROPORTION,
) -> List[ResidentSlot]:
    rng = rng_for(town_seed, "assignment")

    residential_buildings = sorted(
        (b for d in districts for b in d.buildings if b.capacity > 0),
        key=lambda b: b.id,
    )
    vacancy_pool = _build_vacancy_pool(districts, rng)

    residents: List[ResidentSlot] = []
    resident_id = 0

    for household in households:
        ses = _draw_household_ses(rng, rich_proportion)
        preferred_zones = _preferred_zones(ses, rng)

        member_specs = [("adult", True)]
        if household.has_spouse:
            member_specs.append(("adult", True))
        member_specs.extend([("child", False)] * household.child_count)

        def _place(age_bracket, is_working_age, home):
            nonlocal resident_id
            resident = ResidentSlot(
                id=resident_id,
                household_id=household.id,
                ses=ses,
                age_bracket=age_bracket,
                home_building_id=home.id,
            )
            if is_working_age and vacancy_pool:
                vacancy = vacancy_pool.pop()
                resident.workplace_building_id = vacancy.building_id
                resident.occupation = vacancy.occupation
                vacancy.filled_by = resident.id

            residents.append(resident)
            home.resident_ids.append(resident.id)
            resident_id += 1

        whole_household_home = _find_home_with_capacity(residential_buildings, preferred_zones, len(member_specs))
        if whole_household_home is not None:
            for age_bracket, is_working_age in member_specs:
                _place(age_bracket, is_working_age, whole_household_home)
            continue

        # No single building has room for the whole household: place members
        # one at a time, allowing the household to legitimately split across
        # multiple buildings rather than being truncated.
        for age_bracket, is_working_age in member_specs:
            home = _find_home_with_capacity(residential_buildings, preferred_zones, 1)
            if home is None:
                # No building anywhere has any room left; this member is
                # unhoused for this pass (expected end-of-capacity condition).
                continue
            _place(age_bracket, is_working_age, home)

    return residents
