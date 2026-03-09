from fagent.config.schema import Config


def test_resolve_embeddings_role_prefers_role_override() -> None:
    config = Config()
    config.memory.vector.embedding_model = "fallback-embed"
    config.models.embeddings.model = "embed-large"
    config.models.embeddings.api_base = "https://emb.example/v1"
    config.models.embeddings.api_key = "secret"
    config.models.embeddings.dimensions = 1536

    resolved = config.resolve_model_role("embeddings")

    assert resolved.model == "embed-large"
    assert resolved.api_base == "https://emb.example/v1"
    assert resolved.api_key == "secret"
    assert resolved.dimensions == 1536


def test_resolve_non_embedding_role_falls_back_to_agent_defaults() -> None:
    config = Config()
    config.agents.defaults.model = "custom/model"

    resolved = config.resolve_model_role("shadow")

    assert resolved.model == "custom/model"
