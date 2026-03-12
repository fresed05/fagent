#!/usr/bin/env python3
"""Migrate existing graph to hierarchical tier system."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def analyze_graph(db_path: Path) -> dict:
    """Analyze graph connectivity and suggest tier assignments."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get all nodes with edge counts
    nodes = conn.execute("""
        SELECT
            n.id,
            n.label,
            COUNT(DISTINCT e1.target_id) + COUNT(DISTINCT e2.source_id) as edge_count
        FROM graph_nodes n
        LEFT JOIN graph_edges e1 ON e1.source_id = n.id
        LEFT JOIN graph_edges e2 ON e2.target_id = n.id
        GROUP BY n.id, n.label
        ORDER BY edge_count DESC
    """).fetchall()

    conn.close()

    # Assign tiers based on connectivity
    tier_assignments = []
    tier1_count = 0
    tier2_count = 0

    for node in nodes:
        edge_count = node["edge_count"]

        if edge_count >= 8 and tier1_count < 20:
            tier = 1
            tier1_count += 1
        elif edge_count >= 3:
            tier = 2
            tier2_count += 1
        else:
            tier = 3

        tier_assignments.append({
            "id": node["id"],
            "label": node["label"],
            "edge_count": edge_count,
            "tier": tier
        })

    return {
        "total_nodes": len(nodes),
        "tier1_count": tier1_count,
        "tier2_count": tier2_count,
        "tier3_count": len(nodes) - tier1_count - tier2_count,
        "assignments": tier_assignments
    }


def apply_migration(db_path: Path, assignments: list[dict]) -> None:
    """Apply tier assignments to database."""
    conn = sqlite3.connect(db_path)

    conn.executemany(
        "UPDATE graph_nodes SET tier = ? WHERE id = ?",
        [(a["tier"], a["id"]) for a in assignments]
    )

    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Migrate graph to hierarchical tier system")
    parser.add_argument("--workspace", type=Path, required=True, help="Workspace directory")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without applying")
    args = parser.parse_args()

    db_path = args.workspace / "memory" / "registry.sqlite3"

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing graph at {db_path}...")
    result = analyze_graph(db_path)

    print(f"\nGraph Analysis:")
    print(f"  Total nodes: {result['total_nodes']}")
    print(f"  Tier 1 (main concepts): {result['tier1_count']}")
    print(f"  Tier 2 (secondary): {result['tier2_count']}")
    print(f"  Tier 3 (details): {result['tier3_count']}")

    if result['tier1_count'] > 0:
        print(f"\nTier 1 nodes:")
        for a in result['assignments'][:result['tier1_count']]:
            print(f"  - {a['label']} ({a['edge_count']} edges)")

    if args.dry_run:
        print("\nDry run - no changes applied")
        return

    print("\nApplying migration...")
    apply_migration(db_path, result['assignments'])
    print("Migration complete!")


if __name__ == "__main__":
    main()
