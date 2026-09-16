# Narrative Gaps Log

A running log of places where real narrative input didn't map cleanly onto
the current generation system — either because no parameter captures a
theme the narrative expresses, or because a generated result contradicted
what the narrative described. Each entry records what was tested, what
came up short, and whether/how it's been addressed.

This is a review log, not a spec — a gap logged here is a candidate for a
future capability or parameter, not a commitment. Update an entry's status
when it's addressed elsewhere (spec, plan, or code change) rather than
deleting it, so the history of what was considered stays visible.

## Status key

- **Open** — not addressed, no decision made yet
- **Deferred** — considered, deliberately not addressing now, reason given
- **Addressed** — resolved, with a pointer to where

## Priority key

Most entries carry no priority marker — ordinary backlog. Only entries
explicitly flagged as more urgent (by the user) get a **Priority: High**
line, so the marker stays meaningful.

---

## 2026-09-16 — generating Palifas from a real campaign narrative

Source: a real D&D campaign narrative document (`Palifas.md`, Scission
Campaign), mapped to `TownParameters` and generated end-to-end.

### Gap: no way to express a symmetric/planned city layout

**Status:** Deferred — user's own words: "we will come back to it when we
start working on the agentic control and narrative control layer for the
tool."

The narrative described Palifas as rebuilt "perfect from a geometric
point of view" by a hired architect — implied to read as symmetric along
a single axis. The actual town layout comes entirely from settlemaker (an
external Voronoi-patch-based procedural generator, called as a
subprocess) via `settlemaker_bridge.pipeline.generate_via_settlemaker` —
ward placement is driven by randomized rating functions with no concept
of an axis of symmetry, and no parameter anywhere in `TownParameters` or
the settlemaker burg input requests one. Producing a genuinely
mirror-symmetric town would mean either (a) a schematic/illustrative
diagram instead of a real generated town, or (b) generating half a town
and mirroring it programmatically — nontrivial, since roads/walls/districts
wouldn't naturally line up at the seam. Left as narrative flavor for now.

## 2026-08-26 — test generation from a real campaign narrative

Source: a real DM's campaign narrative document, mapped to
`TownParameters(target_population=10000, num_rivers=1)` and generated
end-to-end. The narrative's specific content and identifying details are
deliberately not reproduced here (private campaign material) — only the
generation-system gaps it surfaced.

### Gap: no parameter for a culture-wide militarization trait

**Status:** Open

The narrative described a population where every resident, regardless of
gender, is trained for combat — a standing cultural trait, not tied to
any internal unrest. The generated town had 18 `guard` + 7 `soldier`
occupations out of ~10,000 residents (0.24%), because occupations are
drawn from fixed building-type job-vacancy tables
(`JOB_VACANCIES_BY_BUILDING_TYPE` in `town_shaper/buildings.py`), not
from any narrative-driven cultural trait.

Distinct from `aggression` (which models *internal* unrest between poor
residents and the city guard) — this is about the overall population's
military training/participation, independent of any internal conflict.
No existing parameter captures it.

### Gap: no parameter for religiosity / religious sentiment

**Status:** Open

The narrative described a town whose population had actively rejected
its own former state religion — present but pointedly unpopular. The
generated town produced temples/priests/acolytes as neutral defaults (4
temples, 2 priests, 5 acolytes) with no way to dial religious presence
down (or up) independent of population size, nor any way to express
hostility toward an existing religious presence.

### Gap: `compute_stress` saturates near 1.0 under default wealth distribution

**Status:** Deferred — already logged as a known follow-up from D1d's
final review (see `docs/superpowers/plans/2026-08-26-town-social-unrest-implementation.md`'s
SDD ledger, since deleted, and project memory). Confirmed again here in
practice: the test town, generated with `aggression=0.0` (zero
skirmishes), still returned `compute_stress(db_path) == 0.9498...`. The
formula (`poor_fraction + skirmish_count * 0.1`, clamped at 1.0) is
dominated by `poor_fraction` alone at the default `rich_proportion=0.05`,
so it can't currently discriminate a calm town from a riot-torn one.
Recalibrate before any future capability actually reads this value.

### Gap: no representation of governance/civic structure

**Status:** Deferred — likely out of scope entirely. The narrative
described a distinctive elected civic government structure, with
different terms of office for an executive role and a separate council.
Nothing in `town_db`/`town_shaper` models civic structure at all.
Probably stays pure narrative flavor unless a future capability
specifically needs to reason about governance (e.g. an NPC's title or
authority) rather than demographics/economy.

### Gap: no representation of aesthetic/architectural theming

**Status:** Deferred — likely out of scope. The narrative described a
distinctive architectural material and style for the town. Nothing in
the generation system tracks building materials, colors, or
architectural style — again probably pure narrative flavor, relevant
only if a future capability needs to generate descriptive text about
specific buildings.

### Realism gap (not a narrative-mapping gap): schools don't scale in count with population

**Status:** Open

Not something the narrative expressed — found while fixing the
`derive_classmate_relationships` combinatorial-blowup bug (see git history,
`town_relationships/school.py`) on this same test town. Unlike workplace
buildings (shops, taverns, etc.), which scale in *count* with population,
`town_shaper` generates only a single `school` building regardless of
town size. The ~10,000-resident test town produced ~2,000 school-age
enrollments funneling through that one building, so even after the
classmate fix correctly scopes relationships to same-age peers, each
age-cohort still lands in one unrealistically large "class" (hundreds of
same-age classmates) with no class-section/room-capacity concept to
subdivide it further. Worth a future look at whether school building
count/capacity should scale with population the way other building types
already do.

## 2026-08-26 — first map render

Source: the first `render_town` output for the same real-campaign test
town (see `scripts/render_town.py`), reviewed together after generation.

### Realism gap (not a narrative-mapping gap): no singleton cap on civic buildings

**Status:** Open

The rendered map showed 9 `town_hall` buildings in one town. Traced to
`town_shaper/buildings.py`'s `BUILDING_TYPES_BY_ZONE[ZoneType.CIVIC]`:
every civic building slot independently rolls a building type from a
fixed weight table (`temple: 0.25, town_hall: 0.1, school: 0.15,
guard_post: 0.25, garrison: 0.1, healer: 0.1, university: 0.05`) with no
concept of "a town has exactly one seat of government." `town_hall` (and
similarly `harbormaster_office` in the port zone) is treated the same as
any repeatable building like a shop or tavern — a large civic district
can roll it many times over. Worth a future look at whether certain
building types should be capped at one (or a small, population-scaled
number) per town instead of drawing independently per slot.

### Usability gap (not a narrative-mapping gap): merchant building counts are realistic but unmanageable for a campaign

**Status:** Addressed

The ~10,000-resident test town generated **202 shops** and **91 taverns**
(0 arcane shops, since `magic_prevalence=0.0`). Demographically this may
be defensible, but it's not usable as a DM tool: a real campaign can't
track hundreds of individually-generated taverns, and a player only ever
needs a handful that matter to the story. User's guidance for a town this
size: roughly **5 taverns per 10,000 population** (so ~5, not 91), shops
capped around **100 total** regardless of population size (not
scaling linearly forever), and the implicit expectation that only a small
subset of any building category needs to be individually
notable/visitable — the rest can stay implied background rather than
fully generated. Worth a future look at whether `BUILDING_DENSITY_PER_AREA`/
`BUILDING_TYPES_BY_ZONE` in `town_shaper/buildings.py` should have a
population-scaled cap (not just a density-per-area roll) for
narratively-prominent building types like taverns and shops, separate
from the question of how many are needed to support the underlying
economic simulation (jobs, purchases, tax base).

**2026-09-04 note:** substantially addressed. The population-scaled
business-density cap specified in
`docs/superpowers/specs/2026-09-04-organic-town-rendering-design.md` is
exactly the "population-scaled cap, not just a density-per-area roll"
this entry asked for. Measured at the same population scale during that
branch's final review: shops down from 202 to roughly 100, taverns down
from 91 to roughly 10. Name uniqueness within a category is a separate
issue, tracked on its own elsewhere.

## 2026-08-27 — spot-checking individual resident profiles

Source: pulling full profiles for specific residents (a magically
talented poor resident and their household) in a low-magic test town,
reviewed together.

### Realism gap (not a narrative-mapping gap): home and workplace zones are assigned independently, with no locality preference

**Status:** Open

A resident working `shop_staff` (presumably in the merchant district) was
found living on a `farmstead` in the `farmland_edge` zone, sharing that
one building with two other, unrelated households (three different
family surnames in a single capacity-8 farmstead). Poor-SES residents can
apparently be housed in either `poor_residential` or `farmland_edge` as
interchangeable overflow, with no relationship to where they actually
work — home and workplace assignment appear to be independent processes.
Not obviously wrong (real towns do have workers commuting from the
edges), but worth a future look at whether home-building assignment
should weight proximity to workplace, and whether farmsteads should host
only farming-occupation residents rather than being generic poor-housing
overflow shared across unrelated families.

### Gap: no individual wealth/income model — SES has no effect on spending

**Status:** Addressed — T11, `docs/superpowers/plans/2026-08-31-household-wealth-model-implementation.md`
(spec: `docs/superpowers/specs/2026-08-31-household-wealth-model-design.md`), PR #9. New
`town_db/economy.py` gives every household a running wealth balance driven by occupation/SES-tiered
daily income, and `town_db/purchases.py` now reweights purchase frequency/quantity/luxury-good
selection by each household's current wealth tier. The regression this gap described is fixed and
covered by a standing test (`test_rich_households_out_spend_poor_households_over_time`,
`tests/test_db_simulation_integration.py`) that asserts rich households' median spend beats poor
households' median spend across a 10-seed sweep — passed on the plan's original constants, no
tuning needed. Two narrower gaps surfaced during T11's implementation are logged separately below
("income tiering is a no-op for most occupations" and "yearly income-variation multiplier isn't
actually year-stable").
**Priority:** High (resolved)

`ses` is currently only a binary poor/rich label with a single economic
consequence: a flat `property_tax` rate (`PROPERTY_TAX_RATE_BY_SES` in
`town_db/taxes.py` — 5.0/quarter rich, 1.0/quarter poor). Purchase
generation (`town_db/purchases.py`) doesn't reference SES at all —
frequency, quantity, and good selection are identical regardless of
wealth. Confirmed empirically: in a test town, the single highest
individual spender for the year was **poor** (211.45 total spent),
outspending every rich resident (top rich spender: 177.69). A rich
character currently cannot be shown consistently spending more, buying
more luxury goods, or living more comfortably than a poor one, beyond the
flat tax difference and which residential zone they're placed in.

User's request: there should be a per-resident income/wealth concept —
"how much money this person has, and makes on a daily basis" — that
actually drives differentiated spending behavior, not just tax and
housing. Flagged by the user as a more urgent issue than most entries in
this log.

### Gap: disease is modeled as a rare, all-or-nothing event instead of an everyday part of life

**Status:** Open
**Priority:** High

`disease_events` currently rolls once per year for a single town-wide
outbreak (`DISEASE_EVENT_CHANCE=0.3` in `town_db/vital_records.py`) — a
town can go an entire year with zero disease events. Meanwhile `illness`
as a cause of death is a completely separate, unlinked baseline mortality
roll that happens regardless of whether an outbreak is active. Confirmed
in a test town: `disease_events` was empty (no outbreak that year), yet
107 deaths were still recorded with `cause='illness'` — ordinary
background mortality, not tied to any disease event at all. There is no
notion of everyday sickness (colds, minor ailments, chronic conditions)
as a constant backdrop; only rare epidemic-level outbreaks exist as a
concept.

User's guidance: disease/illness should be treated as a normal, ongoing
part of daily life, not just a rare special event. Flagged by the user as
a more urgent issue than most entries in this log.

## 2026-08-28 — capability 2 (safe-mode simulation) brainstorm

Source: design discussion for the year-advance orchestrator (capability 2,
slice 1), before any implementation started.

### Gap: town's physical footprint (building stock) is fixed at generation, can't grow or shrink

**Status:** Deferred — explicitly raised and set aside during the capability
2 design discussion, to come back to later.

`town_shaper` lays out districts and buildings once, at town creation. As
capability 2's year-advance orchestrator simulates a town forward over many
years, population can grow or shrink (births/deaths/household formation),
but no mechanism adds new buildings/districts or removes them — the
building stock is a permanent ceiling/floor. Slice 1's design deliberately
handles this with a *soft cap*: when housing is full, new-household
formation slows/pauses rather than overflowing or growing the town, and
unfilled job vacancies are treated as normal economic slack rather than an
error. A future slice may need the town to physically grow or contract
(new construction, abandoned/demolished buildings) for long-run simulation
to stay realistic, but that pulls `town_shaper`'s building-placement logic
into a simulation context it wasn't designed for, and was judged too big
for slice 1.

### Gap: no grandparent (or other multi-generational/extended-family) relationship exists

**Status:** Open

`town_relationships/family.py` only derives `spouse`, `parent`, `sibling`,
and `household_member` — all single-generation or same-household links.
There is no derivation that chains "parent of a parent" into
`grandparent`, and no aunt/uncle, cousin, or in-law relationships either.
A resident's grandparents (if still alive and identifiable via the chain
of `parent` links) are not surfaced as a relationship at all, even though
the underlying data (birth records, household history) would support
deriving one.

## 2026-09-01 — T11 implementation (household wealth & income model), final whole-branch review

Source: the final whole-branch code review for T11 (PR #9), which built the
model this log's "no individual wealth/income model" gap (above) asked for.
Both gaps below are real limitations of that new model itself, found while
verifying it end to end — not correctness bugs (nothing here fails a test
or produces bad data), but places where the model is narrower or less
faithful to its own design than a reader would assume.

### Realism gap (not a narrative-mapping gap): occupation-tiered income is a no-op for most jobs

**Status:** Open

`town_db/economy.py`'s `daily_income` is meant to be "occupation/SES-tiered"
— unemployed < apprentice < primary < noble — but the primary/apprentice
split is decided by `town_db.succession.primary_occupation_info`, which was
built by an earlier task purely for shop-succession purposes and only
recognizes 5 of ~18 building types (`shop`, `tavern`, `market_stall`,
`arcane_shop`, `blacksmith`). Every other occupation — priest, guard,
soldier, healer, teacher, farmer, dockworker, warehouse clerk,
harbormaster, town clerk, and more, including single-capacity "head" roles
that are obviously senior by construction — always resolves to
`"apprentice"` tier and can never reach `"primary"`, regardless of
seniority. The rich-vs-poor spending model still works today because SES
and employed/unemployed status differentiate independently of this gap,
but "occupation" doesn't meaningfully drive income for most of the town's
workforce as currently implemented. Worth a future look at widening
primary/senior-role classification across all `JOB_VACANCIES_BY_BUILDING_TYPE`
building types — likely its own small task, since `primary_occupation_info`
is shared with the `promote_apprentice` succession system it was originally
built for, and widening it needs care not to disturb that.

### Gap: yearly income-variation multiplier isn't actually year-stable, contradicting its own design spec

**Status:** Open

`docs/superpowers/specs/2026-08-31-household-wealth-model-design.md` states
a resident's per-resident income-variation multiplier ("their relative
luck/skill among peers") "stays stable" across every simulated year. In
practice, `town_db/simulation.py`'s `advance_town` passes a per-year
`year_seed` into `add_yearly_income` → `daily_income`'s
`rng_for(seed, "db", "income", resident_id)` call, so the multiplier is
actually re-rolled every year — the plan's own literal Task 7 code
specifies passing `year_seed`, so this is a spec-prose/implementation
mismatch baked into the plan itself, not an implementer deviation. No test
depends on year-stability (only per-seed determinism, which does hold), and
year-to-year income drift is arguably more realistic than a frozen
multiplier — but as written, the code and its own design doc disagree.
Needs a decision either way: fix the implementation to hold the multiplier
stable (derive it from the base town seed, not `year_seed`), or fix the
spec's prose to describe the actual (year-varying) behavior.
