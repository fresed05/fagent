# Архитектура памяти

[English version](./memory-architecture.md)

Память в `fagent` изначально многослойная. Каждый слой решает свою задачу continuity, а orchestrator объединяет их до и после вызова основной модели.

## Как идёт retrieval

На верхнем уровне процесс такой:

1. Пользователь задаёт запрос.
2. Memory router определяет intent.
3. `MemoryOrchestrator` обращается к наиболее подходящим хранилищам.
4. Найденные данные ранжируются и сжимаются в shadow brief.
5. Основная модель получает этот бриф как направляющий контекст.

Ключевые модули:

- `fagent/memory/orchestrator.py`
- `fagent/memory/router.py`
- `fagent/memory/shadow.py`

## Как идёт ingestion

После одного хода `fagent` может сохранить сразу несколько артефактов:

- file-memory note или session artifact
- vector index entries
- graph extraction jobs и graph entities
- workflow snapshots
- task graph nodes и edges
- повторяющиеся experience patterns
- session summaries

## Уровни памяти

### 1. File memory

Прозрачные markdown-backed артефакты в workspace.

### 2. Vector memory

Semantic recall через embeddings.

### 3. Graph memory

Сущности и связи для структурного recall.

### 4. Workflow state

Snapshots активного execution state.

Типичные поля:

- current state
- next step
- open blockers
- citations
- tools used

### 5. Task graph

Структурное хранение goals, blockers, decisions и связей между ними.

Это текущий фундамент для graph-shaped planning. `fagent` уже хранит больше, чем линейный план; он хранит структуру задач и отношений, которую дальше можно автоматически усиливать полезными связями.

### 6. Experience memory

Повторяющиеся operational patterns, особенно repairs и recoveries.

### 7. Shadow context

Слой сжатия между сырой памятью и reasoning основной модели.

Shadow brief может включать:

- summary
- relevant facts
- open questions
- contradictions
- citations
- confidence
- store breakdown

### 8. Query-aware routing

Memory router меняет retrieval behavior по типу запроса, включая:

- temporal recall
- relationship recall
- workflow recall
- factual recall
- preference recall
- continuity
- broad synthesis
- fresh request

## Почему это экономит токены основной модели

Без такой архитектуры основная модель часто тратит токены на:

- выбор, где искать
- чтение слишком большого объёма raw history
- восстановление task state по шумным сообщениям
- стартовый разбор контекста

С `fagent` значительная часть этого делается заранее:

- router сужает поиск
- orchestrator собирает evidence
- shadow builder сжимает его
- main model стартует уже с направляющим брифом

## Связанные документы

- Предыдущий: [Почему fagent](../WHY_FAGENT.ru.md)
- Следующий: [Graph memory и Graph UI](./graph-memory-and-gui.ru.md)
- Также см.: [Subagents и workflows](./subagents-and-workflows.ru.md)
