# Household Wealth & Income Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every household a running wealth balance, driven by occupation/SES-tiered income, that actually shapes purchase behavior (frequency, quantity, and good selection) — fixing the empirical gap where a poor resident out-spent every rich resident in a test town.

**Architecture:** A new `town_db/economy.py` module computes per-resident daily income (occupation tier + SES + a deterministic per-resident variation, reusing `town_db/succession.py`'s `primary_occupation_info`) and owns the yearly wealth-update cycle (add income, subtract that year's purchases+taxes, floor at 0). `town_db/purchases.py`'s `generate_purchases` reweights its existing count/quantity/good-selection logic by each household's current wealth tier — its signature is unchanged, `household_rows` just carries a new `"wealth"` key. `town_db/generate.py` (one-shot) and `town_db/simulation.py` (`advance_town`, year-over-year) both run the identical income → purchases/taxes → spend-subtraction cycle, so wealth-scaled behavior is consistent in year 1 and every year after.

**Tech Stack:** Python stdlib `sqlite3`, `town_shaper.seeding.rng_for` (deterministic per-call RNG derivation), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-31-household-wealth-model-design.md`

## Global Constraints

- Every new/changed RNG draw goes through `town_shaper.seeding.rng_for(seed, *parts)` — never bare `random` module state (matches every existing `town_db` generator).
- `households.wealth` is household-pooled, never per-resident. `ses` (on `residents`, not `households`) is untouched by this plan — everything that reads it today keeps working exactly as before.
- Wealth is floored at 0 — no debt/negative-balance modeling this slice.
- `generate_purchases`'s public signature does not change. `generate_tax_payments` is not touched at all — taxes stay SES-keyed, unaffected by wealth.
- A "year" is exactly 365 days everywhere (`town_db.generate.YEAR_LENGTH_DAYS`), matching every existing "a year is 365 days" assumption in this codebase.
- The income tier constants, wealth-tier thresholds, and purchase-reweighting multipliers below are starting points, not final — Task 8's regression test is the actual acceptance bar. If it doesn't show real separation between rich and poor households, tune the constants in `town_db/economy.py`/`town_db/purchases.py` rather than weakening the assertion (same practice as `DEFAULT_BIRTH_RATE`'s calibration in `town_db/vital_records.py` and the household-formation test seed fix in this project's `LOG.md`, 2026-08-31).
- Every task that touches an existing module must leave that module's existing tests passing unchanged — these are explicit regression-guard steps, not assumptions.

---

## Task 1: `households.wealth` schema column

**Files:**
- Modify: `town_db/schema.py`
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Produces: `households` table gains column `wealth REAL NOT NULL DEFAULT 0.0`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db_schema.py`:

```python
def test_households_wealth_defaults_to_zero(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.commit()
    row = conn.execute("SELECT wealth FROM households WHERE id = 1").fetchone()
    assert row == (0.0,)


def test_households_wealth_accepts_an_explicit_value(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute(
        "INSERT INTO households (id, family_name, race, wealth) VALUES (1, 'Smith', 'human', 250.5)"
    )
    conn.commit()
    row = conn.execute("SELECT wealth FROM households WHERE id = 1").fetchone()
    assert row == (250.5,)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: FAIL — `sqlite3.OperationalError: no such column: wealth`

- [ ] **Step 3: Add the column**

In `town_db/schema.py`, change the `households` table definition in `SCHEMA_SQL`:

```sql
CREATE TABLE households (
    id INTEGER PRIMARY KEY,
    family_name TEXT NOT NULL,
    race TEXT NOT NULL,
    wealth REAL NOT NULL DEFAULT 0.0
);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: PASS (all tests, including the two new ones — the existing `INSERT INTO households (id, family_name, race) VALUES (...)` statements used throughout the test suite keep working unchanged since `wealth` has a default and isn't in their column list).

- [ ] **Step 5: Commit**

```bash
git add town_db/schema.py tests/test_db_schema.py
git commit -m "feat: add households.wealth column"
```

---

## Task 2: `town_db/economy.py` — income primitives

**Files:**
- Create: `town_db/economy.py`
- Test: `tests/test_db_economy.py`

**Interfaces:**
- Consumes: `town_db.succession.primary_occupation_info` (Task 4's original extraction, already on `main`), `town_shaper.seeding.rng_for`.
- Produces (for Task 3 and Task 6/7 to reuse): `daily_income(seed, resident_id, occupation, building_type, ses, is_noble) -> float`, `compute_household_income(seed, household_resident_rows, building_type_by_id) -> float`, `household_ses(household_resident_rows) -> str`, `starting_wealth_by_ses(ses) -> float`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_db_economy.py`:

```python
from town_db.economy import (
    compute_household_income,
    daily_income,
    household_ses,
    starting_wealth_by_ses,
)


def test_daily_income_is_deterministic_for_the_same_resident():
    a = daily_income(("town", 1), resident_id=42, occupation="shopkeep", building_type="shop",
                      ses="poor", is_noble=False)
    b = daily_income(("town", 1), resident_id=42, occupation="shopkeep", building_type="shop",
                      ses="poor", is_noble=False)
    assert a == b


def test_daily_income_varies_between_different_residents_in_the_same_role():
    incomes = {
        daily_income(("town", 1), resident_id=rid, occupation="shopkeep", building_type="shop",
                      ses="poor", is_noble=False)
        for rid in range(1, 21)
    }
    assert len(incomes) > 1, "expected variation between residents in the identical role"


def test_daily_income_unemployed_is_lower_than_apprentice_is_lower_than_primary():
    unemployed = daily_income(("town", 1), 1, occupation=None, building_type=None, ses="poor", is_noble=False)
    apprentice = daily_income(("town", 1), 1, occupation="shop_staff", building_type="shop", ses="poor", is_noble=False)
    primary = daily_income(("town", 1), 1, occupation="shopkeep", building_type="shop", ses="poor", is_noble=False)
    assert unemployed < apprentice < primary


def test_daily_income_noble_outearns_everyone_regardless_of_occupation():
    noble = daily_income(("town", 1), 1, occupation=None, building_type=None, ses="poor", is_noble=True)
    primary_non_noble = daily_income(("town", 1), 1, occupation="shopkeep", building_type="shop",
                                      ses="rich", is_noble=False)
    assert noble > primary_non_noble


def test_daily_income_rich_ses_outearns_poor_ses_in_the_same_role():
    # Average over many resident_ids to cancel out the per-resident variation multiplier.
    def avg(ses):
        return sum(
            daily_income(("town", 1), rid, occupation="shopkeep", building_type="shop", ses=ses, is_noble=False)
            for rid in range(1, 101)
        ) / 100
    assert avg("rich") > avg("poor")


def test_compute_household_income_sums_only_living_adults_with_a_workplace():
    residents = [
        {"db_id": 1, "age_bracket": "adult", "death_date": None, "occupation": "shopkeep",
         "workplace_building_id": 10, "ses": "poor", "is_noble": False},
        {"db_id": 2, "age_bracket": "adult", "death_date": "1300-06-01", "occupation": "shopkeep",
         "workplace_building_id": 10, "ses": "poor", "is_noble": False},  # dead -- excluded
        {"db_id": 3, "age_bracket": "child", "death_date": None, "occupation": None,
         "workplace_building_id": None, "ses": "poor", "is_noble": False},  # child -- excluded
        {"db_id": 4, "age_bracket": "adult", "death_date": None, "occupation": None,
         "workplace_building_id": None, "ses": "poor", "is_noble": False},  # unemployed -- still contributes
    ]
    building_type_by_id = {10: "shop"}
    income = compute_household_income(("town", 1), residents, building_type_by_id)
    expected = (
        daily_income(("town", 1), 1, "shopkeep", "shop", "poor", False)
        + daily_income(("town", 1), 4, None, None, "poor", False)
    ) * 365
    assert income == expected


def test_household_ses_is_the_modal_ses_among_members():
    residents = [{"ses": "rich"}, {"ses": "rich"}, {"ses": "poor"}]
    assert household_ses(residents) == "rich"


def test_household_ses_ties_break_toward_poor():
    residents = [{"ses": "rich"}, {"ses": "poor"}]
    assert household_ses(residents) == "poor"


def test_household_ses_defaults_to_poor_when_empty():
    assert household_ses([]) == "poor"


def test_starting_wealth_by_ses_rich_exceeds_poor():
    assert starting_wealth_by_ses("rich") > starting_wealth_by_ses("poor")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_economy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'town_db.economy'`

- [ ] **Step 3: Create `town_db/economy.py`**

```python
# town_db/economy.py
from typing import Any, Dict, List, Optional, Tuple

from town_shaper.seeding import rng_for

from town_db.succession import primary_occupation_info

YEAR_LENGTH_DAYS = 365

INCOME_TIER_BY_ROLE = {"unemployed": 0.5, "apprentice": 1.0, "primary": 2.5, "noble": 5.0}
SES_INCOME_MULTIPLIER = {"rich": 1.3, "poor": 1.0}
INCOME_VARIATION_RANGE: Tuple[float, float] = (0.7, 1.3)
STARTING_WEALTH_BY_SES = {"rich": 500.0, "poor": 50.0}


def daily_income(
    seed,
    resident_id: int,
    occupation: Optional[str],
    building_type: Optional[str],
    ses: str,
    is_noble: bool,
) -> float:
    if is_noble:
        tier = "noble"
    elif occupation is None:
        tier = "unemployed"
    else:
        is_primary, _ = primary_occupation_info(building_type, occupation)
        tier = "primary" if is_primary else "apprentice"
    variation = rng_for(seed, "db", "income", resident_id).uniform(*INCOME_VARIATION_RANGE)
    return INCOME_TIER_BY_ROLE[tier] * SES_INCOME_MULTIPLIER.get(ses, 1.0) * variation


def compute_household_income(
    seed,
    household_resident_rows: List[Dict[str, Any]],
    building_type_by_id: Dict[int, str],
) -> float:
    total = 0.0
    for row in household_resident_rows:
        if row.get("death_date") is not None or row.get("age_bracket") != "adult":
            continue
        workplace_id = row.get("workplace_building_id")
        building_type = building_type_by_id.get(workplace_id) if workplace_id is not None else None
        total += daily_income(
            seed, row["db_id"], row.get("occupation"), building_type, row["ses"], bool(row.get("is_noble")),
        )
    return total * YEAR_LENGTH_DAYS


def household_ses(household_resident_rows: List[Dict[str, Any]]) -> str:
    counts: Dict[str, int] = {}
    for row in household_resident_rows:
        counts[row["ses"]] = counts.get(row["ses"], 0) + 1
    if not counts:
        return "poor"
    # Highest count wins; ties (including the empty-vs-nonzero non-issue above) break toward
    # "poor" -- the safer default -- via sort key (False < True, so "poor" sorts first on a tie).
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0] != "poor"))[0][0]


def starting_wealth_by_ses(ses: str) -> float:
    return STARTING_WEALTH_BY_SES.get(ses, STARTING_WEALTH_BY_SES["poor"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_economy.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_db/economy.py tests/test_db_economy.py
git commit -m "feat: add town_db/economy.py income primitives"
```

---

## Task 3: `town_db/economy.py` — yearly wealth-cycle helpers

**Files:**
- Modify: `town_db/economy.py`
- Test: `tests/test_db_economy.py` (extend)

**Interfaces:**
- Consumes: Task 2's `compute_household_income`, `household_ses`, `starting_wealth_by_ses`.
- Produces (for Task 6/7 to reuse): `seed_starting_wealth(household_rows, resident_rows) -> None`, `add_yearly_income(seed, household_rows, resident_rows, building_type_by_id) -> None`, `subtract_yearly_spend(household_rows, resident_rows, purchases, tax_payments) -> None` (all mutate `household_rows` dicts in place, setting/updating each one's `"wealth"` key), `wealth_tier(wealth: float) -> str` (for Task 5 to reuse).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db_economy.py`:

```python
from town_db.economy import (
    add_yearly_income,
    seed_starting_wealth,
    subtract_yearly_spend,
    wealth_tier,
)


def test_seed_starting_wealth_sets_wealth_by_household_ses():
    households = [{"id": 1}, {"id": 2}]
    residents = [
        {"household_id": 1, "ses": "rich"},
        {"household_id": 2, "ses": "poor"},
    ]
    seed_starting_wealth(households, residents)
    assert households[0]["wealth"] == starting_wealth_by_ses("rich")
    assert households[1]["wealth"] == starting_wealth_by_ses("poor")


def test_add_yearly_income_increases_wealth_by_computed_income():
    households = [{"id": 1, "wealth": 100.0}]
    residents = [{
        "db_id": 1, "household_id": 1, "age_bracket": "adult", "death_date": None,
        "occupation": "shopkeep", "workplace_building_id": 10, "ses": "poor", "is_noble": False,
    }]
    building_type_by_id = {10: "shop"}
    add_yearly_income(("town", 1), households, residents, building_type_by_id)
    expected_income = compute_household_income(("town", 1), residents, building_type_by_id)
    assert households[0]["wealth"] == 100.0 + expected_income


def test_add_yearly_income_defaults_missing_wealth_to_zero():
    households = [{"id": 1}]  # no "wealth" key yet
    residents = [{
        "db_id": 1, "household_id": 1, "age_bracket": "adult", "death_date": None,
        "occupation": None, "workplace_building_id": None, "ses": "poor", "is_noble": False,
    }]
    add_yearly_income(("town", 1), households, residents, {})
    assert households[0]["wealth"] >= 0.0


def test_subtract_yearly_spend_reduces_wealth_by_purchases_and_taxes():
    households = [{"id": 1, "wealth": 100.0}]
    residents = [{"db_id": 1, "household_id": 1}]
    purchases = [{"resident_db_id": 1, "total_price": 20.0}, {"resident_db_id": 1, "total_price": 5.0}]
    tax_payments = [{"resident_db_id": 1, "amount": 10.0}]
    subtract_yearly_spend(households, residents, purchases, tax_payments)
    assert households[0]["wealth"] == 100.0 - 20.0 - 5.0 - 10.0


def test_subtract_yearly_spend_floors_at_zero():
    households = [{"id": 1, "wealth": 10.0}]
    residents = [{"db_id": 1, "household_id": 1}]
    purchases = [{"resident_db_id": 1, "total_price": 500.0}]
    subtract_yearly_spend(households, residents, purchases, [])
    assert households[0]["wealth"] == 0.0


def test_wealth_tier_orders_poor_below_comfortable_below_wealthy():
    tiers = [wealth_tier(0.0), wealth_tier(500.0), wealth_tier(5000.0)]
    assert tiers == ["poor", "comfortable", "wealthy"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_economy.py -v`
Expected: FAIL — `ImportError: cannot import name 'add_yearly_income' from 'town_db.economy'` (and similar for the other three new names)

- [ ] **Step 3: Add the yearly-cycle helpers**

Append to `town_db/economy.py`:

```python
WEALTH_TIER_THRESHOLDS = [(100.0, "poor"), (1000.0, "comfortable")]
WEALTH_TIER_DEFAULT = "wealthy"


def wealth_tier(wealth: float) -> str:
    for threshold, tier in WEALTH_TIER_THRESHOLDS:
        if wealth < threshold:
            return tier
    return WEALTH_TIER_DEFAULT


def _residents_by_household(resident_rows: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for row in resident_rows:
        grouped.setdefault(row["household_id"], []).append(row)
    return grouped


def seed_starting_wealth(household_rows: List[Dict[str, Any]], resident_rows: List[Dict[str, Any]]) -> None:
    grouped = _residents_by_household(resident_rows)
    for household in household_rows:
        ses = household_ses(grouped.get(household["id"], []))
        household["wealth"] = starting_wealth_by_ses(ses)


def add_yearly_income(
    seed,
    household_rows: List[Dict[str, Any]],
    resident_rows: List[Dict[str, Any]],
    building_type_by_id: Dict[int, str],
) -> None:
    grouped = _residents_by_household(resident_rows)
    for household in household_rows:
        income = compute_household_income(seed, grouped.get(household["id"], []), building_type_by_id)
        household["wealth"] = household.get("wealth", 0.0) + income


def subtract_yearly_spend(
    household_rows: List[Dict[str, Any]],
    resident_rows: List[Dict[str, Any]],
    purchases: List[Dict[str, Any]],
    tax_payments: List[Dict[str, Any]],
) -> None:
    household_id_by_resident = {row["db_id"]: row["household_id"] for row in resident_rows}
    spend_by_household: Dict[int, float] = {}
    for p in purchases:
        hh_id = household_id_by_resident.get(p["resident_db_id"])
        if hh_id is not None:
            spend_by_household[hh_id] = spend_by_household.get(hh_id, 0.0) + p["total_price"]
    for t in tax_payments:
        hh_id = household_id_by_resident.get(t["resident_db_id"])
        if hh_id is not None:
            spend_by_household[hh_id] = spend_by_household.get(hh_id, 0.0) + t["amount"]
    for household in household_rows:
        spent = spend_by_household.get(household["id"], 0.0)
        household["wealth"] = max(0.0, household.get("wealth", 0.0) - spent)
```

(`starting_wealth_by_ses`/`household_ses`/`compute_household_income` are the ones already added in Task 2 — this step only appends the block above.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_economy.py -v`
Expected: PASS (all tests, including Task 2's)

- [ ] **Step 5: Commit**

```bash
git add town_db/economy.py tests/test_db_economy.py
git commit -m "feat: add yearly wealth-cycle helpers to town_db/economy.py"
```

---

## Task 4: `town_db/persistence.py` — `update_household_wealth`

**Files:**
- Modify: `town_db/persistence.py`
- Test: `tests/test_db_persistence.py` (extend)

**Interfaces:**
- Produces (for Task 6/7 to reuse): `update_household_wealth(conn, household_rows) -> None`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db_persistence.py`:

```python
from town_db.persistence import insert_deaths, insert_residents, update_household_wealth


def test_update_household_wealth_writes_each_households_current_wealth(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (2, 'Doe', 'human')")
    conn.commit()

    update_household_wealth(conn, [{"id": 1, "wealth": 123.45}, {"id": 2, "wealth": 0.0}])
    conn.commit()

    rows = dict(conn.execute("SELECT id, wealth FROM households").fetchall())
    assert rows == {1: 123.45, 2: 0.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_db_persistence.py::test_update_household_wealth_writes_each_households_current_wealth -v`
Expected: FAIL — `ImportError: cannot import name 'update_household_wealth' from 'town_db.persistence'`

- [ ] **Step 3: Add the helper**

Append to `town_db/persistence.py`:

```python
def update_household_wealth(conn: sqlite3.Connection, household_rows: List[Dict[str, Any]]) -> None:
    for row in household_rows:
        conn.execute("UPDATE households SET wealth = ? WHERE id = ?", (row["wealth"], row["id"]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_persistence.py -v`
Expected: PASS (all tests, including the pre-existing two)

- [ ] **Step 5: Commit**

```bash
git add town_db/persistence.py tests/test_db_persistence.py
git commit -m "feat: add update_household_wealth persistence helper"
```

---

## Task 5: Wealth-tier reweighting in `town_db/purchases.py`

**Files:**
- Modify: `town_db/purchases.py`
- Test: `tests/test_db_goods_purchases.py` (extend)

**Interfaces:**
- Consumes: Task 3's `town_db.economy.wealth_tier`.
- Produces: `generate_purchases`'s existing signature is unchanged — richer households now shop more often, buy more of cheap bulk goods per trip, and skew toward `category == "luxury"` goods; poorer households do the reverse. `household_rows` dicts read a `"wealth"` key (via `.get(..., 0.0)`, so callers/tests that don't set it default to the `"poor"` tier — this task changes no existing test's assertions, but does change the *volume* of purchases generated for households with no `"wealth"` key, per Step 2's analysis below).

**Important — read before writing code:** `tests/test_db_goods_purchases.py`'s `_household()` helper doesn't set `"wealth"`, so every existing test in that file exercises the `"poor"` tier under this task's changes. Two invariants those tests already assert must keep holding *unconditionally*, not just for the `"poor"` tier:
1. `test_expensive_goods_are_only_ever_bought_one_at_a_time` (`price >= 1.0` → `quantity == 1`, always) — so the quantity multiplier below only ever applies to the cheap/bulk branch, never overrides the `quantity = 1` case.
2. `test_high_sv_staples_are_bought_more_often_than_low_sv_luxuries` (bread beats jewelry) — jewelry is `category == "luxury"`; the `"poor"` tier's luxury multiplier is `< 1.0`, which only widens that existing margin, so this holds automatically.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db_goods_purchases.py` (uses the file's existing `_household`/`_resident` helpers):

```python
def _household_with_wealth(id_, wealth):
    return {"id": id_, "family_name": "Smith", "race": "human", "wealth": wealth}


def test_wealthy_households_shop_more_often_than_poor_ones():
    poor_households = [_household_with_wealth(i, 0.0) for i in range(1, 21)]
    wealthy_households = [_household_with_wealth(i, 5000.0) for i in range(1, 21)]
    residents = [_resident(i, i) for i in range(1, 21)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}

    poor_purchases = generate_purchases(("town", 1), poor_households, residents, goods_ids, [10], YEAR_START, weeks=52)
    wealthy_purchases = generate_purchases(("town", 1), wealthy_households, residents, goods_ids, [10], YEAR_START, weeks=52)
    assert len(wealthy_purchases) > len(poor_purchases)


def test_wealthy_households_buy_more_luxury_goods_than_poor_ones():
    poor_households = [_household_with_wealth(i, 0.0) for i in range(1, 41)]
    wealthy_households = [_household_with_wealth(i, 5000.0) for i in range(1, 41)]
    residents = [_resident(i, i) for i in range(1, 41)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    luxury_good_ids = {goods_ids[g["name"]] for g in GOODS_CATALOG if g["category"] == "luxury"}

    poor_purchases = generate_purchases(("town", 1), poor_households, residents, goods_ids, [10], YEAR_START, weeks=52)
    wealthy_purchases = generate_purchases(("town", 1), wealthy_households, residents, goods_ids, [10], YEAR_START, weeks=52)
    poor_luxury = sum(1 for p in poor_purchases if p["good_id"] in luxury_good_ids)
    wealthy_luxury = sum(1 for p in wealthy_purchases if p["good_id"] in luxury_good_ids)
    assert wealthy_luxury > poor_luxury


def test_expensive_goods_are_still_only_ever_bought_one_at_a_time_regardless_of_wealth():
    households = [_household_with_wealth(i, 5000.0) for i in range(1, 21)]
    residents = [_resident(i, i) for i in range(1, 21)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    price_by_id = {goods_ids[g["name"]]: g["typical_price"] for g in GOODS_CATALOG}
    purchases = generate_purchases(("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52)
    for p in purchases:
        if price_by_id[p["good_id"]] >= 1.0:
            assert p["quantity"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_goods_purchases.py -v`
Expected: the three new tests FAIL (no wealth-tier effect exists yet — purchase volume/luxury-good counts are identical between the "poor" and "wealthy" household lists); all pre-existing tests in the file still PASS (nothing implemented yet).

- [ ] **Step 3: Add wealth-tier reweighting to `generate_purchases`**

In `town_db/purchases.py`, add the import and new constants near the top:

```python
from town_db.economy import wealth_tier

SHOP_BUILDING_TYPES = {"shop", "tavern", "market_stall"}
WEEKLY_PURCHASE_COUNT_WEIGHTS_BY_TIER = {
    "poor": [55, 30, 10, 5],
    "comfortable": [40, 30, 20, 10],
    "wealthy": [20, 25, 30, 25],
}
QUANTITY_MULTIPLIER_BY_TIER = {"poor": 0.7, "comfortable": 1.0, "wealthy": 1.4}
LUXURY_WEIGHT_MULTIPLIER_BY_TIER = {"poor": 0.3, "comfortable": 1.0, "wealthy": 2.0}
```

(`WEEKLY_PURCHASE_COUNT_WEIGHTS` is removed — replaced by the per-tier dict above. `"comfortable"`'s weights are the old flat default, so nothing regresses for a household that happens to sit in the middle tier.)

Then, inside `generate_purchases`, replace this block:

```python
    good_weights = [
        float(sv_by_name[name]) * magic_prevalence if category_by_name[name] == "magic" else float(sv_by_name[name])
        for name in goods_names
    ]
```

with (unchanged — this stays exactly as-is; the per-tier luxury reweighting happens per-household further down, since it depends on each household's own wealth, not something computable once up front):

```python
    good_weights = [
        float(sv_by_name[name]) * magic_prevalence if category_by_name[name] == "magic" else float(sv_by_name[name])
        for name in goods_names
    ]
```

Then replace the household loop body's start:

```python
        for household in household_rows:
            all_buyers = residents_by_household.get(household["id"], [])
            # A resident who has already died cannot shop this week.
            buyers = [
                r for r in all_buyers
                if r.get("death_date") is None
                or date.fromisoformat(r["death_date"]) >= week_start
            ]
            if not buyers:
                continue
            count = rng.choices([0, 1, 2, 3], weights=WEEKLY_PURCHASE_COUNT_WEIGHTS, k=1)[0]
            for _ in range(count):
                buyer = rng.choice(buyers)
                good_name = rng.choices(goods_names, weights=good_weights, k=1)[0]
```

with:

```python
        for household in household_rows:
            all_buyers = residents_by_household.get(household["id"], [])
            # A resident who has already died cannot shop this week.
            buyers = [
                r for r in all_buyers
                if r.get("death_date") is None
                or date.fromisoformat(r["death_date"]) >= week_start
            ]
            if not buyers:
                continue
            tier = wealth_tier(household.get("wealth", 0.0))
            tier_good_weights = [
                w * LUXURY_WEIGHT_MULTIPLIER_BY_TIER[tier] if category_by_name[name] == "luxury" else w
                for name, w in zip(goods_names, good_weights)
            ]
            count = rng.choices([0, 1, 2, 3], weights=WEEKLY_PURCHASE_COUNT_WEIGHTS_BY_TIER[tier], k=1)[0]
            for _ in range(count):
                buyer = rng.choice(buyers)
                good_name = rng.choices(goods_names, weights=tier_good_weights, k=1)[0]
```

Then replace the quantity line:

```python
                # Expensive goods are bought one at a time; cheap staples in bulk.
                quantity = 1 if price_by_name[good_name] >= 1.0 else rng.randint(1, 5)
```

with:

```python
                # Expensive goods are bought one at a time, regardless of wealth -- the wealth
                # effect on those goods is entirely via good *selection* (the luxury reweighting
                # above), not quantity. Only the cheap/bulk case scales with wealth tier.
                if price_by_name[good_name] >= 1.0:
                    quantity = 1
                else:
                    quantity = max(1, round(rng.randint(1, 5) * QUANTITY_MULTIPLIER_BY_TIER[tier]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_goods_purchases.py -v`
Expected: PASS (all tests, including every pre-existing one in the file — this is the regression guard for the rewrite).

- [ ] **Step 5: Commit**

```bash
git add town_db/purchases.py tests/test_db_goods_purchases.py
git commit -m "feat: reweight generate_purchases by household wealth tier"
```

---

## Task 6: Wire the wealth cycle into `town_db/generate.py`

**Files:**
- Modify: `town_db/generate.py`
- Test: `tests/test_db_generate.py` (extend)

**Interfaces:**
- Consumes: `town_db.economy.seed_starting_wealth`, `add_yearly_income`, `subtract_yearly_spend` (Tasks 2-3); `town_db.persistence.update_household_wealth` (Task 4).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db_generate.py`:

```python
def test_generate_town_database_seeds_and_updates_household_wealth(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT wealth FROM households").fetchall()
    assert len(rows) > 0
    # Every household ends the year with a real (non-default, non-negative) wealth value --
    # income was added and spend was subtracted, not left at the raw starting seed or at zero
    # for everyone.
    assert all(w >= 0.0 for (w,) in rows)
    assert len(set(rows)) > 1, "expected wealth to vary across households, not be uniform"


def test_generate_town_database_wealth_is_deterministic(tmp_path):
    db_path_1 = str(tmp_path / "town1.db")
    db_path_2 = str(tmp_path / "town2.db")
    generate_town_database(("town", 4), target_population=800, db_path=db_path_1)
    generate_town_database(("town", 4), target_population=800, db_path=db_path_2)

    conn1 = sqlite3.connect(db_path_1)
    conn2 = sqlite3.connect(db_path_2)
    rows1 = conn1.execute("SELECT id, wealth FROM households ORDER BY id").fetchall()
    rows2 = conn2.execute("SELECT id, wealth FROM households ORDER BY id").fetchall()
    assert rows1 == rows2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_generate.py -v`
Expected: the two new tests FAIL (`wealth` column exists from Task 1, but every household still ends at its `DEFAULT 0.0` since nothing populates it yet); all pre-existing tests still PASS.

- [ ] **Step 3: Wire the wealth cycle into `generate_town_database`**

In `town_db/generate.py`, add to the imports:

```python
from town_db.economy import add_yearly_income, seed_starting_wealth, subtract_yearly_spend
from town_db.persistence import update_household_wealth  # add to the existing persistence import block
```

Immediately after `build_households_and_residents` is called and `home_zone_type` is set on `resident_rows` (right before the `for household in household_rows:` insert loop), add:

```python
    seed_starting_wealth(household_rows, resident_rows)
```

Change the households insert loop from:

```python
    for household in household_rows:
        conn.execute(
            "INSERT INTO households (id, family_name, race) VALUES (?, ?, ?)",
            (household["id"], household["family_name"], household["race"]),
        )
```

to:

```python
    for household in household_rows:
        conn.execute(
            "INSERT INTO households (id, family_name, race, wealth) VALUES (?, ?, ?, ?)",
            (household["id"], household["family_name"], household["race"], household["wealth"]),
        )
```

Immediately after the `insert_residents(conn, resident_rows)` call (and before `generate_disease_events` runs), add:

```python
    zone_type_by_building_id_all = zone_type_by_building_id  # already built above, just a local alias for clarity
    building_type_by_id = {
        b.id: b.building_type for d in town.districts for b in d.buildings
    }
    add_yearly_income(seed, household_rows, resident_rows, building_type_by_id)
```

(`zone_type_by_building_id_all` is not otherwise used — drop that alias line, it's a leftover; just add the `building_type_by_id` dict and the `add_yearly_income` call.)

Immediately after `insert_tax_payments(conn, tax_payments)` (right after purchases and taxes are both generated and inserted, before `all_resident_rows = resident_rows + new_resident_rows`), add:

```python
    subtract_yearly_spend(household_rows, resident_rows, purchases, tax_payments)
    update_household_wealth(conn, household_rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_generate.py -v`
Expected: PASS (all tests, including `test_generate_town_database_is_deterministic` and `test_generate_town_database_business_rules` — regression guards for this task).

Run: `python -m pytest tests/ -v`
Expected: PASS — full suite green (this task's `generate_purchases`/`household_rows` changes are exercised by every test that calls `generate_town_database`).

- [ ] **Step 5: Commit**

```bash
git add town_db/generate.py tests/test_db_generate.py
git commit -m "feat: wire household wealth cycle into generate_town_database"
```

---

## Task 7: Wire the wealth cycle into `town_db/simulation.py`

**Files:**
- Modify: `town_db/simulation.py`
- Test: `tests/test_db_simulation.py` (extend)

**Interfaces:**
- Consumes: `town_db.economy.add_yearly_income`, `subtract_yearly_spend` (Tasks 2-3, `seed_starting_wealth` is generation-only, not used here); `town_db.persistence.update_household_wealth` (Task 4).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db_simulation.py`:

```python
def test_advance_town_updates_household_wealth_deterministically(tmp_path):
    db_path_1 = str(tmp_path / "town1.db")
    db_path_2 = str(tmp_path / "town2.db")
    generate_town_database(("town", 9), target_population=500, db_path=db_path_1)
    generate_town_database(("town", 9), target_population=500, db_path=db_path_2)

    advance_town(db_path_1, seed=("town", 9), years=2)
    advance_town(db_path_2, seed=("town", 9), years=2)

    conn1 = sqlite3.connect(db_path_1)
    conn2 = sqlite3.connect(db_path_2)
    rows1 = conn1.execute("SELECT id, wealth FROM households ORDER BY id").fetchall()
    rows2 = conn2.execute("SELECT id, wealth FROM households ORDER BY id").fetchall()
    assert rows1 == rows2
    assert all(w >= 0.0 for (_, w) in rows1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_db_simulation.py::test_advance_town_updates_household_wealth_deterministically -v`
Expected: PASS already by coincidence (wealth stays deterministic at whatever `generate_town_database` set it to, since `advance_town` doesn't touch it yet) — this step's real purpose is Step 3's assertion instead. Add this second assertion right below the existing ones in the same test before running it, so the test actually exercises `advance_town`'s own wealth update:

```python
    total_wealth_1 = sum(w for _, w in rows1)
    conn1_year1 = sqlite3.connect(db_path_1)
    # (Re-derive year-1-only wealth by generating a fresh comparison town and advancing it 1 year,
    # to confirm wealth actually changes between year 1 and year 2 -- not just staying frozen.)
    db_path_1yr = str(tmp_path / "town1_1yr.db")
    generate_town_database(("town", 9), target_population=500, db_path=db_path_1yr)
    advance_town(db_path_1yr, seed=("town", 9), years=1)
    conn_1yr = sqlite3.connect(db_path_1yr)
    total_wealth_1yr = sum(w for (w,) in conn_1yr.execute("SELECT wealth FROM households").fetchall())
    assert total_wealth_1 != total_wealth_1yr, "expected total household wealth to change between year 1 and year 2"
```

Run: `python -m pytest tests/test_db_simulation.py::test_advance_town_updates_household_wealth_deterministically -v`
Expected: FAIL on the new final assertion (`advance_town` doesn't call any wealth-cycle function yet, so total wealth after 1 year equals total wealth after 2 years — both frozen at generation's value).

- [ ] **Step 3: Wire the wealth cycle into `advance_town`**

In `town_db/simulation.py`, add to the imports:

```python
from town_db.economy import add_yearly_income, subtract_yearly_spend
```

and add `update_household_wealth` to the existing `from town_db.persistence import (...)` block.

Add a building-type lookup helper next to the existing `_goods_ids`/`_building_ids` helpers:

```python
def _building_type_by_id(conn) -> Dict[int, str]:
    return {r[0]: r[1] for r in conn.execute("SELECT id, building_type FROM buildings").fetchall()}
```

Inside `advance_town`'s per-year loop, immediately after `resident_rows = _load_resident_rows(conn, year_start)` (before `generate_disease_events` runs), add:

```python
            building_type_by_id = _building_type_by_id(conn)
            add_yearly_income(year_seed, household_rows, resident_rows, building_type_by_id)
```

Finally, update `_load_household_rows` to load the persisted wealth (so the next simulated year, and Task 5's `generate_purchases`, both see the current balance rather than always reading a stale/default 0):

```python
def _load_household_rows(conn) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT id, family_name, race, wealth FROM households").fetchall()
    return [{"id": r[0], "family_name": r[1], "race": r[2], "wealth": r[3]} for r in rows]
```

Add one more helper next to `_building_type_by_id`, to reconcile `household_rows` with the DB after `generate_household_formations` may have created new households mid-year:

```python
def _append_new_households(conn, household_rows: List[Dict[str, Any]]) -> None:
    """generate_household_formations inserts new households directly via SQL, bypassing this
    in-memory list -- append any the list doesn't know about yet, without touching existing
    entries (which already carry this year's added income, computed above, and must not be
    overwritten by a stale DB re-read of their pre-income wealth). A newly-formed household has
    no wealth of its own yet this year -- its movers' income was already added to their *old*
    households before generate_household_formations ran -- so it starts at the schema default
    (0.0), same as any other freshly-inserted household row."""
    known_ids = {h["id"] for h in household_rows}
    for row in conn.execute("SELECT id, family_name, race, wealth FROM households").fetchall():
        if row[0] not in known_ids:
            household_rows.append({"id": row[0], "family_name": row[1], "race": row[2], "wealth": row[3]})
```

**Important — ordering.** `household_rows` is loaded once at the top of each year's iteration and mutated in place by `add_yearly_income` (adding this year's income) before `generate_purchases` runs later in the loop — so it must **not** be reloaded wholesale from the DB afterward (the existing `all_household_rows = _load_household_rows(conn)` call partway through the loop, right before `generate_purchases`, would silently discard that in-memory income addition by re-reading the pre-income DB value). But `generate_household_formations` (which runs between those two points) inserts new households directly into the DB, so `household_rows` also needs to learn about any new ones. Replace:

```python
            all_household_rows = _load_household_rows(conn)
            all_resident_rows = _load_resident_rows(conn, year_start)
```

with:

```python
            _append_new_households(conn, household_rows)
            all_household_rows = household_rows
            all_resident_rows = _load_resident_rows(conn, year_start)
```

(`all_resident_rows` still needs a fresh reload here — it must reflect this year's household-formation and job-market changes.)

Immediately after `insert_tax_payments(conn, tax_payments)` (before the school/military block that follows), add:

```python
            subtract_yearly_spend(household_rows, all_resident_rows, purchases, tax_payments)
            update_household_wealth(conn, household_rows)
```

Note this passes **`all_resident_rows`**, not the year-start `resident_rows` — `purchases`/`tax_payments` were generated against `all_resident_rows` (the post-household-formation/job-market snapshot), so the resident→household mapping `subtract_yearly_spend` builds internally must match that same snapshot, or a resident who moved to a new household this year would have their spend misattributed to the household they left.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_simulation.py -v`
Expected: PASS (all tests, including the pre-existing five).

Run: `python -m pytest tests/ -v`
Expected: PASS — full suite green.

- [ ] **Step 5: Commit**

```bash
git add town_db/simulation.py tests/test_db_simulation.py
git commit -m "feat: wire household wealth cycle into advance_town"
```

---

## Task 8: Integration tests — the regression this plan exists to fix

**Files:**
- Test: `tests/test_db_simulation_integration.py` (extend)

**Interfaces:**
- Consumes: `generate_town_database`, `advance_town` (already imported in this file).

- [ ] **Step 1: Write the tests**

Add to `tests/test_db_simulation_integration.py`:

```python
def test_rich_households_out_spend_poor_households_over_time(tmp_path):
    # The regression this plan exists to fix: a test town previously showed its single highest
    # individual spender for the year was poor, out-spending every rich resident. This asserts
    # the opposite now holds, at the household level, across a seed sweep and multiple years.
    rich_medians = []
    poor_medians = []
    for seed in SEEDS:
        db_path = str(tmp_path / f"wealth_{seed[1]}.db")
        generate_town_database(seed, target_population=600, db_path=db_path)
        advance_town(db_path, seed=seed, years=3)

        conn = sqlite3.connect(db_path)
        # A household's ses for this comparison: the modal ses among its living residents,
        # same definition town_db.economy.household_ses uses internally.
        household_ses_rows = conn.execute(
            "SELECT household_id, ses, COUNT(*) c FROM residents WHERE death_date IS NULL "
            "GROUP BY household_id, ses"
        ).fetchall()
        modal_ses_by_household: dict = {}
        best_count: dict = {}
        for household_id, ses, count in household_ses_rows:
            if household_id not in best_count or count > best_count[household_id]:
                best_count[household_id] = count
                modal_ses_by_household[household_id] = ses

        spend_by_household = dict(conn.execute(
            "SELECT household_id, total FROM ("
            "  SELECT r.household_id AS household_id, SUM(p.total_price) AS total "
            "  FROM purchases p JOIN residents r ON r.id = p.resident_id GROUP BY r.household_id"
            ")"
        ).fetchall())

        rich_spends = [
            spend_by_household.get(hh_id, 0.0)
            for hh_id, ses in modal_ses_by_household.items() if ses == "rich"
        ]
        poor_spends = [
            spend_by_household.get(hh_id, 0.0)
            for hh_id, ses in modal_ses_by_household.items() if ses == "poor"
        ]
        if rich_spends and poor_spends:
            rich_medians.append(sorted(rich_spends)[len(rich_spends) // 2])
            poor_medians.append(sorted(poor_spends)[len(poor_spends) // 2])

    assert rich_medians and poor_medians, "expected both rich and poor households in every swept seed"
    seeds_where_rich_wins = sum(1 for r, p in zip(rich_medians, poor_medians) if r > p)
    assert seeds_where_rich_wins == len(rich_medians), (
        f"expected rich median spend > poor median spend in every seed; "
        f"rich={rich_medians}, poor={poor_medians}"
    )


def test_household_wealth_never_goes_negative_across_seeds_and_years(tmp_path):
    for seed in SEEDS:
        db_path = str(tmp_path / f"wealthfloor_{seed[1]}.db")
        generate_town_database(seed, target_population=400, db_path=db_path)
        advance_town(db_path, seed=seed, years=5)
        conn = sqlite3.connect(db_path)
        negative = conn.execute("SELECT COUNT(*) FROM households WHERE wealth < 0").fetchone()[0]
        assert negative == 0, f"seed {seed}"
```

- [ ] **Step 2: Run to verify they pass**

Run: `python -m pytest tests/test_db_simulation_integration.py -v`
Expected: PASS. If `test_rich_households_out_spend_poor_households_over_time` fails on some seeds, that's this plan's actual acceptance signal per the Global Constraints section — tune `town_db/economy.py`'s `INCOME_TIER_BY_ROLE`/`SES_INCOME_MULTIPLIER`/`STARTING_WEALTH_BY_SES` and/or `town_db/purchases.py`'s `WEEKLY_PURCHASE_COUNT_WEIGHTS_BY_TIER`/`LUXURY_WEIGHT_MULTIPLIER_BY_TIER` until it reliably passes across the full seed sweep, rather than weakening the assertion (e.g. to "most seeds" or a smaller margin).

- [ ] **Step 3: Run the entire test suite one final time**

Run: `python -m pytest tests/ -v`
Expected: PASS — full green suite, household wealth model complete.

- [ ] **Step 4: Commit**

```bash
git add tests/test_db_simulation_integration.py
git commit -m "test: add wealth-differentiation regression test and wealth-floor guard"
```
