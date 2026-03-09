# Конфигурация fagent

Этот файл — практический справочник по `~/.fagent/config.json`.

`fagent onboard` создаёт полный конфиг по умолчанию, поэтому схему не нужно собирать вручную. Ниже разобрано, за что отвечает каждая секция и когда её стоит менять.

## Минимальный стартовый конфиг

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

## Верхние секции

- `agents`: основные runtime defaults, включая модель, провайдера, workspace и лимиты итераций
- `channels`: интеграции с чат-платформами и channel-level поведение
- `providers`: ключи и base URL для провайдеров моделей
- `models`: переопределение моделей по runtime-ролям
- `gateway`: host, port и heartbeat
- `tools`: web, exec, workspace restrictions и MCP server definitions
- `memory`: многослойная подсистема памяти

## `agents`

Пример:

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

Главные поля:

- `workspace`: рабочая директория для шаблонов, памяти и tool-work
- `model`: модель основного agent loop
- `provider`: явный провайдер или `auto`
- `maxTokens`: лимит completion для основной модели
- `temperature`: базовая температура генерации
- `maxToolIterations`: потолок tool-call цикла
- `memoryWindow`: размер недавнего окна сообщений
- `reasoningEffort`: дополнительный hint для моделей, которые это поддерживают

## `providers`

У большинства провайдеров есть:

- `apiKey`
- `apiBase`
- `extraHeaders`

Пример:

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

Доступные provider families в текущей схеме:

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

Секция `models` позволяет задавать разные model roles для разных runtime-задач.

Поддерживаемые роли:

- `main`
- `shadow`
- `graphExtract`
- `graphNormalize`
- `workflowLight`
- `embeddings`
- `autoSummarize`

Пример:

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

Почему это важно:

- `shadow` управляет лёгкой моделью для memory compression
- `workflowLight` задаёт helper-модель для `run_workflow`
- `graphExtract` и `graphNormalize` позволяют отделить graph-specific расходы
- `embeddings` можно направить на отдельный embedding endpoint

## `tools`

Пример:

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

Ключевые поля:

- `web.proxy`: HTTP/SOCKS proxy для web tools
- `web.search.apiKey`: ключ Brave Search
- `exec.timeout`: timeout shell tool в секундах
- `exec.pathAppend`: дополнительные пути в PATH
- `restrictToWorkspace`: жёсткое ограничение file/shell доступа
- `mcpServers`: конфиги для stdio, SSE или streamable HTTP MCP servers

## `channels`

Секция `channels` хранит platform-specific настройки.

Глобальные флаги:

- `sendProgress`
- `sendToolHints`

Типовой пример:

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

Реализованные channel families:

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

Практический совет:

- сначала включайте один канал
- сначала проверьте direct CLI flow, потом переходите к gateway
- не оставляйте `allowFrom` пустым, если не хотите широкий доступ

## `gateway`

Пример:

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

Это используется при долгоживущем режиме:

```bash
fagent gateway
```

## `memory`

Это одна из самых важных секций.

Пример:

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

Практический смысл:

- `shadowContext`: строит компактный brief перед вызовом основной модели
- `vector`: отвечает за semantic recall
- `graph`: отвечает за связи и entity recall
- `router`: управляет query-aware routing
- `searchV2`: включает richer retrieval mode с intent-aware escalation
- `workflowState`: сохраняет snapshot активного workflow
- `experience`: хранит повторяющиеся recovery patterns
- `taskGraph`: хранит цели, blockers и decisions
- `autoSummarize`: архивирует длинные сессии до того, как контекст раздуется

## Рекомендуемые конфигурации

### Небольшой локальный setup

- один провайдер в `providers`
- явный `agents.defaults.provider`
- `memory.vector.enabled = true`
- `memory.graph.backend = "local"`
- `tools.restrictToWorkspace = true`

### Engineering setup с большим числом tools

- отдельная model role `workflowLight`
- отдельная role `embeddings`, если endpoint для embeddings дешевле или быстрее
- `memory.workflowState.enabled = true`
- `memory.experience.enabled = true`
- `memory.router.defaultStrategy = "balanced"`

### Более безопасный shared workspace setup

- `tools.restrictToWorkspace = true`
- узкие `allowFrom` списки на включённых каналах
- API keys только в локальном конфиге, а не в tracked files

## Частые команды

Bootstrap:

```bash
fagent onboard
```

Интерактивный агент:

```bash
fagent agent
```

Запуск с конкретным конфигом:

```bash
fagent agent -c C:\\path\\to\\config.json
```

Запуск с конкретным workspace:

```bash
fagent agent -w C:\\path\\to\\workspace
```

Проверка runtime status:

```bash
fagent status
```

## Security notes

- Храните секреты в `~/.fagent/config.json`, а не в versioned presets.
- Считайте `custom.apiBase` и MCP server definitions привилегированными настройками инфраструктуры.
- Включайте `restrictToWorkspace`, если агент не должен читать и писать за пределами рабочего каталога.

## Связанные документы

- [Почему fagent](./WHY_FAGENT.md)
- [Русская версия сравнения](./WHY_FAGENT.ru.md)
- [English README](./README.md)
- [Russian README](./README.ru.md)
