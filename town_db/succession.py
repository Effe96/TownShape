# town_db/succession.py
from typing import Optional, Tuple

from town_db.purchases import SHOP_BUILDING_TYPES
from town_shaper.buildings import JOB_VACANCIES_BY_BUILDING_TYPE

PROMOTABLE_BUILDING_TYPES = SHOP_BUILDING_TYPES | {"arcane_shop", "blacksmith"}


def primary_occupation_info(building_type: Optional[str], occupation: Optional[str]) -> Tuple[bool, Optional[str]]:
    if building_type is None or building_type not in PROMOTABLE_BUILDING_TYPES:
        return False, None
    roles = JOB_VACANCIES_BY_BUILDING_TYPE.get(building_type, [])
    primary_roles = [name for name, capacity in roles if capacity == 1]
    if len(primary_roles) != 1 or occupation != primary_roles[0]:
        return False, None
    apprentice_roles = [name for name, _ in roles if name != primary_roles[0]]
    return True, (apprentice_roles[0] if apprentice_roles else None)


def promote_apprentice(conn, workplace_id, apprentice_occupation, primary_occupation) -> Optional[int]:
    if apprentice_occupation is None:
        return None
    candidate = conn.execute(
        "SELECT id FROM residents WHERE workplace_building_id = ? AND occupation = ? AND death_date IS NULL "
        "ORDER BY id LIMIT 1",
        (workplace_id, apprentice_occupation),
    ).fetchone()
    if candidate is None:
        return None
    promoted_id = candidate[0]
    conn.execute("UPDATE residents SET occupation = ? WHERE id = ?", (primary_occupation, promoted_id))
    return promoted_id
