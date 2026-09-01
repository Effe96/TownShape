# Town Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, read-only web app that loads one generated town's SQLite DB and lets you explore it — a zoomable/pannable map with clickable buildings, and a searchable resident list with bidirectional building↔resident navigation.

**Architecture:** A Flask backend (`town_viewer/app.py`) exposes a small read-only JSON API over the existing `town_db`/`town_relationships` SQLite tables (`town_viewer/queries.py`), and serves a static vanilla-JS/HTML5-canvas frontend (`town_viewer/static/`). Districts, buildings, and water load once via `/api/map` (bounded ~1-2k rows, fine to hold client-side); residents (5,000+ in a real town) are never loaded in full — the sidebar always goes through paginated, search-filtered `/api/residents` calls. Buildings have no stored footprint (only `x, y`), so the map draws a placeholder rectangle per building: 10 world units square for the eight large-landmark types called out in `town_db/render.py`'s `LANDMARK_BUILDING_TYPES` (temple, town_hall, school, university, garrison, guard_post, arcane_shop, harbormaster_office), 5 world units square for everything else — including `tavern`/`shop`, which `render.py` also colors distinctly but deliberately keeps small since there are many of them — sized against the ~25-unit average building spacing measured in `my_town.db`. No level-of-detail/clustering: canvas comfortably draws 1,000+ rects a frame, so all buildings render at every zoom level; revisit only if real testing shows jank.

**Tech Stack:** Python (Flask, `sqlite3` stdlib) backend; vanilla JS + HTML5 canvas frontend, no framework; pytest for backend tests.

**Spec:** [docs/visual-interface-requirements.md](../../visual-interface-requirements.md) (companion Brief: [docs/visual-interface-brief.md](../../visual-interface-brief.md))

## Global Constraints

- Read-only: no route or query in this plan writes to the DB, or calls `town_db/edits.py` or `town_db/simulation.py`.
- Single town, single session: the viewer is launched against one DB file path; no multi-town gallery, no persistence beyond that file.
- No time-stepping: the DB is a fixed snapshot. `relationships`/`shop_relationships` may be stale after edits per `town_db/edits.py`'s documented gotcha — this viewer displays them as-is, no staleness detection.
- No real building geometry: buildings only have `x, y` in the schema — rectangle sizes drawn by the frontend are a fixed-per-type approximation, not physical footprints.
- Not hosted, not multi-user, no authentication.
- No print/export of a stylized fantasy-style map.

---

## File Structure

- Create: `town_viewer/__init__.py` — empty, marks the package.
- Create: `town_viewer/queries.py` — read-only query functions over a `sqlite3.Connection`, returning plain dicts/lists (JSON-serializable).
- Create: `town_viewer/app.py` — Flask app factory (`create_app(db_path)`) wiring `queries.py` to HTTP routes and serving the static frontend.
- Create: `town_viewer/static/index.html` — page markup: canvas + sidebar (search box, resident list, detail panel).
- Create: `town_viewer/static/style.css` — layout and visual styling.
- Create: `town_viewer/static/app.js` — map rendering (load, pan, zoom, click-to-select), resident search/list, detail panels, bidirectional selection.
- Create: `scripts/serve_town_viewer.py` — CLI entry point, mirrors `scripts/render_town.py`'s `<db_path>` argument pattern.
- Create: `tests/town_viewer_fixtures.py` — shared test helper `build_full_town(db_path)` building a small but complete town (districts, buildings, water, households, residents, relationships, shop_relationships).
- Create: `tests/test_viewer_queries.py` — pytest tests for `town_viewer/queries.py`.
- Create: `tests/test_viewer_app.py` — pytest tests for `town_viewer/app.py` using Flask's test client.
- Modify: `requirements.txt` — add `flask`.

---

### Task 1: Query layer — map data

**Files:**
- Modify: `requirements.txt`
- Create: `town_viewer/__init__.py`
- Create: `town_viewer/queries.py`
- Test: `tests/test_viewer_queries.py`

**Interfaces:**
- Consumes: `town_db.schema.connect(db_path) -> sqlite3.Connection`, `town_db.schema.create_schema(conn)` (existing).
- Produces: `get_map_data(conn: sqlite3.Connection) -> dict` with keys `"districts"`, `"buildings"`, `"water_features"` — each a list of dicts. Used by Task 5's `/api/map` route and Task 6's frontend load.

- [ ] **Step 1: Add Flask to requirements.txt**

Add a line to `requirements.txt`:

```
flask>=3.0
```

Install it:

```bash
pip install -r requirements.txt
```

- [ ] **Step 2: Create the package**

Create `town_viewer/__init__.py` (empty file).

- [ ] **Step 3: Write the failing test**

Create `tests/test_viewer_queries.py`:

```python
import json

from town_db.schema import connect, create_schema
from town_viewer.queries import get_map_data


def _build_minimal_map(db_path):
    conn = connect(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', ?)",
        (json.dumps([[[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]]]),),
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'temple', 10.0, 10.0, 0)"
    )
    conn.execute(
        "INSERT INTO water_features (id, kind, polygon) VALUES (1, 'river', ?)",
        (json.dumps([[[8.0, -2.0], [12.0, -2.0], [12.0, 22.0], [8.0, 22.0]]]),),
    )
    conn.commit()
    conn.close()


def test_get_map_data_returns_districts_buildings_and_water(tmp_path):
    db_path = str(tmp_path / "town.db")
    _build_minimal_map(db_path)

    conn = connect(db_path)
    data = get_map_data(conn)
    conn.close()

    assert data["districts"] == [
        {"id": 1, "zone_type": "civic", "polygon": [[[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]]]}
    ]
    assert data["buildings"] == [
        {"id": 1, "district_id": 1, "zone_type": "civic", "building_type": "temple", "x": 10.0, "y": 10.0}
    ]
    assert data["water_features"] == [
        {"id": 1, "kind": "river", "polygon": [[[8.0, -2.0], [12.0, -2.0], [12.0, 22.0], [8.0, 22.0]]]}
    ]


def test_get_map_data_handles_a_town_with_no_water(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'merchant', ?)",
        (json.dumps([[[0.0, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 5.0]]]),),
    )
    conn.commit()
    conn.close()

    conn = connect(db_path)
    data = get_map_data(conn)
    conn.close()

    assert data["buildings"] == []
    assert data["water_features"] == []
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_viewer_queries.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_viewer.queries'` (or `ImportError: cannot import name 'get_map_data'`).

- [ ] **Step 5: Implement `get_map_data`**

Create `town_viewer/queries.py`:

```python
import json
import sqlite3
from typing import Any, Dict


def get_map_data(conn: sqlite3.Connection) -> Dict[str, Any]:
    districts = [
        {"id": row[0], "zone_type": row[1], "polygon": json.loads(row[2])}
        for row in conn.execute("SELECT id, zone_type, polygon FROM districts")
    ]
    buildings = [
        {"id": row[0], "district_id": row[1], "zone_type": row[2], "building_type": row[3], "x": row[4], "y": row[5]}
        for row in conn.execute(
            "SELECT id, district_id, zone_type, building_type, x, y FROM buildings"
        )
    ]
    water_features = [
        {"id": row[0], "kind": row[1], "polygon": json.loads(row[2])}
        for row in conn.execute("SELECT id, kind, polygon FROM water_features")
    ]
    return {"districts": districts, "buildings": buildings, "water_features": water_features}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_viewer_queries.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add requirements.txt town_viewer/__init__.py town_viewer/queries.py tests/test_viewer_queries.py
git commit -m "feat: add town_viewer package with map-data query"
```

---

### Task 2: Query layer — building detail

**Files:**
- Create: `tests/town_viewer_fixtures.py`
- Modify: `town_viewer/queries.py`
- Modify: `tests/test_viewer_queries.py`

**Interfaces:**
- Consumes: `town_relationships.schema.create_relationships_schema(conn)` (existing).
- Produces: `build_full_town(db_path: str) -> None` (test fixture, reused by Tasks 3-5). `get_building_detail(conn, building_id: int) -> Optional[dict]` with keys `"id", "district_id", "zone_type", "building_type", "x", "y", "capacity", "residents"` where `"residents"` is a list of `{"id", "first_name", "last_name", "lives_here", "works_here"}`. Returns `None` if the building doesn't exist. Used by Task 5's `/api/buildings/<id>` route.

- [ ] **Step 1: Write the shared fixture**

Create `tests/town_viewer_fixtures.py`:

```python
import json

from town_db.schema import connect, create_schema
from town_relationships.schema import create_relationships_schema


def build_full_town(db_path: str) -> None:
    """A small but complete town: 2 districts, 4 buildings, 1 household of
    4 (2 parents + 2 children), family relationships, and a shop_relationship
    for one resident."""
    conn = connect(db_path)
    create_schema(conn)
    create_relationships_schema(conn)

    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', ?)",
        (json.dumps([[[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]]]),),
    )
    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (2, 'poor_residential', ?)",
        (json.dumps([[[20.0, 0.0], [40.0, 0.0], [40.0, 20.0], [20.0, 20.0]]]),),
    )

    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'temple', 10.0, 10.0, 0)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (2, 1, 'civic', 'town_hall', 15.0, 5.0, 5)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (3, 2, 'poor_residential', 'shop', 25.0, 10.0, 0)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (4, 2, 'poor_residential', 'residence', 30.0, 15.0, 6)"
    )

    conn.execute(
        "INSERT INTO households (id, family_name, race, wealth) VALUES (1, 'Stonebrook', 'human', 120.0)"
    )

    # id 1 Mira (parent, works at the shop), id 2 Tomas (parent, works at town hall),
    # id 3 Elin and id 4 Rian (children, siblings, live at home with no job).
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, "
        "ses, home_building_id, workplace_building_id, occupation) VALUES "
        "(1, 1, 'Mira', 'Stonebrook', 'F', 'human', '1288-01-01', 'rich', 4, 3, 'merchant')"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, "
        "ses, home_building_id, workplace_building_id, occupation) VALUES "
        "(2, 1, 'Tomas', 'Stonebrook', 'M', 'human', '1286-05-10', 'rich', 4, 2, 'clerk')"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, "
        "ses, home_building_id, workplace_building_id, occupation) VALUES "
        "(3, 1, 'Elin', 'Stonebrook', 'F', 'human', '1315-03-01', 'rich', 4, NULL, NULL)"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, "
        "ses, home_building_id, workplace_building_id, occupation) VALUES "
        "(4, 1, 'Rian', 'Stonebrook', 'M', 'human', '1317-08-20', 'rich', 4, NULL, NULL)"
    )

    conn.execute(
        "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type, detail) "
        "VALUES (1, 2, 'spouse', NULL)"
    )
    conn.execute(
        "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type, detail) "
        "VALUES (1, 3, 'parent', NULL)"
    )
    conn.execute(
        "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type, detail) "
        "VALUES (2, 3, 'parent', NULL)"
    )
    conn.execute(
        "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type, detail) "
        "VALUES (1, 4, 'parent', NULL)"
    )
    conn.execute(
        "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type, detail) "
        "VALUES (2, 4, 'parent', NULL)"
    )
    conn.execute(
        "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type, detail) "
        "VALUES (3, 4, 'sibling', NULL)"
    )

    conn.execute(
        "INSERT INTO shop_relationships (resident_id, shop_building_id, purchase_count, total_spent, "
        "distance, need_score, customer_score, is_primary) VALUES (1, 3, 12, 340.5, 5.0, 0.8, 0.9, 1)"
    )

    conn.commit()
    conn.close()
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_viewer_queries.py`:

```python
from tests.town_viewer_fixtures import build_full_town
from town_viewer.queries import get_building_detail


def test_get_building_detail_lists_residents_who_live_and_work_there(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    building = get_building_detail(conn, 4)  # the residence, all 4 residents live here
    conn.close()

    assert building["id"] == 4
    assert building["building_type"] == "residence"
    assert building["capacity"] == 6
    residents_by_id = {r["id"]: r for r in building["residents"]}
    assert set(residents_by_id) == {1, 2, 3, 4}
    assert all(r["lives_here"] for r in residents_by_id.values())
    assert all(not r["works_here"] for r in residents_by_id.values())


def test_get_building_detail_flags_workers_not_residents(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    shop = get_building_detail(conn, 3)  # the shop, only Mira (id 1) works here
    conn.close()

    assert [r["id"] for r in shop["residents"]] == [1]
    assert shop["residents"][0]["lives_here"] is False
    assert shop["residents"][0]["works_here"] is True


def test_get_building_detail_returns_none_for_missing_building(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    result = get_building_detail(conn, 999)
    conn.close()

    assert result is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_viewer_queries.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_building_detail'`.

- [ ] **Step 4: Implement `get_building_detail`**

Append to `town_viewer/queries.py`:

```python
from typing import Optional


def get_building_detail(conn: sqlite3.Connection, building_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT id, district_id, zone_type, building_type, x, y, capacity FROM buildings WHERE id = ?",
        (building_id,),
    ).fetchone()
    if row is None:
        return None

    building = {
        "id": row[0], "district_id": row[1], "zone_type": row[2], "building_type": row[3],
        "x": row[4], "y": row[5], "capacity": row[6],
    }
    residents = [
        {
            "id": r[0], "first_name": r[1], "last_name": r[2],
            "lives_here": r[3] == building_id, "works_here": r[4] == building_id,
        }
        for r in conn.execute(
            "SELECT id, first_name, last_name, home_building_id, workplace_building_id "
            "FROM residents WHERE home_building_id = ? OR workplace_building_id = ? ORDER BY id",
            (building_id, building_id),
        )
    ]
    building["residents"] = residents
    return building
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_viewer_queries.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add tests/town_viewer_fixtures.py town_viewer/queries.py tests/test_viewer_queries.py
git commit -m "feat: add building-detail query and shared test town fixture"
```

---

### Task 3: Query layer — resident search

**Files:**
- Modify: `town_viewer/queries.py`
- Modify: `tests/test_viewer_queries.py`

**Interfaces:**
- Consumes: `build_full_town` (Task 2).
- Produces: `search_residents(conn, query: str = "", page: int = 1, page_size: int = 50) -> dict` with keys `"residents"` (list of `{"id", "first_name", "last_name", "occupation"}`), `"total"`, `"page"`, `"page_size"`. Used by Task 5's `/api/residents` route.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_viewer_queries.py`:

```python
from town_viewer.queries import search_residents


def test_search_residents_with_no_query_returns_all_paginated(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    result = search_residents(conn, page=1, page_size=2)
    conn.close()

    assert result["total"] == 4
    assert result["page"] == 1
    assert result["page_size"] == 2
    assert len(result["residents"]) == 2


def test_search_residents_filters_by_name_case_insensitively(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    result = search_residents(conn, query="mira")
    conn.close()

    assert result["total"] == 1
    assert result["residents"][0]["first_name"] == "Mira"


def test_search_residents_second_page_is_the_remainder(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    result = search_residents(conn, page=2, page_size=3)
    conn.close()

    assert result["total"] == 4
    assert len(result["residents"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_viewer_queries.py -v`
Expected: FAIL with `ImportError: cannot import name 'search_residents'`.

- [ ] **Step 3: Implement `search_residents`**

Append to `town_viewer/queries.py`:

```python
def search_residents(
    conn: sqlite3.Connection, query: str = "", page: int = 1, page_size: int = 50
) -> Dict[str, Any]:
    offset = (page - 1) * page_size
    like = f"%{query}%"
    total = conn.execute(
        "SELECT COUNT(*) FROM residents WHERE first_name LIKE ? OR last_name LIKE ?", (like, like)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT id, first_name, last_name, occupation FROM residents "
        "WHERE first_name LIKE ? OR last_name LIKE ? ORDER BY last_name, first_name LIMIT ? OFFSET ?",
        (like, like, page_size, offset),
    ).fetchall()
    residents = [{"id": r[0], "first_name": r[1], "last_name": r[2], "occupation": r[3]} for r in rows]
    return {"residents": residents, "total": total, "page": page, "page_size": page_size}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_viewer_queries.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add town_viewer/queries.py tests/test_viewer_queries.py
git commit -m "feat: add paginated resident search query"
```

---

### Task 4: Query layer — resident detail

**Files:**
- Modify: `town_viewer/queries.py`
- Modify: `tests/test_viewer_queries.py`

**Interfaces:**
- Consumes: `build_full_town` (Task 2).
- Produces: `get_resident_detail(conn, resident_id: int) -> Optional[dict]` with keys `"id", "household_id", "first_name", "last_name", "gender", "race", "birth_date", "death_date", "ses", "occupation", "home_building_id", "workplace_building_id", "household"` (dict: `{"id", "family_name", "race", "wealth"}`), `"relationships"` (list of `{"resident_id", "first_name", "last_name", "relationship_type", "role"}`, `role` is `"a"` or `"b"` — the subject's side of the stored pair, so `relationship_type == "parent"` with `role == "a"` means the subject is the parent), `"shopping"` (list of `{"shop_building_id", "purchase_count", "total_spent", "is_primary"}`). Returns `None` if the resident doesn't exist. Used by Task 5's `/api/residents/<id>` route.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_viewer_queries.py`:

```python
from town_viewer.queries import get_resident_detail


def test_get_resident_detail_includes_household_and_core_fields(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    mira = get_resident_detail(conn, 1)
    conn.close()

    assert mira["first_name"] == "Mira"
    assert mira["occupation"] == "merchant"
    assert mira["home_building_id"] == 4
    assert mira["workplace_building_id"] == 3
    assert mira["household"] == {"id": 1, "family_name": "Stonebrook", "race": "human", "wealth": 120.0}


def test_get_resident_detail_includes_relationships_both_directions(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    mira = get_resident_detail(conn, 1)  # stored as resident_a in all her relationship rows
    elin = get_resident_detail(conn, 3)  # stored as resident_b in her parent relationships
    conn.close()

    mira_types = {(r["resident_id"], r["relationship_type"], r["role"]) for r in mira["relationships"]}
    assert (2, "spouse", "a") in mira_types
    assert (3, "parent", "a") in mira_types
    assert (4, "parent", "a") in mira_types

    elin_types = {(r["resident_id"], r["relationship_type"], r["role"]) for r in elin["relationships"]}
    assert (1, "parent", "b") in elin_types
    assert (2, "parent", "b") in elin_types
    assert (4, "sibling", "a") in elin_types


def test_get_resident_detail_includes_shopping_history(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    mira = get_resident_detail(conn, 1)
    rian = get_resident_detail(conn, 4)
    conn.close()

    assert mira["shopping"] == [
        {"shop_building_id": 3, "purchase_count": 12, "total_spent": 340.5, "is_primary": True}
    ]
    assert rian["shopping"] == []


def test_get_resident_detail_returns_none_for_missing_resident(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    result = get_resident_detail(conn, 999)
    conn.close()

    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_viewer_queries.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_resident_detail'`.

- [ ] **Step 3: Implement `get_resident_detail`**

Append to `town_viewer/queries.py`:

```python
def get_resident_detail(conn: sqlite3.Connection, resident_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT id, household_id, first_name, last_name, gender, race, birth_date, death_date, "
        "ses, occupation, home_building_id, workplace_building_id FROM residents WHERE id = ?",
        (resident_id,),
    ).fetchone()
    if row is None:
        return None

    resident = {
        "id": row[0], "household_id": row[1], "first_name": row[2], "last_name": row[3],
        "gender": row[4], "race": row[5], "birth_date": row[6], "death_date": row[7],
        "ses": row[8], "occupation": row[9], "home_building_id": row[10], "workplace_building_id": row[11],
    }

    household_row = conn.execute(
        "SELECT id, family_name, race, wealth FROM households WHERE id = ?", (resident["household_id"],)
    ).fetchone()
    resident["household"] = {
        "id": household_row[0], "family_name": household_row[1],
        "race": household_row[2], "wealth": household_row[3],
    }

    relationship_rows = conn.execute(
        """
        SELECT resident_b_id, res.first_name, res.last_name, relationship_type, 'a'
        FROM relationships JOIN residents res ON res.id = relationships.resident_b_id
        WHERE resident_a_id = ?
        UNION ALL
        SELECT resident_a_id, res.first_name, res.last_name, relationship_type, 'b'
        FROM relationships JOIN residents res ON res.id = relationships.resident_a_id
        WHERE resident_b_id = ?
        """,
        (resident_id, resident_id),
    ).fetchall()
    resident["relationships"] = [
        {"resident_id": r[0], "first_name": r[1], "last_name": r[2], "relationship_type": r[3], "role": r[4]}
        for r in relationship_rows
    ]

    shopping_rows = conn.execute(
        "SELECT shop_building_id, purchase_count, total_spent, is_primary "
        "FROM shop_relationships WHERE resident_id = ? ORDER BY total_spent DESC",
        (resident_id,),
    ).fetchall()
    resident["shopping"] = [
        {
            "shop_building_id": r[0], "purchase_count": r[1],
            "total_spent": r[2], "is_primary": bool(r[3]),
        }
        for r in shopping_rows
    ]

    return resident
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_viewer_queries.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add town_viewer/queries.py tests/test_viewer_queries.py
git commit -m "feat: add resident-detail query with relationships and shopping history"
```

---

### Task 5: Flask app, API routes, and CLI entry point

**Files:**
- Create: `town_viewer/app.py`
- Create: `scripts/serve_town_viewer.py`
- Create: `town_viewer/static/index.html` (placeholder, replaced fully in Task 6)
- Test: `tests/test_viewer_app.py`

**Interfaces:**
- Consumes: `get_map_data`, `get_building_detail`, `search_residents`, `get_resident_detail` (Tasks 1-4), `town_db.schema.connect`.
- Produces: `create_app(db_path: str) -> flask.Flask` with routes `GET /`, `GET /api/map`, `GET /api/buildings/<int:id>`, `GET /api/residents?q=&page=`, `GET /api/residents/<int:id>`. Used by Task 6 onward (frontend calls these routes) and by `scripts/serve_town_viewer.py`.

- [ ] **Step 1: Write a minimal placeholder index page**

Create `town_viewer/static/index.html`:

```html
<!doctype html>
<html>
<head><title>Town Viewer</title></head>
<body><p>Town Viewer — under construction.</p></body>
</html>
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_viewer_app.py`:

```python
from tests.town_viewer_fixtures import build_full_town
from town_viewer.app import create_app


def _client(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)
    app = create_app(db_path)
    app.testing = True
    return app.test_client()


def test_index_serves_the_frontend_page(tmp_path):
    client = _client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert b"Town Viewer" in response.data


def test_map_endpoint_returns_districts_and_buildings(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/map")
    assert response.status_code == 200
    body = response.get_json()
    assert len(body["districts"]) == 2
    assert len(body["buildings"]) == 4


def test_building_endpoint_returns_detail(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/buildings/4")
    assert response.status_code == 200
    body = response.get_json()
    assert body["building_type"] == "residence"
    assert len(body["residents"]) == 4


def test_building_endpoint_404s_for_missing_building(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/buildings/999")
    assert response.status_code == 404


def test_residents_endpoint_searches_and_paginates(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/residents?q=stonebrook&page=1")
    assert response.status_code == 200
    body = response.get_json()
    assert body["total"] == 4
    assert len(body["residents"]) == 4


def test_resident_detail_endpoint_returns_full_profile(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/residents/1")
    assert response.status_code == 200
    body = response.get_json()
    assert body["first_name"] == "Mira"
    assert len(body["relationships"]) == 3
    assert len(body["shopping"]) == 1


def test_resident_detail_endpoint_404s_for_missing_resident(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/residents/999")
    assert response.status_code == 404
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_viewer_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'town_viewer.app'`.

- [ ] **Step 4: Implement the Flask app**

Create `town_viewer/app.py`:

```python
import os

from flask import Flask, jsonify, request, send_from_directory

from town_db.schema import connect
from town_viewer.queries import get_building_detail, get_map_data, get_resident_detail, search_residents

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def create_app(db_path: str) -> Flask:
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/api/map")
    def map_data():
        conn = connect(db_path)
        try:
            return jsonify(get_map_data(conn))
        finally:
            conn.close()

    @app.get("/api/buildings/<int:building_id>")
    def building_detail(building_id):
        conn = connect(db_path)
        try:
            data = get_building_detail(conn, building_id)
        finally:
            conn.close()
        if data is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(data)

    @app.get("/api/residents")
    def residents_list():
        query = request.args.get("q", "")
        page = int(request.args.get("page", 1))
        conn = connect(db_path)
        try:
            return jsonify(search_residents(conn, query, page))
        finally:
            conn.close()

    @app.get("/api/residents/<int:resident_id>")
    def resident_detail(resident_id):
        conn = connect(db_path)
        try:
            data = get_resident_detail(conn, resident_id)
        finally:
            conn.close()
        if data is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(data)

    return app
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_viewer_app.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Write the CLI entry point**

Create `scripts/serve_town_viewer.py`:

```python
"""Usage: python scripts/serve_town_viewer.py <db_path> [--port PORT]"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from town_viewer.app import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("db_path")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    app = create_app(args.db_path)
    print(f"Serving {args.db_path} at http://127.0.0.1:{args.port}")
    app.run(port=args.port)
```

- [ ] **Step 7: Manually verify the server runs**

Run: `python scripts/serve_town_viewer.py my_town.db`
Expected: prints the serving URL and stays running; visiting `http://127.0.0.1:5000/api/map` in a browser shows JSON with `districts`/`buildings`/`water_features` keys. Stop with Ctrl+C.

- [ ] **Step 8: Commit**

```bash
git add town_viewer/app.py town_viewer/static/index.html scripts/serve_town_viewer.py tests/test_viewer_app.py
git commit -m "feat: add Flask app with read-only town API and CLI entry point"
```

---

### Task 6: Frontend — map rendering with pan and zoom

**Files:**
- Modify: `town_viewer/static/index.html` (full replacement)
- Create: `town_viewer/static/style.css`
- Create: `town_viewer/static/app.js`

**Interfaces:**
- Consumes: `GET /api/map` (Task 5) → `{districts, buildings, water_features}`.
- Produces: global `mapData` (the fetched map JSON), `view` (`{scale, offsetX, offsetY}`), `worldToScreen(x, y)`, `screenToWorld(sx, sy)`, `draw()` — all defined on `window` scope in `app.js`, reused by Tasks 7-10.

- [ ] **Step 1: Replace the page markup**

Replace `town_viewer/static/index.html` in full:

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Town Viewer</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div id="app">
    <canvas id="map"></canvas>
    <div id="sidebar">
      <div id="search-panel">
        <input id="search-input" type="text" placeholder="Search residents by name...">
        <div id="resident-list"></div>
        <div id="pagination">
          <button id="prev-page">&laquo; Prev</button>
          <span id="page-info"></span>
          <button id="next-page">Next &raquo;</button>
        </div>
      </div>
      <div id="detail-panel"><p class="hint">Click a building or a resident to see details.</p></div>
    </div>
  </div>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write the stylesheet**

Create `town_viewer/static/style.css`:

```css
html, body { margin: 0; height: 100%; font-family: sans-serif; }
#app { display: flex; height: 100vh; }
#map { flex: 1; background: #eef2f5; cursor: grab; }
#map.dragging { cursor: grabbing; }
#sidebar {
  width: 340px;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #ccc;
  overflow: hidden;
}
#search-panel { flex: 1 1 50%; display: flex; flex-direction: column; padding: 8px; overflow: hidden; }
#search-input { padding: 6px; margin-bottom: 6px; }
#resident-list { flex: 1; overflow-y: auto; border: 1px solid #ddd; }
.resident-row { padding: 4px 6px; cursor: pointer; border-bottom: 1px solid #eee; }
.resident-row:hover { background: #f0f0f0; }
#pagination { display: flex; justify-content: space-between; align-items: center; padding-top: 6px; }
#detail-panel { flex: 1 1 50%; overflow-y: auto; padding: 8px; border-top: 1px solid #ccc; }
#detail-panel .hint { color: #888; }
.detail-row { margin: 2px 0; }
.detail-row .label { font-weight: bold; }
.linked-name { color: #2255aa; cursor: pointer; text-decoration: underline; }
```

- [ ] **Step 3: Write map load, pan, zoom**

Create `town_viewer/static/app.js`:

```javascript
const ZONE_COLORS = {
  civic: "#c9a0dc",
  merchant: "#f4a460",
  rich_residential: "#ffd700",
  poor_residential: "#a9a9a9",
  farmland_edge: "#9acd32",
  port: "#87ceeb",
};
const DEFAULT_ZONE_COLOR = "#dddddd";
const WATER_COLOR = "#4a90d9";

const LANDMARK_COLORS = {
  temple: "#8b008b",
  town_hall: "#000080",
  school: "#008080",
  university: "#006400",
  garrison: "#8b0000",
  guard_post: "#cd5c5c",
  arcane_shop: "#9400d3",
  harbormaster_office: "#00008b",
};
const GENERIC_BUILDING_COLOR = "#555555";
const LANDMARK_SIZE = 10;
const GENERIC_SIZE = 5;

function buildingHalfSize(buildingType) {
  return (buildingType in LANDMARK_COLORS ? LANDMARK_SIZE : GENERIC_SIZE) / 2;
}

function buildingColor(buildingType) {
  return LANDMARK_COLORS[buildingType] || GENERIC_BUILDING_COLOR;
}

let mapData = { districts: [], buildings: [], water_features: [] };
const view = { scale: 1, offsetX: 0, offsetY: 0 };

const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");

function resizeCanvas() {
  canvas.width = canvas.clientWidth;
  canvas.height = canvas.clientHeight;
}

function worldToScreen(x, y) {
  return {
    sx: (x - view.offsetX) * view.scale + canvas.width / 2,
    sy: (y - view.offsetY) * view.scale + canvas.height / 2,
  };
}

function screenToWorld(sx, sy) {
  return {
    x: (sx - canvas.width / 2) / view.scale + view.offsetX,
    y: (sy - canvas.height / 2) / view.scale + view.offsetY,
  };
}

function fitViewToBounds() {
  const xs = mapData.buildings.map((b) => b.x);
  const ys = mapData.buildings.map((b) => b.y);
  if (xs.length === 0) return;
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const width = Math.max(maxX - minX, 1);
  const height = Math.max(maxY - minY, 1);
  view.offsetX = (minX + maxX) / 2;
  view.offsetY = (minY + maxY) / 2;
  view.scale = 0.9 * Math.min(canvas.width / width, canvas.height / height);
}

function drawPolygon(ringList, fillStyle, strokeStyle) {
  for (const ring of ringList) {
    ctx.beginPath();
    ring.forEach(([x, y], i) => {
      const { sx, sy } = worldToScreen(x, y);
      if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy);
    });
    ctx.closePath();
    ctx.fillStyle = fillStyle;
    ctx.fill();
    if (strokeStyle) { ctx.strokeStyle = strokeStyle; ctx.lineWidth = 1; ctx.stroke(); }
  }
}

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  ctx.globalAlpha = 0.6;
  for (const water of mapData.water_features) drawPolygon(water.polygon, WATER_COLOR, null);
  for (const district of mapData.districts) {
    const color = ZONE_COLORS[district.zone_type] || DEFAULT_ZONE_COLOR;
    drawPolygon(district.polygon, color, "black");
  }
  ctx.globalAlpha = 1;

  for (const building of mapData.buildings) {
    const half = buildingHalfSize(building.building_type);
    const { sx, sy } = worldToScreen(building.x - half, building.y - half);
    const screenSize = half * 2 * view.scale;
    ctx.fillStyle = buildingColor(building.building_type);
    ctx.fillRect(sx, sy, screenSize, screenSize);
  }
}

function loadMap() {
  fetch("/api/map")
    .then((r) => r.json())
    .then((data) => {
      mapData = data;
      resizeCanvas();
      fitViewToBounds();
      draw();
    });
}

// Pan
let dragging = false, lastClientX = 0, lastClientY = 0, dragDistance = 0;
canvas.addEventListener("mousedown", (e) => {
  dragging = true; dragDistance = 0;
  lastClientX = e.clientX; lastClientY = e.clientY;
  canvas.classList.add("dragging");
});
window.addEventListener("mousemove", (e) => {
  if (!dragging) return;
  const dx = e.clientX - lastClientX, dy = e.clientY - lastClientY;
  dragDistance += Math.abs(dx) + Math.abs(dy);
  lastClientX = e.clientX; lastClientY = e.clientY;
  view.offsetX -= dx / view.scale;
  view.offsetY -= dy / view.scale;
  draw();
});
window.addEventListener("mouseup", () => { dragging = false; canvas.classList.remove("dragging"); });

// Zoom
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const mouseX = e.clientX - rect.left, mouseY = e.clientY - rect.top;
  const before = screenToWorld(mouseX, mouseY);
  view.scale *= e.deltaY < 0 ? 1.15 : 1 / 1.15;
  const after = screenToWorld(mouseX, mouseY);
  view.offsetX += before.x - after.x;
  view.offsetY += before.y - after.y;
  draw();
}, { passive: false });

window.addEventListener("resize", () => { resizeCanvas(); draw(); });

loadMap();
```

- [ ] **Step 4: Manually verify in browser**

Run: `python scripts/serve_town_viewer.py my_town.db`, open `http://127.0.0.1:5000/` in a browser.
Expected: colored district polygons and small colored building rectangles fill the canvas, fitted to the window on load. Scrolling the mouse wheel zooms in/out centered on the cursor. Click-and-drag pans the map. No console errors.

- [ ] **Step 5: Commit**

```bash
git add town_viewer/static/index.html town_viewer/static/style.css town_viewer/static/app.js
git commit -m "feat: render the town map on canvas with pan and zoom"
```

---

### Task 7: Frontend — click a building for detail

**Files:**
- Modify: `town_viewer/static/app.js` (append at end)

**Interfaces:**
- Consumes: `worldToScreen`, `screenToWorld`, `mapData`, `dragDistance`, `draw` (Task 6); `GET /api/buildings/<id>` (Task 5).
- Produces: `highlightedBuildingIds` (module-level `let`, array of building ids to outline), `selectBuilding(id)`, `renderBuildingDetail(building)` — reused by Tasks 8-10 for bidirectional navigation and highlight-drawing.

- [ ] **Step 1: Write the click handler and detail renderer**

Append to `town_viewer/static/app.js`:

```javascript
let highlightedBuildingIds = [];

function findBuildingAt(worldX, worldY) {
  for (const building of mapData.buildings) {
    const half = buildingHalfSize(building.building_type);
    if (
      worldX >= building.x - half && worldX <= building.x + half &&
      worldY >= building.y - half && worldY <= building.y + half
    ) {
      return building;
    }
  }
  return null;
}

function renderBuildingDetail(building) {
  const panel = document.getElementById("detail-panel");
  const rows = building.residents
    .map((r) => {
      const role = r.lives_here && r.works_here ? "lives & works here"
        : r.lives_here ? "lives here" : "works here";
      return `<div class="detail-row"><span class="linked-name" data-resident-id="${r.id}">${r.first_name} ${r.last_name}</span> — ${role}</div>`;
    })
    .join("");
  panel.innerHTML = `
    <h3>${building.building_type} (#${building.id})</h3>
    <div class="detail-row"><span class="label">Zone:</span> ${building.zone_type}</div>
    <div class="detail-row"><span class="label">Capacity:</span> ${building.capacity}</div>
    <h4>Residents (${building.residents.length})</h4>
    ${rows || "<p class=\"hint\">Nobody lives or works here.</p>"}
  `;
  panel.querySelectorAll(".linked-name[data-resident-id]").forEach((el) => {
    el.addEventListener("click", () => selectResident(parseInt(el.dataset.residentId, 10)));
  });
}

function selectBuilding(buildingId) {
  fetch(`/api/buildings/${buildingId}`)
    .then((r) => r.json())
    .then((building) => {
      highlightedBuildingIds = [buildingId];
      renderBuildingDetail(building);
      draw();
    });
}

canvas.addEventListener("mouseup", (e) => {
  if (dragDistance > 3) return; // was a drag, not a click
  const rect = canvas.getBoundingClientRect();
  const world = screenToWorld(e.clientX - rect.left, e.clientY - rect.top);
  const building = findBuildingAt(world.x, world.y);
  if (building) selectBuilding(building.id);
});
```

- [ ] **Step 2: Manually verify in browser**

Reload the running server (or restart `python scripts/serve_town_viewer.py my_town.db` if it wasn't left running).
Expected: clicking a building shape (not dragging) opens the detail panel with its type, zone, capacity, and resident list. Clicking empty space does nothing. Dragging to pan no longer opens the panel.

- [ ] **Step 3: Commit**

```bash
git add town_viewer/static/app.js
git commit -m "feat: click a building on the map to see its detail"
```

---

### Task 8: Frontend — resident search and list

**Files:**
- Modify: `town_viewer/static/app.js` (append at end)

**Interfaces:**
- Consumes: `GET /api/residents?q=&page=` (Task 5).
- Produces: `currentPage`, `loadResidents()` — reused by Task 9's pagination-preserving refresh.

- [ ] **Step 1: Write the search/list/pagination logic**

Append to `town_viewer/static/app.js`:

```javascript
let currentPage = 1;

function renderResidentList(data) {
  const list = document.getElementById("resident-list");
  list.innerHTML = data.residents
    .map((r) => `<div class="resident-row" data-resident-id="${r.id}">${r.first_name} ${r.last_name}${r.occupation ? " — " + r.occupation : ""}</div>`)
    .join("");
  list.querySelectorAll(".resident-row").forEach((el) => {
    el.addEventListener("click", () => selectResident(parseInt(el.dataset.residentId, 10)));
  });

  const totalPages = Math.max(1, Math.ceil(data.total / data.page_size));
  document.getElementById("page-info").textContent = `Page ${data.page} of ${totalPages} (${data.total} residents)`;
  document.getElementById("prev-page").disabled = data.page <= 1;
  document.getElementById("next-page").disabled = data.page >= totalPages;
}

function loadResidents() {
  const query = document.getElementById("search-input").value;
  fetch(`/api/residents?q=${encodeURIComponent(query)}&page=${currentPage}`)
    .then((r) => r.json())
    .then(renderResidentList);
}

document.getElementById("search-input").addEventListener("input", () => {
  currentPage = 1;
  loadResidents();
});
document.getElementById("prev-page").addEventListener("click", () => {
  if (currentPage > 1) { currentPage -= 1; loadResidents(); }
});
document.getElementById("next-page").addEventListener("click", () => {
  currentPage += 1; loadResidents();
});

loadResidents();
```

- [ ] **Step 2: Manually verify in browser**

Reload the page.
Expected: the sidebar list populates with the first 50 residents; typing a name into the search box filters the list (and resets to page 1); Next/Prev page through the full resident set; the page buttons disable at the first/last page.

- [ ] **Step 3: Commit**

```bash
git add town_viewer/static/app.js
git commit -m "feat: add searchable, paginated resident list to the sidebar"
```

---

### Task 9: Frontend — resident profile and map highlight

**Files:**
- Modify: `town_viewer/static/app.js` (append at end, plus one small edit to `draw()`)

**Interfaces:**
- Consumes: `GET /api/residents/<id>` (Task 5); `selectBuilding`, `mapData`, `worldToScreen`, `buildingHalfSize` (Tasks 6-7).
- Produces: `selectResident(id)`, `renderResidentDetail(resident)` — completes the bidirectional loop with Task 7's `renderBuildingDetail`.

- [ ] **Step 1: Add highlight drawing to `draw()`**

In `town_viewer/static/app.js`, find the `draw()` function written in Task 6 (it ends with the `for (const building of mapData.buildings)` loop that fills building rectangles). Immediately after that loop, inside `draw()`, add:

```javascript
  for (const buildingId of highlightedBuildingIds) {
    const building = mapData.buildings.find((b) => b.id === buildingId);
    if (!building) continue;
    const half = buildingHalfSize(building.building_type);
    const { sx, sy } = worldToScreen(building.x - half, building.y - half);
    ctx.strokeStyle = "#ff2222";
    ctx.lineWidth = 3;
    ctx.strokeRect(sx, sy, half * 2 * view.scale, half * 2 * view.scale);
  }
```

- [ ] **Step 2: Write `selectResident` and the profile renderer**

Append to `town_viewer/static/app.js`:

```javascript
function relationshipLabel(rel) {
  if (rel.relationship_type === "parent") return rel.role === "a" ? "parent of" : "child of";
  return rel.relationship_type.replace(/_/g, " ");
}

function renderResidentDetail(resident) {
  const panel = document.getElementById("detail-panel");
  const relRows = resident.relationships
    .map((r) => `<div class="detail-row">${relationshipLabel(r)} <span class="linked-name" data-resident-id="${r.resident_id}">${r.first_name} ${r.last_name}</span></div>`)
    .join("") || "<p class=\"hint\">No recorded relationships.</p>";
  const shopRows = resident.shopping
    .map((s) => `<div class="detail-row"><span class="linked-name" data-building-id="${s.shop_building_id}">Shop #${s.shop_building_id}</span> — ${s.purchase_count} purchases, ${s.total_spent.toFixed(2)} spent${s.is_primary ? " (primary)" : ""}</div>`)
    .join("") || "<p class=\"hint\">No recorded purchases.</p>";

  panel.innerHTML = `
    <h3>${resident.first_name} ${resident.last_name}</h3>
    <div class="detail-row"><span class="label">Household:</span> ${resident.household.family_name} (wealth ${resident.household.wealth})</div>
    <div class="detail-row"><span class="label">SES:</span> ${resident.ses}</div>
    <div class="detail-row"><span class="label">Occupation:</span> ${resident.occupation || "none"}</div>
    <div class="detail-row"><span class="label">Home:</span> ${resident.home_building_id != null ? `<span class="linked-name" data-building-id="${resident.home_building_id}">Building #${resident.home_building_id}</span>` : "none"}</div>
    <div class="detail-row"><span class="label">Workplace:</span> ${resident.workplace_building_id != null ? `<span class="linked-name" data-building-id="${resident.workplace_building_id}">Building #${resident.workplace_building_id}</span>` : "none"}</div>
    <h4>Family & relationships</h4>
    ${relRows}
    <h4>Shopping</h4>
    ${shopRows}
  `;
  panel.querySelectorAll(".linked-name[data-resident-id]").forEach((el) => {
    el.addEventListener("click", () => selectResident(parseInt(el.dataset.residentId, 10)));
  });
  panel.querySelectorAll(".linked-name[data-building-id]").forEach((el) => {
    el.addEventListener("click", () => selectBuilding(parseInt(el.dataset.buildingId, 10)));
  });
}

function selectResident(residentId) {
  fetch(`/api/residents/${residentId}`)
    .then((r) => r.json())
    .then((resident) => {
      highlightedBuildingIds = [resident.home_building_id, resident.workplace_building_id]
        .filter((id) => id != null);
      renderResidentDetail(resident);
      const home = mapData.buildings.find((b) => b.id === resident.home_building_id);
      if (home) { view.offsetX = home.x; view.offsetY = home.y; }
      draw();
    });
}
```

- [ ] **Step 3: Manually verify in browser**

Reload the page.
Expected: clicking a resident in the sidebar list, or a linked name inside a building's detail panel, opens their profile (household, SES, occupation, home/workplace links, family relationships with correct parent/child labeling, shopping history), pans the map to center on their home, and outlines **both** their home and workplace buildings in red (only home, if they have no workplace — e.g. the children in the sample town). Clicking their home/workplace link inside the profile re-selects that single building (its own detail panel opens, outline narrows to just it). Clicking a resident's name inside another resident's relationship list navigates to that resident.

- [ ] **Step 4: Commit**

```bash
git add town_viewer/static/app.js
git commit -m "feat: show resident profile with family/shopping and highlight their home on the map"
```

---

### Task 10: Frontend — legend and final integration pass

**Files:**
- Modify: `town_viewer/static/app.js` (append at end, plus one small edit to `draw()`)
- Modify: `town_viewer/static/index.html`
- Modify: `town_viewer/static/style.css`

**Interfaces:**
- Consumes: everything from Tasks 6-9.
- Produces: nothing new consumed by later tasks — this is the last task in the plan.

- [ ] **Step 1: Add a legend element to the page**

In `town_viewer/static/index.html`, add a `<div id="legend"></div>` immediately after the opening `<canvas id="map"></canvas>` tag, so the canvas has an overlay sibling:

```html
    <canvas id="map"></canvas>
    <div id="legend"></div>
```

- [ ] **Step 2: Style the legend as a map overlay**

Append to `town_viewer/static/style.css`:

```css
#legend {
  position: absolute;
  bottom: 12px;
  left: 12px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid #ccc;
  border-radius: 4px;
  padding: 6px 10px;
  font-size: 12px;
  max-width: 220px;
}
#legend .swatch { display: inline-block; width: 10px; height: 10px; margin-right: 4px; border: 1px solid #666; }
#legend .row { margin: 1px 0; }
```

Also add `position: relative;` to the `#app` rule already in `style.css` so the legend's `absolute` positioning is relative to the app container, not the whole page.

- [ ] **Step 3: Render the legend once, after the first map load**

Append to `town_viewer/static/app.js`:

```javascript
function renderLegend() {
  const zoneTypes = [...new Set(mapData.districts.map((d) => d.zone_type))].sort();
  const landmarkTypesPresent = [...new Set(mapData.buildings.map((b) => b.building_type))]
    .filter((t) => t in LANDMARK_COLORS)
    .sort();

  const zoneRows = zoneTypes
    .map((zt) => `<div class="row"><span class="swatch" style="background:${ZONE_COLORS[zt] || DEFAULT_ZONE_COLOR}"></span>${zt}</div>`)
    .join("");
  const landmarkRows = landmarkTypesPresent
    .map((bt) => `<div class="row"><span class="swatch" style="background:${LANDMARK_COLORS[bt]}"></span>${bt}</div>`)
    .join("");

  document.getElementById("legend").innerHTML = `
    <div><strong>Zones</strong></div>${zoneRows}
    <div><strong>Landmarks</strong></div>${landmarkRows || "<div class=\"row hint\">none</div>"}
  `;
}
```

- [ ] **Step 4: Call the legend renderer from `loadMap`**

In `town_viewer/static/app.js`, find `loadMap()` (from Task 6):

```javascript
function loadMap() {
  fetch("/api/map")
    .then((r) => r.json())
    .then((data) => {
      mapData = data;
      resizeCanvas();
      fitViewToBounds();
      draw();
    });
}
```

Replace it with:

```javascript
function loadMap() {
  fetch("/api/map")
    .then((r) => r.json())
    .then((data) => {
      mapData = data;
      resizeCanvas();
      fitViewToBounds();
      draw();
      renderLegend();
    });
}
```

- [ ] **Step 5: Full manual walkthrough against the real sample town**

Run: `python scripts/serve_town_viewer.py my_town.db`, open `http://127.0.0.1:5000/`.
Walk through, in order:
1. Map loads fitted to the town, legend shows zone colors and any landmark types present.
2. Zoom/pan is smooth with all ~1,174 buildings rendered.
3. Click a building → detail panel shows its residents; click a resident name in it → profile opens, map recenters.
4. Search the sidebar for a real last name from `my_town.db` → list filters; page through results.
5. Click a resident's home/workplace link → the correct building is outlined on the map and its own detail panel opens.
6. Confirm no browser console errors throughout.

- [ ] **Step 6: Run the full backend test suite**

Run: `pytest tests/test_viewer_queries.py tests/test_viewer_app.py -v`
Expected: PASS (19 tests total)

- [ ] **Step 7: Commit**

```bash
git add town_viewer/static/index.html town_viewer/static/style.css town_viewer/static/app.js
git commit -m "feat: add map legend and complete town viewer MVP"
```
