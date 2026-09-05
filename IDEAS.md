# Ideas & Feedback Log

Collected feedback on TownShape's simulation, tooling, and user experience.

## Visualization Features

### Feedback

1. **Status check:** Requested for map visualization — streets should appear as real gaps between building blocks, not drawn lines; arterials should follow the actual district-boundary graph instead of spoke-like hub lines; buildings should fully tile each block instead of appearing as floating uniform rectangles.

   **Resolved 2026-09-04:** implemented per
   `docs/superpowers/specs/2026-09-04-organic-town-rendering-design.md` /
   `docs/superpowers/plans/2026-09-04-organic-town-rendering.md`. Streets
   inside the urban core are now the implicit gap between inset block
   polygons (no drawn line), arterial roads follow the real district
   boundary graph instead of straight hub-and-spoke lines, and buildings
   fully tile each block via recursive subdivision. A population-scaled
   cap keeps named/business building counts (taverns, shops, etc.)
   bounded so this doesn't worsen the duplicate-tavern-name issue logged
   above under "Backend > Population Generation > Feedback" (item 1).

## Backend

### Population Generation

#### Feedback

1. **Duplicate tavern names and business duplicates:** When population scales up, the same named building (e.g., "The Rusty Anvil") appears multiple times in one town, breaking immersion. Currently no cap on how many named/business buildings can exist for a given population.
