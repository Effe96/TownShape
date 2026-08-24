# Town Relationships Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `town_relationships`, a package that derives resident-to-resident and resident-to-shop relationship tables purely from a Town DB database's existing contents — no new randomness, no new population/event generation.

**Architecture:** `town_relationships.generate.derive_relationships(db_path, reference_date=...)` reads the existing tables of a town's SQLite file into plain lists of dicts, calls a sequence of pure derivation functions (family, work, neighbors, military, school, shops) that each return plain relationship-row dicts from those inputs, then inserts the results into two new tables (`relationships`, `shop_relationships`) in that same file. Every derivation module except `generate.py` and `schema.py` takes and returns plain Python data — no `sqlite3.Connection` — mirroring `town_db`'s own module design (`households.py`, `taxes.py`, etc. all take/return dicts; only `generate.py`/`schema.py` touch SQL directly).

**Tech Stack:** Python 3.12, stdlib only (`sqlite3`, `json`, `datetime`) plus the already-present `town_shaper.geometry.distance` helper — no new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-08-24-town-relationships-design.md`

## Global Constraints

- No function anywhere in `town_relationships` takes a `seed` or calls anything from `town_shaper.seeding` — every derivation is a pure function of already-persisted `town_db` data, so the same input database always produces identical output.
- Every derivation module (`family.py`, `work.py`, `neighbors.py`, `military.py`, `school.py`, `shops.py`) takes plain lists of dicts and returns plain lists of dicts — it never touches a `sqlite3.Connection` directly. Only `schema.py` and `generate.py` do.
- All SQLite connections are opened via `town_db.schema.connect(db_path)` (already sets `PRAGMA foreign_keys = ON` per connection) — never reimplemented.
- Symmetric relationship types (`spouse`, `sibling`, `household_member`, `coworker`, `neighbor`, `unit_mate`, `classmate`) are always built via the shared `town_relationships.pairs.canonical_pair(...)` helper, which canonicalizes `resident_a_id < resident_b_id`. `parent` is the one asymmetric type (`resident_a_id` = parent, `resident_b_id` = child) and must be built as a plain dict, never through `canonical_pair`.
- Euclidean distance between two `(x, y)` points is always computed via the already-existing `town_shaper.geometry.distance(p1, p2)` — never reimplemented.
- Date-range overlap logic (used by both `military.py` and `school.py`) lives once in `town_relationships/overlap.py` and is imported by both, not duplicated.
- ISO 8601 date strings (`YYYY-MM-DD`) are compared directly as strings wherever only ordering matters (they sort correctly lexicographically) — only converted to `datetime.date` where actual age arithmetic is needed (`family.py`).
- Test files live in the shared top-level `tests/` directory (this repo does not use per-package `tests/` subdirectories) with the `test_relationships_` filename prefix, matching `town_db`'s established `test_db_` prefix convention.
- `derive_relationships(db_path, ...)` is safe to call **at most once** per database — it does not check for or clean up pre-existing rows in `relationships`/`shop_relationships`. This is a documented precondition, not defended against.

---

## Task 1: Package scaffolding, shared pair helper, and relationship schema

**Files:**
- Create: `town_relationships/__init__.py`
- Create: `town_relationships/pairs.py`
- Create: `town_relationships/schema.py`
- Test: `tests/test_relationships_pairs.py`
- Test: `tests/test_relationships_schema.py`

**Interfaces:**
- Consumes: `town_db.schema.connect`, `town_db.schema.create_schema` (already exist)
- Produces: `canonical_pair(resident_a_id: int, resident_b_id: int, relationship_type: str, detail: Optional[str] = None) -> Dict[str, Any]`, `RELATIONSHIPS_SCHEMA_SQL: str`, `create_relationships_schema(conn: sqlite3.Connection) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_relationships_pairs.py
from town_relationships.pairs import canonical_pair


def test_canonical_pair_orders_lower_id_first():
    row = canonical_pair(7, 3, "coworker")
    assert row["resident_a_id"] == 3
    assert row["resident_b_id"] == 7
    assert row["relationship_type"] == "coworker"
    assert row["detail"] is None


def test_canonical_pair_is_order_independent():
    assert canonical_pair(3, 7, "coworker") == canonical_pair(7, 3, "coworker")


def test_canonical_pair_carries_detail():
    row = canonical_pair(1, 2, "neighbor", detail='{"distance": 5.0}')
    assert row["detail"] == '{"distance": 5.0}'
```

```python
# tests/test_relationships_schema.py
import sqlite3

from town_db.schema import connect, create_schema

from town_relationships.schema import create_relationships_schema

EXPECTED_TABLES = {"relationships", "shop_relationships"}


def test_create_relationships_schema_creates_both_tables(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    create_relationships_schema(conn)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {row[0] for row in rows}
    assert EXPECTED_TABLES <= table_names


def test_relationships_foreign_keys_are_enforced(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    create_relationships_schema(conn)
    try:
        conn.execute(
            "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type) VALUES (1, 2, 'coworker')"
        )
        conn.commit()
        assert False, "expected a foreign key violation"
    except sqlite3.IntegrityError:
        pass


def test_shop_relationships_foreign_keys_are_enforced(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    create_relationships_schema(conn)
    try:
        conn.execute(
            "INSERT INTO shop_relationships (resident_id, shop_building_id, purchase_count, total_spent, "
            "distance, need_score, customer_score) VALUES (1, 1, 0, 0.0, 0.0, 0.0, 0.0)"
        )
        conn.commit()
        assert False, "expected a foreign key violation"
    except sqlite3.IntegrityError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_relationships_pairs.py tests/test_relationships_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_relationships'`

- [ ] **Step 3: Write the package files**

```python
# town_relationships/__init__.py
```

```python
# town_relationships/pairs.py
from typing import Any, Dict, Optional


def canonical_pair(
    resident_a_id: int, resident_b_id: int, relationship_type: str, detail: Optional[str] = None
) -> Dict[str, Any]:
    lo, hi = (resident_a_id, resident_b_id) if resident_a_id < resident_b_id else (resident_b_id, resident_a_id)
    return {"resident_a_id": lo, "resident_b_id": hi, "relationship_type": relationship_type, "detail": detail}
```

```python
# town_relationships/schema.py
import sqlite3

RELATIONSHIPS_SCHEMA_SQL = """
CREATE TABLE relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_a_id INTEGER NOT NULL REFERENCES residents(id),
    resident_b_id INTEGER NOT NULL REFERENCES residents(id),
    relationship_type TEXT NOT NULL,
    detail TEXT
);

CREATE TABLE shop_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    shop_building_id INTEGER NOT NULL REFERENCES buildings(id),
    purchase_count INTEGER NOT NULL,
    total_spent REAL NOT NULL,
    distance REAL NOT NULL,
    need_score REAL NOT NULL,
    customer_score REAL NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0
);
"""


def create_relationships_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(RELATIONSHIPS_SCHEMA_SQL)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_relationships_pairs.py tests/test_relationships_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_relationships/__init__.py town_relationships/pairs.py town_relationships/schema.py tests/test_relationships_pairs.py tests/test_relationships_schema.py
git commit -m "feat: add town_relationships package scaffolding and schema"
```

---

## Task 2: Family relationships (spouse, parent, sibling, household_member)

**Files:**
- Create: `town_relationships/family.py`
- Test: `tests/test_relationships_family.py`

**Interfaces:**
- Consumes: `town_relationships.pairs.canonical_pair`
- Produces: `derive_family_relationships(residents: List[Dict[str, Any]], births: List[Dict[str, Any]], reference_date: date) -> List[Dict[str, Any]]`. Each `residents` item needs keys `id`, `household_id`, `birth_date` (ISO string). Each `births` item needs keys `child_resident_id`, `mother_resident_id`, `father_resident_id` (nullable).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_relationships_family.py
from datetime import date

from town_relationships.family import derive_family_relationships

REFERENCE_DATE = date(1300, 1, 1)


def _resident(resident_id, household_id, age):
    birth_year = REFERENCE_DATE.year - age
    return {"id": resident_id, "household_id": household_id, "birth_date": date(birth_year, 1, 1).isoformat()}


def test_two_adult_household_with_children_gets_spouse_parent_and_sibling():
    residents = [
        _resident(1, 100, 40), _resident(2, 100, 38),
        _resident(3, 100, 10), _resident(4, 100, 8),
    ]
    relationships = derive_family_relationships(residents, [], REFERENCE_DATE)

    triples = {(r["resident_a_id"], r["resident_b_id"], r["relationship_type"]) for r in relationships}
    assert (1, 2, "spouse") in triples
    assert (1, 3, "parent") in triples
    assert (2, 3, "parent") in triples
    assert (1, 4, "parent") in triples
    assert (2, 4, "parent") in triples
    assert (3, 4, "sibling") in triples
    assert "household_member" not in {r["relationship_type"] for r in relationships}


def test_three_adult_household_extra_adult_gets_household_member_not_a_role():
    residents = [_resident(1, 100, 45), _resident(2, 100, 43), _resident(3, 100, 20)]
    relationships = derive_family_relationships(residents, [], REFERENCE_DATE)

    by_type = {}
    for r in relationships:
        by_type.setdefault(r["relationship_type"], set()).add((r["resident_a_id"], r["resident_b_id"]))

    assert by_type.get("spouse") == {(1, 2)}
    assert by_type.get("household_member") == {(1, 3), (2, 3)}
    assert "parent" not in by_type


def test_single_resident_household_produces_no_relationships():
    residents = [_resident(1, 100, 30)]
    assert derive_family_relationships(residents, [], REFERENCE_DATE) == []


def test_single_adult_household_still_tags_parent_but_no_spouse():
    residents = [_resident(1, 100, 30), _resident(2, 100, 5)]
    relationships = derive_family_relationships(residents, [], REFERENCE_DATE)
    triples = {(r["resident_a_id"], r["resident_b_id"], r["relationship_type"]) for r in relationships}
    assert triples == {(1, 2, "parent")}


def test_birth_record_overrides_household_heuristic_for_parentage():
    residents = [
        _resident(1, 100, 45), _resident(2, 100, 43), _resident(3, 100, 22), _resident(4, 100, 0),
    ]
    births = [{"child_resident_id": 4, "mother_resident_id": 3, "father_resident_id": None}]
    relationships = derive_family_relationships(residents, births, REFERENCE_DATE)
    parent_pairs = {
        (r["resident_a_id"], r["resident_b_id"]) for r in relationships if r["relationship_type"] == "parent"
    }
    # The heuristic would have used the first two adults (1, 2); the real birth
    # record says the mother is adult #3 -- the exact record must win.
    assert parent_pairs == {(3, 4)}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_relationships_family.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_relationships.family'`

- [ ] **Step 3: Write the implementation**

```python
# town_relationships/family.py
from datetime import date
from typing import Any, Dict, List

from town_relationships.pairs import canonical_pair

ADULT_MIN_AGE = 18


def _age_on(birth_date: date, on_date: date) -> int:
    age = on_date.year - birth_date.year
    if (on_date.month, on_date.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def derive_family_relationships(
    residents: List[Dict[str, Any]], births: List[Dict[str, Any]], reference_date: date
) -> List[Dict[str, Any]]:
    residents_by_household: Dict[int, List[Dict[str, Any]]] = {}
    for resident in sorted(residents, key=lambda r: r["id"]):
        residents_by_household.setdefault(resident["household_id"], []).append(resident)

    birth_parents: Dict[int, List[int]] = {}
    for birth in births:
        parents = [birth["mother_resident_id"]]
        if birth["father_resident_id"] is not None:
            parents.append(birth["father_resident_id"])
        birth_parents[birth["child_resident_id"]] = parents

    relationships: List[Dict[str, Any]] = []

    for members in residents_by_household.values():
        adults, children = [], []
        for member in members:
            birth_date = date.fromisoformat(member["birth_date"])
            (adults if _age_on(birth_date, reference_date) >= ADULT_MIN_AGE else children).append(member)

        parent_candidates = adults[:2]
        extra_adults = adults[2:]

        if len(parent_candidates) == 2:
            relationships.append(
                canonical_pair(parent_candidates[0]["id"], parent_candidates[1]["id"], "spouse")
            )

        for child in children:
            if child["id"] in birth_parents:
                for parent_id in birth_parents[child["id"]]:
                    relationships.append({
                        "resident_a_id": parent_id, "resident_b_id": child["id"],
                        "relationship_type": "parent", "detail": None,
                    })
            else:
                for parent in parent_candidates:
                    relationships.append({
                        "resident_a_id": parent["id"], "resident_b_id": child["id"],
                        "relationship_type": "parent", "detail": None,
                    })

        for i in range(len(children)):
            for j in range(i + 1, len(children)):
                relationships.append(canonical_pair(children[i]["id"], children[j]["id"], "sibling"))

        non_extra = parent_candidates + children
        for extra in extra_adults:
            for other in non_extra:
                relationships.append(canonical_pair(extra["id"], other["id"], "household_member"))
        for i in range(len(extra_adults)):
            for j in range(i + 1, len(extra_adults)):
                relationships.append(
                    canonical_pair(extra_adults[i]["id"], extra_adults[j]["id"], "household_member")
                )

    return relationships
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_relationships_family.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_relationships/family.py tests/test_relationships_family.py
git commit -m "feat: derive spouse/parent/sibling/household_member relationships"
```

---

## Task 3: Coworker relationships

**Files:**
- Create: `town_relationships/work.py`
- Test: `tests/test_relationships_work.py`

**Interfaces:**
- Consumes: `town_relationships.pairs.canonical_pair`
- Produces: `derive_coworker_relationships(residents: List[Dict[str, Any]]) -> List[Dict[str, Any]]`. Each `residents` item needs keys `id`, `workplace_building_id` (nullable).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_relationships_work.py
from town_relationships.work import derive_coworker_relationships


def test_residents_sharing_a_workplace_are_coworkers():
    residents = [
        {"id": 1, "workplace_building_id": 50}, {"id": 2, "workplace_building_id": 50},
        {"id": 3, "workplace_building_id": 51},
    ]
    relationships = derive_coworker_relationships(residents)
    pairs = {(r["resident_a_id"], r["resident_b_id"]) for r in relationships}
    assert pairs == {(1, 2)}
    assert all(r["relationship_type"] == "coworker" for r in relationships)


def test_residents_with_no_workplace_are_excluded():
    residents = [{"id": 1, "workplace_building_id": None}, {"id": 2, "workplace_building_id": None}]
    assert derive_coworker_relationships(residents) == []


def test_three_coworkers_at_the_same_workplace_get_every_pair():
    residents = [{"id": i, "workplace_building_id": 50} for i in (1, 2, 3)]
    relationships = derive_coworker_relationships(residents)
    pairs = {(r["resident_a_id"], r["resident_b_id"]) for r in relationships}
    assert pairs == {(1, 2), (1, 3), (2, 3)}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_relationships_work.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_relationships.work'`

- [ ] **Step 3: Write the implementation**

```python
# town_relationships/work.py
from typing import Any, Dict, List

from town_relationships.pairs import canonical_pair


def derive_coworker_relationships(residents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    residents_by_workplace: Dict[int, List[int]] = {}
    for resident in residents:
        workplace_id = resident.get("workplace_building_id")
        if workplace_id is not None:
            residents_by_workplace.setdefault(workplace_id, []).append(resident["id"])

    relationships: List[Dict[str, Any]] = []
    for resident_ids in residents_by_workplace.values():
        resident_ids = sorted(resident_ids)
        for i in range(len(resident_ids)):
            for j in range(i + 1, len(resident_ids)):
                relationships.append(canonical_pair(resident_ids[i], resident_ids[j], "coworker"))
    return relationships
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_relationships_work.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_relationships/work.py tests/test_relationships_work.py
git commit -m "feat: derive coworker relationships"
```

---

## Task 4: Neighbor relationships

**Note beyond the spec's literal wording:** the spec describes the K-nearest cross-building graph but doesn't address two different households sharing one physical building (possible when a building's capacity exceeds one household's size). Tagging same-building, different-household residents as `neighbor` at `distance: 0.0` is a direct, low-risk completion of the same rule (physically closest residents are the most obvious neighbors) — flagged here rather than silently assumed.

**Files:**
- Create: `town_relationships/neighbors.py`
- Test: `tests/test_relationships_neighbors.py`

**Interfaces:**
- Consumes: `town_relationships.pairs.canonical_pair`, `town_shaper.geometry.distance`
- Produces: `derive_neighbor_relationships(residents: List[Dict[str, Any]], buildings: List[Dict[str, Any]], k: int = K_NEAREST_BUILDINGS) -> List[Dict[str, Any]]`, `K_NEAREST_BUILDINGS = 4`. Each `residents` item needs keys `id`, `household_id`, `home_building_id` (nullable). Each `buildings` item needs keys `id`, `x`, `y`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_relationships_neighbors.py
import json

from town_relationships.neighbors import derive_neighbor_relationships


def test_residents_of_different_households_in_the_same_building_are_neighbors_at_zero_distance():
    residents = [
        {"id": 1, "household_id": 100, "home_building_id": 1},
        {"id": 2, "household_id": 200, "home_building_id": 1},
    ]
    buildings = [{"id": 1, "x": 0.0, "y": 0.0}]
    relationships = derive_neighbor_relationships(residents, buildings)
    assert len(relationships) == 1
    row = relationships[0]
    assert (row["resident_a_id"], row["resident_b_id"]) == (1, 2)
    assert json.loads(row["detail"])["distance"] == 0.0


def test_residents_of_the_same_household_and_building_are_not_double_counted_as_neighbors():
    residents = [
        {"id": 1, "household_id": 100, "home_building_id": 1},
        {"id": 2, "household_id": 100, "home_building_id": 1},
    ]
    buildings = [{"id": 1, "x": 0.0, "y": 0.0}]
    assert derive_neighbor_relationships(residents, buildings) == []


def test_nearest_building_within_k_produces_neighbor_ties():
    residents = [
        {"id": 1, "household_id": 100, "home_building_id": 1},
        {"id": 2, "household_id": 200, "home_building_id": 2},
    ]
    buildings = [{"id": 1, "x": 0.0, "y": 0.0}, {"id": 2, "x": 3.0, "y": 4.0}]
    relationships = derive_neighbor_relationships(residents, buildings, k=1)
    assert len(relationships) == 1
    row = relationships[0]
    assert (row["resident_a_id"], row["resident_b_id"]) == (1, 2)
    assert json.loads(row["detail"])["distance"] == 5.0


def test_buildings_beyond_k_nearest_are_not_neighbors():
    residents = [
        {"id": 1, "household_id": 100, "home_building_id": 1},
        {"id": 2, "household_id": 200, "home_building_id": 2},
        {"id": 3, "household_id": 300, "home_building_id": 3},
        {"id": 4, "household_id": 400, "home_building_id": 4},
    ]
    buildings = [
        {"id": 1, "x": 0.0, "y": 0.0}, {"id": 2, "x": 1.0, "y": 0.0},
        {"id": 3, "x": 1000.0, "y": 0.0}, {"id": 4, "x": 1001.0, "y": 0.0},
    ]
    relationships = derive_neighbor_relationships(residents, buildings, k=1)
    pairs = {(r["resident_a_id"], r["resident_b_id"]) for r in relationships}
    assert pairs == {(1, 2), (3, 4)}


def test_residents_with_no_home_building_are_excluded():
    residents = [{"id": 1, "household_id": 100, "home_building_id": None}]
    buildings = [{"id": 1, "x": 0.0, "y": 0.0}]
    assert derive_neighbor_relationships(residents, buildings) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_relationships_neighbors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_relationships.neighbors'`

- [ ] **Step 3: Write the implementation**

```python
# town_relationships/neighbors.py
import json
from typing import Any, Dict, List, Tuple

from town_shaper.geometry import distance

from town_relationships.pairs import canonical_pair

K_NEAREST_BUILDINGS = 4


def _connected_building_pairs(
    building_coords: Dict[int, Tuple[float, float]], k: int
) -> List[Tuple[int, int, float]]:
    building_ids = sorted(building_coords)
    connected: Dict[Tuple[int, int], float] = {}
    for building_id in building_ids:
        candidates = [
            (other_id, distance(building_coords[building_id], building_coords[other_id]))
            for other_id in building_ids if other_id != building_id
        ]
        candidates.sort(key=lambda pair: (pair[1], pair[0]))
        for other_id, dist in candidates[:k]:
            lo, hi = (building_id, other_id) if building_id < other_id else (other_id, building_id)
            connected[(lo, hi)] = dist
    return [(lo, hi, dist) for (lo, hi), dist in connected.items()]


def derive_neighbor_relationships(
    residents: List[Dict[str, Any]], buildings: List[Dict[str, Any]], k: int = K_NEAREST_BUILDINGS
) -> List[Dict[str, Any]]:
    building_coords = {b["id"]: (b["x"], b["y"]) for b in buildings}

    residents_by_building: Dict[int, List[Dict[str, Any]]] = {}
    for resident in residents:
        home_id = resident.get("home_building_id")
        if home_id is not None:
            residents_by_building.setdefault(home_id, []).append(resident)

    relationships: List[Dict[str, Any]] = []

    # Same building, different household: distance 0, always neighbors.
    for occupants in residents_by_building.values():
        for i in range(len(occupants)):
            for j in range(i + 1, len(occupants)):
                a, b = occupants[i], occupants[j]
                if a["household_id"] != b["household_id"]:
                    detail = json.dumps({"distance": 0.0})
                    relationships.append(canonical_pair(a["id"], b["id"], "neighbor", detail))

    # Cross-building K-nearest union graph.
    occupied_coords = {bid: building_coords[bid] for bid in residents_by_building if bid in building_coords}
    if len(occupied_coords) >= 2:
        for building_a, building_b, dist in _connected_building_pairs(occupied_coords, k):
            detail = json.dumps({"distance": dist})
            for resident_a in residents_by_building[building_a]:
                for resident_b in residents_by_building[building_b]:
                    relationships.append(canonical_pair(resident_a["id"], resident_b["id"], "neighbor", detail))

    return relationships
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_relationships_neighbors.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_relationships/neighbors.py tests/test_relationships_neighbors.py
git commit -m "feat: derive neighbor relationships from K-nearest buildings"
```

---

## Task 5: Date-overlap helper and unit_mate relationships

**Files:**
- Create: `town_relationships/overlap.py`
- Create: `town_relationships/military.py`
- Test: `tests/test_relationships_overlap.py`
- Test: `tests/test_relationships_military.py`

**Interfaces:**
- Consumes: `town_relationships.pairs.canonical_pair`
- Produces: `dates_overlap(start_a: str, end_a: Optional[str], start_b: str, end_b: Optional[str]) -> Optional[Tuple[str, Optional[str]]]`, `derive_unit_mate_relationships(military_service: List[Dict[str, Any]]) -> List[Dict[str, Any]]`. Each `military_service` item needs keys `resident_id`, `garrison_building_id`, `start_date`, `end_date` (nullable).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_relationships_overlap.py
from town_relationships.overlap import dates_overlap


def test_overlapping_ranges_return_the_intersection():
    assert dates_overlap("1300-01-01", "1300-06-01", "1300-03-01", "1300-09-01") == ("1300-03-01", "1300-06-01")


def test_non_overlapping_ranges_return_none():
    assert dates_overlap("1290-01-01", "1291-01-01", "1300-01-01", "1301-01-01") is None


def test_open_ended_range_treated_as_ongoing():
    assert dates_overlap("1300-01-01", None, "1300-06-01", "1300-12-01") == ("1300-06-01", "1300-12-01")


def test_both_open_ended_has_no_overlap_end():
    assert dates_overlap("1300-01-01", None, "1300-06-01", None) == ("1300-06-01", None)
```

```python
# tests/test_relationships_military.py
import json

from town_relationships.military import derive_unit_mate_relationships


def test_overlapping_service_at_the_same_garrison_are_unit_mates():
    military_service = [
        {"resident_id": 1, "garrison_building_id": 5, "start_date": "1300-01-01", "end_date": "1300-06-01"},
        {"resident_id": 2, "garrison_building_id": 5, "start_date": "1300-03-01", "end_date": None},
    ]
    relationships = derive_unit_mate_relationships(military_service)
    assert len(relationships) == 1
    row = relationships[0]
    assert (row["resident_a_id"], row["resident_b_id"]) == (1, 2)
    assert json.loads(row["detail"]) == {"overlap_start": "1300-03-01", "overlap_end": "1300-06-01"}


def test_non_overlapping_service_at_the_same_garrison_are_not_unit_mates():
    military_service = [
        {"resident_id": 1, "garrison_building_id": 5, "start_date": "1290-01-01", "end_date": "1291-01-01"},
        {"resident_id": 2, "garrison_building_id": 5, "start_date": "1300-01-01", "end_date": None},
    ]
    assert derive_unit_mate_relationships(military_service) == []


def test_overlapping_service_at_different_garrisons_are_not_unit_mates():
    military_service = [
        {"resident_id": 1, "garrison_building_id": 5, "start_date": "1300-01-01", "end_date": None},
        {"resident_id": 2, "garrison_building_id": 6, "start_date": "1300-01-01", "end_date": None},
    ]
    assert derive_unit_mate_relationships(military_service) == []


def test_two_still_serving_unit_mates_have_no_overlap_end():
    military_service = [
        {"resident_id": 1, "garrison_building_id": 5, "start_date": "1300-01-01", "end_date": None},
        {"resident_id": 2, "garrison_building_id": 5, "start_date": "1300-02-01", "end_date": None},
    ]
    relationships = derive_unit_mate_relationships(military_service)
    detail = json.loads(relationships[0]["detail"])
    assert detail["overlap_end"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_relationships_overlap.py tests/test_relationships_military.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_relationships.overlap'`

- [ ] **Step 3: Write the implementation**

```python
# town_relationships/overlap.py
from typing import Optional, Tuple

FAR_FUTURE_DATE = "9999-12-31"


def dates_overlap(
    start_a: str, end_a: Optional[str], start_b: str, end_b: Optional[str]
) -> Optional[Tuple[str, Optional[str]]]:
    effective_end_a = end_a or FAR_FUTURE_DATE
    effective_end_b = end_b or FAR_FUTURE_DATE
    if start_a > effective_end_b or start_b > effective_end_a:
        return None
    overlap_start = max(start_a, start_b)
    overlap_end_raw = min(effective_end_a, effective_end_b)
    overlap_end = None if overlap_end_raw == FAR_FUTURE_DATE else overlap_end_raw
    return overlap_start, overlap_end
```

```python
# town_relationships/military.py
import json
from typing import Any, Dict, List

from town_relationships.overlap import dates_overlap
from town_relationships.pairs import canonical_pair


def derive_unit_mate_relationships(military_service: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_garrison: Dict[int, List[Dict[str, Any]]] = {}
    for record in military_service:
        by_garrison.setdefault(record["garrison_building_id"], []).append(record)

    relationships: List[Dict[str, Any]] = []
    seen_pairs = set()
    for records in by_garrison.values():
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                a, b = records[i], records[j]
                overlap = dates_overlap(a["start_date"], a["end_date"], b["start_date"], b["end_date"])
                if overlap is None:
                    continue
                lo, hi = sorted((a["resident_id"], b["resident_id"]))
                if (lo, hi) in seen_pairs:
                    continue
                seen_pairs.add((lo, hi))
                overlap_start, overlap_end = overlap
                detail = json.dumps({"overlap_start": overlap_start, "overlap_end": overlap_end})
                relationships.append(canonical_pair(a["resident_id"], b["resident_id"], "unit_mate", detail))
    return relationships
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_relationships_overlap.py tests/test_relationships_military.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_relationships/overlap.py town_relationships/military.py tests/test_relationships_overlap.py tests/test_relationships_military.py
git commit -m "feat: derive unit_mate relationships from overlapping garrison service"
```

---

## Task 6: Classmate relationships

**Files:**
- Create: `town_relationships/school.py`
- Test: `tests/test_relationships_school.py`

**Interfaces:**
- Consumes: `town_relationships.overlap.dates_overlap`, `town_relationships.pairs.canonical_pair`
- Produces: `derive_classmate_relationships(school_enrollments: List[Dict[str, Any]]) -> List[Dict[str, Any]]`. Each `school_enrollments` item needs keys `resident_id`, `school_building_id`, `start_date`, `end_date` (nullable).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_relationships_school.py
import json

from town_relationships.school import derive_classmate_relationships


def test_overlapping_enrollment_at_the_same_school_are_classmates():
    school_enrollments = [
        {"resident_id": 1, "school_building_id": 21, "start_date": "1300-09-01", "end_date": "1301-06-01"},
        {"resident_id": 2, "school_building_id": 21, "start_date": "1300-09-01", "end_date": None},
    ]
    relationships = derive_classmate_relationships(school_enrollments)
    assert len(relationships) == 1
    row = relationships[0]
    assert (row["resident_a_id"], row["resident_b_id"]) == (1, 2)
    assert row["relationship_type"] == "classmate"
    assert json.loads(row["detail"]) == {"overlap_start": "1300-09-01", "overlap_end": "1301-06-01"}


def test_non_overlapping_enrollment_at_the_same_school_are_not_classmates():
    school_enrollments = [
        {"resident_id": 1, "school_building_id": 21, "start_date": "1290-09-01", "end_date": "1291-06-01"},
        {"resident_id": 2, "school_building_id": 21, "start_date": "1300-09-01", "end_date": None},
    ]
    assert derive_classmate_relationships(school_enrollments) == []


def test_overlapping_enrollment_at_different_schools_are_not_classmates():
    school_enrollments = [
        {"resident_id": 1, "school_building_id": 21, "start_date": "1300-09-01", "end_date": None},
        {"resident_id": 2, "school_building_id": 22, "start_date": "1300-09-01", "end_date": None},
    ]
    assert derive_classmate_relationships(school_enrollments) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_relationships_school.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_relationships.school'`

- [ ] **Step 3: Write the implementation**

```python
# town_relationships/school.py
import json
from typing import Any, Dict, List

from town_relationships.overlap import dates_overlap
from town_relationships.pairs import canonical_pair


def derive_classmate_relationships(school_enrollments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_school: Dict[int, List[Dict[str, Any]]] = {}
    for record in school_enrollments:
        by_school.setdefault(record["school_building_id"], []).append(record)

    relationships: List[Dict[str, Any]] = []
    seen_pairs = set()
    for records in by_school.values():
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                a, b = records[i], records[j]
                overlap = dates_overlap(a["start_date"], a["end_date"], b["start_date"], b["end_date"])
                if overlap is None:
                    continue
                lo, hi = sorted((a["resident_id"], b["resident_id"]))
                if (lo, hi) in seen_pairs:
                    continue
                seen_pairs.add((lo, hi))
                overlap_start, overlap_end = overlap
                detail = json.dumps({"overlap_start": overlap_start, "overlap_end": overlap_end})
                relationships.append(canonical_pair(a["resident_id"], b["resident_id"], "classmate", detail))
    return relationships
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_relationships_school.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_relationships/school.py tests/test_relationships_school.py
git commit -m "feat: derive classmate relationships from overlapping school enrollment"
```

---

## Task 7: Shop relationships (customer scoring)

**Files:**
- Create: `town_relationships/shops.py`
- Test: `tests/test_relationships_shops.py`

**Interfaces:**
- Consumes: `town_shaper.geometry.distance`
- Produces: `derive_shop_relationships(residents: List[Dict[str, Any]], purchases: List[Dict[str, Any]], buildings: List[Dict[str, Any]]) -> List[Dict[str, Any]]`, `STAPLE_CATEGORIES`, `LUXURY_CATEGORIES`, `TOOLS_CATEGORIES`, `POOR_LUXURY_MULTIPLIER`. Each `residents` item needs keys `id`, `household_id`, `ses`, `occupation` (nullable), `home_building_id` (nullable). Each `purchases` item needs keys `resident_id`, `shop_building_id`, `total_price`, `category`. Each `buildings` item needs keys `id`, `x`, `y`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_relationships_shops.py
from town_relationships.shops import derive_shop_relationships

BUILDINGS = [{"id": 1, "x": 0.0, "y": 0.0}, {"id": 10, "x": 3.0, "y": 4.0}, {"id": 11, "x": 0.0, "y": 0.0}]


def _resident(resident_id, household_id, ses="poor", occupation=None, home_building_id=1):
    return {
        "id": resident_id, "household_id": household_id, "ses": ses,
        "occupation": occupation, "home_building_id": home_building_id,
    }


def _purchase(resident_id, shop_building_id, total_price, category):
    return {
        "resident_id": resident_id, "shop_building_id": shop_building_id,
        "total_price": total_price, "category": category,
    }


def test_a_single_purchase_produces_a_customer_row_marked_primary():
    residents = [_resident(1, 100)]
    purchases = [_purchase(1, 10, 2.0, "food")]
    relationships = derive_shop_relationships(residents, purchases, BUILDINGS)
    assert len(relationships) == 1
    row = relationships[0]
    assert row["resident_id"] == 1
    assert row["shop_building_id"] == 10
    assert row["purchase_count"] == 1
    assert row["total_spent"] == 2.0
    assert row["distance"] == 5.0
    assert row["is_primary"] == 1


def test_resident_with_no_purchases_produces_no_rows():
    residents = [_resident(1, 100)]
    assert derive_shop_relationships(residents, [], BUILDINGS) == []


def test_closer_shop_scores_higher_than_farther_shop_for_equal_spend():
    residents = [_resident(1, 100)]
    purchases = [_purchase(1, 10, 5.0, "food"), _purchase(1, 11, 5.0, "food")]
    relationships = derive_shop_relationships(residents, purchases, BUILDINGS)
    by_shop = {r["shop_building_id"]: r for r in relationships}
    assert by_shop[11]["customer_score"] > by_shop[10]["customer_score"]
    assert by_shop[11]["is_primary"] == 1
    assert by_shop[10]["is_primary"] == 0


def test_rich_household_gets_a_higher_luxury_need_score_than_poor():
    rich = [_resident(1, 100, ses="rich")]
    poor = [_resident(2, 200, ses="poor")]
    rich_row = derive_shop_relationships(rich, [_purchase(1, 10, 10.0, "luxury")], BUILDINGS)[0]
    poor_row = derive_shop_relationships(poor, [_purchase(2, 10, 10.0, "luxury")], BUILDINGS)[0]
    assert rich_row["need_score"] > poor_row["need_score"]


def test_tools_need_weight_scales_with_working_adults_not_household_size():
    residents = [
        _resident(1, 100, occupation="smith"), _resident(2, 100, occupation=None),
        _resident(3, 100, occupation="mason"),
    ]
    purchases = [_purchase(1, 10, 10.0, "tools")]
    row = derive_shop_relationships(residents, purchases, BUILDINGS)[0]
    # Household size is 3, but only residents 1 and 3 have an occupation.
    assert row["need_score"] == 10.0 * 2


def test_resident_with_no_home_building_is_skipped():
    residents = [_resident(1, 100, home_building_id=None)]
    purchases = [_purchase(1, 10, 5.0, "food")]
    assert derive_shop_relationships(residents, purchases, BUILDINGS) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_relationships_shops.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_relationships.shops'`

- [ ] **Step 3: Write the implementation**

```python
# town_relationships/shops.py
from typing import Any, Dict, List, Tuple

from town_shaper.geometry import distance

STAPLE_CATEGORIES = {"food", "drink", "household", "clothing"}
LUXURY_CATEGORIES = {"luxury"}
TOOLS_CATEGORIES = {"tools"}
POOR_LUXURY_MULTIPLIER = 0.1


def _household_stats(residents: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    stats: Dict[int, Dict[str, Any]] = {}
    for resident in residents:
        household_id = resident["household_id"]
        entry = stats.setdefault(household_id, {"size": 0, "working_adults": 0, "ses": resident["ses"]})
        entry["size"] += 1
        if resident.get("occupation") is not None:
            entry["working_adults"] += 1
    return stats


def _need_weight(stats: Dict[str, Any], category: str) -> float:
    if category in STAPLE_CATEGORIES:
        return float(stats["size"])
    if category in LUXURY_CATEGORIES:
        multiplier = 1.0 if stats["ses"] == "rich" else POOR_LUXURY_MULTIPLIER
        return stats["size"] * multiplier
    if category in TOOLS_CATEGORIES:
        return float(stats["working_adults"])
    return 0.0


def derive_shop_relationships(
    residents: List[Dict[str, Any]], purchases: List[Dict[str, Any]], buildings: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    household_stats = _household_stats(residents)
    household_by_resident = {r["id"]: r["household_id"] for r in residents}
    home_building_by_resident = {
        r["id"]: r["home_building_id"] for r in residents if r.get("home_building_id") is not None
    }
    building_coords = {b["id"]: (b["x"], b["y"]) for b in buildings}

    aggregated: Dict[Tuple[int, int], Dict[str, float]] = {}
    for purchase in purchases:
        resident_id = purchase["resident_id"]
        if resident_id not in home_building_by_resident:
            continue
        key = (resident_id, purchase["shop_building_id"])
        entry = aggregated.setdefault(key, {"purchase_count": 0, "total_spent": 0.0, "weighted_spend": 0.0})
        entry["purchase_count"] += 1
        entry["total_spent"] += purchase["total_price"]
        stats = household_stats[household_by_resident[resident_id]]
        entry["weighted_spend"] += purchase["total_price"] * _need_weight(stats, purchase["category"])

    rows_by_resident: Dict[int, List[Dict[str, Any]]] = {}
    best_by_resident: Dict[int, Tuple[float, int]] = {}

    for (resident_id, shop_building_id), entry in aggregated.items():
        home_coords = building_coords[home_building_by_resident[resident_id]]
        shop_coords = building_coords[shop_building_id]
        dist = distance(home_coords, shop_coords)
        need_score = entry["weighted_spend"]
        customer_score = need_score / (1 + dist)

        row = {
            "resident_id": resident_id,
            "shop_building_id": shop_building_id,
            "purchase_count": entry["purchase_count"],
            "total_spent": entry["total_spent"],
            "distance": dist,
            "need_score": need_score,
            "customer_score": customer_score,
            "is_primary": 0,
        }
        rows_by_resident.setdefault(resident_id, []).append(row)

        current_best = best_by_resident.get(resident_id)
        if current_best is None or customer_score > current_best[0] or (
            customer_score == current_best[0] and shop_building_id < current_best[1]
        ):
            best_by_resident[resident_id] = (customer_score, shop_building_id)

    relationships: List[Dict[str, Any]] = []
    for resident_id, rows in rows_by_resident.items():
        _, best_shop = best_by_resident[resident_id]
        for row in rows:
            row["is_primary"] = 1 if row["shop_building_id"] == best_shop else 0
            relationships.append(row)

    return relationships
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_relationships_shops.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_relationships/shops.py tests/test_relationships_shops.py
git commit -m "feat: derive shop_relationships scored by need and distance"
```

---

## Task 8: Orchestrator (derive_relationships end-to-end)

**Note beyond the spec's literal wording:** the spec's Scope section writes the entry point as `derive_relationships(db_path: str) -> None`, but its Data Model section separately requires family derivation to use "the same [reference_date] the town database was generated with" — which isn't possible without exposing it. Adding an optional `reference_date` kwarg (defaulting to `town_db`'s own `DEFAULT_YEAR_START`) is the natural, backward-compatible fix needed to actually implement that requirement, not a scope change.

**Files:**
- Create: `town_relationships/generate.py`
- Test: `tests/test_relationships_generate.py`

**Interfaces:**
- Consumes: `town_db.schema.connect`, `town_db.generate.DEFAULT_YEAR_START`, `town_relationships.schema.create_relationships_schema`, and every `derive_*` function from Tasks 2–7
- Produces: `derive_relationships(db_path: str, reference_date: date = DEFAULT_YEAR_START) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_relationships_generate.py
from town_db.schema import connect, create_schema

from town_relationships.generate import derive_relationships


def _build_minimal_town(db_path):
    conn = connect(db_path)
    create_schema(conn)

    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'residential', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'residential', 'house', 0.0, 0.0, 6)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (2, 1, 'residential', 'house', 1.0, 0.0, 6)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (10, 1, 'commercial', 'shop', 3.0, 4.0, 0)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (20, 1, 'civic', 'garrison', 0.0, 0.0, 0)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (21, 1, 'civic', 'school', 0.0, 0.0, 0)"
    )

    conn.execute("INSERT INTO households (id, family_name, race) VALUES (100, 'Smith', 'human')")
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (200, 'Baker', 'human')")

    def resident(household_id, first_name, gender, birth_date, ses, home_building_id, workplace_building_id, occupation):
        cursor = conn.execute(
            "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, ses, "
            "is_noble, home_building_id, workplace_building_id, occupation) "
            "VALUES (?, ?, 'Smith', ?, 'human', ?, ?, 0, ?, ?, ?)",
            (household_id, first_name, gender, birth_date, ses, home_building_id, workplace_building_id, occupation),
        )
        return cursor.lastrowid

    father = resident(100, "Tom", "male", "1260-01-01", "poor", 1, 30, "smith")
    mother = resident(100, "Ann", "female", "1262-01-01", "poor", 1, None, None)
    child = resident(100, "Lil", "female", "1295-01-01", "poor", 1, None, None)
    neighbor = resident(200, "Bob", "male", "1265-01-01", "poor", 2, 30, "mason")

    conn.execute(
        "INSERT INTO births (child_resident_id, mother_resident_id, father_resident_id, birth_date, "
        "reported_by_building_id) VALUES (?, ?, ?, '1295-01-01', 20)",
        (child, mother, father),
    )

    good_id = conn.execute(
        "INSERT INTO goods (name, category, typical_price, sv) VALUES ('bread', 'food', 0.05, 800)"
    ).lastrowid
    conn.execute(
        "INSERT INTO purchases (resident_id, shop_building_id, good_id, quantity, unit_price, total_price, "
        "purchase_date) VALUES (?, 10, ?, 2, 0.05, 0.10, '1300-02-01')",
        (father, good_id),
    )

    conn.execute(
        "INSERT INTO military_service (resident_id, garrison_building_id, rank, start_date, end_date) "
        "VALUES (?, 20, 'soldier', '1300-01-01', NULL)",
        (father,),
    )
    conn.execute(
        "INSERT INTO military_service (resident_id, garrison_building_id, rank, start_date, end_date) "
        "VALUES (?, 20, 'soldier', '1300-02-01', NULL)",
        (neighbor,),
    )

    conn.commit()
    conn.close()
    return {"father": father, "mother": mother, "child": child, "neighbor": neighbor}


def test_derive_relationships_populates_both_tables_end_to_end(tmp_path):
    db_path = str(tmp_path / "town.db")
    ids = _build_minimal_town(db_path)

    derive_relationships(db_path)

    conn = connect(db_path)
    relationship_rows = conn.execute(
        "SELECT resident_a_id, resident_b_id, relationship_type FROM relationships"
    ).fetchall()

    father, mother, child, neighbor = ids["father"], ids["mother"], ids["child"], ids["neighbor"]

    def types_for(resident_x, resident_y):
        lo, hi = sorted((resident_x, resident_y))
        return {t for a, b, t in relationship_rows if (a, b) == (lo, hi)}

    assert types_for(father, mother) == {"spouse"}
    assert types_for(father, child) == {"parent"}
    assert types_for(mother, child) == {"parent"}
    assert types_for(father, neighbor) == {"coworker", "neighbor", "unit_mate"}

    shop_rows = conn.execute(
        "SELECT resident_id, shop_building_id, is_primary FROM shop_relationships"
    ).fetchall()
    assert shop_rows == [(father, 10, 1)]

    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_derive_relationships_is_deterministic_across_separate_databases(tmp_path):
    db_path_a = str(tmp_path / "town_a.db")
    db_path_b = str(tmp_path / "town_b.db")
    _build_minimal_town(db_path_a)
    _build_minimal_town(db_path_b)

    derive_relationships(db_path_a)
    derive_relationships(db_path_b)

    conn_a = connect(db_path_a)
    conn_b = connect(db_path_b)
    rows_a = sorted(conn_a.execute(
        "SELECT resident_a_id, resident_b_id, relationship_type, detail FROM relationships"
    ).fetchall())
    rows_b = sorted(conn_b.execute(
        "SELECT resident_a_id, resident_b_id, relationship_type, detail FROM relationships"
    ).fetchall())
    assert rows_a == rows_b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_relationships_generate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_relationships.generate'`

- [ ] **Step 3: Write the implementation**

```python
# town_relationships/generate.py
import sqlite3
from datetime import date
from typing import Any, Dict, List

from town_db.generate import DEFAULT_YEAR_START
from town_db.schema import connect

from town_relationships.family import derive_family_relationships
from town_relationships.military import derive_unit_mate_relationships
from town_relationships.neighbors import derive_neighbor_relationships
from town_relationships.schema import create_relationships_schema
from town_relationships.school import derive_classmate_relationships
from town_relationships.shops import derive_shop_relationships
from town_relationships.work import derive_coworker_relationships


def derive_relationships(db_path: str, reference_date: date = DEFAULT_YEAR_START) -> None:
    conn = connect(db_path)
    create_relationships_schema(conn)

    residents = _fetch_residents(conn)
    buildings = _fetch_buildings(conn)
    births = _fetch_births(conn)
    military_service = _fetch_military_service(conn)
    school_enrollments = _fetch_school_enrollments(conn)
    purchases = _fetch_purchases(conn)

    relationship_rows: List[Dict[str, Any]] = []
    relationship_rows += derive_family_relationships(residents, births, reference_date)
    relationship_rows += derive_coworker_relationships(residents)
    relationship_rows += derive_neighbor_relationships(residents, buildings)
    relationship_rows += derive_unit_mate_relationships(military_service)
    relationship_rows += derive_classmate_relationships(school_enrollments)

    for row in relationship_rows:
        conn.execute(
            "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type, detail) "
            "VALUES (?, ?, ?, ?)",
            (row["resident_a_id"], row["resident_b_id"], row["relationship_type"], row["detail"]),
        )

    for row in derive_shop_relationships(residents, purchases, buildings):
        conn.execute(
            "INSERT INTO shop_relationships (resident_id, shop_building_id, purchase_count, total_spent, "
            "distance, need_score, customer_score, is_primary) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (row["resident_id"], row["shop_building_id"], row["purchase_count"], row["total_spent"],
             row["distance"], row["need_score"], row["customer_score"], row["is_primary"]),
        )

    conn.commit()
    conn.close()


def _fetch_residents(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    columns = ["id", "household_id", "home_building_id", "workplace_building_id", "occupation", "birth_date", "ses"]
    rows = conn.execute(f"SELECT {', '.join(columns)} FROM residents").fetchall()
    return [dict(zip(columns, row)) for row in rows]


def _fetch_buildings(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT id, x, y FROM buildings").fetchall()
    return [{"id": r[0], "x": r[1], "y": r[2]} for r in rows]


def _fetch_births(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT child_resident_id, mother_resident_id, father_resident_id FROM births"
    ).fetchall()
    return [{"child_resident_id": r[0], "mother_resident_id": r[1], "father_resident_id": r[2]} for r in rows]


def _fetch_military_service(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT resident_id, garrison_building_id, start_date, end_date FROM military_service"
    ).fetchall()
    return [{"resident_id": r[0], "garrison_building_id": r[1], "start_date": r[2], "end_date": r[3]} for r in rows]


def _fetch_school_enrollments(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT resident_id, school_building_id, start_date, end_date FROM school_enrollments"
    ).fetchall()
    return [{"resident_id": r[0], "school_building_id": r[1], "start_date": r[2], "end_date": r[3]} for r in rows]


def _fetch_purchases(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT p.resident_id, p.shop_building_id, p.total_price, g.category "
        "FROM purchases p JOIN goods g ON g.id = p.good_id"
    ).fetchall()
    return [{"resident_id": r[0], "shop_building_id": r[1], "total_price": r[2], "category": r[3]} for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_relationships_generate.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -v -k "not (test_assignment or test_db_generate or test_districts or test_generate)"`
Expected: PASS for every test that doesn't transitively import `town_shaper.generate`/`scipy` — see this session's note on the pre-existing numpy DLL block in this environment. If `scipy`/`numpy.random` import cleanly in the execution environment, just run `python -m pytest tests/ -v` instead and expect a full pass.

- [ ] **Step 6: Commit**

```bash
git add town_relationships/generate.py tests/test_relationships_generate.py
git commit -m "feat: add derive_relationships orchestrator tying town_relationships together"
```
