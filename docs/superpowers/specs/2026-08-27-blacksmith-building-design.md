# Blacksmith Building — Design

## Context

TownShape's MERCHANT zone currently generates `shop`, `tavern`, and
`market_stall` buildings (`BUILDING_TYPES_BY_ZONE[ZoneType.MERCHANT]` in
`town_shaper/buildings.py`), alongside the parameter-gated `arcane_shop`
added in D1c (magic prevalence). This adds a `blacksmith` building type
selling a new `weapons` goods category — a normal, general-purpose
addition to the town economy, not tied to any narrative parameter.
Prompted by a private side project (a SQL-practice game) that wanted a
"blacksmith/weapons and armor shop" flavor with real backing data, but
the building type itself is generally useful independent of that project
and belongs in TownShape proper.

## Scope

- A new `blacksmith` building type, unconditional — every town can
  generate one, the same way every town can generate a `shop` or
  `tavern`. No new `TownParameters` field, no `generation_parameters`
  column, no gating parameter of any kind.
- A new `weapons` goods category (5 goods) purchasable only where a
  `blacksmith` building actually exists, mirroring how `magic`-category
  goods are scoped to `arcane_shop` existence — but with no prevalence
  dial, since there's nothing to dial: a blacksmith is either present or
  it isn't.
- Two new occupations: `blacksmith` (owner) and `smith_apprentice`
  (staff) — `smith_apprentice`, not `apprentice`, to avoid colliding
  with `arcane_shop`'s existing `apprentice` occupation and making
  occupation-based queries ambiguous.

Out of scope: any TownParameters/narrative-mapping changes (this is
unconditional, nothing to map from narrative input); any interaction
with `aggression`/military service (a blacksmith is a MERCHANT-zone
shop, not a CIVIC/garrison building); the private SQL-practice game
itself (separate project, not part of this spec).

## Data Model

### `town_shaper/buildings.py`

`BUILDING_TYPES_BY_ZONE[ZoneType.MERCHANT]` changes from:

```python
{"shop": 0.5, "tavern": 0.2, "market_stall": 0.3}
```

to:

```python
{"shop": 0.4, "tavern": 0.2, "market_stall": 0.25, "blacksmith": 0.15}
```

`JOB_VACANCIES_BY_BUILDING_TYPE` gains:

```python
"blacksmith": [("blacksmith", 1), ("smith_apprentice", 2)],
```

This is a real change to the default distribution of every generated
town — unlike every prior D1a-D1d parameter, there is no "default
reproduces prior behavior" here, because there is no parameter: a
blacksmith building can now appear where previously it never could.
Existing tests that hardcode an exact building type for a specific
building index/seed (relying on the old weight table's sampling order)
may need updating — this is expected, not a regression, and should be
called out explicitly in the task that touches this file.

### `town_db/goods.py`

Adds 5 rows to `GOODS_CATALOG`, category `"weapons"`:

```python
{"name": "dagger", "category": "weapons", "typical_price": 3.0, "sv": 600},
{"name": "sword", "category": "weapons", "typical_price": 10.0, "sv": 350},
{"name": "shield", "category": "weapons", "typical_price": 8.0, "sv": 400},
{"name": "leather armor", "category": "weapons", "typical_price": 15.0, "sv": 300},
{"name": "chainmail", "category": "weapons", "typical_price": 40.0, "sv": 150},
```

Also fixes a stale, incorrect comment above `GOODS_CATALOG`: it
currently reads "Lower sv = more common = more frequently purchased,"
which contradicts both the actual data (bread, the most commonly bought
good, has a *higher* sv (800) than jewelry, a rare luxury good (400))
and `town_db/purchases.py`'s own correct comment ("a HIGHER sv means the
good is bought more often ... weight directly by sv, not by its
reciprocal"). Change it to read "Higher sv = more common = more
frequently purchased" to match reality and the other module's comment.

### `town_db/purchases.py`

`generate_purchases` gains a new parameter,
`blacksmith_building_ids: Optional[List[int]] = None`, mirroring the
existing `arcane_shop_building_ids` parameter exactly:

```python
blacksmith_building_ids = blacksmith_building_ids or []
weapons_available = len(blacksmith_building_ids) > 0
```

`goods_names` filtering changes from:

```python
goods_names = [
    name for name in sv_by_name
    if category_by_name[name] != "magic" or magic_available
]
```

to:

```python
goods_names = [
    name for name in sv_by_name
    if (category_by_name[name] != "magic" or magic_available)
    and (category_by_name[name] != "weapons" or weapons_available)
]
```

Shop selection changes from:

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

No change to `good_weights` — weapons goods weight by `sv` exactly like
every other non-magic category (no `magic_prevalence`-style multiplier,
since there's no prevalence dial for weapons).

`SHOP_BUILDING_TYPES` (`{"shop", "tavern", "market_stall"}`) is
unchanged — `blacksmith`, like `arcane_shop`, is deliberately excluded
from it, so a blacksmith only ever sells weapons goods, never the
generic shop catalog.

### `town_db/generate.py`

Mirrors the existing `arcane_shop_building_ids` wiring:

```python
blacksmith_building_ids = [
    b.id for d in town.districts for b in d.buildings if b.building_type == "blacksmith"
]
```

computed alongside the existing `arcane_shop_building_ids` line, and
passed into the `generate_purchases(...)` call as
`blacksmith_building_ids=blacksmith_building_ids`.

## Error Handling & Edge Cases

- No `blacksmith` building in a generated town (possible for a very
  small town with few MERCHANT slots, same as any other building type
  can be absent by chance): `weapons_available` is `False`, no weapons
  goods appear in `goods_names`, no error — matches the existing
  `magic_available` tolerance pattern exactly.
- A town with `target_population` too small to generate any MERCHANT
  buildings at all: `blacksmith_building_ids` is empty, same as above.

## Testing Strategy

- **Building generation**: across a broad seed sweep, `blacksmith`
  buildings appear at a rate consistent with the new
  `BUILDING_TYPES_BY_ZONE[MERCHANT]` weight (0.15 share of MERCHANT
  slots) — same statistical-verification rigor as every prior building-
  frequency test in this project (broad seed sweep, not a single seed).
- **Job vacancies**: a generated `blacksmith` building's residents
  include exactly the `blacksmith`/`smith_apprentice` occupation split
  the job-vacancy table specifies.
- **Goods catalog**: the 5 new goods exist with the exact
  name/category/price/sv values above; the corrected comment doesn't
  affect runtime behavior, so no behavioral test needed for that part,
  but note it in the task's diff for review.
- **Purchases — no blacksmith exists**: `weapons_available` is `False`,
  zero weapons purchases generated, no error.
- **Purchases — blacksmith exists**: across a broad seed sweep with a
  town population large enough to guarantee a blacksmith, weapons goods
  purchases occur, are drawn only from `blacksmith_building_ids`, and
  never appear in a purchase whose `shop_building_id` is a `shop`,
  `tavern`, `market_stall`, or `arcane_shop` building.
- **Full regression sweep**: since this is not backward-compatible by
  design, run the whole existing test suite after the `buildings.py`
  weight change specifically, and update any test whose expectations
  depended on the old MERCHANT weight table's exact sampling — this is
  expected work, not a sign something is wrong.
- **`PRAGMA foreign_key_check`** stays clean end-to-end, same as every
  prior slice.

## Out of Scope for This Spec

- Any narrative-mapping doc/skill update — there's no parameter to
  document, this is unconditional infrastructure.
- The private SQL-practice game project itself.
- Any interaction between blacksmiths and `aggression`/military service
  (e.g., guards being equipped from a specific blacksmith) — purely a
  MERCHANT-zone economic addition for this pass.
