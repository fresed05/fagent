# Иерархическая графовая память

## Обзор

Трехуровневая иерархическая система памяти с автоматическим определением важности узлов.

## Уровни tier

- **Tier 1** (Главные концепции): Основные домены, 8+ связей, макс 20 узлов
- **Tier 2** (Второстепенные): Фреймворки, компоненты, 3+ связей
- **Tier 3** (Детали): Конкретные факты, любое количество связей

## Миграция

```bash
# Предпросмотр
python scripts/migrate_to_hierarchical.py --workspace .fagent --dry-run

# Применить
python scripts/migrate_to_hierarchical.py --workspace .fagent
```

## API

```python
from fagent.memory.orchestrator import MemoryOrchestrator

orchestrator = MemoryOrchestrator(workspace=Path(".fagent"))

# Анализ tier
result = await orchestrator.analyze_node_tier("entity:python")

# Реорганизация
await orchestrator.reorganize_node_hierarchy(
    "entity:fastapi", new_tier=2, new_parent_ids=["entity:python"]
)

# Обход иерархии
hierarchy = orchestrator.traverse_hierarchy("entity:fastapi", direction="both")
```

## Поиск с приоритетом tier

```python
results = orchestrator.graph_backend.search_candidates(
    "python", tier_weights={1: 2.0, 2: 1.5, 3: 1.0}
)
```

## Визуализация

```bash
python -m fagent.cli graph-ui --workspace .fagent
# Откроется на http://127.0.0.1:8765
```

Визуальные свойства:
- **Tier 1**: 40px, красный (#FF6B6B), обводка 3px
- **Tier 2**: 25px, бирюзовый (#4ECDC4), обводка 2px
- **Tier 3**: 15px, зеленый (#95E1D3), обводка 1px
