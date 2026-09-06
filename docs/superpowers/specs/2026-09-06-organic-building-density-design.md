# Organic Building Density & Shape — Design

## Context

Follow-up to `docs/superpowers/specs/2026-09-04-organic-town-rendering-design.md`,
which fixed streets (inset negative-space instead of drawn lines) and made
blocks fully tile with real building footprints. Comparing a fresh render
against watabou's `TownGeneratorOS` and a richer reference city map (a
watabou devlog screenshot, stylistically different from the OSS renderer —
full painterly color, irregular building fronts, tree/garden texture)
surfaced three remaining gaps, confirmed against a real generated town
(seed `watabou-compare`, population 5000) before this spec was written,
per the user's standing mockup-first practice — five mockup rounds were
built and approved live in-session:

1. **Building counts vastly exceed real household demand.** The test town
   had 5,050 living residents in 1,372 households, but 11,631 buildings —
   10,436 of them plain `residence` (capacity 6 each, ~62,600 housing
   slots for 1,372 households, under 3% occupancy). `place_buildings_in_block`
   fully tiles a block down to a fixed `LOT_FRONTAGE_BY_ZONE ×
   LOT_DEPTH_BY_ZONE` area with zero awareness of how many households
   actually exist — total count is an accident of area ÷ lot-size, not a
   real demand signal. This is a different, deeper gap than the
   named/notable-business overcounting `docs/narrative-gaps.md` and the
   2026-09-04 spec already addressed (that fix capped how many tiles
   become *named* shops/taverns; it never touched the uncapped generic
   `residence`/`manor`/infill counts this spec fixes).
2. **Buildings are clean, grid-like rectangles.** `_split_polygon`
   always cuts perpendicular to the block's OBB long axis at a near-50/50
   ratio, every time, with no size variance — the result reads as a
   checkerboard, not an organic town.
3. **District/block boundaries are straight Voronoi-cell edges.** Even
   after buildings got real footprints, the underlying polygon edges
   (both the district's own outline and each block's) are perfectly
   straight, which reads as geometric next to organic building shapes.

Five rounds of live mockup iteration (built from real `town_shaper`
geometry via `generate_town()`, never fabricated) converged on: fractal
edge perturbation for boundaries, jittered recursive subdivision with a
shared hard size cap for buildings, demand-driven leaf sizing for
residential zones, and straight-walled architectural appendages (porches/
annexes, occasionally curved) instead of edge noise — the user explicitly
rejected a first attempt that added noise directly to building walls
("houses should not be wobbly... they are still buildings, made of more
or less straight walls").

This is **sub-project 1** of a two-part initiative scoped earlier in the
same brainstorm. **Sub-project 2 — walls, gates, towers, and a plaza/
market square (wall-aware generation, constraining artery routing to real
gates) — is deferred, not started, not designed.** This spec covers
sub-project 1 only.

## Scope

In scope:

- Fractal (midpoint-displacement) perturbation of each urban district's
  inset polygon, once, before block subdivision — fixes the straight
  Voronoi-cell-edge look at the district/macro scale.
- Replace `_split_polygon`'s clean OBB-perpendicular cut with a jittered
  version (angle jitter off the long axis, wider ratio range) for both
  block-level and leaf-level splits — this, plus the per-leaf notch/
  appendage finishing pass below, is what supplies *local* irregularity
  (per the "jaggedness needs to be more local" feedback), distinct from
  the one coarse district-level jaggify pass above. Blocks and leaves are
  not separately jaggified — the mockup validated that jittered splits +
  per-leaf finishing alone were enough at that scale.
- A shared hard cap on leaf area (independent of any single zone's target)
  so no building is ever *much much much* bigger than a typical house —
  only a couple of leaves (rich manors, civic landmarks) will approach it.
- Residential (`poor_residential`/`rich_residential`) leaf target area
  derived from real household demand — computed analytically from
  `town_shaper.households.AVERAGE_HOUSEHOLD_SIZE` and `rich_proportion`,
  no dependency on the actual `generate_households()` call — instead of
  the fixed `LOT_FRONTAGE_BY_ZONE × LOT_DEPTH_BY_ZONE` constant.
  `civic`/`merchant`/`port` keep that constant unchanged (their count is
  already controlled by the 2026-09-04 notable-building cap; only their
  *shape* changes in this spec).
- Per-building architectural irregularity: a straight-wall corner notch
  (L-shaped fronts) and/or a small straight-walled porch/annex attached at
  a slight angle offset from the main body, occasionally curved (a bay/
  turret). Never edge noise — walls stay straight.
- A light residential-only cull leaving some leaves unbuilt (courtyards/
  garden gaps) — not persisted as `buildings` rows, not rendered
  specially; the ground/street color simply shows through. (Explicit
  ruling, not left ambiguous: adding a first-class "garden" building type
  or a distinct render tint for unbuilt leaves is a nice-to-have, not
  required by anything in scope here — revisit if the plain look reads as
  too empty in practice.)
- New `footprint` polygon data on `Building`/`buildings`, additive.
  `width`/`height`/`rotation` kept, now derived from the footprint's OBB
  instead of being the source of truth — nothing besides persistence and
  rendering reads them today (confirmed by grep), so this is safe.
- Update both renderers (`town_db/render.py`, `town_viewer/static/app.js`)
  to draw the real footprint polygon, and to stop flood-filling a flat
  background color behind urban-zone buildings — confirmed against
  `CityMap.hx` that watabou's own renderer never does this either; only
  the buildings themselves carry color, which is what makes the boundary
  between zones read as organic instead of a filled polygon edge.
  `farmland_edge` keeps its existing ambient tint (not a hard urban
  boundary the same way).

Out of scope (explicitly deferred):

- Walls, gates, towers, plaza/market square — sub-project 2.
- Painterly ink/parchment rendering style (palette, hand-drawn stroke
  variation, hatching) — the user explicitly deferred this earlier in the
  same brainstorm ("mark it down for future, not now").
- Re-deriving `civic`/`merchant`/`port` building *counts* from any demand
  signal — out of scope; only their subdivision shape changes here.
- `farmland_edge` building placement — stays on today's Poisson-disc point
  placement with a fixed default footprint, untouched.

### Known risk, not yet verified: appendage overlap into neighboring lots

The mockup's `add_appendage` extends a leaf outward from one of its own
edges by up to ~0.6× that edge's adjacent segment length, which can
exceed the real `BUILDING_GAP` party-wall gap (`0.4` map units) between
neighboring leaves. The mockup only checked this visually (it looked
fine at every zoom level tested) — it was never checked programmatically
for actual polygon overlap against a building's neighbors. **The
implementation must either cap appendage depth to a safe fraction of the
adjacent gap, or verify (and reject/shrink) an appendage that would
overlap a neighboring leaf** — this is a real correctness question the
implementation plan needs to resolve, not a cosmetic detail.

## Data Model

- `buildings` table: new column `footprint TEXT NOT NULL` — a JSON list
  of `[x, y]` vertex pairs, the same convention `districts.polygon` and
  `water_features` already use. `width`/`height`/`rotation` columns are
  kept and still populated (now derived from `footprint`'s minimum
  rotated rectangle, the same computation `blocks.py`'s existing
  `_leaf_footprint` already does) — no consumer needs to change.
- `Building` dataclass (`town_shaper/models.py`): new field
  `footprint: List[Tuple[float, float]]`.
- No other schema changes.

## Algorithm

### `town_shaper/geometry.py` — one new helper

`jaggify_polygon(polygon, rng, iterations=2, max_offset_fraction=0.18) ->
Polygon` — per-edge midpoint-displacement: each edge's midpoint is pushed
perpendicular by a random offset scaled to that edge's own length,
repeated `iterations` times (vertex count doubles each round, so
amplitude naturally decays each round — one call already produces a
2-level fractal, not a single uniform wave). Called exactly once per
district in this spec (district-boundary scale); the separate "more
local" feedback is addressed by jittered splits + per-leaf finishing
instead (see Scope). Direct port of the mockup implementation.

### `town_shaper/households.py` — one new helper

`estimate_household_counts(target_population, rich_proportion) -> Tuple[int, int]`
— returns `(poor_count, rich_count)`, computed with the exact same
`AVERAGE_HOUSEHOLD_SIZE`-based formula `generate_households` already uses
internally, so the estimate exactly matches what generation will actually
produce (not just an expected value). Pure function, no RNG — household
*count* is deterministic from population + rich_proportion; only which
household gets which children/spouse is randomized.

### `town_shaper/blocks.py` — the main rewrite

- `_split_polygon` gains angle jitter (±20° off the long OBB axis) and a
  wider ratio range (0.3–0.7, was a fixed near-50/50); used for both
  block-level (`subdivide_into_blocks`) and leaf-level splits — one
  jittered-split primitive, not two.
- Before `subdivide_into_blocks` runs on a district's inset polygon part,
  pass it through `jaggify_polygon` (district-boundary scale — 2
  iterations, 0.18 fraction, matching the district's overall size).
- `generate_blocks_and_buildings` becomes a two-pass process for
  `poor_residential`/`rich_residential` (mirrors the mockup exactly):
  **pass 1** runs `jaggify_polygon` + `subdivide_into_blocks` for every
  district of that zone type and totals the resulting block area;
  **pass 2** derives `target_area = zone_total_area / target_building_count`
  (from `estimate_household_counts`, ÷ `BUILDING_HOME_CAPACITY`, with a
  slack multiplier — `1.25` in the validated mockup) and generates leaves
  against that. `civic`/`merchant`/`port` stay single-pass, using their
  existing `LOT_FRONTAGE_BY_ZONE × LOT_DEPTH_BY_ZONE` constant.
- New `organic_subdivide(polygon, target_area, hard_cap_area, rng, depth,
  max_depth=9) -> List[Polygon]` replaces `place_buildings_in_block`'s
  body: soft stop at `target_area × uniform(0.55, 1.4)`, but always
  splits further if `area > hard_cap_area` regardless of the soft sample.
  `hard_cap_area = 4.0 × (LOT_FRONTAGE_BY_ZONE[POOR_RESIDENTIAL] ×
  LOT_DEPTH_BY_ZONE[POOR_RESIDENTIAL])` — one constant shared across every
  zone, not per-zone, so the "much much much bigger" ceiling is global.
- New `notch_corner(polygon, rng)` (~35% chance per leaf) and
  `add_appendage(polygon, rng)` (~40% chance; picks a random edge,
  attaches a smaller straight-walled rectangle at a slight angle
  deviation from the main body, ~30% of appendages get a curved outer
  edge via quadratic-Bezier sampling, merged with `shapely`'s
  `.union()`) — both direct ports of the mockup, subject to the
  overlap-safety fix noted above under Known Risk.
- Residential leaves get a ~12% random cull (courtyard/garden gaps) after
  generation; culled leaves are simply not turned into `Building` rows.
- Building-type/name/job-vacancy assignment
  (`resolve_building_type_weights`, `BUILDING_NAME_POOLS`,
  `JOB_VACANCIES_BY_BUILDING_TYPE`, the notable-building cap) is
  unchanged in mechanism, applied to whatever leaves `organic_subdivide`
  produces.

### `town_shaper/generate.py` — wiring

Compute `estimate_household_counts` once, early (before the per-district
building loop), and thread the resulting targets into
`generate_blocks_and_buildings` for residential districts alongside the
existing `next_building_id`/`notable_building_counts` threading.

## Rendering

Both `town_db/render.py` and `town_viewer/static/app.js`:

- Draw `building.footprint` (the real polygon) directly, replacing the
  rotated-rectangle reconstruction from `width`/`height`/`rotation`.
- Drop the flat per-district background polygon fill for
  `civic`/`merchant`/`rich_residential`/`poor_residential`/`port` — only
  the buildings themselves carry the zone's color (matches
  `CityMap.hx`'s actual technique, confirmed by re-reading it). Culled/
  garden leaves are simply not drawn — the ground color shows through.
  `farmland_edge` keeps its existing ambient background tint and
  point-scatter, unchanged.
- `town_viewer/static/app.js`'s exact current draw calls haven't been
  read yet — the implementation plan needs a task to locate its
  equivalent of `render.py`'s building/district drawing and mirror both
  changes there.

## Determinism & Testing

RNG threading unchanged in shape — `rng_for(seed, "blocks", district.id,
...)` remains the single source of randomness for block/building
placement; `estimate_household_counts` is pure/deterministic (no RNG), so
adding it doesn't disturb existing seeded sequences elsewhere.

Tests requiring substantial rewrite or addition (TDD, red→green, per this
project's usual practice — not enumerated task-by-task here, that's the
implementation plan's job):

- `tests/test_geometry.py` — new `jaggify_polygon` tests (perturbed
  polygon stays simple/non-self-intersecting for reasonable inputs,
  output vertex count matches the doubling pattern, degenerate/near-zero
  edges don't crash).
- `tests/test_households.py` (or wherever `households.py` is tested) —
  `estimate_household_counts` sums to the same total
  `generate_households` would produce, splits correctly by
  `rich_proportion`.
- `tests/test_blocks.py` — replace grid/frontage-strip assertions with:
  no leaf ever exceeds `hard_cap_area`; residential building counts land
  within a documented tolerance of the household-derived target (not
  exact — subdivision is a stochastic threshold process); appendage/notch
  output is always a simple `Polygon` (no self-intersection, no
  `MultiPolygon` from a degenerate union); **an explicit overlap test**
  covering the Known Risk above — no two leaves' footprints (including
  appendages) within the same block overlap each other.
- `tests/test_generate.py`, `tests/test_db_render.py`,
  `tests/test_viewer_queries.py` — update for the new `footprint` column;
  confirm residential building counts are no longer wildly disproportionate
  to household counts on a real generated town (a regression guard for the
  bug that motivated this spec).
- Full suite + a determinism sweep (advance/regenerate comparison, same
  shape as every prior plan's final task) before this is considered done.

**Performance note, not a design decision:** the two-pass residential
generation (block geometry computed once to total area, then leaves
generated against a derived target) roughly doubles the geometry work for
those zones. Worth a sanity check during implementation at existing test
town sizes (pop 5,000–10,000, already exercised elsewhere in the suite).
