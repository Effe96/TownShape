# Visual Interface — Brainstorm

Scratchpad for figuring out how to actually *see* generated towns, beyond
the current static-PNG output. Fill in freely; doesn't need to be tidy.

## Current state

- Rendering today: `town_db/render.py` (matplotlib, `Agg` backend) →
  static PNG via `scripts/render_town.py`.
- Draws: zone polygons (color by type), water, buildings as colored
  markers (landmarks get distinct shapes, generic buildings a dot).
- Limitation prompting this doc:
  _(why is the current PNG not enough? e.g. can't zoom, can't inspect a
  building's data, can't compare runs, no relationships/households view...)_

## What do you want to see that you can't today?

- I want to have a live visualization tool, to see how the different parameters might affect the city. The UI should have a zoomable map of the city with the buildings (even just as rectangles or squares for now). If I click on a building, it tells me what that building is, and show me the data of who works/lives there. 
- The UI should also have to the side the table with the people that live in the town, that you can open and navigate. Clicking on a person shows where they live and work, and viceversa. If a person is chosen, it should be possible to visualize all their corresponding data (payments, family...). 
- It should be possible to download and print a birdview of the city, both in the current format and drawn as an old-style fantasy map.

## Who's this for?

- [ ] Just me, local iteration while developing the generator
- [ ] Sharing snapshots with others
- [X] Long-lived tool I'll keep coming back to

## Shape of the interface

Options to weigh (not mutually exclusive):

- **Better static export** — keep it a script, improve the matplotlib
  render (labels, legend, hi-res, multiple layers as separate images).
- **Local interactive viewer** — THIS --> one static HTML file (open in browser),
  reads the town DB/JSON, pan/zoom, click a building for details.
- **Small local web app** — THIS --> a server (Flask/FastAPI?) serving a live view,
  maybe with a "regenerate" button.
- **Notebook-based** — Jupyter + a plotting lib for ad hoc exploration.

Leaning toward:

## Data available to visualize

Skim `town_shaper/models.py` and `town_db/` for what's already
structured (districts, buildings, households, relationships, water,
anchors...) — note anything you want surfaced that isn't rendered today:

- `town_shaper/models.py`: `Building`, `District`, `Household`
  (`has_spouse`, `child_count`), `ResidentSlot` (SES, age bracket, home
  building, workplace building, occupation), `WaterFeature`. None of
  this is per-person detail beyond `ResidentSlot`.
- `town_db/` has richer per-person data not in the models above:
  `economy.py`, `taxes.py`, `purchases.py` (income/wealth/payments),
  `simulation.py`. **Not yet checked:** `town_relationships/` — likely
  where named-family / spouse-child links live, needed for the
  "family" panel on a person.
- **Checked `town_relationships/`** — it does cover this. `residents`
  table (`town_db/schema.py`) has `first_name`, `last_name`, `gender`,
  `race`, `birth_date`/`death_date`, `ses`, `is_noble`,
  `has_magical_talent`, `home_building_id`, `workplace_building_id`,
  `occupation`. A `relationships` table
  (`town_relationships/schema.py`) links resident pairs with a type —
  `family.py` derives `spouse` / `parent` / `sibling` /
  `household_member` from household + birth records; `work.py`,
  `neighbors.py`, `school.py`, `military.py` add colleague/neighbor/
  classmate/service-together links the same way. `shop_relationships`
  (purchase_count, total_spent, is_primary...) is the per-person
  spending data for the "payments" ask.
- **Conclusion: no data-model gap.** Everything the UI wants (name,
  household, family tree, work, purchases/spending) already exists in
  the DB — this is a read/query + display problem, not a
  generation-side one. The work is building a query layer (or API)
  over `town_db` + `town_relationships`, not adding new relationship
  types.

## Open questions
- I would like for this tool to become available as a tool for people to use via a website, like donjon, so this interface must also offer that.
- I would also like to integrate it into my very own website, where I would like to have the cities that I develop available for people that visit it to see. If you have any ideas on what this could look like, maybe we could work on it afterwards

## Design gaps to resolve

Raised during review, verified against the code — worth deciding
before/while planning the MVP:

- **Buildings are points, not footprints.** `Building` in
  `town_shaper/models.py` only has `x, y` — no width/height. Drawing
  them as rectangles means inventing a placeholder size per
  `building_type`, not reading real geometry. Decide that sizing
  scheme (and how it affects click hit-testing) up front.
- **The town isn't static.** `town_db/simulation.py` steps years
  forward (births, deaths, job market, purchases). `town_db/edits.py`
  explicitly documents that its mutations (illness, death, disease
  events) leave `relationships` / `shop_relationships` **stale with no
  supported re-derive path**. A "live" viewer needs either a
  re-derive-on-write step, or to be explicit it's showing a snapshot
  as of the last derivation — otherwise a person click can show wrong
  family/work links after an edit.
- **Read-only vs. editable.** Undecided whether clicking a
  building/person is view-only, or should let you trigger edits (kill
  a resident, reassign a job) through the UI. Large scope swing —
  pin down before designing the API layer.
- **Scale is unknown.** No stated target town size (dozens vs.
  thousands of residents/buildings). Decides whether a naive canvas
  render + full side-table works, or clustering/virtualized lists are
  needed from day one.
- **Multi-town.** The "public site like donjon" goal implies a
  gallery/list of towns with identity (slugs, ownership) — bigger
  than the local single-DB viewer alone.
- **Print export is vector, current renderer isn't.** matplotlib PNG
  is raster; a printable birdview usually wants SVG/PDF. Likely a
  separate implementation path from the interactive map.

## Decision log

_(once you land on an approach, note it here with the why, so a future
session — yours or a contributor's — doesn't relitigate it)_

- **2026-09-01 — MVP scoped as a read-only, local, single-town viewer.**
  Full brief and requirements now live in
  [visual-interface-brief.md](visual-interface-brief.md) and
  [visual-interface-requirements.md](visual-interface-requirements.md).
  Key calls: read-only (no edits) for v1; shows one freshly-generated
  town as a fixed snapshot, no time-stepping/simulation playback;
  local web app only, no hosting/multi-town/public site yet. Origin:
  the tune-a-parameter → regenerate → squint-at-PNG loop. Checked
  `my_town.db` for scale — 5,155 residents / 1,174 buildings / 114k
  relationships — so resident search + pagination is a Need, not a
  nice-to-have.
