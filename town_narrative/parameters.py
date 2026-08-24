from dataclasses import dataclass
from typing import Any


@dataclass
class TownParameters:
    seed: Any
    target_population: int
    area_per_resident_multiplier: float = 1.0
    density_multiplier: float = 1.0
    rich_proportion: float = 0.05

    def __post_init__(self) -> None:
        if self.target_population <= 0:
            raise ValueError("target_population must be positive")
        if self.area_per_resident_multiplier <= 0:
            raise ValueError("area_per_resident_multiplier must be positive")
        if self.density_multiplier <= 0:
            raise ValueError("density_multiplier must be positive")
        if not (0.0 <= self.rich_proportion <= 1.0):
            raise ValueError("rich_proportion must be between 0.0 and 1.0")
