# Household Wealth & Income Model — Design

## Context

This addresses the highest-priority open gap in `docs/narrative-gaps.md`
(2026-08-27, "no individual wealth/income model — SES has no effect on
spending", flagged **Priority: High** by the user): `ses` (poor/rich) is
currently a binary label whose only economic consequence is a flat
`property_tax` rate (`PROPERTY_TAX_RATE_BY_SES` in `town_db/taxes.py`).
`generate_purchases` (`town_db/purchases.py`) doesn't reference `ses` at
all — frequency, quantity, and good selection are identical regardless of
wealth. Confirmed empirically: in a test town, the single highest
individual spender for the year was **poor**, out-spending every rich
resident.

This sits within capability 2's "safe-mode simulation" scope (per
`../../../../Agent_Control_Doc.md`'s "overall richness of the city"
parameter and "as realistic rules for the simulation as possible") —
economic realism as the town lives, not a narrative/creative-mode
concern. It is **not** one of the five slices already enumerated in
`2026-08-28-town-year-advance-design.md` (household formation,
event-propagation, disease overhaul, disaster, war) — those are about new
event types; this is a new, independent economic layer that both the
one-shot generator and `advance_town` share. It runs alongside, not
instead of, `ses` — everything that currently reads `ses` (home
assignment, `PROPERTY_TAX_RATE_BY_SES`) is untouched by this spec.

The second Priority: High gap ("disease is a rare, all-or-nothing yearly
event" — the same disease-overhaul slice already earmarked in capability
2) is deliberately **out of scope here**, picked up as a separate spec
after this one lands.

## Scope

New module `town_db/economy.py` (income tiers, per-resident income
computation, starting-wealth-by-SES). Changes to `town_db/schema.py`
(`households.wealth` column), `town_db/purchases.py` (wealth-tier
reweighting of purchase count/quantity/good selection),
`town_db/persistence.py` (`update_household_wealth`), `town_db/generate.py`
and `town_db/simulation.py` (the yearly income/spend/tax wealth-update
cycle, applied identically in both).

Out of scope: replacing or deriving `ses` from wealth (logged as the
rejected alternative below); per-resident (rather than per-household)
wealth tracking; debt/negative balances (wealth floors at 0 this slice);
wealth affecting anything other than `generate_purchases` (taxes stay
SES-keyed, unaffected by wealth); making income tiers or thresholds
`TownParameters`-level inputs; any interaction with `town_db/edits.py`
(creative mode).

### Rejected alternative: wealth replaces `ses`

Considered and rejected during brainstorming: making wealth the single
source of economic truth (`ses` derived from a wealth threshold, or
removed) is a cleaner long-term model, but touches
`town_shaper/assignment.py`'s `rich_proportion` parameter, `taxes.py`'s
tax tiers, and household generation — every capability built on top of
`ses` so far. Sitting alongside `ses` instead keeps this slice's blast
radius to `town_db` only.

## Data Model

### `households` table — one new column (`town_db/schema.py`)

```sql
CREATE TABLE households (
    id INTEGER PRIMARY KEY,
    family_name TEXT NOT NULL,
    race TEXT NOT NULL,
    wealth REAL NOT NULL DEFAULT 0.0   -- new
);
```

A household's running wealth balance. No live migration path needed —
`create_schema` always builds a fresh database, same as every prior
schema change in this project. No new column on `residents` — a
resident's income is derived fresh every simulated year, never stored
(see below).

## Income Computation (`town_db/economy.py`)

```python
INCOME_TIER_BY_ROLE = {"unemployed": 0.5, "apprentice": 1.0, "primary": 2.5, "noble": 5.0}  # per day
SES_INCOME_MULTIPLIER = {"rich": 1.3, "poor": 1.0}
INCOME_VARIATION_RANGE = (0.7, 1.3)

def daily_income(seed, resident_id: int, occupation: Optional[str], building_type: Optional[str],
                  ses: str, is_noble: bool) -> float:
    if is_noble:
        tier = "noble"
    elif occupation is None:
        tier = "unemployed"
    else:
        is_primary, _ = primary_occupation_info(building_type, occupation)  # reuse town_db/succession.py (T04)
        tier = "primary" if is_primary else "apprentice"
    variation = rng_for(seed, "db", "income", resident_id).uniform(*INCOME_VARIATION_RANGE)
    return INCOME_TIER_BY_ROLE[tier] * SES_INCOME_MULTIPLIER.get(ses, 1.0) * variation


def compute_household_income(seed, household_id: int, resident_rows: List[Dict], ses: str) -> float:
    """Sum of daily_income(...) * 365 for every living adult in this household with a workplace."""


def starting_wealth_by_ses(ses: str) -> float:
    """Flat SES-based seed balance for a freshly generated household — not a simulated
    backstory, just a plausible starting point for year 1's purchases to scale against."""
```

`daily_income`'s per-resident variation is **not stored** — `rng_for` is
already a pure deterministic function of `(seed, *parts)`, so the same
`resident_id` always gets the same relative variation on every call, in
every simulated year, without persisting anything extra. This matches
every other RNG use in this codebase (no global `random` state, no
stored "random trait" columns for anything derivable this way). A
resident's *absolute* income can still change year to year — a
promotion changes their `tier` — but their variation multiplier (their
relative luck/skill among peers) stays stable.

`compute_household_income` sums `daily_income(...) * 365` — a flat
365-day year, matching `YEAR_LENGTH_DAYS` and every other "a year is 365
days" assumption already established for `advance_town`. Only living
adults (`death_date IS NULL`, `age_bracket == "adult"`) with a
`workplace_building_id` contribute; non-working adults and children
contribute nothing (covered by the `"unemployed"` tier if they somehow
have an occupation with no workplace, which shouldn't occur given how
`occupation`/`workplace_building_id` are always set together elsewhere).

`INCOME_TIER_BY_ROLE`, `SES_INCOME_MULTIPLIER`, and
`starting_wealth_by_ses`'s exact figures are calibrated during
implementation against the Testing Strategy's success criterion below,
the same way `DEFAULT_BIRTH_RATE` in `vital_records.py` was empirically
tuned to hit a target crude birth rate — the values above are a starting
point, not final.

## Purchases Integration (`town_db/purchases.py`)

`generate_purchases`'s signature is **unchanged** — `household_rows`
already flows in, and now simply carries a `"wealth"` key. A household's
current wealth (post this-year's-income-added, see Yearly Update Cycle
below) maps to a small number of discrete tiers via fixed thresholds
(also calibrated during implementation, not fixed here):

- **Purchase count**: `WEEKLY_PURCHASE_COUNT_WEIGHTS` becomes
  per-wealth-tier — richer tiers shift weight toward 2–3 purchases/week,
  poorer tiers toward 0–1.
- **Quantity**: the existing `quantity = 1 if price >= 1.0 else
  rng.randint(1, 5)` logic gets a wealth-tier multiplier on the bulk-buy
  case — richer households buy more per trip.
- **Good selection**: `good_weights` gets an additional per-tier
  reweighting using the *existing* `price_by_name` data (no new goods
  schema) — poorer tiers discount goods above a price threshold, richer
  tiers boost them. Magic/weapons category gating
  (`magic_available`/`weapons_available`) is unaffected — wealth only
  reweights *within* the already-available goods set.

Taxes (`town_db/taxes.py`) are **unchanged** — still `ses`-keyed
(`PROPERTY_TAX_RATE_BY_SES`), not wealth-aware. This was a deliberate
brainstorming decision to keep this slice's scope to purchases only.

## Yearly Wealth-Update Cycle

Run identically in `generate_town_database` (its single year) and each
`advance_town` iteration, in this order:

1. **Seed or carry forward wealth.** `generate_town_database`: each
   household's `wealth` starts at `starting_wealth_by_ses(ses)`.
   `advance_town`: `wealth` is read from the `households` table (already
   loaded via `_load_household_rows`).
2. **Add this year's income first**: `household["wealth"] +=
   compute_household_income(year_seed, household["id"], resident_rows,
   household["ses"])` — added before purchases are generated, so
   purchase-tier scaling reflects wealth *including* this year's
   earnings, not last year's leftover balance alone.
3. **Generate purchases** (`generate_purchases`, wealth-tier-scaled per
   above) and **taxes** (`generate_tax_payments`, unchanged).
4. **Subtract this year's spend**: `household["wealth"] -=
   (sum of that household's purchases' total_price + sum of that
   household's tax payments' amount this year)`, then
   `household["wealth"] = max(0.0, household["wealth"])` — floored at
   zero, no debt/negative-balance modeling this slice (logged as a
   candidate follow-up, not designed here).
5. **Persist**: `persistence.update_household_wealth(conn,
   household_rows)` — new helper, `UPDATE households SET wealth = ?
   WHERE id = ?` per household, called once at the end of each
   simulated year (both call sites).

## Error Handling & Edge Cases

- A household with zero living working adults (e.g., both spouses died,
  no one else old enough) earns zero income that year — its wealth can
  only shrink (from taxes) or hold at the zero floor, never an error.
- Wealth floored at 0 means a household that "can't afford" its rolled
  purchases/taxes this year still has them recorded as having happened
  (matching how `generate_purchases`/`generate_tax_payments` already
  work — they don't check affordability per-transaction) — the floor
  only prevents the *balance* from going negative, it doesn't retroactively
  cancel transactions. This is a known simplification: a very poor
  household's recorded spending can technically exceed its income in a
  bad year. Acceptable for this slice; a stricter per-transaction budget
  check is a candidate follow-up, not designed here.
- `update_household_wealth` on a household with no purchases/taxes that
  year still runs (income added, nothing subtracted) — not a special
  case.

## Testing Strategy

Per this project's established practice, multi-mechanic economic logic
gets a seed sweep, not one seed:

- **`town_db/economy.py` unit tests**: tier assignment matches
  occupation/`is_noble`/employment status correctly; the same
  `resident_id` gets the same variation multiplier across repeated calls
  (determinism); `starting_wealth_by_ses` differs meaningfully by `ses`.
- **`town_db/purchases.py` unit tests**: wealth-tier reweighting shifts
  count/quantity/good-selection weights in the expected direction without
  changing `generate_purchases`'s existing magic/weapons availability
  gating.
- **The regression this spec exists to fix**: generate a town, advance it
  multiple years across a seed sweep, and assert rich households'
  *median* annual spend is meaningfully higher than poor households' —
  directly disproving the original empirical finding (poor out-spending
  rich).
- **Integration**: extend the existing seed-swept
  `tests/test_db_simulation_integration.py` pattern — wealth never goes
  negative across any seed/year, determinism still holds with wealth in
  the mix (same seed + years -> byte-identical `households.wealth` and
  all other tables), and all pre-existing tests (349 as of this spec)
  stay green — `ses`-driven housing/tax behavior is provably untouched.

## Out of Scope for This Spec

- Deriving/replacing `ses` from wealth (see Rejected Alternative above).
- Per-resident wealth tracking (household-pooled only).
- Debt / negative balances (floored at 0).
- Wealth affecting `town_db/taxes.py` (stays `ses`-keyed).
- `TownParameters`-level tuning of income tiers/thresholds.
- Any `town_db/edits.py` (creative-mode) interaction.
- The disease-as-everyday-life gap (separate spec, next).
