# Village Economy & Growth — Design

## Context

The 2026-09-08/09 settlemaker migration (see `2026-09-08-settlemaker-
integration-design.md` and `-phase2.md`) gave `target_population <= 1000`
towns a real settlement for the first time — settlemaker's own "village"
engine, parsed by `settlemaker_bridge.parse_geojson._parse_village_geojson`
into a single synthesized `POOR_RESIDENTIAL` district of `residence`
buildings.

That fixed the immediate bug (villages used to silently generate empty),
but confirmed two structural gaps, tracked as open items in
`Project_Vision/01-generation-layer.md`:

1. **No economy, ever.** The village engine's own type definitions
   (`village/types.d.ts`'s `PoiKind` union: `well | stone-circle |
   boathouse`) prove it can never emit a shop, tavern, or any other
   job-bearing building. Every village-scale town therefore has zero
   purchases and zero wealth change, regardless of years simulated.
2. **No growth.** Settlemaker sizes total village housing capacity to
   almost exactly match `target_population` (measured: 802 capacity for
   802 residents, zero vacant buildings, at population 800). No slack
   means `town_db.household_formation._vacant_home_building()` can never
   find anywhere for a newly-formed household to move into.

**Decision (this session, 2026-09-09):** villages should get the same
simulation depth as towns — real jobs, real purchases, real growth —
not stay a lighter-weight, population-only backdrop. This document
designs that.

## Scope

**In scope:**
- Reclassifying a small, population-scaled subset of a village's houses
  into job-bearing business buildings, using TownShape's own existing
  building-type/job-vacancy/naming machinery — no new vocabulary.
- Reserving a small, population-scaled subset of houses as genuinely
  empty at initial generation, so household formation has somewhere to
  go.

**Out of scope:**
- Anything about *burg*-mode (population >= 1000) towns — they already
  have real vacancy slack (measured: 10 vacant buildings at population
  1500) and a full commercial mix; this document doesn't touch that
  path.
- Visual/SVG changes. Settlemaker's own persisted SVG for a village
  still shows every building as a plain house — reclassifying a house
  into a tavern is a TownShape-side data change only, invisible in the
  static map. (`town_viewer`'s interactive canvas, which reads
  `buildings.building_type` from the database directly, *would* show
  the distinction correctly — no viewer change needed, it already reads
  the right column.) Making settlemaker's SVG reflect this is not
  attempted here.
- Any change to which populations route to which settlemaker engine.
  `VILLAGE_POP_CEILING` (1000) stays settlemaker's own, unmodified
  threshold.
- Rebalancing `JOB_VACANCIES_BY_BUILDING_TYPE`, `BUILDING_NAME_POOLS`,
  or `BUILDING_HOME_CAPACITY` — this design only *reuses* those tables
  for `tavern` and `shop`, unchanged.

## Data Model

One new field, `town_shaper/models.py`:

```python
@dataclass
class Building:
    ...
    reserved_vacant: bool = False
```

Defaults `False` for every existing caller (burg-mode parsing, all
tests) — purely additive, no migration needed. Meaning: *this building
must not be filled during initial resident assignment, even though its
capacity is nonzero.* Not persisted to the database — once initial
assignment has run, a reserved building is indistinguishable from any
other building with spare capacity, which is exactly the desired end
state (`household_formation.py`'s `_vacant_home_building()` already
finds any building where `capacity > count(residents)`, no matter why
it's empty).

No other model changes. Reclassified business buildings use the
existing `building_type`, `capacity`, `vacancies`, and `name` fields —
just populated with `tavern`/`shop` values instead of `residence`.

## Architecture

### New: `_curate_village_economy`

`settlemaker_bridge/parse_geojson.py`, called from
`_parse_village_geojson` once its house list is built, before returning:

```python
VILLAGE_BUSINESS_MIN_POPULATION = 75   # below this, a village is houses only
VILLAGE_SHOP_MIN_POPULATION = 300      # below this, at most a tavern
VILLAGE_RESERVED_VACANCY_DIVISOR = 100 # ~1 reserved house per this many residents


def _curate_village_economy(buildings: List[Building], population: int, seed: Any) -> None:
    """Mutates a subset of `buildings` in place: reclassifies a few houses
    into businesses, reserves a few more as initially-vacant. No-op below
    VILLAGE_BUSINESS_MIN_POPULATION -- a small enough village is just
    houses, no businesses and no reserved slack either (nothing to grow
    into yet at that scale)."""
    if population < VILLAGE_BUSINESS_MIN_POPULATION or not buildings:
        return

    business_types = ["tavern"] if population < VILLAGE_SHOP_MIN_POPULATION else ["tavern", "shop"]
    reserved_count = max(1, population // VILLAGE_RESERVED_VACANCY_DIVISOR)

    rng = rng_for(seed, "village_economy")
    pool = sorted(buildings, key=lambda b: b.id)
    rng.shuffle(pool)

    for building, new_type in zip(pool, business_types):
        building.building_type = new_type
        building.capacity = BUILDING_HOME_CAPACITY.get(new_type, 0)
        building.vacancies = [
            JobVacancy(building_id=building.id, occupation=occupation)
            for occupation, count in JOB_VACANCIES_BY_BUILDING_TYPE[new_type]
            for _ in range(count)
        ]
        building.name = _building_name(seed, new_type, building.id)

    for building in pool[len(business_types):len(business_types) + reserved_count]:
        building.reserved_vacant = True
```

Deterministic (`rng_for(seed, "village_economy")`, sorted-then-shuffled
pool — same pattern `_build_vacancy_pool` in `town_shaper/assignment.py`
already uses), and bounded by construction at both ends of the range
this activates over: at the smallest population it does anything (75),
a village already has ~19 houses (interpolating the measured
125-buildings-at-population-500 ratio, which holds steady at ~1 building
per 4 residents from population 300 to 1000), so removing 1 tavern + 1
reserved house is well within room. At the largest (999), that same
ratio gives ~250 houses, against 2 businesses + 9 reserved — still a
small fraction. Nowhere in between does `len(business_types) +
reserved_count` come close to the house count.

### Changed: `assign_residents`

`town_shaper/assignment.py`, one-line filter change:

```python
residential_buildings = sorted(
    (b for d in districts for b in d.buildings if b.capacity > 0 and not b.reserved_vacant),
    key=lambda b: b.id,
)
```

This is the entire mechanism that makes reservation work: a reserved
building stays in `district.buildings` (so it's persisted to the
database normally, with its real capacity and zero residents), but
`assign_residents` simply never offers it to a household during initial
placement. No temporary list surgery, no restore step, no new
parameter — `reserved_vacant` defaults `False` everywhere else, so
burg-mode towns are completely unaffected.

### Everything downstream is unchanged

Job market (`town_db/job_market.py`), purchases
(`town_db/purchases.py`), succession (`town_db/succession.py`), and
`household_formation.py` all key off `building_type` and DB-queried
capacity/occupancy — none of them know or care whether a `tavern` came
from settlemaker's burg engine or from this reclassification step. That
was the point of reusing the existing tables rather than inventing a
parallel "village business" concept.

## Determinism & Testing

- Unit tests (new, `tests/test_settlemaker_parse_geojson.py`, hand-built
  village fixtures — same convention as this session's other village
  tests): population below 75 reclassifies nothing; 75-299 reclassifies
  exactly one house to `tavern`; >=300 reclassifies exactly one `tavern`
  and one `shop`; reclassified buildings get 0 capacity and the right
  vacancy list; reserved-building count matches the population/100
  formula (rounded down, floor 1); the same seed produces the same
  chosen buildings across two calls.
- `assign_residents` unit test (new, `tests/test_assignment.py`): a
  district containing one `reserved_vacant=True` building with spare
  capacity never receives a resident, even when other buildings are
  full.
- Integration test (new, `tests/test_db_simulation_integration.py` or
  alongside it): generate a population-500 town (lands in the village
  engine, above both the business and reserved-vacancy floors),
  `advance_town` it 3+ years, and assert both `purchases` and a new
  household actually appear — the two behaviors this document exists to
  fix. This directly supersedes the population bump this session already
  applied to `test_rich_households_out_spend_poor_households_over_time`
  and its neighbors as a workaround; those tests can move back down into
  village-range populations once this lands, if desired (not required —
  out of scope to revisit here, noted for whoever picks that up).

## Risks / Open Questions

- **The population-scaling constants (75, 300, ÷100) are a reasoned
  starting point, not measured against player feedback.** Easy to
  retune later — they're three named constants in one place, nothing
  else depends on their exact values. Flagging so they aren't mistaken
  for a carefully calibrated result the way e.g. `BUILDING_DENSITY_PER_AREA`
  was calibrated against real measured runs elsewhere in this codebase.
- **Static-map/data mismatch is permanent, not a bug to fix later.**
  Called out in Scope above, repeating here because it's the one
  visible surprise a user could hit: opening the persisted `.svg` for a
  village with a tavern will show an ordinary house at that location.
  The interactive viewer shows it correctly today with no changes
  needed.
- **A village's very smallest tier (<75) still can't grow or trade.**
  By design, per this session's own steer ("a small floor... too tiny
  to support even a tavern") — not a gap this document leaves
  accidentally open.
