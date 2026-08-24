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

These ranges are starting points, open to tuning as they're used against
real campaign input — same spirit as the empirically-set constants
elsewhere in this project (e.g. Town DB's disease/birth-rate constants).
