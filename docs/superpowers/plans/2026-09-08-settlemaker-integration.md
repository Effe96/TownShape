# Settlemaker Integration Plan

Spec: `docs/superpowers/specs/2026-09-08-settlemaker-integration-design.md`.
Origin: `Project_Vision/00-proposals.md` P001.

This plan is phased, not task-by-task with full code diffs the way this
project's implementation-ready plans usually are (e.g.
`2026-09-04-organic-town-rendering.md`) — that level of detail is
premature here. Phase 1 exists specifically to produce the evidence
(a real side-by-side render, a validated ward mapping) that a
detailed, implementation-ready plan for Phase 2 would otherwise have to
guess at. Write that detailed plan once Phase 1's checkpoint passes, not
before.

## Global constraints (carry into every phase)

- Every geometry-affecting random draw that stays Python-side keeps
  going through `town_shaper.seeding.rng_for` — unchanged from today.
- `settlemaker` is pinned to an exact commit SHA (never a floating
  branch) from the moment it's first added as a dependency.
- Nothing under `town_db/`, `town_relationships/`, `town_narrative/`
  changes in Phase 1 or Phase 2 — if a task in either phase seems to
  need one of them to change, that's a sign the mapping layer (Data
  Model, in the spec) is wrong, not a reason to widen scope.
- Full test suite (`python -m pytest tests/ -q`) stays the acceptance
  bar throughout, same as every other change in this project.

## Phase 1 — Spike-to-checkpoint (bridge + one real town, no deletions yet)

Goal: produce a real, visually-reviewable town generated through the new
path, running side by side with the existing pipeline (neither replaces
the other yet), and get the user's explicit sign-off on the ward-mapping
table and the visual result before Phase 2 deletes anything.

1. Create `settlemaker_bridge/` with its own `package.json` pinning
   `settlemaker` by commit SHA, and a thin wrapper script
   (`generate.mjs`): reads a JSON `{burg, seed}` payload from stdin,
   calls `generateSettlement`, writes the `geojson` (metadata stripped
   of `generated_at`) to stdout.
2. Python side: a function building an `AzgaarBurgInput` dict from a
   `TownParameters`-like input plus a list of water-feature rings
   (reuse the exact ring-extraction `town_db.generate._water_feature_rings`
   already does, rather than re-deriving it).
3. Python side: `parse_settlemaker_geojson(geojson) -> (List[District], List[Building])`
   per the spec's Data Model mapping tables. Ward types with no mapping
   decision yet (`castle`, `park`) raise loudly (not silently dropped)
   so Phase 1's real-town run surfaces whether they actually show up in
   practice before Phase 2 has to decide their fate for real.
4. Generate one real town this way (a population in the low thousands,
   with a river and a coastline, matching this session's `port_test`
   parameters for a fair comparison) and run it through the *existing,
   unchanged* `town_db.render.render_town` (it only needs
   `districts`/`buildings`/`water_features` rows, which this path now
   produces in the same shape).
5. **Checkpoint — do not proceed to Phase 2 without this:** show the
   result to the user side by side with this session's `port_test.png`
   (the just-shipped bespoke pipeline's output) at the same seed/
   population, and get explicit sign-off on (a) the visual result and
   (b) the ward -> zone-type mapping table actually looking right in
   practice, not just in principle.

**Checkpoint result (2026-09-08): passed, on the second attempt.** The
first attempt (task 4 exactly as written above, through unmodified
`render_town`) was correctly rejected by the user — `render_town` draws
settlemaker's buildings with the old pipeline's flat-color/no-streets/
no-farmland-texture style, which isn't a fair test of settlemaker's own
quality. Re-run against settlemaker's own `result.svg` for the same town
(same seed, same `coastlineGeometry`) instead, and *that* got explicit
sign-off — see the design spec's Rendering section for the full writeup.
Net effect on scope: rendering moved from "deferred, out of scope" to
"in scope, `town_db/render.py` is now a Phase 2 deletion target" — see
that section and "What this deletes" for the updated list. The ward ->
zone-type table also got confirmed, with one addition neither this plan
nor the spec anticipated (`military`) and one resolved as the spec's own
named default (`park` -> `civic`); `castle` is still unresolved, having
never appeared in any Phase 1 run.

## Phase 2 — Replace the real pipeline, delete the superseded code

Only starts once Phase 1's checkpoint passes. Write a detailed,
task-by-task implementation plan at this point (this project's usual
format) rather than executing off this high-level phase description —
by now the bridge script, the parser, and the mapping tables already
exist and are proven from Phase 1, so that plan is scoping real,
known-shaped work, not speculative work.

High-level shape of what it covers, for scoping purposes:

- Wire the Phase 1 bridge + parser into `generate_town` for real,
  replacing the `anchors` -> `districts` -> `blocks`/`countryside` ->
  `roads` call chain.
- Delete `town_shaper/anchors.py`, `districts.py`, `blocks.py`,
  `roads.py`, `countryside.py`, `town_db/render.py`, and the now-unused
  parts of `geometry.py` (keep `chaikin_smooth` for `water.py`) — the
  `render.py` deletion is new since Phase 1's checkpoint (see that
  section above and the design spec's Rendering section).
- Persist settlemaker's own SVG as the real rendering path in
  `render.py`'s place, and decide how `town_viewer` sources its data
  (keep reading `buildings.footprint`/`districts.polygon` from SQLite, or
  switch to settlemaker's GeoJSON directly — not pre-decided, see the
  spec's Rendering section).
- Relax or adapt `District.anchor` per the spec's recommended approach
  (synthesize a centroid anchor rather than making the field Optional).
- `castle` ward-type handling remains an open decision if/when it shows
  up (`military`/`park` were resolved at Phase 1's checkpoint — see
  above and the spec's Data Model table).
- Rewrite the large fraction of `tests/test_blocks.py` (and this
  session's residential/courtyard tests) that directly exercises deleted
  functions — this is the single biggest line-count item in Phase 2,
  called out explicitly so it isn't underestimated the way test-debt
  usually is when a plan is scoped around the "real" code change only.
- Add the new `parse_settlemaker_geojson` unit tests (fixed sample
  GeoJSON fixtures, no live subprocess call in the fast suite) and one
  slow/optional integration smoke test that does make a real subprocess
  call against the pinned commit.
- Full suite green, same bar as every change in this project.

## Phase 3 — Deferred, not scheduled

Real options surfaced during design, deliberately not part of this
rollout:

- Any work toward the multi-town/subagent-world layer from P001's
  original long-term vision.

(Retiring `town_db/render.py` was originally filed here but moved into
Phase 2 at Phase 1's checkpoint — see that section above.)

Revisit either only as its own proposal once Phase 2 has shipped and
been lived with for a while.
