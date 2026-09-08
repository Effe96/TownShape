# Visualization Layer

### How a generated town is actually shown to the user: the static ink-on-parchment map export and the interactive pan/zoom web viewer. Lives in `town_db/render.py` and `town_viewer/`.

**Process note that still applies:** before writing any nontrivial new
visualization code, mock up a few directions first (even a rough
sketch) and check in before implementing — this is exactly how the
current static-map style was arrived at, over several rejected mockup
rounds (see `Project-Memory/` for the session that did this).

## Current State

### Static PNG (`town_db/render.py`)

An ink-on-parchment style deliberately modeled after hand-drawn fantasy
city maps (Watabou's generator was the reference point, technique-only —
see `01-generation-layer.md`), not a GIS zoning overlay:

- One muted building color for the whole town — no per-zone color
  tinting anywhere, farmland included. A hard-edged tinted polygon reads
  as "a zone boundary" regardless of how continuous the underlying
  building density actually is.
- Every non-landmark building is drawn as its real generated footprint
  polygon (single ring, or several rings for a courtyard building — see
  `01-generation-layer.md`), not a placeholder rectangle or a dot.
- A walled ring (with towers) around the "inner city" zone types
  (civic, merchant, rich_residential, port), computed from each
  district's largest polygon part only.
- **No road lines are drawn at all.** Four rounds of increasingly
  specific filtering (zone check, length cap, endpoint-proximity check,
  proximity sampled along a line's entire length) each still left some
  real generated town with a visible stray line — the decisive case was
  a spur whose every sampled point was within 0-6 units of some
  building, yet still rendered as a plainly visible mark, because "a
  building is nearby" isn't "a building's footprint visually covers
  this exact line." Street texture on the map now comes entirely from
  the block-cutting algorithm's own building gaps.
- Water features render as real polygons-with-holes (an island inside a
  bay or lake shows as land, not water) via a matplotlib `PathPatch`
  with one exterior-then-holes `Path` per feature — fixed this session
  after a real generated coastline exposed the bug (every ring was
  previously drawn as its own separately-filled solid shape, painting
  the island as water).
- Landmark building types (temple, town_hall, school, garrison,
  tavern, shop, ...) still render as a marker/icon at their center
  point, not their real footprint — see the queued idea below.

### Interactive web viewer (`town_viewer/`)

Flask + vanilla JS canvas: pan/zoom map, click a building for its detail
(who works/lives there), a searchable resident list, click-through
between a resident and their home/workplace. Draws real building
footprints (not icons), added separately from the static renderer.

## Feedback & Future Ideas

### Landmark buildings should get real footprints too

**Status:** Proposed (queued by the user during this session's mockup
work — "queue it please")

Every other building already gets a real footprint polygon on the
static map; landmarks are the one remaining exception, still a marker
placed at a point. The underlying footprint data exists (landmarks go
through the same block-cutting/lot pipeline as any other building in
their zone) — `render_town`'s drawing loop just special-cases landmark
building types out before ever looking at `footprint`. Proposed
direction: draw the real footprint with a per-type fill color instead
of (or as well as) the current marker, so landmarks read as an actual
building on the map rather than a pin.

### Static renderer and interactive viewer have diverged on roads

**Status:** Open (found while writing this document, not yet raised
with the user)

`town_viewer/queries.py` still reads and presumably still draws
`road_nodes`/`road_edges` on the interactive canvas. The static renderer
used to do the same thing, and categorically stopped after repeated
attempts to filter out visually-stray lines all failed (see Current
State above) — the same underlying road graph (straight ridge/spur/
arterial edges) is very likely still producing the same "random thick
lines" look in the interactive viewer, just unnoticed because attention
was on the static map this session. Worth a look before it's the next
"the map looks bad" report.

### An older, since-resolved item, kept for history

**Status:** Addressed 2026-09-04 (from the old `IDEAS.md`)

Arterial roads used to render as straight, uniformly thick black lines
radiating from a single hub point, cutting hard diagonals across
district polygons and rooftops. Resolved by routing arterial roads
along the real district-boundary graph instead of straight radials, and
implicit inset-gap streets for the urban core — later superseded
entirely by this session's decision to stop drawing roads at all.

### Open, undiscussed: a distinct issue in one small-town mockup

**Status:** Open — flagged by the user as "we can discuss later," never
returned to before the pipeline-port work took priority. No detail was
captured about what the issue actually was; revisit by generating a
fresh small town and asking what specifically still looks wrong, rather
than guessing.
