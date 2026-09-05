# TownShape: Future Ideas & Directions

Running notes on where TownShape could go next. This is a scratchpad, not
a spec — add new ideas under the relevant section (or a new one) as
they come up. 

## Core concept

A tool for generating internally-consistent, database-backed medieval
towns for tabletop (D&D-style) campaigns — from spatial layout down to
individual residents, their households, jobs, purchases, and
relationships to one another. Everything is deterministic: a given seed
+ parameters always regenerates the exact same town, and a town can be
replayed forward in time (`advance_town`) or edited mid-campaign
(kill/injure a resident, declare a disease event) without breaking that
consistency.

## V1: Current Version

### Backend

#### Population Generation

Lives mostly in `town_db/`, on top of the spatial layout `town_shaper`
produces:

- **Residents** — demographically enriched per person: age, sex, race,
  socioeconomic status (SES: poor/rich), noble status, magical talent,
  home building, workplace building, occupation. Households group
  residents by family (`family_name`, race, wealth).
- **A year of historical registry data**, generated alongside the
  population: purchases (from shops, taverns, market stalls...), tax
  payments, births, deaths (with cause — illness, skirmish, old age...),
  disease events, school/university enrollment, military service, and
  (if `aggression > 0`) skirmish events between the poor quarter and the
  city guard.
- **Wealth & income model** — every household has a running wealth
  balance driven by occupation/SES-tiered daily income
  (`town_db/economy.py`); purchase frequency, quantity, and luxury-good
  selection scale with a household's current wealth tier, so rich
  households now measurably out-spend poor ones over time.
- **Relationships** (`town_relationships/`) — derived purely from the
  data above, no new randomness: spouse, parent, sibling, household
  member, coworker, neighbor, unit mate (military), classmate (school),
  and resident-to-shop relationships.
- **Year-advance simulation** (`town_db/simulation.py`) —
  `advance_town(db_path, seed, years)` replays an existing town forward
  N more years against its *current* state: vital records, purchases,
  taxes, school/military service, household formation (adult children
  pairing off and moving out), and job-market succession (apprentices
  promoted into vacated positions), then re-derives relationships.
- **Mid-campaign editing** (`town_db/edits.py`) — `kill_resident`,
  `mark_resident_ill`, `scope_disease_event`, `create_disease_event`.
  Downstream consequences (job vacancy, purchase reassignment, shop
  reputation) ripple through the database correctly.
- **Narrative-language parameters** (`town_narrative/`) — a
  `TownParameters` dataclass (population, physical size/density, wealth,
  water features, magic prevalence, aggression...) that a freeform
  description like "a small, wealthy port town, seaside, orderly" can be
  mapped onto (see `docs/narrative-town-parameters.md`).

#### Town Generation

Lives in `town_shaper/`:

- **Districts** — organic Voronoi diagram around per-zone anchor points,
  zoned by type (civic, merchant, rich/poor residential, port,
  farmland_edge...). District boundaries double as the base for the
  street network.
- **Water features** — optional rivers and coastline, carving real
  unbuildable space out of the town when requested.
- **Road network** — a real, persisted graph of nodes/edges laid over
  the district geometry: hub selection, radial arterial roads, boundary
  roads from Voronoi ridges, spur edges. Urban zones additionally get
  **block/lot subdivision**: each urban district is recursively split
  into blocks by local streets (a new `road_type="local"` edge), then
  each block's frontage is carved into fixed-size lots, one building per
  lot.
- **Buildings** — every building (urban or farmland) now has a real
  rectangular footprint (width/height/rotation), not just a point.
  Urban zones place buildings on street-fronting lots (see above);
  `farmland_edge` keeps the older Poisson-disc point placement with a
  fixed default footprint.
- **Determinism** — all randomness flows through a single
  `rng_for(seed, *path_parts)` helper; no global `random` state anywhere
  in the pipeline.

#### Feedback

1. Multiple Taverns have the same assigned name (in the current city, I
   have seen multiple The Weary Traveler instances).

   **Looked into it:** confirmed, and it's structural, not a fluke.
   `BUILDING_NAME_POOLS["tavern"]` (`town_shaper/buildings.py`) has only
   4 names, and every tavern independently draws `rng.choice(name_pool)`
   with replacement — both in the original Poisson-disc placement path
   and in the newer lot-based placement (`town_shaper/blocks.py`). With
   more than a handful of taverns (and per `docs/narrative-gaps.md`, a
   10,000-pop test town generated **91** of them), duplicate names are
   expected, not a bug in the RNG. This is closely related to two gaps
   already logged in `docs/narrative-gaps.md` — "no singleton cap on
   civic buildings" and "merchant building counts are realistic but
   unmanageable for a campaign" — but the *name*-collision angle isn't
   logged there yet specifically. Not fixed here — worth deciding
   whether the fix is a bigger name pool, sampling without replacement
   until a pool is exhausted (then falling back to a suffix like "The
   Weary Traveler (Docks)"), or folding it into the broader
   population-scaled-cap idea from that gaps log. Say the word if you
   want this actually fixed, or logged into `narrative-gaps.md` as its
   own entry.

### Visualization Features
IMPORTANT: as we delve into visualization features, it is important for me to have an idea of what the visualization might look like BEFORE you write the code and spend my resources. It would be great if you could offer mock ups of the possible ways in which the visualization might look like, before actually writing the code. It does not have to be super precise, even just a sketch for me to get an idea whether we are on the same track (that was not the case for the last implementation you did for the streets)

Current state, for context on the feedback below:

- **Static PNG** (`town_db/render.py`) — districts by zone color, water,
  roads (hierarchy-styled: arterial vs. local), and non-landmark
  buildings drawn as rotated-rectangle footprints (not dots anymore);
  landmark buildings keep distinct markers.
- **Interactive web viewer** (`town_viewer/`, Flask + vanilla JS
  canvas) — pan/zoom map, click a building for its detail (who
  works/lives there), a searchable resident list, click-through between
  a resident and their home/workplace.

#### Feedback
1. The visualization is absolutely atrocious. It does not look like an
   organic city at all, it mostly looks like random thick lines being
   thrown around. For the visual generation, I would like something
   like what you can find at this website
   https://watabou.itch.io/medieval-fantasy-city-generator, for which
   you can find at least part of the code here
   "C:\Users\Effem\OneDrive\Desktop\personal\Development\Town_Generator\TownGeneratorOS".

   **Status check (corrected):** I first assumed this was written before
   the road-network/building-footprint work and might already be
   resolved by it — wrong. This is feedback on the *current* render
   (confirmed by generating a fresh town on today's `main` and looking
   at it directly), and it still stands. The building footprints did
   land, but the road network is still the main offender: arterial
   roads are drawn as straight, uniformly thick black lines radiating
   from a single hub point, cutting hard, unbroken diagonals straight
   across district polygons and rooftops — exactly the "random thick
   lines thrown around" look, not organic streets. Still **not**
   accounted for. Per the instruction above: before writing any more
   visualization code, sketch/mock up a few directions (e.g. curved or
   segmented streets instead of dead-straight radials, width/style
   tuned down, streets routed to *not* overlap buildings) and check in
   here first.

   **Resolved 2026-09-04:** implemented per
   `docs/superpowers/specs/2026-09-04-organic-town-rendering-design.md` /
   `docs/superpowers/plans/2026-09-04-organic-town-rendering.md`. Streets
   inside the urban core are now the implicit gap between inset block
   polygons (no drawn line), arterial roads follow the real district
   boundary graph instead of straight hub-and-spoke lines, and buildings
   fully tile each block via recursive subdivision. A population-scaled
   cap keeps named/business building counts (taverns, shops, etc.)
   bounded so this doesn't worsen the duplicate-tavern-name issue logged
   above under "Backend > Population Generation > Feedback" (item 1).

### Open questions

`docs/narrative-gaps.md` is the running log for open realism/data-quality
gaps and narrative-mapping shortfalls (with Open/Deferred/Addressed
status per entry) — check there before adding a new one here, to avoid
duplicating it in two places.
