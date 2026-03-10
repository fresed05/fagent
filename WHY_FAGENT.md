# Why fagent

[Русская версия](./WHY_FAGENT.ru.md)

This document explains where `fagent` is stronger than broader agent stacks and why its design is optimized for continuity-heavy work rather than only one-shot chat.

## The short version

`fagent` is for teams and individual operators who want:

- a runtime they can inspect directly
- memory that is more than chat history
- graph-aware recall for relationships and blockers
- lower main-model waste during tool-heavy execution
- a local way to inspect what the memory graph actually contains

It is not trying to be the broadest consumer platform. It is trying to be a focused agent runtime that stays coherent over repeated sessions.

## Where fagent wins

### 1. Smaller, more inspectable operational surface

`fagent` is centered on one Python package, one config tree, one workspace model, and one CLI surface. That makes it easier to:

- understand how the runtime behaves
- debug retrieval and tool execution
- change provider wiring
- inspect durable memory on disk

Broader platforms can offer more apps, extension surfaces, and deployment targets. `fagent` wins when clarity and control matter more than platform breadth.

### 2. Memory is layered, not monolithic

Many agents stop at one of these:

- chat history only
- embeddings plus chat history
- periodic summaries

`fagent` combines:

- file memory for transparency
- vector memory for semantic recall
- graph memory for entities and relationships
- workflow state for active execution continuity
- task graph state for goals, blockers, and decisions
- experience memory for repeated recoveries
- shadow context for pre-main-model compression
- routing logic that changes retrieval by query intent

This matters because different memory failures require different storage shapes.

### 3. Graph recall solves a different problem than vector recall

Vector recall is good at semantic similarity. It is weaker at questions like:

- what depends on what
- which decision is tied to this blocker
- which workflow node connects to this fact
- which entities should stay grouped in the current task state

`fagent` treats those as graph problems, not only text-similarity problems.

### 4. The local Graph UI is a practical debugging advantage

Graph memory is usually invisible in agent systems. `fagent` exposes it through a local Graph UI server and editor.

That means you can:

- inspect graph nodes and edges in a browser
- validate whether extraction created useful structure
- debug memory quality instead of guessing
- understand why a relationship-oriented recall happened

### 5. The main model receives guidance, not raw clutter

`fagent` can retrieve from multiple stores and compress the result into a shadow brief before the main model runs.

That changes the economics of reasoning:

- less token spend on memory search
- less wasted context on irrelevant recalled artifacts
- fewer initial “let me figure out what is going on” steps
- more direct reasoning over already filtered evidence

### 6. Tool-heavy work does not force the strongest model to fix everything

`fagent` includes a dedicated workflow tool and a separate `workflowLight` model role.

That allows the runtime to:

- execute ordered tool chains
- interpret rough workflow steps
- repair invalid steps or tool mismatches
- escalate to the main model only when needed

### 7. Subagents provide bounded delegation

`fagent` also supports subagents for background execution. This gives the main runtime a way to delegate focused tasks without flattening everything into one long monologue.

## Why this memory design beats simpler memory stacks

The advantage is not “more components” by itself. The advantage is that each component handles a specific failure mode.

- file memory helps auditability and manual inspection
- vector memory handles fuzzy semantic matching
- graph memory handles relationships
- workflow memory preserves execution state
- task graph memory keeps goal structure alive
- experience memory stops repeated rediscovery of the same fix
- shadow context reduces main-model waste
- routing reduces irrelevant retrieval

## Comparison framing

The point is not that `fagent` is universally better than larger platforms. The point is that it is optimized for a different workload:

- repeat project work
- tool-heavy engineering flows
- memory-sensitive agent behavior
- operators who want to inspect and tune the runtime

## Related docs

- [README](./README.md)
- [Docs hub](./docs/README.md)
- [Memory architecture](./docs/memory-architecture.md)
- [Graph memory and Graph UI](./docs/graph-memory-and-gui.md)
- [Subagents and workflows](./docs/subagents-and-workflows.md)
