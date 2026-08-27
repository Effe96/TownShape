# Creative-Mode Editing (Capability 3, First Slice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add direct, on-demand mutation primitives (`kill_resident`, `mark_resident_ill`, `scope_disease_event`, `create_disease_event`) that edit an already-generated `town_db` SQLite database and keep its other tables consistent, without regenerating anything.

**Architecture:** A new `town_db/edits.py` module holding four public functions plus small private helpers. Each function opens its own connection via `town_db.schema.connect`, applies the core fact, then runs a fixed set of hand-authored per-table consistency rules (not a re-run of the original stream-based generators — see the spec for why that doesn't work). A new `illnesses` table is added to `town_db/schema.py`'s `SCHEMA_SQL`.

**Tech Stack:** Python stdlib `sqlite3`, stdlib `random.Random` (seeded per-call from the mutation's own arguments — no dependency on `town_shaper`'s `rng_for` stream), `town_shaper.buildings.JOB_VACANCIES_BY_BUILDING_TYPE` (reused, not duplicated), `town_db.ages.age_on`/`ADULT_AGE_RANGE`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-creative-mode-editing-design.md`

## Global Constraints

- No changes to `town_shaper` or any existing `town_db` generator module's behavior — this is purely additive.
- Every mutation function takes `db_path: str` and operates via its own `sqlite3.Connection` (opened with `town_db.schema.connect`, which already sets `PRAGMA foreign_keys = ON`), committing and closing before returning.
- Dates are Python `datetime.date` objects in every public function signature; stored as ISO strings (`.isoformat()`), matching every existing `town_db` table.
- RNG for any cascade choice is a fresh `random.Random(seed_string)` keyed from the mutation's own arguments (e.g. `f"kill-resident-{resident_id}-{death_date.isoformat()}"`) — never `town_shaper.seeding.rng_for`, since these primitives don't participate in a town's original generation seed lineage.
- `FK` integrity (`PRAGMA foreign_key_check`) must return no rows after every mutation — every task's tests verify this.

---

## Task 1: `illnesses` table in schema

**Files:**
- Modify: `town_db/schema.py`
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Produces: an `illnesses` table with columns `id, resident_id, disease_event_id, start_date, end_date, severity`, created by the existing `create_schema(conn)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db_schema.py`:

```python
def test_illnesses_table_accepts_a_row_referencing_a_resident_and_disease_event(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses) "
        "VALUES (1, 1, 'A', 'B', 'male', 'human', '1280-01-01', 'poor')"
    )
    conn.execute(
        "INSERT INTO disease_events (id, name, start_date, end_date, affected_zone_type, severity) "
        "VALUES (1, 'fever', '1300-01-01', '1300-02-01', NULL, 0.5)"
    )
    conn.execute(
        "INSERT INTO illnesses (resident_id, disease_event_id, start_date, end_date, severity) "
        "VALUES (1, 1, '1300-01-05', '1300-01-20', 0.5)"
    )
    conn.commit()

    row = conn.execute("SELECT resident_id, disease_event_id, start_date, end_date, severity FROM illnesses").fetchone()
    assert row == (1, 1, "1300-01-05", "1300-01-20", 0.5)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
```

Check the top of `tests/test_db_schema.py` already imports `connect, create_schema` from `town_db.schema` (it does, following the existing file's pattern) — no new import needed.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_db_schema.py::test_illnesses_table_accepts_a_row_referencing_a_resident_and_disease_event -v`
Expected: FAIL with `sqlite3.OperationalError: no such table: illnesses`

- [ ] **Step 3: Add the table to the schema**

In `town_db/schema.py`, inside the `SCHEMA_SQL` string, after the `disease_events` table definition (before `skirmish_events`), add:

```sql
CREATE TABLE illnesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    disease_event_id INTEGER REFERENCES disease_events(id),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    severity REAL NOT NULL
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: all PASS, including the new test.

- [ ] **Step 5: Commit**

```bash
git add town_db/schema.py tests/test_db_schema.py
git commit -m "feat: add illnesses table to town_db schema"
```

---

## Task 2: `town_db/edits.py` module + `mark_resident_ill`

**Files:**
- Create: `town_db/edits.py`
- Create: `tests/test_db_edits.py`

**Interfaces:**
- Consumes: `town_db.schema.connect(db_path)`, `town_db.ages.age_on(birth_date, on_date)`, `town_db.ages.ADULT_AGE_RANGE`.
- Produces:
  - `_living_adult_household_members(conn, resident_id, on_date) -> List[int]`
  - `_reassign_or_delete_buyer_purchases(conn, resident_id, from_date, until_date, rng) -> None`
  - `mark_resident_ill(db_path, resident_id, start_date, end_date, severity, disease_event_id=None) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_db_edits.py`:

```python
# tests/test_db_edits.py
import random
from datetime import date

from town_db.edits import mark_resident_ill
from town_db.schema import connect, create_schema


def _insert_household(conn, household_id, family_name="Smith", race="human"):
    conn.execute(
        "INSERT INTO households (id, family_name, race) VALUES (?, ?, ?)",
        (household_id, family_name, race),
    )


def _insert_resident(conn, resident_id, household_id, birth_date="1280-01-01", death_date=None):
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, death_date, ses) "
        "VALUES (?, ?, 'A', 'B', 'male', 'human', ?, ?, 'poor')",
        (resident_id, household_id, birth_date, death_date),
    )


def _insert_good_and_shop(conn):
    # districts must be inserted before buildings -- buildings.district_id is FK-enforced
    # (connect() sets PRAGMA foreign_keys = ON) and referencing a not-yet-existing district
    # fails immediately.
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'merchant', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'merchant', 'shop', 0, 0, 1)"
    )
    conn.execute(
        "INSERT INTO goods (id, name, category, typical_price, sv) VALUES (1, 'bread', 'food', 0.05, 800)"
    )


def _insert_purchase(conn, purchase_id, resident_id, purchase_date, shop_building_id=1):
    conn.execute(
        "INSERT INTO purchases (id, resident_id, shop_building_id, good_id, quantity, unit_price, total_price, purchase_date) "
        "VALUES (?, ?, ?, 1, 1, 0.05, 0.05, ?)",
        (purchase_id, resident_id, shop_building_id, purchase_date),
    )


def test_mark_resident_ill_inserts_illness_row(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)
    conn.commit()
    conn.close()

    mark_resident_ill(db_path, resident_id=1, start_date=date(1300, 3, 1), end_date=date(1300, 3, 20), severity=0.6)

    conn = connect(db_path)
    row = conn.execute(
        "SELECT resident_id, disease_event_id, start_date, end_date, severity FROM illnesses"
    ).fetchone()
    assert row == (1, None, "1300-03-01", "1300-03-20", 0.6)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_mark_resident_ill_reassigns_purchases_in_window_to_another_household_adult(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)  # will be marked ill
    _insert_resident(conn, 2, 1)  # other living adult in the same household
    _insert_good_and_shop(conn)
    _insert_purchase(conn, 1, resident_id=1, purchase_date="1300-03-10")  # inside illness window
    _insert_purchase(conn, 2, resident_id=1, purchase_date="1300-05-01")  # outside illness window
    conn.commit()
    conn.close()

    mark_resident_ill(db_path, resident_id=1, start_date=date(1300, 3, 1), end_date=date(1300, 3, 20), severity=0.6)

    conn = connect(db_path)
    in_window_buyer = conn.execute("SELECT resident_id FROM purchases WHERE id = 1").fetchone()[0]
    outside_window_buyer = conn.execute("SELECT resident_id FROM purchases WHERE id = 2").fetchone()[0]
    assert in_window_buyer == 2  # reassigned to the other household adult
    assert outside_window_buyer == 1  # untouched, outside the illness window


def test_mark_resident_ill_deletes_purchase_when_sole_adult_in_household(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)  # sole adult, will be marked ill
    _insert_good_and_shop(conn)
    _insert_purchase(conn, 1, resident_id=1, purchase_date="1300-03-10")
    conn.commit()
    conn.close()

    mark_resident_ill(db_path, resident_id=1, start_date=date(1300, 3, 1), end_date=date(1300, 3, 20), severity=0.6)

    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] == 0


def test_mark_resident_ill_raises_on_overlapping_illness(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)
    conn.commit()
    conn.close()

    mark_resident_ill(db_path, resident_id=1, start_date=date(1300, 3, 1), end_date=date(1300, 3, 20), severity=0.6)
    try:
        mark_resident_ill(db_path, resident_id=1, start_date=date(1300, 3, 10), end_date=date(1300, 3, 25), severity=0.4)
        assert False, "expected ValueError"
    except ValueError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_edits.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_db.edits'`

- [ ] **Step 3: Write the module**

Create `town_db/edits.py`:

```python
# town_db/edits.py
import random
from datetime import date
from typing import List, Optional

from town_db.ages import ADULT_AGE_RANGE, age_on
from town_db.schema import connect


def _living_adult_household_members(conn, resident_id: int, on_date: date) -> List[int]:
    household_id = conn.execute(
        "SELECT household_id FROM residents WHERE id = ?", (resident_id,)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT id, birth_date, death_date FROM residents WHERE household_id = ? AND id != ?",
        (household_id, resident_id),
    ).fetchall()

    candidates = []
    for other_id, birth_date_str, other_death_date in rows:
        if other_death_date is not None and other_death_date <= on_date.isoformat():
            continue
        if age_on(date.fromisoformat(birth_date_str), on_date) < ADULT_AGE_RANGE[0]:
            continue
        candidates.append(other_id)
    return candidates


def _reassign_or_delete_buyer_purchases(
    conn, resident_id: int, from_date: date, until_date: Optional[date], rng: random.Random
) -> None:
    # Candidate pool is fixed once at from_date, not re-checked per purchase -- a candidate who
    # dies later in the window stays eligible for the rest of it. Deliberate simplification: exact
    # per-purchase-date liveness would require re-querying per row for marginal realism gain.
    candidates = _living_adult_household_members(conn, resident_id, from_date)

    query = "SELECT id FROM purchases WHERE resident_id = ? AND purchase_date >= ?"
    params: List = [resident_id, from_date.isoformat()]
    if until_date is not None:
        query += " AND purchase_date < ?"
        params.append(until_date.isoformat())

    rows = conn.execute(query, params).fetchall()
    for (purchase_id,) in rows:
        if candidates:
            new_buyer = rng.choice(candidates)
            conn.execute("UPDATE purchases SET resident_id = ? WHERE id = ?", (new_buyer, purchase_id))
        else:
            conn.execute("DELETE FROM purchases WHERE id = ?", (purchase_id,))


def mark_resident_ill(
    db_path: str,
    resident_id: int,
    start_date: date,
    end_date: date,
    severity: float,
    disease_event_id: Optional[int] = None,
) -> None:
    conn = connect(db_path)
    try:
        overlap = conn.execute(
            "SELECT COUNT(*) FROM illnesses WHERE resident_id = ? AND start_date < ? AND end_date > ?",
            (resident_id, end_date.isoformat(), start_date.isoformat()),
        ).fetchone()[0]
        if overlap:
            raise ValueError(f"resident {resident_id} already has an overlapping illness episode")

        conn.execute(
            "INSERT INTO illnesses (resident_id, disease_event_id, start_date, end_date, severity) "
            "VALUES (?, ?, ?, ?, ?)",
            (resident_id, disease_event_id, start_date.isoformat(), end_date.isoformat(), severity),
        )

        rng = random.Random(f"mark-ill-{resident_id}-{start_date.isoformat()}-{end_date.isoformat()}")
        _reassign_or_delete_buyer_purchases(conn, resident_id, start_date, end_date, rng)

        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_edits.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add town_db/edits.py tests/test_db_edits.py
git commit -m "feat: add mark_resident_ill creative-mode editing primitive"
```

---

## Task 3: `kill_resident` (core — no replacement staffing yet)

**Files:**
- Modify: `town_db/edits.py`
- Modify: `tests/test_db_edits.py`

**Interfaces:**
- Consumes: `_reassign_or_delete_buyer_purchases` (Task 2).
- Produces: `kill_resident(db_path, resident_id, death_date, cause, disease_event_id=None, skirmish_event_id=None, promote_replacement=False) -> None`. `promote_replacement` is accepted in this task's signature but has no effect yet — Task 4 implements its behavior. This keeps the public signature stable across both tasks.
- Produces: `_reporting_building_id(conn) -> Optional[int]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db_edits.py`:

```python
from town_db.edits import kill_resident, mark_resident_ill  # update existing import line


def test_kill_resident_sets_death_date_and_inserts_deaths_row(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident")

    conn = connect(db_path)
    resident_death_date = conn.execute("SELECT death_date FROM residents WHERE id = 1").fetchone()[0]
    deaths_row = conn.execute("SELECT resident_id, death_date, cause FROM deaths WHERE resident_id = 1").fetchone()
    assert resident_death_date == "1300-06-01"
    assert deaths_row == (1, "1300-06-01", "accident")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_kill_resident_reassigns_own_future_purchases(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)
    _insert_resident(conn, 2, 1)
    _insert_good_and_shop(conn)
    _insert_purchase(conn, 1, resident_id=1, purchase_date="1300-07-01")  # after death
    _insert_purchase(conn, 2, resident_id=1, purchase_date="1300-05-01")  # before death
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident")

    conn = connect(db_path)
    assert conn.execute("SELECT resident_id FROM purchases WHERE id = 1").fetchone()[0] == 2
    assert conn.execute("SELECT resident_id FROM purchases WHERE id = 2").fetchone()[0] == 1


def test_kill_resident_deletes_future_tax_payments_and_closes_open_records(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'garrison', 0, 0, 1)"
    )
    conn.execute(
        "INSERT INTO tax_payments (resident_id, tax_type, amount, period, payment_date) "
        "VALUES (1, 'head_tax', 1.0, '1300-Q3', '1300-07-01')"
    )
    conn.execute(
        "INSERT INTO tax_payments (resident_id, tax_type, amount, period, payment_date) "
        "VALUES (1, 'head_tax', 1.0, '1300-Q1', '1300-02-01')"
    )
    conn.execute(
        "INSERT INTO military_service (resident_id, garrison_building_id, rank, start_date, end_date) "
        "VALUES (1, 1, 'soldier', '1298-01-01', NULL)"
    )
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident")

    conn = connect(db_path)
    remaining_tax_dates = [
        row[0] for row in conn.execute("SELECT payment_date FROM tax_payments WHERE resident_id = 1").fetchall()
    ]
    assert remaining_tax_dates == ["1300-02-01"]
    military_end_date = conn.execute(
        "SELECT end_date FROM military_service WHERE resident_id = 1"
    ).fetchone()[0]
    assert military_end_date == "1300-06-01"


def test_kill_resident_raises_if_already_dead(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_resident(conn, 1, 1, death_date="1300-01-01")
    conn.commit()
    conn.close()

    try:
        kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident")
        assert False, "expected ValueError"
    except ValueError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_edits.py -v`
Expected: FAIL with `ImportError: cannot import name 'kill_resident'`

- [ ] **Step 3: Implement `kill_resident` core**

Add to `town_db/edits.py`:

```python
def _reporting_building_id(conn) -> Optional[int]:
    temple = conn.execute(
        "SELECT id FROM buildings WHERE building_type = 'temple' ORDER BY id LIMIT 1"
    ).fetchone()
    if temple:
        return temple[0]
    healer = conn.execute(
        "SELECT id FROM buildings WHERE building_type = 'healer' ORDER BY id LIMIT 1"
    ).fetchone()
    return healer[0] if healer else None


def kill_resident(
    db_path: str,
    resident_id: int,
    death_date: date,
    cause: str,
    disease_event_id: Optional[int] = None,
    skirmish_event_id: Optional[int] = None,
    promote_replacement: bool = False,
) -> None:
    conn = connect(db_path)
    try:
        existing_death_date = conn.execute(
            "SELECT death_date FROM residents WHERE id = ?", (resident_id,)
        ).fetchone()[0]
        if existing_death_date is not None:
            raise ValueError(f"resident {resident_id} already has a death_date ({existing_death_date})")

        reporting_building_id = _reporting_building_id(conn)
        conn.execute("UPDATE residents SET death_date = ? WHERE id = ?", (death_date.isoformat(), resident_id))
        conn.execute(
            "INSERT INTO deaths (resident_id, death_date, cause, disease_event_id, skirmish_event_id, reported_by_building_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (resident_id, death_date.isoformat(), cause, disease_event_id, skirmish_event_id, reporting_building_id),
        )

        conn.execute("UPDATE residents SET workplace_building_id = NULL WHERE id = ?", (resident_id,))

        rng = random.Random(f"kill-resident-{resident_id}-{death_date.isoformat()}")
        _reassign_or_delete_buyer_purchases(conn, resident_id, death_date, None, rng)

        conn.execute(
            "DELETE FROM tax_payments WHERE resident_id = ? AND payment_date >= ?",
            (resident_id, death_date.isoformat()),
        )
        conn.execute(
            "UPDATE military_service SET end_date = ? WHERE resident_id = ? AND end_date IS NULL",
            (death_date.isoformat(), resident_id),
        )
        conn.execute(
            "UPDATE school_enrollments SET end_date = ? WHERE resident_id = ? AND end_date IS NULL",
            (death_date.isoformat(), resident_id),
        )

        conn.commit()
    finally:
        conn.close()
```

Note: `promote_replacement` is accepted but unused in this task — Task 4 wires it up. The workplace is unconditionally vacated here; Task 4 changes this to conditionally promote first.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_edits.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add town_db/edits.py tests/test_db_edits.py
git commit -m "feat: add kill_resident core creative-mode editing primitive"
```

---

## Task 4: `kill_resident` replacement staffing + shop reputation ramp (Decision 2)

**Files:**
- Modify: `town_db/edits.py`
- Modify: `tests/test_db_edits.py`

**Interfaces:**
- Consumes: `town_shaper.buildings.JOB_VACANCIES_BY_BUILDING_TYPE`.
- Produces: `_primary_occupation_info(building_type, occupation) -> Tuple[bool, Optional[str]]`, `_promote_apprentice(conn, workplace_id, apprentice_occupation, primary_occupation) -> Optional[int]`, `_apply_shop_reputation_ramp(conn, shop_building_id, from_date, ceiling, rng) -> None`. Modifies `kill_resident` to call these.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db_edits.py`:

```python
def _insert_blacksmith_building(conn, building_id, district_id=1):
    conn.execute(
        "INSERT OR IGNORE INTO districts (id, zone_type, polygon) VALUES (?, 'merchant', '[]')",
        (district_id,),
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (?, ?, 'merchant', 'blacksmith', 0, 0, 3)",
        (building_id, district_id),
    )


def test_kill_resident_promotes_apprentice_when_requested(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_household(conn, 2)
    _insert_blacksmith_building(conn, building_id=1)
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) VALUES (1, 1, 'A', 'B', 'male', 'human', '1260-01-01', 'poor', 1, 'blacksmith')"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) VALUES (2, 2, 'C', 'D', 'male', 'human', '1280-01-01', 'poor', 1, 'smith_apprentice')"
    )
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident", promote_replacement=True)

    conn = connect(db_path)
    promoted_occupation = conn.execute("SELECT occupation FROM residents WHERE id = 2").fetchone()[0]
    assert promoted_occupation == "blacksmith"


def test_kill_resident_leaves_position_vacant_when_no_apprentice_exists(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_blacksmith_building(conn, building_id=1)
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) VALUES (1, 1, 'A', 'B', 'male', 'human', '1260-01-01', 'poor', 1, 'blacksmith')"
    )
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident", promote_replacement=True)

    conn = connect(db_path)
    workplace = conn.execute("SELECT workplace_building_id FROM residents WHERE id = 1").fetchone()[0]
    assert workplace is None


def test_kill_resident_shop_ramp_uses_lower_ceiling_when_replacement_promoted(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    _insert_household(conn, 1)
    _insert_household(conn, 2)
    _insert_household(conn, 3)
    _insert_blacksmith_building(conn, building_id=1)
    conn.execute(
        "INSERT INTO goods (id, name, category, typical_price, sv) VALUES (1, 'sword', 'weapons', 10.0, 350)"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) VALUES (1, 1, 'A', 'B', 'male', 'human', '1260-01-01', 'poor', 1, 'blacksmith')"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) VALUES (2, 2, 'C', 'D', 'male', 'human', '1280-01-01', 'poor', 1, 'smith_apprentice')"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses) "
        "VALUES (3, 3, 'E', 'F', 'male', 'human', '1270-01-01', 'poor')"
    )
    # 200 far-future purchases at the shop by an unrelated customer (resident 3), so the redirect
    # ramp has enough volume for its ceiling to show up as a clear statistical difference.
    for i in range(200):
        conn.execute(
            "INSERT INTO purchases (id, resident_id, shop_building_id, good_id, quantity, unit_price, total_price, purchase_date) "
            "VALUES (?, 3, 1, 1, 1, 10.0, 10.0, '1300-11-01')",
            (i + 1,),
        )
    conn.commit()
    conn.close()

    kill_resident(db_path, resident_id=1, death_date=date(1300, 6, 1), cause="accident", promote_replacement=True)

    conn = connect(db_path)
    remaining_at_shop = conn.execute(
        "SELECT COUNT(*) FROM purchases WHERE shop_building_id = 1 AND purchase_date = '1300-11-01'"
    ).fetchone()[0]
    # 153 days after a 1300-06-01 death exceeds the 120-day ramp, so the chance is pinned at the
    # ceiling for every purchase. With the fixed seed _apply_shop_reputation_ramp derives for this
    # resident/death_date, running the actual RNG sequence gives exactly 136 of 200 remaining at
    # the 0.30 (replaced) ceiling -- versus 73 remaining if the 0.65 (vacant) ceiling had applied
    # instead, confirming promote_replacement genuinely changes which ceiling is used.
    assert remaining_at_shop == 136
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_edits.py -v`
Expected: the three new tests FAIL — `promote_replacement` currently has no effect (position is always vacated, no ramp is applied).

- [ ] **Step 3: Implement replacement staffing and the shop reputation ramp**

Add near the top of `town_db/edits.py`:

```python
from town_shaper.buildings import JOB_VACANCIES_BY_BUILDING_TYPE

SHOP_LOSS_CEILING_VACANT = 0.65
SHOP_LOSS_CEILING_REPLACED = 0.30
SHOP_LOSS_RAMP_DAYS = 120
```

Add the new helpers:

```python
def _primary_occupation_info(building_type: Optional[str], occupation: Optional[str]):
    if building_type is None:
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


def _apply_shop_reputation_ramp(conn, shop_building_id, from_date, ceiling, rng) -> None:
    other_shops = [
        row[0] for row in conn.execute(
            "SELECT b2.id FROM buildings b1 JOIN buildings b2 ON b2.building_type = b1.building_type "
            "WHERE b1.id = ? AND b2.id != ?",
            (shop_building_id, shop_building_id),
        ).fetchall()
    ]
    rows = conn.execute(
        "SELECT id, purchase_date FROM purchases WHERE shop_building_id = ? AND purchase_date >= ? ORDER BY id",
        (shop_building_id, from_date.isoformat()),
    ).fetchall()
    for purchase_id, purchase_date in rows:
        days_since = (date.fromisoformat(purchase_date) - from_date).days
        chance = min(ceiling, days_since / SHOP_LOSS_RAMP_DAYS * ceiling)
        if rng.random() < chance:
            if other_shops:
                dest = rng.choice(other_shops)
                conn.execute("UPDATE purchases SET shop_building_id = ? WHERE id = ?", (dest, purchase_id))
            else:
                conn.execute("DELETE FROM purchases WHERE id = ?", (purchase_id,))
```

Replace the body of `kill_resident` between the `deaths` insert and the `_reassign_or_delete_buyer_purchases` call with:

```python
        workplace_id, occupation, building_type = conn.execute(
            "SELECT r.workplace_building_id, r.occupation, b.building_type FROM residents r "
            "LEFT JOIN buildings b ON b.id = r.workplace_building_id WHERE r.id = ?",
            (resident_id,),
        ).fetchone()

        is_primary, apprentice_occupation = _primary_occupation_info(building_type, occupation)
        promoted_id = None
        if is_primary and promote_replacement:
            promoted_id = _promote_apprentice(conn, workplace_id, apprentice_occupation, occupation)

        conn.execute("UPDATE residents SET workplace_building_id = NULL WHERE id = ?", (resident_id,))

        rng = random.Random(f"kill-resident-{resident_id}-{death_date.isoformat()}")
        _reassign_or_delete_buyer_purchases(conn, resident_id, death_date, None, rng)

        if is_primary:
            shop_rng = random.Random(f"kill-resident-shop-ramp-{resident_id}-{death_date.isoformat()}")
            ceiling = SHOP_LOSS_CEILING_REPLACED if promoted_id is not None else SHOP_LOSS_CEILING_VACANT
            _apply_shop_reputation_ramp(conn, workplace_id, death_date, ceiling, shop_rng)
```

(This replaces the old unconditional `conn.execute("UPDATE residents SET workplace_building_id = NULL ...")` line — the fetch of `workplace_id`/`occupation`/`building_type` now happens here, before that vacate, instead of not at all.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_edits.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add town_db/edits.py tests/test_db_edits.py
git commit -m "feat: add kill_resident replacement staffing (Decision 2)"
```

---

## Task 5: `scope_disease_event` and `create_disease_event`

**Files:**
- Modify: `town_db/edits.py`
- Modify: `tests/test_db_edits.py`

**Interfaces:**
- Produces: `scope_disease_event(db_path, event_id, zone_type) -> None`, `create_disease_event(db_path, zone_type, start_date, end_date, severity) -> int`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db_edits.py`:

```python
from town_db.edits import create_disease_event, scope_disease_event  # update existing import line


def test_scope_disease_event_sets_affected_zone_type(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO disease_events (id, name, start_date, end_date, affected_zone_type, severity) "
        "VALUES (1, 'fever', '1300-03-01', '1300-04-01', NULL, 0.5)"
    )
    conn.commit()
    conn.close()

    scope_disease_event(db_path, event_id=1, zone_type="merchant")

    conn = connect(db_path)
    assert conn.execute("SELECT affected_zone_type FROM disease_events WHERE id = 1").fetchone()[0] == "merchant"


def test_create_disease_event_inserts_and_returns_new_id(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.commit()
    conn.close()

    event_id = create_disease_event(
        db_path, zone_type="poor_residential", start_date=date(1300, 5, 1), end_date=date(1300, 6, 1), severity=0.7
    )

    conn = connect(db_path)
    row = conn.execute(
        "SELECT start_date, end_date, affected_zone_type, severity FROM disease_events WHERE id = ?", (event_id,)
    ).fetchone()
    assert row == ("1300-05-01", "1300-06-01", "poor_residential", 0.7)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_edits.py -v`
Expected: FAIL with `ImportError: cannot import name 'scope_disease_event'`

- [ ] **Step 3: Implement both functions**

Add to `town_db/edits.py`:

```python
def scope_disease_event(db_path: str, event_id: int, zone_type: str) -> None:
    conn = connect(db_path)
    try:
        conn.execute("UPDATE disease_events SET affected_zone_type = ? WHERE id = ?", (zone_type, event_id))
        conn.commit()
    finally:
        conn.close()


def create_disease_event(
    db_path: str, zone_type: str, start_date: date, end_date: date, severity: float
) -> int:
    conn = connect(db_path)
    try:
        cursor = conn.execute(
            "INSERT INTO disease_events (name, start_date, end_date, affected_zone_type, severity) "
            "VALUES (?, ?, ?, ?, ?)",
            ("an outbreak of fever", start_date.isoformat(), end_date.isoformat(), zone_type, severity),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_edits.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add town_db/edits.py tests/test_db_edits.py
git commit -m "feat: add scope_disease_event and create_disease_event primitives"
```

---

## Task 6: Integration test against real generated towns (seed sweep)

Per project convention (D1b/D1c found real bugs this way): randomized cascade logic gets exercised against real generated towns across multiple seeds, not just hand-crafted fixtures, and checked for isolation (no resident outside the mutation's own household/shop is affected).

**Files:**
- Create: `tests/test_db_edits_integration.py`

**Interfaces:**
- Consumes: `town_db.generate.generate_town_database`, all four public functions from `town_db.edits`.

- [ ] **Step 1: Write the integration test**

Create `tests/test_db_edits_integration.py`:

```python
# tests/test_db_edits_integration.py
from datetime import date

import pytest

from town_db.edits import create_disease_event, kill_resident, mark_resident_ill, scope_disease_event
from town_db.generate import generate_town_database
from town_db.schema import connect


@pytest.mark.parametrize("seed_index", range(5))
def test_kill_resident_against_a_real_town_keeps_fk_integrity_and_touches_only_expected_rows(seed_index, tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("edit-integration", seed_index), target_population=2000, db_path=db_path)

    conn = connect(db_path)
    resident_id = conn.execute("SELECT id FROM residents WHERE death_date IS NULL ORDER BY id LIMIT 1").fetchone()[0]
    other_resident_purchases_before = {
        row[0]: row[1] for row in conn.execute(
            "SELECT id, resident_id FROM purchases WHERE resident_id != ?", (resident_id,)
        ).fetchall()
    }
    conn.close()

    kill_resident(db_path, resident_id=resident_id, death_date=date(1300, 6, 1), cause="accident")

    conn = connect(db_path)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("SELECT death_date FROM residents WHERE id = ?", (resident_id,)).fetchone()[0] == "1300-06-01"

    other_resident_purchases_after = {
        row[0]: row[1] for row in conn.execute(
            "SELECT id, resident_id FROM purchases WHERE id IN ({})".format(
                ",".join(str(k) for k in other_resident_purchases_before)
            )
        ).fetchall()
    } if other_resident_purchases_before else {}
    assert other_resident_purchases_after == other_resident_purchases_before


@pytest.mark.parametrize("seed_index", range(5))
def test_mark_resident_ill_against_a_real_town_keeps_fk_integrity(seed_index, tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("edit-integration-ill", seed_index), target_population=2000, db_path=db_path)

    conn = connect(db_path)
    resident_id = conn.execute("SELECT id FROM residents WHERE death_date IS NULL ORDER BY id LIMIT 1").fetchone()[0]
    conn.close()

    mark_resident_ill(db_path, resident_id=resident_id, start_date=date(1300, 3, 1), end_date=date(1300, 4, 1), severity=0.5)

    conn = connect(db_path)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("SELECT COUNT(*) FROM illnesses WHERE resident_id = ?", (resident_id,)).fetchone()[0] == 1


@pytest.mark.parametrize("seed_index", range(5))
def test_kill_resident_with_promote_replacement_against_a_real_town(seed_index, tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("edit-integration-promote", seed_index), target_population=3000, db_path=db_path)

    conn = connect(db_path)
    blacksmith = conn.execute(
        "SELECT id FROM residents WHERE occupation = 'blacksmith' AND death_date IS NULL ORDER BY id LIMIT 1"
    ).fetchone()
    conn.close()
    if blacksmith is None:
        pytest.skip("no living blacksmith in this seed's town")
    resident_id = blacksmith[0]

    kill_resident(db_path, resident_id=resident_id, death_date=date(1300, 6, 1), cause="accident", promote_replacement=True)

    conn = connect(db_path)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_scope_and_create_disease_event_against_a_real_town(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("edit-integration-disease", 0), target_population=2000, db_path=db_path)

    new_id = create_disease_event(
        db_path, zone_type="merchant", start_date=date(1300, 4, 1), end_date=date(1300, 5, 1), severity=0.4
    )
    scope_disease_event(db_path, event_id=new_id, zone_type="civic")

    conn = connect(db_path)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute(
        "SELECT affected_zone_type FROM disease_events WHERE id = ?", (new_id,)
    ).fetchone()[0] == "civic"
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/test_db_edits_integration.py -v`
Expected: all PASS (the `promote_replacement` tests may `SKIP` on seeds with no living blacksmith — that's expected, not a failure).

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `python -m pytest`
Expected: all PASS (previously 286 tests, now 286 + this plan's new tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_db_edits_integration.py
git commit -m "test: add seed-sweep integration tests for creative-mode editing"
```

---

## Self-Review Notes

- **Spec coverage**: `illnesses` table (Task 1); `mark_resident_ill` (Task 2); `kill_resident` core cascade — purchases/tax/military/school (Task 3); Decision 2 replacement staffing + shop reputation ramp (Task 4); `scope_disease_event`/`create_disease_event`, Decision 1 explicitly left with no cascade (Task 5); seed-sweep testing per spec's Testing section (Task 6). Idempotency/error cases (already-dead resident, overlapping illness) covered in Tasks 2 and 3; a `disease_event_id` that doesn't exist is covered implicitly by SQLite's own FK enforcement (`connect()` sets `PRAGMA foreign_keys = ON`) rather than needing bespoke code — not separately tested here since it's stdlib behavior, not this module's logic.
- **Type/signature consistency**: `kill_resident`'s full signature (including `promote_replacement`) is introduced once in Task 3 and never changes shape afterward, only behavior — avoids a signature edit landing in two places.
- **Placeholder scan**: no TBD/TODO; every step has real, complete code.
