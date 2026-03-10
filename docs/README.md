# fagent Docs

[Русская версия](./README.ru.md)

This is the documentation hub for `fagent`: the graph-aware, memory-first runtime for long-running agent work.

## Read by goal

- New to the project: start with the [root README](../README.md)
- Want the product framing: read [Why fagent](../WHY_FAGENT.md)
- Want to understand continuity and token savings: read [Memory architecture](./memory-architecture.md)
- Want to understand bounded delegation and operational execution: read [Subagents and workflows](./subagents-and-workflows.md)
- Want graph internals and the browser GUI: read [Graph memory and Graph UI](./graph-memory-and-gui.md)
- Want provider wiring and model-role separation: read [Providers and model roles](./providers-and-model-roles.md)
- Want the inspection commands and runtime surfaces: read [CLI and observability](./cli-and-observability.md)
- Want the full config schema: read [Configuration reference](../CONFIGURATION.md)

## Documentation map

### Product framing

- [README](../README.md)
- [Why fagent](../WHY_FAGENT.md)

### Core runtime

- [Memory architecture](./memory-architecture.md)
- [Graph memory and Graph UI](./graph-memory-and-gui.md)
- [Subagents and workflows](./subagents-and-workflows.md)
- [Providers and model roles](./providers-and-model-roles.md)
- [CLI and observability](./cli-and-observability.md)

### Reference

- [Configuration reference](../CONFIGURATION.md)
- [Communication](../COMMUNICATION.md)

## Suggested reading order

1. [README](../README.md)
2. [Why fagent](../WHY_FAGENT.md)
3. [Memory architecture](./memory-architecture.md)
4. [Graph memory and Graph UI](./graph-memory-and-gui.md)
5. [Subagents and workflows](./subagents-and-workflows.md)
6. [Providers and model roles](./providers-and-model-roles.md)
7. [CLI and observability](./cli-and-observability.md)

## What this doc set focuses on

This documentation set is centered on the implemented behaviors that make `fagent` different:

- layered memory instead of plain chat history
- graph-aware recall instead of only vector recall
- shadow-context compression before the main model runs
- subagents for bounded background work
- workflow execution with lighter-model repair
- local Graph UI for inspecting and editing graph memory
- provider/model-role separation for cost and latency control

## Module anchors

The most important implementation modules behind these docs are:

- `fagent/memory/orchestrator.py`
- `fagent/memory/router.py`
- `fagent/memory/shadow.py`
- `fagent/memory/graph_ui.py`
- `fagent/agent/subagent.py`
- `fagent/agent/tools/workflow.py`

## Related docs

- Previous: [README](../README.md)
- Next: [Memory architecture](./memory-architecture.md)
- Also see: [Why fagent](../WHY_FAGENT.md)
