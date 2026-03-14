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

## Graph UI — new interface (graph-ui-new)

The Graph UI has been upgraded to a modern React/Next.js interface built with
`react-force-graph-2d`, Tailwind CSS and Radix UI. It replaces the old
`graph_ui/` Vanilla JS viewer.

Features of the new UI:

- force-directed layout with radial and hierarchical modes
- live search and filter panel with kind/type filters
- rich details panel showing neighbors, edges, and metadata
- zoom-independent labels (LOD rendering)
- keyboard shortcuts: `R` relayout, `L` toggle labels, `Esc` deselect
- graph mode selector: Atlas (clustered) / Raw (all nodes)
- query and session filter passed through URL or UI

### First-time setup

The new UI must be compiled once before use:

```bash
# Requires Node.js >= 18 and npm
fagent memory graph-ui-install
```

This builds the static frontend into `fagent/static/graph-ui-new/out/` which
the Python server then serves.

### Auto-start with gateway

Add to `config.json` to start the Graph UI automatically when `fagent gateway` runs:

```json
{
  "gateway": {
    "graph_ui": {
      "enabled": true,
      "port": 8765,
      "open_browser": false
    }
  }
}
```

Use `"open_browser": true` to open a tab in the default browser on startup.

## CLI commands

```bash
# Build the UI (once after installation or upgrade)
fagent memory graph-ui-install

# Start the Graph UI server (opens browser by default)
fagent memory graph-ui
fagent memory graph-ui --query "shadow context"
fagent memory graph-ui --port 9090 --no-open

# Graph data management
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
