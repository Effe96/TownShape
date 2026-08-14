# Town DB Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `town_db`, a deterministic generator that turns a Town Shaper `Town` into a SQLite database of enriched residents (names, race, gender, exact ages) plus a year of historical registry records (purchases, taxes, births, deaths, disease, school/university enrollment, military service).

**Architecture:** `town_db.generate.generate_town_database(seed, target_population, db_path, **params)` calls `town_shaper.generate.generate_town` for the spatial/population substrate, then runs a sequence of pure generation functions (households/names/ages → purchases → taxes → vital records/disease → enrollment → military) that each return plain dicts, which the orchestrator inserts into SQLite. Task 1 makes a small, targeted addition to the already-merged Town Shaper package (three new CIVIC building types) before any `town_db` code is written.

**Tech Stack:** Python 3.12, stdlib only (`sqlite3`, `random` via `town_shaper.seeding.rng_for`, `datetime`, `json`) — no new third-party dependency. Per `docs/superpowers/specs/2026-08-14-town-db-relational-database-design.md` (note: spec file is dated 2026-08-13; both refer to the same approved spec).

## Global Constraints

- Every generation function takes an explicit seed and draws randomness only via `town_shaper.seeding.rng_for(seed, "db", ...)` — never global `random` state, matching Town Shaper's established discipline.
- `districts.id`, `buildings.id`, and `households.id` are Town Shaper's original explicit integer ids (no remapping) — only `residents.id` is `INTEGER PRIMARY KEY AUTOINCREMENT`, because new residents (newborns) are created mid-simulation and must never collide with existing ids.
- Every SQLite connection must run `PRAGMA foreign_keys = ON` (this is a per-connection setting, not persisted in the file).
- Race is limited to the six values with direct name-file coverage in the repo root: `human`, `dwarf`, `elf`, `gnome`, `halfling`, `orc` (no half-elf/half-orc fallback logic).
- The simulated year is anchored at a default start date `date(1300, 1, 1)`, overridable.
- Task 1 modifies already-merged, already-reviewed Town Shaper code (`town_shaper/buildings.py`, `town_shaper/generate.py`). The change must be backward-compatible: `fill_district_buildings`'s new `target_population` parameter defaults to `0` (never eligible for a university), and every existing Town Shaper test must still pass unmodified after the change, in addition to the new tests this plan adds.
- No third-party dependency beyond what Town Shaper already uses (`numpy`, `scipy`) — `town_db` itself needs none beyond stdlib.

---

## Task 1: Extend Town Shaper with university/garrison/healer buildings

**Files:**
- Modify: `town_shaper/buildings.py`
- Modify: `town_shaper/generate.py`
- Modify: `tests/test_buildings.py`
- Modify: `tests/test_generate.py`

**Interfaces:**
- Consumes: existing `town_shaper/buildings.py` and `town_shaper/generate.py` (already merged)
- Produces: `fill_district_buildings(district, town_seed, next_building_id, target_population=0) -> List[Building]` (new optional 4th parameter), `UNIVERSITY_MIN_POPULATION = 8000`, `UNIVERSITY_CHANCE = 0.15`, three new entries in `BUILDING_TYPES_BY_ZONE[ZoneType.CIVIC]` (`garrison`, `healer`, `university`) and matching entries in `JOB_VACANCIES_BY_BUILDING_TYPE`

- [ ] **Step 1: Write the failing tests**

```python
# Add to tests/test_buildings.py

def test_civic_zone_includes_garrison_and_healer():
    from town_shaper.buildings import BUILDING_TYPES_BY_ZONE
    from town_shaper.models import ZoneType
    civic_types = BUILDING_TYPES_BY_ZONE[ZoneType.CIVIC]
    assert "garrison" in civic_types
    assert "healer" in civic_types
    assert "university" in civic_types


def test_university_never_appears_below_min_population():
    district = _square_district(ZoneType.CIVIC, side=200.0)
    for seed_index in range(20):
        buildings = fill_district_buildings(
            district, ("town", seed_index), next_building_id=0, target_population=1000
        )
        assert all(b.building_type != "university" for b in buildings)


def test_university_can_appear_above_min_population():
    district = _square_district(ZoneType.CIVIC, side=200.0)
    found = False
    for seed_index in range(50):
        buildings = fill_district_buildings(
            district, ("town", seed_index), next_building_id=0, target_population=20000
        )
        if any(b.building_type == "university" for b in buildings):
            found = True
            break
    assert found


def test_garrison_and_healer_create_expected_vacancies():
    from town_shaper.buildings import JOB_VACANCIES_BY_BUILDING_TYPE
    assert JOB_VACANCIES_BY_BUILDING_TYPE["garrison"] == [("soldier", 6)]
    assert JOB_VACANCIES_BY_BUILDING_TYPE["healer"] == [("healer", 1)]
    assert JOB_VACANCIES_BY_BUILDING_TYPE["university"] == [("scholar", 3)]
```

```python
# Add to tests/test_generate.py

def test_generate_town_threads_target_population_into_building_fill():
    # A pop-3000 town (below UNIVERSITY_MIN_POPULATION) must never contain
    # a university, proving target_population reaches fill_district_buildings.
    town = generate_town(("town", 1), target_population=3000)
    all_types = [b.building_type for d in town.districts for b in d.buildings]
    assert "university" not in all_types
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_buildings.py tests/test_generate.py -v -k "garrison or healer or university or threads_target_population"`
Expected: FAIL — `garrison`/`healer`/`university` not in `BUILDING_TYPES_BY_ZONE`, `fill_district_buildings()` doesn't accept `target_population`

- [ ] **Step 3: Modify `town_shaper/buildings.py`**

Change the `CIVIC` entry in `BUILDING_TYPES_BY_ZONE` from:
```python
    ZoneType.CIVIC: {"temple": 0.3, "town_hall": 0.1, "school": 0.2, "guard_post": 0.4},
```
to:
```python
    ZoneType.CIVIC: {
        "temple": 0.25, "town_hall": 0.1, "school": 0.15, "guard_post": 0.25,
        "garrison": 0.1, "healer": 0.1, "university": 0.05,
    },
```

Add to `JOB_VACANCIES_BY_BUILDING_TYPE`:
```python
    "garrison": [("soldier", 6)],
    "healer": [("healer", 1)],
    "university": [("scholar", 3)],
```

Add near the top of the file, after the existing module-level constants:
```python
UNIVERSITY_MIN_POPULATION = 8000
UNIVERSITY_CHANCE = 0.15
```

Change `fill_district_buildings`'s signature and body from:
```python
def fill_district_buildings(district: District, town_seed, next_building_id: int) -> List[Building]:
    rng = rng_for(town_seed, "buildings", district.id)
    area = polygon_area(district.polygon)
    density = BUILDING_DENSITY_PER_AREA[district.zone_type]
    target_count = max(1, round(area * density))
    spacing = MIN_BUILDING_SPACING[district.zone_type]

    points = poisson_disc_fill(district.polygon, target_count, spacing, rng)

    type_weights = BUILDING_TYPES_BY_ZONE[district.zone_type]
    subtypes = list(type_weights.keys())
    weights = list(type_weights.values())
```
to:
```python
def fill_district_buildings(
    district: District, town_seed, next_building_id: int, target_population: int = 0
) -> List[Building]:
    rng = rng_for(town_seed, "buildings", district.id)
    area = polygon_area(district.polygon)
    density = BUILDING_DENSITY_PER_AREA[district.zone_type]
    target_count = max(1, round(area * density))
    spacing = MIN_BUILDING_SPACING[district.zone_type]

    points = poisson_disc_fill(district.polygon, target_count, spacing, rng)

    type_weights = dict(BUILDING_TYPES_BY_ZONE[district.zone_type])
    if district.zone_type == ZoneType.CIVIC and "university" in type_weights:
        university_eligible = (
            target_population >= UNIVERSITY_MIN_POPULATION and rng.random() < UNIVERSITY_CHANCE
        )
        if not university_eligible:
            del type_weights["university"]
    subtypes = list(type_weights.keys())
    weights = list(type_weights.values())
```

(The rest of the function body is unchanged — it already uses `subtypes`/`weights` generically.)

- [ ] **Step 4: Modify `town_shaper/generate.py`**

Find the district-fill loop inside `generate_town`:
```python
    next_building_id = 0
    for district in districts:
        next_building_id = district.id * BUILDING_ID_STRIDE
        buildings = fill_district_buildings(district, seed, next_building_id)
        district.buildings = buildings
```
Change the `fill_district_buildings` call to pass `target_population`:
```python
    for district in districts:
        next_building_id = district.id * BUILDING_ID_STRIDE
        buildings = fill_district_buildings(district, seed, next_building_id, target_population=target_population)
        district.buildings = buildings
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/ -v`
Expected: PASS — all existing Town Shaper tests (49 previously) plus the new ones in this task. This is the one task in the whole plan required to run the *entire* pre-existing suite, not just its own new tests, since it touches shared, already-merged code.

- [ ] **Step 6: Commit**

```bash
git add town_shaper/buildings.py town_shaper/generate.py tests/test_buildings.py tests/test_generate.py
git commit -m "feat: add university/garrison/healer CIVIC buildings to Town Shaper"
```

---

## Task 2: town_db package scaffolding and schema

**Files:**
- Create: `town_db/__init__.py`
- Create: `town_db/schema.py`
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Consumes: nothing (stdlib `sqlite3` only)
- Produces: `SCHEMA_SQL: str`, `create_schema(conn: sqlite3.Connection) -> None`, `connect(db_path: str) -> sqlite3.Connection`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_schema.py
import sqlite3

from town_db.schema import connect, create_schema

EXPECTED_TABLES = {
    "districts", "buildings", "households", "residents", "goods",
    "purchases", "tax_payments", "disease_events", "births", "deaths",
    "school_enrollments", "military_service",
}


def test_create_schema_creates_every_table(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {row[0] for row in rows}
    assert EXPECTED_TABLES <= table_names


def test_connect_enables_foreign_keys(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    result = conn.execute("PRAGMA foreign_keys").fetchone()
    assert result[0] == 1


def test_residents_id_is_autoincrement_but_buildings_id_is_not(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (5, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (42, 5, 'civic', 'temple', 1.0, 2.0, 0)"
    )
    row = conn.execute("SELECT id FROM buildings WHERE id = 42").fetchone()
    assert row[0] == 42

    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    cursor = conn.execute(
        "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, "
        "ses, is_noble) VALUES (1, 'Ann', 'Smith', 'female', 'human', '1280-01-01', 'poor', 0)"
    )
    first_id = cursor.lastrowid
    cursor2 = conn.execute(
        "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, "
        "ses, is_noble) VALUES (1, 'Bob', 'Smith', 'male', 'human', '1275-01-01', 'poor', 0)"
    )
    assert cursor2.lastrowid == first_id + 1


def test_foreign_key_violation_is_rejected(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    try:
        conn.execute(
            "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
            "VALUES (1, 999, 'civic', 'temple', 0.0, 0.0, 0)"
        )
        conn.commit()
        assert False, "expected a foreign key violation"
    except sqlite3.IntegrityError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_db'`

- [ ] **Step 3: Write the schema module**

```python
# town_db/__init__.py
```

```python
# town_db/schema.py
import sqlite3

SCHEMA_SQL = """
CREATE TABLE districts (
    id INTEGER PRIMARY KEY,
    zone_type TEXT NOT NULL,
    polygon TEXT NOT NULL
);

CREATE TABLE buildings (
    id INTEGER PRIMARY KEY,
    district_id INTEGER NOT NULL REFERENCES districts(id),
    zone_type TEXT NOT NULL,
    building_type TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    capacity INTEGER NOT NULL
);

CREATE TABLE households (
    id INTEGER PRIMARY KEY,
    family_name TEXT NOT NULL,
    race TEXT NOT NULL
);

CREATE TABLE residents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id),
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    gender TEXT NOT NULL,
    race TEXT NOT NULL,
    birth_date TEXT NOT NULL,
    death_date TEXT,
    ses TEXT NOT NULL,
    is_noble INTEGER NOT NULL DEFAULT 0,
    home_building_id INTEGER REFERENCES buildings(id),
    workplace_building_id INTEGER REFERENCES buildings(id),
    occupation TEXT
);

CREATE TABLE goods (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    typical_price REAL NOT NULL,
    sv INTEGER NOT NULL
);

CREATE TABLE purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    shop_building_id INTEGER NOT NULL REFERENCES buildings(id),
    good_id INTEGER NOT NULL REFERENCES goods(id),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    total_price REAL NOT NULL,
    purchase_date TEXT NOT NULL
);

CREATE TABLE tax_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    tax_type TEXT NOT NULL,
    amount REAL NOT NULL,
    period TEXT NOT NULL,
    payment_date TEXT NOT NULL
);

CREATE TABLE disease_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    affected_zone_type TEXT,
    severity REAL NOT NULL
);

CREATE TABLE births (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_resident_id INTEGER NOT NULL REFERENCES residents(id),
    mother_resident_id INTEGER NOT NULL REFERENCES residents(id),
    father_resident_id INTEGER REFERENCES residents(id),
    birth_date TEXT NOT NULL,
    reported_by_building_id INTEGER NOT NULL REFERENCES buildings(id)
);

CREATE TABLE deaths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL UNIQUE REFERENCES residents(id),
    death_date TEXT NOT NULL,
    cause TEXT NOT NULL,
    disease_event_id INTEGER REFERENCES disease_events(id),
    reported_by_building_id INTEGER NOT NULL REFERENCES buildings(id)
);

CREATE TABLE school_enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    school_building_id INTEGER NOT NULL REFERENCES buildings(id),
    enrollment_type TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT
);

CREATE TABLE military_service (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    garrison_building_id INTEGER NOT NULL REFERENCES buildings(id),
    rank TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add town_db/__init__.py town_db/schema.py tests/test_db_schema.py
git commit -m "feat: add town_db package with SQLite schema"
```

---

## Task 3: Name/race/gender drawing

**Files:**
- Create: `town_db/names.py`
- Test: `tests/test_db_names.py`

**Interfaces:**
- Consumes: the `.txt` name word lists already at the `TownShape` repo root (`{race}_{gender}_names.txt`, `{race}_surnames.txt` for `human`, `dwarf`, `elf`, `gnome`, `halfling`, `orc`)
- Produces: `RACES: List[str]`, `RACE_WEIGHTS: Dict[str, float]`, `GENDERS: List[str]`, `draw_race(rng, race_weights=RACE_WEIGHTS) -> str`, `draw_gender(rng) -> str`, `draw_first_name(rng, race: str, gender: str) -> str`, `draw_surname(rng, race: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_names.py
from town_shaper.seeding import rng_for
from town_db.names import RACE_WEIGHTS, RACES, draw_first_name, draw_gender, draw_race, draw_surname


def test_race_weights_cover_exactly_the_six_supported_races():
    assert set(RACE_WEIGHTS.keys()) == set(RACES)
    assert RACES == ["human", "dwarf", "elf", "gnome", "halfling", "orc"]


def test_draw_race_is_deterministic():
    rng1 = rng_for(("town", 1), "test-names")
    rng2 = rng_for(("town", 1), "test-names")
    draws1 = [draw_race(rng1) for _ in range(20)]
    draws2 = [draw_race(rng2) for _ in range(20)]
    assert draws1 == draws2
    assert set(draws1) <= set(RACES)


def test_draw_gender_returns_male_or_female():
    rng = rng_for(("town", 1), "test-gender")
    draws = {draw_gender(rng) for _ in range(20)}
    assert draws <= {"male", "female"}


def test_draw_first_name_and_surname_come_from_the_real_word_lists():
    rng = rng_for(("town", 1), "test-name-draw")
    name = draw_first_name(rng, "dwarf", "female")
    surname = draw_surname(rng, "dwarf")
    assert isinstance(name, str) and len(name) > 0
    assert isinstance(surname, str) and len(surname) > 0


def test_draw_first_name_for_every_supported_race_and_gender():
    rng = rng_for(("town", 1), "test-all-races")
    for race in RACES:
        for gender in ["male", "female"]:
            name = draw_first_name(rng, race, gender)
            assert isinstance(name, str) and len(name) > 0
        surname = draw_surname(rng, race)
        assert isinstance(surname, str) and len(surname) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_names.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_db.names'`

- [ ] **Step 3: Write the names module**

```python
# town_db/names.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_names.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add town_db/names.py tests/test_db_names.py
git commit -m "feat: add race/gender/name drawing from existing word lists"
```

---

## Task 4: Age distribution and birthdate calculation

**Files:**
- Create: `town_db/ages.py`
- Test: `tests/test_db_ages.py`

**Interfaces:**
- Consumes: nothing (stdlib `datetime` only)
- Produces: `ADULT_AGE_RANGE: Tuple[int, int]`, `CHILD_AGE_RANGE: Tuple[int, int]`, `AGE_DECAY_RATE: float`, `draw_age(rng, age_bracket: str) -> int`, `birth_date_from_age(reference_date: date, age: int) -> date`, `age_on(birth_date: date, on_date: date) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_ages.py
from datetime import date

from town_shaper.seeding import rng_for
from town_db.ages import ADULT_AGE_RANGE, CHILD_AGE_RANGE, age_on, birth_date_from_age, draw_age


def test_draw_age_stays_within_bracket_ranges():
    rng = rng_for(("town", 1), "test-ages")
    for _ in range(100):
        adult_age = draw_age(rng, "adult")
        assert ADULT_AGE_RANGE[0] <= adult_age <= ADULT_AGE_RANGE[1]
        child_age = draw_age(rng, "child")
        assert CHILD_AGE_RANGE[0] <= child_age <= CHILD_AGE_RANGE[1]


def test_draw_age_is_weighted_toward_younger_ages():
    rng = rng_for(("town", 1), "test-ages-weight")
    ages = [draw_age(rng, "adult") for _ in range(500)]
    young = sum(1 for a in ages if a < 40)
    old = sum(1 for a in ages if a >= 70)
    assert young > old


def test_birth_date_from_age_subtracts_years():
    reference = date(1300, 1, 1)
    assert birth_date_from_age(reference, 25) == date(1275, 1, 1)
    assert birth_date_from_age(reference, 0) == date(1300, 1, 1)


def test_age_on_computes_whole_years_elapsed():
    assert age_on(date(1275, 6, 15), date(1300, 1, 1)) == 24
    assert age_on(date(1275, 1, 1), date(1300, 1, 1)) == 25
    assert age_on(date(1300, 1, 1), date(1300, 1, 1)) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_ages.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_db.ages'`

- [ ] **Step 3: Write the ages module**

```python
# town_db/ages.py
from datetime import date
from typing import Tuple

ADULT_AGE_RANGE: Tuple[int, int] = (18, 90)
CHILD_AGE_RANGE: Tuple[int, int] = (0, 17)
AGE_DECAY_RATE = 0.97


def _weighted_age(rng, min_age: int, max_age: int, decay_rate: float = AGE_DECAY_RATE) -> int:
    ages = list(range(min_age, max_age + 1))
    weights = [decay_rate ** (age - min_age) for age in ages]
    return rng.choices(ages, weights=weights, k=1)[0]


def draw_age(rng, age_bracket: str) -> int:
    if age_bracket == "child":
        return _weighted_age(rng, *CHILD_AGE_RANGE)
    return _weighted_age(rng, *ADULT_AGE_RANGE)


def birth_date_from_age(reference_date: date, age: int) -> date:
    return date(reference_date.year - age, reference_date.month, reference_date.day)


def age_on(birth_date: date, on_date: date) -> int:
    age = on_date.year - birth_date.year
    if (on_date.month, on_date.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_ages.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add town_db/ages.py tests/test_db_ages.py
git commit -m "feat: add age-pyramid-weighted age drawing and birthdate math"
```

---

## Task 5: Household race/intermarriage and resident enrichment

**Files:**
- Create: `town_db/households.py`
- Test: `tests/test_db_households.py`

**Interfaces:**
- Consumes: `rng_for` from `town_shaper.seeding`; `RACE_WEIGHTS`, `draw_race`, `draw_gender`, `draw_first_name`, `draw_surname` from `town_db.names`; `draw_age`, `birth_date_from_age` from `town_db.ages`; a Town Shaper `Town` object (`town.residents`, `town.target_population`)
- Produces: `DEFAULT_INTERMARRIAGE_RATE = 0.08`, `NOBLE_POPULATION_RATIO = 200`, `build_households_and_residents(town, seed, reference_date, race_weights=RACE_WEIGHTS, intermarriage_rate=DEFAULT_INTERMARRIAGE_RATE) -> Tuple[List[dict], List[dict]]`

Each resident dict has keys: `town_shaper_id`, `household_id`, `first_name`, `last_name`, `gender`, `race`, `birth_date` (ISO string), `death_date` (`None`), `ses` (string), `is_noble` (bool), `home_building_id`, `workplace_building_id`, `occupation`, `age_bracket`. Each household dict has keys: `id`, `family_name`, `race`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_households.py
from datetime import date

from town_shaper.models import Household, ResidentSlot, SES, Town
from town_db.households import (
    DEFAULT_INTERMARRIAGE_RATE,
    NOBLE_POPULATION_RATIO,
    build_households_and_residents,
)

REFERENCE_DATE = date(1300, 1, 1)


def _make_town(residents):
    town = Town(seed=("town", 1), target_population=len(residents), bounds=(-10.0, -10.0, 10.0, 10.0))
    town.residents = residents
    return town


def test_build_households_and_residents_produces_one_household_per_group():
    residents = [
        ResidentSlot(id=0, household_id=1, ses=SES.POOR, age_bracket="adult"),
        ResidentSlot(id=1, household_id=1, ses=SES.POOR, age_bracket="adult"),
        ResidentSlot(id=2, household_id=1, ses=SES.POOR, age_bracket="child"),
        ResidentSlot(id=3, household_id=2, ses=SES.RICH, age_bracket="adult"),
    ]
    town = _make_town(residents)
    households, enriched = build_households_and_residents(town, ("town", 1), REFERENCE_DATE)

    assert {h["id"] for h in households} == {1, 2}
    assert len(enriched) == 4
    assert {r["household_id"] for r in enriched} == {1, 2}


def test_household_members_share_a_surname_and_usually_share_a_race():
    residents = [
        ResidentSlot(id=0, household_id=1, ses=SES.POOR, age_bracket="adult"),
        ResidentSlot(id=1, household_id=1, ses=SES.POOR, age_bracket="adult"),
        ResidentSlot(id=2, household_id=1, ses=SES.POOR, age_bracket="child"),
    ]
    town = _make_town(residents)
    households, enriched = build_households_and_residents(
        town, ("town", 1), REFERENCE_DATE, intermarriage_rate=0.0
    )
    surnames = {r["last_name"] for r in enriched}
    races = {r["race"] for r in enriched}
    assert len(surnames) == 1
    assert len(races) == 1  # intermarriage_rate=0.0 guarantees a single-race household


def test_build_households_and_residents_is_deterministic():
    residents = [
        ResidentSlot(id=i, household_id=i // 3, ses=SES.POOR, age_bracket="adult")
        for i in range(9)
    ]
    town = _make_town(residents)
    _, enriched1 = build_households_and_residents(town, ("town", 1), REFERENCE_DATE)
    _, enriched2 = build_households_and_residents(town, ("town", 1), REFERENCE_DATE)
    key = lambda r: (r["household_id"], r["first_name"], r["race"], r["birth_date"])
    assert [key(r) for r in enriched1] == [key(r) for r in enriched2]


def test_nobility_is_tagged_at_roughly_the_expected_ratio_and_only_rich_adults():
    target_population = 2000
    residents = [
        ResidentSlot(id=i, household_id=i, ses=SES.RICH, age_bracket="adult")
        for i in range(50)
    ] + [
        ResidentSlot(id=100 + i, household_id=100 + i, ses=SES.POOR, age_bracket="adult")
        for i in range(50)
    ]
    town = Town(seed=("town", 1), target_population=target_population, bounds=(-10.0, -10.0, 10.0, 10.0))
    town.residents = residents
    _, enriched = build_households_and_residents(town, ("town", 1), REFERENCE_DATE)

    nobles = [r for r in enriched if r["is_noble"]]
    expected = round(target_population / NOBLE_POPULATION_RATIO)
    assert len(nobles) == min(expected, 50)
    assert all(r["ses"] == "rich" for r in nobles)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_households.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_db.households'`

- [ ] **Step 3: Write the households module**

```python
# town_db/households.py
from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Tuple

from town_shaper.seeding import rng_for

from town_db.ages import birth_date_from_age, draw_age
from town_db.names import RACE_WEIGHTS, draw_first_name, draw_gender, draw_race, draw_surname

DEFAULT_INTERMARRIAGE_RATE = 0.08
NOBLE_POPULATION_RATIO = 200


def _group_by_household(residents) -> Dict[int, List[Any]]:
    groups: Dict[int, List[Any]] = defaultdict(list)
    for r in residents:
        groups[r.household_id].append(r)
    return groups


def build_households_and_residents(
    town,
    seed,
    reference_date: date,
    race_weights: Dict[str, float] = RACE_WEIGHTS,
    intermarriage_rate: float = DEFAULT_INTERMARRIAGE_RATE,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rng = rng_for(seed, "db", "households")

    groups = _group_by_household(town.residents)
    household_rows: List[Dict[str, Any]] = []
    resident_rows: List[Dict[str, Any]] = []

    for household_id in sorted(groups):
        members = groups[household_id]
        primary_race = draw_race(rng, race_weights)
        surname = draw_surname(rng, primary_race)
        household_rows.append({"id": household_id, "family_name": surname, "race": primary_race})

        adults = [m for m in members if m.age_bracket == "adult"]
        spouse = adults[1] if len(adults) > 1 else None
        spouse_race = primary_race
        if spouse is not None and rng.random() < intermarriage_rate:
            other_races = [r for r in race_weights if r != primary_race]
            if other_races:
                spouse_race = rng.choice(other_races)

        race_by_member_id = {}
        for member in members:
            if spouse is not None and member.id == spouse.id:
                race_by_member_id[member.id] = spouse_race
            elif member.age_bracket == "child":
                race_by_member_id[member.id] = rng.choice([primary_race, spouse_race])
            else:
                race_by_member_id[member.id] = primary_race

        for member in members:
            race = race_by_member_id[member.id]
            gender = draw_gender(rng)
            first_name = draw_first_name(rng, race, gender)
            age = draw_age(rng, member.age_bracket)
            birth_date = birth_date_from_age(reference_date, age)

            resident_rows.append({
                "town_shaper_id": member.id,
                "household_id": household_id,
                "first_name": first_name,
                "last_name": surname,
                "gender": gender,
                "race": race,
                "birth_date": birth_date.isoformat(),
                "death_date": None,
                "ses": member.ses.value,
                "is_noble": False,
                "home_building_id": member.home_building_id,
                "workplace_building_id": member.workplace_building_id,
                "occupation": member.occupation,
                "age_bracket": member.age_bracket,
            })

    _tag_nobility(rng, resident_rows, town.target_population)

    return household_rows, resident_rows


def _tag_nobility(rng, resident_rows: List[Dict[str, Any]], target_population: int) -> None:
    noble_count = max(0, round(target_population / NOBLE_POPULATION_RATIO))
    eligible = [r for r in resident_rows if r["ses"] == "rich" and r["age_bracket"] == "adult"]
    rng.shuffle(eligible)
    for row in eligible[:noble_count]:
        row["is_noble"] = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_households.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add town_db/households.py tests/test_db_households.py
git commit -m "feat: enrich households and residents with race, names, and ages"
```

---

## Task 6: Goods catalog and purchase generation

**Files:**
- Create: `town_db/goods.py`
- Create: `town_db/purchases.py`
- Test: `tests/test_db_goods_purchases.py`

**Interfaces:**
- Consumes: `rng_for` from `town_shaper.seeding`; household/resident dicts from Task 5's shape
- Produces: `GOODS_CATALOG: List[Dict]`, `insert_goods(conn) -> Dict[str, int]`, `SHOP_BUILDING_TYPES = {"shop", "tavern", "market_stall"}`, `WEEKLY_PURCHASE_COUNT_WEIGHTS`, `generate_purchases(seed, household_rows, resident_rows, goods_ids, shop_building_ids, year_start, weeks=52) -> List[dict]`

Each purchase dict has keys: `resident_db_id`, `shop_building_id`, `good_id`, `quantity`, `unit_price`, `total_price`, `purchase_date`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_goods_purchases.py
from datetime import date

from town_shaper.seeding import rng_for
from town_db.goods import GOODS_CATALOG, insert_goods
from town_db.purchases import generate_purchases
from town_db.schema import connect, create_schema

YEAR_START = date(1300, 1, 1)


def _household(id_):
    return {"id": id_, "family_name": "Smith", "race": "human"}


def _resident(db_id, household_id, age_bracket="adult"):
    return {
        "db_id": db_id, "household_id": household_id, "age_bracket": age_bracket,
        "ses": "poor", "is_noble": False,
    }


def test_insert_goods_populates_the_catalog(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    ids = insert_goods(conn)
    assert set(ids.keys()) == {g["name"] for g in GOODS_CATALOG}
    count = conn.execute("SELECT COUNT(*) FROM goods").fetchone()[0]
    assert count == len(GOODS_CATALOG)


def test_generate_purchases_returns_nothing_with_no_shops():
    households = [_household(1)]
    residents = [_resident(1, 1)]
    purchases = generate_purchases(
        ("town", 1), households, residents, {"bread": 1}, [], YEAR_START, weeks=4
    )
    assert purchases == []


def test_generate_purchases_only_references_provided_shops_and_goods():
    households = [_household(1), _household(2)]
    residents = [_resident(1, 1), _resident(2, 2)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    shop_ids = [10, 11, 12]
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, shop_ids, YEAR_START, weeks=52
    )
    assert len(purchases) > 0
    for p in purchases:
        assert p["shop_building_id"] in shop_ids
        assert p["good_id"] in goods_ids.values()
        assert p["total_price"] == round(p["unit_price"] * p["quantity"], 2)
        purchase_date = date.fromisoformat(p["purchase_date"])
        assert YEAR_START <= purchase_date < date(1301, 1, 1)


def test_generate_purchases_is_deterministic():
    households = [_household(1)]
    residents = [_resident(1, 1)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    p1 = generate_purchases(("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52)
    p2 = generate_purchases(("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52)
    assert p1 == p2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_goods_purchases.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_db.goods'`

- [ ] **Step 3: Write the goods module**

```python
# town_db/goods.py
from typing import Any, Dict, List

# A representative slice of medieval-demographics-made-easy.pdf's Support
# Value table: population needed to support one business of this type.
# Lower sv = more common = more frequently purchased.
GOODS_CATALOG: List[Dict[str, Any]] = [
    {"name": "bread", "category": "food", "typical_price": 0.05, "sv": 800},
    {"name": "meat", "category": "food", "typical_price": 0.20, "sv": 1200},
    {"name": "fish", "category": "food", "typical_price": 0.15, "sv": 1200},
    {"name": "ale", "category": "drink", "typical_price": 0.10, "sv": 1400},
    {"name": "wine", "category": "drink", "typical_price": 0.30, "sv": 900},
    {"name": "cloth garment", "category": "clothing", "typical_price": 2.0, "sv": 250},
    {"name": "shoes", "category": "clothing", "typical_price": 1.0, "sv": 150},
    {"name": "candles", "category": "household", "typical_price": 0.10, "sv": 700},
    {"name": "spices", "category": "luxury", "typical_price": 3.0, "sv": 1400},
    {"name": "tools", "category": "tools", "typical_price": 2.5, "sv": 1500},
    {"name": "furniture", "category": "household", "typical_price": 5.0, "sv": 550},
    {"name": "jewelry", "category": "luxury", "typical_price": 15.0, "sv": 400},
]


def insert_goods(conn) -> Dict[str, int]:
    ids: Dict[str, int] = {}
    for good in GOODS_CATALOG:
        cursor = conn.execute(
            "INSERT INTO goods (name, category, typical_price, sv) VALUES (?, ?, ?, ?)",
            (good["name"], good["category"], good["typical_price"], good["sv"]),
        )
        ids[good["name"]] = cursor.lastrowid
    return ids
```

- [ ] **Step 4: Write the purchases module**

```python
# town_db/purchases.py
from datetime import date, timedelta
from typing import Any, Dict, List

from town_shaper.seeding import rng_for

from town_db.goods import GOODS_CATALOG

SHOP_BUILDING_TYPES = {"shop", "tavern", "market_stall"}
WEEKLY_PURCHASE_COUNT_WEIGHTS = [40, 30, 20, 10]  # for 0, 1, 2, 3 purchases


def generate_purchases(
    seed,
    household_rows: List[Dict[str, Any]],
    resident_rows: List[Dict[str, Any]],
    goods_ids: Dict[str, int],
    shop_building_ids: List[int],
    year_start: date,
    weeks: int = 52,
) -> List[Dict[str, Any]]:
    if not shop_building_ids or not goods_ids:
        return []

    rng = rng_for(seed, "db", "purchases")

    sv_by_name = {g["name"]: g["sv"] for g in GOODS_CATALOG if g["name"] in goods_ids}
    price_by_name = {g["name"]: g["typical_price"] for g in GOODS_CATALOG if g["name"] in goods_ids}
    goods_names = list(sv_by_name.keys())
    good_weights = [1.0 / sv_by_name[name] for name in goods_names]

    residents_by_household: Dict[int, List[Dict[str, Any]]] = {}
    for row in resident_rows:
        if row.get("age_bracket") == "adult":
            residents_by_household.setdefault(row["household_id"], []).append(row)

    purchases: List[Dict[str, Any]] = []
    for week in range(weeks):
        week_start = year_start + timedelta(weeks=week)
        for household in household_rows:
            buyers = residents_by_household.get(household["id"], [])
            if not buyers:
                continue
            count = rng.choices([0, 1, 2, 3], weights=WEEKLY_PURCHASE_COUNT_WEIGHTS, k=1)[0]
            for _ in range(count):
                buyer = rng.choice(buyers)
                good_name = rng.choices(goods_names, weights=good_weights, k=1)[0]
                shop_id = rng.choice(shop_building_ids)
                quantity = rng.randint(1, 5)
                unit_price = round(price_by_name[good_name] * rng.uniform(0.85, 1.15), 2)
                day_offset = rng.randint(0, 6)
                purchase_date = week_start + timedelta(days=day_offset)

                purchases.append({
                    "resident_db_id": buyer["db_id"],
                    "shop_building_id": shop_id,
                    "good_id": goods_ids[good_name],
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "total_price": round(unit_price * quantity, 2),
                    "purchase_date": purchase_date.isoformat(),
                })

    return purchases
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_goods_purchases.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add town_db/goods.py town_db/purchases.py tests/test_db_goods_purchases.py
git commit -m "feat: add SV-weighted goods catalog and purchase generation"
```

---

## Task 7: Tax payment generation

**Files:**
- Create: `town_db/taxes.py`
- Test: `tests/test_db_taxes.py`

**Interfaces:**
- Consumes: `rng_for` from `town_shaper.seeding`; household/resident dicts (with `db_id`) from Task 5/6's shape
- Produces: `HEAD_TAX_AMOUNT: float`, `PROPERTY_TAX_RATE_BY_SES: Dict[str, float]`, `generate_tax_payments(seed, household_rows, resident_rows, year_start) -> List[dict]`

Each tax payment dict has keys: `resident_db_id`, `tax_type` (`"head_tax"` or `"property_tax"`), `amount`, `period`, `payment_date`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_taxes.py
from datetime import date

from town_db.taxes import HEAD_TAX_AMOUNT, generate_tax_payments

YEAR_START = date(1300, 1, 1)


def _resident(db_id, household_id, is_noble=False, age_bracket="adult", ses="poor"):
    return {
        "db_id": db_id, "household_id": household_id, "age_bracket": age_bracket,
        "ses": ses, "is_noble": is_noble,
    }


def test_head_tax_charged_once_per_adult_and_never_to_nobles_or_children():
    households = [{"id": 1, "family_name": "Smith", "race": "human"}]
    residents = [
        _resident(1, 1),                       # regular adult -> taxed
        _resident(2, 1, is_noble=True),         # noble -> exempt
        _resident(3, 1, age_bracket="child"),   # child -> exempt
    ]
    payments = generate_tax_payments(("town", 1), households, residents, YEAR_START)
    head_taxes = [p for p in payments if p["tax_type"] == "head_tax"]
    assert len(head_taxes) == 1
    assert head_taxes[0]["resident_db_id"] == 1
    assert head_taxes[0]["amount"] == HEAD_TAX_AMOUNT


def test_property_tax_charged_quarterly_per_household_and_scaled_by_ses():
    households = [{"id": 1, "family_name": "Rich", "race": "human"}, {"id": 2, "family_name": "Poor", "race": "human"}]
    residents = [
        _resident(1, 1, ses="rich"),
        _resident(2, 2, ses="poor"),
    ]
    payments = generate_tax_payments(("town", 1), households, residents, YEAR_START)
    property_taxes = [p for p in payments if p["tax_type"] == "property_tax"]
    assert len(property_taxes) == 8  # 2 households x 4 quarters

    rich_amount = next(p["amount"] for p in property_taxes if p["resident_db_id"] == 1)
    poor_amount = next(p["amount"] for p in property_taxes if p["resident_db_id"] == 2)
    assert rich_amount > poor_amount


def test_household_with_no_adults_pays_no_property_tax():
    households = [{"id": 1, "family_name": "Orphans", "race": "human"}]
    residents = [_resident(1, 1, age_bracket="child")]
    payments = generate_tax_payments(("town", 1), households, residents, YEAR_START)
    assert payments == []


def test_generate_tax_payments_is_deterministic():
    households = [{"id": 1, "family_name": "Smith", "race": "human"}]
    residents = [_resident(1, 1)]
    p1 = generate_tax_payments(("town", 1), households, residents, YEAR_START)
    p2 = generate_tax_payments(("town", 1), households, residents, YEAR_START)
    assert p1 == p2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_taxes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_db.taxes'`

- [ ] **Step 3: Write the taxes module**

```python
# town_db/taxes.py
from datetime import date, timedelta
from typing import Any, Dict, List

from town_shaper.seeding import rng_for

HEAD_TAX_AMOUNT = 0.5
PROPERTY_TAX_RATE_BY_SES = {"rich": 5.0, "poor": 1.0}


def generate_tax_payments(
    seed,
    household_rows: List[Dict[str, Any]],
    resident_rows: List[Dict[str, Any]],
    year_start: date,
) -> List[Dict[str, Any]]:
    rng = rng_for(seed, "db", "taxes")
    payments: List[Dict[str, Any]] = []

    for row in resident_rows:
        if row.get("age_bracket") != "adult" or row.get("is_noble"):
            continue
        day_offset = rng.randint(0, 364)
        payments.append({
            "resident_db_id": row["db_id"],
            "tax_type": "head_tax",
            "amount": HEAD_TAX_AMOUNT,
            "period": f"{year_start.year}",
            "payment_date": (year_start + timedelta(days=day_offset)).isoformat(),
        })

    residents_by_household: Dict[int, List[Dict[str, Any]]] = {}
    for row in resident_rows:
        if row.get("age_bracket") == "adult":
            residents_by_household.setdefault(row["household_id"], []).append(row)

    for household in household_rows:
        payers = residents_by_household.get(household["id"], [])
        if not payers:
            continue
        payer = rng.choice(payers)
        rate = PROPERTY_TAX_RATE_BY_SES.get(payer["ses"], PROPERTY_TAX_RATE_BY_SES["poor"])
        for quarter in range(4):
            quarter_start = year_start + timedelta(days=quarter * 91)
            day_offset = rng.randint(0, 90)
            payments.append({
                "resident_db_id": payer["db_id"],
                "tax_type": "property_tax",
                "amount": rate,
                "period": f"{year_start.year}-Q{quarter + 1}",
                "payment_date": (quarter_start + timedelta(days=day_offset)).isoformat(),
            })

    return payments
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_taxes.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add town_db/taxes.py tests/test_db_taxes.py
git commit -m "feat: add head tax and property tax generation"
```

---

## Task 8: Disease events, births, and deaths

**Files:**
- Create: `town_db/vital_records.py`
- Test: `tests/test_db_vital_records.py`

**Interfaces:**
- Consumes: `rng_for` from `town_shaper.seeding`; `draw_gender`, `draw_first_name` from `town_db.names`
- Produces: `DEFAULT_BIRTH_RATE`, `DEFAULT_DEATH_RATE_BY_AGE`, `DISEASE_DEATH_MULTIPLIER`, `DISEASE_EVENT_CHANCE`, `FERTILE_AGE_RANGE`, `generate_disease_events(seed, year_start, chance=DISEASE_EVENT_CHANCE) -> List[dict]`, `generate_births_and_deaths(seed, household_rows, resident_rows, disease_rows, year_start, temple_building_id, healer_building_id, birth_rate=DEFAULT_BIRTH_RATE, death_rate_by_age=DEFAULT_DEATH_RATE_BY_AGE) -> Tuple[List[dict], List[dict], List[dict]]`

`generate_births_and_deaths` returns `(births, deaths, new_resident_rows)`:
- `births` and `new_resident_rows` are **parallel lists** (same length, same order — `births[i]` is the birth record for the newborn at `new_resident_rows[i]`); the caller must insert `new_resident_rows` first to obtain each newborn's `db_id`, then set `births[i]["child_resident_id"] = new_resident_rows[i]["db_id"]` before inserting `births`.
- `deaths` dicts reference existing residents already in `resident_rows` (already have a `db_id`); `generate_births_and_deaths` also sets `resident_rows[i]["death_date"]` in place for anyone who died.
- Each `disease_rows` dict returned by `generate_disease_events` gets `event["_db_id"] = cursor.lastrowid` set by the caller after insertion, *before* calling `generate_births_and_deaths` (deaths need to reference `disease_event_id`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_vital_records.py
from datetime import date

from town_db.vital_records import (
    DEFAULT_DEATH_RATE_BY_AGE,
    DISEASE_DEATH_MULTIPLIER,
    generate_births_and_deaths,
    generate_disease_events,
)

YEAR_START = date(1300, 1, 1)


def _adult(db_id, household_id, gender, age_years, ses="poor", home_building_id=1, race="human"):
    birth_year = YEAR_START.year - age_years
    return {
        "db_id": db_id, "household_id": household_id, "gender": gender,
        "birth_date": date(birth_year, 1, 1).isoformat(), "death_date": None,
        "ses": ses, "is_noble": False, "home_building_id": home_building_id,
        "home_zone_type": "poor_residential", "age_bracket": "adult", "race": race,
    }


def test_generate_disease_events_shape_is_valid():
    events = generate_disease_events(("town", 1), YEAR_START, chance=1.0)
    assert len(events) == 1
    event = events[0]
    start = date.fromisoformat(event["start_date"])
    end = date.fromisoformat(event["end_date"])
    assert YEAR_START <= start < date(1301, 1, 1)
    assert end > start
    assert 0.0 < event["severity"] <= 1.0


def test_generate_disease_events_can_produce_none():
    events = generate_disease_events(("town", 1), YEAR_START, chance=0.0)
    assert events == []


def test_births_produce_matching_new_resident_and_birth_record():
    household = {"id": 1, "family_name": "Smith", "race": "human"}
    mother = _adult(1, 1, "female", 25)
    father = _adult(2, 1, "male", 27)
    households, residents = [household], [mother, father]

    births, deaths, new_residents = generate_births_and_deaths(
        ("town", 1), households, residents, [], YEAR_START,
        temple_building_id=99, healer_building_id=None, birth_rate=1.0,
    )
    assert len(births) == len(new_residents)
    if births:
        assert births[0]["_mother_db_id"] == 1
        assert new_residents[0]["household_id"] == 1
        assert new_residents[0]["age_bracket"] == "child"
        assert new_residents[0]["race"] in {"human"}


def test_no_reporting_building_means_no_births():
    household = {"id": 1, "family_name": "Smith", "race": "human"}
    mother = _adult(1, 1, "female", 25)
    father = _adult(2, 1, "male", 27)
    births, deaths, new_residents = generate_births_and_deaths(
        ("town", 1), [household], [mother, father], [], YEAR_START,
        temple_building_id=None, healer_building_id=None, birth_rate=1.0,
    )
    assert births == []
    assert new_residents == []


def test_death_rate_is_elevated_during_an_active_town_wide_disease_event():
    disease = {
        "_db_id": 1, "start_date": YEAR_START.isoformat(),
        "end_date": date(1300, 12, 31).isoformat(),
        "affected_zone_type": None, "severity": 1.0,
    }
    household = {"id": 1, "family_name": "Smith", "race": "human"}
    residents = [_adult(i, 1, "male", 30) for i in range(200)]

    _, deaths_with_disease, _ = generate_births_and_deaths(
        ("town", 1), [household], [dict(r) for r in residents], [disease], YEAR_START,
        temple_building_id=99, healer_building_id=None,
        death_rate_by_age={**DEFAULT_DEATH_RATE_BY_AGE, "adult": 0.01},
    )
    _, deaths_without_disease, _ = generate_births_and_deaths(
        ("town", 1), [household], [dict(r) for r in residents], [], YEAR_START,
        temple_building_id=99, healer_building_id=None,
        death_rate_by_age={**DEFAULT_DEATH_RATE_BY_AGE, "adult": 0.01},
    )
    assert len(deaths_with_disease) > len(deaths_without_disease)
    assert all(d["cause"] == "plague" for d in deaths_with_disease)
    assert all(d["disease_event_id"] == 1 for d in deaths_with_disease)


def test_a_resident_who_already_has_a_death_date_is_never_rolled_again():
    household = {"id": 1, "family_name": "Smith", "race": "human"}
    resident = _adult(1, 1, "male", 40)
    resident["death_date"] = "1299-05-01"
    _, deaths, _ = generate_births_and_deaths(
        ("town", 1), [household], [resident], [], YEAR_START,
        temple_building_id=99, healer_building_id=None,
        death_rate_by_age={**DEFAULT_DEATH_RATE_BY_AGE, "adult": 1.0},
    )
    assert deaths == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_vital_records.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_db.vital_records'`

- [ ] **Step 3: Write the vital records module**

```python
# town_db/vital_records.py
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from town_shaper.seeding import rng_for

from town_db.ages import age_on
from town_db.names import draw_first_name, draw_gender

DEFAULT_BIRTH_RATE = 0.09
DEFAULT_DEATH_RATE_BY_AGE = {
    "infant": 0.15,
    "child": 0.02,
    "adult": 0.01,
    "elderly": 0.06,
}
DISEASE_DEATH_MULTIPLIER = 4.0
DISEASE_EVENT_CHANCE = 0.3
FERTILE_AGE_RANGE = (16, 45)


def _age_category(age: int) -> str:
    if age == 0:
        return "infant"
    if age < 18:
        return "child"
    if age < 60:
        return "adult"
    return "elderly"


def generate_disease_events(
    seed, year_start: date, chance: float = DISEASE_EVENT_CHANCE
) -> List[Dict[str, Any]]:
    rng = rng_for(seed, "db", "disease_events")
    if rng.random() >= chance:
        return []
    start_offset = rng.randint(0, 300)
    duration = rng.randint(14, 90)
    start = year_start + timedelta(days=start_offset)
    return [{
        "name": "an outbreak of fever",
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=duration)).isoformat(),
        "affected_zone_type": None,
        "severity": round(rng.uniform(0.3, 1.0), 2),
    }]


def _active_disease(disease_rows: List[Dict[str, Any]], on_date: date, zone_type: Optional[str]):
    for event in disease_rows:
        start = date.fromisoformat(event["start_date"])
        end = date.fromisoformat(event["end_date"])
        if start <= on_date <= end:
            if event["affected_zone_type"] is None or event["affected_zone_type"] == zone_type:
                return event
    return None


def generate_births_and_deaths(
    seed,
    household_rows: List[Dict[str, Any]],
    resident_rows: List[Dict[str, Any]],
    disease_rows: List[Dict[str, Any]],
    year_start: date,
    temple_building_id: Optional[int],
    healer_building_id: Optional[int],
    birth_rate: float = DEFAULT_BIRTH_RATE,
    death_rate_by_age: Dict[str, float] = DEFAULT_DEATH_RATE_BY_AGE,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    rng = rng_for(seed, "db", "vital_records")
    reporting_building = temple_building_id if temple_building_id is not None else healer_building_id

    residents_by_household: Dict[int, List[Dict[str, Any]]] = {}
    for row in resident_rows:
        residents_by_household.setdefault(row["household_id"], []).append(row)

    births: List[Dict[str, Any]] = []
    new_resident_rows: List[Dict[str, Any]] = []

    if reporting_building is not None:
        for household in household_rows:
            members = residents_by_household.get(household["id"], [])
            adults = [m for m in members if m.get("age_bracket") == "adult" and m["death_date"] is None]
            mother = next(
                (m for m in adults if m["gender"] == "female"
                 and FERTILE_AGE_RANGE[0] <= age_on(date.fromisoformat(m["birth_date"]), year_start) <= FERTILE_AGE_RANGE[1]),
                None,
            )
            if mother is None or rng.random() >= birth_rate:
                continue
            father = next((m for m in adults if m is not mother), None)

            day_offset = rng.randint(0, 364)
            birth_date = year_start + timedelta(days=day_offset)
            child_race = rng.choice([mother["race"], father["race"]]) if father else mother["race"]
            child_gender = draw_gender(rng)
            child_first_name = draw_first_name(rng, child_race, child_gender)

            new_resident_rows.append({
                "household_id": household["id"],
                "first_name": child_first_name,
                "last_name": household["family_name"],
                "gender": child_gender,
                "race": child_race,
                "birth_date": birth_date.isoformat(),
                "death_date": None,
                "ses": mother["ses"],
                "is_noble": False,
                "home_building_id": mother["home_building_id"],
                "home_zone_type": mother.get("home_zone_type"),
                "workplace_building_id": None,
                "occupation": None,
                "age_bracket": "child",
            })
            births.append({
                "_mother_db_id": mother["db_id"],
                "_father_db_id": father["db_id"] if father else None,
                "birth_date": birth_date.isoformat(),
                "reported_by_building_id": reporting_building,
            })

    deaths: List[Dict[str, Any]] = []
    if reporting_building is not None:
        for row in resident_rows:
            if row["death_date"] is not None:
                continue
            age = age_on(date.fromisoformat(row["birth_date"]), year_start)
            category = _age_category(age)
            rate = death_rate_by_age[category]

            disease = _active_disease(disease_rows, year_start, row.get("home_zone_type"))
            if disease is not None:
                rate = min(1.0, rate * DISEASE_DEATH_MULTIPLIER * disease["severity"])

            if rng.random() >= rate:
                continue

            day_offset = rng.randint(0, 364)
            death_date = year_start + timedelta(days=day_offset)
            row["death_date"] = death_date.isoformat()

            if disease is not None:
                cause = "plague"
            elif category == "elderly":
                cause = rng.choice(["old age", "illness"])
            else:
                cause = rng.choice(["illness", "accident", "childbirth"])

            deaths.append({
                "resident_db_id": row["db_id"],
                "death_date": death_date.isoformat(),
                "cause": cause,
                "disease_event_id": disease["_db_id"] if disease is not None else None,
                "reported_by_building_id": reporting_building,
            })

    return births, deaths, new_resident_rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_vital_records.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add town_db/vital_records.py tests/test_db_vital_records.py
git commit -m "feat: add disease events, births, and age/disease-weighted deaths"
```

---

## Task 9: School/university enrollment and military service

**Files:**
- Create: `town_db/enrollment.py`
- Create: `town_db/military.py`
- Test: `tests/test_db_enrollment_military.py`

**Interfaces:**
- Consumes: `rng_for` from `town_shaper.seeding`
- Produces: `SCHOOL_AGE_RANGE`, `UNIVERSITY_AGE_RANGE`, `UNIVERSITY_ENROLLMENT_CHANCE`, `generate_school_enrollments(seed, resident_rows, school_building_ids, university_building_ids, year_start) -> List[dict]`; `MILITARY_OCCUPATIONS`, `generate_military_service(resident_rows, garrison_building_ids, year_start) -> List[dict]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_enrollment_military.py
from datetime import date

from town_db.enrollment import SCHOOL_AGE_RANGE, generate_school_enrollments
from town_db.military import MILITARY_OCCUPATIONS, generate_military_service

YEAR_START = date(1300, 1, 1)


def _resident(db_id, age_years, occupation=None, workplace_building_id=None):
    birth_year = YEAR_START.year - age_years
    return {
        "db_id": db_id, "birth_date": date(birth_year, 6, 1).isoformat(),
        "death_date": None, "occupation": occupation,
        "workplace_building_id": workplace_building_id,
    }


def test_school_age_child_enrolls_when_a_school_exists():
    resident = _resident(1, SCHOOL_AGE_RANGE[0])
    enrollments = generate_school_enrollments(
        ("town", 1), [resident], school_building_ids=[10], university_building_ids=[], year_start=YEAR_START
    )
    assert len(enrollments) == 1
    assert enrollments[0]["resident_db_id"] == 1
    assert enrollments[0]["enrollment_type"] == "school"
    assert enrollments[0]["school_building_id"] == 10


def test_no_enrollment_when_no_school_or_university_exists():
    resident = _resident(1, SCHOOL_AGE_RANGE[0])
    enrollments = generate_school_enrollments(
        ("town", 1), [resident], school_building_ids=[], university_building_ids=[], year_start=YEAR_START
    )
    assert enrollments == []


def test_out_of_range_age_never_enrolls():
    resident = _resident(1, 45)
    enrollments = generate_school_enrollments(
        ("town", 1), [resident], school_building_ids=[10], university_building_ids=[20], year_start=YEAR_START
    )
    assert enrollments == []


def test_military_service_only_for_military_occupations_at_a_real_garrison():
    soldier = _resident(1, 30, occupation="soldier", workplace_building_id=50)
    farmer = _resident(2, 30, occupation="farmer", workplace_building_id=51)
    soldier_wrong_building = _resident(3, 30, occupation="soldier", workplace_building_id=99)

    records = generate_military_service(
        [soldier, farmer, soldier_wrong_building], garrison_building_ids=[50], year_start=YEAR_START
    )
    assert len(records) == 1
    assert records[0]["resident_db_id"] == 1
    assert records[0]["garrison_building_id"] == 50


def test_military_service_skips_dead_residents():
    soldier = _resident(1, 30, occupation="soldier", workplace_building_id=50)
    soldier["death_date"] = "1299-01-01"
    records = generate_military_service([soldier], garrison_building_ids=[50], year_start=YEAR_START)
    assert records == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_enrollment_military.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_db.enrollment'`

- [ ] **Step 3: Write the enrollment module**

```python
# town_db/enrollment.py
from datetime import date
from typing import Any, Dict, List

from town_shaper.seeding import rng_for

SCHOOL_AGE_RANGE = (6, 12)
UNIVERSITY_AGE_RANGE = (18, 22)
UNIVERSITY_ENROLLMENT_CHANCE = 0.3


def generate_school_enrollments(
    seed,
    resident_rows: List[Dict[str, Any]],
    school_building_ids: List[int],
    university_building_ids: List[int],
    year_start: date,
) -> List[Dict[str, Any]]:
    rng = rng_for(seed, "db", "enrollment")
    enrollments: List[Dict[str, Any]] = []

    for row in resident_rows:
        if row["death_date"] is not None:
            continue
        birth_date = date.fromisoformat(row["birth_date"])
        age = year_start.year - birth_date.year

        if school_building_ids and SCHOOL_AGE_RANGE[0] <= age <= SCHOOL_AGE_RANGE[1]:
            enrollments.append({
                "resident_db_id": row["db_id"],
                "school_building_id": rng.choice(school_building_ids),
                "enrollment_type": "school",
                "start_date": year_start.isoformat(),
                "end_date": None,
            })
        elif university_building_ids and UNIVERSITY_AGE_RANGE[0] <= age <= UNIVERSITY_AGE_RANGE[1]:
            if rng.random() < UNIVERSITY_ENROLLMENT_CHANCE:
                enrollments.append({
                    "resident_db_id": row["db_id"],
                    "school_building_id": rng.choice(university_building_ids),
                    "enrollment_type": "university",
                    "start_date": year_start.isoformat(),
                    "end_date": None,
                })

    return enrollments
```

- [ ] **Step 4: Write the military module**

```python
# town_db/military.py
from datetime import date
from typing import Any, Dict, List

MILITARY_OCCUPATIONS = {"soldier", "guard"}
RANK_BY_OCCUPATION = {"soldier": "soldier", "guard": "guard"}


def generate_military_service(
    resident_rows: List[Dict[str, Any]],
    garrison_building_ids: List[int],
    year_start: date,
) -> List[Dict[str, Any]]:
    garrison_id_set = set(garrison_building_ids)
    records: List[Dict[str, Any]] = []
    for row in resident_rows:
        if row["death_date"] is not None:
            continue
        occupation = row.get("occupation")
        workplace_id = row.get("workplace_building_id")
        if occupation in MILITARY_OCCUPATIONS and workplace_id in garrison_id_set:
            records.append({
                "resident_db_id": row["db_id"],
                "garrison_building_id": workplace_id,
                "rank": RANK_BY_OCCUPATION[occupation],
                "start_date": year_start.isoformat(),
                "end_date": None,
            })
    return records
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_enrollment_military.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add town_db/enrollment.py town_db/military.py tests/test_db_enrollment_military.py
git commit -m "feat: add school/university enrollment and military service generation"
```

---

## Task 10: Top-level orchestrator and integration tests

**Files:**
- Create: `town_db/generate.py`
- Test: `tests/test_db_generate.py`

**Interfaces:**
- Consumes: everything from Tasks 1-9: `town_shaper.generate.generate_town`; `town_db.schema.{connect, create_schema}`; `town_db.names.RACE_WEIGHTS`; `town_db.households.{build_households_and_residents, DEFAULT_INTERMARRIAGE_RATE}`; `town_db.goods.insert_goods`; `town_db.purchases.{generate_purchases, SHOP_BUILDING_TYPES}`; `town_db.taxes.generate_tax_payments`; `town_db.vital_records.{generate_disease_events, generate_births_and_deaths, DEFAULT_BIRTH_RATE, DEFAULT_DEATH_RATE_BY_AGE}`; `town_db.enrollment.generate_school_enrollments`; `town_db.military.generate_military_service`
- Produces: `DEFAULT_YEAR_START = date(1300, 1, 1)`, `generate_town_database(seed, target_population, db_path, year_start=DEFAULT_YEAR_START, race_weights=RACE_WEIGHTS, intermarriage_rate=DEFAULT_INTERMARRIAGE_RATE, birth_rate=DEFAULT_BIRTH_RATE, death_rate_by_age=DEFAULT_DEATH_RATE_BY_AGE) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_generate.py
import sqlite3

from town_db.generate import generate_town_database


def test_generate_town_database_creates_a_populated_db(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path)

    conn = sqlite3.connect(db_path)
    resident_count = conn.execute("SELECT COUNT(*) FROM residents").fetchone()[0]
    building_count = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
    purchase_count = conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0]
    tax_count = conn.execute("SELECT COUNT(*) FROM tax_payments").fetchone()[0]

    assert resident_count > 0
    assert building_count > 0
    assert purchase_count > 0
    assert tax_count > 0


def test_generate_town_database_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []


def test_generate_town_database_is_deterministic(tmp_path):
    db_path_1 = str(tmp_path / "town1.db")
    db_path_2 = str(tmp_path / "town2.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_1)
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_2)

    conn1 = sqlite3.connect(db_path_1)
    conn2 = sqlite3.connect(db_path_2)
    for table in ["residents", "buildings", "purchases", "tax_payments", "births", "deaths"]:
        rows1 = conn1.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        rows2 = conn2.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        assert rows1 == rows2


def test_generate_town_database_business_rules(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path)
    conn = sqlite3.connect(db_path)

    noble_head_tax = conn.execute(
        "SELECT COUNT(*) FROM tax_payments tp "
        "JOIN residents r ON r.id = tp.resident_id "
        "WHERE tp.tax_type = 'head_tax' AND r.is_noble = 1"
    ).fetchone()[0]
    assert noble_head_tax == 0

    military_without_garrison_job = conn.execute(
        "SELECT COUNT(*) FROM military_service ms "
        "JOIN residents r ON r.id = ms.resident_id "
        "WHERE r.occupation NOT IN ('soldier', 'guard')"
    ).fetchone()[0]
    assert military_without_garrison_job == 0

    plague_deaths_missing_event = conn.execute(
        "SELECT COUNT(*) FROM deaths WHERE cause = 'plague' AND disease_event_id IS NULL"
    ).fetchone()[0]
    assert plague_deaths_missing_event == 0

    duplicate_deaths = conn.execute(
        "SELECT resident_id, COUNT(*) c FROM deaths GROUP BY resident_id HAVING c > 1"
    ).fetchall()
    assert duplicate_deaths == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_generate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_db.generate'`

- [ ] **Step 3: Write the orchestrator**

```python
# town_db/generate.py
import json
import sqlite3
from datetime import date
from typing import Any, Dict, List

from town_shaper.generate import generate_town

from town_db.enrollment import generate_school_enrollments
from town_db.goods import insert_goods
from town_db.households import DEFAULT_INTERMARRIAGE_RATE, build_households_and_residents
from town_db.military import generate_military_service
from town_db.names import RACE_WEIGHTS
from town_db.purchases import SHOP_BUILDING_TYPES, generate_purchases
from town_db.schema import connect, create_schema
from town_db.taxes import generate_tax_payments
from town_db.vital_records import (
    DEFAULT_BIRTH_RATE,
    DEFAULT_DEATH_RATE_BY_AGE,
    generate_births_and_deaths,
    generate_disease_events,
)

DEFAULT_YEAR_START = date(1300, 1, 1)


def generate_town_database(
    seed,
    target_population: int,
    db_path: str,
    year_start: date = DEFAULT_YEAR_START,
    race_weights: Dict[str, float] = RACE_WEIGHTS,
    intermarriage_rate: float = DEFAULT_INTERMARRIAGE_RATE,
    birth_rate: float = DEFAULT_BIRTH_RATE,
    death_rate_by_age: Dict[str, float] = DEFAULT_DEATH_RATE_BY_AGE,
) -> None:
    town = generate_town(seed, target_population)

    conn = connect(db_path)
    create_schema(conn)

    zone_type_by_building_id: Dict[int, str] = {}
    for district in town.districts:
        conn.execute(
            "INSERT INTO districts (id, zone_type, polygon) VALUES (?, ?, ?)",
            (district.id, district.zone_type.value, json.dumps(district.polygon)),
        )
        for building in district.buildings:
            conn.execute(
                "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (building.id, district.id, district.zone_type.value, building.building_type,
                 building.x, building.y, building.capacity),
            )
            zone_type_by_building_id[building.id] = district.zone_type.value

    household_rows, resident_rows = build_households_and_residents(
        town, seed, year_start, race_weights, intermarriage_rate,
    )
    for row in resident_rows:
        row["home_zone_type"] = zone_type_by_building_id.get(row["home_building_id"])

    for household in household_rows:
        conn.execute(
            "INSERT INTO households (id, family_name, race) VALUES (?, ?, ?)",
            (household["id"], household["family_name"], household["race"]),
        )

    _insert_residents(conn, resident_rows)

    goods_ids = insert_goods(conn)

    shop_building_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type in SHOP_BUILDING_TYPES
    ]
    purchases = generate_purchases(
        seed, household_rows, resident_rows, goods_ids, shop_building_ids, year_start,
    )
    for p in purchases:
        conn.execute(
            "INSERT INTO purchases (resident_id, shop_building_id, good_id, quantity, unit_price, total_price, purchase_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (p["resident_db_id"], p["shop_building_id"], p["good_id"], p["quantity"],
             p["unit_price"], p["total_price"], p["purchase_date"]),
        )

    tax_payments = generate_tax_payments(seed, household_rows, resident_rows, year_start)
    for t in tax_payments:
        conn.execute(
            "INSERT INTO tax_payments (resident_id, tax_type, amount, period, payment_date) VALUES (?, ?, ?, ?, ?)",
            (t["resident_db_id"], t["tax_type"], t["amount"], t["period"], t["payment_date"]),
        )

    disease_rows = generate_disease_events(seed, year_start)
    for d in disease_rows:
        cursor = conn.execute(
            "INSERT INTO disease_events (name, start_date, end_date, affected_zone_type, severity) VALUES (?, ?, ?, ?, ?)",
            (d["name"], d["start_date"], d["end_date"], d["affected_zone_type"], d["severity"]),
        )
        d["_db_id"] = cursor.lastrowid

    temple_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "temple"), None)
    healer_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "healer"), None)

    births, deaths, new_resident_rows = generate_births_and_deaths(
        seed, household_rows, resident_rows, disease_rows, year_start,
        temple_id, healer_id, birth_rate, death_rate_by_age,
    )
    _insert_residents(conn, new_resident_rows)
    for birth, new_row in zip(births, new_resident_rows):
        conn.execute(
            "INSERT INTO births (child_resident_id, mother_resident_id, father_resident_id, birth_date, reported_by_building_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (new_row["db_id"], birth["_mother_db_id"], birth["_father_db_id"],
             birth["birth_date"], birth["reported_by_building_id"]),
        )
    for death in deaths:
        conn.execute(
            "INSERT INTO deaths (resident_id, death_date, cause, disease_event_id, reported_by_building_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (death["resident_db_id"], death["death_date"], death["cause"],
             death["disease_event_id"], death["reported_by_building_id"]),
        )
        conn.execute(
            "UPDATE residents SET death_date = ? WHERE id = ?",
            (death["death_date"], death["resident_db_id"]),
        )

    all_resident_rows = resident_rows + new_resident_rows

    school_ids = [b.id for d in town.districts for b in d.buildings if b.building_type == "school"]
    university_ids = [b.id for d in town.districts for b in d.buildings if b.building_type == "university"]
    enrollments = generate_school_enrollments(seed, all_resident_rows, school_ids, university_ids, year_start)
    for e in enrollments:
        conn.execute(
            "INSERT INTO school_enrollments (resident_id, school_building_id, enrollment_type, start_date, end_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (e["resident_db_id"], e["school_building_id"], e["enrollment_type"], e["start_date"], e["end_date"]),
        )

    garrison_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type in {"garrison", "guard_post"}
    ]
    military = generate_military_service(all_resident_rows, garrison_ids, year_start)
    for m in military:
        conn.execute(
            "INSERT INTO military_service (resident_id, garrison_building_id, rank, start_date, end_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (m["resident_db_id"], m["garrison_building_id"], m["rank"], m["start_date"], m["end_date"]),
        )

    conn.commit()
    conn.close()


def _insert_residents(conn: sqlite3.Connection, resident_rows: List[Dict[str, Any]]) -> None:
    for row in resident_rows:
        cursor = conn.execute(
            "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, death_date, "
            "ses, is_noble, home_building_id, workplace_building_id, occupation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["household_id"], row["first_name"], row["last_name"], row["gender"], row["race"],
             row["birth_date"], row["death_date"], row["ses"], int(row["is_noble"]),
             row["home_building_id"], row["workplace_building_id"], row["occupation"]),
        )
        row["db_id"] = cursor.lastrowid
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_generate.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS — every Town Shaper test (with Task 1's additions) plus every `town_db` test.

- [ ] **Step 6: Commit**

```bash
git add town_db/generate.py tests/test_db_generate.py
git commit -m "feat: add generate_town_database orchestrator tying town_db together"
```

---

## Self-Review Notes

- **Spec coverage**: A-extension (Task 1), all core entity tables and registry tables (Tasks 2-9), the full generation pipeline including id-remapping discipline (Task 10), determinism via `rng_for` throughout (every task), the light-touch parameters (`race_weights`, `intermarriage_rate`, `birth_rate`, `death_rate_by_age` — all threaded through `generate_town_database`'s signature per the spec), and disease events with the death-rate multiplier are all covered. Error handling/edge cases from the spec (no eligible buildings → zero records, nobility exemption, one death per resident, plague deaths always carry `disease_event_id`) are covered by Tasks 7-10's tests. Testing strategy items (determinism, referential integrity via `PRAGMA foreign_key_check`, business rules) are covered by Task 10.
- **Type consistency**: `resident_rows` dict shape is defined once in Task 5 and consumed identically (same keys: `db_id`, `household_id`, `age_bracket`, `ses`, `is_noble`, `home_building_id`, `workplace_building_id`, `occupation`, `birth_date`, `death_date`, `home_zone_type`, `race`, `gender`) by Tasks 6-10 — verified no task introduces a differently-named field for the same concept. The `births`/`new_resident_rows` parallel-list contract (Task 8) is stated explicitly in that task's Interfaces block and honored by Task 10's `zip()` usage. `disease_rows`' `_db_id` backfill (Task 10, after insertion) matches what Task 8's `_active_disease`/death logic reads.
- **No placeholders**: every step contains complete, runnable code — no TBDs, no "add appropriate handling" steps.
