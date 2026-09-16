# TownShape

A tool for generating internally-consistent, database-backed medieval
towns for tabletop (D&D-style) campaigns — from spatial layout down to
individual residents, their households, jobs, purchases, and
relationships to one another.

Everything is deterministic: a given seed + parameters always
regenerates the exact same town.

> **Status:** actively developed, pre-release. Core generation
> (layout → database → relationships → narrative parameters) is done
> and tested. Mid-campaign narrative editing (kill/injure a resident,
> scope or create a disease event) and year-advance simulation
> (`advance_town` — replay a town forward N more years against its
> current state) are also done. Not yet built: the town's physical
> footprint (buildings/districts) can't grow or shrink as it's
> simulated forward — deferred by design, see `docs/narrative-gaps.md`.
> See that file for other known data-quality gaps and `docs/superpowers/`
> for design history.

## What it does

Generation happens in layers, each depending on the one before it:

1. **`town_shaper`** — spatial layout. District and building geometry
   (zoned by type — residential, merchant, civic, port, ...) comes from
   [settlemaker](https://github.com/barrulus/settlemaker), an external
   generator invoked as a subprocess via `settlemaker_bridge/` — see
   Acknowledgments below. `town_shaper` handles water features (rivers,
   coastline, carving real unbuildable space out of the town),
   households, and assigning residents to a home and workplace within
   settlemaker's generated buildings.
2. **`town_db`** — a SQLite database built on top of a `town_shaper`
   layout: demographically-enriched residents (age, sex, race,
   socioeconomic status) plus a year of historical registry records —
   purchases, taxes, births, deaths, disease events, school/university
   enrollment, military service, and (if `aggression` is set) skirmish
   events between the poor quarter and the city guard.
3. **`town_relationships`** — derives resident-to-resident relationship
   tables (spouse, parent, sibling, household member, coworker,
   neighbor, unit mate, classmate) and resident-to-shop relationships,
   purely from data already in the `town_db` database. Adds no new
   randomness.
4. **`town_narrative`** — the top-level entry point. Takes a
   `TownParameters` dataclass (population, physical size/density,
   wealth, water features, magic prevalence, aggression, ...) and runs
   the full `town_shaper` → `town_db` pipeline in one call. See
   `docs/narrative-town-parameters.md` for how freeform narrative
   description (e.g. "a small, wealthy port town, seaside, orderly")
   maps onto these parameters — this doc is written to be usable by
   any LLM agent, not just Claude Code specifically.

Two more `town_db` capabilities operate on an already-generated database:

- **Mid-campaign editing** (`town_db/edits.py`) — `kill_resident`,
  `mark_resident_ill`, `scope_disease_event`, `create_disease_event`.
  Lets a DM apply a specific narrative event (a resident dies, a plague
  is declared) and have its downstream consequences (job vacancy,
  purchase reassignment, shop reputation) ripple through the database
  correctly.
- **Year-advance simulation** (`town_db/simulation.py`) —
  `advance_town(db_path, seed, years)` replays a town forward N more
  years against its *current* state: vital records, purchases, taxes,
  school/military service, household formation (adult children pairing
  off and moving out), and job-market succession (apprentices promoted
  into vacated positions), then re-derives relationships. Deterministic
  per year, same as one-shot generation.

Every generated town also gets a rendered map for free: settlemaker
produces its own themed SVG as part of the same call that generates the
geometry, and `town_db.generate.generate_town_database` persists it
verbatim next to the `.db` file (see Quick start below) — TownShape
does no rendering of its own.

## Requirements

- Python 3.10+
- `pip install -r requirements.txt` (numpy, scipy, shapely, pytest)
- Node.js (any recent LTS) and `npm install` run once inside
  `settlemaker_bridge/` — town generation shells out to
  [settlemaker](https://github.com/barrulus/settlemaker) (pinned to a
  specific commit in `settlemaker_bridge/package.json`) for all
  district/building/wall geometry and the rendered SVG. See
  `docs/superpowers/specs/2026-09-08-settlemaker-integration-design.md`
  for the full integration design, including a known npm caveat under
  some sandboxed CI environments.

## Quick start

Generate a town and inspect it:

```bash
python scripts/generate_town.py    # edit the constants at the top of the file first
```

`scripts/generate_town.py` is a plain editable-variables script (not a
CLI with flags) — open it and change `SEED`, `TARGET_POPULATION`, and
the other `TownParameters` fields at the top, then run it. It builds the
town, derives relationships, prints a resident count and stress readout,
and writes both a `.db` file and a `.svg` file (settlemaker's own themed
render of the generated town) next to each other.

To drive generation programmatically:

```python
from town_narrative.parameters import TownParameters
from town_narrative.generate import generate_town_from_parameters
from town_relationships.generate import derive_relationships

params = TownParameters(
    seed="riverbend",
    target_population=5000,
    num_rivers=1,
    magic_prevalence=0.1,
)
generate_town_from_parameters(params, "riverbend.db")
derive_relationships("riverbend.db")
```

The result is a plain SQLite database at the given path — query it
directly with any SQLite client, or via `sqlite3` in Python.

## Running tests

```bash
python -m pytest
```

422 tests as of the last update, covering all four packages plus the
settlemaker bridge.

## Repo layout

- `town_shaper/` — spatial layout and population placement
- `town_db/` — SQLite database generation (residents, history, goods,
  purchases, stats)
- `settlemaker_bridge/` — the Node bridge to
  [settlemaker](https://github.com/barrulus/settlemaker) (district/
  building/wall geometry and SVG rendering) and the Python-side parser
  that maps its output onto `town_shaper`'s `District`/`Building` models
- `town_relationships/` — relationship-graph derivation from an
  existing `town_db` database
- `town_narrative/` — top-level `TownParameters` + orchestration across
  the three packages above
- `scripts/` — small runnable entry points (`generate_town.py`)
- `docs/narrative-town-parameters.md` — narrative-language → parameter
  mapping reference
- `docs/narrative-gaps.md` — ongoing log of known realism/data-quality
  gaps found through hands-on use
- `docs/superpowers/` — specs and implementation plans from this
  project's development history
- `tests/` — pytest suite, one file per module
- `*_names.txt`, `adjectives.txt`, `nouns.txt`, `traits.txt`,
  `gerunds.txt` — word lists used by `town_db.names` for
  procedural name/trait generation

## Determinism

All randomness flows through a single `rng_for(seed, *path_parts)`
helper (`town_shaper.seeding`) — there is no use of global `random`
state anywhere in the generation pipeline. The same seed and parameters
always produce byte-identical output.

## Acknowledgments

TownShape's own code is written from scratch, but district/building
geometry and map rendering are not — they come from real work by other
people, credited here in the manner each project's license calls for:

- **[`settlemaker`](https://github.com/barrulus/settlemaker)** by Barry
  Gill, **GPL-3.0-only**. TownShape depends on it directly: every
  district, building, wall, and the rendered SVG for a generated town
  all come from this library, invoked as a separate subprocess (JSON
  over stdin/stdout via `settlemaker_bridge/`, pinned to an exact commit
  SHA — see `settlemaker_bridge/package.json`), not linked into or
  copied from TownShape's own code. That subprocess boundary is why
  TownShape's own license is unaffected by settlemaker's GPL-3.0 — see
  `docs/superpowers/specs/2026-09-08-settlemaker-integration-design.md`
  for the full reasoning. settlemaker's SVG output uses its own symbol
  library, licensed CC-BY-4.0 with a Rendered Output Exception (no
  per-map attribution needed for rendered/composited maps like the ones
  TownShape persists) — see `settlemaker_bridge/node_modules/settlemaker/NOTICE`
  once installed.
- **[`TownGeneratorOS`](https://github.com/watabou/TownGeneratorOS)**
  (the Medieval Fantasy City Generator) by Oleg Dolya ("watabou"),
  **GPL-3.0**. settlemaker is itself a TypeScript reimplementation of
  this project's technique — so it's the origin, two steps removed, of
  every town TownShape now generates. It was also this project's own
  direct stylistic and technique reference (vertex-anchored polygon
  bisection, per-zone "chaos" parameters, courtyard peeling) during the
  hand-built `town_shaper` pipeline that settlemaker has since replaced
  — studied for approach only, never for code, which was independently
  written and has since been deleted.
- **[Fantasy Map Generator](https://github.com/Azgaar/Fantasy-Map-Generator)**
  by Max Haniyeu ("Azgaar"), **MIT**. Researched as prior art (not
  integrated — no code or assets used) while evaluating options for
  TownShape's longer-term, not-yet-scheduled multi-town/world-scale
  vision; see `Project_Vision/00-proposals.md`'s P001 for the research
  notes.

## License

TownShape's own code is **MIT** — see `LICENSE`. This covers only what's
actually written in this repo; it doesn't relicense settlemaker (which
stays GPL-3.0-only, invoked as a separate subprocess and never
vendored/distributed here) or any of the other credited work above.
