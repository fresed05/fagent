# fagent

[Русская версия](./README.ru.md)

<div align="center">
  <h1>fagent: Memory-First Agent Runtime with Graph Recall</h1>
  <p>
    <a href="https://pypi.org/project/fagent-ai/"><img src="https://img.shields.io/pypi/v/fagent-ai" alt="PyPI"></a>
    <img src="https://img.shields.io/badge/python-%E2%89%A53.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  </p>
</div>

`fagent` is a graph-aware, memory-first AI agent runtime for long-running work: layered memory, shadow-context compression, subagents, workflow execution, provider/model-role routing, and a local Graph UI in one inspectable Python stack.

## Table of contents

- [Why this exists](#why-this-exists)
- [What makes `fagent` different](#what-makes-fagent-different)
- [Architecture at a glance](#architecture-at-a-glance)
- [Quick start](#quick-start)
- [Key CLI commands](#key-cli-commands)
- [Providers and model roles](#providers-and-model-roles)
- [Documentation hub](#documentation-hub)
- [Built on nanobot](#built-on-nanobot)
- [Development](#development)

## Why this exists

Many agent stacks can answer well in a single chat window but lose coherence when work stretches across multiple sessions, tools, and interruptions.

`fagent` is built around a different target:

- memory should be layered, inspectable, and query-aware
- the main model should receive a compact working brief instead of raw memory clutter
- relationships between tasks, entities, blockers, and decisions should survive between turns
- tool-heavy workflows should not burn main-model tokens on every small repair or orientation step

That is why `fagent` combines file memory, vector retrieval, graph memory, workflow state, task graph state, experience memory, shadow briefs, and routing logic inside the runtime itself.

## What makes `fagent` different

### Layered memory instead of plain chat history

`fagent` does not treat memory as only a transcript. It combines:

- file memory for transparent on-disk artifacts
- vector memory for semantic recall
- graph memory for entities and relationships
- workflow state for in-progress execution snapshots
- task graph state for goals, blockers, and decisions
- experience memory for repeated recoveries
- shadow context for compression before the main model runs
- query-aware routing so retrieval changes by intent

### Graph-aware recall instead of only vector recall

Vector search helps with semantic similarity. It is weaker at questions like:

- what depends on what
- which decision caused this blocker
- which workflow node relates to this fact
- which task state should remain grouped

`fagent` treats those as graph problems, not just text-search problems. The runtime already stores task and relationship structure, so the agent preserves more than a linear checklist. That graph-shaped continuity is the foundation for richer graph planning and future automatic relevance links without overstating that full automation already exists.

### Shadow context guides the main model

Before the main model reasons, `fagent` can retrieve memory from multiple stores and compress it into a shadow brief.

That means the main model spends fewer tokens on:

- searching memory
- reconstructing task state from noisy history
- re-discovering known facts
- initial low-value “figure out what is going on” steps

Instead, it starts with directed context: summary, relevant facts, open questions, contradictions, citations, and confidence.

### Mini-agents and workflow-light repair reduce waste

`fagent` supports:

- subagents for bounded background tasks
- `run_workflow` for ordered tool chains
- `workflowLight` as a separate lighter model role for repair and recovery

This lets the main model stay focused on high-value reasoning while smaller operational fixes happen in a constrained execution lane.

### Local Graph UI makes memory visible

`fagent` ships with a local Graph UI server/editor. You can open graph memory in a browser, inspect nodes and edges, and debug why relationship-oriented recall happened.

That turns graph memory from a black box into something you can inspect and tune.

## Architecture at a glance

```text
User / CLI / Chat channel
          |
          v
    Main Agent Loop
          |
          +--> Tool Registry
          |      +--> shell / web / files / MCP / workflow / moa / spawn
          |
          +--> Memory Orchestrator
          |      +--> file memory
          |      +--> vector memory
          |      +--> graph memory
          |      +--> workflow state
          |      +--> task graph
          |      +--> experience patterns
          |      +--> shadow brief builder
          |      +--> query-aware router
          |
          +--> Subagent Manager
          |
          +--> Provider / Model Role Resolver
                 +--> main / shadow / workflowLight / graphExtract / graphNormalize / embeddings / autoSummarize
```

Core implementation modules:

- `fagent/memory/orchestrator.py`
- `fagent/memory/router.py`
- `fagent/memory/shadow.py`
- `fagent/memory/graph_ui.py`
- `fagent/agent/subagent.py`
- `fagent/agent/tools/workflow.py`

## Quick start

### 1. Install

Clone and install:

```bash
git clone https://github.com/fresed05/fagent.git
cd fagent
pip install -e .
```

Or install from PyPI:

```bash
pip install fagent-ai
uv tool install fagent-ai
```

### 2. Bootstrap config and workspace

```bash
fagent onboard
```

`fagent onboard` writes the full default config tree to `~/.fagent/config.json` and creates the default workspace under `~/.fagent/workspace`.

### 3. Add a provider and a main model role

```json
{
  "providers": {
    "openrouter_main": {
      "providerKind": "openrouter",
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "models": {
    "profiles": {
      "opus_main": {
        "provider": "openrouter_main",
        "model": "anthropic/claude-opus-4-5"
      }
    },
    "roles": {
      "main": "opus_main"
    }
  }
}
```

### 4. Start the agent

```bash
fagent agent
fagent agent -m "Summarize this repository"
fagent status
```

### 5. Inspect memory and graph state

```bash
fagent memory doctor
fagent memory query-v2 "what blockers are connected to the current task"
fagent memory inspect-task-graph cli:direct
fagent memory inspect-experience
fagent memory rebuild-graph
```

### 6. Open the local Graph UI

```bash
fagent memory graph-ui --open
fagent memory graph-ui --query "workflowLight"
```

## Key CLI commands

- `fagent onboard`
- `fagent agent`
- `fagent gateway`
- `fagent status`
- `fagent auth login --provider ...`
- `fagent channels login`
- `fagent memory doctor`
- `fagent memory query-v2`
- `fagent memory inspect-task-graph`
- `fagent memory inspect-experience`
- `fagent memory rebuild-graph`
- `fagent memory graph-ui`

## Providers and model roles

Provider instances describe where traffic goes. Model roles describe which model handles which kind of work.

Important built-in roles:

- `main`
- `shadow`
- `workflowLight`
- `graphExtract`
- `graphNormalize`
- `embeddings`
- `autoSummarize`

This allows setups such as:

- strong reasoning model for `main`
- cheaper repair model for `workflowLight`
- separate embedding endpoint for `embeddings`
- separate graph extraction profile for `graphExtract`
- different summarization model for `autoSummarize`

See [docs/providers-and-model-roles.md](./docs/providers-and-model-roles.md) and [CONFIGURATION.md](./CONFIGURATION.md).

## Documentation hub

Start here for deeper guides:

- [Docs index](./docs/README.md)
- [Memory architecture](./docs/memory-architecture.md)
- [Subagents and workflows](./docs/subagents-and-workflows.md)
- [Graph memory and Graph UI](./docs/graph-memory-and-gui.md)
- [Providers and model roles](./docs/providers-and-model-roles.md)
- [CLI and observability](./docs/cli-and-observability.md)
- [Why fagent](./WHY_FAGENT.md)
- [Configuration reference](./CONFIGURATION.md)

## Built on nanobot

This project is based on [nanobot](https://github.com/HKUDS/nanobot), which established the lightweight agent packaging and multi-channel runtime foundation used here.

`fagent` extends that base with:

- memory-first positioning
- graph-aware memory and local graph inspection
- subagents and workflow orchestration
- provider/model-role separation
- workspace bootstrap and runtime ergonomics around `~/.fagent`

If you want the upstream base project, see [HKUDS/nanobot](https://github.com/HKUDS/nanobot). If you want the forked runtime described in this documentation set, stay here.

## Development

```bash
pip install -e ".[dev]"
pytest
python -m fagent --version
fagent --version
fagent onboard
fagent memory doctor
```

## Notes

- default workspace path: `~/.fagent/workspace`
- default config path: `~/.fagent/config.json`
- default gateway port: `18790`
- WhatsApp uses a local Node.js bridge under `~/.fagent/bridge`

## License

[MIT](./LICENSE)
