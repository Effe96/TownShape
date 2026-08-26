# Town Social Unrest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `aggression` parameter driving skirmish/incident events (poor residents vs. guard/soldier occupations) as a new event type in `town_db`'s year-of-history generation, plus a derived, on-demand `compute_stress` readout — threaded end-to-end through `TownParameters` → `generate_town_from_parameters`, the final piece of capability 1.

**Architecture:** `town_db/unrest.py` splits skirmish generation into two functions mirroring the existing `disease_events`/`generate_births_and_deaths` split exactly: `generate_skirmish_events` produces pure event data (no DB dependency), the caller inserts them and assigns `_db_id`, then `generate_skirmish_casualties` consumes the DB-id-populated events plus `resident_rows` to roll casualties among poor adults and guard/soldier residents, mutating `death_date` in place the same way `generate_births_and_deaths` already does. `town_db/stats.py`'s `compute_stress` is a plain query-time function with no stored state — `stress` is explicitly *not* an input parameter or a persisted column, per the design decision made during brainstorming. Every new parameter defaults to reproducing today's exact behavior.

**Tech Stack:** Python 3.12, stdlib only (`sqlite3`) — no new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-08-26-town-social-unrest-design.md`

## Global Constraints

- Every new parameter (`aggression`) is optional with a default that reproduces today's exact behavior (`0.0` — zero skirmishes, zero behavior change) — no existing call site or test outside the files this plan touches should require changes.
- `aggression` is validated `0.0 <= aggression <= 1.0` in `TownParameters.__post_init__`, raising `ValueError` otherwise — same pattern as `magic_prevalence`. No upper bound is enforced anywhere else in the pipeline (matches this project's established tolerance for extreme parameter combinations degrading gracefully).
- Skirmish casualties are restricted to **poor adults** (`ses == "poor" and age_bracket == "adult"`) and **guard/soldier occupations** (reusing the existing `MILITARY_OCCUPATIONS = {"guard", "soldier"}` constant from `town_db/military.py` — do not redefine this set in the new module). A resident who is a guard/soldier is classified by occupation first, regardless of SES; children and rich non-guard residents are never eligible.
- `stress` is **not** a `TownParameters` input and is **not** persisted anywhere — `town_db.stats.compute_stress(db_path)` is a plain, stateless, query-time function callable independently of `town_narrative`.
- **Known intermediate test-failure window (matches the pattern established in 1c):** Task 1's schema change makes `generation_parameters.aggression` `NOT NULL` with no default. `town_narrative/generate.py`'s `generate_town_from_parameters` (untouched until Task 5) still inserts the old 10-column list, so after Task 1 lands, all 9 tests in `tests/test_narrative_generate.py` fail with `NOT NULL constraint failed: generation_parameters.aggression` until Task 5 fixes it. This is intentional and documented at Task 1 and Task 4's "run the whole suite" steps — do not attempt to fix it early.
- Test files for the new `town_db/unrest.py` and `town_db/stats.py` modules go to `tests/test_db_unrest.py` and `tests/test_db_stats.py` respectively, matching the project's one-file-per-module convention; changes to existing modules are tested by appending to their existing test files.

---

## Task 1: DB schema — `skirmish_events` table, `deaths.skirmish_event_id`, `generation_parameters.aggression`

**Files:**
- Modify: `town_db/schema.py`
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Produces: `skirmish_events` table (`id, name, skirmish_date, severity`); `deaths.skirmish_event_id INTEGER REFERENCES skirmish_events(id)` (nullable); `generation_parameters.aggression REAL NOT NULL`.

- [ ] **Step 1: Write the failing tests**

Add `"skirmish_events"` to `EXPECTED_TABLES` in `tests/test_db_schema.py`:

```python
EXPECTED_TABLES = {
    "districts", "buildings", "households", "residents", "goods",
    "purchases", "tax_payments", "disease_events", "births", "deaths",
    "school_enrollments", "military_service", "generation_parameters",
    "water_features", "skirmish_events",
}
```

Replace `test_generation_parameters_accepts_a_row` (currently ends with a
`magic_prevalence` column and no `aggression`):

```python
def test_generation_parameters_accepts_a_row(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute(
        "INSERT INTO generation_parameters (seed, target_population, area_per_resident_multiplier, "
        "density_multiplier, rich_proportion, num_rivers, has_coastline, has_port, magic_prevalence, aggression) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("('town', 1)", 1500, 1.0, 1.0, 0.05, 1, 1, 1, 0.3, 0.2),
    )
    conn.commit()
    row = conn.execute(
        "SELECT seed, target_population, area_per_resident_multiplier, density_multiplier, rich_proportion, "
        "num_rivers, has_coastline, has_port, magic_prevalence, aggression FROM generation_parameters"
    ).fetchone()
    assert row == ("('town', 1)", 1500, 1.0, 1.0, 0.05, 1, 1, 1, 0.3, 0.2)
```

Append three new tests:

```python
def test_skirmish_events_accepts_a_row(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    cursor = conn.execute(
        "INSERT INTO skirmish_events (name, skirmish_date, severity) VALUES (?, ?, ?)",
        ("a clash between the poor quarter and the city guard", "1300-05-01", 0.7),
    )
    conn.commit()
    row = conn.execute(
        "SELECT name, skirmish_date, severity FROM skirmish_events WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    assert row == ("a clash between the poor quarter and the city guard", "1300-05-01", 0.7)


def test_deaths_skirmish_event_id_defaults_to_null(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'guard_post', 0.0, 0.0, 0)"
    )
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.execute(
        "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, ses) "
        "VALUES (1, 'Ann', 'Smith', 'female', 'human', '1280-01-01', 'poor')"
    )
    conn.execute(
        "INSERT INTO deaths (resident_id, death_date, cause, reported_by_building_id) VALUES (1, '1300-01-01', 'illness', 1)"
    )
    row = conn.execute("SELECT skirmish_event_id FROM deaths WHERE resident_id = 1").fetchone()
    assert row[0] is None


def test_deaths_skirmish_event_id_accepts_a_value(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'guard_post', 0.0, 0.0, 0)"
    )
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.execute(
        "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, ses) "
        "VALUES (1, 'Ann', 'Smith', 'female', 'human', '1280-01-01', 'poor')"
    )
    cursor = conn.execute(
        "INSERT INTO skirmish_events (name, skirmish_date, severity) VALUES (?, ?, ?)",
        ("a clash", "1300-05-01", 0.5),
    )
    skirmish_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO deaths (resident_id, death_date, cause, skirmish_event_id, reported_by_building_id) "
        "VALUES (1, '1300-05-01', 'skirmish', ?, 1)",
        (skirmish_id,),
    )
    row = conn.execute("SELECT skirmish_event_id FROM deaths WHERE resident_id = 1").fetchone()
    assert row[0] == skirmish_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: FAIL — `test_create_schema_creates_every_table` fails its subset assertion; `test_generation_parameters_accepts_a_row` fails with `sqlite3.OperationalError: table generation_parameters has no column named aggression`; the three new tests fail with `no such table: skirmish_events` / `no such column: skirmish_event_id`.

- [ ] **Step 3: Modify the implementation**

In `town_db/schema.py`, add a new table right after `disease_events` and before `births`:

```sql
CREATE TABLE skirmish_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    skirmish_date TEXT NOT NULL,
    severity REAL NOT NULL
);
```

Change the `deaths` table from:

```sql
CREATE TABLE deaths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL UNIQUE REFERENCES residents(id),
    death_date TEXT NOT NULL,
    cause TEXT NOT NULL,
    disease_event_id INTEGER REFERENCES disease_events(id),
    reported_by_building_id INTEGER NOT NULL REFERENCES buildings(id)
);
```

to:

```sql
CREATE TABLE deaths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL UNIQUE REFERENCES residents(id),
    death_date TEXT NOT NULL,
    cause TEXT NOT NULL,
    disease_event_id INTEGER REFERENCES disease_events(id),
    skirmish_event_id INTEGER REFERENCES skirmish_events(id),
    reported_by_building_id INTEGER NOT NULL REFERENCES buildings(id)
);
```

Change the `generation_parameters` table from:

```sql
CREATE TABLE generation_parameters (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    seed TEXT NOT NULL,
    target_population INTEGER NOT NULL,
    area_per_resident_multiplier REAL NOT NULL,
    density_multiplier REAL NOT NULL,
    rich_proportion REAL NOT NULL,
    num_rivers INTEGER NOT NULL,
    has_coastline INTEGER NOT NULL,
    has_port INTEGER NOT NULL,
    magic_prevalence REAL NOT NULL
);
```

to:

```sql
CREATE TABLE generation_parameters (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    seed TEXT NOT NULL,
    target_population INTEGER NOT NULL,
    area_per_resident_multiplier REAL NOT NULL,
    density_multiplier REAL NOT NULL,
    rich_proportion REAL NOT NULL,
    num_rivers INTEGER NOT NULL,
    has_coastline INTEGER NOT NULL,
    has_port INTEGER NOT NULL,
    magic_prevalence REAL NOT NULL,
    aggression REAL NOT NULL
);
```

- [ ] **Step 4: Run the schema tests to verify they pass**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite — confirm the *only* failures are the 9 expected ones**

Run: `python -m pytest tests/ -q`
Expected: exactly these 9 tests FAIL, all in `tests/test_narrative_generate.py`, all with `sqlite3.IntegrityError: NOT NULL constraint failed: generation_parameters.aggression` — because `town_narrative/generate.py`'s `generate_town_from_parameters` (untouched until Task 5) still inserts the old 10-column list:
- `test_generate_town_from_parameters_creates_a_populated_db`
- `test_generate_town_from_parameters_records_one_generation_parameters_row`
- `test_generate_town_from_parameters_passes_foreign_key_check`
- `test_generate_town_from_parameters_threads_density_multiplier_into_building_count`
- `test_generate_town_from_parameters_threads_rich_proportion_into_resident_ses`
- `test_generate_town_from_parameters_records_water_params`
- `test_generate_town_from_parameters_with_water_passes_foreign_key_check`
- `test_generate_town_from_parameters_records_magic_prevalence`
- `test_generate_town_from_parameters_with_magic_passes_foreign_key_check`

This is expected and intentional — Task 5 fixes it. `tests/test_db_generate.py` is unaffected (it never writes to `generation_parameters`). If any test fails that is **not** in this list, stop and treat it as a real regression — do not proceed to commit.

- [ ] **Step 6: Commit**

```bash
git add town_db/schema.py tests/test_db_schema.py
git commit -m "feat: add skirmish_events table and aggression column"
```

---

## Task 2: Skirmish event and casualty generation (`town_db/unrest.py`)

**Files:**
- Create: `town_db/unrest.py`
- Test: `tests/test_db_unrest.py`

**Interfaces:**
- Consumes: `MILITARY_OCCUPATIONS` (existing constant from `town_db/military.py`)
- Produces: `generate_skirmish_events(seed, year_start: date, aggression: float, weeks: int = 52) -> List[Dict[str, Any]]` (each dict: `name`, `skirmish_date`, `severity` — no `_db_id` yet); `generate_skirmish_casualties(seed, resident_rows: List[Dict], skirmish_rows: List[Dict], reporting_building_id: Optional[int]) -> List[Dict[str, Any]]` (each death dict: `resident_db_id`, `death_date`, `cause`, `skirmish_event_id`, `reported_by_building_id`) — mutates `resident_rows`' `death_date` in place for new casualties; `skirmish_rows` must already have `_db_id` populated by the caller (mirrors the existing `disease_rows`/`_db_id` convention in `town_db/vital_records.py`).

**Note on the two-function split:** the design spec sketches a single
`generate_skirmish_events(...) -> Tuple[events, deaths]` function, but a
death record needs its `skirmish_event_id` to reference the *real*
database id of its skirmish — which only exists after the caller has
inserted the event row and read back `cursor.lastrowid`. A single function
called before any insert has happened cannot produce that id. Splitting
into `generate_skirmish_events` (pure event data, no DB dependency) and a
second `generate_skirmish_casualties` (consumes events that already carry
`_db_id`, assigned by the caller in between) resolves this the same way
`disease_events`/`generate_births_and_deaths` already do it in
`town_db/vital_records.py` and `town_db/generate.py` — insert first, assign
`_db_id`, then generate anything that must reference it. This is a
deliberate, spec-preserving refinement, not a deviation to flag: the final
table shapes, casualty rules, and generation ordering are unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_db_unrest.py`:

```python
# tests/test_db_unrest.py
from datetime import date

from town_db.military import MILITARY_OCCUPATIONS
from town_db.unrest import generate_skirmish_casualties, generate_skirmish_events

YEAR_START = date(1300, 1, 1)


def _resident(db_id, ses="poor", age_bracket="adult", occupation=None, death_date=None):
    return {
        "db_id": db_id, "ses": ses, "age_bracket": age_bracket,
        "occupation": occupation, "death_date": death_date,
    }


def test_generate_skirmish_events_produces_none_at_zero_aggression():
    events = generate_skirmish_events(("town", 1), YEAR_START, aggression=0.0)
    assert events == []


def test_generate_skirmish_events_frequency_scales_with_aggression():
    low_total = 0
    high_total = 0
    trials = 30
    for seed_index in range(trials):
        low_total += len(generate_skirmish_events(("town", seed_index), YEAR_START, aggression=0.05))
        high_total += len(generate_skirmish_events(("town", seed_index), YEAR_START, aggression=0.9))
    assert high_total > low_total


def test_generate_skirmish_events_shape_is_valid():
    # aggression=100.0 forces a skirmish every single week (weekly chance is
    # capped at 1.0 in practice since rng.random() < 1.0 always), making this
    # deterministic rather than relying on a specific seed happening to roll one.
    events = generate_skirmish_events(("town", 1), YEAR_START, aggression=100.0)
    assert len(events) == 52
    for event in events:
        d = date.fromisoformat(event["skirmish_date"])
        assert YEAR_START <= d < date(1301, 1, 1)
        assert 0.2 <= event["severity"] <= 1.0
        assert event["name"]


def test_casualties_only_ever_poor_adults_or_guards():
    residents = (
        [_resident(i, ses="poor", age_bracket="adult") for i in range(200)]
        + [_resident(200 + i, ses="poor", age_bracket="child") for i in range(50)]
        + [_resident(300 + i, ses="rich", age_bracket="adult") for i in range(50)]
        + [_resident(400 + i, ses="rich", age_bracket="adult", occupation="guard") for i in range(10)]
        + [_resident(500 + i, ses="poor", age_bracket="adult", occupation="soldier") for i in range(10)]
    )
    skirmishes = [{"_db_id": 1, "skirmish_date": "1300-06-01", "severity": 1.0}]
    deaths = generate_skirmish_casualties(("town", 1), residents, skirmishes, reporting_building_id=99)

    resident_by_id = {r["db_id"]: r for r in residents}
    assert len(deaths) > 0
    for death in deaths:
        resident = resident_by_id[death["resident_db_id"]]
        is_guard = resident["occupation"] in MILITARY_OCCUPATIONS
        is_poor_adult = resident["ses"] == "poor" and resident["age_bracket"] == "adult"
        assert is_guard or is_poor_adult
        assert resident["age_bracket"] != "child"


def test_no_reporting_building_means_no_casualties():
    residents = [_resident(i, ses="poor", age_bracket="adult") for i in range(500)]
    skirmishes = [{"_db_id": 1, "skirmish_date": "1300-06-01", "severity": 1.0}]
    deaths = generate_skirmish_casualties(("town", 1), residents, skirmishes, reporting_building_id=None)
    assert deaths == []


def test_a_resident_who_already_died_is_never_a_casualty():
    resident = _resident(1, ses="poor", age_bracket="adult", death_date="1299-05-01")
    skirmishes = [{"_db_id": 1, "skirmish_date": "1300-06-01", "severity": 1.0}]
    deaths = generate_skirmish_casualties(("town", 1), [resident], skirmishes, reporting_building_id=99)
    assert deaths == []


def test_casualty_records_reference_the_correct_skirmish_and_building():
    residents = [_resident(i, occupation="guard") for i in range(50)]
    skirmishes = [{"_db_id": 7, "skirmish_date": "1300-06-01", "severity": 1.0}]
    deaths = generate_skirmish_casualties(("town", 1), residents, skirmishes, reporting_building_id=42)
    assert len(deaths) > 0
    for death in deaths:
        assert death["skirmish_event_id"] == 7
        assert death["reported_by_building_id"] == 42
        assert death["cause"] == "skirmish"


def test_casualties_mutate_resident_death_date_in_place():
    residents = [_resident(i, occupation="guard") for i in range(50)]
    skirmishes = [{"_db_id": 1, "skirmish_date": "1300-06-01", "severity": 1.0}]
    deaths = generate_skirmish_casualties(("town", 1), residents, skirmishes, reporting_building_id=99)
    assert len(deaths) > 0
    dead_ids = {d["resident_db_id"] for d in deaths}
    for resident in residents:
        if resident["db_id"] in dead_ids:
            assert resident["death_date"] == "1300-06-01"
        else:
            assert resident["death_date"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_unrest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_db.unrest'`

- [ ] **Step 3: Write the implementation**

```python
# town_db/unrest.py
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from town_shaper.seeding import rng_for

from town_db.military import MILITARY_OCCUPATIONS

SKIRMISH_WEEKLY_CHANCE_SCALE = 0.1
POOR_CASUALTY_RATE_SCALE = 0.002
GUARD_CASUALTY_RATE_SCALE = 0.01
SKIRMISH_NAME = "a clash between the poor quarter and the city guard"


def generate_skirmish_events(
    seed, year_start: date, aggression: float, weeks: int = 52,
) -> List[Dict[str, Any]]:
    rng = rng_for(seed, "db", "unrest_events")
    events: List[Dict[str, Any]] = []
    if aggression <= 0:
        return events

    for week in range(weeks):
        week_start = year_start + timedelta(weeks=week)
        if rng.random() >= aggression * SKIRMISH_WEEKLY_CHANCE_SCALE:
            continue
        day_offset = rng.randint(0, 6)
        skirmish_date = week_start + timedelta(days=day_offset)
        events.append({
            "name": SKIRMISH_NAME,
            "skirmish_date": skirmish_date.isoformat(),
            "severity": round(rng.uniform(0.2, 1.0), 2),
        })
    return events


def generate_skirmish_casualties(
    seed,
    resident_rows: List[Dict[str, Any]],
    skirmish_rows: List[Dict[str, Any]],
    reporting_building_id: Optional[int],
) -> List[Dict[str, Any]]:
    if reporting_building_id is None:
        return []

    rng = rng_for(seed, "db", "unrest_casualties")
    deaths: List[Dict[str, Any]] = []

    for skirmish in skirmish_rows:
        severity = skirmish["severity"]
        for row in resident_rows:
            if row["death_date"] is not None:
                continue
            is_guard = row.get("occupation") in MILITARY_OCCUPATIONS
            is_poor_adult = row.get("ses") == "poor" and row.get("age_bracket") == "adult"
            if is_guard:
                rate = severity * GUARD_CASUALTY_RATE_SCALE
            elif is_poor_adult:
                rate = severity * POOR_CASUALTY_RATE_SCALE
            else:
                continue
            if rng.random() >= rate:
                continue

            row["death_date"] = skirmish["skirmish_date"]
            deaths.append({
                "resident_db_id": row["db_id"],
                "death_date": skirmish["skirmish_date"],
                "cause": "skirmish",
                "skirmish_event_id": skirmish["_db_id"],
                "reported_by_building_id": reporting_building_id,
            })

    return deaths
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_unrest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_db/unrest.py tests/test_db_unrest.py
git commit -m "feat: add skirmish event and casualty generation"
```

---

## Task 3: Derived `stress` (`town_db/stats.py`)

**Files:**
- Create: `town_db/stats.py`
- Test: `tests/test_db_stats.py`

**Interfaces:**
- Consumes: nothing new (reads `residents`/`skirmish_events` tables directly, both present after Task 1)
- Produces: `compute_stress(db_path: str) -> float`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_db_stats.py`:

```python
# tests/test_db_stats.py
from town_db.schema import connect, create_schema
from town_db.stats import compute_stress


def _insert_resident(conn, resident_id, ses, household_id=1):
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses) "
        "VALUES (?, ?, 'A', 'B', 'male', 'human', '1280-01-01', ?)",
        (resident_id, household_id, ses),
    )


def _setup_db(db_path, poor_count, rich_count):
    conn = connect(db_path)
    create_schema(conn)
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    for i in range(poor_count):
        _insert_resident(conn, i + 1, "poor")
    for i in range(rich_count):
        _insert_resident(conn, poor_count + i + 1, "rich")
    conn.commit()
    conn.close()


def test_compute_stress_returns_zero_for_empty_database(tmp_path):
    db_path = str(tmp_path / "empty.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.commit()
    conn.close()
    assert compute_stress(db_path) == 0.0


def test_compute_stress_increases_with_higher_poor_fraction(tmp_path):
    low_poor_path = str(tmp_path / "low_poor.db")
    high_poor_path = str(tmp_path / "high_poor.db")
    _setup_db(low_poor_path, poor_count=10, rich_count=90)
    _setup_db(high_poor_path, poor_count=90, rich_count=10)
    assert compute_stress(high_poor_path) > compute_stress(low_poor_path)


def test_compute_stress_increases_with_more_skirmish_events(tmp_path):
    db_path = str(tmp_path / "town.db")
    _setup_db(db_path, poor_count=50, rich_count=50)
    baseline = compute_stress(db_path)

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO skirmish_events (name, skirmish_date, severity) VALUES (?, ?, ?)",
        ("a clash", "1300-06-01", 0.8),
    )
    conn.commit()
    conn.close()
    assert compute_stress(db_path) > baseline


def test_compute_stress_is_clamped_at_one(tmp_path):
    db_path = str(tmp_path / "town.db")
    _setup_db(db_path, poor_count=100, rich_count=0)
    conn = connect(db_path)
    for _ in range(20):
        conn.execute(
            "INSERT INTO skirmish_events (name, skirmish_date, severity) VALUES (?, ?, ?)",
            ("a clash", "1300-06-01", 1.0),
        )
    conn.commit()
    conn.close()
    assert compute_stress(db_path) == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_stats.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_db.stats'`

- [ ] **Step 3: Write the implementation**

```python
# town_db/stats.py
import sqlite3

STRESS_PER_SKIRMISH = 0.1


def compute_stress(db_path: str) -> float:
    conn = sqlite3.connect(db_path)
    poor_count, total_count = conn.execute(
        "SELECT SUM(CASE WHEN ses = 'poor' THEN 1 ELSE 0 END), COUNT(*) FROM residents"
    ).fetchone()
    skirmish_count = conn.execute("SELECT COUNT(*) FROM skirmish_events").fetchone()[0]
    conn.close()

    if not total_count:
        return 0.0

    poor_fraction = poor_count / total_count
    return min(1.0, poor_fraction + skirmish_count * STRESS_PER_SKIRMISH)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_stats.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_db/stats.py tests/test_db_stats.py
git commit -m "feat: add compute_stress derived metric"
```

---

## Task 4: `generate_town_database` threads `aggression` end-to-end (`town_db/generate.py`)

**Files:**
- Modify: `town_db/generate.py`
- Test: `tests/test_db_generate.py`

**Interfaces:**
- Consumes: `generate_skirmish_events(seed, year_start, aggression, weeks=52)` (Task 2), `generate_skirmish_casualties(seed, resident_rows, skirmish_rows, reporting_building_id)` (Task 2), `skirmish_events` table + `deaths.skirmish_event_id` (Task 1)
- Produces: `generate_town_database(..., aggression: float = 0.0) -> None`, now also writing `skirmish_events` rows and any resulting `deaths` rows with `cause='skirmish'`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db_generate.py`:

```python
def test_generate_town_database_default_aggression_matches_previous_behavior(tmp_path):
    db_path_a = str(tmp_path / "a.db")
    db_path_b = str(tmp_path / "b.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_a)
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_b, aggression=0.0)

    conn_a = sqlite3.connect(db_path_a)
    conn_b = sqlite3.connect(db_path_b)
    for table in ["residents", "buildings", "deaths"]:
        rows_a = conn_a.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        rows_b = conn_b.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        assert rows_a == rows_b

    assert conn_a.execute("SELECT COUNT(*) FROM skirmish_events").fetchone()[0] == 0


def test_generate_town_database_high_aggression_produces_skirmishes_and_maybe_casualties(tmp_path):
    found_casualty = False
    for seed_index in range(10):
        db_path = str(tmp_path / f"town_{seed_index}.db")
        generate_town_database(
            ("town", seed_index), target_population=5000, db_path=db_path, aggression=1.0,
        )
        conn = sqlite3.connect(db_path)
        skirmish_count = conn.execute("SELECT COUNT(*) FROM skirmish_events").fetchone()[0]
        assert skirmish_count > 0

        skirmish_death_count = conn.execute(
            "SELECT COUNT(*) FROM deaths WHERE cause = 'skirmish'"
        ).fetchone()[0]
        if skirmish_death_count > 0:
            found_casualty = True

    assert found_casualty


def test_generate_town_database_with_aggression_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(
        ("town", 1), target_population=5000, db_path=db_path, aggression=1.0,
    )
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_generate.py -v -k aggression`
Expected: FAIL with `TypeError: generate_town_database() got an unexpected keyword argument 'aggression'`

- [ ] **Step 3: Modify the implementation**

Add to the imports in `town_db/generate.py`:

```python
from town_db.unrest import generate_skirmish_casualties, generate_skirmish_events
```

Change `generate_town_database`'s signature from ending with `magic_prevalence: float = 0.0,\n) -> None:` to:

```python
    magic_prevalence: float = 0.0,
    aggression: float = 0.0,
) -> None:
```

(no other change to the `generate_town(...)` call — `aggression` does not affect `town_shaper`, only `town_db`'s year-of-history generation)

Immediately after the existing deaths-insert loop (the one ending with the `UPDATE residents SET death_date = ...` for disease/age deaths, right before `goods_ids = insert_goods(conn)`), insert:

```python
    guard_post_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "guard_post"), None)
    garrison_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "garrison"), None)
    reporting_building_id = guard_post_id if guard_post_id is not None else garrison_id

    skirmish_rows = generate_skirmish_events(seed, year_start, aggression)
    for s in skirmish_rows:
        cursor = conn.execute(
            "INSERT INTO skirmish_events (name, skirmish_date, severity) VALUES (?, ?, ?)",
            (s["name"], s["skirmish_date"], s["severity"]),
        )
        s["_db_id"] = cursor.lastrowid

    skirmish_deaths = generate_skirmish_casualties(seed, resident_rows, skirmish_rows, reporting_building_id)
    for death in skirmish_deaths:
        conn.execute(
            "INSERT INTO deaths (resident_id, death_date, cause, skirmish_event_id, reported_by_building_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (death["resident_db_id"], death["death_date"], death["cause"],
             death["skirmish_event_id"], death["reported_by_building_id"]),
        )
        conn.execute(
            "UPDATE residents SET death_date = ? WHERE id = ?",
            (death["death_date"], death["resident_db_id"]),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_generate.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: PASS for every test except the same 9 `tests/test_narrative_generate.py` tests listed in Task 1's Step 5 (still failing with the same `NOT NULL constraint failed: generation_parameters.aggression` — `town_narrative/generate.py` is untouched until Task 5). Confirm no *other* test fails before committing — any new failure outside that list of 9 is a real regression from this task's changes.

- [ ] **Step 6: Commit**

```bash
git add town_db/generate.py tests/test_db_generate.py
git commit -m "feat: thread aggression through generate_town_database"
```

---

## Task 5: `TownParameters` gains `aggression`; `generate_town_from_parameters` wiring

**Files:**
- Modify: `town_narrative/parameters.py`
- Modify: `town_narrative/generate.py`
- Test: `tests/test_narrative_parameters.py`
- Test: `tests/test_narrative_generate.py`

**Interfaces:**
- Consumes: `generate_town_database(..., aggression=0.0)` (Task 4)
- Produces: `TownParameters` gains `aggression: float = 0.0` — `__post_init__` raises `ValueError` for values outside `[0.0, 1.0]`. `generate_town_from_parameters` passes it through and records it in `generation_parameters`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_narrative_parameters.py`:

```python
def test_aggression_default_is_zero():
    params = TownParameters(seed="town-1", target_population=1000)
    assert params.aggression == 0.0


def test_aggression_out_of_range_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, aggression=1.5)
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, aggression=-0.1)


def test_aggression_boundary_values_are_valid():
    TownParameters(seed="town-1", target_population=1000, aggression=0.0)
    TownParameters(seed="town-1", target_population=1000, aggression=1.0)
```

Append to `tests/test_narrative_generate.py`:

```python
def test_generate_town_from_parameters_records_aggression(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(seed=("town", 1), target_population=1500, aggression=0.4)
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT aggression FROM generation_parameters").fetchone()
    assert row == (0.4,)


def test_generate_town_from_parameters_with_aggression_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(seed=("town", 1), target_population=5000, aggression=1.0)
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_narrative_parameters.py tests/test_narrative_generate.py -v -k aggression`
Expected: FAIL with `TypeError: TownParameters.__init__() got an unexpected keyword argument 'aggression'`

- [ ] **Step 3: Update `town_narrative/parameters.py`**

Replace the whole file:

```python
from dataclasses import dataclass
from typing import Any

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
```

- [ ] **Step 4: Update `town_narrative/generate.py`**

Replace the whole file:

```python
from town_db.generate import generate_town_database
from town_db.schema import connect

from town_narrative.parameters import TownParameters


def generate_town_from_parameters(params: TownParameters, db_path: str) -> None:
    generate_town_database(
        params.seed,
        params.target_population,
        db_path,
        area_per_resident_multiplier=params.area_per_resident_multiplier,
        density_multiplier=params.density_multiplier,
        rich_proportion=params.rich_proportion,
        num_rivers=params.num_rivers,
        has_coastline=params.has_coastline,
        has_port=params.has_port,
        magic_prevalence=params.magic_prevalence,
        aggression=params.aggression,
    )

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO generation_parameters (id, seed, target_population, area_per_resident_multiplier, "
        "density_multiplier, rich_proportion, num_rivers, has_coastline, has_port, magic_prevalence, aggression) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, str(params.seed), params.target_population, params.area_per_resident_multiplier,
         params.density_multiplier, params.rich_proportion, params.num_rivers,
         int(params.has_coastline), int(params.has_port), params.magic_prevalence, params.aggression),
    )
    conn.commit()
    conn.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_narrative_parameters.py tests/test_narrative_generate.py -v`
Expected: PASS

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: PASS for every test — this fixes all 9 previously-expected failures.

- [ ] **Step 7: Commit**

```bash
git add town_narrative/parameters.py town_narrative/generate.py tests/test_narrative_parameters.py tests/test_narrative_generate.py
git commit -m "feat: add aggression to TownParameters"
```

---

## Task 6: Narrative-mapping doc and skill update

**Files:**
- Modify: `docs/narrative-town-parameters.md`
- Modify: `.claude/skills/generate-town-from-narrative/SKILL.md`

**Interfaces:**
- Consumes: `TownParameters` (Task 5), `compute_stress` (Task 3)
- Produces: updated agent-neutral reference documentation and Claude Code skill wrapper.

- [ ] **Step 1: Update the reference doc**

In `docs/narrative-town-parameters.md`, after the `magic_prevalence` bullet in the `## Fields` section, insert:

```markdown
- **`aggression`** (default `0.0`) — how prone the population is to
  skirmishes/incidents between the poor quarter and the city guard, as a
  fraction from `0.0` (none) to `1.0` (frequent unrest). Drives skirmish
  event frequency across the simulated year; skirmishes can produce
  resident casualties among poor adults and guard/soldier-occupation
  residents specifically.

  There is no `stress` input field — it's a **derived** value, not
  something you set. After generating a town, call
  `town_db.stats.compute_stress(db_path)` to get a `0.0`-`1.0` readout
  reflecting the town's poor-population fraction and observed skirmish
  frequency, if you need to describe the town's overall tension level in
  narrative terms.
```

Add rows to the `## Narrative language → value` table (after the
`magic_prevalence` rows, before the closing paragraph):

```markdown
| "restless", "prone to riots", "tense streets" | `aggression` | 0.3 – 0.6 |
| "peaceful", "orderly", "no unrest" | `aggression` | 0.0 (default) |
| (no aggression cue) | `aggression` | 0.0 (default) |
```

- [ ] **Step 2: Update the skill file**

In `.claude/skills/generate-town-from-narrative/SKILL.md`, change step 2 of the procedure from:

```markdown
2. **Map narrative language onto `TownParameters` fields** using
   `docs/narrative-town-parameters.md` as the reference table. Fields
   available today: `seed`, `target_population`,
   `area_per_resident_multiplier`, `density_multiplier`,
   `rich_proportion`, `num_rivers`, `has_coastline`, `has_port`,
   `magic_prevalence`.
```

to:

```markdown
2. **Map narrative language onto `TownParameters` fields** using
   `docs/narrative-town-parameters.md` as the reference table. Fields
   available today: `seed`, `target_population`,
   `area_per_resident_multiplier`, `density_multiplier`,
   `rich_proportion`, `num_rivers`, `has_coastline`, `has_port`,
   `magic_prevalence`, `aggression`.
```

Change the example `TownParameters(...)` construction in step 5 from:

```python
   params = TownParameters(
       seed=<a stable seed derived from the campaign/town name>,
       target_population=<int>,
       area_per_resident_multiplier=<float>,
       density_multiplier=<float>,
       rich_proportion=<float>,
       num_rivers=<int>,
       has_coastline=<bool>,
       has_port=<bool>,
       magic_prevalence=<float>,
   )
```

to:

```python
   params = TownParameters(
       seed=<a stable seed derived from the campaign/town name>,
       target_population=<int>,
       area_per_resident_multiplier=<float>,
       density_multiplier=<float>,
       rich_proportion=<float>,
       num_rivers=<int>,
       has_coastline=<bool>,
       has_port=<bool>,
       magic_prevalence=<float>,
       aggression=<float>,
   )
```

- [ ] **Step 3: Verify both files are internally consistent**

Run: `python -c "import pathlib; text = pathlib.Path('docs/narrative-town-parameters.md').read_text(); assert 'aggression' in text and 'compute_stress' in text; skill = pathlib.Path('.claude/skills/generate-town-from-narrative/SKILL.md').read_text(); assert 'aggression' in skill; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Run the whole suite one last time**

Run: `python -m pytest tests/ -q`
Expected: PASS for every test

- [ ] **Step 5: Commit**

```bash
git add docs/narrative-town-parameters.md .claude/skills/generate-town-from-narrative/SKILL.md
git commit -m "docs: document aggression narrative-mapping fields and compute_stress"
```
