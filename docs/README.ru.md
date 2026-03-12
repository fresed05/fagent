# Документация fagent

[English version](./README.md)

Это documentation hub для `fagent`: graph-aware, memory-first runtime для долгой работы агента.

## Читать по задаче

- Новичку в проекте: начните с [корневого README](../README.ru.md)
- Нужен product framing: читайте [Почему fagent](../WHY_FAGENT.ru.md)
- Нужно понять continuity и экономию токенов: читайте [Архитектуру памяти](./memory-architecture.ru.md)
- Нужны bounded delegation и execution mechanics: читайте [Subagents и workflows](./subagents-and-workflows.ru.md)
- Нужны graph internals и browser GUI: читайте [Graph memory и Graph UI](./graph-memory-and-gui.ru.md)
- Нужна иерархическая графовая память с tier системой: читайте [Иерархическую графовую память](./hierarchical-graph-memory.ru.md)
- Нужны provider wiring и разделение model roles: читайте [Провайдеры и роли моделей](./providers-and-model-roles.ru.md)
- Нужны inspection-команды и runtime surfaces: читайте [CLI и observability](./cli-and-observability.ru.md)
- Нужна полная схема конфига: читайте [Конфигурацию](../CONFIGURATION.ru.md)

## Карта документации

### Product framing

- [README](../README.ru.md)
- [Почему fagent](../WHY_FAGENT.ru.md)

### Core runtime

- [Архитектура памяти](./memory-architecture.ru.md)
- [Graph memory и Graph UI](./graph-memory-and-gui.ru.md)
- [Subagents и workflows](./subagents-and-workflows.ru.md)
- [Провайдеры и роли моделей](./providers-and-model-roles.ru.md)
- [CLI и observability](./cli-and-observability.ru.md)

### Reference

- [Конфигурация](../CONFIGURATION.ru.md)
- [Communication](../COMMUNICATION.md)

## Рекомендуемый порядок чтения

1. [README](../README.ru.md)
2. [Почему fagent](../WHY_FAGENT.ru.md)
3. [Архитектура памяти](./memory-architecture.ru.md)
4. [Graph memory и Graph UI](./graph-memory-and-gui.ru.md)
5. [Subagents и workflows](./subagents-and-workflows.ru.md)
6. [Провайдеры и роли моделей](./providers-and-model-roles.ru.md)
7. [CLI и observability](./cli-and-observability.ru.md)

## На чём сфокусирован этот набор docs

Этот набор документов построен вокруг реально реализованных отличий `fagent`:

- layered memory вместо простой истории чата
- graph-aware recall вместо одного только vector recall
- shadow-context compression перед запуском основной модели
- subagents для bounded background work
- workflow execution с lighter-model repair
- локальный Graph UI для инспекции и редактирования graph memory
- provider/model-role separation для управления cost и latency

## Module anchors

Ключевые implementation modules за этими документами:

- `fagent/memory/orchestrator.py`
- `fagent/memory/router.py`
- `fagent/memory/shadow.py`
- `fagent/memory/graph_ui.py`
- `fagent/agent/subagent.py`
- `fagent/agent/tools/workflow.py`

## Связанные документы

- Предыдущий: [README](../README.ru.md)
- Следующий: [Архитектура памяти](./memory-architecture.ru.md)
- Также смотрите: [Почему fagent](../WHY_FAGENT.ru.md)
