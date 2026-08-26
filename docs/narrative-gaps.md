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

**Status:** Open

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

**Status:** Open
**Priority:** High

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
