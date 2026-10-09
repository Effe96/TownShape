from dataclasses import dataclass
from typing import Any, Tuple

from town_shaper.assignment import DEFAULT_RICH_PROPORTION


@dataclass(frozen=True)
class TownParameters:
    seed: Any
    target_population: int
    area_per_resident_multiplier: float = 1.0
    density_multiplier: float = 1.0
    rich_proportion: float = DEFAULT_RICH_PROPORTION
    num_rivers: int = 0
    has_coastline: bool = False
    has_port: bool = False
    magic_prevalence: float = 0.0
    aggression: float = 0.0
    # Layout: compass bearings in degrees (0 = north, clockwise).
    # river_bearings[i] is where river i flows in from (it leaves opposite);
    # road_bearings are the directions approach roads arrive from.
    has_citadel: bool = False
    river_bearings: Tuple[float, ...] = ()
    road_bearings: Tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.target_population <= 0:
            raise ValueError("target_population must be positive")
        if self.area_per_resident_multiplier <= 0:
            raise ValueError("area_per_resident_multiplier must be positive")
        if self.density_multiplier <= 0:
            raise ValueError("density_multiplier must be positive")
        if not (0.0 <= self.rich_proportion <= 1.0):
            raise ValueError("rich_proportion must be between 0.0 and 1.0")
        if self.num_rivers < 0:
            raise ValueError("num_rivers must be non-negative")
        if self.has_port and not (self.num_rivers > 0 or self.has_coastline):
            raise ValueError("has_port requires num_rivers > 0 or has_coastline to be True")
        if not (0.0 <= self.magic_prevalence <= 1.0):
            raise ValueError("magic_prevalence must be between 0.0 and 1.0")
        if not (0.0 <= self.aggression <= 1.0):
            raise ValueError("aggression must be between 0.0 and 1.0")
        if len(self.river_bearings) > self.num_rivers:
            raise ValueError("river_bearings has more entries than num_rivers")
        for bearing in tuple(self.river_bearings) + tuple(self.road_bearings):
            if not (0.0 <= bearing < 360.0):
                raise ValueError("bearings must be in [0, 360)")
