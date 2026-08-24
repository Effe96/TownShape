---
name: generate-town-from-narrative
description: Generate a new medieval town database from narrative input (a short description or a longer campaign-wiki document) by mapping it onto TownParameters, confirming with the user, then calling town_narrative.generate.generate_town_from_parameters.
---

# Generate Town From Narrative

Use when asked to create a new town/city for a D&D campaign from
narrative input — a short description ("kinda large, sparse, poor
town") or a path to a longer document.

## Procedure

1. **Read the input.** If given a file path, read it in full. If given
   inline text, use it directly.
2. **Map narrative language onto `TownParameters` fields** using
   `docs/narrative-town-parameters.md` as the reference table. Fields
   available today: `seed`, `target_population`,
   `area_per_resident_multiplier`, `density_multiplier`,
   `rich_proportion`.
3. **When the input doesn't clearly resolve a field, don't guess
   silently** — state your recommended default and reasoning, and ask
   the user to confirm or override it.
4. **Present the filled-in parameters to the user before generating**,
   and confirm.
5. **Generate:**

   ```python
   from town_narrative.generate import generate_town_from_parameters
   from town_narrative.parameters import TownParameters

   params = TownParameters(
       seed=<a stable seed derived from the campaign/town name>,
       target_population=<int>,
       area_per_resident_multiplier=<float>,
       density_multiplier=<float>,
       rich_proportion=<float>,
   )
   generate_town_from_parameters(params, db_path="<destination path>.db")
   ```

6. **Verify the actual resident count.** Low `density_multiplier`
   combined with a small `area_per_resident_multiplier` can leave the
   generated town short of `target_population` — residents who don't
   fit in any building are silently omitted, with no marker of the
   shortfall in the data. After generating, run:

   ```sql
   SELECT COUNT(*) FROM residents;
   ```

   against the generated database, and if the result differs
   materially from the requested `target_population`, tell the user the
   actual resident count.

See `docs/narrative-town-parameters.md` for the full mapping table and
the reasoning behind each field.
