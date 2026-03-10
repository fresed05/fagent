# Memory Architecture

[Русская версия](./memory-architecture.ru.md)

`fagent` memory is layered by design. Each layer handles a different continuity problem, and the orchestrator combines them before and after the main model call.

## The retrieval flow

At a high level:

1. The user asks something.
2. The memory router classifies the request intent.
3. `MemoryOrchestrator` queries the most relevant stores.
4. Retrieved evidence is ranked and compressed into a shadow brief.
5. The main model receives that brief as guidance.

Relevant modules:

- `fagent/memory/orchestrator.py`
- `fagent/memory/router.py`
- `fagent/memory/shadow.py`

## The ingestion flow

After a turn, `fagent` can persist multiple artifacts from one interaction:

- a file-memory note or session artifact
- vector index entries
- graph extraction jobs and graph entities
- workflow snapshots
- task graph nodes and edges
- repeated experience patterns
- session summaries

## Memory levels

### 1. File memory

Transparent markdown-backed artifacts in the workspace.

Why it matters:

- human-readable fallback
- easy inspection and manual correction
- auditability when debugging retrieval quality

### 2. Vector memory

Semantic recall through embeddings.

Why it matters:

- fuzzy recall
- semantic similarity beyond exact keyword match
- useful for messy, real-world phrasing

### 3. Graph memory

Entities and relationships for structural recall.

Why it matters:

- relationship recall
- entity continuity
- decision, blocker, and dependency traversal

### 4. Workflow state

Snapshots of active execution state.

Typical contents:

- current state
- next step
- open blockers
- citations
- tools used

### 5. Task graph

Structured storage for goals, blockers, decisions, and related edges.

This is the current foundation for graph-shaped planning. `fagent` already stores more than a linear plan; it stores task and relationship structure that can later support richer automatic relevance links.

### 6. Experience memory

Repeated operational patterns, especially repairs and recoveries.

Why it matters:

- repeated failures become reusable knowledge
- the agent stops rediscovering the same fix from scratch
- recovery patterns can be ranked by evidence, not just recency

### 7. Shadow context

Compression layer between raw retrieval and main-model reasoning.

The shadow brief can include:

- summary
- relevant facts
- open questions
- contradictions
- citations
- confidence
- store breakdown

### 8. Query-aware routing

The memory router changes retrieval behavior by intent, including:

- temporal recall
- relationship recall
- workflow recall
- factual recall
- preference recall
- continuity
- broad synthesis
- fresh request

## Why this saves main-model tokens

Without this architecture, the main model often has to spend tokens on:

- deciding where to search
- reading too much raw history
- inferring task state from noisy turns
- redoing basic orientation reasoning

With `fagent`, much of that is handled before the main reasoning step:

- the router narrows the search
- the orchestrator gathers evidence
- the shadow builder compresses it
- the main model starts with a more useful brief

## Related docs

- Previous: [Why fagent](../WHY_FAGENT.md)
- Next: [Graph memory and Graph UI](./graph-memory-and-gui.md)
- Also see: [Subagents and workflows](./subagents-and-workflows.md)
