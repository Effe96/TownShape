# Town DB — Relational Database Design

## Context

This is the second of four sub-projects toward a tool that generates a
realistic medieval town, populates a relational database with plausible
records for it, builds a relationship graph between residents, and
eventually lets an agent simulate a day in the town's life. See
`docs/superpowers/specs/2026-08-13-town-shaper-spatial-generation-design.md`
for the full four-sub-project context.

- **A. Town Shaper** (done, merged) — spatial layout and population
  placement. Produces `Town(seed, target_population, bounds, districts,
  residents)`, `District`, `Building` (with `JobVacancy`s), and
  `ResidentSlot` (id, household_id, ses, age_bracket, home_building_id,
  workplace_building_id, occupation). Deliberately has no names, race,
  gender, or exact ages — see its spec's "Out of Scope" section.
- **B. Town DB (this spec)** — a SQLite database of realistic town records,
  built on top of A's output: full demographic enrichment (names, race,
  gender, exact ages) plus a year of historical registry records
  (purchases, taxes, births, deaths, disease, school/university enrollment,
  military service). Primary goal: a rich, explorable dataset for
  practicing SQL.
- **C. Relationship graph** — family/work/neighbor/military links between
  residents; likely derivable from B's data.
- **D. Agent-driven daily simulation** — cascading daily events, built on
  A + B + C.

This spec covers **B only**.

### Reference material

`medieval-demographics-made-easy.pdf` (project root) grounds several of
B's numbers: the Support Value (SV) table (population needed to support
one business of a given type — spice merchant 1,400, tavern 400,
blacksmith 1,500, baker 800, doctor 1,700, etc.), the finding that
universities exist at a rate of roughly 1 per 27.3 million people
(computed at the kingdom/continent level, not per town — even large
cities "rarely" have one directly), the law-enforcement ratio (1 guard per
150 citizens well-kept, per 300 slack), and the noble-household ratio
(roughly 1 per 200 population). The PDF does **not** cover individual
birth/death rates or age-at-death distributions — those are grounded in
standard pre-industrial demographic estimates instead (this is called out
explicitly rather than implied to come from the PDF).

## Scope

B is responsible for everything A explicitly deferred (names, race,
gender, exact birthdates) plus a full year of historical registry records.
B calls `town_shaper.generate.generate_town(seed, target_population)`
internally with the same seed, so the whole A→B pipeline stays
reproducible end to end from one seed. No new runtime dependency: raw
`sqlite3` (stdlib), not an ORM — appropriate given the point is to write
and practice raw SQL against the result.

New top-level package `town_db/` (parallel to `town_shaper/`, own
`tests/`), depending on `town_shaper` but structurally separate.

### A-extension (small, done as an early task in B's plan — not a re-open of A's design)

Three new CIVIC-zone building types, added to A's existing
`BUILDING_TYPES_BY_ZONE`/`JOB_VACANCIES_BY_BUILDING_TYPE` tables:

- `university` — population-gated (only eligible above ~8,000 population,
  per the PDF's Town/City size taxonomy) and even then a low-probability
  roll, not guaranteed, matching "even cities rarely have one directly."
  Occupation: `scholar`.
- `garrison` — sized off the PDF's law-enforcement ratio, distinct from
  the existing `guard_post` (town watch). Occupation: `soldier`.
- `healer` — informed by the PDF's Doctors SV row. Occupation: `healer`.
  Gives births/deaths a real "local healing area" building to report
  through, matching how the source data was originally described.

A's other constants (SES proportions, existing building weights) are
**not** revisited in this pass — see "Future Parameters" below for why
that matters for at least one of the scenarios that prompted this
discussion.

## Data Model

### Core entities

- **`districts`** — id, zone_type, polygon (JSON text; SQLite has no
  native geometry type)
- **`buildings`** — id, district_id, zone_type, building_type, x, y,
  capacity (direct mapping from A's `Building` objects)
- **`households`** — id, family_name, race (rolled once per household, so
  spouses/children match by default — see `intermarriage_rate` below)
- **`residents`** — id (SQLite autoincrement, decoupled from A's
  transient `ResidentSlot.id` — no id-collision concern when new
  residents are born mid-simulation), household_id, first_name,
  last_name, gender, race, birth_date, death_date (nullable), ses,
  is_noble (bool), home_building_id, workplace_building_id, occupation

Names are drawn from the race/gender-keyed `.txt` word lists already in
the `TownShape` repo root (left over from `population-gen.py`), not a new
name generator. Exact ages are drawn from an age-pyramid-shaped
distribution (weighted toward younger, thinning through the 60s–80s) —
not a flat uniform range, so "elderly" emerges realistically rather than
being over- or under-represented. `is_noble` is tagged on
`round(target_population / 200)` of the `RICH`-SES adults, per the PDF's
noble-household ratio — "rich" in A is a much broader wealth tier than
actual nobility, so this gives tax records something historically
distinct to key off without needing to touch A's SES model.

### Registry tables

- **`goods`** (lookup) — id, name, category, typical_price, sv. Seeded
  from a representative slice of the PDF's SV table; SV weights how often
  a purchase category occurs (bread constantly, jewelry rarely).
- **`purchases`** — id, resident_id (buyer), shop_building_id, good_id,
  quantity, unit_price, total_price, purchase_date. The good/category is
  a B-level concept attached to any open `shop`/`tavern`/`market_stall`
  building — A's buildings are **not** given per-shop specialization in
  this pass, to avoid re-touching A's design twice in the same cycle.
- **`tax_payments`** — id, resident_id, tax_type (`head_tax`, annual, per
  adult, nobility exempt per historical practice / `property_tax`,
  quarterly, per household, scaled by SES and home capacity), amount,
  period, payment_date.
- **`births`** — id, child_resident_id, mother_resident_id,
  father_resident_id (nullable), birth_date, reported_by_building_id (a
  `temple`).
- **`deaths`** — id, resident_id, death_date, cause, disease_event_id
  (nullable, FK to `disease_events`), reported_by_building_id (a `temple`
  or `healer`).
- **`disease_events`** — id, name, start_date, end_date,
  affected_zone_type (nullable — town-wide if null), severity. During an
  outbreak's date range, the death-roll's effective rate is elevated
  (weighted worse for `POOR_RESIDENTIAL`, matching real crowding/sanitation
  history), and resulting deaths get `cause='plague'`/`'illness'` with
  `disease_event_id` set.
- **`school_enrollments`** — id, resident_id, school_building_id,
  enrollment_type (`school`/`university`), start_date, end_date
  (nullable).
- **`military_service`** — id, resident_id, garrison_building_id, rank,
  start_date, end_date (nullable).

## Generation Pipeline

`generate_town_database(seed, target_population, db_path, **params) ->
None`:

1. Call `town_shaper.generate.generate_town(seed, target_population)` to
   get the `Town` (built with the university/garrison/healer extension
   already applied).
2. Create the SQLite schema (`PRAGMA foreign_keys = ON`), insert
   `districts` and `buildings` directly from `Town`.
3. **Enrich people, household by household**, grouping `Town.residents`
   by `household_id` (the only linkage A preserves): roll one primary
   race per household via `race_weights`; with probability
   `intermarriage_rate`, a spouse gets a different race instead of
   inheriting the household's — children of a mixed household inherit one
   parent's race at random (a simple 50/50 pick, not a blended/hybrid race
   concept). Roll gender, first name (from the race/gender word lists),
   and an exact birthdate per member. Tag `is_noble`.
4. **Simulate one year of events** against real ISO calendar dates
   (default start `1300-01-01` — enables using SQLite's native date
   functions, itself useful for the SQL-learning goal):
   - Weekly purchase rolls per household (good picked by SV-weighted
     probability).
   - Quarterly property tax + annual head tax (nobility exempt).
   - Birth rolls per fertile household (mother aged 16–45) at a rate
     tuned to `birth_rate`.
   - Zero or more `disease_events` rolled for the year; during an
     outbreak, death rolls use an elevated rate for affected residents.
   - Death rolls per resident on an age-appropriate mortality curve
     (elevated for infants and the elderly, further elevated during an
     active disease event), tagged with `cause` and, when applicable,
     `disease_event_id`.
   - School/university enrollment for age-appropriate residents where a
     school/university building exists.
   - `military_service` rows for garrison/guard-occupation residents.
5. Newborns become real new `residents` rows mid-simulation (inheriting
   household/home/race/SES; no job — multi-year career progression, i.e.
   a newborn eventually growing up and taking a job within the same
   simulated year, is out of scope for v1).

### Parameters (light-touch extensibility)

Per the discussion of future narrative-driven overrides (a future agent
setting parameters like "the elves are racist against the dwarves" or
"the city lost its trade route"), the following become named,
overridable parameters on B's generation functions rather than buried
module constants — with today's defaults, so nothing changes yet:

- `race_weights` — per-household race distribution
- `intermarriage_rate` — default low (~5–10%), so most households are
  single-race out of the box even without any override
- `birth_rate`, `death_rate` — the crude-rate constants driving the
  year's births/deaths (disease events apply a temporary multiplier on
  top of `death_rate`, not a separate rate system)

This is deliberately **not** a full narrative-interpretation system or a
per-race-pair compatibility matrix (e.g. "elves specifically refuse
dwarves") — just making the obvious knobs overridable. The actual
agent/parameter-setting mechanism is future work, out of scope here.

### Future Parameters (named, not built)

Documented for later, deliberately not designed in detail now:

- **War/violence** — elevated `deaths.cause='violence'` rate, garrison
  casualties.
- **Famine/harvest failure** — goods scarcity (failed purchases, price
  spikes) rather than a direct death-rate lever; this is what would
  eventually realize the "100 farmers die → food shortage → more deaths"
  cascade once sub-project D exists.
- **Migration in/out** — a real structural gap, not just a missing dial:
  B currently only changes population via birth/death, never by people
  moving to or from town. The "lost trade route" scenario arguably
  implies emigration (merchants leaving) as much as in-place poverty.
- **Governance/crime quality** — the PDF's well-kept-vs-slack law
  enforcement ratio (1-per-150 vs 1-per-300) is a real number that could
  be exposed as a parameter; a `crimes`/court-records table would be a
  natural sibling registry later.
- **Religious plurality** — the PDF notes temple density differs sharply
  under one dominant faith vs. many small ones. Currently governed by A's
  temple weighting, not a B concern.
- **Population wealth mix** (e.g. "no longer on a trade route → more
  poverty") — this one actually lives in **A**'s `SES_PROPORTIONS`, not
  B, since B only consumes the SES tag A already assigned. Flagged
  explicitly so it isn't mistaken for something B's parameters above
  cover.

## Error Handling & Edge Cases

- No eligible buildings for a registry (e.g. no school in a small town) →
  zero records of that type, not an error.
- Newborns get no job/workplace — expected, not a gap to patch in v1.
- Mortality/fertility curves must be age-shaped, not flat, or "elderly"
  and "childbearing-age" become degenerate.
- Nobility exempt from head tax; a resident can have at most one death
  record (enforced at the application level when rolling deaths — a
  resident with `death_date` already set is excluded from further
  mortality rolls).
- A `deaths` row with `cause` in (`'plague'`, `'illness'`) tied to an
  active outbreak must have `disease_event_id` set; a `disease_events` row
  with zero resulting deaths (unlucky rolls) is valid, not an error.

## Testing Strategy

- **Determinism**: same `(seed, target_population)` → identical database
  contents, table by table.
- **Referential integrity**: `PRAGMA foreign_key_check` clean; every FK
  resolves (e.g. `purchases.shop_building_id` really is a
  merchant-zone building).
- **Plausibility bounds**: total purchases/births/deaths land within a
  tolerance band of `rate × population`; nobility count ≈
  `target_population / 200`.
- **Business rules**: no head tax on children or nobles; every born
  resident's `birth_date` falls inside the simulated year; school
  enrollment ages are sane; `military_service` only for
  garrison/guard-occupation residents; every `plague`/`illness` death
  during an active `disease_events` window has `disease_event_id` set.

## Out of Scope for This Spec

- The narrative-agent/parameter-setting mechanism itself (only the
  underlying knobs are being made overridable)
- Migration, war, famine, crime/court records, religious plurality as
  built features (named above as future parameters only)
- Multi-year history, career progression/aging into jobs, sub-projects C
  and D themselves
