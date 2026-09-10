# Interactive Town Viewer: Real SVG Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the interactive `town_viewer` render settlemaker's real, themed SVG as its map (instead of flat gray canvas rectangles), while keeping its existing pan/zoom/click/search interactivity completely unchanged.

**Architecture:** Persist settlemaker's `metadata.local_bounds` (four floats) per town, alongside the SVG it already persists. The viewer fetches the raw SVG markup, injects it behind the interactive canvas, and keeps it positioned via a CSS transform derived from `local_bounds` plus the SVG's own `viewBox` — recomputed every time the existing pan/zoom state changes, never redrawn. The canvas stops drawing water/farmland/building fills (now redundant) and keeps only the selection-highlight outline.

**Tech Stack:** Python (existing stack: sqlite3, Flask, pytest), vanilla JS (no new frontend dependencies).

## Global Constraints

- No migration system exists in this project — `town_db/schema.py` is only ever applied fresh, at generation time (per `docs/superpowers/specs/2026-09-09-town-viewer-svg-overlay-design.md`'s Risks section). The four new `town_state` columns are nullable; a `.db` generated before this change simply lacks them, and every read of them must handle that (`sqlite3.OperationalError` on the missing columns, not a null value) without raising.
- The coordinate-transform formula is engine-agnostic by construction — it must never branch on which settlemaker engine (burg vs. village) produced a town. Verified empirically in the design spec: burg mode reduces to `scale == 1`, village mode to `scale ≈ 4`, from the exact same formula.
- No change to click hit-testing, pan/zoom math (`worldToScreen`/`screenToWorld`/`fitViewToBounds`), the resident search panel, or any `/api/buildings`/`/api/residents` endpoint — all already work off stored coordinate/footprint data, independent of how the map is drawn.
- The selection-highlight outline (`#ff2222`, traced through a building's real footprint) is unchanged, byte-for-byte, from its current implementation.

---

## Task 1: Persist `local_bounds` through generation

**Files:**
- Modify: `town_db/schema.py` (four new nullable `town_state` columns)
- Modify: `town_shaper/models.py` (four new `Town` fields)
- Modify: `settlemaker_bridge/pipeline.py` (`generate_via_settlemaker`'s return value)
- Modify: `town_shaper/generate.py` (`generate_town()` captures the new fields)
- Modify: `town_db/generate.py` (`generate_town_database()`'s `town_state` INSERT)
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Produces: `generate_via_settlemaker(...) -> Tuple[List[District], List[Building], List[WaterFeature], str, Dict[str, float]]` — fifth element is `{"min_x": ..., "min_y": ..., "max_x": ..., "max_y": ...}`, settlemaker's own `metadata.local_bounds` passed through unmodified.
- Produces: `Town.svg_min_x/svg_min_y/svg_max_x/svg_max_y: Optional[float] = None`.
- Produces: `town_state` table gains `svg_min_x REAL, svg_min_y REAL, svg_max_x REAL, svg_max_y REAL` (nullable).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_db_schema.py`, right after `test_generate_town_database_honors_explicit_svg_path`:

```python
def test_generate_town_database_writes_svg_bounds_for_burg_mode(tmp_path):
    from town_db.generate import generate_town_database

    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path)

    conn = connect(db_path)
    row = conn.execute(
        "SELECT svg_min_x, svg_min_y, svg_max_x, svg_max_y FROM town_state WHERE id = 1"
    ).fetchone()
    conn.close()

    assert None not in row
    min_x, min_y, max_x, max_y = row
    assert max_x > min_x
    assert max_y > min_y


def test_generate_town_database_writes_svg_bounds_for_village_mode(tmp_path):
    from town_db.generate import generate_town_database

    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 9), target_population=500, db_path=db_path)

    conn = connect(db_path)
    row = conn.execute(
        "SELECT svg_min_x, svg_min_y, svg_max_x, svg_max_y FROM town_state WHERE id = 1"
    ).fetchone()
    conn.close()

    assert None not in row
    min_x, min_y, max_x, max_y = row
    assert max_x > min_x
    assert max_y > min_y
```

`connect` is already imported at the top of this file (`from town_db.schema import connect, create_schema`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_db_schema.py -k svg_bounds -v`
Expected: FAIL — `sqlite3.OperationalError: no such column: svg_min_x` (the columns don't exist yet).

- [ ] **Step 3: Add the four columns to `town_state`**

In `town_db/schema.py`, change:

```python
CREATE TABLE town_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    year_start TEXT NOT NULL,
    current_date TEXT NOT NULL,
    aggression REAL NOT NULL,
    magic_prevalence REAL NOT NULL
);
```

to:

```python
CREATE TABLE town_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    year_start TEXT NOT NULL,
    current_date TEXT NOT NULL,
    aggression REAL NOT NULL,
    magic_prevalence REAL NOT NULL,
    svg_min_x REAL,
    svg_min_y REAL,
    svg_max_x REAL,
    svg_max_y REAL
);
```

- [ ] **Step 4: Add the four fields to `Town`**

In `town_shaper/models.py`, add four fields to the `Town` dataclass, right after `svg: str = ""`:

```python
    svg: str = ""
    svg_min_x: Optional[float] = None
    svg_min_y: Optional[float] = None
    svg_max_x: Optional[float] = None
    svg_max_y: Optional[float] = None
```

(`Optional` is already imported at the top of this file.)

- [ ] **Step 5: Return `local_bounds` from `generate_via_settlemaker`**

In `settlemaker_bridge/pipeline.py`, change the `typing` import:

```python
from typing import Any, Dict, List, Tuple
```

Change the function's return type and final lines. From:

```python
) -> Tuple[List[District], List[Building], List[WaterFeature], str]:
```

to:

```python
) -> Tuple[List[District], List[Building], List[WaterFeature], str, Dict[str, float]]:
```

And its docstring's first line, from:

```python
    """Returns (districts, buildings, scaled_water_features, svg). `svg` is
```

to:

```python
    """Returns (districts, buildings, scaled_water_features, svg, local_bounds).
    `local_bounds` is settlemaker's own metadata.local_bounds for this call,
    passed through unmodified (keys: min_x, min_y, max_x, max_y) -- see
    docs/superpowers/specs/2026-09-09-town-viewer-svg-overlay-design.md for
    what it's for. `svg` is
```

(the rest of the docstring is unchanged). Then change the function body's final two lines, from:

```python
    result = call_settlemaker(burg, settlemaker_seed)
    districts, buildings = parse_settlemaker_geojson(result["geojson"], seed, target_population)
    return districts, buildings, scaled_water_features, result["svg"]
```

to:

```python
    result = call_settlemaker(burg, settlemaker_seed)
    districts, buildings = parse_settlemaker_geojson(result["geojson"], seed, target_population)
    local_bounds = result["geojson"]["metadata"]["local_bounds"]
    return districts, buildings, scaled_water_features, result["svg"], local_bounds
```

- [ ] **Step 6: Capture the new return value in `generate_town()`**

In `town_shaper/generate.py`, change:

```python
    districts, buildings, water_features, svg = generate_via_settlemaker(
        seed, target_population,
        area_per_resident_multiplier=area_per_resident_multiplier,
        num_rivers=num_rivers, has_coastline=has_coastline, has_port=has_port,
    )
```

to:

```python
    districts, buildings, water_features, svg, local_bounds = generate_via_settlemaker(
        seed, target_population,
        area_per_resident_multiplier=area_per_resident_multiplier,
        num_rivers=num_rivers, has_coastline=has_coastline, has_port=has_port,
    )
```

And change the end of the function, from:

```python
    town.road_network = RoadNetwork()
    town.svg = svg
    return town
```

to:

```python
    town.road_network = RoadNetwork()
    town.svg = svg
    town.svg_min_x = local_bounds["min_x"]
    town.svg_min_y = local_bounds["min_y"]
    town.svg_max_x = local_bounds["max_x"]
    town.svg_max_y = local_bounds["max_y"]
    return town
```

- [ ] **Step 7: Write the four values in `generate_town_database`**

In `town_db/generate.py`, change the `town_state` INSERT (currently around line 208):

```python
    conn.execute(
        "INSERT INTO town_state (id, year_start, current_date, aggression, magic_prevalence) "
        "VALUES (1, ?, ?, ?, ?)",
        (year_start.isoformat(), year_end.isoformat(), aggression, magic_prevalence),
    )
```

to:

```python
    conn.execute(
        "INSERT INTO town_state (id, year_start, current_date, aggression, magic_prevalence, "
        "svg_min_x, svg_min_y, svg_max_x, svg_max_y) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            year_start.isoformat(), year_end.isoformat(), aggression, magic_prevalence,
            town.svg_min_x, town.svg_min_y, town.svg_max_x, town.svg_max_y,
        ),
    )
```

(`town` is already in scope in this function — the same object `town.svg` is read from a few lines earlier.)

- [ ] **Step 8: Run the tests to verify they pass**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_db_schema.py -v`
Expected: all pass, including the two new tests.

- [ ] **Step 9: Run the settlemaker bridge integration test and the full `test_generate.py`/`test_db_generate.py` files**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_settlemaker_bridge_integration.py tests/test_generate.py tests/test_db_generate.py -v`
Expected: all pass — `generate_via_settlemaker`'s signature change is consumed correctly everywhere it's called (only `town_shaper/generate.py`, per Step 6).

- [ ] **Step 10: Commit**

```bash
git add town_db/schema.py town_shaper/models.py settlemaker_bridge/pipeline.py town_shaper/generate.py town_db/generate.py tests/test_db_schema.py
git commit -m "feat: persist settlemaker's local_bounds for the SVG overlay feature"
```

---

## Task 2: Backend viewer API — serve the SVG, expose `local_bounds`, fall back gracefully

**Files:**
- Modify: `town_viewer/app.py` (new `/api/town.svg` route)
- Modify: `town_viewer/queries.py` (`get_map_data` gains `local_bounds`)
- Test: `tests/test_viewer_app.py`, `tests/test_viewer_queries.py`

**Interfaces:**
- Consumes: `town_state.svg_min_x/svg_min_y/svg_max_x/svg_max_y` (Task 1).
- Produces: `GET /api/town.svg` — the persisted `.svg` file, `Content-Type: image/svg+xml`.
- Produces: `get_map_data(conn)`'s returned dict gains a `"local_bounds"` key: `{"min_x": ..., "min_y": ..., "max_x": ..., "max_y": ...}` when available, `None` otherwise (missing row, `NULL` values, or a `town_state` predating this feature — all three collapse to the same `None`, on purpose, per the design spec).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_viewer_queries.py`, after `test_get_map_data_returns_roads` (or any other existing `get_map_data` test — exact position doesn't matter, this project's convention keeps related tests grouped, not ordered by line number):

```python
def test_get_map_data_returns_local_bounds_when_present(tmp_path):
    db_path = str(tmp_path / "town.db")
    _build_minimal_map(db_path)
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO town_state (id, year_start, current_date, aggression, magic_prevalence, "
        "svg_min_x, svg_min_y, svg_max_x, svg_max_y) VALUES (1, '1300-01-01', '1301-01-01', 0.0, 0.0, "
        "-10.0, -20.0, 30.0, 40.0)"
    )
    conn.commit()

    data = get_map_data(conn)
    conn.close()

    assert data["local_bounds"] == {"min_x": -10.0, "min_y": -20.0, "max_x": 30.0, "max_y": 40.0}


def test_get_map_data_returns_none_local_bounds_when_town_state_row_is_missing(tmp_path):
    db_path = str(tmp_path / "town.db")
    _build_minimal_map(db_path)
    # _build_minimal_map never inserts a town_state row -- this is the real,
    # already-existing shape every other test in this file exercises.
    conn = connect(db_path)

    data = get_map_data(conn)
    conn.close()

    assert data["local_bounds"] is None


def test_get_map_data_returns_none_local_bounds_when_columns_predate_this_feature(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    # A minimal stand-in for a `.db` generated before this feature existed --
    # the four-column town_state schema this project used before Task 1.
    conn.execute(
        "CREATE TABLE town_state (id INTEGER PRIMARY KEY CHECK (id = 1), year_start TEXT NOT NULL, "
        "current_date TEXT NOT NULL, aggression REAL NOT NULL, magic_prevalence REAL NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE districts (id INTEGER PRIMARY KEY, zone_type TEXT NOT NULL, polygon TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE buildings (id INTEGER PRIMARY KEY, district_id INTEGER NOT NULL, "
        "zone_type TEXT NOT NULL, building_type TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL, "
        "capacity INTEGER NOT NULL, name TEXT, width REAL NOT NULL DEFAULT 0, "
        "height REAL NOT NULL DEFAULT 0, rotation REAL NOT NULL DEFAULT 0, footprint TEXT)"
    )
    conn.execute("CREATE TABLE water_features (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, polygon TEXT NOT NULL)")
    conn.execute(
        "INSERT INTO town_state (id, year_start, current_date, aggression, magic_prevalence) "
        "VALUES (1, '1300-01-01', '1301-01-01', 0.0, 0.0)"
    )
    conn.commit()

    data = get_map_data(conn)
    conn.close()

    assert data["local_bounds"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_viewer_queries.py -k local_bounds -v`
Expected: FAIL — `KeyError: 'local_bounds'` (the key doesn't exist in the response yet).

- [ ] **Step 3: Implement `_read_local_bounds` and wire it into `get_map_data`**

In `town_viewer/queries.py`, add a new function right before `get_map_data`:

```python
def _read_local_bounds(conn: sqlite3.Connection) -> Optional[Dict[str, float]]:
    try:
        row = conn.execute(
            "SELECT svg_min_x, svg_min_y, svg_max_x, svg_max_y FROM town_state WHERE id = 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None  # town_state predates this feature -- no such column
    if row is None or any(v is None for v in row):
        return None
    return {"min_x": row[0], "min_y": row[1], "max_x": row[2], "max_y": row[3]}
```

Then change `get_map_data`'s final `return` statement, from:

```python
    return {
        "districts": districts, "buildings": buildings, "water_features": water_features,
        "roads": {"nodes": road_nodes, "edges": road_edges},
    }
```

to:

```python
    return {
        "districts": districts, "buildings": buildings, "water_features": water_features,
        "roads": {"nodes": road_nodes, "edges": road_edges},
        "local_bounds": _read_local_bounds(conn),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_viewer_queries.py -v`
Expected: all pass.

- [ ] **Step 5: Write the failing test for the new SVG route**

Append to `tests/test_viewer_app.py`:

```python
def test_town_svg_endpoint_serves_the_persisted_svg(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)
    svg_path = str(tmp_path / "town.svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write("<svg xmlns=\"http://www.w3.org/2000/svg\"><rect/></svg>")

    app = create_app(db_path)
    app.testing = True
    client = app.test_client()
    response = client.get("/api/town.svg")

    assert response.status_code == 200
    assert b"<svg" in response.data
    assert "svg" in response.content_type
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_viewer_app.py::test_town_svg_endpoint_serves_the_persisted_svg -v`
Expected: FAIL — 404 (the route doesn't exist yet).

- [ ] **Step 7: Add the `/api/town.svg` route**

In `town_viewer/app.py`, add `import os` is already present at the top of the file. Add the new route right after the `index` route:

```python
    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/api/town.svg")
    def town_svg():
        svg_path = os.path.splitext(db_path)[0] + ".svg"
        return send_from_directory(os.path.dirname(svg_path) or ".", os.path.basename(svg_path))
```

(`os.path.dirname(svg_path) or "."` guards the case where `db_path` has no directory component, e.g. a bare `"town.db"` passed from the current working directory — `os.path.dirname` would return `""`, which `send_from_directory` rejects.)

- [ ] **Step 8: Run the tests to verify they pass**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_viewer_app.py -v`
Expected: all pass.

- [ ] **Step 9: Run the full viewer test suite**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_viewer_app.py tests/test_viewer_queries.py -v`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add town_viewer/app.py town_viewer/queries.py tests/test_viewer_app.py tests/test_viewer_queries.py
git commit -m "feat: serve the persisted SVG and expose local_bounds from the viewer API"
```

---

## Task 3: Frontend — render the real SVG, retire the flat canvas fills

**Files:**
- Modify: `town_viewer/static/index.html`
- Modify: `town_viewer/static/style.css`
- Modify: `town_viewer/static/app.js`

**Interfaces:**
- Consumes: `GET /api/town.svg` and `/api/map`'s `local_bounds` key (Task 2).
- No test framework exists for this project's frontend JS (confirmed in the design spec) — this task's verification is Step 6's manual check plus Task 4's end-to-end check, not automated tests. Every code step below is still complete, runnable code — "no tests" does not mean "no verification," see Step 6.

- [ ] **Step 1: Restructure the map area to hold both the SVG layer and the canvas**

In `town_viewer/static/index.html`, change:

```html
  <div id="app">
    <canvas id="map"></canvas>
    <div id="legend"></div>
```

to:

```html
  <div id="app">
    <div id="map-container">
      <div id="svg-layer"></div>
      <canvas id="map"></canvas>
    </div>
    <div id="legend"></div>
```

(everything else in the file is unchanged.)

- [ ] **Step 2: Add the layout CSS for the new elements**

In `town_viewer/static/style.css`, change:

```css
#app { display: flex; height: 100vh; position: relative; }
#map { flex: 1; background: #eef2f5; cursor: grab; }
#map.dragging { cursor: grabbing; }
```

to:

```css
#app { display: flex; height: 100vh; position: relative; }
#map-container { flex: 1; position: relative; overflow: hidden; background: #eef2f5; }
#svg-layer { position: absolute; top: 0; left: 0; width: 100%; height: 100%; overflow: hidden; pointer-events: none; }
#svg-layer svg { position: absolute; top: 0; left: 0; transform-origin: 0 0; }
#map { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: transparent; cursor: grab; }
#map.dragging { cursor: grabbing; }
```

(`#map`'s own background moves from `#eef2f5` to transparent, so the SVG layer shows through it; `#map-container` carries that same background color now, for towns with no `local_bounds` to overlay. `pointer-events: none` on `#svg-layer` means every mouse/wheel event still reaches the canvas above it unchanged — this is what keeps pan/zoom/click hit-testing untouched.)

- [ ] **Step 3: Track `local_bounds` and the parsed SVG viewBox as module state**

In `town_viewer/static/app.js`, change the existing module-level state line:

```javascript
let mapData = { districts: [], buildings: [], water_features: [], roads: { nodes: [], edges: [] } };
const view = { scale: 1, offsetX: 0, offsetY: 0 };
```

to:

```javascript
let mapData = { districts: [], buildings: [], water_features: [], roads: { nodes: [], edges: [] }, local_bounds: null };
const view = { scale: 1, offsetX: 0, offsetY: 0 };

const svgLayer = document.getElementById("svg-layer");
let svgViewBox = null;  // { minX, minY, width, height }, parsed once per town load
```

- [ ] **Step 4: Fetch and inject the SVG when the map loads**

In `town_viewer/static/app.js`, change `loadMap()`, from:

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

to:

```javascript
function loadMap() {
  fetch("/api/map")
    .then((r) => r.json())
    .then((data) => {
      mapData = data;
      resizeCanvas();
      fitViewToBounds();
      svgLayer.innerHTML = "";
      svgViewBox = null;
      if (mapData.local_bounds) {
        fetch("/api/town.svg")
          .then((r) => r.text())
          .then((svgText) => {
            svgLayer.innerHTML = svgText;
            const svgEl = svgLayer.querySelector("svg");
            const vb = (svgEl.getAttribute("viewBox") || "").trim().split(/\s+/).map(Number);
            if (vb.length === 4) {
              svgViewBox = { minX: vb[0], minY: vb[1], width: vb[2], height: vb[3] };
              svgEl.setAttribute("width", vb[2]);
              svgEl.setAttribute("height", vb[3]);
            }
            draw();
          });
      }
      draw();
      renderLegend();
    });
}
```

(the fetch for the SVG is async and calls `draw()` again once it lands, since the SVG is a separate network request from `/api/map` and shouldn't block the first render — the buildings/canvas interactivity is usable immediately, the SVG appears a moment later.)

- [ ] **Step 5: Add `updateSvgTransform()` and fold it into `draw()`**

In `town_viewer/static/app.js`, add a new function right after `worldToScreen`:

```javascript
function updateSvgTransform() {
  if (!mapData.local_bounds || !svgViewBox) return;
  const svgEl = svgLayer.querySelector("svg");
  if (!svgEl) return;

  const lb = mapData.local_bounds;
  const worldWidth = lb.max_x - lb.min_x;
  const worldHeight = lb.max_y - lb.min_y;
  if (worldWidth <= 0 || worldHeight <= 0) return;

  // World units -> SVG units. Verified empirically (design spec): this is
  // exactly 1 for burg-mode towns (SVG paths already use world coordinates
  // directly) and a real, consistent per-town factor (~4 in one measured
  // village) for village-mode towns -- one formula, no per-engine branch.
  const svgUnitsPerWorldUnit = svgViewBox.width / worldWidth;
  const pixelsPerSvgUnit = view.scale / svgUnitsPerWorldUnit;

  // The SVG element's own local pixel (0, 0) already corresponds to its
  // viewBox's (minX, minY) point -- the <svg width> attribute was set equal
  // to the viewBox width in loadMap(), so that offset is handled entirely
  // by the SVG's own internal rendering. Working through the algebra: local
  // pixel (0, 0) is exactly the point at world (local_bounds.min_x,
  // local_bounds.min_y), for BOTH engines, regardless of what the viewBox's
  // own (minX, minY) numerically is -- that term cancels out. (An earlier
  // draft of this function subtracted a `svgViewBox.minX/minY`-derived term
  // here; that was wrong -- it happened to vanish for village-mode towns,
  // whose viewBox origin is (0, 0), but would have visibly misaligned
  // burg-mode towns, whose viewBox origin is not. Do not reintroduce it.)
  const origin = worldToScreen(lb.min_x, lb.min_y);

  svgEl.style.transform = `translate(${origin.sx}px, ${origin.sy}px) scale(${pixelsPerSvgUnit})`;
}
```

- [ ] **Step 6: Simplify `draw()` — call the new transform, drop the now-redundant fills**

In `town_viewer/static/app.js`, replace the whole `draw()` function. From:

```javascript
function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  ctx.globalAlpha = 0.6;
  for (const water of mapData.water_features) drawPolygon(water.polygon, WATER_COLOR, null);
  for (const district of mapData.districts) {
    if (district.zone_type !== "farmland_edge") continue;
    const color = ZONE_COLORS[district.zone_type] || DEFAULT_ZONE_COLOR;
    drawPolygon(district.polygon, color, "black");
  }
  ctx.globalAlpha = 1;

  const roadNodeById = new Map((mapData.roads?.nodes || []).map((n) => [n.id, n]));
  for (const edge of mapData.roads?.edges || []) {
    const from = roadNodeById.get(edge.from_node_id);
    const to = roadNodeById.get(edge.to_node_id);
    if (!from || !to) continue;
    const style = ROAD_STYLE[edge.road_type] || ROAD_STYLE.spur;
    const a = worldToScreen(from.x, from.y);
    const b = worldToScreen(to.x, to.y);
    ctx.beginPath();
    ctx.moveTo(a.sx, a.sy);
    ctx.lineTo(b.sx, b.sy);
    ctx.strokeStyle = style.color;
    ctx.lineWidth = style.width;
    ctx.stroke();
  }

  for (const building of mapData.buildings) {
    ctx.fillStyle = buildingColor(building.building_type);
    if (building.footprint) {
      ctx.beginPath();
      building.footprint.forEach(([x, y], i) => {
        const { sx, sy } = worldToScreen(x, y);
        if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy);
      });
      ctx.closePath();
      ctx.fill();
    } else {
      const { sx, sy } = worldToScreen(building.x, building.y);
      ctx.save();
      ctx.translate(sx, sy);
      ctx.rotate(building.rotation);
      const screenWidth = building.width * view.scale;
      const screenHeight = building.height * view.scale;
      ctx.fillRect(-screenWidth / 2, -screenHeight / 2, screenWidth, screenHeight);
      ctx.restore();
    }
  }

  for (const buildingId of highlightedBuildingIds) {
    const building = mapData.buildings.find((b) => b.id === buildingId);
    if (!building) continue;
    ctx.strokeStyle = "#ff2222";
    ctx.lineWidth = 3;
    if (building.footprint) {
      // Same footprint path used for the fill above, so the highlight
      // traces the actual drawn shape instead of the OBB-derived
      // width/height/rotation rectangle (which _leaf_footprint shrinks to
      // match the leaf's real area, so it no longer matches the fill).
      ctx.beginPath();
      building.footprint.forEach(([x, y], i) => {
        const { sx, sy } = worldToScreen(x, y);
        if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy);
      });
      ctx.closePath();
      ctx.stroke();
    } else {
      const { sx, sy } = worldToScreen(building.x, building.y);
      ctx.save();
      ctx.translate(sx, sy);
      ctx.rotate(building.rotation);
      const screenWidth = building.width * view.scale;
      const screenHeight = building.height * view.scale;
      ctx.strokeRect(-screenWidth / 2, -screenHeight / 2, screenWidth, screenHeight);
      ctx.restore();
    }
  }
}
```

to:

```javascript
function draw() {
  updateSvgTransform();
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Water/farmland/building fills and road lines used to be drawn here.
  // Settlemaker's own SVG (rendered underneath via #svg-layer, positioned
  // by updateSvgTransform above) already shows all of that -- see
  // docs/superpowers/specs/2026-09-09-town-viewer-svg-overlay-design.md.
  // The canvas now exists only for interaction (click hit-testing, which
  // reads mapData directly and was never part of this function) and the
  // selection highlight below.

  for (const buildingId of highlightedBuildingIds) {
    const building = mapData.buildings.find((b) => b.id === buildingId);
    if (!building) continue;
    ctx.strokeStyle = "#ff2222";
    ctx.lineWidth = 3;
    if (building.footprint) {
      ctx.beginPath();
      building.footprint.forEach(([x, y], i) => {
        const { sx, sy } = worldToScreen(x, y);
        if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy);
      });
      ctx.closePath();
      ctx.stroke();
    } else {
      const { sx, sy } = worldToScreen(building.x, building.y);
      ctx.save();
      ctx.translate(sx, sy);
      ctx.rotate(building.rotation);
      const screenWidth = building.width * view.scale;
      const screenHeight = building.height * view.scale;
      ctx.strokeRect(-screenWidth / 2, -screenHeight / 2, screenWidth, screenHeight);
      ctx.restore();
    }
  }
}
```

`drawPolygon`, `buildingColor`, `WATER_COLOR`, `ZONE_COLORS`, `DEFAULT_ZONE_COLOR`, `ROAD_STYLE`, and `LANDMARK_COLORS`/`COMMON_BUILDING_COLORS`/`ALL_TYPED_COLORS`/`GENERIC_BUILDING_COLOR` are now unused by `draw()` — **do not delete them in this task.** `renderLegend()` (a separate function, not shown above) still reads `ALL_TYPED_COLORS` to build the color-key sidebar widget, which is unaffected by this task and stays exactly as it is.

- [ ] **Step 6: Manual verification (no JS test framework exists for this project)**

Generate one town of each engine and confirm the server itself round-trips correctly, using `curl` (fast, no browser needed) before checking visually:

```bash
~/venvs/townshape/bin/python -c "
from town_db.generate import generate_town_database
generate_town_database(('town', 1), target_population=3000, db_path='/tmp/svg_overlay_check_town.db')
generate_town_database(('town', 9), target_population=500, db_path='/tmp/svg_overlay_check_village.db')
"
~/venvs/townshape/bin/python scripts/serve_town_viewer.py /tmp/svg_overlay_check_village.db --port 5099 &
sleep 2
curl -s http://127.0.0.1:5099/api/map | python3 -c "import json,sys; d=json.load(sys.stdin); print('local_bounds:', d['local_bounds'])"
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://127.0.0.1:5099/api/town.svg
kill %1
```

Expected: `local_bounds` prints real min/max values (not `None`); the second `curl` prints `200` and a content type containing `svg`.

Then, if you have a way to view the page in a browser (this project's own history treats "look at it" as the correct verification method for visual work, not something to automate around): start the server against a real town, open `http://127.0.0.1:<port>` and confirm the real settlemaker map (not flat gray rectangles) is visible, pans and zooms smoothly, and clicking a building still opens its detail panel. If no browser is reachable in this environment, report this step's code changes as complete but the visual check as not independently confirmed, and say so plainly — do not claim a visual result you didn't observe.

- [ ] **Step 7: Commit**

```bash
git add town_viewer/static/index.html town_viewer/static/style.css town_viewer/static/app.js
git commit -m "feat: render settlemaker's real SVG in the interactive viewer"
```

---

## Task 4: End-to-end verification and wrap-up

**Files:** None (verification only).

- [ ] **Step 1: Run the full test suite**

Run: `~/venvs/townshape/bin/python -m pytest tests/ -q`

If a background-task memory watchdog kills this run partway through (a known, unrelated environment quirk from earlier sessions — see any recent plan's Global Constraints for the same note), split into file-group chunks and run each in the foreground instead, the same way prior sessions in this project have.

Expected: every test passes, total count up from wherever the suite stood at the start of this plan, by the number of new tests added across Tasks 1 and 2 (2 + 4 = 6; Task 3 adds none, per its own Interfaces note).

- [ ] **Step 2: Confirm the old-`.db` fallback against a real, currently-existing town**

If any `.db` file generated before this plan is available (e.g. one of this session's earlier `/tmp/*.db` files, or any town generated on `main` before Task 1 landed), serve it through the viewer and confirm `/api/map`'s `local_bounds` comes back `null` and the page falls back to today's flat rendering without erroring — the real-world version of `test_get_map_data_returns_none_local_bounds_when_columns_predate_this_feature`, against an actual old file rather than a hand-built fixture.

- [ ] **Step 3: Report to the user**

Confirm the final pass count, and ask the user to open the viewer themselves against a real town and confirm the visual result looks right — the same "show, don't just assert" standard this project has used at every prior visual checkpoint (Phase 1's settlemaker spike side-by-side comparison, the Pipeline Specimens artifact, this session's own live viewer walkthrough).

## Self-Review

**Spec coverage** — every piece of `docs/superpowers/specs/2026-09-09-town-viewer-svg-overlay-design.md`'s Architecture section is covered: capturing `local_bounds` (Task 1), the engine-agnostic transform formula (Task 3, `updateSvgTransform`), serving the SVG (Task 2), the old-`.db` graceful-fallback query (Task 2), and the frontend rework (Task 3). The design's explicit Scope exclusions (no change to hit-testing/pan-zoom/search/highlight, no SVG-generation changes) are respected by construction — no task touches any of them beyond `draw()`'s fill-removal, which the design's Architecture section specifically calls for.

**Placeholder scan** — no TBD/TODO; every step shows complete code or an exact command with its expected output. Task 3's Step 6 is deliberately honest about a real limitation (no browser available to auto-verify) rather than a placeholder — it tells the executor exactly what to report if that's the case, which is not the same thing as leaving a gap unfilled.

**Type consistency** — `generate_via_settlemaker`'s new 5th return element (`Dict[str, float]`, keys `min_x`/`min_y`/`max_x`/`max_y`) is defined once (Task 1, Step 5) and consumed once with the same keys (Task 1, Step 6). `Town.svg_min_x`/etc. are defined once (Task 1, Step 4) and consumed once, in the same names, by `generate_town_database` (Task 1, Step 7) and never referenced again. `get_map_data`'s `"local_bounds"` key and its `{"min_x", "min_y", "max_x", "max_y"}` shape are defined once (Task 2, Step 3) and consumed with the exact same key names by `app.js` (Task 3, Steps 4-5) — no drift between the Python dict keys and the JS property accesses (`mapData.local_bounds.min_x`, etc.).
