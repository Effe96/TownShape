from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from shapely.geometry import Polygon


class ZoneType(Enum):
    CIVIC = "civic"
    MERCHANT = "merchant"
    RICH_RESIDENTIAL = "rich_residential"
    POOR_RESIDENTIAL = "poor_residential"
    FARMLAND_EDGE = "farmland_edge"


class SES(Enum):
    RICH = "rich"
    POOR = "poor"


@dataclass
class Anchor:
    id: int
    zone_type: ZoneType
    x: float
    y: float


@dataclass
class JobVacancy:
    building_id: int
    occupation: str
    filled_by: Optional[int] = None


@dataclass
class Building:
    id: int
    district_id: int
    district_zone_type: ZoneType
    x: float
    y: float
    building_type: str
    capacity: int
    vacancies: List[JobVacancy] = field(default_factory=list)
    resident_ids: List[int] = field(default_factory=list)


@dataclass
class District:
    id: int
    zone_type: ZoneType
    anchor: Anchor
    polygon: List[Tuple[float, float]]
    buildings: List[Building] = field(default_factory=list)


@dataclass
class Household:
    id: int
    has_spouse: bool
    child_count: int


@dataclass
class ResidentSlot:
    id: int
    household_id: int
    ses: SES
    age_bracket: str
    home_building_id: Optional[int] = None
    workplace_building_id: Optional[int] = None
    occupation: Optional[str] = None


@dataclass
class Town:
    seed: tuple
    target_population: int
    bounds: Tuple[float, float, float, float]
    districts: List[District] = field(default_factory=list)
    residents: List[ResidentSlot] = field(default_factory=list)


@dataclass
class WaterFeature:
    id: int
    kind: str
    polygon: Polygon
