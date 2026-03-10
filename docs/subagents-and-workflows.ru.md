# Subagents и workflows

[English version](./subagents-and-workflows.md)

В `fagent` есть два runtime-паттерна для делегированной и операционной работы:

- subagents для ограниченных фоновых задач
- workflow execution для последовательных цепочек инструментов

Они решают разные проблемы, но объединены одной целью: снизить waste в основном цикле агента.

## Subagents

Путь subagent реализован через `SubagentManager` в `fagent/agent/subagent.py`.

## Что делает subagent

Subagent может:

- принять сфокусированную задачу
- работать в фоне
- использовать ограниченный набор инструментов
- выдать итоговый результат
- вернуть краткую сводку в основной поток через message bus

## Жизненный цикл subagent

На верхнем уровне:

1. Главный рантайм создаёт subagent task.
2. Subagent получает свой prompt и ограниченный tool registry.
3. Он выполняет собственный локальный tool loop с лимитом итераций.
4. Завершается успешно или с ошибкой.
5. Результат кратко возвращается в основную беседу.

## Почему subagents важны

Они помогают, когда:

- работу можно распараллелить
- ограниченная фоновая задача не должна блокировать основной обмен
- основной модели не нужно держать все низкоуровневые промежуточные детали

## Workflows

Workflow-путь реализуется инструментом `run_workflow` в `fagent/agent/tools/workflow.py`.

## Что делает `run_workflow`

Он исполняет ordered tool steps с:

- явным `allowed_tools`
- нормализацией шагов
- выводом аргументов
- optional lighter-model help
- repair attempts
- explicit escalation control

Это не то же самое, что subagent. Workflow — это жёстко контролируемая execution lane для последовательности инструментов.

## Workflow execution loop

На верхнем уровне:

1. Передаётся цель workflow и шаги, inline или через workflow file.
2. Каждый шаг нормализуется.
3. Инструмент проверяется на соответствие `allowed_tools`.
4. Шаг исполняется.
5. При ошибке инструмент пробует heuristic repair или обращается к более лёгкой helper model.
6. Итогом становится completion, retry, escalation или fail-fast.

## Почему важен `workflowLight`

Многим tool failures не нужна сильнейшая модель. В `fagent` есть отдельная model role для более дешёвого или быстрого ремонта workflow.

Это значит, что main model не обязана тратить дорогие токены на:

- интерпретацию rough workflow syntax
- исправление malformed step
- восстановление после локального tool mismatch
- перепланирование каждой micro-failure

## Workflow repair и experience memory

Workflow repair может писать telemetry в experience memory. Повторяющиеся recoveries становятся долговременным operational knowledge.

## Когда использовать что

Используйте subagent, когда:

- работу можно отправить в фон
- задача — это bounded mini-mission
- главному потоку нужен только итоговый результат

Используйте `run_workflow`, когда:

- работа является контролируемой tool chain
- порядок шагов важен
- policy ремонта и escalation должен быть явным
- вы хотите, чтобы step execution принадлежал рантайму, а не основной модели

## Связанные документы

- Предыдущий: [Graph memory и Graph UI](./graph-memory-and-gui.ru.md)
- Следующий: [Провайдеры и роли моделей](./providers-and-model-roles.ru.md)
- Также см.: [CLI и observability](./cli-and-observability.ru.md)
