# Generation Layer

### Procedural spatial layout — districts, water, roads, blocks, lots, and building footprints. Lives in `town_shaper/`. The part of the codebase responsible for *where everything is*, before any resident or history exists.

Stylistic reference point: Watabou's `TownGeneratorOS` (a copy lives in a
sibling directory, GPLv3) was studied for *technique* — vertex-anchored
polygon bisection, per-zone "chaos" parameters, courtyard peeling — never
for code, which was independently reimplemented. A Florence map photo was
also used as organic-irregularity reference during mockup iteration.

## Current State

### Districts

Organic Voronoi diagram around per-zone anchor points, zoned by type
(civic, merchant, rich/poor residential, port, farmland_edge...). A
river or coastline can split one district's Voronoi cell into several
disconnected `polygon_parts` — every downstream consumer (block-cutting,
wall rendering) uses **only the largest part**, never all of them.
Treating every part as buildable used to produce a phantom, disconnected
mini-neighbourhood (with its own street grid) stranded on a secondary
fragment on the wrong side of the water — found and fixed twice
(residential, then separately for civic/merchant/port) before becoming
this one shared rule.

### Water features

Optional rivers and coastline, carving real unbuildable space out of the
town when requested. River/coastline centerlines are Chaikin-smoothed
before being buffered into a strip, so they curve instead of zigzagging.
A water feature's polygon can have interior holes (an island in a bay,
for instance) — anything that touches water anywhere in the pipeline
must treat the shape as a real `shapely` polygon-with-holes, not just
its list of rings, or an island silently gets treated as open water (see
`03-visualization-layer.md`'s equivalent rendering gap, found and fixed
in the same session).

**Invariant, enforced centrally:** no building anywhere may intersect
water. `town_shaper/countryside.py`'s `remove_buildings_in_water` runs
once, after every generation path has placed its buildings, and is the
single source of truth for this — several generation paths (residential
cutting near a coastal edge, countryside placement, occasionally
merchant/civic) each had their own narrower water check that still let
edge cases through independently; the shared final filter is what
actually guarantees zero.

### Road network

A real, persisted graph of nodes/edges laid over district geometry
(boundary ridges, spur edges, arterial routes along the boundary graph
toward `farmland_edge`) still exists and is still computed/persisted —
`town_shaper/roads.py`, `road_nodes`/`road_edges` tables. It is **no
longer drawn on the static map** (see visualization layer) after
repeated attempts to filter out visually-stray lines all failed; the
graph itself is kept for whatever still consumes it (routing logic, the
interactive viewer — see the cross-layer gap noted in
`03-visualization-layer.md`). Urban streets on the static map are purely
implicit: each district and each block is inset, so the gap between
neighbouring inset polygons *is* the street, with no edge object behind
it.

### Blocks, lots, and buildings

Two independent pipelines, chosen by zone type:

- **Civic / merchant / port** (`generate_blocks_and_buildings`,
  `compute_district_blocks`): district → inset + jaggified → recursively
  subdivided into blocks by `subdivide_into_blocks`/`organic_subdivide`,
  then tiled down to lot-sized leaves, one building per leaf. A
  population-scaled cap bounds how many named/business building types
  (taverns, shops, temples...) get generated so counts stay usable for a
  DM rather than realistic-but-unmanageable.
- **Residential (poor/rich)** (`generate_organic_residential_buildings`,
  `town_shaper/blocks.py`): a separate, more organic pipeline —
  per-edge `variable_inset` (wide setback on a block's longest edge, a
  proxy for "faces a street"; narrow on the rest), vertex-anchored
  recursive bisection (`organic_subdivide_residential`) with per-zone
  "chaos" parameters (`RESIDENTIAL_CHAOS`: poor is chaotic/dense-ish,
  rich is calmer/roomier), independent block-level and house-level
  rotation, and a per-leaf choice between an ordinary rotated house or
  peeling the leaf into a **courtyard building** (`ring_peel`) — one
  `Building` with a multi-ring footprint (a hollow ring of wall-strip
  polygons), the same convention `District.polygon` already uses for
  multi-part polygons.
- **Farmland** (`town_shaper/countryside.py`) is no longer a zone fill
  at a uniform density at all. A countryside building (single house or a
  2-4-building farm cluster: main house + outbuildings) can appear
  anywhere it has enough clearance from the *nearest actually-placed
  building* in any direction; required clearance grows smoothly
  (smoothstep, not a hard cutoff) with distance to that nearest
  building, so density fades continuously from town into open
  countryside with no zone-boundary seam to see. Attempt counts scale
  with map area, not a fixed constant, so bigger towns don't undersample
  into patchy gaps.

### Determinism

All randomness flows through a single `rng_for(seed, *path_parts)`
helper; no global `random` state anywhere in the pipeline.

## Feedback & Future Ideas

### Duplicate tavern (and other) building names within one town

**Status:** Open

`BUILDING_NAME_POOLS["tavern"]` (`town_shaper/buildings.py`) has only 4
names, and every tavern independently draws `rng.choice(name_pool)` with
replacement. A town with more than a handful of taverns will produce
duplicates ("The Weary Traveler" twice) as a structural certainty, not a
fluke. Not fixed yet — candidates: a bigger name pool, sampling without
replacement until a pool is exhausted then falling back to a
disambiguating suffix ("The Weary Traveler (Docks)"), or folding it into
whatever future population-scaled-cap work touches this table next.

### Generation time is growing with visual quality

**Status:** Open (informational, not a regression)

The organic residential cutting (vertex-anchored recursive bisection per
lot) and the area-scaled countryside sampling pass are both real,
deliberate trade-offs of generation time for the visual quality they
buy. A population-3000 town now takes roughly 14-16s to generate
end-to-end (was under 10s before this session's port), and the
regression test's budget was raised to 20s to match. Worth a look if
target populations grow much past the low thousands, or if generation
time ever needs to be interactive rather than a batch step.
