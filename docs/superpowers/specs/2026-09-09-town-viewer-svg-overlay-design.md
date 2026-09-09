# Interactive Town Viewer: Real SVG Overlay — Design

## Context

The settlemaker migration (`2026-09-08-settlemaker-integration*` docs)
replaced TownShape's own matplotlib renderer with settlemaker's own
themed SVG, persisted alongside every generated town's `.db` file. It
looks good — real walls, streets, farmland texture, per-building
glyphs.

`town_viewer/` (the interactive Flask + canvas app: pan/zoom, click a
building or resident for detail, search) was never touched by that
migration and never got that visual upgrade. It draws its own flat
canvas shapes from `town_viewer/static/app.js`'s `buildingColor()`: a
handful of hardcoded colors for landmark types (`temple`, `tavern`,
`shop`, ...) and `GENERIC_BUILDING_COLOR = "#555555"` — flat dark gray —
for everything else, i.e. every ordinary house. Flagged by the user
2026-09-09, comparing a viewer screenshot against the settlemaker SVG
shown earlier the same session ("this looks much, much poorer quality
than what you showed me previously"). Logged in
`Project_Vision/03-visualization-layer.md`.

**Decision (this session, 2026-09-09):** render settlemaker's actual
persisted SVG as the map itself, with the viewer's existing
click/search interactivity layered on top — not a nicer version of the
flat canvas style. This document designs that.

## Scope

**In scope:**
- Persisting one new piece of data per town (settlemaker's own
  `metadata.local_bounds`) so the SVG can be positioned/scaled to align
  exactly with the coordinates already stored for districts/buildings.
- A new route serving the persisted `.svg` file.
- Reworking `town_viewer/static/app.js` to render that SVG, inline,
  positioned via a CSS transform kept in sync with the existing
  pan/zoom state, instead of drawing water/farmland/building fills
  itself.
- Graceful fallback to today's flat rendering for any `.db` generated
  before this change (no migration exists in this project — see Risks).

**Out of scope:**
- Any change to how `.svg` files are generated or what they contain —
  this only consumes the existing settlemaker output.
- Any change to click hit-testing, pan/zoom math, the resident search
  panel, or the building/resident detail API endpoints — all already
  work off stored coordinate/footprint data, independent of how the
  map is drawn.
- The selection highlight (`#ff2222` outline traced through a
  building's real footprint) stays exactly as it is today — it already
  draws in world coordinates via the same transform this document
  extends, not something this document changes.
- Backfilling `local_bounds` for already-generated `.db` files. Decided
  explicitly this session: not worth the ~1% imprecision a
  district-bounds-derived approximation would carry (see Architecture);
  older towns simply keep today's rendering.

## Data Model

Four new nullable columns on `town_state` (`town_db/schema.py`) — the
existing per-town singleton metadata table (`year_start`,
`current_date`, `aggression`, `magic_prevalence` already live there):

```sql
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

Nullable, not `NOT NULL`: this project has no migration system (schema
is only ever created fresh, at generation time — see Risks), so a `.db`
generated before this change simply won't have these columns at all.
Making them nullable (rather than requiring a value) keeps the *new*
generation path simple; the *old-`.db`* compatibility problem is
handled at the query layer instead (Architecture, below), because a
missing column raises `sqlite3.OperationalError`, not a null read.

`town_shaper/models.py`'s `Town` dataclass gains four matching fields,
same additive-default pattern as `Town.svg` from the earlier migration:

```python
@dataclass
class Town:
    ...
    svg: str = ""
    svg_min_x: Optional[float] = None
    svg_min_y: Optional[float] = None
    svg_max_x: Optional[float] = None
    svg_max_y: Optional[float] = None
```

## Architecture

### Capturing `local_bounds`

`settlemaker_bridge/pipeline.py`'s `generate_via_settlemaker` already
extracts `result["svg"]` from settlemaker's response right next to
`result["geojson"]`; `result["geojson"]["metadata"]["local_bounds"]` is
sitting right there too, just never read for this purpose (Phase 1's
water-scaling code already reads a *dry-run* call's `local_bounds` for
an unrelated reason — this is the *real* call's `local_bounds`, kept
for a different purpose). Its return type gains one element:

```python
def generate_via_settlemaker(...) -> Tuple[List[District], List[Building], List[WaterFeature], str, Dict[str, float]]:
    ...
    local_bounds = result["geojson"]["metadata"]["local_bounds"]
    return districts, buildings, scaled_water_features, result["svg"], local_bounds
```

`town_shaper/generate.py`'s `generate_town()` captures it onto the four
new `Town` fields; `town_db/generate.py`'s `generate_town_database()`
writes them into the `town_state` INSERT (nullable, so this needs no
special-casing — the existing four-column INSERT just grows to eight
placeholders).

### Why one formula covers both settlemaker engines

Verified empirically against real generated towns this session, not
assumed:

- **Burg mode:** SVG path coordinates *are* world coordinates — no
  scale, no offset. Measured: `local_bounds` `(-105.4897, -102.599,
  105.479, 102.389)` against a real SVG `viewBox="-105.5 -102.6 211.0
  205.0"` — scale `1.0001`/`1.0000` (rounding only), origins matching
  to the same precision.
- **Village mode:** a real internal scale exists. Measured: district
  bounds (== `local_bounds`, since `_parse_village_geojson` already
  sets the district's `polygon_parts` to the full `local_bounds`
  rectangle) of width/height `617.18`/`672.94` against a real SVG
  `viewBox="0 0 2468.72 2691.77"` — scale `4.000007`/`4.000001` in each
  axis, origin at the viewBox's own `(0, 0)`.

One formula covers both, because it never assumes which case it's in —
it only uses `local_bounds` (now persisted) and the SVG's own `viewBox`
attribute (parsed from the fetched SVG's markup, client-side, not
persisted separately — one fewer thing to keep in sync):

```
scale = viewBox.width / (local_bounds.max_x - local_bounds.min_x)   // and the y equivalent
svg_x = (world_x - local_bounds.min_x) * scale + viewBox.min_x
```

For burg mode this reduces to `svg_x = world_x` (scale `1`, and
`viewBox.min_x == local_bounds.min_x` cancels the rest); for village
mode it's the real `× 4` relationship. The formula doesn't need to know
which engine produced the town.

### Serving the SVG

`town_viewer/app.py`'s `create_app(db_path)` already knows `db_path`;
the `.svg` path is always derivable from it (`splitext(db_path)[0] +
".svg"`, the same convention `generate_town_database`'s `svg_path`
default already uses) — no new parameter. New route:

```python
@app.get("/api/town.svg")
def town_svg():
    svg_path = os.path.splitext(db_path)[0] + ".svg"
    return send_from_directory(os.path.dirname(svg_path), os.path.basename(svg_path))
```

### Old `.db` files: the graceful-fallback query

`town_viewer/queries.py`'s `get_map_data` reads the four new columns
and returns `null` for `local_bounds` (not an error) when they don't
exist:

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

`/api/map`'s response gains a `"local_bounds"` key holding this result
(or `null`).

### Frontend: `town_viewer/static/app.js`

- On town load, if `mapData.local_bounds` is non-null: fetch
  `/api/town.svg` as text (not as an `<img src>` — inline markup, so a
  single wrapping `<div>`'s CSS `transform` can position it, and there's
  no cross-document id collision risk since only one town's SVG is ever
  shown at a time), inject it into an absolutely-positioned layer behind
  the canvas, and parse its own `viewBox` attribute (one regex, same
  pattern already used server-side in this session's investigation) to
  compute the scale/offset above.
- A new `updateSvgTransform()` — called wherever pan/zoom state
  (`view.scale`, `view.offsetX`, `view.offsetY`) already changes today
  — applies `transform: translate(...) scale(...)` to that wrapper,
  composing the world→SVG formula above with the existing
  `worldToScreen` transform, so the SVG visually tracks pan/zoom
  pixel-for-pixel without redrawing anything (cheap; the browser
  handles the actual scaling).
- `draw()` drops its water-feature, farmland-district, building-fill,
  and road-drawing loops — all now redundant, since the real SVG
  already draws water, fields, buildings, and walls correctly. It keeps
  exactly the selection-highlight loop (the `#ff2222` outline through a
  building's stored footprint), unchanged.
- If `mapData.local_bounds` is `null`: skip all of the above, keep
  today's `draw()` exactly as it is now. One `if`, not two code paths
  to maintain long-term — the old path doesn't grow new logic, it's
  just what already exists today, gated behind the null check.

## Determinism & Testing

- No new randomness anywhere in this document — `local_bounds` is
  read-through data from settlemaker's own deterministic response, not
  generated.
- Backend: a test asserting `generate_town_database` writes
  `svg_min_x`/etc. matching the real settlemaker response's
  `local_bounds` for both a burg-scale and a village-scale town (the
  same two-engine split verified manually this session, now pinned by
  a test). A test asserting `get_map_data` returns `local_bounds: null`
  (not an error) against a `town_state` row created via the *old*
  four-column schema, proving the fallback path.
- Frontend: no existing JS test infrastructure in this project
  (`town_viewer` has no test framework configured beyond the Python
  API's own `tests/test_viewer_*.py`) — this document doesn't propose
  adding one just for this feature. The transform math itself is proven
  by the measurements above, not by new JS tests; visual correctness
  (does the SVG really line up with clickable buildings) is a "look at
  it" verification step, not an automatable one, same as every prior
  visual checkpoint in this project's history.

## Risks / Open Questions

- **No migration system, by design, elsewhere in this project too.**
  This isn't a new pattern introduced here — `town_db/schema.py` has
  never had an `ALTER TABLE` path; every schema change so far has been
  "new `.db` files get it, old ones don't." This document follows that
  existing convention rather than introducing migrations just for this
  feature.
- **The `viewBox` regex is a real, if small, coupling to settlemaker's
  SVG output format.** If a future settlemaker version changed how it
  writes the `viewBox` attribute (unlikely — it's a standard SVG
  attribute, not a settlemaker-specific convention), the fallback
  (`local_bounds` present but `viewBox` unparseable) should behave the
  same as the "old `.db`" case: skip the overlay, keep flat rendering,
  not crash the viewer.
- **Both scale relationships were measured against one real town each**
  (one burg-scale, one village-scale), not swept across many seeds/
  populations. Worth a wider sweep during implementation if either
  formula doesn't hold up on a second real town — but the burg case in
  particular (`scale == 1` exactly) is unlikely to be a coincidence
  specific to one seed, since it falls directly out of settlemaker
  using the same coordinate system for both its GeoJSON and SVG output
  by construction, not by a per-town computed factor.
