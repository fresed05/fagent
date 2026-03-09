"""Provider factory for resolved model profiles."""

from __future__ import annotations

from fagent.config.schema import Config, ModelProfileConfig
from fagent.providers.azure_openai_provider import AzureOpenAIProvider
from fagent.providers.base import LLMProvider
from fagent.providers.custom_provider import CustomProvider
from fagent.providers.litellm_provider import LiteLLMProvider
from fagent.providers.openai_codex_provider import OpenAICodexProvider
from fagent.providers.registry import find_by_name


class ProviderFactory:
    """Build provider instances from named model profiles."""

    def __init__(self, config: Config):
        self.config = config

    def resolve_profile(
        self,
        profile_name: str,
        fallback_model: str | None = None,
    ) -> ModelProfileConfig:
        """Resolve a named model profile."""
        return self.config.resolve_model_profile(profile_name, fallback_model=fallback_model)

    def build_for_profile(
        self,
        profile_name: str,
        fallback_model: str | None = None,
    ) -> tuple[LLMProvider, ModelProfileConfig]:
        """Build a provider for a named model profile."""
        profile = self.resolve_profile(profile_name, fallback_model=fallback_model)
        return self.build_from_profile(profile), profile

    def build_main_provider(self) -> tuple[LLMProvider, ModelProfileConfig]:
        """Build the main provider from agent defaults."""
        profile = self.config.resolve_model_role("main", fallback_model=self.config.agents.defaults.model)
        if not profile.provider and self.config.agents.defaults.provider != "auto":
            profile.provider = self.config.agents.defaults.provider
        if not profile.model:
            profile.model = self.config.agents.defaults.model
        if not profile.max_tokens:
            profile.max_tokens = self.config.agents.defaults.max_tokens
        return self.build_from_profile(profile), profile

    def build_from_profile(self, profile: ModelProfileConfig) -> LLMProvider:
        """Build a provider instance from a resolved model profile."""
        provider_kind = profile.provider_kind or self.config.get_provider_name(profile.model)
        if not provider_kind or provider_kind == "inherit":
            raise ValueError(f"Unable to resolve provider for model '{profile.model}'")

        if provider_kind == "openai_codex" or profile.model.startswith("openai-codex/"):
            return OpenAICodexProvider(default_model=profile.model)

        if provider_kind == "custom":
            return CustomProvider(
                api_key=profile.api_key or "no-key",
                api_base=profile.api_base or "http://localhost:8000/v1",
                default_model=profile.model,
            )

        if provider_kind == "azure_openai":
            if not profile.api_key or not profile.api_base:
                raise ValueError("Azure OpenAI requires api_key and api_base.")
            return AzureOpenAIProvider(
                api_key=profile.api_key,
                api_base=profile.api_base,
                default_model=profile.model,
            )

        spec = find_by_name(provider_kind)
        if not profile.model.startswith("bedrock/") and not profile.api_key and not (spec and spec.is_oauth):
            raise ValueError(f"No API key configured for provider '{provider_kind}'.")

        return LiteLLMProvider(
            api_key=profile.api_key or None,
            api_base=profile.api_base,
            default_model=profile.model,
            extra_headers=profile.extra_headers or None,
            provider_name=provider_kind,
        )
