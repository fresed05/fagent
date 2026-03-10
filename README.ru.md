# fagent

[English version](./README.md)

<div align="center">
  <h1>fagent: memory-first рантайм агента с графовой памятью</h1>
</div>

`fagent` — это graph-aware, memory-first AI runtime для долгой работы агента: многослойная память, shadow-context compression, mini-agents, workflow execution, provider/model-role routing и локальный Graph UI внутри одного прозрачного Python-стека.

## Оглавление

- [Зачем это нужно](#зачем-это-нужно)
- [Чем `fagent` отличается](#чем-fagent-отличается)
- [Архитектура в одном взгляде](#архитектура-в-одном-взгляде)
- [Быстрый старт](#быстрый-старт)
- [Ключевые CLI-команды](#ключевые-cli-команды)
- [Провайдеры и роли моделей](#провайдеры-и-роли-моделей)
- [Центр документации](#центр-документации)
- [Основан на nanobot](#основан-на-nanobot)
- [Разработка](#разработка)

## Зачем это нужно

Многие агентные стеки неплохо отвечают в одном окне чата, но теряют связность, когда работа растягивается на несколько сессий, инструментов и прерываний.

`fagent` строится вокруг другой цели:

- память должна быть многослойной, проверяемой и query-aware
- основная модель должна получать короткий рабочий бриф, а не сырой шум памяти
- связи между задачами, сущностями, блокерами и решениями должны переживать отдельные ходы
- tool-heavy workflows не должны постоянно сжигать токены главной модели на мелком ремонте и первичной ориентации

Поэтому `fagent` сочетает file memory, vector retrieval, graph memory, workflow state, task graph state, experience memory, shadow briefs и routing logic внутри самого рантайма.

## Чем `fagent` отличается

### Многослойная память вместо простой истории чата

`fagent` не считает память просто transcript-лентой. Он сочетает:

- file memory для прозрачных on-disk артефактов
- vector memory для semantic recall
- graph memory для сущностей и связей
- workflow state для снимков активного выполнения
- task graph state для целей, блокеров и решений
- experience memory для повторяющихся recoveries
- shadow context для сжатия перед вызовом основной модели
- query-aware routing, чтобы retrieval менялся по типу запроса

### Graph-aware recall вместо только vector recall

Vector search помогает с semantic similarity. Он слабее на вопросах вида:

- что от чего зависит
- какое решение породило этот blocker
- какой workflow node связан с этим фактом
- какое task state нужно держать вместе

`fagent` относится к таким вопросам как к графовой задаче, а не только как к text-search задаче. Рантайм уже хранит структуру задач и отношений, поэтому агент сохраняет не только линейный checklist. Такая graph-shaped continuity и есть база для более богатого graph planning и будущих автоматических relevance links без заявлений о несуществующей полной автоматизации.

### Shadow context направляет основную модель

До того как основная модель начинает reasoning, `fagent` может собрать память из нескольких хранилищ и сжать её в shadow brief.

За счёт этого главная модель тратит меньше токенов на:

- поиск по памяти
- восстановление task state из шумной истории
- повторное открытие уже известных фактов
- стартовые низкоценные шаги вида «сейчас разберусь, что происходит»

Вместо этого она начинает с направляющего контекста: summary, relevant facts, open questions, contradictions, citations и confidence.

### Мини-агенты и workflow-light repair уменьшают waste

`fagent` поддерживает:

- subagents для ограниченных фоновых задач
- `run_workflow` для ordered tool chains
- `workflowLight` как отдельную более лёгкую model role для repair и recovery

Это позволяет главной модели держать фокус на дорогом reasoning, пока меньшие операционные починки происходят в ограниченном execution lane.

### Локальный Graph UI делает память видимой

`fagent` поставляется с локальным Graph UI server/editor. Можно открыть graph memory в браузере, посмотреть nodes и edges и понять, почему произошёл relationship-oriented recall.

Это превращает graph memory из чёрного ящика в то, что можно инспектировать и тюнить.

## Архитектура в одном взгляде

```text
Пользователь / CLI / чат-канал
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

Ключевые implementation modules:

- `fagent/memory/orchestrator.py`
- `fagent/memory/router.py`
- `fagent/memory/shadow.py`
- `fagent/memory/graph_ui.py`
- `fagent/agent/subagent.py`
- `fagent/agent/tools/workflow.py`

## Быстрый старт

### 1. Установка

```bash
git clone https://github.com/fresed05/fagent.git
cd fagent
pip install -e .
```

Или:

```bash
pip install fagent-ai
uv tool install fagent-ai
```

### 2. Сгенерировать config и workspace

```bash
fagent onboard
```

`fagent onboard` создаёт полный default config tree в `~/.fagent/config.json` и default workspace в `~/.fagent/workspace`.

### 3. Добавить провайдера и главную роль модели

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

### 4. Запустить агента

```bash
fagent agent
fagent agent -m "Summarize this repository"
fagent status
```

### 5. Посмотреть память и графовое состояние

```bash
fagent memory doctor
fagent memory query-v2 "what blockers are connected to the current task"
fagent memory inspect-task-graph cli:direct
fagent memory inspect-experience
fagent memory rebuild-graph
```

### 6. Открыть локальный Graph UI

```bash
fagent memory graph-ui --open
fagent memory graph-ui --query "workflowLight"
```

## Ключевые CLI-команды

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

## Провайдеры и роли моделей

Provider instances отвечают за то, куда идёт трафик. Model roles отвечают за то, какая модель выполняет конкретную работу.

Ключевые встроенные роли:

- `main`
- `shadow`
- `workflowLight`
- `graphExtract`
- `graphNormalize`
- `embeddings`
- `autoSummarize`

Это позволяет делать такие схемы:

- сильная reasoning model для `main`
- более дешёвая repair model для `workflowLight`
- отдельный embedding endpoint для `embeddings`
- отдельный graph extraction profile для `graphExtract`
- отдельная summarization model для `autoSummarize`

Смотрите [docs/providers-and-model-roles.ru.md](./docs/providers-and-model-roles.ru.md) и [CONFIGURATION.ru.md](./CONFIGURATION.ru.md).

## Центр документации

Начните с этих deep-dive материалов:

- [Docs index](./docs/README.ru.md)
- [Архитектура памяти](./docs/memory-architecture.ru.md)
- [Subagents и workflows](./docs/subagents-and-workflows.ru.md)
- [Graph memory и Graph UI](./docs/graph-memory-and-gui.ru.md)
- [Провайдеры и роли моделей](./docs/providers-and-model-roles.ru.md)
- [CLI и observability](./docs/cli-and-observability.ru.md)
- [Почему fagent](./WHY_FAGENT.ru.md)
- [Конфигурация](./CONFIGURATION.ru.md)

## Основан на nanobot

Проект основан на [nanobot](https://github.com/HKUDS/nanobot), который дал лёгкую agent packaging model и multi-channel runtime foundation.

`fagent` расширяет эту базу:

- memory-first позиционированием
- graph-aware memory и локальной graph inspection
- subagents и workflow orchestration
- разделением provider/model roles
- bootstrap-потоком и runtime ergonomics вокруг `~/.fagent`

Если нужен upstream base project, смотрите [HKUDS/nanobot](https://github.com/HKUDS/nanobot). Если нужен форкнутый runtime, описанный в этом наборе документации, оставайтесь здесь.

## Разработка

```bash
pip install -e ".[dev]"
pytest
python -m fagent --version
fagent --version
fagent onboard
fagent memory doctor
```

## Примечания

- workspace по умолчанию: `~/.fagent/workspace`
- config по умолчанию: `~/.fagent/config.json`
- gateway port по умолчанию: `18790`
- WhatsApp использует локальный Node.js bridge в `~/.fagent/bridge`

## Лицензия

[MIT](./LICENSE)
