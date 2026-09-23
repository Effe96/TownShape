# Frameworks for Decomposing Human Relationships into Network Components

Reference doc for modeling a personal/professional relationship network as a weighted (multi)graph.

## 1. Core edge model — Granovetter's Tie Strength (1973)

Any relationship edge can be scored as a composite of 4 measurable dimensions (0–1 scale):

- **time**: frequency/amount of substantive direct contact
- **intensity**: emotional intensity (either valence direction)
- **intimacy**: mutual disclosure of vulnerable/personal information
- **services**: reciprocal exchange of practical favors/support

`tie_strength = mean(time, intensity, intimacy, services)`

## 2. Relationship type tag — Fiske's Relational Models Theory (1991)

Categorical label for the dominant exchange logic of a tie (often a blend of two):

- **Communal Sharing** — undifferentiated in-group, no accounting
- **Authority Ranking** — asymmetric, hierarchical
- **Equality Matching** — turn-based, tit-for-tat balance
- **Market Pricing** — explicit cost-benefit exchange

## 3. Structural/positional layer — Social Convoy Model (Kahn & Antonucci, 1980)

Concentric circles around ego, ranked by closeness and role-independence: innermost = tied to ego regardless of role (e.g. family); outer = role-contingent (e.g. coworkers). Gives a radial coordinate complementary to edge attributes.

## 4. Graph formalism — standard SNA

- Represent the network as a **multiplex graph**: nodes = people, edges = relationship instances, each edge carries a type + attribute vector.
- **Multiplexity** = number of distinct role-types connecting the same two nodes (e.g. kinship + friendship + shared hobby = 3).
- Standard structural metrics (degree, betweenness, clustering coefficient) apply once the graph has more than a star topology around ego.

## 5. Work-relationship layers — Krackhardt & Hanson (1993); Podolny & Baron (1997)

Workplace ties should be split into **separate layers on the same nodes**, since they don't coincide with the formal org chart or with each other:

- **advice network** — who you'd ask to solve a technical problem
- **trust network** — who you'd involve in politically sensitive situations
- **communication network** — who you actually talk to, regardless of trust/competence

Podolny & Baron extend this to 5 relational contents: advice, buy-in/political support, task interdependence, communication, friendship.

## 6. Trust — ABI Model (Mayer, Davis & Schoorman, 1995)

Trust is not a scalar; it decomposes into 3 perceived antecedents of the trustee:

- **Ability** — perceived domain-specific competence
- **Benevolence** — perceived motivation to act in the trustor's interest
- **Integrity** — perceived adherence to acceptable principles

These, moderated by the trustor's own disposition to trust, predict trust → which predicts risk-taking behavior in the relationship. Validated scale: Mayer & Davis (1999); confirmed via meta-analysis (Colquitt, Scott & LePine, 2007).

Simpler 2-axis alternative: **McAllister (1995)** — cognition-based trust (competence/reliability track record) vs. affect-based trust (emotional bond); empirically separable, grow at different rates.

Temporal/stage model: **Lewicki & Bunker (1996)** — trust matures through calculus-based → knowledge-based → identification-based stages.

## 7. Finer-grained support taxonomy — House (1981)

Granovetter's "services" dimension can be unpacked into 4 distinct support types if more resolution is needed:

- **emotional** (empathy/listening)
- **instrumental** (practical/material help)
- **informational** (advice/information)
- **appraisal** (feedback for self-evaluation)

## 8. Multilayer network formalism — De Domenico et al. (2013)

General mathematical framework: instead of one edge with N attributes, each relationship type (family, work, hobby, trust...) becomes a **separate layer** with its own adjacency matrix; nodes are replicated across layers and linked via coupling edges. Enables metrics like **versatility centrality** (consistency of centrality across layers). Use this when relation types are too heterogeneous to compress into a single attribute vector.

## 9. Perceptual layer — Cognitive Social Structures (Krackhardt, 1987)

Orthogonal dimension: collect the perceived graph from *every* node, not just ego. Divergence between "who X thinks trusts whom" and the actual graph is often the most informative signal — especially in workplace contexts.

## Recommended integration strategy

- Keep **Granovetter (tie strength) + Fiske (relation type)** as the core edge schema for family/friends.
- For colleagues, add a **separate layer**: ABI trust score + Krackhardt advice/trust/communication split, rather than forcing workplace ties into the same vector — these constructs are validated on different relationship populations and mixing them dilutes predictive power.
- Use House's 4-part support taxonomy in place of "services" if more resolution on reciprocal support is needed.
- Move to a full multilayer graph (De Domenico) once more than ~2 relationship types need to be modeled simultaneously without collapsing them into one score.

## Worked example (from this conversation)

Ego-network with 3 nodes, using the core Granovetter+Fiske schema, all dimensions 0–1 except multiplexity (raw role count):

| Relationship | time | intensity | intimacy | services | multiplexity | Fiske type | tie_strength |
|---|---|---|---|---|---|---|---|
| Brother | 0.7 | 1.0 | 1.0 | 1.0 | 3 | Equality Matching | 0.92 |
| Best friend | 0.7 | 1.0 | 1.0 | 1.0 | 2 | Equality Matching | 0.92 |
| Distant friend | 0.1 | 0.5 | 0.5 | 1.0 | 1 | Communal Sharing | 0.52 |

Implemented as a NetworkX weighted graph: nodes = people, `Io` (ego) as hub, edges carry all 6 fields as attributes, edge width ∝ tie_strength, edge color = Fiske type.
