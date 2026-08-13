# Town Shaper — Spatial & Population Generation Design

## Context

This is the first of four sub-projects that together form a larger goal: a
tool that generates a realistic medieval town, populates a relational
database with plausible records for that town (purchases, taxes, births,
deaths, school/university/military enrollment), builds a relationship graph
between residents, and eventually lets an agent simulate a day in the town's
life (e.g. an epidemic among farmers causing food shortages that kill other
residents).

The four sub-projects, in dependency order:

- **A. Town Shaper (this spec)** — spatial layout (districts, buildings) and
  population placement (who lives/works where)
- **B. Relational database** — realistic town records, built on top of A's
  population and buildings
- **C. Relationship graph** — family/work/neighbor/military links between
  residents; likely derivable from B's data rather than a fully separate
  generation step
- **D. Agent-driven daily simulation** — cascading daily events, built on
  A + B + C as its substrate

This spec covers **A only**.

### Reference material

Three existing repos informed this design:

- `gamemaster-scripts/general/popgen` and `TownShape/population-gen.py` —
  eager, unseeded generation of a `Town` of `Resident`/`Building` objects in
  one batch call. Simple, but can't reproduce a specific town, and must hold
  the whole population in memory at once.
- `dnd5e-town-generator` — a Flask app that generates towns lazily and
  deterministically: every object carries a seed tuple, and generator
  functions call `random.seed(str(seed))` before drawing values. This makes
  arbitrarily large populations cheap to *declare* (nothing is generated
  until a specific person/house is requested), but reseeding global state on
  every property access is wasteful when actually materializing a whole
  town.
- `donjuan` — a battle-map generator with a clean `Grid`/`Cell`/`Edge`/
  `Space`/`Room` primitive model. Its primitives have no third-party
  dependencies and could technically be imported standalone, but its grid is
  sized for a single battle-map scene (default 24×24 cells, examples as
  small as 4×5), not a town-scale layout, and it has no concept of districts/
  zones. Used as a design reference, not a dependency.

Town Shaper borrows the reproducibility of dnd5e-town-generator's seeding
without its reseed-per-property cost (see **Determinism** below), and
borrows donjuan's separation of spatial primitives without taking it as a
dependency.

## Scope

Town Shaper is responsible for **where things are and who lives/works
where**. It is not responsible for rich resident detail (names, personal
traits, transaction history) — that's generated later by the database
sub-project (B), using Town Shaper's output as the skeleton to attach
records to. This keeps A focused on geometry and structural relationships
and avoids building demographic-detail generation twice.

Target scale: full town / small city, low thousands of residents.

## Data Model

- **`Town`** — bounding area, seed, target population; holds the list of
  districts.
- **`District`** — an irregular (Voronoi) polygon, a zone type (civic,
  merchant, rich residential, poor residential, farmland/edge), and the
  anchor point it grew from.
- **`Building`** — position, footprint, type/subtype (residence, shop,
  tavern, farmstead, ...), owning `District`, capacity, and the job
  vacancies it creates (see **Jobs as a resource pool**).
- **`ResidentSlot`** — id, home `Building`, workplace `Building` (nullable
  for children/non-working residents), SES tier, occupation category, broad
  age bracket. Not a full character profile — see **Scope** above.

## Generation Pipeline

All randomness is derived from one top-level town seed.

1. **Derive sub-seeds** for each stage (e.g. `(seed, "anchors")`,
   `(seed, "buildings")`, `(seed, "residents")`) so each stage's randomness
   is independent and individually reproducible.
2. **Place anchors.** The number of districts scales with target
   population. Each anchor is placed with a structural bias — civic/market
   anchors near the town centroid, farmland/poor anchors biased toward the
   edge, merchant/rich in between — and target zone-type *proportions*
   (not pure chance) determine how many anchors of each type get placed, so
   no seed can produce a degenerate town (e.g. 90% farmland).
3. **Compute the Voronoi diagram** over the anchors (`scipy.spatial.
   Voronoi`), clipped to the town's bounding box (via the standard technique
   of adding distant phantom points, then intersecting resulting polygons
   with the box). Each anchor's cell becomes its `District`.
4. **Fill buildings** within each district polygon via Poisson-disc
   sampling. Target building count is derived from district area × a
   density figure for that zone type; building type/subtype is drawn from a
   per-zone-type distribution table. Each building creates job vacancies
   appropriate to its type (a shop creates a shopkeep vacancy plus N staff
   vacancies, a farmstead creates farmhand vacancies, etc.) — see **Jobs as
   a resource pool**.
5. **Assign residents.** Generate household groups (adult + optional spouse
   + children, following the family-linking pattern from popgen /
   dnd5e-town-generator). Assign each household to a residence matching its
   SES to the district's wealth tier, with a small chance of drifting one
   tier (same idea as dnd5e-town-generator's `sort_buildings`). Working-age
   household members then draw from the open job-vacancy pool created in
   step 4 to determine their occupation and workplace.

### Jobs as a resource pool

Rather than rolling a resident's occupation first and hoping a matching
workplace exists, buildings create job vacancies when placed (step 4).
Resident generation (step 5) draws from that vacancy pool to decide who
fills what job. This closes the loop by construction: there is never a
resident needing a job that doesn't exist, so no retry/fallback logic is
needed for occupation-building mismatches.

## Determinism

Every generation function takes an explicit `random.Random(derived_seed)`
instance and passes it down explicitly — it never calls the global
`random.seed(...)` / module-level `random.random()`. This preserves the
reproducibility benefit of dnd5e-town-generator's approach (regenerate the
whole town, or one specific district/building, from its seed path alone)
without redundant reseeding on every attribute access, and without shared
mutable global state.

## Error Handling & Edge Cases

- **Voronoi boundary regions** are unbounded by default; clipped against the
  town's bounding box (phantom points + polygon intersection).
- **Small/degenerate towns** (too few anchors for a stable Voronoi diagram)
  are out of scope for v1's target scale — enforce a minimum anchor count
  and raise a clear error below it, rather than producing a malformed
  diagram.
- **Poisson-disc packing shortfall** (a district's target building count
  doesn't physically fit its polygon): deterministically reduce footprint or
  count based on available area, rather than silently varying density by
  packing luck.
- **Zone proportions** are enforced by anchor-type quotas (step 2), not left
  to chance.

## Testing Strategy

- **Determinism**: same seed regenerates byte-identical output, both for a
  whole town and for a single district/building looked up by its seed path.
- **Geometric validity**: districts partition the bounding box with no
  gaps/overlaps beyond float tolerance; buildings lie inside their assigned
  district; buildings respect minimum spacing.
- **Population consistency**: building occupancy never exceeds capacity;
  every working resident's job matches a real vacancy; total workforce never
  exceeds total vacancies.
- **Proportion + scale checks**: district-type proportions land within
  target tolerance across many seeds/sizes; a low-thousands-population town
  generates within an acceptable time budget (regression guard against
  accidental O(n²) behavior).

## Out of Scope for This Spec

- Rendering/visualizing the map (data structure only, for now)
- Rich resident profiles (names, traits, inventories) — deferred to the
  database sub-project (B)
- The relational database, relationship graph, and simulation agent
  themselves (sub-projects B, C, D)
