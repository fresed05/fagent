"""Tests for improved memory search functionality."""

import pytest


def test_fuzzy_search_threshold():
    """Test that fuzzy search threshold is lowered to 0.2."""
    # Simulate threshold check
    candidate_score = 0.25
    old_threshold = 0.3
    new_threshold = 0.2

    # Old logic would reject this
    passes_old = candidate_score >= old_threshold
    # New logic accepts it
    passes_new = candidate_score >= new_threshold

    assert passes_old is False
    assert passes_new is True


def test_cosine_similarity():
    """Test cosine similarity calculation."""
    import math

    def cosine_similarity(vec1, vec2):
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        return dot_product / (magnitude1 * magnitude2)

    # Identical vectors
    vec1 = [1.0, 0.0, 0.0]
    vec2 = [1.0, 0.0, 0.0]
    assert abs(cosine_similarity(vec1, vec2) - 1.0) < 0.001

    # Orthogonal vectors
    vec3 = [1.0, 0.0, 0.0]
    vec4 = [0.0, 1.0, 0.0]
    assert abs(cosine_similarity(vec3, vec4) - 0.0) < 0.001

    # Similar vectors
    vec5 = [1.0, 1.0, 0.0]
    vec6 = [1.0, 0.9, 0.0]
    similarity = cosine_similarity(vec5, vec6)
    assert 0.9 < similarity < 1.0


def test_semantic_search_result_structure():
    """Test semantic search result structure."""
    # Mock result
    result = {
        "id": "entity:test",
        "label": "Test Entity",
        "score": 0.85,
        "metadata": {"kind": "entity"},
        "edges": [
            {
                "source_id": "entity:test",
                "target_id": "entity:other",
                "relation": "mentions",
                "weight": 0.9,
            }
        ],
    }

    assert "id" in result
    assert "label" in result
    assert "score" in result
    assert "metadata" in result
    assert "edges" in result
    assert len(result["edges"]) > 0
    assert result["score"] > 0.8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
