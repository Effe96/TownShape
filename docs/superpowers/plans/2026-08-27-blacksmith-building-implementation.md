# Blacksmith Building Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new, unconditional `blacksmith` MERCHANT-zone building type and a new `weapons` goods category, mirroring `arcane_shop`'s purchase-scoping pattern but with no gating parameter.

**Architecture:** `town_shaper/buildings.py` gains `blacksmith` as a normal MERCHANT-zone building type option (rebalanced weights, new job vacancies) — no new `TownParameters` field, since every town can generate one just like a `shop` or `tavern`. `town_db/goods.py` gains 5 new `weapons`-category goods. `town_db/purchases.py` scopes weapons-good purchases to `blacksmith_building_ids` exactly the way magic goods are scoped to `arcane_shop_building_ids`, and `town_db/generate.py` computes and threads that list through, mirroring the existing `arcane_shop_building_ids` wiring line-for-line.

**Tech Stack:** Python 3.12, stdlib `sqlite3` — no new dependency.

**Spec:** `docs/superpowers/specs/2026-08-27-blacksmith-building-design.md`

## Global Constraints

- This change is **NOT backward-compatible by design** — unlike every prior D1a-D1d parameter, `blacksmith` is unconditional (no gating field), so it is a real, deliberate change to every generated town's default building distribution the moment Task 1 lands. A test that starts failing because it depended on the old `BUILDING_TYPES_BY_ZONE[MERCHANT]` weight table's exact sampling is expected fallout to **fix**, not a regression to revert and not evidence Task 1 is wrong.
- `smith_apprentice`, never `apprentice`, for the blacksmith's staff occupation — `apprentice` is already used by `arcane_shop`, and reusing it would make occupation-based queries ambiguous between the two building types.
- `blacksmith` is deliberately excluded from `SHOP_BUILDING_TYPES` (`{"shop", "tavern", "market_stall"}`) and from `BUILDING_HOME_CAPACITY` — it never sells the generic shop catalog, and it is a workplace, not a home, exactly like `arcane_shop`.
- No `TownParameters`, `generation_parameters`, or narrative-mapping doc changes anywhere in this plan — this is unconditional infrastructure, not a narrative-driven parameter.

---

## Task 1: `blacksmith` building type in `town_shaper/buildings.py`

**Files:**
- Modify: `town_shaper/buildings.py`
- Test: `tests/test_buildings.py`

**Interfaces:**
- Produces: `BUILDING_TYPES_BY_ZONE[ZoneType.MERCHANT]` includes `"blacksmith": 0.15`; `JOB_VACANCIES_BY_BUILDING_TYPE["blacksmith"] == [("blacksmith", 1), ("smith_apprentice", 2)]`; `"blacksmith"` is absent from `BUILDING_HOME_CAPACITY`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_buildings.py`:

```python
def test_blacksmith_appears_in_merchant_zone():
    district = _square_district(ZoneType.MERCHANT, side=200.0)
    shop_count = 0
    blacksmith_count = 0
    trials = 30
    for seed_index in range(trials):
        buildings = fill_district_buildings(district, ("town", seed_index), next_building_id=0)
        shop_count += sum(1 for b in buildings if b.building_type == "shop")
        blacksmith_count += sum(1 for b in buildings if b.building_type == "blacksmith")
    assert blacksmith_count > 0
    assert shop_count > blacksmith_count


def test_blacksmith_does_not_crowd_out_existing_merchant_building_types():
    district = _square_district(ZoneType.MERCHANT, side=200.0)
    seen_types = set()
    for seed_index in range(30):
        buildings = fill_district_buildings(district, ("town", seed_index), next_building_id=0)
        seen_types.update(b.building_type for b in buildings)
    assert {"shop", "tavern", "market_stall", "blacksmith"} <= seen_types


def test_blacksmith_job_vacancies_match_job_table():
    from town_shaper.buildings import JOB_VACANCIES_BY_BUILDING_TYPE
    assert JOB_VACANCIES_BY_BUILDING_TYPE["blacksmith"] == [("blacksmith", 1), ("smith_apprentice", 2)]


def test_blacksmith_has_no_home_capacity():
    from town_shaper.buildings import BUILDING_HOME_CAPACITY
    assert "blacksmith" not in BUILDING_HOME_CAPACITY
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_buildings.py -v -k blacksmith`
Expected: FAIL — `blacksmith` never appears (`blacksmith_count == 0`), `KeyError: 'blacksmith'` on the job-vacancy lookup.

- [ ] **Step 3: Modify the implementation**

In `town_shaper/buildings.py`, change:

```python
    ZoneType.MERCHANT: {"shop": 0.5, "tavern": 0.2, "market_stall": 0.3},
```

to:

```python
    ZoneType.MERCHANT: {"shop": 0.4, "tavern": 0.2, "market_stall": 0.25, "blacksmith": 0.15},
```

and add to `JOB_VACANCIES_BY_BUILDING_TYPE` (anywhere in the dict, e.g. right after the `"tavern"` entry):

```python
    "blacksmith": [("blacksmith", 1), ("smith_apprentice", 2)],
```

Do not add `"blacksmith"` to `BUILDING_HOME_CAPACITY` — its absence is the correct, default state; no edit needed there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_buildings.py -v`
Expected: PASS (every test in the file, not just the new ones)

- [ ] **Step 5: Run the whole suite and fix (not revert) any fallout**

Run: `python -m pytest tests/ -q`

This change is not backward-compatible by design (see Global Constraints) — a test that hardcoded an exact building type for a specific seed/index tied to the old `BUILDING_TYPES_BY_ZONE[MERCHANT]` weights may now fail. If any test fails:
1. Read it and confirm the failure is exactly this kind of hardcoded-old-weight dependency (not some other break).
2. Update that test's expectation to match the new, correct behavior — do not revert the weight change to make an old expectation pass again.
3. Re-run the full suite to confirm everything is green.

If nothing fails, that's fine too — proceed directly to Step 6.

- [ ] **Step 6: Commit**

```bash
git add town_shaper/buildings.py tests/test_buildings.py
git commit -m "feat: add blacksmith building type to the merchant zone"
```

If Step 5 required fixing any other test file, `git add` those files in the same commit.

---

## Task 2: `weapons` goods category in `town_db/goods.py`

**Files:**
- Modify: `town_db/goods.py`
- Test: `tests/test_db_goods_purchases.py`

**Interfaces:**
- Consumes: nothing from Task 1 — this task is independent and can be done in either order relative to Task 1.
- Produces: `GOODS_CATALOG` includes 5 rows with `category == "weapons"`: `dagger` ($3.0, sv 600), `sword` ($10.0, sv 350), `shield` ($8.0, sv 400), `leather armor` ($15.0, sv 300), `chainmail` ($40.0, sv 150).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db_goods_purchases.py`:

```python
def test_goods_catalog_includes_weapons_category():
    weapons_goods = [g for g in GOODS_CATALOG if g["category"] == "weapons"]
    assert {g["name"] for g in weapons_goods} == {"dagger", "sword", "shield", "leather armor", "chainmail"}


def test_weapons_goods_have_the_expected_prices_and_sv():
    by_name = {g["name"]: g for g in GOODS_CATALOG if g["category"] == "weapons"}
    assert by_name["dagger"]["typical_price"] == 3.0 and by_name["dagger"]["sv"] == 600
    assert by_name["sword"]["typical_price"] == 10.0 and by_name["sword"]["sv"] == 350
    assert by_name["shield"]["typical_price"] == 8.0 and by_name["shield"]["sv"] == 400
    assert by_name["leather armor"]["typical_price"] == 15.0 and by_name["leather armor"]["sv"] == 300
    assert by_name["chainmail"]["typical_price"] == 40.0 and by_name["chainmail"]["sv"] == 150


def test_insert_goods_includes_weapons_goods(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    ids = insert_goods(conn)
    for name in ("dagger", "sword", "shield", "leather armor", "chainmail"):
        assert name in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_goods_purchases.py -v -k weapons`
Expected: FAIL — `AssertionError`, the weapons goods don't exist in `GOODS_CATALOG` yet.

- [ ] **Step 3: Modify the implementation**

In `town_db/goods.py`, change the stale comment above `GOODS_CATALOG` from:

```python
# A representative slice of medieval-demographics-made-easy.pdf's Support
# Value table: population needed to support one business of this type.
# Lower sv = more common = more frequently purchased.
```

to:

```python
# A representative slice of medieval-demographics-made-easy.pdf's Support
# Value table: population needed to support one business of this type.
# Higher sv = more common = more frequently purchased.
```

(this corrects a pre-existing documentation error — it contradicted both the actual data below, e.g. bread at sv=800 is bought far more often than jewelry at sv=400, and `town_db/purchases.py`'s own correct comment on the same concept; no runtime behavior changes)

Then append 5 rows to `GOODS_CATALOG` (after the existing `"arcane reagents"` row):

```python
    {"name": "dagger", "category": "weapons", "typical_price": 3.0, "sv": 600},
    {"name": "sword", "category": "weapons", "typical_price": 10.0, "sv": 350},
    {"name": "shield", "category": "weapons", "typical_price": 8.0, "sv": 400},
    {"name": "leather armor", "category": "weapons", "typical_price": 15.0, "sv": 300},
    {"name": "chainmail", "category": "weapons", "typical_price": 40.0, "sv": 150},
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_goods_purchases.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_db/goods.py tests/test_db_goods_purchases.py
git commit -m "feat: add weapons goods category"
```

---

## Task 3: Scope weapons purchases to blacksmith buildings

**Files:**
- Modify: `town_db/purchases.py`
- Modify: `town_db/generate.py`
- Test: `tests/test_db_goods_purchases.py`
- Test: `tests/test_db_generate.py`

**Interfaces:**
- Consumes: `GOODS_CATALOG` weapons rows (Task 2); `"blacksmith"` building type (Task 1, for the end-to-end test in Step 6 — the unit tests in Steps 1-4 don't need real generation, they pass `blacksmith_building_ids` directly like the existing magic tests do).
- Produces: `generate_purchases(..., blacksmith_building_ids: Optional[List[int]] = None)`; `town_db/generate.py` computes and passes `blacksmith_building_ids` into that call, mirroring the existing `arcane_shop_building_ids` line exactly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db_goods_purchases.py`:

```python
def test_weapons_goods_excluded_when_no_blacksmith_building_ids_given():
    households = [_household(i) for i in range(1, 21)]
    residents = [_resident(i, i) for i in range(1, 21)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    weapons_good_ids = {goods_ids[n] for n in ("dagger", "sword", "shield", "leather armor", "chainmail")}
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52,
    )
    assert all(p["good_id"] not in weapons_good_ids for p in purchases)


def test_weapons_goods_excluded_when_blacksmith_building_ids_is_empty():
    households = [_household(i) for i in range(1, 21)]
    residents = [_resident(i, i) for i in range(1, 21)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    weapons_good_ids = {goods_ids[n] for n in ("dagger", "sword", "shield", "leather armor", "chainmail")}
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52,
        blacksmith_building_ids=[],
    )
    assert all(p["good_id"] not in weapons_good_ids for p in purchases)


def test_weapons_goods_purchased_and_shop_scoped_when_available():
    households = [_household(i) for i in range(1, 41)]
    residents = [_resident(i, i) for i in range(1, 41)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    weapons_good_ids = {goods_ids[n] for n in ("dagger", "sword", "shield", "leather armor", "chainmail")}
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52,
        blacksmith_building_ids=[99],
    )
    weapons_purchases = [p for p in purchases if p["good_id"] in weapons_good_ids]
    assert len(weapons_purchases) > 0
    assert all(p["shop_building_id"] == 99 for p in weapons_purchases)
    non_weapons_purchases = [p for p in purchases if p["good_id"] not in weapons_good_ids]
    assert all(p["shop_building_id"] == 10 for p in non_weapons_purchases)


def test_generate_purchases_with_weapons_goods_present_in_catalog_matches_pool_without_them_at_defaults():
    households = [_household(1)]
    residents = [_resident(1, 1)]
    full_goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    non_weapons_goods_ids = {
        g["name"]: full_goods_ids[g["name"]] for g in GOODS_CATALOG if g["category"] != "weapons"
    }
    with_weapons_in_catalog = generate_purchases(
        ("town", 1), households, residents, full_goods_ids, [10], YEAR_START, weeks=52
    )
    without_weapons_in_catalog = generate_purchases(
        ("town", 1), households, residents, non_weapons_goods_ids, [10], YEAR_START, weeks=52
    )
    assert with_weapons_in_catalog == without_weapons_in_catalog
```

Append to `tests/test_db_generate.py`:

```python
def test_generate_town_database_produces_weapons_purchases_scoped_to_blacksmiths(tmp_path):
    found_weapons_purchase = False
    for seed_index in range(10):
        db_path = str(tmp_path / f"town_{seed_index}.db")
        generate_town_database(("town", seed_index), target_population=3000, db_path=db_path)
        conn = sqlite3.connect(db_path)

        blacksmith_ids = {
            row[0] for row in conn.execute(
                "SELECT id FROM buildings WHERE building_type = 'blacksmith'"
            ).fetchall()
        }
        weapons_good_ids = {
            row[0] for row in conn.execute(
                "SELECT id FROM goods WHERE category = 'weapons'"
            ).fetchall()
        }
        weapons_purchase_shops = {
            row[0] for row in conn.execute(
                "SELECT DISTINCT shop_building_id FROM purchases WHERE good_id IN ({})".format(
                    ",".join(str(i) for i in weapons_good_ids)
                )
            ).fetchall()
        } if weapons_good_ids else set()

        if weapons_purchase_shops:
            found_weapons_purchase = True
            assert weapons_purchase_shops <= blacksmith_ids

    assert found_weapons_purchase


def test_generate_town_database_with_blacksmith_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_goods_purchases.py tests/test_db_generate.py -v -k "weapons or blacksmith"`
Expected: FAIL — `TypeError: generate_purchases() got an unexpected keyword argument 'blacksmith_building_ids'` for the purchases tests; the generate.py-level tests fail because no weapons purchases can exist yet (blacksmith buildings exist from Task 1, but nothing scopes weapons goods to them).

- [ ] **Step 3: Modify `town_db/purchases.py`**

Change the function signature from:

```python
def generate_purchases(
    seed,
    household_rows: List[Dict[str, Any]],
    resident_rows: List[Dict[str, Any]],
    goods_ids: Dict[str, int],
    shop_building_ids: List[int],
    year_start: date,
    weeks: int = 52,
    magic_prevalence: float = 0.0,
    arcane_shop_building_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
```

to:

```python
def generate_purchases(
    seed,
    household_rows: List[Dict[str, Any]],
    resident_rows: List[Dict[str, Any]],
    goods_ids: Dict[str, int],
    shop_building_ids: List[int],
    year_start: date,
    weeks: int = 52,
    magic_prevalence: float = 0.0,
    arcane_shop_building_ids: Optional[List[int]] = None,
    blacksmith_building_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
```

Change:

```python
    arcane_shop_building_ids = arcane_shop_building_ids or []
    rng = rng_for(seed, "db", "purchases")
```

to:

```python
    arcane_shop_building_ids = arcane_shop_building_ids or []
    blacksmith_building_ids = blacksmith_building_ids or []
    rng = rng_for(seed, "db", "purchases")
```

Change:

```python
    magic_available = magic_prevalence > 0 and len(arcane_shop_building_ids) > 0
    goods_names = [
        name for name in sv_by_name
        if category_by_name[name] != "magic" or magic_available
    ]
```

to:

```python
    magic_available = magic_prevalence > 0 and len(arcane_shop_building_ids) > 0
    weapons_available = len(blacksmith_building_ids) > 0
    goods_names = [
        name for name in sv_by_name
        if (category_by_name[name] != "magic" or magic_available)
        and (category_by_name[name] != "weapons" or weapons_available)
    ]
```

Change:

```python
                if category_by_name[good_name] == "magic":
                    shop_id = rng.choice(arcane_shop_building_ids)
                else:
                    shop_id = rng.choice(shop_building_ids)
```

to:

```python
                if category_by_name[good_name] == "magic":
                    shop_id = rng.choice(arcane_shop_building_ids)
                elif category_by_name[good_name] == "weapons":
                    shop_id = rng.choice(blacksmith_building_ids)
                else:
                    shop_id = rng.choice(shop_building_ids)
```

Do not change `SHOP_BUILDING_TYPES` — it stays `{"shop", "tavern", "market_stall"}`.

- [ ] **Step 4: Run the purchases tests to verify they pass**

Run: `python -m pytest tests/test_db_goods_purchases.py -v`
Expected: PASS

- [ ] **Step 5: Modify `town_db/generate.py`**

Find the existing block:

```python
    arcane_shop_building_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type == "arcane_shop"
    ]
    purchases = generate_purchases(
        seed, household_rows, resident_rows, goods_ids, shop_building_ids, year_start,
        magic_prevalence=magic_prevalence, arcane_shop_building_ids=arcane_shop_building_ids,
    )
```

and change it to:

```python
    arcane_shop_building_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type == "arcane_shop"
    ]
    blacksmith_building_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type == "blacksmith"
    ]
    purchases = generate_purchases(
        seed, household_rows, resident_rows, goods_ids, shop_building_ids, year_start,
        magic_prevalence=magic_prevalence, arcane_shop_building_ids=arcane_shop_building_ids,
        blacksmith_building_ids=blacksmith_building_ids,
    )
```

- [ ] **Step 6: Run the generate-level tests to verify they pass**

Run: `python -m pytest tests/test_db_generate.py -v -k "weapons or blacksmith"`
Expected: PASS

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: PASS for every test.

- [ ] **Step 8: Commit**

```bash
git add town_db/purchases.py town_db/generate.py tests/test_db_goods_purchases.py tests/test_db_generate.py
git commit -m "feat: scope weapons purchases to blacksmith buildings"
```
