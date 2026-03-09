from fagent.config.loader import _migrate_config
from fagent.config.schema import Config
from fagent.providers.azure_openai_provider import AzureOpenAIProvider
from fagent.providers.custom_provider import CustomProvider
from fagent.providers.factory import ProviderFactory
from fagent.providers.litellm_provider import LiteLLMProvider
from fagent.providers.openai_codex_provider import OpenAICodexProvider


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


def test_migrate_legacy_provider_and_model_shape() -> None:
    migrated = _migrate_config(
        {
            "providers": {
                "openrouter": {"apiKey": "sk-or-v1-test"},
                "custom": {"apiKey": "local-key", "apiBase": "http://localhost:8000/v1"},
            },
            "models": {
                "main": {"model": "anthropic/claude-opus-4-5"},
                "workflowLight": {"model": "openai/gpt-4.1-mini"},
            },
        }
    )

    assert migrated["providers"]["openrouter"]["providerKind"] == "openrouter"
    assert migrated["providers"]["custom"]["providerKind"] == "custom"
    assert migrated["models"]["profiles"]["workflow_light"]["model"] == "openai/gpt-4.1-mini"
    assert migrated["models"]["roles"]["main"] == "main"


def test_provider_factory_builds_custom_provider() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "custom_local": {
                    "providerKind": "custom",
                    "apiKey": "local-key",
                    "apiBase": "http://localhost:8000/v1",
                }
            },
            "models": {
                "profiles": {
                    "local_chat": {
                        "provider": "custom_local",
                        "model": "gpt-5.4",
                    }
                }
            },
        }
    )

    provider, profile = ProviderFactory(config).build_for_profile("local_chat")

    assert isinstance(provider, CustomProvider)
    assert profile.provider_kind == "custom"


def test_provider_factory_builds_litellm_provider() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "router_primary": {
                    "providerKind": "openrouter",
                    "apiKey": "sk-or-v1-test",
                }
            },
            "models": {
                "profiles": {
                    "judge": {
                        "provider": "router_primary",
                        "model": "anthropic/claude-opus-4-5",
                    }
                }
            },
        }
    )

    provider, profile = ProviderFactory(config).build_for_profile("judge")

    assert isinstance(provider, LiteLLMProvider)
    assert profile.provider_kind == "openrouter"


def test_provider_factory_builds_azure_provider() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "azure_prod": {
                    "providerKind": "azure_openai",
                    "apiKey": "azure-key",
                    "apiBase": "https://example.openai.azure.com",
                }
            },
            "models": {
                "profiles": {
                    "azure_chat": {
                        "provider": "azure_prod",
                        "model": "deployment-name",
                    }
                }
            },
        }
    )

    provider, _ = ProviderFactory(config).build_for_profile("azure_chat")

    assert isinstance(provider, AzureOpenAIProvider)


def test_provider_factory_builds_openai_codex_provider() -> None:
    config = Config.model_validate(
        {
            "models": {
                "profiles": {
                    "codex": {
                        "providerKind": "openai_codex",
                        "model": "openai-codex/gpt-5.1-codex",
                    }
                }
            }
        }
    )

    provider, _ = ProviderFactory(config).build_for_profile("codex")

    assert isinstance(provider, OpenAICodexProvider)
