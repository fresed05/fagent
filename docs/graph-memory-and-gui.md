# Graph Memory and Graph UI

[Русская версия](./graph-memory-and-gui.ru.md)

This guide explains how graph memory works in `fagent`, what it stores, and why the local Graph UI matters.

## What graph memory adds

Graph memory stores durable entities and relationships. It complements file and vector memory by preserving structure.

This is especially useful for:

- dependencies
- blockers
- decisions
- related workflow concepts
- grouped project facts

Vector memory can tell you what sounds similar. Graph memory can tell you what is connected.

## Graph extraction flow

Graph extraction is managed through `fagent/memory/graph.py` and coordinated by `fagent/memory/orchestrator.py`.

At a high level:

1. A session artifact is available.
2. Graph extraction tools search existing graph state.
3. The runtime stages entities, facts, and relations.
4. The graph backend persists nodes and edges.
5. Graph jobs can be inspected later from the CLI.

## Local and Neo4j-backed modes

`fagent` supports a local graph backend and an optional Neo4j mirror/backend configuration.

## Task graph and graph memory

Task graph state is not identical to general graph memory, but they reinforce each other.

- task graph stores goals, blockers, decisions, and task edges
- graph memory stores broader entities, facts, and relations

Together they push the runtime toward graph-shaped continuity rather than linear memory only.

## Graph UI

The local Graph UI is implemented in `fagent/memory/graph_ui.py` and serves a browser-based graph viewer/editor.

It can:

- open a local HTTP server
- render graph snapshots and focused views
- load graph overview, focus, and details payloads
- create, update, and delete graph nodes and edges
- persist layout positions

## Why the Graph UI is important

It gives you a human way to inspect what the memory graph actually contains.

That helps with:

- debugging bad recalls
- validating graph extraction quality
- checking whether useful entities and relations exist
- understanding why a relationship-oriented answer happened

## CLI commands

```bash
fagent memory graph-ui --open
fagent memory graph-ui --query "shadow context"
fagent memory rebuild-graph
fagent memory inspect-graph-jobs
fagent memory inspect-task-graph cli:direct
```

## Why this improves understanding and planning

When the agent preserves relationships as structure, it can reason over more than a checklist.

That matters because:

- blockers can stay linked to decisions
- entities can stay linked to tools and workflows
- current task state can stay connected to supporting facts
- future graph-shaped planning becomes easier to enrich automatically

This should be understood as a current structural advantage, not as a claim that fully automatic graph planning is already complete.

## Related docs

- Previous: [Memory architecture](./memory-architecture.md)
- Next: [Subagents and workflows](./subagents-and-workflows.md)
- Also see: [CLI and observability](./cli-and-observability.md)
