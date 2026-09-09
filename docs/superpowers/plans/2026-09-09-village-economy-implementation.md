# Village Economy & Growth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give village-scale towns (`target_population <= 1000`, settlemaker's village engine) the same simulation depth as burg-mode towns — real businesses to work at and buy from, and real vacant housing for household formation to grow into.

**Architecture:** A new `_curate_village_economy(buildings, population, seed)` helper in `settlemaker_bridge/parse_geojson.py` reclassifies a population-scaled subset of a village's houses into `tavern`/`shop` (reusing the existing `JOB_VACANCIES_BY_BUILDING_TYPE`/`BUILDING_NAME_POOLS`/`BUILDING_HOME_CAPACITY` tables) and flags a few more as `reserved_vacant` — a new `Building` field that a one-line change to `town_shaper.assignment.assign_residents` respects, keeping those houses empty at initial generation without touching persistence, `household_formation.py`, or any other downstream consumer.

**Tech Stack:** Python (existing stack: pytest, no new dependencies).

## Global Constraints

- Every random draw stays on the `rng_for(seed, *path_parts)` backbone — no new source of randomness (per `docs/superpowers/specs/2026-09-09-village-economy-design.md`'s Determinism & Testing section, and this project's existing convention throughout).
- `Building.reserved_vacant` is generation-time-only — never persisted to the database, never read by `household_formation.py` or any other `town_db` module (per the design's Data Model section: "once initial assignment has run, a reserved building is indistinguishable from any other building with spare capacity").
- No changes to `VILLAGE_POP_CEILING`, the burg-mode code path, or any existing table (`JOB_VACANCIES_BY_BUILDING_TYPE`, `BUILDING_NAME_POOLS`, `BUILDING_HOME_CAPACITY`) — this plan only reuses them for `tavern`/`shop` in the village path.
- Full test suite (`~/venvs/townshape/bin/python -m pytest tests/ -q`) stays the acceptance bar after every task. This environment has shown a background-task memory watchdog that can kill a single long-running backgrounded pytest invocation partway through — if that happens, re-run in the foreground (not backgrounded), or split `tests/*.py` into a few file-group chunks and run each in the foreground; neither is a code problem.

---

## Task 1: `_curate_village_economy` — business reclassification and reserved-vacancy tagging

**Files:**
- Modify: `town_shaper/models.py` (add `Building.reserved_vacant`)
- Modify: `settlemaker_bridge/parse_geojson.py` (add the three tier constants and `_curate_village_economy`)
- Test: `tests/test_settlemaker_parse_geojson.py`

**Interfaces:**
- Produces: `Building.reserved_vacant: bool = False` (new field, `town_shaper/models.py`).
- Produces: `_curate_village_economy(buildings: List[Building], population: int, seed: Any) -> None` (`settlemaker_bridge/parse_geojson.py`) — mutates a subset of `buildings` in place, returns nothing.

- [ ] **Step 1: Add `Building.reserved_vacant`**

In `town_shaper/models.py`, add one field to the `Building` dataclass, after `footprint`:

```python
    footprint: Optional[List[Tuple[float, float]]] = None
    reserved_vacant: bool = False
```

- [ ] **Step 2: Write the failing tests for `_curate_village_economy`**

Append to `tests/test_settlemaker_parse_geojson.py`:

```python
from settlemaker_bridge.parse_geojson import _curate_village_economy
from town_shaper.models import Building, ZoneType


def _make_houses(n):
    return [
        Building(
            id=i, district_id=0, district_zone_type=ZoneType.POOR_RESIDENTIAL,
            x=0.0, y=0.0, building_type="residence", capacity=6,
        )
        for i in range(n)
    ]


def test_curate_village_economy_below_floor_reclassifies_nothing():
    houses = _make_houses(20)
    _curate_village_economy(houses, population=74, seed="s")
    assert all(b.building_type == "residence" for b in houses)
    assert all(not b.reserved_vacant for b in houses)


def test_curate_village_economy_tavern_tier_reclassifies_exactly_one_tavern():
    houses = _make_houses(20)
    _curate_village_economy(houses, population=150, seed="s")
    types = [b.building_type for b in houses]
    assert types.count("tavern") == 1
    assert types.count("shop") == 0
    assert types.count("residence") == 19


def test_curate_village_economy_shop_tier_reclassifies_tavern_and_shop():
    houses = _make_houses(75)
    _curate_village_economy(houses, population=300, seed="s")
    types = [b.building_type for b in houses]
    assert types.count("tavern") == 1
    assert types.count("shop") == 1
    assert types.count("residence") == 73


def test_curate_village_economy_reclassified_building_has_zero_capacity_and_real_vacancies():
    houses = _make_houses(20)
    _curate_village_economy(houses, population=150, seed="s")
    tavern = next(b for b in houses if b.building_type == "tavern")
    assert tavern.capacity == 0
    assert sorted(v.occupation for v in tavern.vacancies) == ["barkeep", "tavern_staff", "tavern_staff"]
    assert tavern.name is not None


def test_curate_village_economy_reserved_count_matches_population_over_100_floor_1():
    houses = _make_houses(20)
    _curate_village_economy(houses, population=150, seed="s")
    assert sum(1 for b in houses if b.reserved_vacant) == 1

    houses = _make_houses(250)
    _curate_village_economy(houses, population=800, seed="s")
    assert sum(1 for b in houses if b.reserved_vacant) == 8


def test_curate_village_economy_reserved_buildings_are_not_also_reclassified():
    houses = _make_houses(20)
    _curate_village_economy(houses, population=150, seed="s")
    reserved = [b for b in houses if b.reserved_vacant]
    assert all(b.building_type == "residence" for b in reserved)
    assert all(b.capacity == 6 for b in reserved)


def test_curate_village_economy_is_deterministic_for_same_seed():
    houses1 = _make_houses(75)
    houses2 = _make_houses(75)
    _curate_village_economy(houses1, population=300, seed="fixed-seed")
    _curate_village_economy(houses2, population=300, seed="fixed-seed")
    assert [(b.id, b.building_type, b.reserved_vacant) for b in houses1] == \
           [(b.id, b.building_type, b.reserved_vacant) for b in houses2]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_settlemaker_parse_geojson.py -k curate_village_economy -v`
Expected: FAIL — `ImportError: cannot import name '_curate_village_economy'`

- [ ] **Step 4: Implement `_curate_village_economy`**

In `settlemaker_bridge/parse_geojson.py`, add after the `VILLAGE_BUILDING_TYPE` constant (and before `def _centroid`):

```python
# Population tiers a village's business/vacancy curation activates over --
# see docs/superpowers/specs/2026-09-09-village-economy-design.md. Starting
# points, not calibrated against real feedback yet -- easy to retune later,
# nothing else depends on their exact values.
VILLAGE_BUSINESS_MIN_POPULATION = 75   # below this, a village is houses only
VILLAGE_SHOP_MIN_POPULATION = 300      # below this, at most a tavern
VILLAGE_RESERVED_VACANCY_DIVISOR = 100 # ~1 reserved house per this many residents


def _curate_village_economy(buildings: List[Building], population: int, seed: Any) -> None:
    """Mutates a subset of `buildings` in place: reclassifies a few houses
    into businesses, reserves a few more as initially-vacant (so
    town_shaper.assignment.assign_residents' reserved_vacant filter leaves
    them empty for household_formation to grow into later). No-op below
    VILLAGE_BUSINESS_MIN_POPULATION -- a small enough village is just
    houses, no businesses and no reserved slack either."""
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

- [ ] **Step 5: Run the tests to verify they pass**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_settlemaker_parse_geojson.py -k curate_village_economy -v`
Expected: 7 passed

- [ ] **Step 6: Run the full `test_settlemaker_parse_geojson.py` file**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_settlemaker_parse_geojson.py -v`
Expected: all pass (the 19 existing tests plus these 7 new ones) — `_curate_village_economy` isn't wired into `_parse_village_geojson` yet (that's Task 2), so nothing existing should be affected.

- [ ] **Step 7: Commit**

```bash
git add town_shaper/models.py settlemaker_bridge/parse_geojson.py tests/test_settlemaker_parse_geojson.py
git commit -m "feat: add village business reclassification and reserved-vacancy tagging"
```

---

## Task 2: Wire `_curate_village_economy` into the village parser, thread `target_population` through

**Files:**
- Modify: `settlemaker_bridge/parse_geojson.py`
- Modify: `settlemaker_bridge/pipeline.py`
- Test: `tests/test_settlemaker_parse_geojson.py`

**Interfaces:**
- Consumes: `_curate_village_economy` (Task 1).
- Produces: `parse_settlemaker_geojson(geojson, seed, target_population: int = 0) -> (List[District], List[Building])` — new third parameter, default `0` (below `VILLAGE_BUSINESS_MIN_POPULATION`, so every existing call site that doesn't pass it keeps its current no-curation behavior unchanged). `_parse_village_geojson` gets the same new parameter.

`target_population` defaults to `0` rather than being required: `tests/test_settlemaker_parse_geojson.py`'s existing 19 burg-mode tests and this session's earlier village tests all call `parse_settlemaker_geojson(geojson, seed="s")` with no population argument, and their fixtures are hand-built with specific building counts that a real curation pass would silently perturb. A default of `0` keeps every one of those tests passing unchanged, while `settlemaker_bridge/pipeline.py` (the only real production call site) passes the actual value it already has in scope.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_settlemaker_parse_geojson.py`:

```python
def test_parse_village_geojson_wires_target_population_into_curation():
    features = [_village_building(SQUARE, 6)] + [
        _village_building([[x, 0.0], [x + 10, 0.0], [x + 10, 10.0], [x, 10.0], [x, 0.0]], 6)
        for x in range(20, 20 * 20, 20)  # 19 more houses, 20 total
    ]
    geojson = _village_geojson(features)
    _districts, buildings = parse_settlemaker_geojson(geojson, seed="s", target_population=150)
    assert sum(1 for b in buildings if b.building_type == "tavern") == 1


def test_parse_village_geojson_default_target_population_curates_nothing():
    geojson = _village_geojson([_village_building(SQUARE, 6)])
    _districts, buildings = parse_settlemaker_geojson(geojson, seed="s")
    assert buildings[0].building_type == "residence"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_settlemaker_parse_geojson.py -k "wires_target_population or default_target_population" -v`
Expected: FAIL — `TypeError: parse_settlemaker_geojson() got an unexpected keyword argument 'target_population'`

- [ ] **Step 3: Thread `target_population` through and call `_curate_village_economy`**

In `settlemaker_bridge/parse_geojson.py`, change `_parse_village_geojson`'s signature and add the curation call before its `return`:

```python
def _parse_village_geojson(
    geojson: Dict[str, Any], seed: Any, target_population: int = 0,
) -> Tuple[List[District], List[Building]]:
```

(docstring unchanged) ... and just before `return [district], buildings` at the end of the function:

```python
    _curate_village_economy(buildings, target_population, seed)
    return [district], buildings
```

Change `parse_settlemaker_geojson`'s signature and its call into `_parse_village_geojson`:

```python
def parse_settlemaker_geojson(
    geojson: Dict[str, Any], seed: Any, target_population: int = 0,
) -> Tuple[List[District], List[Building]]:
```

```python
    if geojson.get("metadata", {}).get("settlement_generation_version") == "village":
        return _parse_village_geojson(geojson, seed, target_population)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_settlemaker_parse_geojson.py -v`
Expected: all pass (28 tests: 19 original + 7 from Task 1 + 2 from this task).

- [ ] **Step 5: Wire the real call site**

In `settlemaker_bridge/pipeline.py`, change:

```python
    districts, buildings = parse_settlemaker_geojson(result["geojson"], seed)
```

to:

```python
    districts, buildings = parse_settlemaker_geojson(result["geojson"], seed, target_population)
```

- [ ] **Step 6: Run the bridge integration test**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_settlemaker_bridge_integration.py -v`
Expected: 2 passed (unaffected — both use population 3000, burg mode, where `target_population` reaches `parse_settlemaker_geojson` but the burg branch never reads it).

- [ ] **Step 7: Commit**

```bash
git add settlemaker_bridge/parse_geojson.py settlemaker_bridge/pipeline.py tests/test_settlemaker_parse_geojson.py
git commit -m "feat: thread target_population into the village parser, wire up business curation"
```

---

## Task 3: `assign_residents` respects `reserved_vacant`

**Files:**
- Modify: `town_shaper/assignment.py`
- Test: `tests/test_assignment.py`

**Interfaces:**
- Consumes: `Building.reserved_vacant` (Task 1).
- Produces: `assign_residents` unchanged in signature — only its internal `residential_buildings` filter changes.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_assignment.py`:

```python
def test_assign_residents_never_fills_a_reserved_vacant_building():
    seed = ("town", 1)
    districts, households = _build_town_pieces(seed, target_population=200)
    # Reserve every building in the poor district but one -- if the reserved
    # ones ever got filled, this would force overflow into the rich district
    # in a way the next assertion catches.
    poor_district = next(d for d in districts if d.zone_type == ZoneType.POOR_RESIDENTIAL)
    for building in poor_district.buildings[1:]:
        building.reserved_vacant = True

    assign_residents(seed, households, districts)

    for building in poor_district.buildings[1:]:
        assert building.resident_ids == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_assignment.py::test_assign_residents_never_fills_a_reserved_vacant_building -v`
Expected: FAIL — `AssertionError` (reserved buildings get filled anyway, since `assign_residents` doesn't check the flag yet).

- [ ] **Step 3: Implement the filter change**

In `town_shaper/assignment.py`, change:

```python
    residential_buildings = sorted(
        (b for d in districts for b in d.buildings if b.capacity > 0),
        key=lambda b: b.id,
    )
```

to:

```python
    residential_buildings = sorted(
        (b for d in districts for b in d.buildings if b.capacity > 0 and not b.reserved_vacant),
        key=lambda b: b.id,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_assignment.py -v`
Expected: all 12 tests pass (11 existing + this new one).

- [ ] **Step 5: Commit**

```bash
git add town_shaper/assignment.py tests/test_assignment.py
git commit -m "fix: assign_residents skips reserved_vacant buildings during initial placement"
```

---

## Task 4: End-to-end integration test — a village with a real economy and real growth

**Files:**
- Test: `tests/test_db_simulation_integration.py`

**Interfaces:**
- Consumes: `generate_town_database` (`town_db.generate`), `advance_town` (`town_db.simulation`) — both unchanged by this plan, exercised here as full black-box verification that Tasks 1-3 actually fix the two behaviors `docs/superpowers/specs/2026-09-09-village-economy-design.md` exists for.

- [ ] **Step 1: Write the test**

Append to `tests/test_db_simulation_integration.py`:

```python
def test_village_scale_town_produces_purchases_and_grows_a_new_household(tmp_path):
    # The regression this plan exists to fix: before it, a village-scale town
    # (population <= settlemaker's VILLAGE_POP_CEILING of 1000) had zero
    # purchases forever (no shops exist in raw village output) and could
    # never form a new household (housing had zero vacancy slack). Population
    # 500 clears both curation floors (75 for a tavern, 300 for a shop too).
    db_path = str(tmp_path / "village.db")
    generate_town_database(("village-economy-test", 1), target_population=500, db_path=db_path)

    conn = sqlite3.connect(db_path)
    building_types = {row[0] for row in conn.execute("SELECT DISTINCT building_type FROM buildings")}
    assert "tavern" in building_types
    assert "shop" in building_types
    max_original_household_id = conn.execute("SELECT MAX(id) FROM households").fetchone()[0]
    conn.close()

    advance_town(db_path, seed=("village-economy-test", 1), years=5)

    conn = sqlite3.connect(db_path)
    purchase_count = conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0]
    assert purchase_count > 0, "expected at least one purchase in a village with a tavern and a shop"

    new_households = conn.execute(
        "SELECT id FROM households WHERE id > ?", (max_original_household_id,)
    ).fetchall()
    assert new_households, "expected at least one new household to have formed over 5 years"
```

- [ ] **Step 2: Run it**

Run: `~/venvs/townshape/bin/python -m pytest tests/test_db_simulation_integration.py::test_village_scale_town_produces_purchases_and_grows_a_new_household -v`
Expected: PASS. (If it fails on the purchases assertion, check that population 500 is actually landing in the village engine and that the tavern/shop reclassification ran — add a print of `building_types` and re-run with `-s`; if it fails on the households assertion, this is a probabilistic draw over 5 years the same way the original town-scale version of this test is — re-run once before assuming a real regression, per this project's existing convention for household-formation tests.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_db_simulation_integration.py
git commit -m "test: add end-to-end village economy and growth integration test"
```

---

## Task 5: Full suite verification and wrap-up

**Files:** None (verification only).

- [ ] **Step 1: Run the full suite**

Run: `~/venvs/townshape/bin/python -m pytest tests/ -q`

If a background-task memory watchdog kills this run partway through (see Global Constraints), split into file-group chunks and run each in the foreground instead:

```bash
python3 -c "
import glob
files = sorted(glob.glob('tests/*.py'))
files = [f for f in files if not f.endswith('town_viewer_fixtures.py')]
n = 5
for i, chunk in enumerate([files[i::n] for i in range(n)]):
    open(f'/tmp/chunk_{i}.txt', 'w').write(' '.join(chunk))
"
# then, for i in 0 1 2 3 4:
~/venvs/townshape/bin/python -m pytest $(cat /tmp/chunk_0.txt) -q
```

Expected: every test passes, total count up from 422 (this session's last confirmed full-suite count) by the number of new tests added across Tasks 1, 2, 3, and 4 (7 + 2 + 1 + 1 = 11, so 433).

Two *existing* tests are worth a second look if anything fails, since this plan is the first thing that ever gives them something real to check at village scale: `test_five_year_advance_preserves_data_integrity_across_seeds` and `test_household_wealth_never_goes_negative_across_seeds_and_years` (both `tests/test_db_simulation_integration.py`, `target_population=400`, swept across 10 seeds). Before this plan, villages had zero purchases and zero wealth change, so their FK-integrity, no-purchase-after-death, and wealth-never-negative assertions were trivially true. After it, population 400 clears both curation floors (a tavern and a shop), so these assertions get exercised by real village purchases and wealth flow for the first time. A failure here is a legitimate finding about the wealth/purchase pipeline at small scale, not a fluke to retry past.

- [ ] **Step 2: Report to the user**

Confirm the final pass count, and offer to generate a real village-scale town (`scripts/generate_town.py`, `TARGET_POPULATION` set to something in the 100-999 range) for a direct look — the same "show, don't just assert" standard this project has used at every prior checkpoint (Phase 1's settlemaker spike, Phase 2's sign-off).

## Self-Review

**Spec coverage** — every piece of `docs/superpowers/specs/2026-09-09-village-economy-design.md`'s Architecture section is covered: `Building.reserved_vacant` (Task 1), `_curate_village_economy` (Task 1), wiring + `target_population` threading (Task 2), the `assign_residents` filter (Task 3), and the design's own three prescribed test levels — unit (Task 1), `assign_residents`-level (Task 3), integration (Task 4) — are all present. The Scope section's explicit exclusions (burg-mode untouched, no SVG change, no `VILLAGE_POP_CEILING` change, no rebalancing the shared tables) are respected by construction — no task touches any of them.

**Placeholder scan** — no TBD/TODO; every step shows complete code or an exact command with its expected output.

**Type consistency** — `_curate_village_economy(buildings: List[Building], population: int, seed: Any) -> None` is defined once (Task 1) and consumed once, with the same signature (Task 2). `parse_settlemaker_geojson`/`_parse_village_geojson`'s new `target_population: int = 0` parameter is introduced and used consistently across Task 2's two edits and Task 2's own tests. `Building.reserved_vacant: bool = False` is defined once (Task 1) and consumed in exactly the form defined, in Task 3.
