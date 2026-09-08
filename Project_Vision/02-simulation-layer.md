# Simulation & Data Layer

### Everything about the *people* on top of the spatial layout the generation layer produces: demographics, economy, history, relationships, and mapping a freeform narrative description onto generation parameters. Lives in `town_db/`, `town_relationships/`, and `town_narrative/`.

For detailed, dated gap entries (narrative-mapping shortfalls and
realism gaps found while testing against real campaign narratives) see
`docs/narrative-gaps.md` — the older, more granular log for this layer,
kept separate rather than merged in so its history stays in one place.
This file is for the higher-level current-state description and newer
feedback/proposals; check `narrative-gaps.md` too before filing a
duplicate.

## Current State

### Population generation

Built on top of the spatial layout `town_shaper` produces:

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
  households measurably out-spend poor ones over time.

### Relationships (`town_relationships/`)

Derived purely from the data above, no new randomness: spouse, parent,
sibling, household member, coworker, neighbor, unit mate (military),
classmate (school), and resident-to-shop relationships.

### Year-advance simulation (`town_db/simulation.py`)

`advance_town(db_path, seed, years)` replays an existing town forward N
more years against its *current* state: vital records, purchases,
taxes, school/military service, household formation (adult children
pairing off and moving out), and job-market succession (apprentices
promoted into vacated positions), then re-derives relationships.

### Mid-campaign editing (`town_db/edits.py`)

`kill_resident`, `mark_resident_ill`, `scope_disease_event`,
`create_disease_event`. Downstream consequences (job vacancy, purchase
reassignment, shop reputation) ripple through the database correctly.

### Narrative-language parameters (`town_narrative/`)

A `TownParameters` dataclass (population, physical size/density, wealth,
water features, magic prevalence, aggression...) that a freeform
description like "a small, wealthy port town, seaside, orderly" can be
mapped onto.

## Feedback & Future Ideas

See `docs/narrative-gaps.md` for the full, detailed backlog (each entry
dated, statused Open/Deferred/Addressed, with priority flags for the two
the user has explicitly called more urgent: the everyday-disease-as-normal-
life gap, and occupation-tiered income being a no-op for most jobs).
High-level open threads worth surfacing here:

### No population-wide cultural/religious traits

**Status:** Open — see `docs/narrative-gaps.md` 2026-08-26 entries.
No parameter currently captures a culture-wide militarization trait or
population-wide religiosity/religious-sentiment level, independent of
town size or internal unrest.

### Home/workplace assignment has no locality preference

**Status:** Open — see `docs/narrative-gaps.md` 2026-08-27 entry. A
resident can be assigned to live on the opposite side of town (or in a
farmstead, sharing it with unrelated households) from where they work,
with no proximity weighting between the two assignments.

### No multi-generational relationships

**Status:** Open — see `docs/narrative-gaps.md` 2026-08-28 entry.
`town_relationships/family.py` derives only single-generation/same-
household links (spouse, parent, sibling, household member) — no
grandparent, aunt/uncle, cousin, or in-law relationships, even though
the underlying birth/household records would support deriving them.

### Town's physical footprint is fixed after generation

**Status:** Deferred — explicitly set aside during the year-advance
(capability 2) design discussion. As `advance_town` simulates years
forward, population can grow or shrink, but no mechanism adds or
removes buildings/districts; a soft cap (household formation slows when
housing is full) stands in for this today. A future slice may need the
town to physically grow or contract for long-run simulation to stay
realistic — this pulls `town_shaper`'s building-placement logic into a
simulation context it wasn't designed for.
