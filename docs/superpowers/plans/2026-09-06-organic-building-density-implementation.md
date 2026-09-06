# Organic Building Density & Shape Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix residential building counts to match real household demand (a test town had 10,436 `residence` buildings for 1,372 households) and replace clean grid-cut buildings with organic, jittered, notched/appendage-bearing footprints, with district/block boundaries perturbed away from straight Voronoi-cell edges.

**Architecture:** `town_shaper/blocks.py` gets a jittered-split primitive (replacing the clean OBB-perpendicular cut), a fractal boundary-perturbation pass, a demand-driven leaf-area calculation for residential zones (via a new pure `estimate_household_counts` helper), and a two-stage per-building finishing pass (straight-wall notch + porch/annex appendage, with a sibling-overlap safety check). Buildings gain a real polygon `footprint`, persisted additively (nullable column, existing `width`/`height`/`rotation` kept and now derived from it) so every existing consumer that doesn't care about the real shape keeps working unchanged.

**Tech Stack:** Python 3.12, `shapely` (polygon ops), `sqlite3` (stdlib), `pytest`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-06-organic-building-density-design.md`

## Global Constraints

- All randomness flows through `rng_for(seed, *path_parts)` (`town_shaper/seeding.py`) — never global `random` state, per every prior spec in this repo.
- `footprint` is a **nullable** `TEXT` column, not `NOT NULL` as the spec's Data Model section literally says — a deliberate, documented deviation. Making it `NOT NULL` would require touching every raw-SQL `buildings` INSERT across `tests/test_db_schema.py`, `tests/test_db_render.py`, `tests/test_viewer_queries.py`, `tests/town_viewer_fixtures.py`, and more, none of which care about the real footprint shape. Nullable + a graceful width/height/rotation-rectangle fallback in both renderers achieves the same goal (real generation always populates it) with zero unrelated test churn. This is a compatible refinement of the spec, not a contradiction of its intent.
- `width`/`height`/`rotation` stay populated for every building (never left at the schema's old `DEFAULT 0`) — computed from `footprint`'s minimum rotated rectangle via the existing `_leaf_footprint` in `town_shaper/blocks.py`, same as today.
- Farmland (`ZoneType.FARMLAND_EDGE`) is untouched by this entire plan: still Poisson-disc point placement, `footprint` stays `None`, renders via the width/height/rotation fallback forever.

---

## Task 1: `jaggify_polygon` — fractal boundary perturbation

**Files:**
- Modify: `town_shaper/geometry.py`
- Test: `tests/test_geometry.py`

**Interfaces:**
- Produces: `jaggify_polygon(polygon: Polygon, rng, iterations: int = 2, max_offset_fraction: float = 0.18, max_absolute_offset: Optional[float] = None) -> Polygon`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_geometry.py`:

```python
def test_jaggify_polygon_preserves_vertex_count_doubling():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    rng = rng_for(("town", 1), "jaggify-test", 1)
    result = jaggify_polygon(square, rng, iterations=2)
    assert len(result) == len(square) * 4  # each iteration doubles vertex count


def test_jaggify_polygon_is_deterministic():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    rng1 = rng_for(("town", 1), "jaggify-test", 2)
    rng2 = rng_for(("town", 1), "jaggify-test", 2)
    assert jaggify_polygon(square, rng1) == jaggify_polygon(square, rng2)


def test_jaggify_polygon_perturbs_at_least_one_vertex_off_the_original_edges():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    rng = rng_for(("town", 1), "jaggify-test", 3)
    result = jaggify_polygon(square, rng, iterations=1, max_offset_fraction=0.3)
    # midpoints are inserted between original vertices -- at least one should
    # have moved off the square's exact boundary (a random offset of 0.0 for
    # every one of 4 edges is not plausible with this rng/seed combination).
    on_boundary = lambda p: p[0] in (0.0, 10.0) or p[1] in (0.0, 10.0)
    assert not all(on_boundary(p) for p in result)


def test_jaggify_polygon_zero_iterations_returns_the_same_shape():
    triangle = [(0.0, 0.0), (10.0, 0.0), (5.0, 8.0)]
    rng = rng_for(("town", 1), "jaggify-test", 4)
    result = jaggify_polygon(triangle, rng, iterations=0)
    assert result == triangle


def test_jaggify_polygon_respects_max_absolute_offset():
    # A huge max_offset_fraction would normally displace midpoints far off
    # the original edge -- max_absolute_offset must clamp that regardless
    # of how large the fractional request is (this is what keeps a
    # jaggified district's own boundary from bleeding past its own inset
    # margin into a neighbouring district).
    square = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    rng = rng_for(("town", 1), "jaggify-test", 5)
    result = jaggify_polygon(square, rng, iterations=1, max_offset_fraction=0.9, max_absolute_offset=1.0)
    original_edges = [
        ((0.0, 0.0), (100.0, 0.0)), ((100.0, 0.0), (100.0, 100.0)),
        ((100.0, 100.0), (0.0, 100.0)), ((0.0, 100.0), (0.0, 0.0)),
    ]

    def distance_to_segment(p, a, b):
        ax, ay = a
        bx, by = b
        px, py = p
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
        cx, cy = ax + t * dx, ay + t * dy
        return math.hypot(px - cx, py - cy)

    # Every inserted midpoint (odd-indexed vertices) must stay within
    # max_absolute_offset of the edge it was displaced from.
    for i in range(1, len(result), 2):
        edge = original_edges[(i - 1) // 2]
        assert distance_to_segment(result[i], *edge) <= 1.0 + 1e-9
```

Add the import at the top of `tests/test_geometry.py`:

```python
from town_shaper.geometry import jaggify_polygon
from town_shaper.seeding import rng_for
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_geometry.py -k jaggify -v`
Expected: FAIL with `ImportError: cannot import name 'jaggify_polygon'`

- [ ] **Step 3: Implement `jaggify_polygon`**

Append to `town_shaper/geometry.py` (needs `from typing import Optional` added to its existing `typing` import line):

```python
def jaggify_polygon(
    polygon: Polygon, rng, iterations: int = 2,
    max_offset_fraction: float = 0.18, max_absolute_offset: Optional[float] = None,
) -> Polygon:
    """Midpoint-displacement fractal edge perturbation (classic coastline-
    generator technique): each edge's midpoint is pushed perpendicular by a
    random offset scaled to that edge's own length, repeated `iterations`
    times (vertex count doubles each round, so amplitude naturally decays
    each round -- one call already produces a 2-level fractal). Fixes the
    straight Voronoi-cell-edge look of district boundaries.

    `max_absolute_offset`, when given, clamps the offset in map units
    regardless of edge length -- needed when jaggifying an already-inset
    polygon, so the perturbation can never push a vertex back out past its
    own inset margin into a neighbouring district's territory.
    """
    pts = list(polygon)
    for _ in range(iterations):
        new_pts = []
        n = len(pts)
        for i in range(n):
            p1, p2 = pts[i], pts[(i + 1) % n]
            new_pts.append(p1)
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            length = math.hypot(dx, dy)
            if length == 0:
                continue
            mx, my = (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0
            perp = (-dy / length, dx / length)
            offset = rng.uniform(-max_offset_fraction, max_offset_fraction) * length
            if max_absolute_offset is not None:
                offset = max(-max_absolute_offset, min(max_absolute_offset, offset))
            new_pts.append((mx + perp[0] * offset, my + perp[1] * offset))
        pts = new_pts
    return pts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_geometry.py -k jaggify -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/geometry.py tests/test_geometry.py
git commit -m "$(cat <<'EOF'
feat: add jaggify_polygon fractal boundary perturbation

Midpoint-displacement perturbation for polygon edges, fixing straight
Voronoi-cell-edge district boundaries. max_absolute_offset lets a
caller clamp displacement in map units regardless of edge length.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AMajdcVvM4s56PJmpBMi4g
EOF
)"
```

---

## Task 2: `estimate_household_counts` — analytical household demand

**Files:**
- Modify: `town_shaper/households.py`
- Test: `tests/test_households.py`

**Interfaces:**
- Consumes: `AVERAGE_HOUSEHOLD_SIZE` (existing module constant in `town_shaper/households.py`)
- Produces: `estimate_household_counts(target_population: int, rich_proportion: float) -> Tuple[int, int]` — returns `(poor_count, rich_count)`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_households.py`:

```python
def test_estimate_household_counts_sums_to_the_target_household_count():
    poor, rich = estimate_household_counts(target_population=3000, rich_proportion=0.05)
    expected_total = round(3000 / AVERAGE_HOUSEHOLD_SIZE)
    assert poor + rich == expected_total


def test_estimate_household_counts_splits_by_rich_proportion():
    poor, rich = estimate_household_counts(target_population=10000, rich_proportion=0.05)
    total = poor + rich
    assert rich == round(total * 0.05)
    assert poor == total - rich


def test_estimate_household_counts_zero_rich_proportion_gives_no_rich_households():
    poor, rich = estimate_household_counts(target_population=3000, rich_proportion=0.0)
    assert rich == 0
    assert poor > 0


def test_estimate_household_counts_is_at_least_one_poor_household_for_a_tiny_town():
    poor, rich = estimate_household_counts(target_population=1, rich_proportion=0.05)
    assert poor >= 1
```

Add the import at the top of `tests/test_households.py`:

```python
from town_shaper.households import AVERAGE_HOUSEHOLD_SIZE, estimate_household_counts, generate_households
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_households.py -k estimate_household_counts -v`
Expected: FAIL with `ImportError: cannot import name 'estimate_household_counts'`

- [ ] **Step 3: Implement `estimate_household_counts`**

Append to `town_shaper/households.py`:

```python
def estimate_household_counts(target_population: int, rich_proportion: float) -> Tuple[int, int]:
    """Analytical (non-random) estimate of (poor_count, rich_count)
    households, using the same AVERAGE_HOUSEHOLD_SIZE-based total
    generate_households() derives internally, so building generation can
    size residential lots against real demand before any household or
    resident object exists. This is an ESTIMATE, not an exact prediction
    of what generate_households() will produce: real household sizes vary
    (spouse/child counts) and that function can stop slightly early once
    target_population is reached, so its actual household count can come
    in a bit under this formula's total -- callers that use this for
    sizing (town_shaper/blocks.py) already apply their own slack margin
    to absorb that, so an exact match isn't required here."""
    target_household_count = max(1, round(target_population / AVERAGE_HOUSEHOLD_SIZE))
    rich_count = round(target_household_count * rich_proportion)
    poor_count = target_household_count - rich_count
    return poor_count, rich_count
```

Add `Tuple` to the existing `from typing import List` line at the top of `town_shaper/households.py` (becomes `from typing import List, Tuple`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_households.py -v`
Expected: PASS (all tests, including the pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/households.py tests/test_households.py
git commit -m "$(cat <<'EOF'
feat: add estimate_household_counts analytical helper

Reuses generate_households' own AVERAGE_HOUSEHOLD_SIZE formula so
block/building generation can size residential lots against real
household demand before any household object exists.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AMajdcVvM4s56PJmpBMi4g
EOF
)"
```

---

## Task 3: `footprint` plumbing — model, schema, persistence

**Files:**
- Modify: `town_shaper/models.py`
- Modify: `town_db/schema.py`
- Modify: `town_db/generate.py`
- Test: `tests/test_models.py`
- Test: `tests/test_db_schema.py` (this is where `test_generate_town_database_persists_road_network` and `test_generate_town_database_persists_building_footprints` already live, confirmed — the new persistence test below is added next to them, not in `tests/test_db_generate.py`)

**Interfaces:**
- Produces: `Building.footprint: Optional[List[Tuple[float, float]]] = None` (new field, additive, defaults `None`)
- Produces: `buildings.footprint` — nullable `TEXT` column (JSON list of `[x, y]` pairs when set)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_models.py`:

```python
def test_building_footprint_defaults_to_none():
    building = Building(
        id=1, district_id=1, district_zone_type=ZoneType.POOR_RESIDENTIAL,
        x=0.0, y=0.0, building_type="residence", capacity=6,
    )
    assert building.footprint is None


def test_building_accepts_an_explicit_footprint():
    footprint = [(0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 5.0)]
    building = Building(
        id=1, district_id=1, district_zone_type=ZoneType.POOR_RESIDENTIAL,
        x=2.5, y=2.5, building_type="residence", capacity=6, footprint=footprint,
    )
    assert building.footprint == footprint
```

Append to `tests/test_db_schema.py`:

```python
def test_buildings_footprint_defaults_to_null(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'temple', 0.0, 0.0, 0)"
    )
    row = conn.execute("SELECT footprint FROM buildings WHERE id = 1").fetchone()
    assert row[0] is None


def test_buildings_footprint_accepts_a_json_polygon(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, footprint) "
        "VALUES (1, 1, 'civic', 'temple', 0.0, 0.0, 0, ?)",
        ('[[0.0, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 5.0]]',),
    )
    row = conn.execute("SELECT footprint FROM buildings WHERE id = 1").fetchone()
    assert row[0] == '[[0.0, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 5.0]]'
```

Append to `tests/test_db_schema.py` (persistence round-trip, next to the existing `test_generate_town_database_persists_building_footprints` — note that test name refers to `width`/`height`/`rotation`, not the new polygon `footprint` field; leave it as-is and add a new one for the real polygon):

```python
def test_generate_town_database_persists_building_footprint_polygons(tmp_path):
    import json

    from town_db.generate import generate_town_database

    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path)

    conn = connect(db_path)
    rows = conn.execute(
        "SELECT footprint FROM buildings WHERE zone_type != 'farmland_edge'"
    ).fetchall()
    conn.close()

    assert len(rows) > 0
    # Not populated with real geometry until Task 6/7 wire it in -- for now
    # this just proves the column round-trips NULL cleanly end-to-end.
    assert all(row[0] is None for row in rows)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py tests/test_db_schema.py -k "footprint" -v`
Expected: FAIL — `test_building_footprint_defaults_to_none`/`test_building_accepts_an_explicit_footprint` with `TypeError: __init__() got an unexpected keyword argument 'footprint'`; the schema tests with `sqlite3.OperationalError: no such column: footprint`.

- [ ] **Step 3: Add the field and column**

In `town_shaper/models.py`, add `footprint` to the `Building` dataclass (after `rotation`):

```python
    footprint: Optional[List[Tuple[float, float]]] = None
```

(`Optional` must be imported — it already is, per the existing `from typing import List, Optional, Tuple` line at the top of the file.)

In `town_db/schema.py`, the `buildings` table's last two lines today are:

```sql
    rotation REAL NOT NULL DEFAULT 0
);
```

(`rotation` has no trailing comma, since it's currently the last column.) Replace those two lines with:

```sql
    rotation REAL NOT NULL DEFAULT 0,
    footprint TEXT
);
```

(`rotation` now needs its own trailing comma, since `footprint` follows it.)

- [ ] **Step 4: Persist it**

In `town_db/generate.py`, the buildings `executemany` block needs a new column and a `json.dumps`-or-`None` value per building. Replace:

```python
    conn.executemany(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, name, "
        "width, height, rotation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(building.id, district.id, district.zone_type.value, building.building_type,
          building.x, building.y, building.capacity, building.name,
          building.width, building.height, building.rotation)
         for district in town.districts for building in district.buildings],
    )
```

with:

```python
    conn.executemany(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, name, "
        "width, height, rotation, footprint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(building.id, district.id, district.zone_type.value, building.building_type,
          building.x, building.y, building.capacity, building.name,
          building.width, building.height, building.rotation,
          json.dumps(building.footprint) if building.footprint is not None else None)
         for district in town.districts for building in district.buildings],
    )
```

(`json` is already imported at the top of `town_db/generate.py`, used for `water_features`/`districts`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_models.py tests/test_db_schema.py -v`
Expected: PASS (all tests, including pre-existing ones — no existing `buildings` INSERT statement anywhere needs updating, since `footprint` is nullable)

- [ ] **Step 6: Run the full existing suite to confirm no regressions**

Run: `pytest tests/ -x -q`
Expected: PASS. (This is the first checkpoint where an untouched raw-SQL INSERT elsewhere in the suite could have broken — it shouldn't have, since the column is nullable, but verify.)

- [ ] **Step 7: Commit**

```bash
git add town_shaper/models.py town_db/schema.py town_db/generate.py tests/test_models.py tests/test_db_schema.py
git commit -m "$(cat <<'EOF'
feat: add nullable footprint column/field for real building polygons

Additive: Building.footprint defaults to None, buildings.footprint is
a nullable TEXT column. Deliberately NOT NOT NULL -- avoids touching
every existing raw-SQL buildings INSERT across the test suite that
doesn't care about the real footprint shape. width/height/rotation
stay as the fallback for anything that doesn't read footprint.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AMajdcVvM4s56PJmpBMi4g
EOF
)"
```

---

## Task 4: Jittered split — replace the clean OBB-perpendicular cut

**Files:**
- Modify: `town_shaper/blocks.py`
- Test: `tests/test_blocks.py`

**Interfaces:**
- Consumes: `clip_polygon_by_line` (`town_shaper/geometry.py`, existing)
- Produces: `_split_polygon(polygon, rng, gap) -> Tuple[Polygon, Polygon]` (same signature, new jittered behavior — still module-private, only called from within `blocks.py`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_blocks.py`:

```python
def test_split_polygon_angle_varies_across_calls():
    # The old clean OBB-perpendicular split always cut along the same axis
    # (a grid-like result); the jittered version should vary the cut angle
    # from one call to the next given different rng draws.
    from town_shaper.blocks import _split_polygon

    square = _square(40.0)
    rng1 = rng_for(("town", 1), "split-test", 1)
    rng2 = rng_for(("town", 1), "split-test", 2)

    side_a1, _ = _split_polygon(square, rng1, gap=0.4)
    side_a2, _ = _split_polygon(square, rng2, gap=0.4)

    # Different rng streams should not produce byte-identical first halves
    # (a purely-fixed-axis split would, since the split line's angle
    # never varies regardless of rng).
    assert side_a1 != side_a2


def test_split_polygon_still_conserves_area_within_the_gap():
    from town_shaper.blocks import _split_polygon

    square = _square(40.0)
    rng = rng_for(("town", 1), "split-test", 3)
    side_a, side_b = _split_polygon(square, rng, gap=0.4)

    original_area = polygon_area(square)
    total = polygon_area(side_a) + polygon_area(side_b)
    assert total <= original_area
    assert total >= original_area * 0.85  # gap only removes a thin strip
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_blocks.py -k "test_split_polygon" -v`
Expected: FAIL on `test_split_polygon_angle_varies_across_calls` (current implementation always cuts perpendicular to the same computed OBB axis regardless of rng, since `_longer_axis_direction` is a pure geometric function of the polygon alone — `side_a1 == side_a2`)

- [ ] **Step 3: Implement the jittered split**

In `town_shaper/blocks.py`, replace the existing `_split_polygon` function body:

```python
def _split_polygon(polygon: Polygon, rng, gap: float) -> Tuple[Polygon, Polygon]:
    """Split `polygon` into two halves along a jittered axis (angle offset
    from the longer OBB axis, wider ratio range than a clean 50/50) --
    this plus the per-leaf finishing pass is what gives buildings local
    irregularity, distinct from the one coarse jaggify_polygon pass on
    the district boundary."""
    axis_dir = _longer_axis_direction(polygon)
    angle = math.atan2(axis_dir[1], axis_dir[0]) + rng.uniform(-0.35, 0.35)  # +/- ~20 degrees
    axis_dir = (math.cos(angle), math.sin(angle))
    split_dir = (-axis_dir[1], axis_dir[0])  # perpendicular to the jittered axis
    cx, cy = _polygon_centroid(polygon)

    span = max((distance(p, q) for p in polygon for q in polygon), default=0.0) + 1.0
    split_fraction = rng.uniform(0.3, 0.7)
    offset_along_axis = (split_fraction - 0.5) * span
    center = (cx + axis_dir[0] * offset_along_axis, cy + axis_dir[1] * offset_along_axis)

    line_start = (center[0] - split_dir[0] * span, center[1] - split_dir[1] * span)
    line_end = (center[0] + split_dir[0] * span, center[1] + split_dir[1] * span)

    half_gap = gap / 2.0
    offset_a = (axis_dir[0] * half_gap, axis_dir[1] * half_gap)
    offset_b = (-offset_a[0], -offset_a[1])

    side_a = clip_polygon_by_line(
        polygon,
        (line_start[0] + offset_b[0], line_start[1] + offset_b[1]),
        (line_end[0] + offset_b[0], line_end[1] + offset_b[1]),
    )
    side_b = clip_polygon_by_line(
        polygon,
        (line_end[0] + offset_a[0], line_end[1] + offset_a[1]),
        (line_start[0] + offset_a[0], line_start[1] + offset_a[1]),
    )
    return side_a, side_b
```

(This is the same structure as before, with two changes: `angle` now jitters the axis by up to ±0.35 radians instead of using `_longer_axis_direction`'s raw output directly, and `split_fraction` widens from `rng.uniform(0.4, 0.6)` to `rng.uniform(0.3, 0.7)`. `math` is already imported at the top of `blocks.py`.)

- [ ] **Step 4: Fix the existing axis-aligned test — it breaks immediately, not later**

`_subdivide_into_buildings` (the still-active body of `place_buildings_in_block`, not replaced until Task 8) calls `_split_polygon` directly — so this change breaks `test_place_buildings_in_block_footprints_stay_axis_aligned_for_a_rectangular_block` (`tests/test_blocks.py`) right now, not at Task 8 as its position later in this plan might suggest. Its premise (every leaf's rotation is a multiple of 90°) is exactly what this task intentionally makes false. Replace it:

```python
def test_place_buildings_in_block_rotations_vary_for_a_rectangular_block():
    # Was "...stays_axis_aligned..." -- the old clean OBB-perpendicular
    # split kept every leaf's rotation at a multiple of 90 degrees. The
    # jittered split (this task) is specifically meant to break that.
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 12)

    buildings = place_buildings_in_block(
        block, district, rng, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )

    assert buildings

    def is_axis_aligned(rotation):
        remainder = abs(rotation) % (math.pi / 2)
        return remainder < 1e-6 or (math.pi / 2 - remainder) < 1e-6

    assert any(not is_axis_aligned(b.rotation) for b in buildings)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_blocks.py -v`
Expected: PASS. Some other pre-existing tests may also now be flaky/borderline (e.g. `test_subdivide_into_blocks_conserves_area_within_street_gaps`'s `>= original_area * 0.6` floor) since the wider ratio range and angle jitter change how much area a gap removes across many recursive splits — if any other pre-existing test fails here, loosen its numeric tolerance (not its intent) to accommodate the new variance; do not change what property it verifies.

- [ ] **Step 6: Commit**

```bash
git add town_shaper/blocks.py tests/test_blocks.py
git commit -m "$(cat <<'EOF'
feat: jitter block/leaf split angle and ratio

Replaces the clean OBB-perpendicular 50/50 cut with angle jitter
(+/- ~20 degrees) and a wider ratio range (0.3-0.7), fixing the
grid-like look of recursively subdivided blocks and buildings.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AMajdcVvM4s56PJmpBMi4g
EOF
)"
```

---

## Task 5: `compute_district_blocks` — jaggify + block geometry as its own step

**Files:**
- Modify: `town_shaper/blocks.py`
- Test: `tests/test_blocks.py`

**Interfaces:**
- Consumes: `jaggify_polygon` (Task 1), `inset_polygon`, `subdivide_into_blocks` (existing)
- Produces: `compute_district_blocks(district: District, town_seed) -> List[Polygon]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_blocks.py`:

```python
def test_compute_district_blocks_covers_every_polygon_part():
    from town_shaper.blocks import compute_district_blocks

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(40.0, 20.0), _rectangle(30.0, 15.0)])
    blocks = compute_district_blocks(district, ("town", 1))
    assert len(blocks) > 0


def test_compute_district_blocks_is_deterministic():
    from town_shaper.blocks import compute_district_blocks

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(60.0, 60.0)])
    blocks1 = compute_district_blocks(district, ("town", 1))
    blocks2 = compute_district_blocks(district, ("town", 1))
    assert [sorted(b) for b in blocks1] == [sorted(b) for b in blocks2]


def test_compute_district_blocks_stays_within_the_original_district_polygon():
    from shapely.geometry import Polygon as ShapelyPolygon

    from town_shaper.blocks import compute_district_blocks

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(60.0, 60.0)])
    blocks = compute_district_blocks(district, ("town", 1))

    original = ShapelyPolygon(_rectangle(60.0, 60.0))
    for block in blocks:
        # jaggify_polygon's max_absolute_offset keeps the perturbed inset
        # boundary from bleeding past the original district edge -- a
        # small buffer absorbs floating-point/clip slack, not design slack.
        assert original.buffer(0.5).contains(ShapelyPolygon(block))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_blocks.py -k compute_district_blocks -v`
Expected: FAIL with `ImportError: cannot import name 'compute_district_blocks'`

- [ ] **Step 3: Implement `compute_district_blocks`, wire jaggify in with a safe absolute cap**

Append to `town_shaper/blocks.py`:

```python
def compute_district_blocks(district: District, town_seed) -> List[Polygon]:
    """Inset each of the district's polygon parts, jaggify the inset
    boundary (fixes the straight Voronoi-cell-edge look), then subdivide
    into blocks. Split out from generate_blocks_and_buildings so the
    two-pass residential flow (town_shaper/generate.py) can compute every
    residential district's block geometry and total area before deriving
    a demand-driven leaf target area -- see the design spec's two-pass
    description."""
    rng = rng_for(town_seed, "blocks", district.id)
    blocks: List[Polygon] = []
    for part in district.polygon_parts:
        inset_part = inset_polygon(part, DISTRICT_INSET_DISTANCE)
        if len(inset_part) < 3:
            continue
        # Absolute cap so the perturbation can never push a vertex back out
        # past most of its own inset margin into a neighbouring district.
        jagged = jaggify_polygon(inset_part, rng, max_absolute_offset=DISTRICT_INSET_DISTANCE * 0.8)
        blocks.extend(subdivide_into_blocks(jagged, district.zone_type, rng))
    return blocks
```

Add the import at the top of `town_shaper/blocks.py`: `from town_shaper.geometry import clip_polygon_by_line, distance, inset_polygon, jaggify_polygon, polygon_area`.

- [ ] **Step 4: Update `generate_blocks_and_buildings` to use it**

`town_shaper/blocks.py`'s existing `generate_blocks_and_buildings` currently reads:

```python
def generate_blocks_and_buildings(
    district: District, town_seed, next_building_id: int,
    target_population: int = 0, density_multiplier: float = 1.0, magic_prevalence: float = 0.0,
    notable_building_counts: Optional[Dict[str, int]] = None,
) -> List[Building]:
    rng = rng_for(town_seed, "blocks", district.id)
    if notable_building_counts is None:
        notable_building_counts = {}

    buildings: List[Building] = []
    building_id = next_building_id

    for part in district.polygon_parts:
        inset_part = inset_polygon(part, DISTRICT_INSET_DISTANCE)
        if len(inset_part) < 3:
            continue
        blocks = subdivide_into_blocks(inset_part, district.zone_type, rng)
        for block in blocks:
            block_buildings = place_buildings_in_block(
                block, district, rng, building_id, target_population, magic_prevalence,
                notable_building_counts=notable_building_counts, density_multiplier=density_multiplier,
            )
            buildings.extend(block_buildings)
            building_id += len(block_buildings)

    return buildings
```

Replace it with (this task only changes how blocks are obtained — the double-nested `for part` / `for block` loop collapses to a single `for block in compute_district_blocks(...)`; building placement per block is unchanged for now, Task 6 changes that):

```python
def generate_blocks_and_buildings(
    district: District, town_seed, next_building_id: int,
    target_population: int = 0, density_multiplier: float = 1.0, magic_prevalence: float = 0.0,
    notable_building_counts: Optional[Dict[str, int]] = None,
) -> List[Building]:
    rng = rng_for(town_seed, "blocks", district.id)
    if notable_building_counts is None:
        notable_building_counts = {}

    buildings: List[Building] = []
    building_id = next_building_id

    for block in compute_district_blocks(district, town_seed):
        block_buildings = place_buildings_in_block(
            block, district, rng, building_id, target_population, magic_prevalence,
            notable_building_counts=notable_building_counts, density_multiplier=density_multiplier,
        )
        buildings.extend(block_buildings)
        building_id += len(block_buildings)

    return buildings
```

(This intermediate signature — no `blocks`/`target_area`/`hard_cap_area` parameters yet — is fully replaced again in Task 8; don't add those parameters yet, this task's diff is deliberately minimal and self-contained.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_blocks.py -v`
Expected: PASS. If `test_generate_blocks_and_buildings_insets_away_from_the_district_boundary` (existing test) now fails because jaggify moved a building closer to the original boundary than its `DISTRICT_INSET_DISTANCE - 0.5` tolerance allows, replace its assertion with a boundary-containment check instead of a fixed-distance one:

```python
def test_generate_blocks_and_buildings_insets_away_from_the_district_boundary():
    from shapely.geometry import Point, Polygon as ShapelyPolygon

    from town_shaper.blocks import generate_blocks_and_buildings

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(60.0, 60.0)])

    buildings = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, target_population=3000, magic_prevalence=0.0,
    )

    assert buildings
    original = ShapelyPolygon(_rectangle(60.0, 60.0))
    for building in buildings:
        # jaggify can locally push the inset boundary back out closer to
        # the original edge than a fixed distance tolerance assumes, but
        # every building must still stay inside the district's own true
        # polygon (a small buffer absorbs floating-point slack only).
        assert original.buffer(0.5).contains(Point(building.x, building.y))
```

Run: `pytest tests/test_blocks.py -v` again.
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add town_shaper/blocks.py tests/test_blocks.py
git commit -m "$(cat <<'EOF'
feat: split out compute_district_blocks, jaggify district boundaries

District inset polygons are now perturbed via jaggify_polygon before
block subdivision (capped at 80% of the inset margin so districts
can't bleed into a neighbour's territory), fixing straight Voronoi
edges. Block computation is now its own function so the upcoming
two-pass residential flow can compute total area before generating
buildings.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AMajdcVvM4s56PJmpBMi4g
EOF
)"
```

---

## Task 6: `organic_subdivide` — soft target + hard cap leaf splitting

**Files:**
- Modify: `town_shaper/blocks.py`
- Test: `tests/test_blocks.py`

**Interfaces:**
- Consumes: `_split_polygon` (Task 4)
- Produces: `organic_subdivide(polygon: Polygon, target_area: float, hard_cap_area: float, rng, depth: int = 0, max_depth: int = 9) -> List[Polygon]`
- Produces: `DEFAULT_HARD_CAP_AREA` (module constant in `blocks.py`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_blocks.py`:

```python
def test_organic_subdivide_never_exceeds_the_hard_cap():
    from town_shaper.blocks import organic_subdivide

    large_square = _square(100.0)  # area 10000
    target_area = 50.0
    hard_cap = 200.0
    rng = rng_for(("town", 1), "organic-test", 1)

    leaves = organic_subdivide(large_square, target_area, hard_cap, rng)

    assert len(leaves) > 1
    for leaf in leaves:
        assert polygon_area(leaf) <= hard_cap + 1e-6


def test_organic_subdivide_returns_original_when_already_small():
    small_square = _square(5.0)  # area 25, under any reasonable target
    rng = rng_for(("town", 1), "organic-test", 2)

    leaves = organic_subdivide(small_square, target_area=100.0, hard_cap_area=400.0, rng=rng)

    assert leaves == [small_square]


def test_organic_subdivide_forces_a_split_above_the_hard_cap_even_if_near_target():
    # A polygon whose area sits between target_area and hard_cap_area could
    # randomly sample a stop_area above its own area and stop immediately
    # under the old design -- but once area exceeds hard_cap_area outright,
    # it must always keep splitting regardless of the soft sample.
    from town_shaper.blocks import organic_subdivide

    square = _square(20.0)  # area 400
    rng = rng_for(("town", 1), "organic-test", 3)

    leaves = organic_subdivide(square, target_area=50.0, hard_cap_area=300.0, rng=rng)

    assert len(leaves) > 1
    for leaf in leaves:
        assert polygon_area(leaf) <= 300.0 + 1e-6


def test_organic_subdivide_is_deterministic():
    from town_shaper.blocks import organic_subdivide

    large_square = _square(100.0)
    rng1 = rng_for(("town", 1), "organic-test", 4)
    leaves1 = organic_subdivide(large_square, 50.0, 200.0, rng1)
    rng2 = rng_for(("town", 1), "organic-test", 4)
    leaves2 = organic_subdivide(large_square, 50.0, 200.0, rng2)

    assert [sorted(leaf) for leaf in leaves1] == [sorted(leaf) for leaf in leaves2]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_blocks.py -k organic_subdivide -v`
Expected: FAIL with `ImportError: cannot import name 'organic_subdivide'`

- [ ] **Step 3: Implement `organic_subdivide`**

Append to `town_shaper/blocks.py`:

```python
HARD_CAP_AREA_MULTIPLIER = 4.0
DEFAULT_HARD_CAP_AREA = (
    HARD_CAP_AREA_MULTIPLIER
    * LOT_FRONTAGE_BY_ZONE[ZoneType.POOR_RESIDENTIAL]
    * LOT_DEPTH_BY_ZONE[ZoneType.POOR_RESIDENTIAL]
)


def organic_subdivide(
    polygon: Polygon, target_area: float, hard_cap_area: float, rng, depth: int = 0, max_depth: int = 9,
) -> List[Polygon]:
    """Recursively split `polygon` into building-sized leaves. Soft stop at
    a randomized fraction of target_area (size variance between leaves);
    but always splits further if area exceeds hard_cap_area regardless of
    that soft sample, so no leaf can end up "much much much" bigger than
    the rest of a zone just because its containing block happened to be
    smaller than target_area to begin with (the degenerate case an
    earlier version of this algorithm hit: an undersized block became one
    giant, unfinished single "building")."""
    area = polygon_area(polygon)
    stop_area = target_area * rng.uniform(0.55, 1.4)
    must_split = area > hard_cap_area
    if len(polygon) < 3 or depth >= max_depth or (area <= stop_area and not must_split):
        return [polygon]

    result = _split_polygon(polygon, rng, gap=rng.uniform(0.25, 0.6))
    side_a, side_b = result
    if len(side_a) < 3 or len(side_b) < 3:
        return [polygon]

    return (
        organic_subdivide(side_a, target_area, hard_cap_area, rng, depth + 1, max_depth)
        + organic_subdivide(side_b, target_area, hard_cap_area, rng, depth + 1, max_depth)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_blocks.py -k organic_subdivide -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/blocks.py tests/test_blocks.py
git commit -m "$(cat <<'EOF'
feat: add organic_subdivide with a shared hard size cap

Soft target-area stop (randomized 0.55-1.4x) plus a hard ceiling
(4x the smallest house's lot area, shared across every zone) that
forces further splitting regardless of the soft sample -- prevents
an undersized block from becoming one oversized, unfinished leaf.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AMajdcVvM4s56PJmpBMi4g
EOF
)"
```

---

## Task 7: `notch_corner` + `add_appendage` + `finish_leaves` — architectural irregularity

**Files:**
- Modify: `town_shaper/blocks.py`
- Test: `tests/test_blocks.py`

**Interfaces:**
- Produces: `notch_corner(polygon: Polygon, rng) -> Polygon`
- Produces: `add_appendage(polygon: Polygon, rng) -> Polygon`
- Produces: `finish_leaves(leaves: List[Polygon], rng) -> List[Polygon]`

This is where the Known Risk from the spec (an appendage overlapping a neighboring leaf) gets resolved: `finish_leaves` operates on a whole block's leaf list together, so it can check a candidate appendage against every sibling leaf and skip it (never shrink it — simplest correct behavior) if it would overlap.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_blocks.py`:

```python
def test_notch_corner_never_increases_area():
    from town_shaper.blocks import notch_corner

    square = _square(20.0)
    rng = rng_for(("town", 1), "notch-test", 1)
    for i in range(20):  # sample several rng draws -- notch is probabilistic
        r = rng_for(("town", 1), "notch-test", i)
        result = notch_corner(square, r)
        assert polygon_area(result) <= polygon_area(square) + 1e-9


def test_notch_corner_is_deterministic():
    from town_shaper.blocks import notch_corner

    square = _square(20.0)
    rng1 = rng_for(("town", 1), "notch-test", 5)
    rng2 = rng_for(("town", 1), "notch-test", 5)
    assert notch_corner(square, rng1) == notch_corner(square, rng2)


def test_add_appendage_produces_a_simple_polygon_or_leaves_it_unchanged():
    from shapely.geometry import Polygon as ShapelyPolygon

    from town_shaper.blocks import add_appendage

    square = _square(20.0)
    for i in range(30):  # sample several draws -- appendage/curve are both probabilistic
        rng = rng_for(("town", 1), "appendage-test", i)
        result = add_appendage(square, rng)
        shape = ShapelyPolygon(result)
        assert shape.is_valid
        assert shape.geom_type == "Polygon"


def test_add_appendage_area_is_at_least_the_original():
    from town_shaper.blocks import add_appendage

    square = _square(20.0)
    for i in range(30):
        rng = rng_for(("town", 1), "appendage-test", 100 + i)
        result = add_appendage(square, rng)
        assert polygon_area(result) >= polygon_area(square) - 1e-9


def test_finish_leaves_never_produces_overlapping_footprints():
    # The Known Risk from the design spec: an appendage grown outward from
    # one leaf's edge could reach into a neighbouring leaf across the
    # narrow party-wall gap between them. finish_leaves must check every
    # candidate appendage against every sibling leaf in the same block and
    # skip it (not shrink it) if it would overlap.
    from shapely.geometry import Polygon as ShapelyPolygon

    from town_shaper.blocks import finish_leaves, organic_subdivide

    block = _rectangle(40.0, 20.0)
    rng = rng_for(("town", 1), "finish-test", 1)
    raw_leaves = organic_subdivide(block, target_area=30.0, hard_cap_area=120.0, rng=rng)

    finish_rng = rng_for(("town", 1), "finish-test", 2)
    finished = finish_leaves(raw_leaves, finish_rng)

    assert len(finished) == len(raw_leaves)
    shapes = [ShapelyPolygon(leaf) for leaf in finished]
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            assert shapes[i].intersection(shapes[j]).area < 1e-6


def test_finish_leaves_is_deterministic():
    from town_shaper.blocks import finish_leaves, organic_subdivide

    block = _rectangle(40.0, 20.0)
    gen_rng = rng_for(("town", 1), "finish-test", 3)
    raw_leaves = organic_subdivide(block, target_area=30.0, hard_cap_area=120.0, rng=gen_rng)

    rng1 = rng_for(("town", 1), "finish-test", 4)
    finished1 = finish_leaves(raw_leaves, rng1)
    rng2 = rng_for(("town", 1), "finish-test", 4)
    finished2 = finish_leaves(raw_leaves, rng2)

    assert finished1 == finished2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_blocks.py -k "notch_corner or add_appendage or finish_leaves" -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `notch_corner`, `add_appendage`, `finish_leaves`**

Append to `town_shaper/blocks.py` (needs `from shapely.geometry import Polygon as ShapelyPolygon` already imported at the top of the file — confirm; it already is, used by `_longer_axis_direction` and `_leaf_footprint`):

```python
def notch_corner(polygon: Polygon, rng) -> Polygon:
    """Shave a small triangular notch off one random corner, ~35% of the
    time -- a straight-wall L-shaped front. Can only shrink the polygon,
    never grow it, so it can never introduce a new overlap with a
    neighbour."""
    if len(polygon) < 4 or rng.random() > 0.35:
        return polygon
    idx = rng.randrange(len(polygon))
    v = polygon[idx]
    prev_v = polygon[idx - 1]
    next_v = polygon[(idx + 1) % len(polygon)]
    frac = rng.uniform(0.25, 0.45)
    p1 = (v[0] + (prev_v[0] - v[0]) * frac, v[1] + (prev_v[1] - v[1]) * frac)
    p2 = (v[0] + (next_v[0] - v[0]) * frac, v[1] + (next_v[1] - v[1]) * frac)
    return polygon[:idx] + [p1, p2] + polygon[idx + 1:]


def add_appendage(polygon: Polygon, rng) -> Polygon:
    """Attach a small straight-walled porch/annex to one edge, at a
    slightly different orientation than the main body -- or, ~30% of the
    time, a curved bay/turret bulge instead of a rectangular one. Real
    building-shaped irregularity (real walls, a real addition), never
    edge noise. ~40% chance of doing anything at all; the caller
    (finish_leaves) is responsible for rejecting the result if it would
    overlap a sibling leaf -- this function only ever grows the polygon
    outward, it has no notion of neighbours."""
    if len(polygon) < 4 or rng.random() > 0.4:
        return polygon
    idx = rng.randrange(len(polygon))
    p1, p2 = polygon[idx], polygon[(idx + 1) % len(polygon)]
    edge_len = math.dist(p1, p2)
    if edge_len < 3.0:
        return polygon

    ex, ey = (p2[0] - p1[0]) / edge_len, (p2[1] - p1[1]) / edge_len
    angle_dev = rng.uniform(-0.2, 0.2)
    cos_d, sin_d = math.cos(angle_dev), math.sin(angle_dev)
    ex2, ey2 = ex * cos_d - ey * sin_d, ex * sin_d + ey * cos_d
    perp = (-ey2, ex2)

    frac = rng.uniform(0.3, 0.55)
    start_t = rng.uniform(0.0, 1.0 - frac)
    base1 = (p1[0] + ex * edge_len * start_t, p1[1] + ey * edge_len * start_t)
    base2 = (p1[0] + ex * edge_len * (start_t + frac), p1[1] + ey * edge_len * (start_t + frac))
    seg_len = edge_len * frac
    depth = max(0.8, rng.uniform(0.25, 0.6) * seg_len)
    out1 = (base1[0] + perp[0] * depth, base1[1] + perp[1] * depth)
    out2 = (base2[0] + perp[0] * depth, base2[1] + perp[1] * depth)

    if rng.random() < 0.3:
        mid = ((out1[0] + out2[0]) / 2.0, (out1[1] + out2[1]) / 2.0)
        bulge = depth * rng.uniform(0.3, 0.6)
        arc_peak = (mid[0] + perp[0] * bulge, mid[1] + perp[1] * bulge)
        appendage_pts = [base1, out1]
        for t in (0.25, 0.5, 0.75):
            appendage_pts.append((
                (1 - t) ** 2 * out1[0] + 2 * (1 - t) * t * arc_peak[0] + t ** 2 * out2[0],
                (1 - t) ** 2 * out1[1] + 2 * (1 - t) * t * arc_peak[1] + t ** 2 * out2[1],
            ))
        appendage_pts += [out2, base2]
    else:
        appendage_pts = [base1, out1, out2, base2]

    try:
        merged = ShapelyPolygon(polygon).buffer(0).union(ShapelyPolygon(appendage_pts).buffer(0))
        if merged.geom_type == "Polygon":
            return list(merged.exterior.coords)[:-1]
    except Exception:
        pass
    return polygon


def finish_leaves(leaves: List[Polygon], rng) -> List[Polygon]:
    """Per-block finishing pass: notch (always safe -- never grows a
    leaf) then a candidate appendage per leaf, checked against every
    OTHER leaf already finished in this same block; a candidate that
    would overlap a sibling is rejected outright (never shrunk -- the
    appendage is probabilistic in the first place, occasionally skipping
    one for lack of room is an acceptable, minor loss)."""
    finished: List[Polygon] = []
    shapes: List[ShapelyPolygon] = []
    for leaf in leaves:
        notched = notch_corner(leaf, rng)
        candidate = add_appendage(notched, rng)
        candidate_shape = ShapelyPolygon(candidate).buffer(0)
        overlaps = any(candidate_shape.intersection(other).area > 1e-6 for other in shapes)
        final = notched if overlaps else candidate
        finished.append(final)
        shapes.append(ShapelyPolygon(final).buffer(0))
    return finished
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_blocks.py -k "notch_corner or add_appendage or finish_leaves" -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/blocks.py tests/test_blocks.py
git commit -m "$(cat <<'EOF'
feat: add notch/appendage building irregularity with overlap safety

notch_corner shaves a straight-wall L-shaped corner (area-reducing,
always safe). add_appendage attaches a small porch/annex at a slight
angle offset, occasionally curved. finish_leaves runs both per block
and rejects (never shrinks) any appendage that would overlap a
sibling leaf -- resolves the spec's flagged overlap risk.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AMajdcVvM4s56PJmpBMi4g
EOF
)"
```

---

## Task 8: Wire it all together — two-pass residential generation

**Files:**
- Modify: `town_shaper/blocks.py` (`place_buildings_in_block`, `generate_blocks_and_buildings`)
- Modify: `town_shaper/generate.py`
- Test: `tests/test_blocks.py`
- Test: `tests/test_generate.py`

**Interfaces:**
- Consumes: `estimate_household_counts` (Task 2), `compute_district_blocks` (Task 5), `organic_subdivide` (Task 6), `finish_leaves` (Task 7), `BUILDING_HOME_CAPACITY` (existing, `town_shaper/buildings.py`)
- Produces: `place_buildings_in_block(block, district, rng, next_building_id, target_population, magic_prevalence, notable_building_counts, density_multiplier=1.0, target_area=None, hard_cap_area=None) -> List[Building]` (same call shape as today, two new optional kwargs)
- Produces: `generate_blocks_and_buildings(district, town_seed, next_building_id, target_population=0, density_multiplier=1.0, magic_prevalence=0.0, notable_building_counts=None, blocks=None, target_area=None, hard_cap_area=None) -> List[Building]` (same call shape as today, three new optional kwargs)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_blocks.py`:

```python
def test_place_buildings_in_block_footprints_now_set_on_every_building():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 30)

    buildings = place_buildings_in_block(
        block, district, rng, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )

    assert buildings
    for b in buildings:
        assert b.footprint is not None
        assert len(b.footprint) >= 3


def test_place_buildings_in_block_respects_a_caller_supplied_target_area():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(60.0, 60.0)  # area 3600
    district = _district(ZoneType.POOR_RESIDENTIAL)
    rng_small_target = rng_for(("town", 1), "blocks-test", 31)
    small_target = place_buildings_in_block(
        block, district, rng_small_target, 0, target_population=3000, magic_prevalence=0.0,
        notable_building_counts={}, target_area=30.0, hard_cap_area=200.0,
    )
    rng_large_target = rng_for(("town", 1), "blocks-test", 31)
    large_target = place_buildings_in_block(
        block, district, rng_large_target, 0, target_population=3000, magic_prevalence=0.0,
        notable_building_counts={}, target_area=900.0, hard_cap_area=3600.0,
    )

    # A much bigger target area should produce noticeably fewer buildings
    # from the same block.
    assert len(large_target) < len(small_target)


def test_generate_blocks_and_buildings_accepts_precomputed_blocks():
    from town_shaper.blocks import (
        DEFAULT_HARD_CAP_AREA, LOT_DEPTH_BY_ZONE, LOT_FRONTAGE_BY_ZONE,
        compute_district_blocks, generate_blocks_and_buildings,
    )

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(40.0, 20.0)])
    precomputed = compute_district_blocks(district, ("town", 1))

    buildings = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, target_population=3000, magic_prevalence=0.0,
        blocks=precomputed, target_area=LOT_FRONTAGE_BY_ZONE[ZoneType.MERCHANT] * LOT_DEPTH_BY_ZONE[ZoneType.MERCHANT],
        hard_cap_area=DEFAULT_HARD_CAP_AREA,
    )

    assert len(buildings) > 0
```

(Matches this test file's existing convention of local per-function imports for `town_shaper.blocks` names rather than editing the module-level import line.)

Append to `tests/test_generate.py`:

```python
def test_generate_town_residential_building_counts_are_proportional_to_households():
    # Regression guard for the bug that motivated this whole plan: a real
    # test town had 10,436 "residence" buildings for 1,372 households
    # (under 3% occupancy). Building count should now land within a
    # generous multiple of real household demand, not two orders of
    # magnitude over it.
    from town_shaper.buildings import BUILDING_HOME_CAPACITY
    from town_shaper.households import estimate_household_counts
    from town_shaper.models import SES

    town = generate_town(("town", 1), target_population=5000, rich_proportion=0.05)

    household_ses = {}
    for r in town.residents:
        household_ses.setdefault(r.household_id, r.ses)
    poor_households = sum(1 for s in household_ses.values() if s == SES.POOR)
    rich_households = sum(1 for s in household_ses.values() if s == SES.RICH)

    residence_count = sum(
        1 for d in town.districts for b in d.buildings if b.building_type == "residence"
    )
    manor_count = sum(
        1 for d in town.districts for b in d.buildings if b.building_type == "manor"
    )

    # Generous upper bound (2x the raw household count, ignoring capacity
    # and slack entirely) -- the old behavior blew past this by ~8x.
    assert residence_count <= max(1, poor_households) * 2
    assert manor_count <= max(1, rich_households) * 2
    assert residence_count > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_blocks.py tests/test_generate.py -k "target_area or precomputed_blocks or proportional_to_households or now_set_on_every_building" -v`
Expected: FAIL — `place_buildings_in_block`/`generate_blocks_and_buildings` don't yet accept `target_area`/`hard_cap_area`/`blocks` kwargs (`TypeError`), and the household-proportionality test fails against current behavior (residence count wildly exceeds `poor_households * 2`).

- [ ] **Step 3: Rewrite `place_buildings_in_block` and `generate_blocks_and_buildings`**

In `town_shaper/blocks.py`, replace the existing `place_buildings_in_block` function:

```python
def place_buildings_in_block(
    block_polygon: Polygon, district: District, rng,
    next_building_id: int, target_population: int, magic_prevalence: float,
    notable_building_counts: Optional[Dict[str, int]] = None,
    density_multiplier: float = 1.0,
    target_area: Optional[float] = None,
    hard_cap_area: Optional[float] = None,
) -> List[Building]:
    if notable_building_counts is None:
        notable_building_counts = {}

    zone_type = district.zone_type
    if target_area is None:
        target_area = (
            (LOT_FRONTAGE_BY_ZONE[zone_type] / density_multiplier)
            * (LOT_DEPTH_BY_ZONE[zone_type] / density_multiplier)
        )
    if hard_cap_area is None:
        hard_cap_area = DEFAULT_HARD_CAP_AREA

    raw_leaves = organic_subdivide(block_polygon, target_area, hard_cap_area, rng)
    leaves = finish_leaves(raw_leaves, rng)

    buildings: List[Building] = []
    building_id = next_building_id
    for leaf in leaves:
        if polygon_area(leaf) < 1.0:
            continue  # sliver left over from a degenerate cut, not worth a building

        cx, cy, width, height, rotation = _leaf_footprint(leaf)
        building_type = pick_building_type_with_cap(
            zone_type, target_population, magic_prevalence, rng, notable_building_counts,
        )
        capacity = BUILDING_HOME_CAPACITY.get(building_type, 0)
        vacancies = [
            JobVacancy(building_id=building_id, occupation=occupation)
            for occupation, count in JOB_VACANCIES_BY_BUILDING_TYPE[building_type]
            for _ in range(count)
        ]
        name_pool = BUILDING_NAME_POOLS.get(building_type)
        name = rng.choice(name_pool) if name_pool else None

        buildings.append(Building(
            id=building_id,
            district_id=district.id,
            district_zone_type=zone_type,
            x=cx,
            y=cy,
            building_type=building_type,
            capacity=capacity,
            vacancies=vacancies,
            name=name,
            width=width,
            height=height,
            rotation=rotation,
            footprint=leaf,
        ))
        building_id += 1

    return buildings
```

This replaces the old body that called `_subdivide_into_buildings` — that function, along with the module's earlier `_subdivide` free function used only by `subdivide_into_blocks`, is unrelated and stays; only `_subdivide_into_buildings` becomes dead code (`place_buildings_in_block` was its only call site). Delete it entirely from `town_shaper/blocks.py`:

```python
def _subdivide_into_buildings(block_polygon: Polygon, target_area: float, rng, depth: int = 0) -> List[Polygon]:
    if len(block_polygon) < 3 or depth >= MAX_SPLIT_DEPTH or polygon_area(block_polygon) <= target_area:
        return [block_polygon]

    side_a, side_b = _split_polygon(block_polygon, rng, BUILDING_GAP)
    if len(side_a) < 3 or len(side_b) < 3:
        return [block_polygon]

    return (
        _subdivide_into_buildings(side_a, target_area, rng, depth + 1)
        + _subdivide_into_buildings(side_b, target_area, rng, depth + 1)
    )
```

Replace the existing `generate_blocks_and_buildings`:

```python
def generate_blocks_and_buildings(
    district: District, town_seed, next_building_id: int,
    target_population: int = 0, density_multiplier: float = 1.0, magic_prevalence: float = 0.0,
    notable_building_counts: Optional[Dict[str, int]] = None,
    blocks: Optional[List[Polygon]] = None,
    target_area: Optional[float] = None,
    hard_cap_area: Optional[float] = None,
) -> List[Building]:
    rng = rng_for(town_seed, "blocks", district.id)
    if notable_building_counts is None:
        notable_building_counts = {}
    if blocks is None:
        blocks = compute_district_blocks(district, town_seed)

    buildings: List[Building] = []
    building_id = next_building_id

    for block in blocks:
        block_buildings = place_buildings_in_block(
            block, district, rng, building_id, target_population, magic_prevalence,
            notable_building_counts=notable_building_counts, density_multiplier=density_multiplier,
            target_area=target_area, hard_cap_area=hard_cap_area,
        )
        buildings.extend(block_buildings)
        building_id += len(block_buildings)

    return buildings
```

(This drops the old inline `for part in district.polygon_parts: inset_part = ...` loop entirely — `compute_district_blocks` now owns that, called either by the caller up front, via the `blocks=` param, or internally here when not supplied.)

- [ ] **Step 4: Wire the two-pass flow into `town_shaper/generate.py`**

Replace the existing per-district loop body in `generate_town` (`town_shaper/generate.py`):

```python
    notable_building_counts: Dict[str, int] = {}

    for district in districts:
        next_building_id = district.id * BUILDING_ID_STRIDE
        if district.zone_type == ZoneType.FARMLAND_EDGE:
            buildings = fill_district_buildings(
                district, seed, next_building_id,
                target_population=target_population, density_multiplier=density_multiplier,
                magic_prevalence=magic_prevalence,
            )
        else:
            buildings = generate_blocks_and_buildings(
                district, seed, next_building_id,
                target_population=target_population, density_multiplier=density_multiplier,
                magic_prevalence=magic_prevalence, notable_building_counts=notable_building_counts,
            )
        district.buildings = buildings
```

with:

```python
    notable_building_counts: Dict[str, int] = {}

    # Pass 1: block geometry + total area for every residential district
    # (cached, not recomputed in pass 2) -- lets the leaf target area be
    # derived from real household demand instead of a fixed lot constant.
    residential_zone_types = (ZoneType.POOR_RESIDENTIAL, ZoneType.RICH_RESIDENTIAL)
    blocks_by_district_id: Dict[int, list] = {}
    block_area_by_zone: Dict[ZoneType, float] = {zt: 0.0 for zt in residential_zone_types}
    for district in districts:
        if district.zone_type in residential_zone_types:
            district_blocks = compute_district_blocks(district, seed)
            blocks_by_district_id[district.id] = district_blocks
            block_area_by_zone[district.zone_type] += sum(polygon_area(b) for b in district_blocks)

    poor_household_count, rich_household_count = estimate_household_counts(target_population, rich_proportion)
    effective_slack = RESIDENTIAL_SLACK / density_multiplier
    poor_target_count = max(1, math.ceil(poor_household_count * effective_slack / BUILDING_HOME_CAPACITY["residence"]))
    rich_target_count = max(1, math.ceil(rich_household_count * effective_slack / BUILDING_HOME_CAPACITY["manor"]))

    poor_min_leaf_area = LOT_FRONTAGE_BY_ZONE[ZoneType.POOR_RESIDENTIAL] * LOT_DEPTH_BY_ZONE[ZoneType.POOR_RESIDENTIAL]
    rich_min_leaf_area = LOT_FRONTAGE_BY_ZONE[ZoneType.RICH_RESIDENTIAL] * LOT_DEPTH_BY_ZONE[ZoneType.RICH_RESIDENTIAL]
    residential_target_area = {
        ZoneType.POOR_RESIDENTIAL: max(poor_min_leaf_area, block_area_by_zone[ZoneType.POOR_RESIDENTIAL] / poor_target_count),
        ZoneType.RICH_RESIDENTIAL: max(rich_min_leaf_area, block_area_by_zone[ZoneType.RICH_RESIDENTIAL] / rich_target_count),
    }

    for district in districts:
        next_building_id = district.id * BUILDING_ID_STRIDE
        if district.zone_type == ZoneType.FARMLAND_EDGE:
            buildings = fill_district_buildings(
                district, seed, next_building_id,
                target_population=target_population, density_multiplier=density_multiplier,
                magic_prevalence=magic_prevalence,
            )
        elif district.zone_type in residential_zone_types:
            buildings = generate_blocks_and_buildings(
                district, seed, next_building_id,
                target_population=target_population, density_multiplier=density_multiplier,
                magic_prevalence=magic_prevalence, notable_building_counts=notable_building_counts,
                blocks=blocks_by_district_id[district.id],
                target_area=residential_target_area[district.zone_type],
                hard_cap_area=DEFAULT_HARD_CAP_AREA,
            )
        else:
            buildings = generate_blocks_and_buildings(
                district, seed, next_building_id,
                target_population=target_population, density_multiplier=density_multiplier,
                magic_prevalence=magic_prevalence, notable_building_counts=notable_building_counts,
            )
        district.buildings = buildings
```

Add `RESIDENTIAL_SLACK = 1.25` as a new module constant in `town_shaper/blocks.py` (next to `HARD_CAP_AREA_MULTIPLIER`).

`town_shaper/generate.py`'s existing import block is:

```python
import math
from typing import Dict, Tuple

from shapely.ops import unary_union

from town_shaper.anchors import place_anchors
from town_shaper.assignment import DEFAULT_RICH_PROPORTION, assign_residents
from town_shaper.blocks import generate_blocks_and_buildings
from town_shaper.buildings import fill_district_buildings
from town_shaper.districts import build_districts
from town_shaper.households import generate_households
from town_shaper.models import Town, ZoneType
from town_shaper.roads import generate_road_network
from town_shaper.water import generate_water_features
```

Change exactly three of those lines (the other eight — `import math`, `from typing import ...`, `unary_union`, `place_anchors`, `assign_residents`, `build_districts`, `Town, ZoneType`, `generate_road_network`, `generate_water_features` — are untouched):

- `from town_shaper.blocks import generate_blocks_and_buildings` becomes:
  ```python
  from town_shaper.blocks import (
      DEFAULT_HARD_CAP_AREA, LOT_DEPTH_BY_ZONE, LOT_FRONTAGE_BY_ZONE, RESIDENTIAL_SLACK,
      compute_district_blocks, generate_blocks_and_buildings,
  )
  ```
- `from town_shaper.buildings import fill_district_buildings` becomes:
  ```python
  from town_shaper.buildings import BUILDING_HOME_CAPACITY, fill_district_buildings
  ```
- `from town_shaper.households import generate_households` becomes:
  ```python
  from town_shaper.households import estimate_household_counts, generate_households
  ```

And add one new import line (`town_shaper.geometry` isn't imported anywhere in `generate.py` today):

```python
from town_shaper.geometry import polygon_area
```

(`math` itself needs no import change — it's already imported at the top of the file and used by `compute_town_bounds`; the new two-pass code just adds another call site, `math.ceil`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_blocks.py tests/test_generate.py -v`
Expected: PASS. If `test_generate_town_completes_within_time_budget_at_low_thousands_scale` (pre-existing performance test) now fails, this is the "roughly doubles the geometry work" cost flagged in the spec's Performance Note — investigate before loosening the time budget; a real slowdown here is exactly what that note warned to check for.

- [ ] **Step 6: Run the full existing suite**

Run: `pytest tests/ -x -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add town_shaper/blocks.py town_shaper/generate.py tests/test_blocks.py tests/test_generate.py
git commit -m "$(cat <<'EOF'
fix: derive residential building counts from real household demand

The core fix: poor_residential/rich_residential leaf target area is
now computed from estimate_household_counts (analytical, matches
generate_households' own formula) divided across each zone's real
total block area, instead of a fixed lot-area constant that tiled
independently of how many households actually exist. A real test
town had 10,436 residences for 1,372 households; this bounds it to
within 2x real household count. civic/merchant/port unaffected --
same lot-area constant as before, only their subdivision shape
changed (organic_subdivide + finish_leaves, wired in Tasks 6-7).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AMajdcVvM4s56PJmpBMi4g
EOF
)"
```

---

## Task 9: Garden/courtyard cull for residential zones

**Files:**
- Modify: `town_shaper/blocks.py`
- Test: `tests/test_blocks.py`

**Interfaces:**
- Produces: `GARDEN_CULL_FRACTION` (module constant, `blocks.py`)
- Modifies behavior of `generate_blocks_and_buildings` when called for a residential zone (an internal culling step, no new public parameter — see rationale below)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_blocks.py`:

```python
def test_generate_blocks_and_buildings_culls_some_residential_leaves_as_gardens():
    from town_shaper.blocks import compute_district_blocks, generate_blocks_and_buildings

    district = _multi_part_district(ZoneType.POOR_RESIDENTIAL, [_rectangle(80.0, 80.0)])
    blocks = compute_district_blocks(district, ("town", 1))

    # A small target_area forces many leaves from an 80x80 block -- with
    # GARDEN_CULL_FRACTION > 0, the building count should land measurably
    # below the raw leaf count organic_subdivide alone would produce.
    from town_shaper.blocks import DEFAULT_HARD_CAP_AREA, organic_subdivide

    rng_probe = rng_for(("town", 1), "blocks", district.id)
    raw_leaf_count = sum(
        len(organic_subdivide(b, target_area=40.0, hard_cap_area=DEFAULT_HARD_CAP_AREA, rng=rng_probe))
        for b in blocks
    )

    buildings = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, target_population=3000, magic_prevalence=0.0,
        blocks=blocks, target_area=40.0, hard_cap_area=DEFAULT_HARD_CAP_AREA,
    )

    assert 0 < len(buildings) < raw_leaf_count


def test_generate_blocks_and_buildings_does_not_cull_merchant_leaves():
    from town_shaper.blocks import DEFAULT_HARD_CAP_AREA, compute_district_blocks, generate_blocks_and_buildings, organic_subdivide

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(80.0, 80.0)])
    blocks = compute_district_blocks(district, ("town", 1))

    rng_probe = rng_for(("town", 1), "blocks", district.id)
    raw_leaf_count = sum(
        len(organic_subdivide(b, target_area=40.0, hard_cap_area=DEFAULT_HARD_CAP_AREA, rng=rng_probe))
        for b in blocks
    )

    buildings = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, target_population=3000, magic_prevalence=0.0,
        blocks=blocks, target_area=40.0, hard_cap_area=DEFAULT_HARD_CAP_AREA,
    )

    # Merchant/civic/port are NOT culled -- every generated leaf becomes a
    # building (named or infill).
    assert len(buildings) == raw_leaf_count
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_blocks.py -k "culls_some_residential or does_not_cull_merchant" -v`
Expected: FAIL — no culling happens yet, so `len(buildings) == raw_leaf_count` for both zone types (the residential test's `<` assertion fails).

- [ ] **Step 3: Implement the cull**

In `town_shaper/blocks.py`, add the constant near `RESIDENTIAL_SLACK`:

```python
GARDEN_CULL_FRACTION = 0.12
RESIDENTIAL_ZONE_TYPES = (ZoneType.POOR_RESIDENTIAL, ZoneType.RICH_RESIDENTIAL)
```

In `place_buildings_in_block`, after computing `leaves = finish_leaves(raw_leaves, rng)`, add the cull before the `for leaf in leaves:` building-construction loop:

```python
    if zone_type in RESIDENTIAL_ZONE_TYPES:
        leaves = [leaf for leaf in leaves if rng.random() >= GARDEN_CULL_FRACTION]
```

(Culled leaves are simply dropped — never turned into a `Building` row, never rendered specially, per the spec's explicit ruling. `civic`/`merchant`/`port` don't match `RESIDENTIAL_ZONE_TYPES`, so every leaf there still becomes a building, unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_blocks.py -v`
Expected: PASS (all tests, including every earlier task's).

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -x -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add town_shaper/blocks.py tests/test_blocks.py
git commit -m "$(cat <<'EOF'
feat: cull ~12% of residential leaves as unbuilt garden/courtyard gaps

Residential-only (civic/merchant/port stay fully tiled, unaffected).
Culled leaves are simply not turned into Building rows -- no new
building_type, no special rendering; the ground/street color shows
through, per the design spec's explicit ruling.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AMajdcVvM4s56PJmpBMi4g
EOF
)"
```

---

## Task 10: `town_db/render.py` — draw real footprints, drop flat urban zone fill

**Files:**
- Modify: `town_db/render.py`
- Test: `tests/test_db_render.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db_render.py`:

```python
def test_render_town_draws_a_real_footprint_polygon_when_present(tmp_path):
    db_path = str(tmp_path / "town.db")
    output_path = str(tmp_path / "town.png")

    conn = connect(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'poor_residential', ?)",
        (json.dumps([[[0.0, 0.0], [40.0, 0.0], [40.0, 40.0], [0.0, 40.0]]]),),
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, "
        "width, height, rotation, footprint) VALUES (1, 1, 'poor_residential', 'residence', "
        "20.0, 20.0, 6, 5.0, 6.0, 0.0, ?)",
        (json.dumps([[18.0, 17.0], [23.0, 17.0], [23.0, 22.0], [19.0, 22.0], [18.0, 20.0]]),),
    )
    conn.commit()
    conn.close()

    render_town(db_path, output_path)  # must not raise

    with open(output_path, "rb") as f:
        header = f.read(8)
    assert header == b"\x89PNG\r\n\x1a\n"


def test_render_town_falls_back_to_rotated_rect_when_footprint_is_null(tmp_path):
    # Every pre-existing test fixture in this suite inserts buildings
    # without a footprint -- render.py must keep working against them via
    # the width/height/rotation rectangle, not just for new data.
    db_path = str(tmp_path / "town.db")
    output_path = str(tmp_path / "town.png")
    _build_minimal_town(db_path)  # existing helper, no footprint column set

    render_town(db_path, output_path)  # must not raise

    with open(output_path, "rb") as f:
        header = f.read(8)
    assert header == b"\x89PNG\r\n\x1a\n"
```

Add `import json` at the top of `tests/test_db_render.py` if not already present (it already is, per line 1 of the existing file).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db_render.py -k "real_footprint_polygon or falls_back_to_rotated_rect" -v`
Expected: The fallback test likely already passes (current code always uses width/height/rotation). The real-footprint test passes too today since `render_town` doesn't yet read the `footprint` column at all — both currently pass vacuously. This task is about *drawing the real shape*, which isn't asserted by a PNG-header check; move to Step 3 and rely on the full-suite run plus a manual visual check (documented below) rather than inventing a brittle pixel-content assertion.

- [ ] **Step 3: Implement the footprint-aware, fallback-capable rendering**

In `town_db/render.py`, add `footprint` to the buildings query and change the drawing logic. Replace:

```python
    buildings = conn.execute(
        "SELECT x, y, building_type, width, height, rotation FROM buildings"
    ).fetchall()
```

with:

```python
    buildings = conn.execute(
        "SELECT x, y, building_type, width, height, rotation, footprint FROM buildings"
    ).fetchall()
```

Replace the building-drawing loop:

```python
    landmark_points: Dict[str, List[Tuple[float, float]]] = {}
    for x, y, building_type, width, height, rotation in buildings:
        if building_type in LANDMARK_BUILDING_TYPES:
            landmark_points.setdefault(building_type, []).append((x, y))
        else:
            corners = _rotated_rect_corners(x, y, width, height, rotation)
            ax.add_patch(MplPolygon(
                corners, closed=True, facecolor=GENERIC_BUILDING_COLOR, edgecolor="none", zorder=3,
            ))
```

with:

```python
    landmark_points: Dict[str, List[Tuple[float, float]]] = {}
    for x, y, building_type, width, height, rotation, footprint_json in buildings:
        if building_type in LANDMARK_BUILDING_TYPES:
            landmark_points.setdefault(building_type, []).append((x, y))
        else:
            corners = json.loads(footprint_json) if footprint_json else _rotated_rect_corners(x, y, width, height, rotation)
            ax.add_patch(MplPolygon(
                corners, closed=True, facecolor=GENERIC_BUILDING_COLOR, edgecolor="none", zorder=3,
            ))
```

Now drop the flat district-polygon background fill for urban zones. Replace the existing per-district loop:

```python
    seen_zone_types: List[str] = []
    for zone_type, polygon_json in districts:
        color = ZONE_COLORS.get(zone_type, DEFAULT_ZONE_COLOR)
        for ring in json.loads(polygon_json):
            ax.add_patch(MplPolygon(
                ring, closed=True, facecolor=color, edgecolor="black", linewidth=0.5, alpha=0.6, zorder=2,
            ))
        if zone_type not in seen_zone_types:
            seen_zone_types.append(zone_type)
```

with:

```python
    seen_zone_types: List[str] = []
    for zone_type, polygon_json in districts:
        if zone_type == "farmland_edge":
            # Farmland keeps an ambient background tint -- it's not a hard
            # urban boundary the way civic/merchant/residential/port are,
            # and the field-grid look benefits from a background wash.
            color = ZONE_COLORS.get(zone_type, DEFAULT_ZONE_COLOR)
            for ring in json.loads(polygon_json):
                ax.add_patch(MplPolygon(
                    ring, closed=True, facecolor=color, edgecolor="black", linewidth=0.5, alpha=0.6, zorder=2,
                ))
        if zone_type not in seen_zone_types:
            seen_zone_types.append(zone_type)
```

(The legend-building loop further down already iterates `seen_zone_types` independently of whether a flat fill was drawn, so the legend is unaffected — every zone type still gets a swatch. Buildings alone now carry color for urban zones, matching watabou's `CityMap.hx` technique.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db_render.py -v`
Expected: PASS (all tests, old and new).

- [ ] **Step 5: Manual visual check**

Run: `python scripts/generate_town.py` then `python scripts/render_town.py my_town.db my_town_check.png`, and open `my_town_check.png` to confirm real building footprints render (irregular shapes, not clean rectangles) and urban districts no longer show a flat background color behind their buildings. Delete `my_town_check.png` afterward (throwaway check, not a repo artifact).

- [ ] **Step 6: Commit**

```bash
git add town_db/render.py tests/test_db_render.py
git commit -m "$(cat <<'EOF'
feat: render real building footprints, drop flat urban zone fill

Draws the real footprint polygon when present, falling back to the
width/height/rotation rectangle when it's NULL (every pre-existing
test fixture, and farmland forever). Urban zones (civic/merchant/
residential/port) no longer flood-fill a flat background color --
only the buildings themselves carry zone color now, matching
watabou's CityMap.hx technique; farmland keeps its ambient tint.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AMajdcVvM4s56PJmpBMi4g
EOF
)"
```

---

## Task 11: `town_viewer` — footprint in the API, drawn in the canvas

**Files:**
- Modify: `town_viewer/queries.py`
- Modify: `town_viewer/static/app.js`
- Test: `tests/test_viewer_queries.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_viewer_queries.py`:

```python
def test_get_map_data_includes_null_footprint_when_not_set(tmp_path):
    db_path = str(tmp_path / "town.db")
    _build_minimal_map(db_path)

    conn = connect(db_path)
    data = get_map_data(conn)
    conn.close()

    assert data["buildings"][0]["footprint"] is None


def test_get_map_data_includes_a_real_footprint_when_set(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', ?)",
        (json.dumps([[[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]]]),),
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, footprint) "
        "VALUES (1, 1, 'civic', 'temple', 10.0, 10.0, 0, ?)",
        (json.dumps([[8.0, 8.0], [12.0, 8.0], [12.0, 12.0], [8.0, 12.0]]),),
    )
    conn.commit()

    data = get_map_data(conn)
    conn.close()

    assert data["buildings"][0]["footprint"] == [[8.0, 8.0], [12.0, 8.0], [12.0, 12.0], [8.0, 12.0]]


def test_get_building_detail_includes_null_footprint_when_not_set(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    building = get_building_detail(conn, 4)
    conn.close()

    assert building["footprint"] is None
```

Note: `test_get_map_data_returns_districts_buildings_and_water` (existing test, line 34-43 of `tests/test_viewer_queries.py`) asserts an exact `data["buildings"]` dict that will need `"footprint": None` added to match the new field — update that literal dict in place rather than leaving it to fail:

```python
    assert data["buildings"] == [
        {
            "id": 1, "district_id": 1, "zone_type": "civic", "building_type": "temple",
            "x": 10.0, "y": 10.0, "name": None,
            "width": 0.0, "height": 0.0, "rotation": 0.0, "footprint": None,
        }
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_viewer_queries.py -v`
Expected: FAIL — `KeyError: 'footprint'` on the new tests, and the updated exact-dict test fails until `queries.py` is changed (temporarily leave the dict-literal edit uncommitted until Step 3 lands, or accept it fails in this run — either is fine, this is the "write the failing test" step).

- [ ] **Step 3: Implement**

In `town_viewer/queries.py`, update `get_map_data`:

```python
def get_map_data(conn: sqlite3.Connection) -> Dict[str, Any]:
    districts = [
        {"id": row[0], "zone_type": row[1], "polygon": json.loads(row[2])}
        for row in conn.execute("SELECT id, zone_type, polygon FROM districts")
    ]
    buildings = [
        {
            "id": row[0], "district_id": row[1], "zone_type": row[2], "building_type": row[3],
            "x": row[4], "y": row[5], "name": row[6],
            "width": row[7], "height": row[8], "rotation": row[9],
            "footprint": json.loads(row[10]) if row[10] else None,
        }
        for row in conn.execute(
            "SELECT id, district_id, zone_type, building_type, x, y, name, width, height, rotation, footprint "
            "FROM buildings"
        )
    ]
```

(leave the rest of `get_map_data` unchanged.)

Update `get_building_detail`:

```python
    row = conn.execute(
        "SELECT id, district_id, zone_type, building_type, x, y, capacity, name, width, height, rotation, footprint "
        "FROM buildings WHERE id = ?",
        (building_id,),
    ).fetchone()
    if row is None:
        return None

    building = {
        "id": row[0], "district_id": row[1], "zone_type": row[2], "building_type": row[3],
        "x": row[4], "y": row[5], "capacity": row[6], "name": row[7],
        "width": row[8], "height": row[9], "rotation": row[10],
        "footprint": json.loads(row[11]) if row[11] else None,
    }
```

(leave the rest of `get_building_detail` unchanged.)

In `town_viewer/static/app.js`, update the building-drawing loop in `draw()`. Replace:

```javascript
  for (const building of mapData.buildings) {
    const { sx, sy } = worldToScreen(building.x, building.y);
    ctx.save();
    ctx.translate(sx, sy);
    ctx.rotate(building.rotation);
    const screenWidth = building.width * view.scale;
    const screenHeight = building.height * view.scale;
    ctx.fillStyle = buildingColor(building.building_type);
    ctx.fillRect(-screenWidth / 2, -screenHeight / 2, screenWidth, screenHeight);
    ctx.restore();
  }
```

with:

```javascript
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
```

(Hit-testing in `findBuildingAt` and the highlight-drawing loop deliberately keep using `width`/`height`/`rotation` as an approximate bounding box — real point-in-polygon hit-testing against `footprint` is a nice-to-have, not required by anything in the design spec's scope, and `width`/`height`/`rotation` are still populated as the real footprint's own OBB, so the approximation is reasonable.)

Also update `draw()`'s district-fill loop to drop the flat urban-zone fill, matching Task 10's `render.py` change:

```javascript
  ctx.globalAlpha = 0.6;
  for (const water of mapData.water_features) drawPolygon(water.polygon, WATER_COLOR, null);
  for (const district of mapData.districts) {
    if (district.zone_type !== "farmland_edge") continue;
    const color = ZONE_COLORS[district.zone_type] || DEFAULT_ZONE_COLOR;
    drawPolygon(district.polygon, color, "black");
  }
  ctx.globalAlpha = 1;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_viewer_queries.py -v`
Expected: PASS (all tests, old and new).

- [ ] **Step 5: Manual check of the viewer**

Run: `python -m town_viewer.app my_town.db` (check `town_viewer/app.py`'s actual CLI invocation first — match however it's normally started, e.g. via a `scripts/` wrapper if one exists) and open it in a browser to confirm buildings render as real irregular polygons and urban zones no longer show a flat background fill.

- [ ] **Step 6: Commit**

```bash
git add town_viewer/queries.py town_viewer/static/app.js tests/test_viewer_queries.py
git commit -m "$(cat <<'EOF'
feat: draw real building footprints in the interactive viewer

Mirrors the render.py change: footprint (when present) is drawn as
the real polygon; falls back to the width/height/rotation rectangle
otherwise. Urban zones no longer flood-fill a flat background color.
Hit-testing/highlighting deliberately keep using the width/height
bounding box -- real point-in-polygon hit-testing is a nice-to-have
outside this spec's scope, and width/height still reflect the real
footprint's own OBB.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AMajdcVvM4s56PJmpBMi4g
EOF
)"
```

---

## Task 12: Full regression, determinism sweep, performance check

**Files:** none (verification-only task)

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -q`
Expected: PASS, zero failures.

- [ ] **Step 2: Determinism sweep**

Run this inline check (not a persisted test file — a one-off verification, matching every prior plan's final task in this repo):

```bash
python -c "
from town_shaper.generate import generate_town

town1 = generate_town(('town', 42), target_population=5000, rich_proportion=0.05)
town2 = generate_town(('town', 42), target_population=5000, rich_proportion=0.05)

key = lambda b: (b.id, b.x, b.y, b.building_type, tuple(b.footprint) if b.footprint else None)
buildings1 = [key(b) for d in town1.districts for b in d.buildings]
buildings2 = [key(b) for d in town2.districts for b in d.buildings]
assert buildings1 == buildings2, 'non-deterministic building generation'
print(f'OK: {len(buildings1)} buildings, fully deterministic across two runs')
"
```

Expected: `OK: <N> buildings, fully deterministic across two runs`, no `AssertionError`.

- [ ] **Step 3: Performance and density sanity check at realistic scale**

Run:

```bash
python -c "
import time
from town_shaper.generate import generate_town
from town_shaper.models import SES

for pop in (5000, 10000):
    start = time.monotonic()
    town = generate_town(('town', 1), target_population=pop, rich_proportion=0.05)
    elapsed = time.monotonic() - start

    household_ses = {}
    for r in town.residents:
        household_ses.setdefault(r.household_id, r.ses)
    poor_hh = sum(1 for s in household_ses.values() if s == SES.POOR)
    rich_hh = sum(1 for s in household_ses.values() if s == SES.RICH)
    residence_count = sum(1 for d in town.districts for b in d.buildings if b.building_type == 'residence')
    manor_count = sum(1 for d in town.districts for b in d.buildings if b.building_type == 'manor')
    total_buildings = sum(len(d.buildings) for d in town.districts)

    print(f'pop={pop}: {elapsed:.1f}s, {total_buildings} buildings '
          f'({residence_count} residence / {poor_hh} poor households, '
          f'{manor_count} manor / {rich_hh} rich households)')
"
```

Expected: both runs complete in a reasonable time (compare against the existing `test_generate_town_completes_within_time_budget_at_low_thousands_scale` budget in `tests/test_generate.py` — if generation at pop=10000 is noticeably slower than that test's budget implies for pop=3000, scaled up, that's the two-pass residential flow's real cost showing up per the spec's Performance Note; if it's egregious, consider caching `compute_district_blocks`' shapely OBB/union calls, but don't preemptively optimize without evidence it's actually a problem here) and `residence_count`/`manor_count` land within a small multiple (not orders of magnitude) of `poor_hh`/`rich_hh`.

- [ ] **Step 4: Generate and visually inspect a real town**

Run: `python scripts/generate_town.py` then `python scripts/render_town.py my_town.db my_town_final_check.png`, and view the image to confirm it matches the approved mockup direction from the design spec (organic building shapes, no flat zone fill, reasonable residential density). Delete `my_town_final_check.png` afterward.

- [ ] **Step 5: Final commit (only if any of the above steps required code fixes)**

If everything passed clean, there's nothing to commit for this task — it's verification-only. If Step 3's performance check or Step 4's visual check surfaced a real bug, fix it, add a regression test in the relevant existing test file from an earlier task, and commit:

```bash
git add -A
git commit -m "$(cat <<'EOF'
fix: <describe the specific issue found during final regression pass>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AMajdcVvM4s56PJmpBMi4g
EOF
)"
```
