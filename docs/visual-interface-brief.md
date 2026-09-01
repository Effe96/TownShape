# Project Brief: Town Viewer

## Where the need came from

TownShape generates fantasy towns from a large set of tunable
parameters (zoning, population, economy, and more). The only way to
see the result of a generation run today is a static PNG — zones as
colored polygons, buildings as small colored dots. When tuning a
parameter, the workflow is: change it, regenerate, open the PNG, and
try to judge from colored shapes alone whether the change did what was
intended. There's no way to ask the town anything.

## The problem, in plain terms

You can see that a town has shapes and colors, but you can't inspect
it. You can't click a building and ask "who lives here?" You can't
click a person and ask "where do they work, who's in their family,
what do they buy?" Every question past "does this look roughly right"
means reading raw database rows by hand.

## Who it's for

Right now: the person building the generator, iterating on generation
parameters. (There's a longer-term ambition to make a public version —
something like donjon.io — and to showcase towns on a personal
website. That's a real goal, but it's a later phase and isn't part of
what's being built here.)

## What the product will actually do

- Show one generated town as a zoomable, pannable map — zones and
  buildings drawn as shapes you can see at a glance and zoom into.
- Let you click a building and see what it is and who lives and works
  there.
- Show a searchable list of every resident in the town alongside the
  map. Picking a resident highlights their home and workplace on the
  map, and shows their household, family (spouse, parents, siblings),
  and spending history.
- Run entirely on your own machine, pointed at one town at a time.

## What it deliberately won't do (and why)

- **It won't let you edit the town.** Editing is a different job from
  viewing. Keeping this version view-only is what makes it small
  enough to actually finish.
- **It won't play the town forward in time.** The generator has
  year-by-year simulation, but its edit code doesn't yet guarantee a
  town's family/work/spending data stays correct after the town
  changes. This version always shows one complete, freshly-generated
  town exactly as it was produced — never a town being aged forward
  live.
- **It won't be hosted, shared, or multi-user.** No accounts, no
  gallery of towns, no public website. That's a real future goal, but
  building it now would mean solving hosting and multi-town problems
  before the core viewing experience even works.
- **It won't produce a printable, illustrated fantasy-style map.**
  That's a distinct art project, not a data-inspection tool, and is
  deferred.

## Real-world facts that shaped it

- The data this tool needs (names, families, jobs, spending) already
  exists in the generator's database. This is a display project, not
  a data-generation project.
- A real generated town is not small: one existing sample town has
  over 5,000 residents, 1,100+ buildings, and well over 100,000
  recorded relationships. "Just render everything" won't hold up —
  the resident list has to support real search, not just scrolling.
- This is a one-person side project with no external deadline, so the
  plan favors shipping something usable soon over building for a
  hypothetical future audience.
