# Town Relationships — Relationship Graph Design

## Context

This is the third of four sub-projects toward a tool that generates a
realistic medieval town, populates a relational database with plausible
records for it, builds a relationship graph between residents, and
eventually lets an agent simulate a day in the town's life. See
`docs/superpowers/specs/2026-08-13-town-shaper-spatial-generation-design.md`
for the full four-sub-project context.

- **A. Town Shaper** (done, merged) — spatial layout and population
  placement.
- **B. Town DB** (done, merged) — a SQLite database of enriched residents
  plus a year of historical registry records (purchases, taxes, vital
  records, disease, school/university enrollment, military service),
  built on A's output.
- **C. Relationship graph (this spec)** — derives resident-to-resident
  and resident-to-shop relationships entirely from what A and B already
  wrote to the database. No new population/event generation, no random
  draws anywhere in this package.
- **D. Agent-driven daily simulation** — cascading daily events, built on
  A + B + C.

This spec covers **C only**.

### Unrelated same-session change (background, not part of C)

While grounding C's need-model, `town_shaper/assignment.py`'s
`SES_PROPORTIONS` was independently retuned from `{RICH: 0.2, POOR: 0.8}`
to `{RICH: 0.05, POOR: 0.95}` (commit `62542d6`) — a more historically
plausible split. This is an A-scoped change with no logic dependency from
C; it's noted here only because C's household-need model (below) reads
whatever real `ses` distribution ends up in the database.

## Scope

C is a **pure derivation layer**: every relationship it produces is
computed from rows A/B already wrote (`households`, `residents`,
`buildings`, `births`, `purchases`, `military_service`,
`school_enrollments`) — never from a new random draw. Because of this,
nothing in C takes a `seed`; the same input database always produces the
same output relationships, deterministically, by construction.

New top-level package `town_relationships/` (parallel to `town_shaper/`
and `town_db/`, own `tests/`), depending on `town_db`'s schema but
structurally separate. Entry point:

```
town_relationships.generate.derive_relationships(db_path: str) -> None
```

Reads the existing tables in a town's SQLite file and writes new
relationship rows back into the *same* file. Safe to call at most once
per database (see Error Handling below for re-run behavior).

## Data Model

Two new tables — kept separate because they connect different entity
pairs (resident↔resident vs. resident↔building).

### `relationships` (resident ↔ resident)

```sql
CREATE TABLE relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_a_id INTEGER NOT NULL REFERENCES residents(id),
    resident_b_id INTEGER NOT NULL REFERENCES residents(id),
    relationship_type TEXT NOT NULL,
    detail TEXT
);
```

`relationship_type` is one of `spouse`, `parent`, `sibling`,
`household_member`, `coworker`, `neighbor`, `unit_mate`, `classmate`.

- All types except `parent` are **symmetric**: one row per unordered
  pair, stored canonically with `resident_a_id < resident_b_id`.
  Queries match either column.
- `parent` is the one **asymmetric** type: `resident_a_id` is the
  parent, `resident_b_id` the child. There is no separate `child` type —
  "who are X's parents" queries `resident_b_id = X`, "who are X's
  children" queries `resident_a_id = X`.
- `detail` is nullable free-form JSON text for type-specific context
  (e.g. `neighbor` stores the connecting building pair's distance,
  `unit_mate`/`classmate` store the overlapping date range).

### `shop_relationships` (resident ↔ building)

```sql
CREATE TABLE shop_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    shop_building_id INTEGER NOT NULL REFERENCES buildings(id),
    purchase_count INTEGER NOT NULL,
    total_spent REAL NOT NULL,
    distance REAL NOT NULL,
    need_score REAL NOT NULL,
    customer_score REAL NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0
);
```

One row per `(resident, shop)` pair with **at least one** matching row
in `purchases` — a customer tie is never invented without a real
transaction behind it. `is_primary = 1` marks the single
highest-`customer_score` shop for that resident (their "regular" shop);
every other row for that resident has `is_primary = 0`.

## Derivation Rules

Shared helper: `town_relationships/geometry.py` — `distance(building_a,
building_b) -> float`, plain Euclidean distance on `x`/`y`, used by both
`neighbors.py` and `shops.py`.

### `family.py` → `spouse`, `parent`, `sibling`, `household_member`

Per household, bracket every member as adult/child using
`age_on(birth_date, reference_date) >= 18`, reusing B's own
`ADULT_AGE_RANGE` threshold (the `reference_date` used is the same one
the town database was generated with, i.e. `households` +
`residents.birth_date` are already consistent with it).

- The **first two adults**, ordered by `residents.id` (which preserves
  B's own household-generation order — see `households.py`'s
  `adults[1]` spouse pairing) → `spouse`.
- Each of those two → each **child** (age-bracketed) in the household →
  `parent`.
- All children of the same household → pairwise `sibling`.
- Any **additional adults** beyond the first two (ambiguous households —
  could be an adult child, an elderly parent, or an unrelated roommate;
  nothing in the data disambiguates this) get `household_member` to
  every other resident in the household instead of an asserted role.
  Likewise, a household with 0 or 1 adult (no spouse pair possible)
  produces no `spouse` row, and its members fall back to
  `household_member` for any tie the adult/child rules above don't
  otherwise cover.
- **Exact data overrides the heuristic**: for the (small) subset of
  residents with a real `births` row — i.e. children born during B's
  simulated year — `parent` is derived directly from that row's
  `mother_resident_id`/`father_resident_id` instead of the household
  heuristic above.

### `work.py` → `coworker`

Residents sharing a non-null `workplace_building_id` → `coworker`.

### `neighbors.py` → `neighbor`

Build a building-adjacency graph over all buildings with at least one
resident in `home_building_id`: for each such building, find its
**K = 4** nearest other occupied buildings by `distance()`. Union the
edges — building A and B are connected if B is in A's nearest-4 **or**
A is in B's nearest-4 (plain nearest-K is not symmetric on its own).
Every resident pair across two connected buildings → `neighbor`, with
`detail` recording the connecting buildings' distance.

Residents with `home_building_id IS NULL` (the capacity-overflow edge
case A can produce — see A's spec) are skipped entirely; they get no
`neighbor` rows.

### `military.py` → `unit_mate`

Residents with rows in `military_service` sharing the same
`garrison_building_id` whose `[start_date, end_date)` ranges overlap
(a null `end_date` means "still serving," treated as open-ended) →
`unit_mate`, with `detail` recording the overlap window.

### `school.py` → `classmate`

Same overlap logic over `school_enrollments`, keyed on
`school_building_id` → `classmate`.

### `shops.py` → `shop_relationships`

**Household-need model** — new for C, since nothing upstream models
"need." Constants (open to tuning, same spirit as B's empirically-set
constants):

```
STAPLE_CATEGORIES = {"food", "drink", "household", "clothing"}
LUXURY_CATEGORIES = {"luxury"}
TOOLS_CATEGORIES  = {"tools"}
POOR_LUXURY_MULTIPLIER = 0.1
```

```
household_size(household_id)   = COUNT(residents WHERE household_id = X)
working_adults(household_id)   = COUNT(residents WHERE household_id = X
                                        AND occupation IS NOT NULL)

need_weight(household_id, category):
    if category in STAPLE_CATEGORIES: household_size(household_id)
    if category in LUXURY_CATEGORIES:
        household_size(household_id) if household's ses == 'rich'
        else household_size(household_id) * POOR_LUXURY_MULTIPLIER
    if category in TOOLS_CATEGORIES: working_adults(household_id)
```

A household's `ses` for this purpose is read directly off its members'
`residents.ses` (household members share one SES tier by construction —
see B's `households.py`). `household_size`/`working_adults` count all
residents ever recorded under that `household_id`, living or dead — a
structural property of the household, not a point-in-time snapshot.

**Scoring**, aggregating real `purchases` rows joined to `goods` for
category:

```
customer_score(resident, shop) =
    Σ over purchases by resident at shop: total_price × need_weight(resident's household, good.category)
    ÷ (1 + distance(resident's home_building, shop))
```

For each resident with any purchases, the shop with the highest
`customer_score` gets `is_primary = 1` (ties broken by lowest
`shop_building_id`, for determinism). Residents with
`home_building_id IS NULL` are skipped (no distance is computable).

## Error Handling & Edge Cases

- `derive_relationships` assumes it runs once against a freshly-built
  database from B — it does not check for or clean up pre-existing rows
  in `relationships`/`shop_relationships`. Calling it twice against the
  same database produces duplicate rows; this is a documented
  precondition, not guarded against defensively.
- A household with 0 or 1 adult, or 0 children, simply produces fewer
  relationship rows (no `spouse` without 2 adults, no `parent`/`sibling`
  without children) — not an error.
- A resident with no purchases anywhere produces zero
  `shop_relationships` rows — not an error, and no `is_primary` row
  either (there is nothing to be primary among).
- Deceased residents (`death_date IS NOT NULL`) are **not** excluded
  from any relationship — these are historical facts (D's simulation
  cares that a resident *had* a spouse/coworkers even after one of them
  dies). Consumers filter by `death_date` themselves if they only want
  currently-living ties.

## Testing Strategy

- **Determinism**: running `derive_relationships` twice against two
  copies of the same input database produces byte-identical relationship
  rows (order-independent comparison, since no seed/randomness is
  involved by construction).
- **Referential integrity**: `PRAGMA foreign_key_check` clean; every
  `resident_a_id`/`resident_b_id`/`resident_id`/`shop_building_id`
  resolves to a real row.
- **Business rules per type**: `spouse` only ever pairs the first two
  adults of a household; `parent` only links an adult to a child in the
  same household unless sourced from an exact `births` row; `sibling`
  only pairs children of the same household; `coworker` only pairs
  residents sharing a non-null `workplace_building_id`; `neighbor` only
  exists across buildings connected by the K=4 union graph; `unit_mate`/
  `classmate` require an actual date overlap, not just a shared
  building; every `shop_relationships` row has `purchase_count >= 1`;
  exactly one `is_primary = 1` row per resident who has any purchases,
  zero for residents with none.
- **Edge cases**: single-resident household, household with 3+ adults,
  resident with `home_building_id IS NULL`, resident with zero
  purchases, two military members whose service dates don't overlap
  (must NOT produce `unit_mate`).

## Out of Scope for This Spec

- Any relationship with no mechanical basis in A/B's existing data
  (friendships, rivalries, non-married romantic partners) — deliberately
  excluded per this design's "strictly derived" scope decision.
- Sub-project D (the simulation) itself, and any notion of relationships
  changing over time (this is a one-time derivation over a finished
  database, not a time-varying graph).
- Shop specialization by good category (today's `purchases` assigns
  shops uniformly at random, independent of what's bought — a real gap
  in B, not something C fixes; C's need-model only shapes the *score* of
  an existing purchase, it cannot make B's shop assignment itself more
  realistic).
