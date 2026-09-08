# Settlemaker Integration — Design

## Context

`Project_Vision/00-proposals.md` P001: after a full session spent hand-building
an organic block/lot cutting pipeline, courtyard buildings, and a
clearance-based countryside system (all landed, tested, 499/499 passing),
the user's assessment was that the result still isn't close to what they
want, and asked to evaluate integrating an existing open-source
watabou-style generator instead of continuing to build one from scratch.

A time-boxed spike (same session, see P001's "Spike results") cloned
[`barrulus/settlemaker`](https://github.com/barrulus/settlemaker) — a
TypeScript, GPL-3.0, watabou-style settlement generator — built it, and ran
it standalone via a throwaway Node script. Findings, verified directly
(not from documentation alone):

- **One clean library entry point**: `generateSettlement(burg: AzgaarBurgInput, {seed}) -> {kind, svg, geojson, degradedFlags}`. No CLI packaging needed — it's a normal importable module (`main`/`types` in `package.json`).
- **Output**: flat GeoJSON, each feature tagged `properties.layer` (`ward`, `building`, `street`, `wall`, `tower`, `entrance`, `poi`), each `building` carrying a real polygon, a `wardType`, and a stable `building_id`. A separate `poi` layer (kind: `inn`/`tavern`/`temple`/`cathedral`/`shop`/`market`/... ) links back to a building via `buildingId` for most kinds.
- **Speed**: 137ms for a population-3000 town, 169ms for a population-400 village — roughly 100x faster than this session's ported `town_shaper` pipeline (13-16s at the same population).
- **Visual quality**: substantially ahead of every mockup iteration this project has produced — organic (non-rectangular) building footprints, a real walled core with towers/gates, textured farm field plots, scattered vegetation, landmark glyphs. Both a town-scale and a village-scale render were reviewed directly in-session.
- **Determinism**: two calls with the same `burg`+`seed` produce byte-identical `svg` and byte-identical `geojson` except one non-semantic field, `metadata.generated_at` (a wall-clock ISO timestamp). Everything that matters — geometry, IDs, bounds, scale — is exactly reproducible.
- **License**: GPL-3.0-only. Fine for a subprocess/library-dependency integration (this document's approach) without relicensing TownShape; would not be fine to copy its source into `town_shaper`.

This document designs the actual integration: what TownShape keeps, what it
deletes, and how the two halves connect. It does not implement anything —
per this project's own standing rule (mock up / spec before writing real
code), Phase 1 below is itself a checkpoint for the user to sign off on
before Phase 2 touches `generate_town`'s real call path.

## Scope

**In scope:**

- Replace `town_shaper`'s district/road/wall/building **geometry**
  generation (currently `anchors.py`, `districts.py`'s Voronoi cut,
  `blocks.py`'s entire cutting apparatus — both the pre-existing
  civic/merchant pipeline and this session's new organic-residential one
  — `roads.py`'s road-graph generation, and `countryside.py`) with a call
  to `settlemaker` via a small Node bridge process.
- Keep `town_shaper/water.py` generating rivers/coastline exactly as
  today; its output becomes settlemaker's `coastlineGeometry` **input**
  instead of feeding our own building-placement/water-avoidance logic.
- Keep `town_db`, `town_relationships`, `town_narrative` **completely
  unchanged** — the integration's whole point is that they keep consuming
  `District`/`Building` objects in the exact shape they do today; nothing
  downstream of `generate_town()`'s return value should need to change.
- Keep the existing SQLite schema (`districts`, `buildings` tables)
  unchanged — verified below, in Data Model, that settlemaker's output
  maps onto it with zero migrations.
- Persist settlemaker's own themed SVG as the real rendering path,
  **superseding** `town_db/render.py`'s matplotlib renderer rather than
  running alongside it (see Rendering, below — moved in-scope after
  Phase 1's checkpoint, reversing this doc's original call to defer it).
- A phased rollout (Rollout, below) with an explicit visual-approval
  checkpoint before the old pipeline is touched or deleted.

**Out of scope (raised during design, deliberately deferred):**

- The long-term multi-town/subagent-world vision from P001's original
  request. `settlemaker`'s `AzgaarBurgInput` shape (designed for exactly
  this — feeding individual burgs from a world-map tool) is compatible
  with that future direction, but building it is a separate, much larger
  initiative this spec doesn't block or need to solve.
- `town_viewer` changes beyond whatever's needed for it to keep working
  against the same DB schema (it already reads footprints, not
  settlemaker-specific shapes).
- Re-deriving `AzgaarBurgInput` fields TownShape has no equivalent for yet
  (`culture`, `elevation`, `temperature`, `trade`) — left at their
  defaults/unset until `town_narrative` has an opinion about them.

### Rejected alternative: keep patching the bespoke pipeline

Considered continuing to refine this session's newly-ported organic
cutting/courtyard/countryside code rather than switching. Rejected on the
spike evidence: `settlemaker` is ~100x faster, visually ahead on every
axis this project has spent a full session fighting (organic footprints,
farmland texture, wall/gate detail), and represents work already done,
tested, and iterated by another project rather than a from-scratch
reimplementation of the same watabou techniques. Continuing to hand-build
the same category of algorithm settlemaker already ships is the more
expensive path, not the safer one — the risk this document manages
instead is *dependency* risk (Risks, below), not algorithm-quality risk.

## Data Model

**No SQLite schema changes.** Verified against the current schema
(`town_db/schema.py`):

```sql
CREATE TABLE districts (
    id INTEGER PRIMARY KEY,
    zone_type TEXT NOT NULL,
    polygon TEXT NOT NULL          -- JSON list of rings, already the multi-part convention
);

CREATE TABLE buildings (
    id INTEGER PRIMARY KEY,
    district_id INTEGER NOT NULL REFERENCES districts(id),
    zone_type TEXT NOT NULL,
    building_type TEXT NOT NULL,
    x REAL NOT NULL, y REAL NOT NULL,
    capacity INTEGER NOT NULL,
    name TEXT,
    width REAL NOT NULL DEFAULT 0, height REAL NOT NULL DEFAULT 0, rotation REAL NOT NULL DEFAULT 0,
    footprint TEXT                  -- JSON ring or list-of-rings; already optional
);
```

A settlemaker `building` feature maps directly: `footprint` <- its ring
(centroid computed for `x`/`y`, same as any footprint-only building
today), `width`/`height`/`rotation` left at their existing 0.0 default
(already an established, tested convention this session — nothing reads
them when `footprint` is present). A `ward` feature maps directly onto a
`District` row: `polygon` <- its ring.

**One in-memory model change needed:** `town_shaper/models.py`'s
`District.anchor: Anchor` is currently non-optional, but settlemaker
generates wards without our anchor concept at all. Two options:

- Make `anchor: Optional[Anchor] = None`. Simple, but every existing
  reader of `district.anchor` (there are a few, e.g. in `roads.py`, which
  is being deleted anyway) needs an audit for `None`-safety.
- Synthesize a trivial `Anchor` at each ward's centroid on the way in.
  Zero readers need to change; `anchor` continues to mean "a point inside
  this district," just computed differently. **Recommended** — lower
  blast radius, and "a representative point in the district" is still a
  meaningful thing to have even when it no longer drove generation.

**Zone/ward mapping** (confirmed at Phase 1's checkpoint, 2026-09-08 —
`military` wasn't anticipated by this table's first pass and showed up in
practice; `park` was anticipated as a decision to make and is now made):

| Our `ZoneType` | settlemaker `WardType` |
|---|---|
| `civic` | `administration`, `cathedral`, `military`, `park` |
| `merchant` | `merchant`, `market` |
| `poor_residential` | `slum`, `craftsmen` |
| `rich_residential` | `patriciate` |
| `port` | `harbour`, `gate` |
| `farmland_edge` | `farm` |

settlemaker also has `castle`, `empty`, `water` ward types with no current
TownShape equivalent — `water`/`empty` are skippable (not buildable area).
`castle` never appeared in Phase 1's runs; still needs the same fold-into-
`civic`-or-new-`ZoneType` decision if/when it does (see `parse_geojson.py`'s
loud-raise, kept for exactly this reason — it isn't silently defaulted).

**`poi.kind` -> our `building_type`**: settlemaker's `PoiKind` enum
(`inn, tavern, temple, cathedral, chapel, smithy, stable, shop, market,
bathhouse, guardhouse, guildhall, warehouse, pier, mill, well`) lines up
closely with `town_shaper/buildings.py`'s existing `BUILDING_NAME_POOLS`
and `JOB_VACANCIES_BY_BUILDING_TYPE` keys (`tavern`, `shop`, `temple`,
`town_hall`, `guard_post`, ...) — reuse those tables as-is, keyed off
`poi.kind` after a small renaming pass (e.g. `guardhouse` -> our
`guard_post`) rather than inventing a parallel naming system. A `poi`
entry with a non-null `buildingId` names an *existing* `building` feature
as that named type; the rest of that ward's `building` features become
plain unnamed infill (`residence`, `shop_generic`, or whatever this
project's existing infill convention is per zone) — same population-
scaled-named-building-cap idea this project already has, just driven by
settlemaker's own `poi_density` setting instead of our own cap logic.

## Architecture — the integration boundary

```
town_narrative (unchanged)
        |  TownParameters
        v
town_shaper.water (unchanged)  ---->  WaterFeature polygons
        |                                     |
        |                          (ring coords, reused --
        |                        town_db.generate._water_feature_rings
        |                         already extracts exactly this shape)
        v                                     v
  build AzgaarBurgInput  <----------------------
        |
        v
  Node bridge process (new, thin)
    - imports `generateSettlement` from settlemaker (npm dependency)
    - stdin: JSON { burg, seed }
    - stdout: JSON geojson (settlemaker's own shape, unmodified)
        |
        v
  Python: parse_settlemaker_geojson(geojson) -> (List[District], List[Building])
    - group features by properties.layer
    - ward -> District (per Data Model mapping table)
    - building (+ matching poi) -> Building (per Data Model mapping table)
        |
        v
  town_db, town_relationships, town_narrative  (unchanged from here on)
```

**Why a subprocess, not an HTTP service or embedded JS runtime:**
settlemaker is a library, not a server — running it as a long-lived
service would need code we'd have to write and maintain (a small Express
wrapper, a process supervisor) for no benefit over a synchronous
subprocess call, given generation takes ~150ms. An embedded JS runtime
inside Python (e.g. a JS-in-Python bridge library) is unnecessary
complexity for a boundary this simple, and adds a dependency of its own
kind. A plain `node bridge.mjs` subprocess, JSON over stdin/stdout, is the
smallest thing that works — reconsider only if per-call process-spawn
overhead (not measured here, likely tens of ms) turns out to matter at
whatever `generate_town` call volume this project actually sees.

**Version pinning.** settlemaker is not published to npm (no evidence of
an npm registry listing) — it's consumed via a git dependency:
`"settlemaker": "github:barrulus/settlemaker#<commit-sha>"` in
`package.json`, pinned to an exact commit, never a floating branch or
tag. It's a young, actively-changing project (schema already at
`schema_version: 4`; the spike's `package.json` showed `"version":
"2.1.0"` with no npm publish) — an unpinned dependency would let its
generation algorithm (and therefore every generated town) silently drift
out from under this project's own determinism guarantee. Bumping the
pinned commit is a deliberate, reviewed action (regenerate reference
towns, re-check the ward mapping table still looks right, re-run the
determinism test), not an automatic `npm update`.

## What this deletes from `town_shaper`

Being upfront about this rather than burying it: a real amount of code
from this very session gets deleted if this integration proceeds,
alongside older pre-existing code.

**Deleted:**
- `town_shaper/anchors.py` — zone-anchor Voronoi placement, no longer needed.
- `town_shaper/districts.py` — Voronoi cell computation, superseded by settlemaker's ward layout.
- `town_shaper/blocks.py` — in its entirety: both the pre-existing civic/merchant block-cutting pipeline *and* this session's new organic-residential/courtyard code.
- `town_shaper/roads.py` — road-graph generation; settlemaker's `street` layer replaces it, if kept at all (TownShape doesn't currently draw roads on the static map either way).
- `town_shaper/countryside.py` — clearance-based farm/house placement, including this session's water-safety filter (settlemaker clips against `coastlineGeometry` itself — verify empirically in Phase 1 before assuming this is redundant, rather than deleting on faith).
- `town_db/render.py` (outside `town_shaper`, added to this list after the Rendering section above changed at Phase 1's checkpoint) — the matplotlib renderer, superseded by persisting settlemaker's own SVG.

**Kept, unchanged:**
- `town_shaper/water.py` — still generates the river/coastline geometry; its output just feeds settlemaker's input now instead of `town_shaper`'s own downstream logic.
- `town_shaper/models.py` — `Building`/`District` dataclasses stay the target shape everything gets mapped into (with the one `anchor` change above).
- `town_shaper/buildings.py` — name pools and job-vacancy tables are reused; only its *placement* logic (`fill_district_buildings`, if anything in the new path still called it, which it wouldn't) goes away. It also stays as-is for any test fixture that already depends on it directly (`tests/test_assignment.py`).
- `town_shaper/seeding.py` (`rng_for`) — still the determinism backbone for every non-geometry random draw (population, households, economy) that stays Python-side.
- `town_shaper/geometry.py`'s `chaikin_smooth` — still used by `water.py`. Everything else in that file (`inset_polygon`, `jaggify_polygon`, `rotated_rect_corners`, the Sutherland-Hodgman clipper) was purely in service of the deleted geometry pipeline and goes with it.

**New:**
- A small bridge directory (e.g. `settlemaker_bridge/`) holding the Node wrapper script, its own minimal `package.json` pinning settlemaker by commit SHA, and the Python-side `parse_settlemaker_geojson` module.

## Rendering

**Decided at Phase 1's checkpoint (2026-09-08), reversing this doc's
original call to defer this section:** persist settlemaker's own themed
SVG (`result.svg` — 8 built-in palettes, night/blueprint/ink themes) as
the real rendering path, in place of `town_db/render.py`'s matplotlib
renderer, not alongside it.

Why: Phase 1's first checkpoint compared the old pipeline's `port_test.png`
against settlemaker's *geojson*, mapped onto `District`/`Building` rows
and drawn through the existing, unmodified `render_town` — and the user
correctly rejected it. The comparison was unfair to settlemaker:
`render_town` was built for the old pipeline's blockier building style. It
draws flat single-color footprints with no street lines, no farmland
texture, no plaza fill, and no proper wall/tower styling — all things
settlemaker's own renderer draws and this project's data model doesn't
even capture (the `street` and farmland-subplot layers are parsed by
`parse_settlemaker_geojson` only insofar as they don't crash it; their
actual geometry is dropped). Re-running the same town straight through
settlemaker's own `generateSvg` (still the same generated model, same
seed, same `coastlineGeometry`) produced a result the user did sign off
on. Trying to close that gap by extending `render_town.py` to draw
streets/farmland/plaza fill was considered and rejected as strictly more
work than using the renderer settlemaker already ships, for a worse
result (this project's matplotlib renderer would always be reproducing a
subset of what `generateSvg` already does natively).

Consequence for Phase 2's scope: `town_db/render.py` — the matplotlib
renderer, its `_polygon_with_holes_patch`/`_draw_wall`/landmark-marker
logic, and `town_shaper.geometry.rotated_rect_corners` (its only other
caller besides the deleted `blocks.py` — see What this deletes, above) —
is now a **deletion candidate for Phase 2**, not a keep. `town_viewer`
either keeps working against `buildings.footprint`/`districts.polygon`
(unaffected either way — SQLite rows are still populated exactly as this
doc's Data Model section describes, since `town_db`/`town_relationships`/
`town_narrative` still need them) or gets pointed at settlemaker's own
GeoJSON directly; Phase 2's implementation plan decides which, it isn't
pre-decided here.

## Determinism & Testing

- **Verified in the spike**: identical `burg`+`seed` in -> byte-identical
  `geojson` out, except `metadata.generated_at` (a timestamp, discarded
  entirely on the Python side — never persisted, never compared).
- **New determinism test**: `generate_town(seed, ...)` called twice ->
  byte-identical `District`/`Building` data, same as the existing
  `test_generate_town_is_fully_deterministic` — this test's *assertions*
  don't change, only what's running underneath them does.
- **Test suite impact is large, not incidental**: most of
  `tests/test_blocks.py` (and this session's just-written residential/
  courtyard tests) directly exercises functions (`organic_subdivide`,
  `_split_polygon_organic`, `ring_peel`, `variable_inset`, ...) that this
  spec deletes. This is a real migration, not a small delta — budget for
  it explicitly in the plan rather than discovering it mid-implementation.
- **New test surface**: `parse_settlemaker_geojson` needs its own unit
  tests against fixed, checked-in sample GeoJSON (not a live settlemaker
  call in the fast test suite) — mirrors this project's existing
  preference for deterministic, non-generative test fixtures.
- **Integration smoke test**: one real subprocess call to settlemaker in
  the test suite (marked slow/optional if the suite needs to run without
  Node available in some environment) confirming the bridge itself still
  works end-to-end against the pinned commit.

## Risks / Open Questions

- **New runtime dependency: Node.js.** TownShape has been a pure-Python
  project; this adds Node as a hard requirement for town generation
  (not for `town_db`/simulation, which stay pure Python). Needs a line in
  `requirements.txt`'s neighboring setup docs / README, and matters for
  deployment (whatever runs this needs both runtimes installed).
- **Dependency health.** `settlemaker` is a small (5-star), young,
  effectively single-maintainer project. Mitigated by commit pinning
  (above) and by the fact that GPL-3.0 + public source means TownShape
  could fork and maintain its own copy if it ever goes unmaintained —
  worth remembering as the fallback, not necessarily doing preemptively.
- **Ward-mapping — RESOLVED at Phase 1's checkpoint** (2026-09-08): the
  table in Data Model above is the confirmed mapping, not a first pass
  anymore. `castle` remains genuinely unresolved (never appeared in
  Phase 1's runs to be judged against) — still raises loudly rather than
  silently defaulting, same reasoning as before.
- **`AzgaarBurgInput` fields TownShape doesn't have yet** (`culture`,
  `elevation`, `temperature`, `trade`, `biome`) are simply left unset for
  now; `town_narrative` gaining opinions about them later is a separate,
  future proposal, not blocking this one.
- **Attribution.** Not a legal requirement for a subprocess dependency,
  but good practice given the size of what settlemaker's doing for this
  project: credit it in TownShape's own README/NOTICE once integrated.
- **This sandbox's npm cannot run `npm install` for `settlemaker_bridge`.**
  Discovered in Phase 1, specific to the Claude-Code-sandboxed npm used to
  build this integration (not a general npm limitation, and not fixable
  via this project's own `package.json`/`.npmrc`): any git dependency
  whose `package.json` declares a `build` script (settlemaker's does)
  triggers an internal `npm install` inside pacote's ephemeral clone
  directory, which inherits this sandbox's `allow-scripts` policy via
  environment variable — and this sandbox's npm hard-refuses any
  project-scoped install that sees an env-sourced `allow-scripts` value,
  regardless of what `settlemaker_bridge/package.json` itself declares.
  Phase 1 worked around it by manually populating
  `settlemaker_bridge/node_modules/settlemaker/` from a clone built
  directly (`git clone` + `npx tsc`, same pinned commit) outside npm's
  dependency resolution. **Not yet verified: whether a plain `npm install`
  in `settlemaker_bridge/` succeeds end-to-end in a normal, non-sandboxed
  environment** — the `package.json` declaration (git dependency pin +
  `postinstall` build step) is believed correct but untested there. Verify
  this before treating Phase 2 (or any deployment) as done.

## Rollout

See the companion plan, `docs/superpowers/plans/2026-09-08-settlemaker-integration.md`,
for the phase breakdown and an explicit sign-off checkpoint before any of
today's working pipeline is touched or deleted.
