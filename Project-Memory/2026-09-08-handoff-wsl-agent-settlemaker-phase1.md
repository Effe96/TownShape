# Handoff: Settlemaker Integration, Phase 1 — to the WSL agent

### The user is moving this work from a Windows Claude Code session to a new agent running under WSL on the same machine. This document is a self-contained briefing for that new agent: what happened before you, what's already decided, what's already verified, and the exact next action. Read this fully before touching any code.

## Read these first, in this order

1. `Project-Memory/2026-09-08-organic-visual-overhaul-and-pipeline-port.md` —
   full history of the session that just finished: why the hand-built
   organic town-generation pipeline was built, what it fixed, and why the
   user ultimately judged it not good enough.
2. `Project_Vision/00-proposals.md`, entry **P001** — the decision trail
   that followed: the user's request to integrate an existing open-source
   generator instead of continuing to hand-build one, the license/scope
   triage, the spike results (with real numbers), and the pointer to the
   design work below.
3. `docs/superpowers/specs/2026-09-08-settlemaker-integration-design.md`
   — the actual design. Read this in full before writing any code — it
   has the integration boundary, the data mapping tables, exactly what
   gets deleted vs. kept, and the known open risks.
4. `docs/superpowers/plans/2026-09-08-settlemaker-integration.md` — the
   phased rollout. **You are starting Phase 1.** Phase 2 (deleting the
   old pipeline) does not start until Phase 1's checkpoint — a real
   rendered town, approved by the user — passes. Do not skip that
   checkpoint because the environment changed.

## Current repo state — read before running any git command

As of this handoff, the working tree has substantial **uncommitted**
changes from the prior session. Nothing has been committed to git yet —
this was deliberate (the user never asked for a commit), not an
oversight. Do **not** run `git checkout`/`restore`/`reset`/`clean` on
anything without checking `git status` first and understanding what
you'd be discarding. The uncommitted set, last checked:

```
 M CLAUDE.md                          (pre-existing, not from this work)
 D IDEAS.md                           (content migrated into Project_Vision/)
 M tests/test_blocks.py
 M tests/test_db_render.py
 M tests/test_db_schema.py
 M tests/test_generate.py
 M town_db/render.py
 M town_shaper/blocks.py
 M town_shaper/generate.py
 M town_shaper/geometry.py
 M town_shaper/roads.py
 M town_shaper/water.py
?? Project-Memory/
?? Project_Vision/
?? docs/superpowers/plans/2026-09-08-settlemaker-integration.md
?? docs/superpowers/specs/2026-09-08-settlemaker-integration-design.md
?? relational_network_frameworks.md      (the user's own notes, not agent-authored)
?? town_shaper/countryside.py
```

All of it is real, working, and was verified passing the full test suite
(499/499) before this handoff. It's the bespoke organic-generation port
that `Project-Memory/2026-09-08-organic-visual-overhaul-and-pipeline-port.md`
describes — the very thing Phase 2 of the settlemaker plan will
eventually delete most of. **Whether/when to commit this is a decision
for the user, not something to assume** — ask, rather than committing it
yourself or building Phase 1 on top of it unmentioned.

## Environment differences to watch for (Windows → WSL)

- **This repo lives on the Windows filesystem**, mounted into WSL at
  (most likely) `/mnt/c/Users/Effem/OneDrive/Desktop/personal/Development/Town_Generator/TownShape`
  — confirm the exact path rather than assuming.
- **The Windows session hit a `git clone` "Filename too long" error**
  cloning `settlemaker` directly, caused by Windows' `MAX_PATH` limit
  colliding with that repo's own deeply-nested `docs/superpowers/...`
  paths. This is an NTFS/Git-for-Windows limitation — it should **not**
  occur on a native Linux filesystem. But `/mnt/c/...` paths are still
  backed by NTFS underneath, so the same limit could resurface there too.
  **Clone and build settlemaker under WSL's native filesystem** (e.g.
  `~/scratch/settlemaker`, not `/mnt/c/...`) — both to sidestep this and
  for meaningfully better I/O performance on `npm install`. Only the
  small, final bridge script + pinned dependency need to end up inside
  the actual TownShape repo on `/mnt/c/...`.
- **Node.js availability is unconfirmed on the WSL side.** The Windows
  session had Node v24.15.0 / npm 11.12.1 available and used them
  directly. Check `node --version` / `npm --version` before assuming
  they're present; install if not (Phase 1 needs them).
- The prior session used Windows-native tool calls (a Bash tool backed
  by Git Bash, plus a separate PowerShell tool). You almost certainly
  have a normal POSIX Bash tool instead — this only matters if you're
  reading the prior transcript for command syntax; don't copy
  Windows-path-flavored commands (`C:\...`, `/c/...`) verbatim.

## What was already verified in the spike (don't re-derive these)

A throwaway clone of `settlemaker` was built and run standalone on the
Windows side (since deleted, per the user's request — nothing of it
remains except these findings and the design spec):

- **Validated commit:** `af6741127086762fc0d73bdec374dcfcd373d5be`
  ("Roads to the tile edge (v2.1.0)") on `barrulus/settlemaker`'s
  `master` branch. **Pin Phase 1's dependency to this exact commit** —
  it's the one everything below was actually verified against, not a
  later, unvalidated one.
- Builds cleanly: `npm install && npx tsc`, no errors.
- One public entry point: `generateSettlement(burg: AzgaarBurgInput, {seed}) -> {kind, svg, geojson, degradedFlags}`. No CLI needed — it's a plain importable module.
- Output: flat GeoJSON, `properties.layer` in (`ward`, `building`, `street`, `wall`, `tower`, `entrance`, `poi`). A pop-3000 walled/plaza/temple burg at seed 42 produced 799 features (403 ward, 328 building, 9 street, 1 wall, 23 tower, 4 entrance, 31 poi).
- Speed: 137ms (pop 3000), 169ms (pop 400, routes internally to a separate "village" engine below `VILLAGE_POP_CEILING`).
- **Determinism:** same `burg`+`seed` twice -> byte-identical `geojson` and `svg` **except** `metadata.generated_at` (a wall-clock timestamp). Strip that field; don't let it break a determinism check.
- No npm registry publish exists for this package — it must be consumed as a git dependency (`"settlemaker": "github:barrulus/settlemaker#af6741127086762fc0d73bdec374dcfcd373d5be"` in `package.json`), never a floating branch/tag.
- Visual quality was reviewed directly (both a town-scale and a village-scale render) and judged substantially ahead of everything the prior session's hand-built pipeline produced — that judgment is *why* this integration is happening, not something Phase 1 needs to re-litigate.

## Your exact next action

Phase 1, task 1 from the plan. Reproduce the spike as your starting
point, on WSL's native filesystem:

```bash
cd ~/scratch   # or wherever — just not /mnt/c/...
git clone https://github.com/barrulus/settlemaker.git
cd settlemaker
git checkout af6741127086762fc0d73bdec374dcfcd373d5be
npm install
npx tsc
```

Then follow `docs/superpowers/plans/2026-09-08-settlemaker-integration.md`'s
Phase 1 task list exactly:

1. Create `settlemaker_bridge/` **inside the TownShape repo**, with its
   own `package.json` pinning the commit above, and a thin wrapper
   script (stdin: JSON `{burg, seed}`; stdout: `geojson` with
   `metadata.generated_at` stripped).
2. Python-side `AzgaarBurgInput` builder (reuse
   `town_db.generate._water_feature_rings`'s ring-extraction for the
   `coastlineGeometry` field rather than re-deriving it).
3. Python-side `parse_settlemaker_geojson` per the spec's Data Model
   mapping tables. Ward types with no mapping yet (`castle`, `park`)
   should raise loudly, not silently drop, so you find out during this
   phase whether they actually show up in practice.
4. Generate **one** real town this way and render it through the
   existing, unchanged `town_db.render.render_town`.
5. **Stop. Show the result to the user side by side with the prior
   session's `port_test.png`** (same seed/population if possible) and
   get explicit sign-off on both the visual result and the ward-mapping
   table actually looking right in practice. Do not start Phase 2
   (deleting `town_shaper` modules) without this.

## One more thing

The user's standing rule throughout this whole project, stated multiple
times in the prior session: **mock up / get sign-off before writing real
pipeline code**, and **claimed fixes must be independently re-verified,
not just asserted**. Both apply directly to Phase 1's checkpoint above —
don't treat it as a formality.
