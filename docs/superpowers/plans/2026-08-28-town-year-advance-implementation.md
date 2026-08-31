# Town Year-Advance (Capability 2, Slice 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an already-generated town keep living — `advance_town(db_path, seed, years)` simulates a town forward N more years using the existing per-year generators against current state, plus two new mechanics (household formation, job-market succession) that make later years meaningfully different from year 1.

**Architecture:** A new orchestrator (`town_db/simulation.py`) reads the current town state from SQLite into the same in-memory row-dict shapes the existing `town_db` generators already expect, re-runs those generators unchanged with a per-year derived seed, layers two new DB-mutating passes (household formation, job-market fill) between vital records and economic activity, persists everything back, and re-syncs the derived relationship tables. Existing insert logic is extracted out of `town_db/generate.py` into a shared `town_db/persistence.py` first, so both the original one-shot generator and the new orchestrator use the same, single implementation.

**Tech Stack:** Python stdlib `sqlite3`, `town_shaper.seeding.rng_for` (deterministic per-call RNG derivation), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-28-town-year-advance-design.md`

## Global Constraints

- Every new/changed RNG draw goes through `town_shaper.seeding.rng_for(seed, *parts)` — never bare `random` module state (matches every existing `town_db` generator).
- `advance_town` and both new mechanics (`household_formation.py`, `job_market.py`) operate directly on a `sqlite3.Connection` via raw SQL — no ORM, matching the whole `town_db` package.
- `town_state` is written unconditionally by `generate_town_database` itself and carries its own `year_start`/`aggression`/`magic_prevalence` — it must never depend on `generation_parameters`, which `town_narrative.generate_town_from_parameters` is the only writer of (confirmed: every test in `tests/test_db_generate.py` calls `generate_town_database` directly, with no `generation_parameters` row ever created for those databases).
- A "year" is exactly `YEAR_LENGTH_DAYS = 365` days everywhere in this plan (matches `vital_records.py`'s existing `rng.randint(0, 364)` day-offset range).
- Every task that touches an existing module must leave that module's existing tests passing unchanged — these are explicit regression-guard steps, not assumptions.

---

## Task 1: `town_state` schema table

**Files:**
- Modify: `town_db/schema.py`
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Produces: `town_state` table — columns `id, year_start, current_date, aggression, magic_prevalence`, singleton row (`id = 1`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db_schema.py` (add `"town_state"` to the existing `EXPECTED_TABLES` set at the top of the file too):

```python
def test_town_state_accepts_a_row(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute(
        "INSERT INTO town_state (id, year_start, current_date, aggression, magic_prevalence) "
        "VALUES (1, ?, ?, ?, ?)",
        ("1300-01-01", "1301-01-01", 0.2, 0.1),
    )
    conn.commit()
    row = conn.execute(
        "SELECT year_start, current_date, aggression, magic_prevalence FROM town_state WHERE id = 1"
    ).fetchone()
    assert row == ("1300-01-01", "1301-01-01", 0.2, 0.1)


def test_town_state_enforces_singleton(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute(
        "INSERT INTO town_state (id, year_start, current_date, aggression, magic_prevalence) "
        "VALUES (1, '1300-01-01', '1301-01-01', 0.0, 0.0)"
    )
    conn.commit()
    try:
        conn.execute(
            "INSERT INTO town_state (id, year_start, current_date, aggression, magic_prevalence) "
            "VALUES (2, '1300-01-01', '1301-01-01', 0.0, 0.0)"
        )
        assert False, "expected a CHECK constraint violation"
    except sqlite3.IntegrityError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: FAIL — `sqlite3.OperationalError: no such table: town_state`

- [ ] **Step 3: Add the table to the schema**

In `town_db/schema.py`, add to `SCHEMA_SQL` (anywhere after `generation_parameters`, before the closing `"""`):

```sql
CREATE TABLE town_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    year_start TEXT NOT NULL,
    current_date TEXT NOT NULL,
    aggression REAL NOT NULL,
    magic_prevalence REAL NOT NULL
);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: PASS (all tests, including the two new ones)

- [ ] **Step 5: Commit**

```bash
git add town_db/schema.py tests/test_db_schema.py
git commit -m "feat: add town_state singleton table for year-advance tracking"
```

---

## Task 2: Extract `town_db/persistence.py`, wire `town_state` into `generate_town_database`

**Files:**
- Create: `town_db/persistence.py`
- Modify: `town_db/generate.py`
- Test: `tests/test_db_persistence.py`
- Test: `tests/test_db_generate.py` (extend)

**Interfaces:**
- Consumes: `town_state` table from Task 1.
- Produces (for Task 7 to reuse): `insert_residents(conn, resident_rows) -> None` (sets `row["db_id"]` in place), `insert_disease_events(conn, disease_rows) -> None` (sets `row["_db_id"]`), `insert_skirmish_events(conn, skirmish_rows) -> None` (sets `row["_db_id"]`), `insert_births(conn, births, new_resident_rows) -> None`, `insert_deaths(conn, deaths) -> None`, `insert_purchases(conn, purchases) -> None`, `insert_tax_payments(conn, tax_payments) -> None`, `insert_school_enrollments(conn, enrollments) -> None`, `insert_military_service(conn, records) -> None`. Also `town_db.generate.YEAR_LENGTH_DAYS = 365`.

This task is a pure refactor (extraction) plus one small new-behavior addition (the `town_state` insert) — kept together because both land in the same file and the refactor exists specifically to support the new insert.

- [ ] **Step 1: Write the failing persistence tests**

Create `tests/test_db_persistence.py`:

```python
from town_db.persistence import insert_deaths, insert_residents
from town_db.schema import connect, create_schema


def _insert_household(conn, household_id=1):
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (?, 'Smith', 'human')", (household_id,))


def test_insert_residents_sets_db_id_in_place(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    _insert_household(conn)
    rows = [{
        "household_id": 1, "first_name": "Ann", "last_name": "Smith", "gender": "female", "race": "human",
        "birth_date": "1280-01-01", "death_date": None, "ses": "poor", "is_noble": False,
        "has_magical_talent": False, "home_building_id": None, "workplace_building_id": None, "occupation": None,
    }]
    insert_residents(conn, rows)
    conn.commit()
    assert rows[0]["db_id"] is not None
    stored = conn.execute("SELECT first_name FROM residents WHERE id = ?", (rows[0]["db_id"],)).fetchone()
    assert stored == ("Ann",)


def test_insert_deaths_accepts_disease_or_skirmish_cause_and_updates_resident(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    _insert_household(conn)
    rows = [{
        "household_id": 1, "first_name": "Ann", "last_name": "Smith", "gender": "female", "race": "human",
        "birth_date": "1280-01-01", "death_date": None, "ses": "poor", "is_noble": False,
        "has_magical_talent": False, "home_building_id": None, "workplace_building_id": None, "occupation": None,
    }]
    insert_residents(conn, rows)
    conn.commit()
    resident_db_id = rows[0]["db_id"]

    insert_deaths(conn, [{
        "resident_db_id": resident_db_id, "death_date": "1300-06-01", "cause": "illness",
        "reported_by_building_id": None,
    }])
    conn.commit()

    death_row = conn.execute(
        "SELECT death_date, cause, disease_event_id, skirmish_event_id FROM deaths WHERE resident_id = ?",
        (resident_db_id,),
    ).fetchone()
    assert death_row == ("1300-06-01", "illness", None, None)
    resident_row = conn.execute("SELECT death_date FROM residents WHERE id = ?", (resident_db_id,)).fetchone()
    assert resident_row == ("1300-06-01",)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_persistence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'town_db.persistence'`

- [ ] **Step 3: Create `town_db/persistence.py`**

```python
# town_db/persistence.py
import sqlite3
from typing import Any, Dict, List


def insert_residents(conn: sqlite3.Connection, resident_rows: List[Dict[str, Any]]) -> None:
    for row in resident_rows:
        cursor = conn.execute(
            "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, death_date, "
            "ses, is_noble, has_magical_talent, home_building_id, workplace_building_id, occupation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["household_id"], row["first_name"], row["last_name"], row["gender"], row["race"],
             row["birth_date"], row["death_date"], row["ses"], int(row["is_noble"]),
             int(row.get("has_magical_talent", False)),
             row["home_building_id"], row["workplace_building_id"], row["occupation"]),
        )
        row["db_id"] = cursor.lastrowid


def insert_disease_events(conn: sqlite3.Connection, disease_rows: List[Dict[str, Any]]) -> None:
    for d in disease_rows:
        cursor = conn.execute(
            "INSERT INTO disease_events (name, start_date, end_date, affected_zone_type, severity) "
            "VALUES (?, ?, ?, ?, ?)",
            (d["name"], d["start_date"], d["end_date"], d["affected_zone_type"], d["severity"]),
        )
        d["_db_id"] = cursor.lastrowid


def insert_skirmish_events(conn: sqlite3.Connection, skirmish_rows: List[Dict[str, Any]]) -> None:
    for s in skirmish_rows:
        cursor = conn.execute(
            "INSERT INTO skirmish_events (name, skirmish_date, severity) VALUES (?, ?, ?)",
            (s["name"], s["skirmish_date"], s["severity"]),
        )
        s["_db_id"] = cursor.lastrowid


def insert_births(conn: sqlite3.Connection, births: List[Dict[str, Any]], new_resident_rows: List[Dict[str, Any]]) -> None:
    for birth, new_row in zip(births, new_resident_rows):
        conn.execute(
            "INSERT INTO births (child_resident_id, mother_resident_id, father_resident_id, birth_date, "
            "reported_by_building_id) VALUES (?, ?, ?, ?, ?)",
            (new_row["db_id"], birth["_mother_db_id"], birth["_father_db_id"],
             birth["birth_date"], birth["reported_by_building_id"]),
        )


def insert_deaths(conn: sqlite3.Connection, deaths: List[Dict[str, Any]]) -> None:
    # A single unified statement for both disease-caused and skirmish-caused deaths -- each death
    # dict only ever populates one of disease_event_id/skirmish_event_id, so .get() gives the
    # other column NULL exactly as the old two separate call sites did implicitly.
    for death in deaths:
        conn.execute(
            "INSERT INTO deaths (resident_id, death_date, cause, disease_event_id, skirmish_event_id, "
            "reported_by_building_id) VALUES (?, ?, ?, ?, ?, ?)",
            (death["resident_db_id"], death["death_date"], death["cause"],
             death.get("disease_event_id"), death.get("skirmish_event_id"), death["reported_by_building_id"]),
        )
        conn.execute(
            "UPDATE residents SET death_date = ? WHERE id = ?",
            (death["death_date"], death["resident_db_id"]),
        )


def insert_purchases(conn: sqlite3.Connection, purchases: List[Dict[str, Any]]) -> None:
    for p in purchases:
        conn.execute(
            "INSERT INTO purchases (resident_id, shop_building_id, good_id, quantity, unit_price, total_price, "
            "purchase_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (p["resident_db_id"], p["shop_building_id"], p["good_id"], p["quantity"],
             p["unit_price"], p["total_price"], p["purchase_date"]),
        )


def insert_tax_payments(conn: sqlite3.Connection, tax_payments: List[Dict[str, Any]]) -> None:
    for t in tax_payments:
        conn.execute(
            "INSERT INTO tax_payments (resident_id, tax_type, amount, period, payment_date) VALUES (?, ?, ?, ?, ?)",
            (t["resident_db_id"], t["tax_type"], t["amount"], t["period"], t["payment_date"]),
        )


def insert_school_enrollments(conn: sqlite3.Connection, enrollments: List[Dict[str, Any]]) -> None:
    for e in enrollments:
        conn.execute(
            "INSERT INTO school_enrollments (resident_id, school_building_id, enrollment_type, start_date, "
            "end_date) VALUES (?, ?, ?, ?, ?)",
            (e["resident_db_id"], e["school_building_id"], e["enrollment_type"], e["start_date"], e["end_date"]),
        )


def insert_military_service(conn: sqlite3.Connection, records: List[Dict[str, Any]]) -> None:
    for m in records:
        conn.execute(
            "INSERT INTO military_service (resident_id, garrison_building_id, rank, start_date, end_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (m["resident_db_id"], m["garrison_building_id"], m["rank"], m["start_date"], m["end_date"]),
        )
```

- [ ] **Step 4: Run persistence tests to verify they pass**

Run: `python -m pytest tests/test_db_persistence.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing `town_state` + backward-compatibility tests**

Add to `tests/test_db_generate.py`:

```python
def test_generate_town_database_writes_town_state(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path, aggression=0.3, magic_prevalence=0.1)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT year_start, current_date, aggression, magic_prevalence FROM town_state WHERE id = 1"
    ).fetchone()
    assert row == ("1300-01-01", "1301-01-01", 0.3, 0.1)


def test_generate_town_database_unchanged_by_persistence_refactor(tmp_path):
    # Regression guard for the generate.py -> persistence.py extraction: every existing table's
    # content for a fixed seed must be byte-identical to before the refactor.
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path)
    conn = sqlite3.connect(db_path)
    for table in ["residents", "households", "buildings", "purchases", "tax_payments",
                  "births", "deaths", "school_enrollments", "military_service", "skirmish_events"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count >= 0  # table exists and is queryable
    resident_count = conn.execute("SELECT COUNT(*) FROM residents").fetchone()[0]
    assert resident_count > 1000  # sanity floor matching the existing plausibility-bounds test
```

(The `test_generate_town_database_is_deterministic` test already in this file, run again after Step 6, is the real regression guard — it compares two independently generated databases row-for-row across the tables the refactor touches.)

- [ ] **Step 6: Run to verify the new tests fail, existing tests still discoverable**

Run: `python -m pytest tests/test_db_generate.py -v`
Expected: the two new tests FAIL (`no such table: town_state` / assertion), existing tests still PASS (nothing touched yet)

- [ ] **Step 7: Refactor `town_db/generate.py` to use `persistence.py`, and add the `town_state` insert**

Replace the full contents of `town_db/generate.py` with:

```python
import json
from datetime import date, timedelta
from typing import Dict

from town_shaper.assignment import DEFAULT_RICH_PROPORTION
from town_shaper.generate import generate_town

from town_db.enrollment import generate_school_enrollments
from town_db.goods import insert_goods
from town_db.households import DEFAULT_INTERMARRIAGE_RATE, build_households_and_residents
from town_db.military import generate_military_service
from town_db.names import RACE_WEIGHTS
from town_db.persistence import (
    insert_births,
    insert_deaths,
    insert_disease_events,
    insert_military_service,
    insert_purchases,
    insert_residents,
    insert_school_enrollments,
    insert_skirmish_events,
    insert_tax_payments,
)
from town_db.purchases import SHOP_BUILDING_TYPES, generate_purchases
from town_db.schema import connect, create_schema
from town_db.taxes import generate_tax_payments
from town_db.unrest import generate_skirmish_casualties, generate_skirmish_events
from town_db.vital_records import (
    DEFAULT_BIRTH_RATE,
    DEFAULT_DEATH_RATE_BY_AGE,
    generate_births_and_deaths,
    generate_disease_events,
)

DEFAULT_YEAR_START = date(1300, 1, 1)
YEAR_LENGTH_DAYS = 365


def generate_town_database(
    seed,
    target_population: int,
    db_path: str,
    year_start: date = DEFAULT_YEAR_START,
    race_weights: Dict[str, float] = RACE_WEIGHTS,
    intermarriage_rate: float = DEFAULT_INTERMARRIAGE_RATE,
    birth_rate: float = DEFAULT_BIRTH_RATE,
    death_rate_by_age: Dict[str, float] = DEFAULT_DEATH_RATE_BY_AGE,
    area_per_resident_multiplier: float = 1.0,
    density_multiplier: float = 1.0,
    rich_proportion: float = DEFAULT_RICH_PROPORTION,
    num_rivers: int = 0,
    has_coastline: bool = False,
    has_port: bool = False,
    magic_prevalence: float = 0.0,
    aggression: float = 0.0,
) -> None:
    town = generate_town(
        seed, target_population,
        area_per_resident_multiplier=area_per_resident_multiplier,
        density_multiplier=density_multiplier,
        rich_proportion=rich_proportion,
        num_rivers=num_rivers,
        has_coastline=has_coastline,
        has_port=has_port,
        magic_prevalence=magic_prevalence,
    )

    conn = connect(db_path)
    create_schema(conn)

    for feature in town.water_features:
        polygon = feature.polygon
        rings = [list(polygon.exterior.coords)[:-1]] + [
            list(interior.coords)[:-1] for interior in polygon.interiors
        ]
        conn.execute(
            "INSERT INTO water_features (id, kind, polygon) VALUES (?, ?, ?)",
            (feature.id, feature.kind, json.dumps(rings)),
        )

    zone_type_by_building_id: Dict[int, str] = {}
    for district in town.districts:
        conn.execute(
            "INSERT INTO districts (id, zone_type, polygon) VALUES (?, ?, ?)",
            (district.id, district.zone_type.value, json.dumps(district.polygon_parts)),
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
        town, seed, year_start, race_weights, intermarriage_rate, magic_prevalence=magic_prevalence,
    )
    for row in resident_rows:
        row["home_zone_type"] = zone_type_by_building_id.get(row["home_building_id"])

    for household in household_rows:
        conn.execute(
            "INSERT INTO households (id, family_name, race) VALUES (?, ?, ?)",
            (household["id"], household["family_name"], household["race"]),
        )

    insert_residents(conn, resident_rows)

    # Vital records run BEFORE purchases and taxes so that residents who die
    # partway through the year stop shopping and paying tax on their death
    # date, rather than transacting for the whole year regardless.
    disease_rows = generate_disease_events(seed, year_start)
    insert_disease_events(conn, disease_rows)

    temple_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "temple"), None)
    healer_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "healer"), None)

    births, deaths, new_resident_rows = generate_births_and_deaths(
        seed, household_rows, resident_rows, disease_rows, year_start,
        temple_id, healer_id, birth_rate, death_rate_by_age,
    )
    insert_residents(conn, new_resident_rows)
    insert_births(conn, births, new_resident_rows)
    insert_deaths(conn, deaths)

    guard_post_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "guard_post"), None)
    garrison_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "garrison"), None)
    reporting_building_id = guard_post_id if guard_post_id is not None else garrison_id

    skirmish_rows = generate_skirmish_events(seed, year_start, aggression)
    insert_skirmish_events(conn, skirmish_rows)

    skirmish_deaths = generate_skirmish_casualties(seed, resident_rows, skirmish_rows, reporting_building_id)
    insert_deaths(conn, skirmish_deaths)

    goods_ids = insert_goods(conn)

    shop_building_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type in SHOP_BUILDING_TYPES
    ]
    arcane_shop_building_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type == "arcane_shop"
    ]
    blacksmith_building_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type == "blacksmith"
    ]
    purchases = generate_purchases(
        seed, household_rows, resident_rows, goods_ids, shop_building_ids, year_start,
        magic_prevalence=magic_prevalence, arcane_shop_building_ids=arcane_shop_building_ids,
        blacksmith_building_ids=blacksmith_building_ids,
    )
    insert_purchases(conn, purchases)

    tax_payments = generate_tax_payments(seed, household_rows, resident_rows, year_start)
    insert_tax_payments(conn, tax_payments)

    all_resident_rows = resident_rows + new_resident_rows

    school_ids = [b.id for d in town.districts for b in d.buildings if b.building_type == "school"]
    university_ids = [b.id for d in town.districts for b in d.buildings if b.building_type == "university"]
    enrollments = generate_school_enrollments(seed, all_resident_rows, school_ids, university_ids, year_start)
    insert_school_enrollments(conn, enrollments)

    garrison_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type in {"garrison", "guard_post"}
    ]
    military = generate_military_service(all_resident_rows, garrison_ids, year_start)
    insert_military_service(conn, military)

    year_end = year_start + timedelta(days=YEAR_LENGTH_DAYS)
    conn.execute(
        "INSERT INTO town_state (id, year_start, current_date, aggression, magic_prevalence) "
        "VALUES (1, ?, ?, ?, ?)",
        (year_start.isoformat(), year_end.isoformat(), aggression, magic_prevalence),
    )

    conn.commit()
    conn.close()
```

(`_insert_residents` is gone — every call site now uses `persistence.insert_residents`.)

- [ ] **Step 8: Run all `town_db` tests to verify nothing regressed**

Run: `python -m pytest tests/test_db_generate.py tests/test_db_persistence.py -v`
Expected: PASS — all existing `test_db_generate.py` tests (including `test_generate_town_database_is_deterministic` and `test_generate_town_database_business_rules`) plus the new ones from Step 5.

Run: `python -m pytest tests/ -v`
Expected: PASS — full suite green (this refactor touches a function every other `town_db` test transitively depends on).

- [ ] **Step 9: Commit**

```bash
git add town_db/persistence.py town_db/generate.py tests/test_db_persistence.py tests/test_db_generate.py
git commit -m "refactor: extract town_db/persistence.py; write town_state on generation"
```

---

## Task 3: Make `derive_relationships` idempotent

**Files:**
- Modify: `town_relationships/generate.py`
- Test: `tests/test_relationships_generate.py` (extend)

**Interfaces:**
- Produces: `derive_relationships(db_path, reference_date=...)` safely callable more than once (used by Task 7's orchestrator every simulated year).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_relationships_generate.py` (reuses the existing `_build_minimal_town` helper already in this file):

```python
def test_derive_relationships_is_idempotent_when_called_twice(tmp_path):
    db_path = str(tmp_path / "town.db")
    _build_minimal_town(db_path)

    derive_relationships(db_path)
    conn = connect(db_path)
    first_relationship_count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    first_shop_count = conn.execute("SELECT COUNT(*) FROM shop_relationships").fetchone()[0]

    derive_relationships(db_path)
    second_relationship_count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    second_shop_count = conn.execute("SELECT COUNT(*) FROM shop_relationships").fetchone()[0]

    assert first_relationship_count > 0
    assert second_relationship_count == first_relationship_count
    assert second_shop_count == first_shop_count
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_relationships_generate.py::test_derive_relationships_is_idempotent_when_called_twice -v`
Expected: FAIL — `second_relationship_count` is double `first_relationship_count`

- [ ] **Step 3: Add the clearing statements**

In `town_relationships/generate.py`, update the docstring and add two `DELETE` statements right after `create_relationships_schema(conn)`:

```python
def derive_relationships(db_path: str, reference_date: date = DEFAULT_YEAR_START) -> None:
    """Safe to call any number of times on the same database -- each call clears and
    re-derives relationships/shop_relationships from current town_db state."""
    conn = connect(db_path)
    create_relationships_schema(conn)
    conn.execute("DELETE FROM relationships")
    conn.execute("DELETE FROM shop_relationships")
```

(everything below is unchanged)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_relationships_generate.py -v`
Expected: PASS (all tests, including the two pre-existing ones — a no-op `DELETE` on a database where relationships were never derived before changes nothing about the first call).

- [ ] **Step 5: Commit**

```bash
git add town_relationships/generate.py tests/test_relationships_generate.py
git commit -m "fix: make derive_relationships idempotent (delete-then-reinsert)"
```

---

## Task 4: Extract `town_db/succession.py`

**Files:**
- Create: `town_db/succession.py`
- Modify: `town_db/edits.py`
- Test: `tests/test_db_succession.py`

**Interfaces:**
- Produces (for Task 6 to reuse): `primary_occupation_info(building_type, occupation) -> Tuple[bool, Optional[str]]`, `promote_apprentice(conn, workplace_id, apprentice_occupation, primary_occupation) -> Optional[int]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_db_succession.py`:

```python
from town_db.schema import connect, create_schema
from town_db.succession import primary_occupation_info, promote_apprentice


def test_primary_occupation_info_identifies_shopkeep_with_apprentice():
    is_primary, apprentice_occupation = primary_occupation_info("shop", "shopkeep")
    assert is_primary is True
    assert apprentice_occupation == "shop_staff"


def test_primary_occupation_info_false_for_non_promotable_building():
    is_primary, apprentice_occupation = primary_occupation_info("temple", "priest")
    assert is_primary is False
    assert apprentice_occupation is None


def test_primary_occupation_info_false_for_non_primary_occupation():
    is_primary, apprentice_occupation = primary_occupation_info("shop", "shop_staff")
    assert is_primary is False


def test_promote_apprentice_promotes_living_apprentice(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'merchant', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'merchant', 'shop', 0, 0, 1)"
    )
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) "
        "VALUES (1, 1, 'A', 'B', 'male', 'human', '1280-01-01', 'poor', 1, 'shop_staff')"
    )
    conn.commit()

    promoted_id = promote_apprentice(conn, workplace_id=1, apprentice_occupation="shop_staff", primary_occupation="shopkeep")
    conn.commit()

    assert promoted_id == 1
    row = conn.execute("SELECT occupation FROM residents WHERE id = 1").fetchone()
    assert row == ("shopkeep",)


def test_promote_apprentice_returns_none_when_no_apprentice_occupation():
    conn = None  # not reached -- apprentice_occupation is None short-circuits before any query
    assert promote_apprentice(conn, workplace_id=1, apprentice_occupation=None, primary_occupation="shopkeep") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_succession.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'town_db.succession'`

- [ ] **Step 3: Create `town_db/succession.py`**

```python
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
```

- [ ] **Step 4: Update `town_db/edits.py` to import from `succession.py`**

Replace this block near the top of `town_db/edits.py`:

```python
from town_db.ages import ADULT_AGE_RANGE, age_on
from town_db.purchases import SHOP_BUILDING_TYPES
from town_db.schema import connect
from town_shaper.buildings import JOB_VACANCIES_BY_BUILDING_TYPE

SHOP_LOSS_CEILING_VACANT = 0.65
SHOP_LOSS_CEILING_REPLACED = 0.30
SHOP_LOSS_RAMP_DAYS = 120

_PROMOTABLE_BUILDING_TYPES = SHOP_BUILDING_TYPES | {"arcane_shop", "blacksmith"}
```

with:

```python
from town_db.ages import ADULT_AGE_RANGE, age_on
from town_db.schema import connect
from town_db.succession import primary_occupation_info as _primary_occupation_info
from town_db.succession import promote_apprentice as _promote_apprentice

SHOP_LOSS_CEILING_VACANT = 0.65
SHOP_LOSS_CEILING_REPLACED = 0.30
SHOP_LOSS_RAMP_DAYS = 120
```

Then delete the two now-duplicate function definitions from `edits.py` entirely — remove this whole block:

```python
def _primary_occupation_info(building_type: Optional[str], occupation: Optional[str]) -> Tuple[bool, Optional[str]]:
    if building_type is None or building_type not in _PROMOTABLE_BUILDING_TYPES:
        return False, None
    roles = JOB_VACANCIES_BY_BUILDING_TYPE.get(building_type, [])
    primary_roles = [name for name, capacity in roles if capacity == 1]
    if len(primary_roles) != 1 or occupation != primary_roles[0]:
        return False, None
    apprentice_roles = [name for name, _ in roles if name != primary_roles[0]]
    return True, (apprentice_roles[0] if apprentice_roles else None)


def _promote_apprentice(conn, workplace_id, apprentice_occupation, primary_occupation) -> Optional[int]:
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
```

(Everything else in `edits.py` — `kill_resident`, `mark_resident_ill`, `scope_disease_event`, `create_disease_event`, and the other private helpers — is untouched; they call `_primary_occupation_info`/`_promote_apprentice` exactly as before, now resolving to the imported names.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_succession.py tests/test_db_edits.py -v`
Expected: PASS — the new succession tests, and every pre-existing `edits.py` test unchanged (this is the regression guard for the extraction).

- [ ] **Step 6: Commit**

```bash
git add town_db/succession.py town_db/edits.py tests/test_db_succession.py
git commit -m "refactor: extract town_db/succession.py from edits.py"
```

---

## Task 5: Household formation (`town_db/household_formation.py`)

**Files:**
- Create: `town_db/household_formation.py`
- Test: `tests/test_db_household_formation.py`

**Interfaces:**
- Consumes: `town_db.ages.ADULT_AGE_RANGE`, `age_on`; `town_db.names.draw_surname`; `town_shaper.seeding.rng_for`.
- Produces (for Task 7): `HOUSEHOLD_FORMATION_RATE = 0.15`, `generate_household_formations(conn, seed, year_start: date, year_end: date) -> None`.

Note: `buildings.capacity` in the schema is already exactly `BUILDING_HOME_CAPACITY.get(building_type, 0)` (confirmed in `town_shaper/buildings.py:149`) — vacant-housing lookups query `buildings.capacity` directly rather than importing `BUILDING_HOME_CAPACITY`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_db_household_formation.py`:

```python
from datetime import date

from town_db.household_formation import generate_household_formations
from town_db.schema import connect, create_schema


def _insert_home_building(conn, building_id, capacity, district_id=1):
    conn.execute(
        f"INSERT OR IGNORE INTO districts (id, zone_type, polygon) VALUES ({district_id}, 'rich_residential', '[]')"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (?, ?, 'rich_residential', 'residence', 0, 0, ?)",
        (building_id, district_id, capacity),
    )


def _insert_household_with_adults(conn, household_id, resident_ids, home_building_id=None, birth_date="1275-01-01"):
    conn.execute(
        "INSERT INTO households (id, family_name, race) VALUES (?, 'Smith', 'human')", (household_id,)
    )
    for resident_id in resident_ids:
        conn.execute(
            "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
            "home_building_id) VALUES (?, ?, 'A', 'B', 'male', 'human', ?, 'poor', ?)",
            (resident_id, household_id, birth_date, home_building_id),
        )


def test_third_adult_in_household_is_eligible_and_moves_out_when_matched(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    # household 1: three adults -- residents 1,2 are the "couple", resident 3 is eligible
    _insert_household_with_adults(conn, 1, [1, 2, 3])
    # household 2: a lone eligible adult from a different household, for resident 3 to pair with
    _insert_household_with_adults(conn, 2, [4])
    _insert_home_building(conn, building_id=10, capacity=2)
    conn.commit()

    generate_household_formations(conn, seed=("town", 1), year_start=date(1301, 1, 1), year_end=date(1302, 1, 1))
    conn.commit()

    new_household_ids = {
        row[0] for row in conn.execute("SELECT DISTINCT household_id FROM residents WHERE id IN (3, 4)").fetchall()
    }
    # Either both stayed put (rate didn't fire this seed) or both moved to the same new household --
    # never split, never still 1-and-2 respectively.
    assert len(new_household_ids) == 1


def test_first_two_adults_in_household_are_never_eligible(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    _insert_household_with_adults(conn, 1, [1, 2])
    _insert_home_building(conn, building_id=10, capacity=2)
    conn.commit()

    generate_household_formations(conn, seed=("town", 1), year_start=date(1301, 1, 1), year_end=date(1302, 1, 1))
    conn.commit()

    household_ids = {row[0] for row in conn.execute("SELECT household_id FROM residents WHERE id IN (1, 2)").fetchall()}
    assert household_ids == {1}  # unchanged -- the founding couple is never eligible


def test_no_formation_when_no_vacant_housing(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    _insert_household_with_adults(conn, 1, [1, 2, 3])
    _insert_household_with_adults(conn, 2, [4])
    # A home building that exists but is already full.
    _insert_home_building(conn, building_id=10, capacity=1)
    conn.execute("UPDATE residents SET home_building_id = 10 WHERE id = 1")
    conn.commit()

    generate_household_formations(conn, seed=("town", 1), year_start=date(1301, 1, 1), year_end=date(1302, 1, 1))
    conn.commit()

    household_ids = {row[0] for row in conn.execute("SELECT household_id FROM residents WHERE id IN (3, 4)").fetchall()}
    assert household_ids == {1, 2}  # neither moved -- soft cap in effect


def test_formation_does_not_touch_occupation_or_workplace(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    _insert_household_with_adults(conn, 1, [1, 2, 3])
    _insert_household_with_adults(conn, 2, [4])
    _insert_home_building(conn, building_id=10, capacity=2)
    conn.execute("UPDATE residents SET occupation = 'farmer', workplace_building_id = 99 WHERE id = 3")
    conn.commit()

    generate_household_formations(conn, seed=("town", 1), year_start=date(1301, 1, 1), year_end=date(1302, 1, 1))
    conn.commit()

    row = conn.execute("SELECT occupation, workplace_building_id FROM residents WHERE id = 3").fetchone()
    assert row == ("farmer", 99)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_household_formation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'town_db.household_formation'`

- [ ] **Step 3: Write the implementation**

```python
# town_db/household_formation.py
from datetime import date
from typing import Dict, List, Optional, Tuple

from town_shaper.seeding import rng_for

from town_db.ages import ADULT_AGE_RANGE, age_on
from town_db.names import draw_surname

HOUSEHOLD_FORMATION_RATE = 0.15


def _eligible_movers(conn, year_start: date) -> List[Tuple[int, int, str]]:
    """(resident_id, household_id, race) for living adults who are NOT one of their household's
    first-two-adults (by id) -- i.e. not already structurally 'married' per
    town_relationships/family.py's own positional definition of spouse."""
    rows = conn.execute(
        "SELECT id, household_id, race, birth_date FROM residents WHERE death_date IS NULL "
        "ORDER BY household_id, id"
    ).fetchall()

    adults_by_household: Dict[int, List[Tuple[int, str]]] = {}
    for resident_id, household_id, race, birth_date_str in rows:
        if age_on(date.fromisoformat(birth_date_str), year_start) < ADULT_AGE_RANGE[0]:
            continue
        adults_by_household.setdefault(household_id, []).append((resident_id, race))

    eligible: List[Tuple[int, int, str]] = []
    for household_id, adults in adults_by_household.items():
        for resident_id, race in adults[2:]:
            eligible.append((resident_id, household_id, race))
    return eligible


def _vacant_home_building(conn) -> Optional[int]:
    row = conn.execute(
        "SELECT b.id FROM buildings b LEFT JOIN residents r "
        "ON r.home_building_id = b.id AND r.death_date IS NULL "
        "WHERE b.capacity > 0 GROUP BY b.id HAVING COUNT(r.id) < b.capacity ORDER BY b.id LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def generate_household_formations(conn, seed, year_start: date, year_end: date) -> None:
    rng = rng_for(seed, "db", "household_formation")
    eligible = _eligible_movers(conn, year_start)
    paired_this_year: set = set()

    for resident_id, household_id, race in eligible:
        if resident_id in paired_this_year:
            continue
        if rng.random() >= HOUSEHOLD_FORMATION_RATE:
            continue

        spouse_candidates = [
            other_id for other_id, other_household_id, _ in eligible
            if other_id != resident_id
            and other_household_id != household_id
            and other_id not in paired_this_year
        ]
        if not spouse_candidates:
            continue
        spouse_id = rng.choice(spouse_candidates)

        destination_building_id = _vacant_home_building(conn)
        if destination_building_id is None:
            continue

        surname = draw_surname(rng, race)
        cursor = conn.execute("INSERT INTO households (family_name, race) VALUES (?, ?)", (surname, race))
        new_household_id = cursor.lastrowid

        conn.execute(
            "UPDATE residents SET household_id = ?, home_building_id = ? WHERE id IN (?, ?)",
            (new_household_id, destination_building_id, resident_id, spouse_id),
        )
        paired_this_year.add(resident_id)
        paired_this_year.add(spouse_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_household_formation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_db/household_formation.py tests/test_db_household_formation.py
git commit -m "feat: add household formation pass for year-advance simulation"
```

---

## Task 6: Job market (`town_db/job_market.py`)

**Files:**
- Create: `town_db/job_market.py`
- Test: `tests/test_db_job_market.py`

**Interfaces:**
- Consumes: `town_db.succession.primary_occupation_info`, `promote_apprentice` (Task 4); `town_db.ages.ADULT_AGE_RANGE`, `age_on`; `town_shaper.seeding.rng_for`.
- Produces (for Task 7): `fill_job_vacancies(conn, seed, year_start: date, year_end: date) -> None`.

(Deviates slightly from the spec's sketched `fill_job_vacancies(conn, seed, year_start)` signature by also taking `year_end` explicitly, matching `generate_household_formations`'s shape — avoids this module needing its own copy of `YEAR_LENGTH_DAYS`.)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_db_job_market.py`:

```python
from datetime import date

from town_db.job_market import fill_job_vacancies
from town_db.schema import connect, create_schema


def _insert_shop_with_owner_and_apprentice(conn, owner_id, apprentice_id, household_id=1, building_id=1):
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'merchant', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (?, 1, 'merchant', 'shop', 0, 0, 0)", (building_id,),
    )
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (?, 'Smith', 'human')", (household_id,))
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) "
        "VALUES (?, ?, 'A', 'B', 'male', 'human', '1260-01-01', 'poor', ?, 'shopkeep')",
        (owner_id, household_id, building_id),
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) "
        "VALUES (?, ?, 'C', 'D', 'male', 'human', '1280-01-01', 'poor', ?, 'shop_staff')",
        (apprentice_id, household_id, building_id),
    )


def test_apprentice_is_promoted_when_owner_dies_this_year(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    _insert_shop_with_owner_and_apprentice(conn, owner_id=1, apprentice_id=2)
    conn.execute(
        "INSERT INTO deaths (resident_id, death_date, cause) VALUES (1, '1301-03-01', 'illness')"
    )
    conn.execute("UPDATE residents SET death_date = '1301-03-01' WHERE id = 1")
    conn.commit()

    fill_job_vacancies(conn, seed=("town", 1), year_start=date(1301, 1, 1), year_end=date(1302, 1, 1))
    conn.commit()

    row = conn.execute("SELECT occupation FROM residents WHERE id = 2").fetchone()
    assert row == ("shopkeep",)


def test_labor_market_fallback_fills_non_promotable_vacancy(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'temple', 0, 0, 0)"
    )
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    # the deceased acolyte
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) "
        "VALUES (1, 1, 'A', 'B', 'male', 'human', '1260-01-01', 'poor', 1, 'acolyte')"
    )
    conn.execute("INSERT INTO deaths (resident_id, death_date, cause) VALUES (1, '1301-03-01', 'illness')")
    conn.execute("UPDATE residents SET death_date = '1301-03-01' WHERE id = 1")
    # an unemployed adult, the only eligible candidate
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses) "
        "VALUES (2, 1, 'C', 'D', 'male', 'human', '1275-01-01', 'poor')"
    )
    conn.commit()

    fill_job_vacancies(conn, seed=("town", 1), year_start=date(1301, 1, 1), year_end=date(1302, 1, 1))
    conn.commit()

    row = conn.execute("SELECT occupation, workplace_building_id FROM residents WHERE id = 2").fetchone()
    assert row == ("acolyte", 1)


def test_vacancy_unfilled_when_no_apprentice_and_no_candidates(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    _insert_shop_with_owner_and_apprentice(conn, owner_id=1, apprentice_id=2)
    # the apprentice also dies, along with the owner -- no one left to promote or hire
    conn.execute("INSERT INTO deaths (resident_id, death_date, cause) VALUES (1, '1301-03-01', 'illness')")
    conn.execute("INSERT INTO deaths (resident_id, death_date, cause) VALUES (2, '1301-03-01', 'illness')")
    conn.execute("UPDATE residents SET death_date = '1301-03-01' WHERE id IN (1, 2)")
    conn.commit()

    fill_job_vacancies(conn, seed=("town", 1), year_start=date(1301, 1, 1), year_end=date(1302, 1, 1))
    conn.commit()  # must not raise

    assert conn.execute("SELECT COUNT(*) FROM residents WHERE occupation = 'shopkeep' AND death_date IS NULL").fetchone()[0] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_job_market.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'town_db.job_market'`

- [ ] **Step 3: Write the implementation**

```python
# town_db/job_market.py
from datetime import date
from typing import List, Optional, Tuple

from town_shaper.seeding import rng_for

from town_db.ages import ADULT_AGE_RANGE, age_on
from town_db.succession import primary_occupation_info, promote_apprentice

SES_MATCH_WEIGHT = 3.0


def _vacancies(conn, year_start: date, year_end: date) -> List[Tuple[int, int, str, Optional[str]]]:
    return conn.execute(
        "SELECT r.id, r.workplace_building_id, r.occupation, b.building_type FROM deaths d "
        "JOIN residents r ON r.id = d.resident_id "
        "LEFT JOIN buildings b ON b.id = r.workplace_building_id "
        "WHERE d.death_date >= ? AND d.death_date < ? "
        "AND r.workplace_building_id IS NOT NULL AND r.occupation IS NOT NULL",
        (year_start.isoformat(), year_end.isoformat()),
    ).fetchall()


def _modal_ses_for_occupation(conn, occupation: str) -> Optional[str]:
    rows = conn.execute(
        "SELECT ses, COUNT(*) c FROM residents WHERE occupation = ? AND death_date IS NULL "
        "GROUP BY ses ORDER BY c DESC, ses ASC",
        (occupation,),
    ).fetchall()
    return rows[0][0] if rows else None


def _select_candidate(conn, rng, occupation: str, year_start: date) -> Optional[int]:
    rows = conn.execute(
        "SELECT id, ses, birth_date FROM residents WHERE death_date IS NULL AND occupation IS NULL ORDER BY id"
    ).fetchall()
    candidates = [
        (resident_id, ses) for resident_id, ses, birth_date_str in rows
        if age_on(date.fromisoformat(birth_date_str), year_start) >= ADULT_AGE_RANGE[0]
    ]
    if not candidates:
        return None

    modal_ses = _modal_ses_for_occupation(conn, occupation)
    if modal_ses is None:
        return rng.choice(candidates)[0]

    weights = [SES_MATCH_WEIGHT if ses == modal_ses else 1.0 for _, ses in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0][0]


def fill_job_vacancies(conn, seed, year_start: date, year_end: date) -> None:
    rng = rng_for(seed, "db", "job_market")

    for _deceased_id, workplace_id, occupation, building_type in _vacancies(conn, year_start, year_end):
        is_primary, apprentice_occupation = primary_occupation_info(building_type, occupation)
        promoted_id = promote_apprentice(conn, workplace_id, apprentice_occupation, occupation) if is_primary else None
        if promoted_id is not None:
            continue

        candidate_id = _select_candidate(conn, rng, occupation, year_start)
        if candidate_id is None:
            continue
        conn.execute(
            "UPDATE residents SET occupation = ?, workplace_building_id = ? WHERE id = ?",
            (occupation, workplace_id, candidate_id),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_job_market.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_db/job_market.py tests/test_db_job_market.py
git commit -m "feat: add job-market vacancy fill pass for year-advance simulation"
```

---

## Task 7: Orchestrator (`town_db/simulation.py`)

**Files:**
- Create: `town_db/simulation.py`
- Test: `tests/test_db_simulation.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6 — `town_state` (Task 1); all `insert_*` helpers and `YEAR_LENGTH_DAYS` from `town_db.persistence`/`town_db.generate` (Task 2); `derive_relationships` (Task 3, now idempotent); `generate_household_formations` (Task 5); `fill_job_vacancies` (Task 6); plus the untouched existing generators (`generate_disease_events`, `generate_births_and_deaths`, `generate_skirmish_events`, `generate_skirmish_casualties`, `generate_purchases`, `SHOP_BUILDING_TYPES`, `generate_tax_payments`, `generate_school_enrollments`, `generate_military_service`).
- Produces: `advance_town(db_path: str, seed, years: int = 1) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_db_simulation.py`:

```python
import sqlite3

import pytest

from town_db.generate import generate_town_database
from town_db.simulation import advance_town


def test_advance_town_updates_town_state(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=300, db_path=db_path)

    advance_town(db_path, seed=("town", 1), years=1)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT year_start, current_date FROM town_state WHERE id = 1").fetchone()
    assert row == ("1300-01-01", "1302-01-01")


def test_advance_town_two_years_advances_current_date_twice(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=300, db_path=db_path)

    advance_town(db_path, seed=("town", 1), years=2)

    conn = sqlite3.connect(db_path)
    current_date = conn.execute("SELECT current_date FROM town_state WHERE id = 1").fetchone()[0]
    assert current_date == "1303-01-01"


def test_advance_town_raises_on_non_positive_years(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=300, db_path=db_path)

    with pytest.raises(ValueError):
        advance_town(db_path, seed=("town", 1), years=0)


def test_advance_town_raises_when_town_state_row_missing(tmp_path):
    from town_db.schema import connect, create_schema
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.commit()

    with pytest.raises(ValueError):
        advance_town(db_path, seed=("town", 1), years=1)


def test_advance_town_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=300, db_path=db_path)

    advance_town(db_path, seed=("town", 1), years=1)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_advance_town_produces_new_purchases_and_relationships(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=300, db_path=db_path)
    conn = sqlite3.connect(db_path)
    purchases_before = conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0]

    advance_town(db_path, seed=("town", 1), years=1)

    conn = sqlite3.connect(db_path)
    purchases_after = conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0]
    relationship_count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    assert purchases_after > purchases_before
    assert relationship_count > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_simulation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'town_db.simulation'`

- [ ] **Step 3: Write the implementation**

```python
# town_db/simulation.py
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from town_shaper.seeding import rng_for

from town_db.ages import ADULT_AGE_RANGE, age_on
from town_db.generate import YEAR_LENGTH_DAYS
from town_db.household_formation import generate_household_formations
from town_db.job_market import fill_job_vacancies
from town_db.enrollment import generate_school_enrollments
from town_db.military import generate_military_service
from town_db.persistence import (
    insert_births,
    insert_deaths,
    insert_disease_events,
    insert_military_service,
    insert_purchases,
    insert_residents,
    insert_school_enrollments,
    insert_skirmish_events,
    insert_tax_payments,
)
from town_db.purchases import SHOP_BUILDING_TYPES, generate_purchases
from town_db.schema import connect
from town_db.taxes import generate_tax_payments
from town_db.unrest import generate_skirmish_casualties, generate_skirmish_events
from town_db.vital_records import generate_births_and_deaths, generate_disease_events

from town_relationships.generate import derive_relationships


def _age_bracket(age: int) -> str:
    return "child" if age < ADULT_AGE_RANGE[0] else "adult"


def _load_household_rows(conn) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT id, family_name, race FROM households").fetchall()
    return [{"id": r[0], "family_name": r[1], "race": r[2]} for r in rows]


def _load_resident_rows(conn, year_start: date) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT r.id, r.household_id, r.gender, r.race, r.birth_date, r.death_date, r.ses, r.is_noble, "
        "r.home_building_id, r.workplace_building_id, r.occupation, b.zone_type "
        "FROM residents r LEFT JOIN buildings b ON b.id = r.home_building_id"
    ).fetchall()
    result: List[Dict[str, Any]] = []
    for (resident_id, household_id, gender, race, birth_date, death_date, ses, is_noble,
         home_building_id, workplace_building_id, occupation, home_zone_type) in rows:
        age = age_on(date.fromisoformat(birth_date), year_start)
        result.append({
            "db_id": resident_id,
            "household_id": household_id,
            "gender": gender,
            "race": race,
            "birth_date": birth_date,
            "death_date": death_date,
            "ses": ses,
            "is_noble": bool(is_noble),
            "home_building_id": home_building_id,
            "home_zone_type": home_zone_type,
            "workplace_building_id": workplace_building_id,
            "occupation": occupation,
            "age_bracket": _age_bracket(age),
        })
    return result


def _building_ids(conn, building_type: str) -> List[int]:
    return [r[0] for r in conn.execute("SELECT id FROM buildings WHERE building_type = ?", (building_type,)).fetchall()]


def _first_building_id(conn, building_type: str) -> Optional[int]:
    row = conn.execute("SELECT id FROM buildings WHERE building_type = ? ORDER BY id LIMIT 1", (building_type,)).fetchone()
    return row[0] if row else None


def _goods_ids(conn) -> Dict[str, int]:
    return {name: good_id for good_id, name in conn.execute("SELECT id, name FROM goods").fetchall()}


def advance_town(db_path: str, seed, years: int = 1) -> None:
    if years <= 0:
        raise ValueError("years must be a positive integer")

    conn = connect(db_path)
    try:
        state_row = conn.execute(
            "SELECT year_start, current_date, aggression, magic_prevalence FROM town_state WHERE id = 1"
        ).fetchone()
        if state_row is None:
            raise ValueError(f"{db_path} has no town_state row -- was it generated with capability-2 slice 1 or later?")
        original_year_start = date.fromisoformat(state_row[0])
        current_date = date.fromisoformat(state_row[1])
        aggression = state_row[2]
        magic_prevalence = state_row[3]

        for _ in range(years):
            year_start = current_date
            year_end = year_start + timedelta(days=YEAR_LENGTH_DAYS)
            year_index = (year_start - original_year_start).days // YEAR_LENGTH_DAYS
            year_seed = rng_for(seed, "town_state", "year", year_index)

            household_rows = _load_household_rows(conn)
            resident_rows = _load_resident_rows(conn, year_start)

            disease_rows = generate_disease_events(year_seed, year_start)
            insert_disease_events(conn, disease_rows)

            temple_id = _first_building_id(conn, "temple")
            healer_id = _first_building_id(conn, "healer")
            births, deaths, new_resident_rows = generate_births_and_deaths(
                year_seed, household_rows, resident_rows, disease_rows, year_start, temple_id, healer_id,
            )
            insert_residents(conn, new_resident_rows)
            insert_births(conn, births, new_resident_rows)
            insert_deaths(conn, deaths)

            guard_post_id = _first_building_id(conn, "guard_post")
            garrison_id = _first_building_id(conn, "garrison")
            reporting_building_id = guard_post_id if guard_post_id is not None else garrison_id
            skirmish_rows = generate_skirmish_events(year_seed, year_start, aggression)
            insert_skirmish_events(conn, skirmish_rows)
            skirmish_deaths = generate_skirmish_casualties(year_seed, resident_rows, skirmish_rows, reporting_building_id)
            insert_deaths(conn, skirmish_deaths)

            generate_household_formations(conn, year_seed, year_start, year_end)
            fill_job_vacancies(conn, year_seed, year_start, year_end)

            all_household_rows = _load_household_rows(conn)
            all_resident_rows = _load_resident_rows(conn, year_start)

            goods_ids = _goods_ids(conn)
            shop_building_ids = [b_id for bt in SHOP_BUILDING_TYPES for b_id in _building_ids(conn, bt)]
            arcane_shop_building_ids = _building_ids(conn, "arcane_shop")
            blacksmith_building_ids = _building_ids(conn, "blacksmith")
            purchases = generate_purchases(
                year_seed, all_household_rows, all_resident_rows, goods_ids, shop_building_ids, year_start,
                magic_prevalence=magic_prevalence, arcane_shop_building_ids=arcane_shop_building_ids,
                blacksmith_building_ids=blacksmith_building_ids,
            )
            insert_purchases(conn, purchases)

            tax_payments = generate_tax_payments(year_seed, all_household_rows, all_resident_rows, year_start)
            insert_tax_payments(conn, tax_payments)

            school_ids = _building_ids(conn, "school")
            university_ids = _building_ids(conn, "university")
            enrollments = generate_school_enrollments(year_seed, all_resident_rows, school_ids, university_ids, year_start)
            insert_school_enrollments(conn, enrollments)

            garrison_ids = _building_ids(conn, "garrison") + _building_ids(conn, "guard_post")
            military = generate_military_service(all_resident_rows, garrison_ids, year_start)
            insert_military_service(conn, military)

            conn.execute("UPDATE town_state SET current_date = ? WHERE id = 1", (year_end.isoformat(),))
            conn.commit()

            derive_relationships(db_path, reference_date=year_end)
            current_date = year_end
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_simulation.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: PASS — everything green.

- [ ] **Step 6: Commit**

```bash
git add town_db/simulation.py tests/test_db_simulation.py
git commit -m "feat: add advance_town year-advance orchestrator"
```

---

## Task 8: Integration tests — seed sweep, determinism, data integrity

**Files:**
- Test: `tests/test_db_simulation_integration.py`

**Interfaces:**
- Consumes: `advance_town` (Task 7), `generate_town_database` (Task 2).

Per this project's established practice, probabilistic multi-mechanic logic needs a seed sweep, not a single seed — this task is that sweep.

- [ ] **Step 1: Write the tests**

Create `tests/test_db_simulation_integration.py`:

```python
import sqlite3

from town_db.generate import generate_town_database
from town_db.simulation import advance_town

SEEDS = [("town", n) for n in range(1, 11)]


def test_five_year_advance_preserves_data_integrity_across_seeds(tmp_path):
    for seed in SEEDS:
        db_path = str(tmp_path / f"town_{seed[1]}.db")
        generate_town_database(seed, target_population=400, db_path=db_path)

        advance_town(db_path, seed=seed, years=5)

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == [], f"seed {seed}"

        # No purchase dated after its buyer's own death.
        late_purchases = conn.execute(
            "SELECT COUNT(*) FROM purchases p JOIN residents r ON r.id = p.resident_id "
            "WHERE r.death_date IS NOT NULL AND p.purchase_date > r.death_date"
        ).fetchone()[0]
        assert late_purchases == 0, f"seed {seed}"

        # No tax payment dated after its payer's own death.
        late_taxes = conn.execute(
            "SELECT COUNT(*) FROM tax_payments t JOIN residents r ON r.id = t.resident_id "
            "WHERE r.death_date IS NOT NULL AND t.payment_date > r.death_date"
        ).fetchone()[0]
        assert late_taxes == 0, f"seed {seed}"

        # No duplicate relationship rows after repeated re-derivation.
        dup_relationships = conn.execute(
            "SELECT resident_a_id, resident_b_id, relationship_type, COUNT(*) c FROM relationships "
            "GROUP BY resident_a_id, resident_b_id, relationship_type HAVING c > 1"
        ).fetchall()
        assert dup_relationships == [], f"seed {seed}"

        # No resident has more than one deaths row.
        dup_deaths = conn.execute(
            "SELECT resident_id, COUNT(*) c FROM deaths GROUP BY resident_id HAVING c > 1"
        ).fetchall()
        assert dup_deaths == [], f"seed {seed}"


def test_advance_town_is_deterministic(tmp_path):
    db_path_1 = str(tmp_path / "town1.db")
    db_path_2 = str(tmp_path / "town2.db")
    generate_town_database(("town", 7), target_population=400, db_path=db_path_1)
    generate_town_database(("town", 7), target_population=400, db_path=db_path_2)

    advance_town(db_path_1, seed=("town", 7), years=3)
    advance_town(db_path_2, seed=("town", 7), years=3)

    conn1 = sqlite3.connect(db_path_1)
    conn2 = sqlite3.connect(db_path_2)
    for table in ["residents", "households", "purchases", "tax_payments", "births", "deaths",
                  "skirmish_events", "relationships", "shop_relationships"]:
        rows1 = conn1.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        rows2 = conn2.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        assert rows1 == rows2, table


def test_household_formation_produces_spouse_not_household_member_relationship(tmp_path):
    # Runs a higher-population, higher-year-count town to make formation events likely, then
    # checks that any newly-formed household (more than 2 members starting at a household id
    # beyond the original generation range) is reflected as 'spouse' by the re-derived
    # relationships, not 'household_member'.
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 3), target_population=800, db_path=db_path)
    conn = sqlite3.connect(db_path)
    max_original_household_id = conn.execute("SELECT MAX(id) FROM households").fetchone()[0]

    advance_town(db_path, seed=("town", 3), years=5)

    conn = sqlite3.connect(db_path)
    new_households = conn.execute(
        "SELECT id FROM households WHERE id > ?", (max_original_household_id,)
    ).fetchall()
    assert new_households, "expected at least one new household to have formed over 5 years at this population"

    for (household_id,) in new_households:
        member_ids = [
            r[0] for r in conn.execute(
                "SELECT id FROM residents WHERE household_id = ? AND death_date IS NULL", (household_id,)
            ).fetchall()
        ]
        assert len(member_ids) == 2, household_id
        a, b = sorted(member_ids)
        rel_type = conn.execute(
            "SELECT relationship_type FROM relationships WHERE resident_a_id = ? AND resident_b_id = ?", (a, b)
        ).fetchone()
        assert rel_type == ("spouse",), household_id
```

- [ ] **Step 2: Run to verify they pass**

Run: `python -m pytest tests/test_db_simulation_integration.py -v`
Expected: PASS. If `test_household_formation_produces_spouse_not_household_member_relationship` fails because zero households formed at this population/seed/year-count, raise `target_population` and/or `years` until at least one formation reliably occurs, rather than weakening the assertion.

- [ ] **Step 3: Run the entire test suite one final time**

Run: `python -m pytest tests/ -v`
Expected: PASS — full green suite, capability 2 slice 1 complete.

- [ ] **Step 4: Commit**

```bash
git add tests/test_db_simulation_integration.py
git commit -m "test: add seed-swept integration tests for town year-advance"
```
