---
name: fagent
description: Understanding fagent architecture, memory system, and key components
always: true
---

# fagent Architecture Guide

## Overview

fagent is a multi-agent system with layered memory (file, vector, graph, shadow-context), sub-agent support, and multi-channel integration (Telegram, Discord).

## Key Components

### Agent Core
- **loop.py** - Main processing loop, handles messages and tool execution
- **subagent.py** - Sub-agent spawning and management
- **context.py** - Context building for LLM prompts
- **tools/** - Agent tools (filesystem, web, memory, shell, etc.)

### Memory System
- **orchestrator.py** - Memory coordination across backends
- **graph.py** - Graph-based knowledge extraction (entities, facts, relations)
- **registry.py** - SQLite persistence layer
- **vector.py** - Vector embeddings and semantic search

### Channels
- **telegram.py** - Telegram bot integration
- **discord.py** - Discord bot integration

### Recovery
- **manager.py** - Auto-recovery after crashes
- **tracker.py** - State tracking for recovery

## Memory Architecture

### Graph Memory
- Nodes: entities, facts, episodes
- Edges: relations (mentions, decided, supersedes)
- Embeddings: semantic vectors for nodes (enables semantic search)

### Tools
- `memory_search` - Multi-backend search
- `memory_get_entity` - Retrieve graph entity (fuzzy threshold: 0.2)
- `memory_semantic_graph_search` - Semantic similarity search (NEW)

## Sub-Agent Isolation

Sub-agents are isolated from main agent:
- Metadata `_subagent_result: true` marks sub-agent messages
- Pipeline skipped for sub-agent turns (no graph writes)
- Text messages filtered in Telegram (tool calls visible)

## Configuration

### Main Config: `~/.fagent/config.json`

**Location**: `~/.fagent/config.json` (user home directory)

**Structure**:
```json
{
  "providers": {
    "anthropic": {"api_key": "sk-..."},
    "openai": {"api_key": "sk-..."},
    "openrouter": {"api_key": "sk-..."}
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4",
      "temperature": 0.7,
      "max_tokens": 4096
    }
  },
  "memory": {
    "file": {"enabled": true},
    "vector": {"enabled": true},
    "graph": {"enabled": true},
    "workflow_state": {"enabled": true}
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "bot_token",
      "allowed_users": []
    },
    "discord": {
      "enabled": false,
      "token": "bot_token"
    }
  },
  "tools": {
    "exec": {
      "enabled": true,
      "timeout": 120000
    },
    "web": {
      "brave_api_key": "key"
    }
  },
  "workspace_path": "~/.fagent/workspace"
}
```

**Key Settings**:
- `providers` - LLM API keys (Anthropic, OpenAI, OpenRouter)
- `agents.defaults.model` - Default model for agent
- `memory.*` - Enable/disable memory backends
- `channels.*` - Bot tokens and settings
- `tools.exec.timeout` - Shell command timeout (ms)
- `workspace_path` - Where to store data

**Editing Config**:
```bash
# Initialize config
fagent onboard

# View status
fagent status

# Edit manually
nano ~/.fagent/config.json
```

## File Structure

### Workspace: `~/.fagent/workspace/`

**Directory Layout**:
```
~/.fagent/workspace/
├── skills/              # User skills (override builtin)
│   └── custom-skill/
│       └── SKILL.md
├── memory/              # Memory database
│   └── registry.db      # SQLite database
├── sessions/            # Conversation history
│   └── telegram_123.json
├── prompts/             # Custom prompts (optional)
│   └── system/
│       └── custom.md
├── MEMORY.md            # Memory instructions
└── WORKSPACE.md         # Workspace notes
```

### Memory Database: `{workspace}/memory/registry.db`

**SQLite Tables**:
- `graph_nodes` - Entities, facts, episodes
- `graph_edges` - Relations between nodes
- `graph_node_embeddings` - Semantic vectors (NEW)
- `entity_aliases` - Alternative names
- `artifacts` - Stored memories
- `embedding_cache` - Vector cache
- `graph_jobs` - Indexing queue
- `workflow_snapshots` - Task state

**Accessing**:
```bash
sqlite3 ~/.fagent/workspace/memory/registry.db
.tables
SELECT * FROM graph_nodes LIMIT 5;
```

### Sessions: `{workspace}/sessions/`

**Format**: JSON files per channel:chat_id
- `telegram_123456.json` - Telegram chat history
- `discord_789012.json` - Discord chat history

**Structure**:
```json
{
  "key": "telegram:123456",
  "messages": [
    {"role": "user", "content": "Hello", "timestamp": "..."},
    {"role": "assistant", "content": "Hi!", "timestamp": "..."}
  ],
  "metadata": {
    "total_prompt_tokens": 1000,
    "total_completion_tokens": 500
  }
}
```

### Skills: `{workspace}/skills/` and `fagent/fagent/skills/`

**Priority**: Workspace > Builtin

**Builtin Skills** (`fagent/fagent/skills/`):
- `fagent/` - This architecture guide
- `github/` - GitHub CLI integration
- `cron/` - Task scheduling
- `weather/` - Weather forecasts
- `clawhub/` - Skill marketplace
- `skill-creator/` - Create new skills
- `agent-management/` - Manage agents
- `summarize/` - URL summarization
- `tmux/` - Terminal multiplexer control

**User Skills** (`~/.fagent/workspace/skills/`):
- Created by user or copied from builtin
- Override builtin skills with same name
- Automatically discovered by agent

### Documentation

**Project Docs** (`fagent/docs/`):
- `SKILLS.md` - Skills system documentation
- Other project documentation

**User Docs** (`~/.fagent/workspace/`):
- `MEMORY.md` - Memory system instructions
- `WORKSPACE.md` - Workspace notes
- Custom prompt files in `prompts/`

## Common Paths Reference

| Path | Description |
|------|-------------|
| `~/.fagent/config.json` | Main configuration |
| `~/.fagent/workspace/` | User workspace root |
| `~/.fagent/workspace/skills/` | User skills (high priority) |
| `~/.fagent/workspace/memory/registry.db` | Memory database |
| `~/.fagent/workspace/sessions/` | Chat history |
| `fagent/fagent/skills/` | Builtin skills |
| `fagent/fagent/agent/` | Agent core code |
| `fagent/fagent/memory/` | Memory system code |
| `fagent/fagent/channels/` | Channel integrations |
| `fagent/docs/` | Project documentation |
