# Requirements & Design: Town Viewer

Companion to [visual-interface-brief.md](visual-interface-brief.md).
Every requirement below traces back to a line in that Brief.

## Functional requirements

### Need

1. Load a single town from an existing generated `town_db` SQLite file
   and render its map.
   _Traces to: Brief, "show one generated town as a zoomable,
   pannable map"._
   **Acceptance:** given a valid town DB path, the map renders all
   districts and buildings without manual data prep.
2. Map is zoomable and pannable.
   _Traces to: same._
   **Acceptance:** can zoom from full-town view down to a single
   building being clearly distinguishable, and pan anywhere in between.
3. Buildings render as shapes (placeholder rectangle sized by
   `building_type`, since real footprints aren't stored) positioned by
   their `x, y` and styled by type, at least as legible as today's
   static renderer.
   _Traces to: same._
4. Clicking a building shows its type, district/zone, capacity, and
   the residents who live and/or work there.
   _Traces to: Brief, "click a building and see what it is and who
   lives and works there"._
   **Acceptance:** click any rendered building → a detail panel opens
   listing resident names, each tagged as resident/worker.
5. A side panel lists every resident in the town with real search
   (by name at minimum) and pagination/virtualized scrolling — not a
   plain unbounded list.
   _Traces to: Brief, "searchable list of every resident" +
   "a real generated town is not small" (5,000+ residents observed)._
   **Acceptance:** panel stays responsive against a 5,000+ resident
   town; searching by name narrows the list without a full page
   reload.
6. Selecting a resident highlights their home and workplace building
   on the map.
   _Traces to: Brief, "picking a resident highlights their home and
   workplace"._
7. Selecting a resident shows their profile: name, household, family
   relationships (spouse/parent/sibling/household member), and
   purchase/spending history (from `shop_relationships`).
   _Traces to: Brief, "shows their household, family..., and spending
   history"._
8. Navigation between a building and its residents, and between a
   resident and their buildings, is consistent both directions.
   _Traces to: Brief, same two bullets above._
9. Runs entirely locally (a local server + browser frontend, or
   equivalent) against one town DB file given at launch. No auth, no
   deployment, no persistence beyond that one file.
   _Traces to: Brief, "run entirely on your own machine, pointed at
   one town at a time"._

### Want

10. Legend/labels for zone and building types on the map, consistent
    with the existing static renderer's color scheme, so the map
    reads on its own without opening the data panel.
    _Traces to: Brief, "see the result... at a glance"._
11. A way to point the running viewer at a newly-regenerated DB file
    without restarting the server, to keep the parameter-tuning loop
    tight.
    _Traces to: Brief, "Where the need came from" — the
    tune-regenerate-inspect loop._

### Nice-to-have

12. Visual styling shared/reused from `town_db/render.py`'s color
    constants, so the interactive map and the static PNG look like
    the same tool.

## Explicit constraints and limitations

- **Read-only.** No write endpoints; nothing in the viewer calls
  `town_db/edits.py` or `town_db/simulation.py`.
- **Single town, single session.** No multi-town gallery, no stored
  "current town" beyond the file path passed at launch.
- **No time-stepping.** The DB is treated as a fixed, already-generated
  snapshot. Known gotcha carried over from `town_db/edits.py`: if a
  town's mutations are ever applied after `town_relationships` was
  derived, `relationships`/`shop_relationships` go stale with no
  supported re-derive path. This viewer does not attempt to detect or
  fix that — it displays whatever is in those tables as-is. Handling
  staleness is out of scope for this version.
- **No real building geometry.** `Building` only stores `x, y`
  (`town_shaper/models.py`); rectangle sizes are a rendering
  approximation, not physical footprints.
- **Not hosted, not multi-user, no authentication.**
- **No print/export of a stylized fantasy-style map.**

## Architecture (decisions, with rationale)

- **ADR-1: Ship as a small local web app** — a lightweight Python
  server (Flask/FastAPI) serving a browser frontend, rather than a
  single static HTML file or a notebook.
  Rationale: a server is needed regardless, to query a 5,000+ row
  SQLite DB without shipping the whole thing to the browser up front;
  a thin server also keeps a straight (but not yet committed) path
  toward the later public-site goal, without building any of that now.
- **ADR-2: Map renders client-side** (canvas or SVG in the browser;
  specific frontend approach TBD at implementation time), not as
  server-rendered images, so pan/zoom/click are locally interactive
  instead of round-tripping to the server per interaction.
- **ADR-3: Backend is a read-only query layer over the existing
  `town_db` and `town_relationships` SQLite tables** (`buildings`,
  `districts`, `residents`, `relationships`, `shop_relationships`).
  No new generation-side data is needed — confirmed while scoping
  this project that every field the UI wants already exists.
- **ADR-4: Resident list and per-building/per-resident detail are
  server-paginated/queried on demand**, not loaded to the client in
  full — driven directly by the 5,000+ resident / 114,000+
  relationship row counts observed in a real town DB.

## Open questions and risks

- Building placeholder sizing scheme (fixed size per `building_type`
  vs. scaled by `capacity`) — not yet decided, needed before frontend
  work starts.
- Frontend implementation approach (plain JS/canvas vs. a framework)
  — deferred to implementation planning, doesn't affect this scope
  document.
- Risk: 1,174 buildings rendered at once (real sample town) may need a
  level-of-detail strategy when zoomed out (e.g. cluster/fade small
  buildings) to stay legible — worth a quick spike before committing
  to a rendering library.
- Future public/multi-town site and personal-website embedding remain
  real goals but are explicitly out of scope here; ADR-1's choice of
  "small web app" is meant to not foreclose that path, without
  building any part of it now.
