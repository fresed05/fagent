# CLI and Observability

[Русская версия](./cli-and-observability.ru.md)

`fagent` exposes a practical CLI for runtime health, memory inspection, graph inspection, and graph UI access.

## Core runtime commands

```bash
fagent onboard
fagent agent
fagent gateway
fagent status
```

## Memory inspection commands

Implemented memory inspection commands include:

```bash
fagent memory doctor
fagent memory query-v2 "current blockers"
fagent memory inspect-task-graph cli:direct
fagent memory inspect-experience
fagent memory rebuild-graph
fagent memory inspect-graph-jobs
fagent memory graph-ui --open
```

## What to inspect when something feels wrong

### Bad recall

Check:

- `fagent memory query-v2`
- `fagent memory inspect-graph-jobs`
- `fagent memory graph-ui`

### Lost task continuity

Check:

- `fagent memory inspect-task-graph`
- workflow snapshots and session summaries

### Repeated workflow failures

Check:

- `fagent memory inspect-experience`
- workflow repair behavior and `workflowLight` configuration

## Graph UI as observability surface

Use it to:

- see relationship density
- confirm graph extraction quality
- inspect focused subgraphs
- verify whether a node or edge should exist

## Runtime stage visibility

The CLI also surfaces different stages of memory work such as:

- file memory saving
- graph building
- vector writing
- session summarization

## Related docs

- Previous: [Providers and model roles](./providers-and-model-roles.md)
- Next: [Docs index](./README.md)
- Also see: [Configuration reference](../CONFIGURATION.md)
