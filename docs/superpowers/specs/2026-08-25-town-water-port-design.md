# Town Water & Port Features — Design

## Context

This is sub-slice **1b** of capability 1 ("narrative-to-parameters
generation") from `../../../Agent_Control_Doc.md` — see
`2026-08-24-town-narrative-parameters-design.md` (1a) for the full
capability breakdown. 1a is done and merged: it established the
`town_narrative.parameters.TownParameters` dataclass and the
`generate_town_from_parameters(params, db_path)` orchestrator, both of
which this slice extends.

1b adds rivers and coastline as real geometry in Town Shaper's spatial
model — carving unbuildable space out of districts, the way an actual
river would — plus a port district with dock/warehouse buildings.

## Scope

New module `town_shaper/water.py`. Changes to `town_shaper/anchors.py`,
`town_shaper/districts.py`, `town_shaper/buildings.py`,
`town_shaper/generate.py`, `town_shaper/models.py`,
`town_narrative/parameters.py`, `town_narrative/generate.py`,
`town_db/schema.py`, `town_db/generate.py`, and
`docs/narrative-town-parameters.md`. New dependency: **Shapely**.

Out of scope: bridges/landmass connectivity (resident-to-workplace
assignment in `assignment.py` is purely capacity-based with no spatial
pathing — a river splitting the town into disjoint landmasses has no
simulation effect today, so connectivity is not modeled); multiple
independent water bodies interacting narratively (e.g. named rivers);
magic/aggression/stress (1c/1d, separate specs).

## Data Model

### `TownParameters` additions (`town_narrative/parameters.py`)

```python
num_rivers: int = 0
has_coastline: bool = False
has_port: bool = False
```

Validated in `__post_init__`:
- `num_rivers >= 0`
- `has_port` requires `num_rivers > 0 or has_coastline` — raises
  `ValueError` otherwise (a port needs water to sit on)

No upper bound on `num_rivers`: an extreme value on a small town is
allowed to degrade gracefully (very small/empty districts, few
buildings) rather than raise, matching 1a's existing tolerance for
extreme `density_multiplier`/`area_per_resident_multiplier` combinations
leaving residents unhoused.

### `WaterFeature` (new, `town_shaper/models.py`)

```python
@dataclass
class WaterFeature:
    id: int
    kind: str  # "river" | "coastline"
    polygon: "shapely.geometry.Polygon"
```

### `Town` gains `water_features: List[WaterFeature]`

### `District.polygon` → `District.polygon_parts`

```python
polygon_parts: List[List[Tuple[float, float]]]
```

Replaces the single-ring `polygon: List[Tuple[float, float]]` field.
Almost always length 1; length 0 if a district ends up fully submerged
(rare, since anchor placement avoids water — see below); length 2+ if a
water feature bisects a district's Voronoi cell. This is a breaking
rename with no external consumers (confirmed: only `buildings.py`,
`town_db/generate.py`, and this repo's own tests read `District.polygon`
today), so no compatibility shim is added.

### `water_features` table (new, `town_db/schema.py`)

```sql
CREATE TABLE water_features (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    polygon TEXT NOT NULL
);
```

`polygon` is a JSON-encoded single ring (`[[x, y], ...]`), matching the
existing `districts.polygon` convention. One row per `WaterFeature`.

### `districts.polygon` format change

Same column, new JSON shape: a list of rings
(`[[[x, y], ...], [[x, y], ...]]`) instead of a flat point list, to
match `polygon_parts`. No migration path — this is a generator, not a
schema that evolves under existing data.

### `generation_parameters` table gains

```sql
num_rivers INTEGER NOT NULL,
has_coastline INTEGER NOT NULL,
has_port INTEGER NOT NULL
```

Booleans as `0`/`1`, matching the existing `residents.is_noble`
convention.

## Water Feature Generation (`town_shaper/water.py`)

```python
def generate_water_features(
    seed, bounds: Tuple[float, float, float, float],
    num_rivers: int, has_coastline: bool,
) -> List[WaterFeature]:
```

Called from `generate_town` immediately after `compute_town_bounds`,
before anchor placement — everything downstream (anchor water-avoidance,
port anchor placement, district clipping) depends on knowing where water
is.

**River** *i* (`kind="river"`): via `rng_for(seed, "water", "river", i,
...)`, pick two distinct edges of the bounds rectangle and a random
point on each. Generate 2–3 intermediate waypoints jittered
perpendicular to the straight line between those two points, for a
gentle curve (not a straight line — the strip must actually bend).
Build a Shapely `LineString` through start → waypoints → end, then
`.buffer(RIVER_WIDTH / 2)` to produce a strip `Polygon`.

**Coastline** (`kind="coastline"`, at most one): via `rng_for(seed,
"water", "coastline", ...)`, pick one bounds edge, build a jittered line
roughly parallel to it at some depth into the bounds, and buffer/extend
it so the full area between that line and the chosen edge is water
(reusing the same curved-strip machinery as a river, anchored to one
edge and extended past the far side — not a separate geometric
representation).

Returns one `WaterFeature` per river, plus one more if `has_coastline`.
The function does **not** pre-union them — callers needing "all water as
one shape" (anchor placement, district clipping) call
`shapely.ops.unary_union` themselves, so each feature stays
independently identifiable for the `water_features` table.

`RIVER_WIDTH` (and the coastline's depth-into-bounds constant) are fixed
module constants for this slice, not caller-supplied parameters — no
narrative language naturally maps to "river width," and YAGNI applies
per this project's established light-touch-forward-compatibility norm.

## Anchor Placement Changes (`town_shaper/anchors.py`)

`ZoneType.PORT` is added to `models.py`'s `ZoneType` enum. Its anchor is
**not** carved out of `ZONE_PROPORTIONS` (which must keep summing to 1.0
across the original 5 zones — an existing, tested invariant). Instead:

```python
def place_anchors(
    town_seed, target_population, bounds,
    water_polygon=None,  # unary_union of all WaterFeature polygons, or None
    has_port=False,
) -> List[Anchor]:
```

- **Non-port anchors** (existing radius-band method, unchanged when
  `water_polygon is None`): after computing `(x, y)`, if `water_polygon`
  is given and the point falls inside it, resample (same
  rejection-sampling shape as `poisson_disc_fill`) up to a capped number
  of attempts; if still unresolved, clamp to the nearest point outside
  water.
- **Port anchor** (exactly one, when `has_port`): sample candidate points
  along `water_polygon.exterior.interpolate(...)`, discard candidates
  that lie on the outer town-bounds rectangle itself (that's where a
  river exits the map, not a bank), nudge each surviving candidate a
  fixed distance away from the water polygon so it lands on land, and
  pick one via `rng_for(town_seed, "anchors", "port")`. One anchor
  regardless of population — real towns generally have a single port
  district; no new population-scaled divisor constant is introduced for
  this MVP.

`ZONE_RADIUS_BANDS` does not gain a `PORT` entry — port placement is
water-relative, not center-relative, so it bypasses the radius-band path
entirely.

## District Generation Changes (`town_shaper/districts.py`)

`build_districts` gains an optional `water_polygon` (unary union of all
`WaterFeature` polygons, or `None`). After the existing Voronoi +
bounds-clip step (unchanged), each district's polygon is additionally
run through Shapely's `.difference(water_polygon)` when water is
present. The result populates `polygon_parts`:
- `Polygon` → one-element list
- `MultiPolygon` → one element per part
- empty → `[]`

## Building Fill Changes (`town_shaper/buildings.py`)

`fill_district_buildings` operates over `district.polygon_parts` instead
of a single polygon:

1. Compute area per part; sum for the density-driven `target_count`
   (unchanged formula, applied to the total).
2. Split `target_count` across parts proportional to area, using
   largest-remainder rounding (same pattern as
   `anchors.compute_anchor_counts`) so counts are deterministic and sum
   exactly to `target_count`.
3. Run `poisson_disc_fill` independently per part against that part's
   own polygon.
4. When total area is 0 (fully-submerged district), skip fill entirely
   and return `[]` — relaxes today's `target_count = max(1, round(area *
   density))` floor, which would otherwise force a phantom minimum count
   that Poisson-disc filling could never place against an empty polygon.

**New `ZoneType.PORT` entries**, styled like the existing zone dicts —
no historical reference document backs these (unlike the
demographics-PDF-grounded constants elsewhere in this project), flagged
as reasonable defaults open to tuning:

```python
BUILDING_DENSITY_PER_AREA[ZoneType.PORT] = 1 / 250   # dense, like MERCHANT
MIN_BUILDING_SPACING[ZoneType.PORT] = 8.0             # like MERCHANT

BUILDING_TYPES_BY_ZONE[ZoneType.PORT] = {
    "dock": 0.4, "warehouse": 0.35, "harbormaster_office": 0.25,
}

JOB_VACANCIES_BY_BUILDING_TYPE additions:
    "dock": [("dockworker", 3)],
    "warehouse": [("warehouse_clerk", 1), ("laborer", 2)],
    "harbormaster_office": [("harbormaster", 1), ("customs_clerk", 2)],
```

No `BUILDING_HOME_CAPACITY` entries — none of these are housing, same
treatment as `shop`/`tavern`/etc.

## `generate_town` / `generate_town_database` / `generate_town_from_parameters`

`generate_town` (`town_shaper/generate.py`) gains `num_rivers: int = 0`,
`has_coastline: bool = False`, `has_port: bool = False`, threading them
through in order: `generate_water_features` → `place_anchors` (with the
unioned water polygon and `has_port`) → `build_districts` (with the same
water polygon) → `fill_district_buildings` (unchanged call, now
operating on `polygon_parts` internally) → `assign_residents`
(unchanged). `Town.water_features` is populated from the
`generate_water_features` result.

`generate_town_database` (`town_db/generate.py`) gains the same three
parameters, passed straight through, plus writes to the new
`water_features` table alongside its existing `districts`/`buildings`
inserts, and serializes `district.polygon_parts` as the new list-of-rings
JSON shape.

`generate_town_from_parameters` (`town_narrative/generate.py`) passes
`params.num_rivers`, `params.has_coastline`, `params.has_port` through
and includes them in the `generation_parameters` insert.

## Narrative-Mapping Workflow (`docs/narrative-town-parameters.md`)

New fields section and language-table rows:

| Narrative language | Field | Suggested value |
|---|---|---|
| "a river runs through it", "on the river", "riverside" | `num_rivers` | 1 |
| "where two rivers meet", "at the confluence" | `num_rivers` | 2 |
| (no river cue) | `num_rivers` | 0 (default) |
| "coastal", "seaside", "on the coast/sea" | `has_coastline` | `true` |
| (no coastal cue) | `has_coastline` | `false` (default) |
| "port town", "trading port", "harbor" | `has_port` | `true`, defaulting `has_coastline=true` as the implied water source unless the narrative specifies a river port |

Same standing rule as 1a: when narrative input doesn't clearly resolve,
ask the user directly, state the recommended default and why.

## Error Handling & Edge Cases

- `has_port=True` with `num_rivers=0` and `has_coastline=False` raises
  `ValueError` from `TownParameters.__post_init__`, before any
  generation work starts.
- No upper-bound validation on `num_rivers` (see Data Model) — extreme
  values degrade gracefully rather than erroring.
- A district fully submerged by water (`polygon_parts == []`) is not an
  error: it simply contributes 0 buildings and, transitively, is never
  selected as a home/workplace by `assignment.py` (already true for any
  district with `capacity == 0` or no vacancies).
- `generate_water_features` failing to find a valid PORT anchor position
  after the capped resampling attempts (e.g. an absurdly small water
  polygon) falls back the same way non-port anchors do: clamp to the
  nearest valid point outside water, rather than raising.

## Testing Strategy

- **`TownParameters` validation**: `num_rivers < 0` raises;
  `has_port=True` with no water raises; a fully-valid set with water
  constructs successfully; defaults (`0`, `False`, `False`) reproduce
  1a's exact current behavior with no water generated.
- **`water.py`**: same seed + params → identical `WaterFeature` list
  (determinism); a river's polygon is not a simple rectangle (curvature
  assertion — e.g. checking the buffered strip's bounding geometry isn't
  axis-aligned/straight); a coastline touches its chosen bounds edge and
  has no gap to it; `num_rivers=0, has_coastline=False` → `[]`.
- **`anchors.py`**: `has_port=True` adds exactly one `PORT` anchor
  without changing counts for the other 5 zones (existing sum-to-1 test
  still passes unmodified); a water polygon covering a known anchor band
  causes resampling to avoid it (no anchor lands inside water, for a
  fixed seed and a contrived water shape).
- **`districts.py`**: a water strip placed directly through a known
  anchor's Voronoi cell (contrived bounds/water for determinism)
  produces a multi-part `polygon_parts`; a district fully inside a
  contrived water polygon produces `[]`.
- **`buildings.py`**: multi-part fill splits `target_count`
  proportionally to part area and sums to the same total as a
  single-part district of equal total area; a zero-area district
  produces `[]` with no exception.
- **End-to-end determinism**: `generate_town`/`generate_town_from_parameters`
  with `num_rivers=1, has_coastline=True, has_port=True` on a fixed seed
  produces byte-identical output across two runs; `water_features` table
  has the expected row count; at least one `PORT`-zone district with
  `dock`/`warehouse`/`harbormaster_office` buildings exists; `PRAGMA
  foreign_key_check` is clean.
- **Backward compatibility**: calling all changed functions with no new
  arguments (defaults `num_rivers=0, has_coastline=False,
  has_port=False`) produces byte-identical output to before this change,
  for a fixed seed — regression guard, same as 1a's own backward-
  compatibility test.

## Out of Scope for This Spec

- Bridges or any landmass-connectivity modeling (see Scope).
- Magic prevalence, aggression/stress (1c/1d — separate specs).
- Narrative language for river/coastline *characteristics* beyond
  presence/count (width, name, water quality, etc.) — `RIVER_WIDTH` and
  the coastline depth constant are fixed, not parameterized.
- Multiple independent, narratively-distinct water bodies (e.g. "the
  Sernan river" vs. "the old canal") — `water_features` rows are
  geometry-only, with no name/identity field.
- Any rendering/visualization of water — this project has no rendering
  layer yet for districts or buildings either.
