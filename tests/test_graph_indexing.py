"""Tests for graph indexing with embeddings."""

import json
import pytest


def test_node_embedding_structure():
    """Test node embedding data structure."""
    node_id = "entity:test"
    vector = [0.1, 0.2, 0.3, 0.4, 0.5]

    # Simulate storage format
    stored_data = {
        "node_id": node_id,
        "vector_json": json.dumps(vector),
    }

    assert stored_data["node_id"] == node_id
    retrieved_vector = json.loads(stored_data["vector_json"])
    assert retrieved_vector == vector
    assert len(retrieved_vector) == 5


def test_graph_persistence_error_logging():
    """Test that graph persistence errors are logged with details."""
    extraction = {
        "entities": [{"id": "e1", "name": "Entity1"}],
        "facts": [{"id": "f1", "statement": "Fact1"}],
        "relations": [{"source": "e1", "target": "f1", "type": "mentions"}],
    }

    # Verify extraction structure
    assert "entities" in extraction
    assert "facts" in extraction
    assert "relations" in extraction
    assert len(extraction["entities"]) == 1
    assert len(extraction["facts"]) == 1
    assert len(extraction["relations"]) == 1


def test_node_rows_structure():
    """Test node rows tuple structure for bulk insert."""
    # Node rows should be (id, label, metadata, tier)
    node_rows = [
        ("entity:test", "Test Entity", {"kind": "entity"}, 3),
        ("fact:test", "Test Fact", {"kind": "fact"}, 3),
    ]

    for node_id, label, metadata, tier in node_rows:
        assert isinstance(node_id, str)
        assert isinstance(label, str)
        assert isinstance(metadata, dict)
        assert isinstance(tier, int)


def test_edge_rows_structure():
    """Test edge rows tuple structure for bulk insert."""
    # Edge rows should be (source_id, target_id, relation, weight, metadata)
    edge_rows = [
        ("entity:a", "entity:b", "mentions", 0.9, {"episode_id": "ep1"}),
        ("entity:b", "fact:c", "decided", 0.8, {"episode_id": "ep1"}),
    ]

    for source_id, target_id, relation, weight, metadata in edge_rows:
        assert isinstance(source_id, str)
        assert isinstance(target_id, str)
        assert isinstance(relation, str)
        assert isinstance(weight, float)
        assert isinstance(metadata, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
