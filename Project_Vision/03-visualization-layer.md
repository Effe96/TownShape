# Visualization Layer

### How a generated town is actually shown to the user: the exported map (now an SVG) and the interactive pan/zoom web viewer. `town_db/render.py` is gone; the export path lives in `town_db/generate.py` (the sidecar-file write) and, upstream, [`settlemaker`](https://github.com/barrulus/settlemaker) itself. The interactive viewer lives in `town_viewer/`.

**Process note that still applies:** before writing any nontrivial new
visualization code, mock up a few directions first (even a rough
sketch) and check in before implementing — this is exactly how the
old static-map style was arrived at, over several rejected mockup
rounds (see `Project-Memory/` for the session that did this). It's also
exactly what made the case for replacing that renderer entirely: no
amount of further mockup iteration on TownShape's own matplotlib output
closed the gap to what an existing, purpose-built tool already drew.

## Current State

### The map export (settlemaker's own SVG)

**2026-09-09 — replaced, not iterated on.** `town_db/render.py` (the
matplotlib ink-on-parchment renderer this section used to describe in
detail) is deleted. `town_shaper.generate.generate_town()` now persists
`Town.svg` — settlemaker's own themed SVG for that exact generated town,
produced as a side effect of the same subprocess call that produces the
district/building geometry (see `01-generation-layer.md`) — verbatim,
next to the `.db` file, via `generate_town_database`'s `svg_path`
argument (defaults to the `.db` path with its extension swapped).
`scripts/generate_town.py` writes both files by default.

This resolves several things the old renderer's Feedback section used
to track as open gaps, for free: settlemaker draws real streets (the old
renderer gave up on this entirely after four failed filtering attempts —
see git history), farmland with furrow-texture fill, a proper walled
core with towers and gates, and every building — landmarks included —
as its own real footprint with a type-appropriate glyph, not a marker at
a point. None of that is TownShape's own rendering code to maintain
anymore.

**Attribution / license note:** settlemaker's SVG symbol library (the
glyphs actually drawn) is licensed CC-BY-4.0 *separately* from
settlemaker's own GPL-3.0 code, with a "Rendered Output Exception" —
maps drawn with the symbols carry no attribution obligation, because
attribution can't survive compositing into a larger map (see
`settlemaker_bridge/node_modules/settlemaker/NOTICE` for the exact
terms once `npm install` has run). So persisting settlemaker's SVG
output as-is, as TownShape does, needs no per-generated-map credit. The
tool itself is still credited once, in the README's Acknowledgments
section.

### Interactive web viewer (`town_viewer/`)

Unaffected by the migration except upstream data provenance: still
Flask + vanilla JS canvas, pan/zoom, click a building for its detail
(who works/lives there), a searchable resident list, click-through
between a resident and their home/workplace. Draws real building
footprints from the `buildings.footprint` column — that column is now
populated from settlemaker's polygons instead of the old hand-cut ones,
same schema, same viewer code, no changes needed. `town_viewer/queries.py`
still reads and returns `road_nodes`/`road_edges` for the canvas to
draw — those tables are now always empty (see `01-generation-layer.md`'s
Road network note), so this silently draws nothing rather than
anything wrong. Harmless, but dead weight worth deleting next time
`town_viewer/` gets real attention.

## Feedback & Future Ideas

### Landmark buildings should get real footprints too

**Status:** Addressed, by the settlemaker migration (2026-09-09) — not
by the fix originally proposed here

The original ask was for `render_town`'s drawing loop to stop
special-casing landmark building types out before checking `footprint`.
That code is gone along with the rest of `render.py`; settlemaker draws
every building, landmarks included, with its own real footprint and a
type-appropriate glyph in the SVG TownShape now just persists.

### Static renderer and interactive viewer had diverged on roads

**Status:** Addressed, incidentally — nothing left to diverge over

The static renderer that stopped drawing roads is gone. The interactive
viewer's road-drawing path still exists but reads permanently-empty
tables (see Current State above) — not a visible bug, since it draws
nothing rather than something wrong, but see the cleanup note above.

### An older, since-resolved item, kept for history

**Status:** Addressed 2026-09-04 (from the old `IDEAS.md`)

Arterial roads used to render as straight, uniformly thick black lines
radiating from a single hub point, cutting hard diagonals across
district polygons and rooftops. Resolved that session by routing along
the real district-boundary graph instead of straight radials — later
superseded entirely, first by the decision to stop drawing roads at
all, then by the settlemaker migration replacing the renderer outright.

### Open, undiscussed: a distinct issue in one small-town mockup

**Status:** Open, but likely moot — flagged by the user as "we can
discuss later" against the *old* renderer, never returned to before the
pipeline-port work took priority, and the entire rendering approach it
was flagged against no longer exists. No detail was ever captured about
what specifically looked wrong. If it still matters, revisit fresh
against a settlemaker-generated small town (the new village engine —
see `01-generation-layer.md`) rather than trying to reconstruct what the
original complaint was about.

### The interactive viewer never got settlemaker's visual treatment

**Status:** Open — flagged by the user 2026-09-09, comparing a
`town_viewer` screenshot against the settlemaker SVG shown earlier the
same session ("this looks much, much poorer quality than what you
showed me previously")

The two rendering paths have never been connected. Settlemaker's own
SVG (what a user sees via the persisted `.svg` file, or the Pipeline
Specimens-style demo) has a real parchment palette, walls, streets,
farmland texture, and per-building glyphs. `town_viewer/static/app.js`
draws its own flat canvas rectangles instead, with only a handful of
hardcoded colors (`LANDMARK_COLORS`, `COMMON_BUILDING_COLORS` — e.g.
`tavern: "#b5651d"`, `shop: "#daa520"`) and everything else —
`GENERIC_BUILDING_COLOR = "#555555"`, i.e. every ordinary house —
falling back to flat dark gray. This isn't a regression from any recent
work; the viewer was always built for *interactivity* (click a building
or resident, search, see detail) rather than visual fidelity, and
nobody has connected the two since settlemaker replaced the static
renderer.

Real options, not decided here: (a) give `app.js`'s canvas renderer a
richer, settlemaker-inspired palette (more building-type colors, zone
tinting) without changing its interaction model; (b) render
settlemaker's actual persisted SVG as the map layer and lay the
existing click/search interactivity on top of it (bigger lift — needs
click-to-building hit-testing against the SVG's real shapes, not the
canvas's own draw calls); (c) leave it as-is, since its job is
information density and click-through, not prettiness, and the two
tools can keep serving different purposes. Whoever picks this up should
weigh effort against how much the interactive viewer actually gets used
day to day.
