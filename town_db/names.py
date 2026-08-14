from pathlib import Path
from typing import Dict, List, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent

RACES: List[str] = ["human", "dwarf", "elf", "gnome", "halfling", "orc"]

RACE_WEIGHTS: Dict[str, float] = {
    "human": 0.70,
    "dwarf": 0.08,
    "elf": 0.06,
    "gnome": 0.05,
    "halfling": 0.08,
    "orc": 0.03,
}

GENDERS: List[str] = ["male", "female"]

_name_cache: Dict[Tuple[str, str], List[str]] = {}
_surname_cache: Dict[str, List[str]] = {}


def _load_lines(filename: str) -> List[str]:
    path = _REPO_ROOT / filename
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _names_for(race: str, gender: str) -> List[str]:
    key = (race, gender)
    if key not in _name_cache:
        _name_cache[key] = _load_lines(f"{race}_{gender}_names.txt")
    return _name_cache[key]


def _surnames_for(race: str) -> List[str]:
    if race not in _surname_cache:
        _surname_cache[race] = _load_lines(f"{race}_surnames.txt")
    return _surname_cache[race]


def draw_race(rng, race_weights: Dict[str, float] = RACE_WEIGHTS) -> str:
    races = list(race_weights.keys())
    weights = list(race_weights.values())
    return rng.choices(races, weights=weights, k=1)[0]


def draw_gender(rng) -> str:
    return rng.choice(GENDERS)


def draw_first_name(rng, race: str, gender: str) -> str:
    return rng.choice(_names_for(race, gender))


def draw_surname(rng, race: str) -> str:
    return rng.choice(_surnames_for(race))
