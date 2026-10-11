# Construction Edits, Layout Knobs, and the Narrative Layout Direction

### Session spanning 2026-10-09 to 2026-10-10. Started as "work on physical town generation and visualization", grew into a full physical-edit layer on top of settlemaker towns (growth, side streets, fields, demolish/resize/reshape, build near a place), narrative layout knobs for random towns (river/road bearings, citadel), several parser and viewer fixes, and ended with the owner reframing the goal: the town's structure should follow *whatever* the narrative describes. That produced P002 and a design spec for a compositional narrative layout engine. All code is on branch `town-construction` (pushed, 9 commits, full suite 501 passing); the spec and these vision/memory updates are the last, uncommitted step.

## Low-Detail Summary

- **Viewer:** building-type emoji icons (zoom-gated for commercial types), legend toggles per type, ruins/demolished handling, flat modes draw roads parsed from the SVG, resident detail no longer 500s on towns without derived relationships.
- **Construction edits** (`town_db/construction.py`, physical layer only — owner was explicit: no residents, no `advance_town`, the *why* of growth is another project of theirs): `add_buildings` (ribbons along roads, irregular side streets, fields trimmed/converted/re-sown, `near=` a named place), `demolish_building` (cleared or ruin), `resize_building`, `reshape_building`; every edit logged in `construction_edits`.
- **Layout knobs:** `TownParameters.river_bearings`, `has_citadel`, `road_bearings`.
- **Parser fixes:** castle wards → civic/garrison; park lawns no longer become shops; a cathedral ward merges into one temple.
- **Direction change:** owner: "the tool should be able to service more or less whatever narrative description it is given (within some boundaries)" — example: three concentric round walls each with a river-fed moat, heart-shaped church in the middle. → P002 + `docs/superpowers/specs/2026-10-10-narrative-layout-engine-design.md`.

## High-Detail Summary

### Owner preferences learned (apply going forward)

- **Scope discipline:** physical construction/visualization is decoupled from the people layer; integration with the owner's other project comes later. Don't wire construction into `advance_town`.
- **Medieval, not modern:** straight perpendicular lanes with detached houses were rejected as "modern American living areas". Growth must wander, join up, be near-terraced, mix gable-end plots.
- **Show, then build:** the owner reviews renders at every step; before/after images with coloured outlines per edit worked well. Keep doing visual checkpoints.
- **Generality over features:** castle/star walls/symmetry were *examples*; the goal is compositional narrative → structure.
- Commits only when asked; owner asked to commit/push after each completed chunk, and for full-suite runs before commits.

### Technical facts worth knowing before touching this again

- Settlemaker towns persist **no roads or walls** to the DB; they exist only in the SVG (`#roads` casing/core paths, `#walls` path + `<line class="gate">`). Construction parses them from there and writes side streets back into `#roads` (+ `road_nodes`/`road_edges`).
- SVG coordinates == DB footprint coordinates; the SVG `viewBox` == `town_state` svg bounds (and settlemaker writes the frame in 3 places: viewBox, frame clipPath rect, paper rect) — widen all together.
- Settlemaker buildings carry **no id** in the SVG: match by geometry (IoU ≥ 0.9, or several pieces each ≥ 90% inside covering ≥ 60% — a cloister courtyard is in the outline but no piece covers it). Groups searched: `#buildings`, `#landmarks`, `#greens` (park lawns).
- Settlemaker buildings store `width`/`height` = 0 — size anything from `footprint`.
- Settlemaker's tavern lots are ~5x a house; new non-residential buildings are sized 1.4x a typical house instead.
- Each settlemaker field plot == exactly one `farmland_edge` district.
- Landscape glyphs (`#symbols`/`#canopy`/`#marks` `<use>` with `translate(x,y) scale(s)`, 64-unit glyphs) and `#greens` must be treated as obstacles.
- Road bearings: settlemaker's *gates* match requests within a few degrees; the road course outside follows field edges (20-40° drift; once two requests shared one road).
- Compass frames: town_shaper is Y-up (bearing → (sin, cos)); settlemaker/SVG Y-down (bearing → (sin, −cos)); the water rescale's Y flip reconciles them.
- `generate_town_from_parameters` doesn't derive relationships; demo DBs made that way crashed the viewer's resident detail until fixed.
- `demo_riverport_town.svg` is stale vs its `.db` (Sep 16 vs Sep 23) — misaligned overlay; regenerate before demoing.
- Full suite ~6-10 min (settlemaker integration tests call Node). Construction tests use a synthetic town (`tests/test_construction.py` fixtures), no Node.
- Bash heredocs on this machine mangle backslashes/`'[]'`; write multi-line patch scripts to the scratchpad and run them.
- `.git/worktrees/{svg-overlay,town-viewer-svg-overlay}` can't be deleted (permission denied, likely OneDrive) — harmless git noise.

### Wrong turns (and why) — useful to avoid repeating

- Ring/cluster accretion for growth → read as an even "dotted fence"; replaced by road-led side streets.
- Fixed-step candidate lots → every other lot rejected, loose spacing; probe every 0.5 units and pack greedily.
- Lane gap exactly as wide as the street corridor → float touching blocked every street; gap widened by one clearance.
- Converting a whole field when one house touched it → large bare voids; now trim with a smoothed clearance, convert only when > 50% lost.
- "Near the mill" first put houses ~300 px away (no road reaches the mill, lanes wandered randomly); lanes now steer toward the place and run until they arrive.
- Absorbing neighbours on resize first cleared their lots without building on them (voids); now the whole lots are built over.
- Assumed the cathedral was one building; it's 5-15 pieces — fixed in the parser.

### State at end of session

- Branch `town-construction`, pushed, commits `e6490a0` … `deed745`; no PR opened.
- Uncommitted: this file, `Project_Vision/*` updates, the P002 design spec.
- Next: owner decisions D1-D4 in the spec, then Phase 0 (2-3 day settlemaker fork spike: can its wards fill regions TownShape defines, and does it look as good?).
