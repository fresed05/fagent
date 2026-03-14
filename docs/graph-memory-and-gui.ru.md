# Graph memory и Graph UI

[English version](./graph-memory-and-gui.md)

Этот документ объясняет, как в `fagent` работает graph memory, что именно она хранит и почему локальный Graph UI важен на практике.

## Что даёт graph memory

Graph memory хранит долговечные сущности и связи между ними. Она дополняет file и vector memory, сохраняя структуру.

Особенно полезно для:

- зависимостей
- блокеров
- решений
- связанных workflow concepts
- сгруппированных проектных фактов

Vector memory говорит, что похоже по смыслу. Graph memory говорит, что с чем связано.

## Flow извлечения графа

Graph extraction управляется через `fagent/memory/graph.py` и координируется из `fagent/memory/orchestrator.py`.

На верхнем уровне:

1. Есть session artifact.
2. Extraction tools ищут существующее состояние графа.
3. Рантайм stage-ит entities, facts и relations.
4. Graph backend сохраняет nodes и edges.
5. Graph jobs можно потом инспектировать из CLI.

## Локальный режим и Neo4j

`fagent` поддерживает локальный graph backend и optional Neo4j mirror/backend configuration.

## Task graph и graph memory

Task graph state не совпадает полностью с общей graph memory, но они усиливают друг друга.

- task graph хранит goals, blockers, decisions и task edges
- graph memory хранит более широкие entities, facts и relations

Вместе они двигают рантайм в сторону graph-shaped continuity, а не только линейной памяти.

## Graph UI

Локальный Graph UI реализован в `fagent/memory/graph_ui.py` и поднимает browser-based graph viewer/editor.

Он умеет:

- запускать локальный HTTP server
- рендерить graph snapshots и focused views
- загружать graph overview, focus и details payloads
- создавать, обновлять и удалять graph nodes/edges
- сохранять layout positions

## Почему Graph UI важен

Он даёт человеку способ увидеть, что именно лежит в memory graph.

Это помогает:

- дебажить плохой recall
- проверять качество graph extraction
- понимать, существуют ли полезные entities и relations
- разбирать, почему произошёл relationship-oriented answer

## Graph UI — новый интерфейс (graph-ui-new)

Graph UI обновлён до современного интерфейса на React/Next.js с использованием
`react-force-graph-2d`, Tailwind CSS и Radix UI. Он заменяет старый просмотрщик
`graph_ui/` на Vanilla JS.

Что умеет новый UI:

- force-directed layout с режимами radial и hierarchical
- живая панель поиска с фильтрами по типу узла (kind)
- богатая панель деталей с соседями, рёбрами и метаданными
- отрисовка меток с учётом уровня зума (LOD)
- горячие клавиши: `R` перестроить layout, `L` показать/скрыть метки, `Esc` снять выделение
- выбор режима карты: Atlas (кластеризованный) / Raw (все узлы)
- query и session фильтр через URL или интерфейс

### Первоначальная установка

Новый UI нужно собрать один раз перед использованием:

```bash
# Требует Node.js >= 18 и npm
fagent memory graph-ui-install
```

Команда компилирует фронтенд в `fagent/static/graph-ui-new/out/`, откуда
Python-сервер раздаёт файлы.

### Автозапуск вместе с gateway

Добавьте в `config.json`, чтобы Graph UI стартовал автоматически при запуске `fagent gateway`:

```json
{
  "gateway": {
    "graph_ui": {
      "enabled": true,
      "port": 8765,
      "open_browser": false
    }
  }
}
```

Используйте `"open_browser": true`, чтобы при старте открывался браузер.

## CLI-команды

```bash
# Собрать UI (один раз после установки или обновления)
fagent memory graph-ui-install

# Запустить Graph UI сервер (по умолчанию открывает браузер)
fagent memory graph-ui
fagent memory graph-ui --query "shadow context"
fagent memory graph-ui --port 9090 --no-open

# Управление данными графа
fagent memory rebuild-graph
fagent memory inspect-graph-jobs
fagent memory inspect-task-graph cli:direct
```

## Почему это улучшает понимание и планирование

Когда агент хранит отношения как структуру, он может опираться не только на checklist.

Это важно, потому что:

- blockers остаются связанными с decisions
- entities остаются связанными с tools и workflows
- current task state остаётся связанным с supporting facts
- будущее graph-shaped planning легче автоматически обогащать

Это нужно понимать как текущее структурное преимущество, а не как заявление, что полностью автоматическое graph planning уже завершено.

## Связанные документы

- Предыдущий: [Архитектура памяти](./memory-architecture.ru.md)
- Следующий: [Subagents и workflows](./subagents-and-workflows.ru.md)
- Также см.: [CLI и observability](./cli-and-observability.ru.md)
