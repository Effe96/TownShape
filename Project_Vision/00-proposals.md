# Proposals Inbox

### Where new change requests and feature ideas land first, before they're triaged into a layer file (`01-generation-layer.md`, `02-simulation-layer.md`, `03-visualization-layer.md`), acted on directly, or rejected. One flat list, stable IDs, newest at the bottom.

## How this works

1. **You add a proposal** using the template below — only `Title` and
   `Request` are required, everything else can be left blank or
   omitted. Don't worry about which layer it belongs to or how it'd be
   implemented; that's the next step's job.
2. **An agent triages it**: fills in `Layer`, adds `Notes` (feasibility,
   relevant code, open questions), and updates `Status`. Nothing about
   your original `Request` text gets edited — clarifications go in
   `Notes`, not by rewriting your ask.
3. **It resolves** one of three ways, recorded in `Resolution`:
   - **Moved** to the relevant layer file's Feedback & Future Ideas
     section, once it's a standing backlog item — this file then just
     keeps a one-line pointer.
   - **Addressed**, with a pointer to the commit/session that did it.
   - **Rejected**, with the reason.

## Index

Scan this table first; only open the full entry below if you need the
detail. Keep it in sync whenever an entry's status changes.

| ID | Title | Layer | Status |
|---|---|---|---|
| [P001](#p001--integrate-existing-open-source-watabou-style-generators-instead-of-building-bespoke) | Integrate existing open-source watabou-style generators instead of building bespoke | generation (cross-cutting) | Addressed (Phases 1-2); Phase 3 deferred |

## Status values

Same vocabulary as the other `Project_Vision` files:
**Proposed** (default for anything new, not yet triaged) → **Planned**
(agreed direction, not started) → **Addressed** (resolved, see
`Resolution`) — or, off that path at any point, **Deferred**
(considered, deliberately shelved, reason given) or **Rejected**
(considered, declined, reason given).

## Template — copy this block to the bottom of the list for a new proposal

```
## P001 — <short title>

**Status:** Proposed
**Layer:** <generation / simulation / visualization / cross-cutting / unsure>
**Date:** <YYYY-MM-DD>

**Request:**
<what you want, in your own words — as short or long as you like>

**Why:** <optional — the motivation, if there's a story behind it>

**Notes:** <left blank for triage>

**Resolution:** <left blank until resolved>
```

Increment the `P00N` number by one each time (check the Index table for
the last one used).

---

<!-- Proposals start here, in order added. -->

## P001 — Integrate existing open-source watabou-style generators instead of building bespoke

**Status:** Addressed (Phases 1-2); Phase 3 deferred
**Layer:** generation (cross-cutting — see Notes)
**Date:** 2026-09-08

**Request:**
The way we have been trying to get a nice visualization layer and visual generation for the towns is not working well enough for me. The cities look bad, not organic, and there are many open source tools we could be using instead. I want to try and integrate these tools into our pipeline, instead of trying to create something completely new.

**Why:** During the last week, many tokens have been used to try and get TownShape to generate nice looking cities. We are still not close to what I want.

**Notes:**
- The final aim of this OPEN SOURCE project is: being able to generate a town by feeding narrative to an ai agent, which in turn uses the tools at its disposal to create the town, population, and interactions themselves. The agent is then able to simulate the passing of years realistically, either by running on its own or by incorporating narrative notes from the user. The evolution of the town should have a layer that just runs based on the network tree and population itself, without need of an agent (less realistic, more deterministic, game-of-life style, or similar to viral infection models). Then there should be an harness for the agent to actually guide the simulation itself, making it more realistic. Finally, if narrative points are given to the agent by the user, the agent should be able to update the town and the states of the single dwellers and the town itself, without being too constricted. Itself, the project is composed of many different interlocking parts:
   - Generation of population backed by actual database of products, personality traits, and so on. (this already exists in some projects online)
   - Network of relationship between the different people in the city (I don't know that it exists online like this, but you can see examples in the relational_network_frameworks.md file in the Town_shape directory)
   - Generation of the town itself, with the actual buildings, assigned shops, taverns, and so on.
      - This repo https://github.com/barrulus/settlemaker?tab=readme-ov-file has a watabou-inspired town generation feature, that works much better than what we have. I believe in its online tool https://azgaar.github.io/Fantasy-Map-Generator/ also ties somehow to watabou's town generator to generate the single towns. Instead of creating a new tool, I want to find a way to integrate this project with these existing tools (appropriately, following any licenses needed)
   - The very final step would be the possibility to have multiple towns (in a context similar to what https://github.com/Azgaar/Fantasy-Map-Generator does) being controlled by different subagents simulate interactions with each other.

— **Agent triage (2026-09-08):**
- **`barrulus/settlemaker`** — TypeScript, **GPL-3.0**, small/young (5 stars). README describes a genuinely rich watabou-style feature set already: walled cities with towers/gates, ward types (craftsmen/merchant/patriciate/slums/military/admin), farmlands with strip fields, harbour/dock wards, deterministic seeds, SVG/GeoJSON output. This is a direct, apples-to-apples competitor to `town_shaper`'s job. GPL-3.0 means: safe to invoke as a **separate process** (spawn its Node CLI, read back its SVG/GeoJSON output as data) without any licensing obligation on TownShape's own code — that's ordinary "mere aggregation," not a combined work. It would **not** be safe to copy or adapt its source directly into `town_shaper` without relicensing that code GPL-3.0 (which would then also affect anything statically linked to it, though a separate Python codebase calling it as a subprocess is not "linking" in the GPL sense).
- **Azgaar's `Fantasy-Map-Generator`** — JS/HTML, actually **MIT**-licensed (GitHub's UI shows the SPDX detector as "NOASSERTION"/"Other" only because the LICENSE file has an added clarifying paragraph about map-output ownership on top of the standard MIT text — the license itself is unambiguous, permissive MIT). However: it's a world/continent-scale map generator — individual settlements are markers/icons on the world map, not detailed building-level town layouts. It is **not** a like-for-like replacement for what `town_shaper` does today; it's much more relevant to the later "multiple towns in a shared world, run by subagents" step of the vision than to fixing the current single-town visual-quality problem.
- **Net read:** `settlemaker` looks like the actually relevant near-term option for the immediate visual-quality complaint, and its GPL-3.0 license doesn't block a subprocess-based integration. Azgaar's FMG is real prior art for the longer-term multi-town/world layer, but isn't a drop-in fix for today's problem.
- **Not yet done (at first triage):** no code exploration of `settlemaker`'s actual CLI/output interface, no spike on a Python↔Node integration boundary, no assessment of how much of `town_db`'s population/economy layer would sit unchanged on top of externally-generated geometry. See spike below — the interface question is now answered; the `town_db` integration-effort question is not.

— **Spike results (2026-09-08), per the user's "spike settlemaker integration" decision:**

Cloned `barrulus/settlemaker` (`git clone --depth 1`, `npm install`, `npx tsc`) and ran it standalone via a throwaway Node wrapper script (not committed anywhere in this repo) calling its public API directly — no CLI packaging needed, it's a normal importable library (`main: dist/index.js`, typed via `dist/index.d.ts`).

- **Interface confirmed:** one entry point, `generateSettlement(burg: AzgaarBurgInput, { seed }) -> { kind, model, svg, geojson, degradedFlags }`. `AzgaarBurgInput` is a plain object (`name, population, port, walls, plaza, temple, coreCapacity, coastlineGeometry: [[{x,y}...]], roadBearings, urbanDensity, biome, ...`) — maps cleanly onto parameters `town_narrative`/`town_shaper` already have (population, water polygons, port flag). It auto-routes to one of two internal engines by population against a `VILLAGE_POP_CEILING`: a "village" engine (roads-first: lanes → parcels → dwellings) for small settlements, a "settlement"/ward-based engine above that — a very similar poor/rich-residential-style split to what `town_shaper/blocks.py` hand-builds today, just with two dedicated engines instead of one shared one.
- **Output confirmed:** `geojson.features` is flat, each tagged `properties.layer` — ran a pop-3000 `walls+plaza+temple` burg (seed 42) and got 799 features: `ward` (403), `building` (328, each with `wardType` + `building_id` and a real irregular polygon — not a rectangle), `street` (9), `wall` (1), `tower` (23), `entrance` (4), `poi` (31). A lower-level typed `Scene`/`buildScene` API also exists with named layers (`WaterLayer, FieldPlot, Furrow, GreenFeature, VegetationInstance, RoadFeature, BuildingFeature, PierFeature, WallFeature, WallGate`) if the flat GeoJSON ever isn't enough.
- **Speed:** 137ms for the pop-3000 town, 169ms for a pop-400 village — both fully in-process, no browser. Roughly **100x faster** than this session's ported `town_shaper` pipeline (13-16s at the same population).
- **Visual quality, rendered from its own SVG output (rasterized via its own `sharp` dev-dependency, no new tooling added):** substantially better than anything produced in this project so far on every axis this project has been fighting — organic non-rectangular building footprints, a real walled core with towers and gates, a market square, temple/windmill/landmark glyphs, and — most relevant to this session's farmland fight — irregular farm field plots with actual crop-texture fill patterns and scattered tree/vegetation clusters immediately outside the settlement. The pop-400 village run in particular (lanes branching from a center point, individual rotated dwellings along them, textured fields beyond) is a closer match to the "organic medieval town" target than any mockup iteration produced this session. Both renders were shown directly in this session's chat.
- **Not yet done at spike time:** the clone/build/renders above were all outside this repo (`C:\st_spike`, not the usual scratchpad — the scratchpad's deep path tripped Windows' filename-length limit on this repo's checkout; nothing was added to TownShape itself). Designing the actual boundary was flagged as real design work, not more spiking.

— **Design spec + plan written (2026-09-08), per the user's "write a real integration plan/spec" decision:**

- `docs/superpowers/specs/2026-09-08-settlemaker-integration-design.md` — full design: integration boundary (Node bridge subprocess, JSON over stdin/stdout, no schema changes needed), the `ZoneType`↔`WardType` and `building_type`↔`PoiKind` mapping tables, exactly what gets deleted from `town_shaper` (`anchors.py`, `districts.py`, `blocks.py`, `roads.py`, `countryside.py` — including this same session's brand-new organic-residential/courtyard/countryside code) versus kept (`water.py`, `models.py`, `buildings.py`'s name/job tables, `seeding.py`), a verified determinism finding (identical seed -> byte-identical output except a harmless `generated_at` timestamp), and open risks (Node becomes a hard runtime dependency; settlemaker is young and must be pinned to a commit SHA, never a floating branch).
- `docs/superpowers/plans/2026-09-08-settlemaker-integration.md` — phased rollout: **Phase 1** builds the bridge + parser and produces one real side-by-side town for the user to visually approve (and confirm the ward mapping actually looks right) *before anything existing is touched or deleted*; **Phase 2** (only after that checkpoint) replaces the real pipeline and carries the bulk of the test-suite rewrite; **Phase 3** (retiring `town_db/render.py` for settlemaker's native SVG, and the long-term multi-town vision) stays deliberately deferred, not scheduled.
— **Phase 1 shipped (2026-09-08):** the Node bridge (`settlemaker_bridge/`), pinned to
`barrulus/settlemaker` commit `af6741127086762fc0d73bdec374dcfcd373d5be`, plus the
GeoJSON parser onto `District`/`Building`. Checkpoint town approved by the user
(rendering moved in-scope, ward-mapping confirmed) before Phase 2 started.

— **Phase 2 shipped (2026-09-09):** `town_shaper.generate.generate_town()` now calls
the bridge for real, replacing the `anchors → districts → blocks/countryside → roads`
pipeline outright (~2,800 lines deleted: `anchors.py`, `districts.py`, `blocks.py`,
`roads.py`, `countryside.py`, plus `town_db/render.py`'s matplotlib renderer,
superseded by persisting settlemaker's own SVG). Along the way, found and fixed a
real gap the original spike didn't cover: settlemaker silently routes
`target_population <= 1000` through an entirely different "village" engine with no
ward layer, which the parser didn't understand — full write-up in
`01-generation-layer.md`'s Current State and Feedback sections, including the
resulting real gap (villages can never have an economy or grow via household
formation) now tracked there as its own open item.

**Resolution:** Addressed — see `01-generation-layer.md` and
`03-visualization-layer.md` for the current state of the generation and
visualization layers post-migration, and this file's own License/Acknowledgments
notes on `settlemaker` (GPL-3.0) and its own upstream, watabou's `TownGeneratorOS`
(GPL-3.0), also credited in the README. Azgaar's Fantasy Map Generator (MIT) was
researched as prior art for the multi-town/world-scale step of this proposal's
original vision but never integrated — that step is exactly Phase 3, still
deliberately deferred per `docs/superpowers/plans/2026-09-08-settlemaker-integration.md`
("revisit only as its own proposal once Phase 2 has shipped and been lived with for
a while") — not started, not scheduled.