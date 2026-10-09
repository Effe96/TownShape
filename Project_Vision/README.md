# TownShape: Project Vision

Replaces the old root-level `IDEAS.md`, split by stack layer so feedback
and feature requests stay next to the part of the system they're about.

## Core concept

A tool for generating internally-consistent, database-backed medieval
towns for tabletop (D&D-style) campaigns — from spatial layout down to
individual residents, their households, jobs, purchases, and
relationships to one another. Everything is deterministic: a given seed
+ parameters always regenerates the exact same town, and a town can be
replayed forward in time (`advance_town`) or edited mid-campaign
(kill/injure a resident, declare a disease event) without breaking that
consistency.

**Direction (2026-10-10, P002):** the town's *physical* shape should follow
the narrative too — not just knobs on a random generator, but whatever
structure the narrative describes ("three concentric round walls, each with
a moat fed by a redirected river, a heart-shaped church at the centre"),
within stated boundaries. An agent turns narrative into a *layout spec*
(shapes, walls, water, roads, districts, landmarks); the engine builds that
structure and fills the rest procedurally, then the agent reviews the render
and revises. Design: `docs/superpowers/specs/2026-10-10-narrative-layout-engine-design.md`.
Already shipped toward this: physical construction edits on an existing town
(`town_db/construction.py`) and narrative layout knobs (river/road bearings,
citadel).

## How this folder is organized

[`00-proposals.md`](00-proposals.md) is the inbox: file a new change
request or feature idea there first, untriaged. Once triaged it either
resolves right there (addressed/rejected) or graduates into the
relevant layer file below as a standing backlog entry.

One file per stack layer:

| File | Covers | Main code |
|---|---|---|
| [`01-generation-layer.md`](01-generation-layer.md) | Procedural spatial generation: districts, water, roads, block/lot subdivision, building footprints; construction edits on an existing town; the planned narrative layout engine | `town_shaper/`, `settlemaker_bridge/`, `town_db/construction.py` |
| [`02-simulation-layer.md`](02-simulation-layer.md) | Population, economy, history simulation, relationships, narrative-parameter mapping | `town_db/`, `town_relationships/`, `town_narrative/` |
| [`03-visualization-layer.md`](03-visualization-layer.md) | Static map rendering and the interactive web viewer | `town_db/render.py`, `town_viewer/` |

Each layer file has the same two sections:

- **Current State** — what V1 actually does today, layer by layer. This
  is the section to comment on if something shipped doesn't look/feel
  right, or if a description here has drifted from what the code
  actually does.
- **Feedback & Future Ideas** — a flat list of entries: standing
  feedback on the current state, proposed features, and known gaps.
  Add a new entry here for a feature request or change proposal; it
  doesn't need to be fully thought through, a sentence is enough to
  start from.

## Status key

Same convention as `docs/narrative-gaps.md` (the simulation layer's
older, more detailed gap log — still linked from `02-simulation-layer.md`
rather than merged in, so its history stays in one place):

- **Open** — not addressed, no decision made yet
- **Proposed** — a new idea/feature request, not yet triaged
- **Deferred** — considered, deliberately not doing now, reason given
- **Planned** — agreed direction, not yet implemented
- **Addressed** — resolved, with a pointer to where/when
- **Rejected** — considered and deliberately not doing, reason given

## How to give feedback

- **On something in Current State:** add a line right under the
  relevant bullet, e.g. `> Feedback: ...`. It'll get read and folded
  into the next relevant piece of work, and the Current State text
  itself gets corrected once the code changes.
- **A new idea or feature request:** add it to `00-proposals.md` using
  its template — just a title and what you want, in your own words. No
  need to specify implementation, or even which layer it belongs to.
- **Reacting to an existing entry:** add a line under it rather than
  editing the original text, so the back-and-forth stays visible
  instead of getting overwritten.
