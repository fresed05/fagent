# CLI и observability

[English version](./cli-and-observability.md)

`fagent` даёт практичный CLI для runtime health, memory inspection, graph inspection и доступа к Graph UI.

## Основные runtime-команды

```bash
fagent onboard
fagent agent
fagent gateway
fagent status
```

## Команды для инспекции памяти

Реально реализованные команды памяти включают:

```bash
fagent memory doctor
fagent memory query-v2 "current blockers"
fagent memory inspect-task-graph cli:direct
fagent memory inspect-experience
fagent memory rebuild-graph
fagent memory inspect-graph-jobs
fagent memory graph-ui --open
```

## Что смотреть, если что-то ощущается неправильным

### Плохой recall

Проверьте:

- `fagent memory query-v2`
- `fagent memory inspect-graph-jobs`
- `fagent memory graph-ui`

### Потеря continuity задачи

Проверьте:

- `fagent memory inspect-task-graph`
- workflow snapshots и session summaries

### Повторяющиеся workflow failures

Проверьте:

- `fagent memory inspect-experience`
- workflow repair behavior и конфигурацию `workflowLight`

## Graph UI как поверхность наблюдаемости

Используйте его, чтобы:

- видеть плотность связей
- подтверждать качество graph extraction
- смотреть focused subgraphs
- проверять, должен ли существовать конкретный node или edge

## Видимость runtime stages

CLI также показывает стадии работы памяти:

- сохранение file memory
- построение graph
- запись vectors
- summarization сессии

## Связанные документы

- Предыдущий: [Провайдеры и роли моделей](./providers-and-model-roles.ru.md)
- Следующий: [Docs index](./README.ru.md)
- Также см.: [Конфигурация](../CONFIGURATION.ru.md)
