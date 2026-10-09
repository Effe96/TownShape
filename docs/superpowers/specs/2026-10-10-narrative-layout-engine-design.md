# Narrative Layout Engine — Design

**Status:** Draft for owner review (2026-10-10). No code yet.
**Proposal:** `Project_Vision/00-proposals.md` P002.
**Supersedes, for structured towns only:** the "settlemaker owns all
geometry" assumption of `2026-09-08-settlemaker-integration-design.md`.
Settlemaker stays as the random-town path and (recommended below) as the
engine that fills structured towns.

## Context

TownShape's end goal (P001's Notes) is an agent that builds a town from
narrative. Today a town's *physical* shape comes from settlemaker, a closed
procedural generator: TownShape can pass it a handful of knobs (population,
water, citadel on/off, road bearings, river bearing) and edit the result
afterwards (`town_db/construction.py`: add buildings, side streets, demolish,
resize, reshape, build near a place). That covers "a river from the northeast"
or "the tavern burned down". It cannot cover structure that has to exist
*before* the town is filled in.

The owner's framing (2026-10-10), verbatim in spirit: the square castle, star
walls and symmetric town were only examples — **the tool should service more or
less whatever narrative description it is given, within some boundaries.** The
reference example:

> "The town is composed of three concentric round walls, every one with its
> moat which is a redirected river, and within the central one there is a
> church in the shape of a heart."

No feature list — in settlemaker, a fork of it, or TownShape — ever covers
descriptions like that one by one. The design has to be *compositional*.

### Lesson carried over from P001

Before settlemaker, TownShape built its own organic block/lot/building
pipeline; after many iterations the owner judged it "not organic, looks bad"
and it was replaced (~2,800 lines deleted). Settlemaker's strength is exactly
the part TownShape failed at: **filling space with convincing medieval
fabric** (blocks, alleys, irregular houses, fields, the rendered look). Any
design that re-implements that filling from scratch repeats the mistake. This
design keeps settlemaker doing the filling and takes over only the part
settlemaker can't express: the *structure*.

## Goal and boundaries

**Goal:** given a narrative, an agent produces a town whose *structure* matches
what the narrative states, with everything the narrative leaves unstated filled
in procedurally, deterministically, in the existing map style — and says
plainly where it had to approximate.

**In scope** — anything expressible as a 2D plan view built from:
shapes (any outline), walls, water, roads, districts, open spaces, landmark
buildings with arbitrary footprints, and fields; placed by absolute position or
by relation to each other; at plausible medieval scale.

**Out of scope:** 3D/elevation (a moat "fed by a redirected river" is drawn as
connected water, not simulated hydrology), interiors, decorative/artistic
detail beyond footprints and the map's own style, self-contradictory
descriptions, and anything needing physics. Ambiguity is resolved by the agent
asking, not guessing (same rule as `docs/narrative-town-parameters.md`).

**"More or less" made concrete:** every generation returns a *fidelity
report* — each narrative element, how it was realized, and any approximation
("heart-shaped church: realized, 38 m across"; "moat 3: only partly connected
to the river, the outer moat had no room to the east").

## Core idea: structure vs. filling

A narrative states some things explicitly and leaves the rest implicit:

| | Structure | Filling |
|---|---|---|
| What | What the narrative is explicit about: walls, moats, rivers, named roads, districts and their character, landmarks, open spaces, symmetry | Everything else: streets inside districts, blocks, houses, everyday buildings, fields, trees |
| Who decides | The agent, from the narrative, as a **layout spec** | The engine, procedurally, from the spec + seed |
| Built by | TownShape (geometry from the spec) | Settlemaker, constrained by the structure (recommended; see Filling) |

The **layout spec** is the new central artifact: a structured, saved,
diffable description of a town's structure. The same spec + seed always
produces the same town; editing the town structurally means editing the spec
and rebuilding.

## The layout spec

JSON, versioned (`"spec_version": 1`). Units are **metres**, origin at the
town centre, **north up** (+y north in the spec; the engine converts to
settlemaker's Y-down frame). Three layers:

### 1. Shapes — pure geometry, named, reusable

| Primitive | Parameters |
|---|---|
| `circle` | `center`, `radius` |
| `ring` | `center`, `inner_radius`, `outer_radius` (or `around: <shape>`, `width`) |
| `polygon` | `points` |
| `regular_polygon` | `center`, `radius`, `sides`, `rotation` |
| `star` | `center`, `outer_radius`, `inner_radius`, `points`, `rotation` |
| `rectangle` | `center`, `width`, `height`, `rotation` |
| `path` | `points` (open polyline, optionally `smooth: true`) |
| `outline` | `points` — any closed shape the agent draws (a heart is an `outline`) |
| `from_library` | `name` (`heart`, `cross`, `crescent`, `key`, `shield`, …), `center`, `size`, `rotation` |

Derived shapes: `offset` (grow/shrink a shape by a distance), `boundary_of`
(a closed shape's edge as a path), `union`/`difference`/`intersection`,
`mirror` (reflect across an axis — see Symmetry), `array` (N copies around a
centre).

Placement can be absolute (`center: [0, 0]`) or relational:
`"center": {"at": "market", "offset": [0, 40]}`,
`"concentric_with": "wall_1"`, `"north_of": "keep"`, `"along": "river"`.
Relations resolve to absolute geometry in dependency order; a cycle is a
validation error.

### 2. Elements — what a shape *is* in the town

| Element | Built on | Key fields |
|---|---|---|
| `wall` | a closed shape's boundary or a path | `towers` (spacing), `gates` (count, or bearings, or `where_roads_cross`), `thickness` |
| `water` | a shape (lake, moat ring) or a path + width (river, canal) | `kind` (river/moat/canal/lake/sea), `connects_to` (other water — a moat fed by a river), `bridges` (`where_roads_cross` / explicit) |
| `road` | a path, or `from`/`to` (gate, landmark, district, map edge) routed by the engine | `rank` (main/street/lane), `width` |
| `district` | a region (shape) | `type` (any ward type: residential-poor/rich, craftsmen, merchant, market, religious, military, administration, harbour, park, farm, slum, …), `density`, `building_grain`, `street_pattern` (organic / grid / radial) |
| `open_space` | a region | `kind` (plaza, market square, park, cemetery, garden, parade ground) |
| `landmark` | a footprint shape | `building_type` (church/temple, castle/keep, tower, town_hall, …), `name`, `courtyard` (optional inner shape) |
| `fields` | a region, or `around_town` | `density` |

Anything inside the town extent not claimed by an element is **filler
territory**: the engine fills it as the `default_district` (spec-level field,
e.g. poor residential).

### 3. Global

`seed`, `population` (target), `extent` (town size or "fit"), `default_district`,
`symmetry` (`none` / `mirror: {axis}` / `rotational: {n}`), `style` (map
palette; see Rendering), and the existing `TownParameters` people-side fields
(wealth, magic, aggression…) which this spec doesn't change.

### The reference example as a spec (abridged)

```json
{
  "spec_version": 1, "seed": "trivallis", "population": 9000,
  "shapes": {
    "c1": {"circle": {"center": [0, 0], "radius": 90}},
    "c2": {"circle": {"concentric_with": "c1", "radius": 210}},
    "c3": {"circle": {"concentric_with": "c1", "radius": 340}},
    "heart": {"from_library": {"name": "heart", "center": [0, 0], "size": 38}},
    "river_in": {"path": {"from_bearing": 20, "to": {"edge_of": "c3"}, "smooth": true}},
    "river_out": {"path": {"from": {"edge_of": "c3"}, "to_bearing": 200, "smooth": true}}
  },
  "elements": [
    {"wall": {"on": "c1", "towers": 30, "gates": 2}},
    {"wall": {"on": "c2", "towers": 30, "gates": 4}},
    {"wall": {"on": "c3", "towers": 30, "gates": 4}},
    {"water": {"kind": "moat", "on": {"ring": {"around": "c1", "width": 8}}, "connects_to": "moat_2"}, "id": "moat_1"},
    {"water": {"kind": "moat", "on": {"ring": {"around": "c2", "width": 10}}, "connects_to": "moat_3"}, "id": "moat_2"},
    {"water": {"kind": "moat", "on": {"ring": {"around": "c3", "width": 12}}, "connects_to": ["river_in", "river_out"]}, "id": "moat_3"},
    {"water": {"kind": "river", "on": "river_in", "width": 14}, "id": "river_in"},
    {"water": {"kind": "river", "on": "river_out", "width": 14}, "id": "river_out"},
    {"landmark": {"building_type": "temple", "name": "Church of the Sacred Heart", "footprint": "heart"}},
    {"open_space": {"kind": "plaza", "on": {"ring": {"around": "heart", "width": 12}}}},
    {"district": {"on": {"difference": ["c1", "heart"]}, "type": "religious", "density": 0.7}},
    {"district": {"on": {"difference": ["c2", "c1"]}, "type": "rich_residential"}},
    {"district": {"on": {"difference": ["c3", "c2"]}, "type": "craftsmen"}},
    {"fields": {"around_town": true}}
  ],
  "default_district": "poor_residential"
}
```

Roads aren't listed: the engine connects gates through each ring to the
centre (default `road` routing), adding bridges where roads cross moats.

## Pipeline

```
narrative ──(agent, using docs/narrative-layout.md)──▶ layout spec
   ▲                                                       │
   │                                             resolve + validate
   │                                                       │
   │   fidelity report + rendered preview            structure geometry
   │                                                       │
   └──────(agent reviews, revises spec)◀── render ◀── fill (settlemaker)
                                                           │
                                                persist (same DB schema)
```

1. **Narrative → spec** — the agent writes the spec, guided by a new
   `docs/narrative-layout.md` (patterns: concentric walls, moat fed by river,
   bastide grid, star fort, cathedral close, bridge town, symmetric planned
   town, ring of suburbs…) and a JSON Schema the engine validates against.
2. **Resolve** — relations → absolute geometry (shapely), in dependency order.
3. **Validate** — schema errors; geometric problems (a landmark wider than
   its district, a wall crossing itself, overlapping districts, water cutting
   a district into slivers); scale sanity vs. population. Errors block;
   warnings go into the fidelity report.
4. **Fill** — districts and filler territory become blocks, streets and
   buildings (see Filling).
5. **Render** — the town's SVG in the existing map style (see Rendering).
6. **Persist** — the existing `districts`/`buildings`/`water_features`/
   `road_*` tables (so `town_db`'s people pipeline, `town_relationships`, the
   viewer and `construction.py` edits all keep working unchanged), plus a new
   `layout_spec` table holding the spec JSON and its fidelity report.
7. **Review loop** — the agent gets the fidelity report and a rendered PNG,
   compares against the narrative, revises the spec, rebuilds. A spec rebuild
   is deterministic and takes seconds, so iterating is cheap.

## Filling: the decision that matters most

Three options, recommendation first:

### Option A (recommended) — settlemaker fills, in a fork with a "structured" entry point

Settlemaker's generator already works in two stages: it lays out patches
(Voronoi cells) and assigns each a ward; each ward class (`CommonWard`,
`Cathedral`, `Market`, `Farm`, …) then builds its own blocks and buildings
**from its patch polygon** (`new Ward(model, patch).createGeometry()`). A fork
adds an entry point that takes TownShape's structure instead of inventing it:

- **Input:** district regions (each with a ward type), walls (as given
  paths, with towers/gates), water polygons, fixed roads, landmark footprints
  (placed as-is, not generated), and fields regions.
- **Inside:** each district region is subdivided into patch-sized cells
  (Voronoi within the region — settlemaker's own technique), each cell gets
  the district's ward class, and wards fill as they do today; streets are
  routed between cells and onto the fixed roads; landmarks and walls are
  inserted as fixed geometry.
- **Output:** the same GeoJSON + SVG as today, so `parse_geojson.py` and
  everything downstream barely change.

Pros: keeps the visual quality that won P001; most new code is plumbing, not
aesthetics; the random-town path is untouched. Cons: GPL fork to maintain
(see Licensing); settlemaker's internals assume its own model (e.g. streets
and walls are derived from patch topology), so how cleanly wards accept
foreign patches must be **proven by a spike first** (Phase 0).

### Option B — TownShape's own filler (MIT)

Re-implement block/lot/building filling in Python. Full control and no GPL,
but it is exactly the work P001 abandoned for poor visual quality. Only worth
it if the Phase 0 spike shows settlemaker can't be bent this way.

### Option C — settlemaker fills per region, as separate calls

Call today's unmodified settlemaker once per district (masking everything
outside the region as water via `coastlineGeometry`), then stitch. No fork,
but seams at every region edge, walls/streets that don't line up, and one
wall per call. Rejected except as a throwaway experiment.

**Recommendation:** Phase 0 spike of Option A (bounded, ~2–3 days). If wards
accept foreign patches, proceed with A. If not, return to the owner with what
the spike found before considering B.

## Rendering

Settlemaker's SVG pipeline is already modular (`buildScene` → `Scene` layers →
`assembleSvg`, all exported). With Option A the fork renders the structured
town itself — walls, moats, landmarks and filler all in today's style, no
second renderer. Custom landmark footprints (the heart) render as landmark
polygons, which settlemaker already styles. New element kinds settlemaker has
no layer for (e.g. a moat ring that isn't coastline) are added to the fork's
scene, or drawn by TownShape into the SVG the way `construction.py` already
appends paths.

## Symmetry

`symmetry: mirror` is enforced at the structure level and in the filler:
the spec's shapes and elements are mirrored by the resolver, and the filler
mirrors cell seeds and copies each cell's generated contents to its mirror
cell (with a fixed seed per pair). This is the hardest filler requirement and
is scheduled last (Phase 4); approximate symmetry (structure mirrored, filling
not) is available from Phase 1 at no extra cost and is reported as such.

## Relationship to existing code

- **Random towns:** unchanged. No spec → today's `generate_via_settlemaker`.
- **`TownParameters` knobs** (river/road bearings, citadel, port…): still
  work for random towns; for structured towns the spec is the source of
  truth, and the narrative-parameters doc points to `narrative-layout.md`
  for structural language.
- **`construction.py` edits:** work unchanged on structured towns (same
  tables + SVG groups). Rebuilding from a changed spec regenerates the whole
  layout; edits made after the previous build are **not** replayed
  automatically in v1 (building ids aren't stable across rebuilds) — the
  agent is told, and can re-apply them. Owner decision D3.
- **People pipeline, relationships, viewer:** unchanged — they read the same
  tables.

## Licensing and the website

- The fork is GPL-3.0 (settlemaker is). TownShape stays MIT: it still
  talks to the generator as a separate process over JSON.
- Running the fork on a server and serving maps creates no source-publishing
  obligation (GPL, not AGPL); shipping it to browsers or as a download does.
  Plan: keep the fork public on GitHub regardless, and offer the structured
  entry point upstream to settlemaker's author — accepted upstream means no
  fork to maintain.
- Option B, if ever needed, would be MIT.

## Phases

| Phase | Delivers | Acceptance |
|---|---|---|
| **0 — Spike** (2–3 days) | Fork settlemaker; feed one hand-made region (a circle) as patches of one ward type; render | Owner looks at the render: does settlemaker's filling inside a foreign region look as good as its own towns? Go/no-go for Option A |
| **1 — Spec + structure** | JSON Schema, shape library, resolver, validator, fidelity report; structure-only render (walls, water, roads, landmarks, district outlines on fields) | Reference example's *structure* renders correctly; validator catches a set of broken specs |
| **2 — Structured filling** | Fork's structured entry point: districts filled, streets routed to fixed roads/gates, landmarks inserted, bridges over moats | Reference example fully generated and filled; owner visual sign-off |
| **3 — Integration** | Persist to existing tables + `layout_spec`; people pipeline, viewer, construction edits on structured towns; agent docs (`narrative-layout.md`) + preview PNG tool | Generate the reference example *from its narrative* end-to-end via the agent; residents, viewer, edits all work |
| **4 — Symmetry + breadth** | True mirror symmetry in the filler; more ward/landmark types; pattern library growth | Palifas (symmetric rebuild) narrative reproduced; 5 further narratives from the owner reproduced "more or less" |

Each phase ends with an owner checkpoint, per this project's standing rule to
show visual work before building on it.

## Testing

- Unit: each shape primitive and relation; resolver ordering and cycle
  detection; validator cases; spec → geometry snapshots.
- Determinism: same spec + seed → byte-identical DB and SVG.
- Golden narratives: a small set of narrative → spec → town fixtures (the
  reference example first), checked structurally (three walls, moats
  connected to the river, a temple whose footprint is the heart) not by
  pixels.
- Visual: owner review of rendered previews at each checkpoint.

## Risks

1. **Settlemaker may not accept foreign patches cleanly** — mitigated by
   Phase 0 before any commitment.
2. **Fork maintenance** — mitigated by offering the entry point upstream and
   pinning to commit SHAs as today.
3. **Agent spec quality** — the agent may write invalid or implausible
   specs; mitigated by schema validation, the pattern library, and the
   render-and-review loop.
4. **Scope creep toward "anything at all"** — the boundaries above are the
   contract; out-of-scope requests get a clear "can't, here's the closest".

## Decisions for the owner

- **D1 — Filling engine:** go with Option A (settlemaker fork), gated on the
  Phase 0 spike? *(recommended: yes)*
- **D2 — Style:** structured towns use today's settlemaker map style exactly,
  or is a distinct style acceptable/wanted?
- **D3 — Edits vs. rebuilds:** is it acceptable in v1 that rebuilding from
  an edited spec drops construction edits made after the last build (agent
  re-applies them), or should edits be expressed in the spec itself from
  the start?
- **D4 — Upstream:** OK to offer the structured entry point to settlemaker's
  author as a pull request (public fork either way)?
