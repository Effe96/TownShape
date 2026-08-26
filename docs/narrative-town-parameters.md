# Narrative → Town Parameters

Reference for mapping narrative town descriptions onto
`town_narrative.parameters.TownParameters` fields. Written to be
agent-neutral: any agent driving town generation from narrative input can
use this table, not just Claude Code (see
`.claude/skills/generate-town-from-narrative/SKILL.md` for the
Claude-Code-specific invocation wrapper around this content).

**Rule: when narrative input doesn't clearly resolve to a value or
range, ask the user directly.** State your recommended default and why,
rather than silently guessing.

## Fields

- **`seed`** — any stable, reproducible value (e.g. the town's name).
  The same seed + parameters always regenerate the same town.
- **`target_population`** — headcount. No narrative-language table below;
  ask directly if not stated numerically or as a clear size descriptor
  ("a small village," "a large city").
- **`area_per_resident_multiplier`** (default `1.0`) — physical town
  footprint, independent of population. "How large the city is,"
  physically, as distinct from headcount — a modest population can be
  sprawled across an old, oversized city, or a huge population packed
  into a small one.
- **`density_multiplier`** (default `1.0`) — how tightly buildings are
  packed within whatever area exists, independent of size. Low density
  at a large size reads as "a small village in a large town." Low
  density combined with a small area reduces total housing capacity;
  residents beyond that capacity are omitted from the generated town
  entirely (never written to the `residents` table), so the actual
  generated population can end up well below `target_population`, with
  no explicit marker of the shortfall anywhere in the data.
- **`rich_proportion`** (default `0.05`) — fraction of households that
  are SES-rich; the rest are poor (there is no third tier). "Richness"
  of the town overall.
- **`num_rivers`** (default `0`) — how many rivers run through the town.
  Each is generated as an independent, gently curved strip of water
  crossing the town, carving real unbuildable space out of whatever
  district it passes through.
- **`has_coastline`** (default `false`) — whether one side of the town
  borders open water (a sea/lake edge), as opposed to an interior river.
  Water carves real unbuildable space out of the town, the same way a low
  `density_multiplier` does — a coastal town's realized population can run
  20-40% below `target_population`, silently, with no marker of the
  shortfall in the data. Verify the actual resident count after
  generating (see the skill's step 6).
- **`has_port`** (default `false`) — whether the town has a dedicated
  port district (docks, warehouses, a harbormaster's office). Requires
  `num_rivers > 0` or `has_coastline` — raises otherwise, since a port
  needs water to sit on. Carries the same population-shortfall caveat as
  `has_coastline`.
- **`magic_prevalence`** (default `0.0`) — how prevalent magic is in the
  town, as a fraction from `0.0` (none) to `1.0` (saturated). Drives three
  independent things: an `arcane_shop` (a MERCHANT-zone building, staffed
  by a mage + apprentices) becomes more likely to appear as this rises;
  magic-category goods (healing potions, spell scrolls, arcane reagents)
  become purchasable, but only where an `arcane_shop` actually exists;
  and the fraction of residents with `has_magical_talent` (a latent trait,
  independent of occupation — not every mage is guaranteed to roll it,
  and untrained townsfolk can have it too) tracks this value directly.
- **`aggression`** (default `0.0`) — how prone the population is to
  skirmishes/incidents between the poor quarter and the city guard, as a
  fraction from `0.0` (none) to `1.0` (frequent unrest). Drives skirmish
  event frequency across the simulated year; skirmishes can produce
  resident casualties among poor adults and guard/soldier-occupation
  residents specifically.

  There is no `stress` input field — it's a **derived** value, not
  something you set. After generating a town, call
  `town_db.stats.compute_stress(db_path)` to get a `0.0`-`1.0` readout
  reflecting the town's poor-population fraction and observed skirmish
  frequency, if you need to describe the town's overall tension level in
  narrative terms.

## Narrative language → value

| Narrative language | Field | Suggested value |
|---|---|---|
| "sprawling", "spread out", physically large | `area_per_resident_multiplier` | 1.5 – 2.5 |
| "compact", "walled", small footprint | `area_per_resident_multiplier` | 0.4 – 0.7 |
| (no size cue) | `area_per_resident_multiplier` | 1.0 (default) |
| "cramped", "crowded", "packed" | `density_multiplier` | 1.3 – 2.0 |
| "sparse", "spread thin", "a village in a large town" | `density_multiplier` | 0.3 – 0.6 |
| (no density cue) | `density_multiplier` | 1.0 (default) |
| "wealthy", "prosperous", "opulent" | `rich_proportion` | 0.15 – 0.3 |
| "poor", "impoverished", "destitute" | `rich_proportion` | 0.01 – 0.03 |
| (no wealth cue) | `rich_proportion` | 0.05 (default) |
| "a river runs through it", "on the river", "riverside" | `num_rivers` | 1 |
| "where two rivers meet", "at the confluence" | `num_rivers` | 2 |
| (no river cue) | `num_rivers` | 0 (default) |
| "coastal", "seaside", "on the coast/sea" | `has_coastline` | `true` |
| (no coastal cue) | `has_coastline` | `false` (default) |
| "port town", "trading port", "harbor" | `has_port` | `true` — also set `has_coastline=true` as the implied water source, unless the narrative specifies a river port instead |
| "arcane", "wizards on every corner", "high magic" | `magic_prevalence` | 0.3 – 0.6 |
| "no magic", "mundane", "magic is rare/forbidden here" | `magic_prevalence` | 0.0 (explicit absence stated) |
| (no magic cue either way) | `magic_prevalence` | 0.05 – 0.1 (low, not zero — most fantasy settings have *some* ambient magic even when the narrative doesn't call it out; reserve `0.0` for when the text explicitly says magic is absent/forbidden/mundane) |
| "restless", "prone to riots", "tense streets" | `aggression` | 0.3 – 0.6 |
| "peaceful", "orderly", "no unrest" | `aggression` | 0.0 (default) |
| (no aggression cue) | `aggression` | 0.0 (default) |

These ranges are starting points, open to tuning as they're used against
real campaign input — same spirit as the empirically-set constants
elsewhere in this project (e.g. Town DB's disease/birth-rate constants).
