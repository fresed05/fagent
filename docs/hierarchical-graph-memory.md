# Hierarchical Graph Memory

## Overview

Three-tier hierarchical memory system with automatic node importance detection.

## Tier Levels

- **Tier 1** (Main Concepts): Core domains, 8+ edges, max 20 nodes
- **Tier 2** (Secondary): Frameworks, components, 3+ edges
- **Tier 3** (Details): Specific facts, any edge count

## Migration

```bash
# Dry run
python scripts/migrate_to_hierarchical.py --workspace .fagent --dry-run

# Apply
python scripts/migrate_to_hierarchical.py --workspace .fagent
```

## API

```python
from fagent.memory.orchestrator import MemoryOrchestrator

orchestrator = MemoryOrchestrator(workspace=Path(".fagent"))

# Analyze tier
result = await orchestrator.analyze_node_tier("entity:python")

# Reorganize
await orchestrator.reorganize_node_hierarchy(
    "entity:fastapi", new_tier=2, new_parent_ids=["entity:python"]
)

# Traverse
hierarchy = orchestrator.traverse_hierarchy("entity:fastapi", direction="both")
```

## Search with Tier Boost

```python
results = orchestrator.graph_backend.search_candidates(
    "python", tier_weights={1: 2.0, 2: 1.5, 3: 1.0}
)
```

## Visualization

```bash
python -m fagent.cli graph-ui --workspace .fagent
# Opens at http://127.0.0.1:8765
```

Visual properties:
- **Tier 1**: 40px, red (#FF6B6B), 3px stroke
- **Tier 2**: 25px, teal (#4ECDC4), 2px stroke
- **Tier 3**: 15px, green (#95E1D3), 1px stroke
