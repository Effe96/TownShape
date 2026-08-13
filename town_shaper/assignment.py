from typing import Dict, List, Optional

from town_shaper.models import Building, District, Household, JobVacancy, ResidentSlot, SES, ZoneType
from town_shaper.seeding import rng_for

SES_PROPORTIONS: Dict[SES, float] = {SES.RICH: 0.2, SES.POOR: 0.8}
DRIFT_CHANCE = 0.05

ZONE_TYPE_BY_SES: Dict[SES, ZoneType] = {
    SES.RICH: ZoneType.RICH_RESIDENTIAL,
    SES.POOR: ZoneType.POOR_RESIDENTIAL,
}


def _draw_household_ses(rng) -> SES:
    base = SES.RICH if rng.random() < SES_PROPORTIONS[SES.RICH] else SES.POOR
    if rng.random() < DRIFT_CHANCE:
        return SES.POOR if base == SES.RICH else SES.RICH
    return base


def _find_home_with_capacity(residential_buildings: List[Building], ses: SES) -> Optional[Building]:
    preferred_zone = ZONE_TYPE_BY_SES[ses]
    for building in residential_buildings:
        if building.district_zone_type == preferred_zone and len(building.resident_ids) < building.capacity:
            return building
    for building in residential_buildings:
        if len(building.resident_ids) < building.capacity:
            return building
    return None


def _build_vacancy_pool(districts: List[District], rng) -> List[JobVacancy]:
    vacancies = [v for d in districts for b in d.buildings for v in b.vacancies]
    vacancies.sort(key=lambda v: (v.building_id, v.occupation))
    rng.shuffle(vacancies)
    return vacancies


def assign_residents(town_seed, households: List[Household], districts: List[District]) -> List[ResidentSlot]:
    rng = rng_for(town_seed, "assignment")

    residential_buildings = sorted(
        (b for d in districts for b in d.buildings if b.capacity > 0),
        key=lambda b: b.id,
    )
    vacancy_pool = _build_vacancy_pool(districts, rng)

    residents: List[ResidentSlot] = []
    resident_id = 0

    for household in households:
        ses = _draw_household_ses(rng)
        home = _find_home_with_capacity(residential_buildings, ses)
        if home is None:
            break

        member_specs = [("adult", True)]
        if household.has_spouse:
            member_specs.append(("adult", True))
        member_specs.extend([("child", False)] * household.child_count)

        for age_bracket, is_working_age in member_specs:
            if len(home.resident_ids) >= home.capacity:
                # Household no longer fits in this home; remaining members go homeless
                # for this pass rather than double-booking capacity.
                break

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

    return residents
