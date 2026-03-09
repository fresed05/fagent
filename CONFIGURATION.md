# fagent Configuration

This file is the practical reference for `~/.fagent/config.json`.

`fagent onboard` writes a full default config tree, so you do not need to assemble the schema by hand. This reference explains what each major section does and when to change it.

## Minimal starter config

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

## Top-level sections

- `agents`: main runtime defaults such as model, provider, workspace, temperature, and iteration limits
- `channels`: chat platform integrations and channel-level behavior
- `providers`: credentials and base URLs for model providers
- `models`: per-role model overrides for main, shadow, workflow, graph, embeddings, and auto-summary jobs
- `gateway`: gateway host, port, and heartbeat behavior
- `tools`: web, exec, workspace restriction, and MCP server definitions
- `memory`: layered memory subsystem controls

## `agents`

Example:

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.fagent/workspace",
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter",
      "maxTokens": 8192,
      "temperature": 0.1,
      "maxToolIterations": 40,
      "memoryWindow": 100,
      "reasoningEffort": null
    }
  }
}
```

Main fields:

- `workspace`: active working directory for templates, memory files, and tool work
- `model`: default chat model for the main agent loop
- `provider`: provider override; use `auto` to infer from the model or first available key
- `maxTokens`: completion cap for the main model
- `temperature`: default generation temperature
- `maxToolIterations`: upper bound for tool call loops
- `memoryWindow`: recent message window retained in chat context
- `reasoningEffort`: optional reasoning hint for providers that support it

## `providers`

Each provider entry usually accepts:

- `apiKey`
- `apiBase`
- `extraHeaders`

Example:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    },
    "custom": {
      "apiKey": "local-key",
      "apiBase": "http://localhost:8000/v1"
    },
    "azureOpenai": {
      "apiKey": "azure-key",
      "apiBase": "https://example.openai.azure.com"
    }
  }
}
```

Available provider families in the current schema include:

- `custom`
- `azureOpenai`
- `anthropic`
- `openai`
- `openrouter`
- `deepseek`
- `groq`
- `zhipu`
- `dashscope`
- `vllm`
- `gemini`
- `moonshot`
- `minimax`
- `aihubmix`
- `siliconflow`
- `volcengine`
- `openaiCodex`
- `githubCopilot`

## `models`

The `models` section lets you assign different model roles to different runtime jobs.

Supported roles:

- `main`
- `shadow`
- `graphExtract`
- `graphNormalize`
- `workflowLight`
- `embeddings`
- `autoSummarize`

Example:

```json
{
  "models": {
    "main": {
      "providerKind": "openrouter",
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192,
      "temperature": 0.1
    },
    "workflowLight": {
      "providerKind": "openrouter",
      "model": "openai/gpt-4.1-mini",
      "maxTokens": 1200,
      "temperature": 0.1
    },
    "embeddings": {
      "providerKind": "openai",
      "model": "text-embedding-3-large",
      "dimensions": 3072,
      "timeoutS": 45
    }
  }
}
```

Why this matters:

- `shadow` controls the lighter model used to compress recalled memory
- `workflowLight` controls the helper model used by `run_workflow`
- `graphExtract` and `graphNormalize` let you isolate graph-specific costs
- `embeddings` can point to a separate embedding endpoint from your main chat model

## `tools`

Example:

```json
{
  "tools": {
    "web": {
      "proxy": null,
      "search": {
        "apiKey": "",
        "maxResults": 5
      }
    },
    "exec": {
      "timeout": 60,
      "pathAppend": ""
    },
    "restrictToWorkspace": false,
    "mcpServers": {
      "filesystem": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
        "env": {},
        "toolTimeout": 30
      }
    }
  }
}
```

Key fields:

- `web.proxy`: optional HTTP/SOCKS proxy for web tools
- `web.search.apiKey`: Brave Search API key
- `exec.timeout`: shell tool timeout in seconds
- `exec.pathAppend`: additional PATH fragments for shell execution
- `restrictToWorkspace`: hard restriction for file/shell operations
- `mcpServers`: stdio, SSE, or streamable HTTP MCP server definitions

## `channels`

The `channels` section holds platform-specific config.

Global flags:

- `sendProgress`
- `sendToolHints`

Common channel pattern:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "123456:ABCDEF",
      "allowFrom": []
    },
    "discord": {
      "enabled": false,
      "token": "",
      "groupPolicy": "mention"
    }
  }
}
```

Implemented channel families:

- `whatsapp`
- `telegram`
- `discord`
- `feishu`
- `mochat`
- `dingtalk`
- `email`
- `slack`
- `qq`
- `matrix`

Typical advice:

- enable one channel first
- confirm direct CLI flow works before enabling gateway mode
- keep `allowFrom` empty only if you explicitly want broad access

## `gateway`

Example:

```json
{
  "gateway": {
    "host": "0.0.0.0",
    "port": 18790,
    "heartbeat": {
      "enabled": true,
      "intervalS": 1800
    }
  }
}
```

Use this when running long-lived channel mode with:

```bash
fagent gateway
```

## `memory`

This is one of the most important sections.

Example:

```json
{
  "memory": {
    "enabled": true,
    "shadowContext": {
      "enabled": true,
      "fastModel": "",
      "maxTokens": 400
    },
    "fileMemory": {
      "enabled": true
    },
    "vector": {
      "enabled": true,
      "backend": "embedded",
      "collection": "memory",
      "embeddingModel": "",
      "embeddingApiBase": "",
      "embeddingApiKey": "",
      "embeddingDimensions": 0,
      "embeddingExtraHeaders": {},
      "batchSize": 16,
      "requestTimeoutS": 30,
      "cacheTtlS": 0
    },
    "graph": {
      "enabled": true,
      "backend": "local",
      "groupStrategy": "workspace",
      "uri": "",
      "username": "",
      "password": ""
    },
    "ingest": {
      "asyncEnabled": true,
      "maxRetries": 3
    },
    "retrieval": {
      "topK": 5,
      "rerankEnabled": true
    },
    "backfill": {
      "batchSize": 100
    },
    "router": {
      "enabled": true,
      "defaultStrategy": "balanced",
      "rawEvidenceEscalation": true
    },
    "searchV2": {
      "enabled": true,
      "defaultTopK": 6,
      "maxRawArtifacts": 4
    },
    "workflowState": {
      "enabled": true,
      "snapshotEveryNTools": 6,
      "includeToolResults": false
    },
    "experience": {
      "enabled": true,
      "minRepeatCount": 2,
      "writePolicy": "only_repeated_patterns"
    },
    "taskGraph": {
      "enabled": true,
      "scope": "session"
    },
    "autoSummarize": {
      "enabled": true,
      "modelRole": "auto_summarize",
      "triggerRatio": 0.8,
      "maxContextTokens": 1000000,
      "minNewMessages": 12,
      "archiveMode": "archive_continue",
      "summaryMaxTokens": 1200,
      "includeOpenThreads": true
    }
  }
}
```

Practical interpretation:

- `shadowContext`: builds a compressed brief before the main model runs
- `vector`: semantic recall
- `graph`: relationship and entity recall
- `router`: query-aware retrieval routing
- `searchV2`: richer retrieval mode with intent-aware escalation
- `workflowState`: stores in-progress workflow snapshots
- `experience`: stores repeated recovery patterns
- `taskGraph`: stores goal/blocker/decision state
- `autoSummarize`: archives long sessions before context becomes bloated

## Recommended setups

### Small local setup

- one provider in `providers`
- `agents.defaults.provider` set explicitly
- `memory.vector.enabled = true`
- `memory.graph.backend = "local"`
- `tools.restrictToWorkspace = true`

### Tool-heavy engineering setup

- separate `workflowLight` model role
- separate `embeddings` role if your embedding endpoint is cheaper or faster
- `memory.workflowState.enabled = true`
- `memory.experience.enabled = true`
- `memory.router.defaultStrategy = "balanced"`

### Safer shared workspace setup

- `tools.restrictToWorkspace = true`
- narrow `allowFrom` lists on enabled channels
- keep API keys only in local config, never in tracked files

## Common commands

Bootstrap:

```bash
fagent onboard
```

Run interactive agent:

```bash
fagent agent
```

Use a specific config file:

```bash
fagent agent -c C:\\path\\to\\config.json
```

Run with a specific workspace:

```bash
fagent agent -w C:\\path\\to\\workspace
```

Check runtime status:

```bash
fagent status
```

## Security notes

- Keep secrets in `~/.fagent/config.json`, not in versioned presets.
- Treat `custom.apiBase` and MCP definitions as privileged infrastructure settings.
- Enable `restrictToWorkspace` when the agent should not read or write outside its working directory.

## Related docs

- [Why fagent](./WHY_FAGENT.md)
- [English README](./README.md)
- [Russian README](./README.ru.md)
