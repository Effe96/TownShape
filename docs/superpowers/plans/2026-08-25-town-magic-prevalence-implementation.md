# Town Magic Prevalence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `magic_prevalence` parameter representing how prevalent magic is in a town, expressed as a new `arcane_shop` building type with `mage`/`apprentice` jobs, new magic-category goods purchasable only where an `arcane_shop` exists, and a `has_magical_talent` resident trait — threaded end-to-end through `TownParameters` → `generate_town_from_parameters`.

**Architecture:** `arcane_shop` is added dynamically (not statically) to `MERCHANT`'s building-type weights inside `fill_district_buildings`, scaling with `magic_prevalence` — the same "copy the dict, conditionally mutate" pattern already used for `university`'s conditional inclusion in `CIVIC`. Magic goods are new `GOODS_CATALOG` entries with `category="magic"`; `generate_purchases` gains scoping logic so they're only purchasable (and only at `arcane_shop` buildings specifically) when both `magic_prevalence > 0` and an `arcane_shop` actually exists in the town. `has_magical_talent` is a new boolean column on `residents`, tagged by a new `_tag_magical_talent` helper structurally identical to the existing `_tag_nobility` pass — an independent per-resident coin flip, deliberately uncorrelated with occupation. Every new parameter defaults to reproducing today's exact behavior.

**Tech Stack:** Python 3.12, stdlib only (`dataclasses`, `sqlite3`) — no new runtime dependency (unlike 1b, this slice needs no geometry).

**Spec:** `docs/superpowers/specs/2026-08-25-town-magic-prevalence-design.md`

## Global Constraints

- Every new parameter (`magic_prevalence`) is optional with a default that reproduces today's exact behavior (`0.0` — no arcane shops, no magic goods purchased, no residents tagged with `has_magical_talent`) — no existing call site or test outside the files this plan touches should require changes.
- `arcane_shop`'s weight in `MERCHANT`'s building-type dict is computed dynamically as `magic_prevalence * ARCANE_SHOP_WEIGHT_SCALE` (`ARCANE_SHOP_WEIGHT_SCALE = 0.5`) inside `fill_district_buildings`, added to a **copy** of the zone's type-weights dict — never a static entry in the module-level `BUILDING_TYPES_BY_ZONE` dict, since it must scale continuously rather than sit at a fixed value.
- Magic-category goods (`category == "magic"` in `GOODS_CATALOG`) are excluded entirely from `generate_purchases`'s weighted-choice pool unless **both** `magic_prevalence > 0` **and** `arcane_shop_building_ids` is non-empty. When eligible, their weight is `sv * magic_prevalence` and their shop is drawn from `arcane_shop_building_ids` specifically, never the general `shop_building_ids` pool.
- `has_magical_talent` is tagged as an independent per-resident probability (`rng.random() < magic_prevalence`), deliberately **not** correlated with the `mage`/`apprentice` occupations or any other resident attribute — this is an explicit design decision, not an oversight.
- `magic_prevalence` is validated `0.0 <= magic_prevalence <= 1.0` in `TownParameters.__post_init__`, raising `ValueError` otherwise — same pattern as the existing `rich_proportion` check.
- No `arcane_shop` spawning, and no residents with `has_magical_talent`, is not an error at any `magic_prevalence` value — matches this project's existing tolerance for statistical/probabilistic shortfalls (e.g. `density_multiplier`'s housing-shortfall behavior).
- Test files for changed modules are extended by appending to their existing test files — no new test files needed for this plan (no new modules are created).

---

## Task 1: `arcane_shop` building type + occupations (`town_shaper/buildings.py`)

**Files:**
- Modify: `town_shaper/buildings.py`
- Test: `tests/test_buildings.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: `fill_district_buildings(district, town_seed, next_building_id, target_population=0, density_multiplier=1.0, magic_prevalence=0.0) -> List[Building]`; `JOB_VACANCIES_BY_BUILDING_TYPE["arcane_shop"] == [("mage", 1), ("apprentice", 2)]`; `ARCANE_SHOP_WEIGHT_SCALE = 0.5` module constant.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_buildings.py`:

```python
def test_arcane_shop_never_appears_at_zero_magic_prevalence():
    district = _square_district(ZoneType.MERCHANT, side=200.0)
    for seed_index in range(20):
        buildings = fill_district_buildings(district, ("town", seed_index), next_building_id=0)
        assert all(b.building_type != "arcane_shop" for b in buildings)


def test_arcane_shop_appears_more_often_at_higher_magic_prevalence():
    district = _square_district(ZoneType.MERCHANT, side=200.0)
    low_count = 0
    high_count = 0
    trials = 30
    for seed_index in range(trials):
        low_buildings = fill_district_buildings(
            district, ("town", seed_index), next_building_id=0, magic_prevalence=0.05,
        )
        high_buildings = fill_district_buildings(
            district, ("town", seed_index), next_building_id=0, magic_prevalence=0.9,
        )
        low_count += sum(1 for b in low_buildings if b.building_type == "arcane_shop")
        high_count += sum(1 for b in high_buildings if b.building_type == "arcane_shop")
    assert high_count > low_count


def test_arcane_shop_job_vacancies_match_job_table():
    from town_shaper.buildings import JOB_VACANCIES_BY_BUILDING_TYPE
    assert JOB_VACANCIES_BY_BUILDING_TYPE["arcane_shop"] == [("mage", 1), ("apprentice", 2)]


def test_arcane_shop_has_no_home_capacity():
    from town_shaper.buildings import BUILDING_HOME_CAPACITY
    assert "arcane_shop" not in BUILDING_HOME_CAPACITY


def test_fill_district_buildings_default_magic_prevalence_matches_previous_behavior():
    district = _square_district(ZoneType.MERCHANT, side=100.0)
    baseline = fill_district_buildings(district, ("town", 1), next_building_id=0)
    explicit = fill_district_buildings(district, ("town", 1), next_building_id=0, magic_prevalence=0.0)
    assert [(b.id, b.x, b.y, b.building_type) for b in baseline] == \
           [(b.id, b.x, b.y, b.building_type) for b in explicit]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_buildings.py -v -k "arcane_shop or default_magic_prevalence"`
Expected: FAIL — `test_arcane_shop_never_appears_at_zero_magic_prevalence` and `..._appears_more_often...` fail because `arcane_shop` never appears at all (no code produces it yet); `test_arcane_shop_job_vacancies_match_job_table` fails with `KeyError: 'arcane_shop'`; `test_fill_district_buildings_default_magic_prevalence_matches_previous_behavior` fails with `TypeError: fill_district_buildings() got an unexpected keyword argument 'magic_prevalence'`.

- [ ] **Step 3: Modify the implementation**

Add a new constant near `UNIVERSITY_MIN_POPULATION`/`UNIVERSITY_CHANCE`:

```python
ARCANE_SHOP_WEIGHT_SCALE = 0.5
```

Add a new entry to `JOB_VACANCIES_BY_BUILDING_TYPE` (after `"harbormaster_office"`):

```python
    "arcane_shop": [("mage", 1), ("apprentice", 2)],
```

Change `fill_district_buildings`'s signature and the `type_weights` construction:

```python
def fill_district_buildings(
    district: District, town_seed, next_building_id: int,
    target_population: int = 0, density_multiplier: float = 1.0,
    magic_prevalence: float = 0.0,
) -> List[Building]:
```

```python
    type_weights = dict(BUILDING_TYPES_BY_ZONE[district.zone_type])
    if district.zone_type == ZoneType.CIVIC and "university" in type_weights:
        university_eligible = (
            target_population >= UNIVERSITY_MIN_POPULATION and rng.random() < UNIVERSITY_CHANCE
        )
        if not university_eligible:
            del type_weights["university"]
    if district.zone_type == ZoneType.MERCHANT and magic_prevalence > 0:
        type_weights["arcane_shop"] = magic_prevalence * ARCANE_SHOP_WEIGHT_SCALE
    subtypes = list(type_weights.keys())
    weights = list(type_weights.values())
```

The rest of the function (from `buildings: List[Building] = []` onward) is unchanged — `JOB_VACANCIES_BY_BUILDING_TYPE[building_type]` already generalizes to `"arcane_shop"` since it's a plain dict lookup, and `BUILDING_HOME_CAPACITY.get(building_type, 0)` already defaults to `0` (no housing) for any type not in that dict, which `"arcane_shop"` correctly is not.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_buildings.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add town_shaper/buildings.py tests/test_buildings.py
git commit -m "feat: add arcane_shop building type scaling with magic_prevalence"
```

---

## Task 2: `generate_town` threads `magic_prevalence` (`town_shaper/generate.py`)

**Files:**
- Modify: `town_shaper/generate.py`
- Test: `tests/test_generate.py` (append)

**Interfaces:**
- Consumes: `fill_district_buildings(..., magic_prevalence=0.0)` (Task 1)
- Produces: `generate_town(seed, target_population, area_per_resident_multiplier=1.0, density_multiplier=1.0, rich_proportion=DEFAULT_RICH_PROPORTION, num_rivers=0, has_coastline=False, has_port=False, magic_prevalence=0.0) -> Town`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_generate.py`:

```python
def test_generate_town_with_no_magic_prevalence_matches_previous_behavior():
    town_default = generate_town(("town", 1), target_population=3000)
    town_explicit = generate_town(("town", 1), target_population=3000, magic_prevalence=0.0)
    resident_key = lambda r: (r.id, r.household_id, r.ses, r.home_building_id, r.workplace_building_id, r.occupation)
    assert [resident_key(r) for r in town_default.residents] == [resident_key(r) for r in town_explicit.residents]


def test_generate_town_with_magic_prevalence_can_produce_arcane_shops():
    found = False
    for seed_index in range(20):
        town = generate_town(("town", seed_index), target_population=5000, magic_prevalence=0.8)
        all_types = [b.building_type for d in town.districts for b in d.buildings]
        if "arcane_shop" in all_types:
            found = True
            break
    assert found
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_generate.py -v -k magic_prevalence`
Expected: FAIL with `TypeError: generate_town() got an unexpected keyword argument 'magic_prevalence'`

- [ ] **Step 3: Modify the implementation**

Change `generate_town`'s signature and its `fill_district_buildings` call:

```python
def generate_town(
    seed, target_population: int,
    area_per_resident_multiplier: float = 1.0,
    density_multiplier: float = 1.0,
    rich_proportion: float = DEFAULT_RICH_PROPORTION,
    num_rivers: int = 0,
    has_coastline: bool = False,
    has_port: bool = False,
    magic_prevalence: float = 0.0,
) -> Town:
    bounds = compute_town_bounds(target_population, area_per_resident_multiplier)

    water_features = generate_water_features(seed, bounds, num_rivers=num_rivers, has_coastline=has_coastline)
    water_polygon = unary_union([f.polygon for f in water_features]) if water_features else None

    anchors = place_anchors(seed, target_population, bounds, water_polygon=water_polygon, has_port=has_port)
    districts = build_districts(anchors, bounds, water_polygon=water_polygon)

    for district in districts:
        next_building_id = district.id * BUILDING_ID_STRIDE
        buildings = fill_district_buildings(
            district, seed, next_building_id,
            target_population=target_population, density_multiplier=density_multiplier,
            magic_prevalence=magic_prevalence,
        )
        district.buildings = buildings
```

The rest of the function (from `households = generate_households(...)` onward) is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_generate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_shaper/generate.py tests/test_generate.py
git commit -m "feat: thread magic_prevalence through generate_town"
```

---

## Task 3: Magic goods in `GOODS_CATALOG` (`town_db/goods.py`)

**Files:**
- Modify: `town_db/goods.py`
- Test: `tests/test_db_goods_purchases.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: three new `GOODS_CATALOG` entries with `"category": "magic"`: `"healing potion"`, `"spell scroll"`, `"arcane reagents"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db_goods_purchases.py`:

```python
def test_goods_catalog_includes_magic_category():
    magic_goods = [g for g in GOODS_CATALOG if g["category"] == "magic"]
    assert {g["name"] for g in magic_goods} == {"healing potion", "spell scroll", "arcane reagents"}


def test_insert_goods_includes_magic_goods(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    ids = insert_goods(conn)
    assert "healing potion" in ids
    assert "spell scroll" in ids
    assert "arcane reagents" in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_goods_purchases.py -v -k magic`
Expected: FAIL — `test_goods_catalog_includes_magic_category` fails with an empty set not matching the expected 3 names; `test_insert_goods_includes_magic_goods` fails with `assert "healing potion" in ids` false.

- [ ] **Step 3: Modify the implementation**

In `town_db/goods.py`, append to `GOODS_CATALOG` (after `"jewelry"`, before the closing `]`):

```python
    {"name": "healing potion", "category": "magic", "typical_price": 4.0, "sv": 500},
    {"name": "spell scroll", "category": "magic", "typical_price": 8.0, "sv": 300},
    {"name": "arcane reagents", "category": "magic", "typical_price": 1.5, "sv": 700},
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_goods_purchases.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_db/goods.py tests/test_db_goods_purchases.py
git commit -m "feat: add magic-category goods to GOODS_CATALOG"
```

---

## Task 4: `generate_purchases` scopes magic goods to `arcane_shop` (`town_db/purchases.py`)

**Files:**
- Modify: `town_db/purchases.py`
- Test: `tests/test_db_goods_purchases.py` (append)

**Interfaces:**
- Consumes: `GOODS_CATALOG` entries with `"category": "magic"` (Task 3)
- Produces: `generate_purchases(seed, household_rows, resident_rows, goods_ids, shop_building_ids, year_start, weeks=52, magic_prevalence=0.0, arcane_shop_building_ids=None) -> List[Dict[str, Any]]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db_goods_purchases.py`:

```python
def test_magic_goods_excluded_when_magic_prevalence_is_zero():
    households = [_household(i) for i in range(1, 21)]
    residents = [_resident(i, i) for i in range(1, 21)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    magic_good_ids = {goods_ids["healing potion"], goods_ids["spell scroll"], goods_ids["arcane reagents"]}
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52,
        magic_prevalence=0.0, arcane_shop_building_ids=[99],
    )
    assert all(p["good_id"] not in magic_good_ids for p in purchases)


def test_magic_goods_excluded_when_no_arcane_shop_exists():
    households = [_household(i) for i in range(1, 21)]
    residents = [_resident(i, i) for i in range(1, 21)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    magic_good_ids = {goods_ids["healing potion"], goods_ids["spell scroll"], goods_ids["arcane reagents"]}
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52,
        magic_prevalence=0.9, arcane_shop_building_ids=[],
    )
    assert all(p["good_id"] not in magic_good_ids for p in purchases)


def test_magic_goods_purchased_and_shop_scoped_when_available():
    households = [_household(i) for i in range(1, 41)]
    residents = [_resident(i, i) for i in range(1, 41)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    magic_good_ids = {goods_ids["healing potion"], goods_ids["spell scroll"], goods_ids["arcane reagents"]}
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52,
        magic_prevalence=0.9, arcane_shop_building_ids=[99],
    )
    magic_purchases = [p for p in purchases if p["good_id"] in magic_good_ids]
    assert len(magic_purchases) > 0
    assert all(p["shop_building_id"] == 99 for p in magic_purchases)
    non_magic_purchases = [p for p in purchases if p["good_id"] not in magic_good_ids]
    assert all(p["shop_building_id"] == 10 for p in non_magic_purchases)


def test_generate_purchases_default_magic_params_match_previous_behavior():
    households = [_household(1)]
    residents = [_resident(1, 1)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    baseline = generate_purchases(("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52)
    explicit = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52,
        magic_prevalence=0.0, arcane_shop_building_ids=None,
    )
    assert baseline == explicit
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_goods_purchases.py -v -k "magic_goods or default_magic_params"`
Expected: FAIL with `TypeError: generate_purchases() got an unexpected keyword argument 'magic_prevalence'`

- [ ] **Step 3: Modify the implementation**

Replace `town_db/purchases.py`'s imports and `generate_purchases` function:

```python
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from town_shaper.seeding import rng_for

from town_db.goods import GOODS_CATALOG

SHOP_BUILDING_TYPES = {"shop", "tavern", "market_stall"}
WEEKLY_PURCHASE_COUNT_WEIGHTS = [40, 30, 20, 10]  # for 0, 1, 2, 3 purchases


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
    if not shop_building_ids or not goods_ids:
        return []

    arcane_shop_building_ids = arcane_shop_building_ids or []
    rng = rng_for(seed, "db", "purchases")

    sv_by_name = {g["name"]: g["sv"] for g in GOODS_CATALOG if g["name"] in goods_ids}
    price_by_name = {g["name"]: g["typical_price"] for g in GOODS_CATALOG if g["name"] in goods_ids}
    category_by_name = {g["name"]: g["category"] for g in GOODS_CATALOG if g["name"] in goods_ids}

    # Magic goods are only purchasable when both the town has some magic
    # prevalence AND an arcane_shop actually exists to sell them at -- see
    # the design decision in the spec.
    magic_available = magic_prevalence > 0 and len(arcane_shop_building_ids) > 0
    goods_names = [
        name for name in sv_by_name
        if category_by_name[name] != "magic" or magic_available
    ]
    # SV is the population needed to support one business of this type, so a
    # HIGHER sv means the good is bought more often (bread constantly, jewelry
    # rarely) -- weight directly by sv, not by its reciprocal. Magic goods are
    # additionally scaled by magic_prevalence so a low-magic town buys them
    # rarely even when an arcane_shop exists.
    good_weights = [
        float(sv_by_name[name]) * magic_prevalence if category_by_name[name] == "magic" else float(sv_by_name[name])
        for name in goods_names
    ]

    residents_by_household: Dict[int, List[Dict[str, Any]]] = {}
    for row in resident_rows:
        if row.get("age_bracket") == "adult":
            residents_by_household.setdefault(row["household_id"], []).append(row)

    purchases: List[Dict[str, Any]] = []
    for week in range(weeks):
        week_start = year_start + timedelta(weeks=week)
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
                if category_by_name[good_name] == "magic":
                    shop_id = rng.choice(arcane_shop_building_ids)
                else:
                    shop_id = rng.choice(shop_building_ids)
                # Expensive goods are bought one at a time; cheap staples in bulk.
                quantity = 1 if price_by_name[good_name] >= 1.0 else rng.randint(1, 5)
                unit_price = round(price_by_name[good_name] * rng.uniform(0.85, 1.15), 2)
                # Cap the within-week day so a buyer who dies mid-week never
                # shops after their own death date.
                max_day_offset = 6
                if buyer.get("death_date") is not None:
                    days_left = (date.fromisoformat(buyer["death_date"]) - week_start).days
                    max_day_offset = min(6, max(0, days_left))
                day_offset = rng.randint(0, max_day_offset)
                purchase_date = week_start + timedelta(days=day_offset)

                purchases.append({
                    "resident_db_id": buyer["db_id"],
                    "shop_building_id": shop_id,
                    "good_id": goods_ids[good_name],
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "total_price": round(unit_price * quantity, 2),
                    "purchase_date": purchase_date.isoformat(),
                })

    return purchases
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_goods_purchases.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_db/purchases.py tests/test_db_goods_purchases.py
git commit -m "feat: scope magic goods purchases to arcane_shop buildings"
```

---

## Task 5: DB schema — `residents.has_magical_talent` and `generation_parameters.magic_prevalence`

**Files:**
- Modify: `town_db/schema.py`
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Produces: `residents.has_magical_talent INTEGER NOT NULL DEFAULT 0`; `generation_parameters.magic_prevalence REAL NOT NULL`.

- [ ] **Step 1: Write the failing tests**

Replace `test_generation_parameters_accepts_a_row` in `tests/test_db_schema.py`:

```python
def test_generation_parameters_accepts_a_row(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute(
        "INSERT INTO generation_parameters (seed, target_population, area_per_resident_multiplier, "
        "density_multiplier, rich_proportion, num_rivers, has_coastline, has_port, magic_prevalence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("('town', 1)", 1500, 1.0, 1.0, 0.05, 1, 1, 1, 0.3),
    )
    conn.commit()
    row = conn.execute(
        "SELECT seed, target_population, area_per_resident_multiplier, density_multiplier, rich_proportion, "
        "num_rivers, has_coastline, has_port, magic_prevalence FROM generation_parameters"
    ).fetchone()
    assert row == ("('town', 1)", 1500, 1.0, 1.0, 0.05, 1, 1, 1, 0.3)
```

Append two new tests:

```python
def test_residents_has_magical_talent_defaults_to_zero(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.execute(
        "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, ses) "
        "VALUES (1, 'Ann', 'Smith', 'female', 'human', '1280-01-01', 'poor')"
    )
    row = conn.execute("SELECT has_magical_talent FROM residents").fetchone()
    assert row[0] == 0


def test_residents_has_magical_talent_accepts_a_row(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.execute(
        "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, ses, has_magical_talent) "
        "VALUES (1, 'Ann', 'Smith', 'female', 'human', '1280-01-01', 'poor', 1)"
    )
    row = conn.execute("SELECT has_magical_talent FROM residents").fetchone()
    assert row[0] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: FAIL — `test_generation_parameters_accepts_a_row` fails with `sqlite3.OperationalError: table generation_parameters has no column named magic_prevalence`; the two `has_magical_talent` tests fail with `sqlite3.OperationalError: table residents has no column named has_magical_talent` / `no such column: has_magical_talent`.

- [ ] **Step 3: Modify the implementation**

In `town_db/schema.py`, change the `residents` table definition from:

```sql
CREATE TABLE residents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id),
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    gender TEXT NOT NULL,
    race TEXT NOT NULL,
    birth_date TEXT NOT NULL,
    death_date TEXT,
    ses TEXT NOT NULL,
    is_noble INTEGER NOT NULL DEFAULT 0,
    home_building_id INTEGER REFERENCES buildings(id),
    workplace_building_id INTEGER REFERENCES buildings(id),
    occupation TEXT
);
```

to:

```sql
CREATE TABLE residents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id),
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    gender TEXT NOT NULL,
    race TEXT NOT NULL,
    birth_date TEXT NOT NULL,
    death_date TEXT,
    ses TEXT NOT NULL,
    is_noble INTEGER NOT NULL DEFAULT 0,
    has_magical_talent INTEGER NOT NULL DEFAULT 0,
    home_building_id INTEGER REFERENCES buildings(id),
    workplace_building_id INTEGER REFERENCES buildings(id),
    occupation TEXT
);
```

Change the `generation_parameters` table definition from:

```sql
CREATE TABLE generation_parameters (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    seed TEXT NOT NULL,
    target_population INTEGER NOT NULL,
    area_per_resident_multiplier REAL NOT NULL,
    density_multiplier REAL NOT NULL,
    rich_proportion REAL NOT NULL,
    num_rivers INTEGER NOT NULL,
    has_coastline INTEGER NOT NULL,
    has_port INTEGER NOT NULL
);
```

to:

```sql
CREATE TABLE generation_parameters (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    seed TEXT NOT NULL,
    target_population INTEGER NOT NULL,
    area_per_resident_multiplier REAL NOT NULL,
    density_multiplier REAL NOT NULL,
    rich_proportion REAL NOT NULL,
    num_rivers INTEGER NOT NULL,
    has_coastline INTEGER NOT NULL,
    has_port INTEGER NOT NULL,
    magic_prevalence REAL NOT NULL
);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_schema.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite — confirm the *only* failures are the 7 expected ones**

Run: `python -m pytest tests/ -q`
Expected: exactly these 7 tests FAIL, all in `tests/test_narrative_generate.py`, all with `sqlite3.IntegrityError: NOT NULL constraint failed: generation_parameters.magic_prevalence` — because `town_narrative/generate.py`'s `generate_town_from_parameters` (untouched until Task 8) still inserts into `generation_parameters` using the old 9-column list, and the table now requires a 10th (`magic_prevalence`) with no default:
- `test_generate_town_from_parameters_creates_a_populated_db`
- `test_generate_town_from_parameters_records_one_generation_parameters_row`
- `test_generate_town_from_parameters_passes_foreign_key_check`
- `test_generate_town_from_parameters_threads_density_multiplier_into_building_count`
- `test_generate_town_from_parameters_threads_rich_proportion_into_resident_ses`
- `test_generate_town_from_parameters_records_water_params`
- `test_generate_town_from_parameters_with_water_passes_foreign_key_check`

This is expected and intentional — Task 8 fixes `town_narrative/generate.py`'s INSERT, which is out of this task's file scope (`town_db/schema.py` only). `tests/test_db_generate.py` is unaffected: `generate_town_database` never writes to `generation_parameters` at all, and `residents.has_magical_talent`'s `DEFAULT 0` means existing `_insert_residents` calls (which don't mention that column) keep working unchanged until Task 7. If any test fails that is **not** in the list above, stop and treat it as a real regression — do not proceed to commit.

- [ ] **Step 6: Commit**

```bash
git add town_db/schema.py tests/test_db_schema.py
git commit -m "feat: add has_magical_talent and magic_prevalence columns"
```

---

## Task 6: `build_households_and_residents` tags `has_magical_talent` (`town_db/households.py`)

**Files:**
- Modify: `town_db/households.py`
- Test: `tests/test_db_households.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: `build_households_and_residents(town, seed, reference_date, race_weights=RACE_WEIGHTS, intermarriage_rate=DEFAULT_INTERMARRIAGE_RATE, magic_prevalence=0.0) -> Tuple[List[Dict], List[Dict]]` — each resident row gains `"has_magical_talent": bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db_households.py`:

```python
def test_default_magic_prevalence_produces_no_magical_talent():
    residents = [
        ResidentSlot(id=i, household_id=i, ses=SES.POOR, age_bracket="adult")
        for i in range(50)
    ]
    town = _make_town(residents)
    _, enriched = build_households_and_residents(town, ("town", 1), REFERENCE_DATE)
    assert all(r["has_magical_talent"] is False for r in enriched)


def test_high_magic_prevalence_tags_most_residents():
    residents = [
        ResidentSlot(id=i, household_id=i, ses=SES.POOR, age_bracket="adult")
        for i in range(200)
    ]
    town = _make_town(residents)
    _, enriched = build_households_and_residents(town, ("town", 1), REFERENCE_DATE, magic_prevalence=0.9)
    talented_count = sum(1 for r in enriched if r["has_magical_talent"])
    assert talented_count > 150


def test_magic_prevalence_zero_matches_default_behavior():
    residents = [
        ResidentSlot(id=i, household_id=i, ses=SES.POOR, age_bracket="adult")
        for i in range(30)
    ]
    town = _make_town(residents)
    _, baseline = build_households_and_residents(town, ("town", 1), REFERENCE_DATE)
    _, explicit = build_households_and_residents(town, ("town", 1), REFERENCE_DATE, magic_prevalence=0.0)
    key = lambda r: (r["household_id"], r["first_name"], r["race"], r["birth_date"], r["has_magical_talent"])
    assert [key(r) for r in baseline] == [key(r) for r in explicit]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_households.py -v -k magic`
Expected: FAIL — `test_default_magic_prevalence_produces_no_magical_talent` fails with `KeyError: 'has_magical_talent'`; `test_high_magic_prevalence_tags_most_residents` fails with `TypeError: build_households_and_residents() got an unexpected keyword argument 'magic_prevalence'`.

- [ ] **Step 3: Modify the implementation**

In `town_db/households.py`, change `build_households_and_residents`'s signature:

```python
def build_households_and_residents(
    town,
    seed,
    reference_date: date,
    race_weights: Dict[str, float] = RACE_WEIGHTS,
    intermarriage_rate: float = DEFAULT_INTERMARRIAGE_RATE,
    magic_prevalence: float = 0.0,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
```

Add `"has_magical_talent": False` to the `resident_rows.append({...})` dict, right after `"is_noble": False,`:

```python
            resident_rows.append({
                "town_shaper_id": member.id,
                "household_id": household_id,
                "first_name": first_name,
                "last_name": surname,
                "gender": gender,
                "race": race,
                "birth_date": birth_date.isoformat(),
                "death_date": None,
                "ses": member.ses.value,
                "is_noble": False,
                "has_magical_talent": False,
                "home_building_id": member.home_building_id,
                "workplace_building_id": member.workplace_building_id,
                "occupation": member.occupation,
                "age_bracket": member.age_bracket,
            })
```

Change the end of `build_households_and_residents` from:

```python
    _tag_nobility(rng, resident_rows, town.target_population)

    return household_rows, resident_rows
```

to:

```python
    _tag_nobility(rng, resident_rows, town.target_population)
    _tag_magical_talent(rng, resident_rows, magic_prevalence)

    return household_rows, resident_rows
```

Add a new function after `_tag_nobility`:

```python
def _tag_magical_talent(rng, resident_rows: List[Dict[str, Any]], magic_prevalence: float) -> None:
    for row in resident_rows:
        row["has_magical_talent"] = rng.random() < magic_prevalence
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_households.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add town_db/households.py tests/test_db_households.py
git commit -m "feat: tag residents with has_magical_talent independent of occupation"
```

---

## Task 7: `generate_town_database` threads `magic_prevalence` end-to-end (`town_db/generate.py`)

**Files:**
- Modify: `town_db/generate.py`
- Test: `tests/test_db_generate.py` (append)

**Interfaces:**
- Consumes: `generate_town(..., magic_prevalence=0.0)` (Task 2), `build_households_and_residents(..., magic_prevalence=0.0)` (Task 6), `generate_purchases(..., magic_prevalence=0.0, arcane_shop_building_ids=None)` (Task 4), `residents.has_magical_talent` column (Task 5)
- Produces: `generate_town_database(..., magic_prevalence: float = 0.0) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db_generate.py`:

```python
def test_generate_town_database_default_magic_prevalence_matches_previous_behavior(tmp_path):
    db_path_a = str(tmp_path / "a.db")
    db_path_b = str(tmp_path / "b.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_a)
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_b, magic_prevalence=0.0)

    conn_a = sqlite3.connect(db_path_a)
    conn_b = sqlite3.connect(db_path_b)
    for table in ["residents", "buildings", "purchases"]:
        rows_a = conn_a.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        rows_b = conn_b.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        assert rows_a == rows_b


def test_generate_town_database_high_magic_prevalence_produces_talented_residents_and_arcane_purchases(tmp_path):
    found_arcane_purchase = False
    for seed_index in range(5):
        db_path = str(tmp_path / f"town_{seed_index}.db")
        generate_town_database(
            ("town", seed_index), target_population=5000, db_path=db_path, magic_prevalence=0.9,
        )
        conn = sqlite3.connect(db_path)
        talented_count = conn.execute("SELECT COUNT(*) FROM residents WHERE has_magical_talent = 1").fetchone()[0]
        assert talented_count > 0

        magic_purchase_count = conn.execute(
            "SELECT COUNT(*) FROM purchases p JOIN goods g ON g.id = p.good_id WHERE g.category = 'magic'"
        ).fetchone()[0]
        if magic_purchase_count > 0:
            found_arcane_purchase = True

    assert found_arcane_purchase


def test_generate_town_database_with_magic_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(
        ("town", 1), target_population=5000, db_path=db_path, magic_prevalence=0.9,
    )
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_generate.py -v -k magic`
Expected: FAIL with `TypeError: generate_town_database() got an unexpected keyword argument 'magic_prevalence'`

- [ ] **Step 3: Modify the implementation**

Change `generate_town_database`'s signature and its `generate_town` call from:

```python
def generate_town_database(
    seed,
    target_population: int,
    db_path: str,
    year_start: date = DEFAULT_YEAR_START,
    race_weights: Dict[str, float] = RACE_WEIGHTS,
    intermarriage_rate: float = DEFAULT_INTERMARRIAGE_RATE,
    birth_rate: float = DEFAULT_BIRTH_RATE,
    death_rate_by_age: Dict[str, float] = DEFAULT_DEATH_RATE_BY_AGE,
    area_per_resident_multiplier: float = 1.0,
    density_multiplier: float = 1.0,
    rich_proportion: float = DEFAULT_RICH_PROPORTION,
    num_rivers: int = 0,
    has_coastline: bool = False,
    has_port: bool = False,
) -> None:
    town = generate_town(
        seed, target_population,
        area_per_resident_multiplier=area_per_resident_multiplier,
        density_multiplier=density_multiplier,
        rich_proportion=rich_proportion,
        num_rivers=num_rivers,
        has_coastline=has_coastline,
        has_port=has_port,
    )
```

to:

```python
def generate_town_database(
    seed,
    target_population: int,
    db_path: str,
    year_start: date = DEFAULT_YEAR_START,
    race_weights: Dict[str, float] = RACE_WEIGHTS,
    intermarriage_rate: float = DEFAULT_INTERMARRIAGE_RATE,
    birth_rate: float = DEFAULT_BIRTH_RATE,
    death_rate_by_age: Dict[str, float] = DEFAULT_DEATH_RATE_BY_AGE,
    area_per_resident_multiplier: float = 1.0,
    density_multiplier: float = 1.0,
    rich_proportion: float = DEFAULT_RICH_PROPORTION,
    num_rivers: int = 0,
    has_coastline: bool = False,
    has_port: bool = False,
    magic_prevalence: float = 0.0,
) -> None:
    town = generate_town(
        seed, target_population,
        area_per_resident_multiplier=area_per_resident_multiplier,
        density_multiplier=density_multiplier,
        rich_proportion=rich_proportion,
        num_rivers=num_rivers,
        has_coastline=has_coastline,
        has_port=has_port,
        magic_prevalence=magic_prevalence,
    )
```

Change the `build_households_and_residents` call from:

```python
    household_rows, resident_rows = build_households_and_residents(
        town, seed, year_start, race_weights, intermarriage_rate,
    )
```

to:

```python
    household_rows, resident_rows = build_households_and_residents(
        town, seed, year_start, race_weights, intermarriage_rate, magic_prevalence=magic_prevalence,
    )
```

Change the `shop_building_ids`/`generate_purchases` block from:

```python
    shop_building_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type in SHOP_BUILDING_TYPES
    ]
    purchases = generate_purchases(
        seed, household_rows, resident_rows, goods_ids, shop_building_ids, year_start,
    )
```

to:

```python
    shop_building_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type in SHOP_BUILDING_TYPES
    ]
    arcane_shop_building_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type == "arcane_shop"
    ]
    purchases = generate_purchases(
        seed, household_rows, resident_rows, goods_ids, shop_building_ids, year_start,
        magic_prevalence=magic_prevalence, arcane_shop_building_ids=arcane_shop_building_ids,
    )
```

Change `_insert_residents` from:

```python
def _insert_residents(conn: sqlite3.Connection, resident_rows: List[Dict[str, Any]]) -> None:
    for row in resident_rows:
        cursor = conn.execute(
            "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, death_date, "
            "ses, is_noble, home_building_id, workplace_building_id, occupation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["household_id"], row["first_name"], row["last_name"], row["gender"], row["race"],
             row["birth_date"], row["death_date"], row["ses"], int(row["is_noble"]),
             row["home_building_id"], row["workplace_building_id"], row["occupation"]),
        )
        row["db_id"] = cursor.lastrowid
```

to:

```python
def _insert_residents(conn: sqlite3.Connection, resident_rows: List[Dict[str, Any]]) -> None:
    for row in resident_rows:
        cursor = conn.execute(
            "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, death_date, "
            "ses, is_noble, has_magical_talent, home_building_id, workplace_building_id, occupation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["household_id"], row["first_name"], row["last_name"], row["gender"], row["race"],
             row["birth_date"], row["death_date"], row["ses"], int(row["is_noble"]),
             int(row.get("has_magical_talent", False)),
             row["home_building_id"], row["workplace_building_id"], row["occupation"]),
        )
        row["db_id"] = cursor.lastrowid
```

(`_insert_residents` is also called for `new_resident_rows` from `generate_births_and_deaths` — those rows don't set `"has_magical_talent"`, so `row.get("has_magical_talent", False)` correctly defaults newborns to no talent rather than raising `KeyError`. Out of scope for this slice to roll talent for babies born during the simulated year.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_generate.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: PASS for every test except the same 7 `tests/test_narrative_generate.py` tests listed in Task 5's Step 5 (still failing with the same `NOT NULL constraint failed: generation_parameters.magic_prevalence` — `town_narrative/generate.py` is untouched until Task 8). Confirm no *other* test fails before committing — any new failure outside that list of 7 is a real regression from this task's changes.

- [ ] **Step 6: Commit**

```bash
git add town_db/generate.py tests/test_db_generate.py
git commit -m "feat: thread magic_prevalence through generate_town_database"
```

---

## Task 8: `TownParameters` gains `magic_prevalence`; `generate_town_from_parameters` wiring

**Files:**
- Modify: `town_narrative/parameters.py`
- Modify: `town_narrative/generate.py`
- Test: `tests/test_narrative_parameters.py` (append)
- Test: `tests/test_narrative_generate.py` (append)

**Interfaces:**
- Consumes: `generate_town_database(..., magic_prevalence=0.0)` (Task 7)
- Produces: `TownParameters` gains `magic_prevalence: float = 0.0` — `__post_init__` raises `ValueError` for values outside `[0.0, 1.0]`. `generate_town_from_parameters` passes it through and records it in `generation_parameters`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_narrative_parameters.py`:

```python
def test_magic_prevalence_default_is_zero():
    params = TownParameters(seed="town-1", target_population=1000)
    assert params.magic_prevalence == 0.0


def test_magic_prevalence_out_of_range_raises():
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, magic_prevalence=1.5)
    with pytest.raises(ValueError):
        TownParameters(seed="town-1", target_population=1000, magic_prevalence=-0.1)


def test_magic_prevalence_boundary_values_are_valid():
    TownParameters(seed="town-1", target_population=1000, magic_prevalence=0.0)
    TownParameters(seed="town-1", target_population=1000, magic_prevalence=1.0)
```

Append to `tests/test_narrative_generate.py`:

```python
def test_generate_town_from_parameters_records_magic_prevalence(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(seed=("town", 1), target_population=1500, magic_prevalence=0.4)
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT magic_prevalence FROM generation_parameters").fetchone()
    assert row == (0.4,)


def test_generate_town_from_parameters_with_magic_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    params = TownParameters(seed=("town", 1), target_population=5000, magic_prevalence=0.8)
    generate_town_from_parameters(params, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_narrative_parameters.py tests/test_narrative_generate.py -v -k magic`
Expected: FAIL with `TypeError: TownParameters.__init__() got an unexpected keyword argument 'magic_prevalence'`

- [ ] **Step 3: Update `town_narrative/parameters.py`**

Replace the whole file:

```python
from dataclasses import dataclass
from typing import Any

from town_shaper.assignment import DEFAULT_RICH_PROPORTION


@dataclass(frozen=True)
class TownParameters:
    seed: Any
    target_population: int
    area_per_resident_multiplier: float = 1.0
    density_multiplier: float = 1.0
    rich_proportion: float = DEFAULT_RICH_PROPORTION
    num_rivers: int = 0
    has_coastline: bool = False
    has_port: bool = False
    magic_prevalence: float = 0.0

    def __post_init__(self) -> None:
        if self.target_population <= 0:
            raise ValueError("target_population must be positive")
        if self.area_per_resident_multiplier <= 0:
            raise ValueError("area_per_resident_multiplier must be positive")
        if self.density_multiplier <= 0:
            raise ValueError("density_multiplier must be positive")
        if not (0.0 <= self.rich_proportion <= 1.0):
            raise ValueError("rich_proportion must be between 0.0 and 1.0")
        if self.num_rivers < 0:
            raise ValueError("num_rivers must be non-negative")
        if self.has_port and not (self.num_rivers > 0 or self.has_coastline):
            raise ValueError("has_port requires num_rivers > 0 or has_coastline to be True")
        if not (0.0 <= self.magic_prevalence <= 1.0):
            raise ValueError("magic_prevalence must be between 0.0 and 1.0")
```

- [ ] **Step 4: Update `town_narrative/generate.py`**

Replace the whole file:

```python
from town_db.generate import generate_town_database
from town_db.schema import connect

from town_narrative.parameters import TownParameters


def generate_town_from_parameters(params: TownParameters, db_path: str) -> None:
    generate_town_database(
        params.seed,
        params.target_population,
        db_path,
        area_per_resident_multiplier=params.area_per_resident_multiplier,
        density_multiplier=params.density_multiplier,
        rich_proportion=params.rich_proportion,
        num_rivers=params.num_rivers,
        has_coastline=params.has_coastline,
        has_port=params.has_port,
        magic_prevalence=params.magic_prevalence,
    )

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO generation_parameters (id, seed, target_population, area_per_resident_multiplier, "
        "density_multiplier, rich_proportion, num_rivers, has_coastline, has_port, magic_prevalence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, str(params.seed), params.target_population, params.area_per_resident_multiplier,
         params.density_multiplier, params.rich_proportion, params.num_rivers,
         int(params.has_coastline), int(params.has_port), params.magic_prevalence),
    )
    conn.commit()
    conn.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_narrative_parameters.py tests/test_narrative_generate.py -v`
Expected: PASS

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: PASS for every test

- [ ] **Step 7: Commit**

```bash
git add town_narrative/parameters.py town_narrative/generate.py tests/test_narrative_parameters.py tests/test_narrative_generate.py
git commit -m "feat: add magic_prevalence to TownParameters"
```

---

## Task 9: Narrative-mapping doc and skill update

**Files:**
- Modify: `docs/narrative-town-parameters.md`
- Modify: `.claude/skills/generate-town-from-narrative/SKILL.md`

**Interfaces:**
- Consumes: `TownParameters` (Task 8)
- Produces: updated agent-neutral reference documentation and Claude Code skill wrapper.

- [ ] **Step 1: Update the reference doc**

In `docs/narrative-town-parameters.md`, after the `has_port` bullet in the `## Fields` section, insert:

```markdown
- **`magic_prevalence`** (default `0.0`) — how prevalent magic is in the
  town, as a fraction from `0.0` (none) to `1.0` (saturated). Drives three
  independent things: an `arcane_shop` (a MERCHANT-zone building, staffed
  by a mage + apprentices) becomes more likely to appear as this rises;
  magic-category goods (healing potions, spell scrolls, arcane reagents)
  become purchasable, but only where an `arcane_shop` actually exists;
  and the fraction of residents with `has_magical_talent` (a latent trait,
  independent of occupation — not every mage is guaranteed to roll it,
  and untrained townsfolk can have it too) tracks this value directly.
```

Add rows to the `## Narrative language → value` table (after the `has_port` row, before the closing paragraph):

```markdown
| "arcane", "wizards on every corner", "high magic" | `magic_prevalence` | 0.3 – 0.6 |
| "no magic", "mundane", "magic is rare/forbidden here" | `magic_prevalence` | 0.0 (default) |
| (no magic cue) | `magic_prevalence` | 0.0 (default) |
```

- [ ] **Step 2: Update the skill file**

In `.claude/skills/generate-town-from-narrative/SKILL.md`, change step 2 of the procedure from:

```markdown
2. **Map narrative language onto `TownParameters` fields** using
   `docs/narrative-town-parameters.md` as the reference table. Fields
   available today: `seed`, `target_population`,
   `area_per_resident_multiplier`, `density_multiplier`,
   `rich_proportion`, `num_rivers`, `has_coastline`, `has_port`.
```

to:

```markdown
2. **Map narrative language onto `TownParameters` fields** using
   `docs/narrative-town-parameters.md` as the reference table. Fields
   available today: `seed`, `target_population`,
   `area_per_resident_multiplier`, `density_multiplier`,
   `rich_proportion`, `num_rivers`, `has_coastline`, `has_port`,
   `magic_prevalence`.
```

Change the example `TownParameters(...)` construction in step 5 from:

```python
   params = TownParameters(
       seed=<a stable seed derived from the campaign/town name>,
       target_population=<int>,
       area_per_resident_multiplier=<float>,
       density_multiplier=<float>,
       rich_proportion=<float>,
       num_rivers=<int>,
       has_coastline=<bool>,
       has_port=<bool>,
   )
```

to:

```python
   params = TownParameters(
       seed=<a stable seed derived from the campaign/town name>,
       target_population=<int>,
       area_per_resident_multiplier=<float>,
       density_multiplier=<float>,
       rich_proportion=<float>,
       num_rivers=<int>,
       has_coastline=<bool>,
       has_port=<bool>,
       magic_prevalence=<float>,
   )
```

- [ ] **Step 3: Verify both files are internally consistent**

Run: `python -c "import pathlib; text = pathlib.Path('docs/narrative-town-parameters.md').read_text(); assert 'magic_prevalence' in text and 'arcane_shop' in text; skill = pathlib.Path('.claude/skills/generate-town-from-narrative/SKILL.md').read_text(); assert 'magic_prevalence' in skill; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Run the whole suite one last time**

Run: `python -m pytest tests/ -q`
Expected: PASS for every test

- [ ] **Step 5: Commit**

```bash
git add docs/narrative-town-parameters.md .claude/skills/generate-town-from-narrative/SKILL.md
git commit -m "docs: document magic_prevalence narrative-mapping fields"
```
