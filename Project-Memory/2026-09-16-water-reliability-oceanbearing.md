# RESOLVED 2026-09-21 — water-rendering reliability

**Status: fixed and shipped.** This note originally proposed switching to
`oceanBearing` after a deep dive into settlemaker's `classifyWater()`
internals. That diagnosis turned out to be a red herring — a much simpler,
complete root cause was found immediately after, and the actual fix is a
one-line change in `settlemaker_bridge/pipeline.py`. Keeping this file as a
record of the wrong turn (and why it was wrong), not as a task list anymore.

## What actually happened

While generating a river+coastline demo town with `has_port=False`,
settlemaker's own SVG showed no water at all, even though `Town.water_features`
was correct. Investigating this, the original version of this note concluded
that `coastlineGeometry` — a *prediction* built from a "dry" (no-water)
settlemaker call, before the "real" call's mesh exists to measure — sometimes
doesn't land close enough to settlemaker's own generated patches for its
`classifyWater()` to register any water, and proposed switching to
`oceanBearing` (a compass bearing that settlemaker synthesizes into its own
coastline internally, immune to prediction error) as the reliable
alternative for coastline-only towns.

**That theory was incomplete.** The actual, dominant, and much simpler cause:
settlemaker's `dist/input/azgaar-input.js` silently drops
`coastlineGeometry` from the params it passes to the generator unless
`burg.port === true` — the exact same gate `harbourSize` and `oceanBearing`
are behind (see this session's earlier `has_port` fix,
`settlemaker_bridge/build_input.py`'s doc comment). TownShape's own code only
ever set `port: has_port` (the user's real intent about whether a harbour
ward should exist) — so any water request made with `has_port=False` (the
common case: scenery water, no dock) silently sent settlemaker **no water
definition at all**. The "dry-call prediction is sometimes imprecise" theory
wasn't the deciding factor in the failing case investigated — it was never
properly isolated, because `has_port` differed between the working demo town
and the failing one without that being recognized as the controlling
variable.

## The fix (already shipped)

`generate_via_settlemaker` now forces `burg["port"] = True` internally
whenever `water_features` is non-empty, regardless of the caller's actual
`has_port` — applied before *both* the dry and real settlemaker calls (not
just the one that attaches `coastlineGeometry`), so the dry call's own
`local_bounds` stays an accurate proxy for the real call, which now also
carries the override. `harbourSize` (and therefore whether a real harbour
ward gets placed) still only follows the caller's actual `has_port`,
unaffected by this — verified directly: a town generated with
`has_port=False` now shows real water in settlemaker's own SVG AND has zero
PORT districts, as expected.

**Verified with a sweep, not just the one reported case:** population
2000/3000/6000/8000 x 3 seeds x {river-only, coastline-only, both} = 36/36
now show real water in settlemaker's own SVG. Regression test:
`tests/test_settlemaker_bridge_integration.py::test_water_renders_in_settlemakers_own_svg_without_a_port`.

The `oceanBearing`/fork-vs-keep-using-settlemaker discussion that followed
this investigation is still relevant context (see conversation history) —
the decision was to keep using settlemaker as-is (not fork), and this fix
removes the concrete problem that prompted that discussion in the first
place. `oceanBearing` may still be worth revisiting someday as a *feature*
(letting a narrative parameter pick which compass direction the sea is in),
but it is no longer needed for basic reliability.
