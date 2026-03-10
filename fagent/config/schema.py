"""Configuration schema using Pydantic."""

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings


class Base(BaseModel):
    """Base model that accepts both camelCase and snake_case keys."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class WhatsAppConfig(Base):
    """WhatsApp channel configuration."""

    enabled: bool = False
    bridge_url: str = "ws://localhost:3001"
    bridge_token: str = ""  # Shared token for bridge auth (optional, recommended)
    allow_from: list[str] = Field(default_factory=list)  # Allowed phone numbers


class TelegramConfig(Base):
    """Telegram channel configuration."""

    enabled: bool = False
    token: str = ""  # Bot token from @BotFather
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs or usernames
    proxy: str | None = (
        None  # HTTP/SOCKS5 proxy URL, e.g. "http://127.0.0.1:7890" or "socks5://127.0.0.1:1080"
    )
    reply_to_message: bool = False  # If true, bot replies quote the original message


class FeishuConfig(Base):
    """Feishu/Lark channel configuration using WebSocket long connection."""

    enabled: bool = False
    app_id: str = ""  # App ID from Feishu Open Platform
    app_secret: str = ""  # App Secret from Feishu Open Platform
    encrypt_key: str = ""  # Encrypt Key for event subscription (optional)
    verification_token: str = ""  # Verification Token for event subscription (optional)
    allow_from: list[str] = Field(default_factory=list)  # Allowed user open_ids
    react_emoji: str = (
        "THUMBSUP"  # Emoji type for message reactions (e.g. THUMBSUP, OK, DONE, SMILE)
    )


class DingTalkConfig(Base):
    """DingTalk channel configuration using Stream mode."""

    enabled: bool = False
    client_id: str = ""  # AppKey
    client_secret: str = ""  # AppSecret
    allow_from: list[str] = Field(default_factory=list)  # Allowed staff_ids


class DiscordConfig(Base):
    """Discord channel configuration."""

    enabled: bool = False
    token: str = ""  # Bot token from Discord Developer Portal
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs
    gateway_url: str = "wss://gateway.discord.gg/?v=10&encoding=json"
    intents: int = 37377  # GUILDS + GUILD_MESSAGES + DIRECT_MESSAGES + MESSAGE_CONTENT
    group_policy: Literal["mention", "open"] = "mention"


class MatrixConfig(Base):
    """Matrix (Element) channel configuration."""

    enabled: bool = False
    homeserver: str = "https://matrix.org"
    access_token: str = ""
    user_id: str = ""  # @bot:matrix.org
    device_id: str = ""
    e2ee_enabled: bool = True  # Enable Matrix E2EE support (encryption + encrypted room handling).
    sync_stop_grace_seconds: int = (
        2  # Max seconds to wait for sync_forever to stop gracefully before cancellation fallback.
    )
    max_media_bytes: int = (
        20 * 1024 * 1024
    )  # Max attachment size accepted for Matrix media handling (inbound + outbound).
    allow_from: list[str] = Field(default_factory=list)
    group_policy: Literal["open", "mention", "allowlist"] = "open"
    group_allow_from: list[str] = Field(default_factory=list)
    allow_room_mentions: bool = False


class EmailConfig(Base):
    """Email channel configuration (IMAP inbound + SMTP outbound)."""

    enabled: bool = False
    consent_granted: bool = False  # Explicit owner permission to access mailbox data

    # IMAP (receive)
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_mailbox: str = "INBOX"
    imap_use_ssl: bool = True

    # SMTP (send)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    from_address: str = ""

    # Behavior
    auto_reply_enabled: bool = (
        True  # If false, inbound email is read but no automatic reply is sent
    )
    poll_interval_seconds: int = 30
    mark_seen: bool = True
    max_body_chars: int = 12000
    subject_prefix: str = "Re: "
    allow_from: list[str] = Field(default_factory=list)  # Allowed sender email addresses


class MochatMentionConfig(Base):
    """Mochat mention behavior configuration."""

    require_in_groups: bool = False


class MochatGroupRule(Base):
    """Mochat per-group mention requirement."""

    require_mention: bool = False


class MochatConfig(Base):
    """Mochat channel configuration."""

    enabled: bool = False
    base_url: str = "https://mochat.io"
    socket_url: str = ""
    socket_path: str = "/socket.io"
    socket_disable_msgpack: bool = False
    socket_reconnect_delay_ms: int = 1000
    socket_max_reconnect_delay_ms: int = 10000
    socket_connect_timeout_ms: int = 10000
    refresh_interval_ms: int = 30000
    watch_timeout_ms: int = 25000
    watch_limit: int = 100
    retry_delay_ms: int = 500
    max_retry_attempts: int = 0  # 0 means unlimited retries
    claw_token: str = ""
    agent_user_id: str = ""
    sessions: list[str] = Field(default_factory=list)
    panels: list[str] = Field(default_factory=list)
    allow_from: list[str] = Field(default_factory=list)
    mention: MochatMentionConfig = Field(default_factory=MochatMentionConfig)
    groups: dict[str, MochatGroupRule] = Field(default_factory=dict)
    reply_delay_mode: str = "non-mention"  # off | non-mention
    reply_delay_ms: int = 120000


class SlackDMConfig(Base):
    """Slack DM policy configuration."""

    enabled: bool = True
    policy: str = "open"  # "open" or "allowlist"
    allow_from: list[str] = Field(default_factory=list)  # Allowed Slack user IDs


class SlackConfig(Base):
    """Slack channel configuration."""

    enabled: bool = False
    mode: str = "socket"  # "socket" supported
    webhook_path: str = "/slack/events"
    bot_token: str = ""  # xoxb-...
    app_token: str = ""  # xapp-...
    user_token_read_only: bool = True
    reply_in_thread: bool = True
    react_emoji: str = "eyes"
    allow_from: list[str] = Field(default_factory=list)  # Allowed Slack user IDs (sender-level)
    group_policy: str = "mention"  # "mention", "open", "allowlist"
    group_allow_from: list[str] = Field(default_factory=list)  # Allowed channel IDs if allowlist
    dm: SlackDMConfig = Field(default_factory=SlackDMConfig)


class QQConfig(Base):
    """QQ channel configuration using botpy SDK."""

    enabled: bool = False
    app_id: str = ""  # 机器人 ID (AppID) from q.qq.com
    secret: str = ""  # 机器人密钥 (AppSecret) from q.qq.com
    allow_from: list[str] = Field(
        default_factory=list
    )  # Allowed user openids (empty = public access)




class ChannelsConfig(Base):
    """Configuration for chat channels."""

    send_progress: bool = True  # stream agent's text progress to the channel
    send_tool_hints: bool = False  # stream tool-call hints (e.g. read_file("…"))
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    mochat: MochatConfig = Field(default_factory=MochatConfig)
    dingtalk: DingTalkConfig = Field(default_factory=DingTalkConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    qq: QQConfig = Field(default_factory=QQConfig)
    matrix: MatrixConfig = Field(default_factory=MatrixConfig)


class AgentDefaults(Base):
    """Default agent configuration."""

    workspace: str = "~/.fagent/workspace"
    model: str = "anthropic/claude-opus-4-5"
    provider: str = (
        "auto"  # Provider name (e.g. "anthropic", "openrouter") or "auto" for auto-detection
    )
    max_tokens: int = 8192
    temperature: float = 0.1
    max_tool_iterations: int = 40
    memory_window: int = 100
    reasoning_effort: str | None = None  # low / medium / high — enables LLM thinking mode


class AgentsConfig(Base):
    """Agent configuration."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class ProviderInstanceConfig(Base):
    """Named provider instance configuration."""

    provider_kind: str = ""
    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None  # Custom headers (e.g. APP-Code for AiHubMix)


class ModelProfileConfig(Base):
    """Named model profile configuration."""

    provider: str | None = None
    provider_kind: str = "inherit"
    api_base: str | None = None
    api_key: str = ""
    model: str = ""
    extra_headers: dict[str, str] = Field(default_factory=dict)
    timeout_s: int = 30
    max_tokens: int = 4096
    temperature: float = 0.1
    dimensions: int | None = None


ROLE_MODEL_NAMES = (
    "main",
    "shadow",
    "graph_extract",
    "graph_normalize",
    "workflow_light",
    "embeddings",
    "auto_summarize",
)


def _default_model_profiles() -> dict[str, ModelProfileConfig]:
    return {name: ModelProfileConfig() for name in ROLE_MODEL_NAMES}


def _default_model_roles() -> dict[str, str]:
    return {name: name for name in ROLE_MODEL_NAMES}


class ModelsConfig(Base):
    """Central named model registry with backward-compatible role aliases."""

    profiles: dict[str, ModelProfileConfig] = Field(default_factory=_default_model_profiles)
    roles: dict[str, str] = Field(default_factory=_default_model_roles)

    @model_validator(mode="before")
    @classmethod
    def _migrate_old_role_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        profiles = dict(data.get("profiles") or {})
        roles = {**_default_model_roles(), **dict(data.get("roles") or {})}

        for role in ROLE_MODEL_NAMES:
            role_value = data.get(role)
            if isinstance(role_value, dict):
                profiles.setdefault(role, role_value)
                roles.setdefault(role, role)

        if not profiles:
            profiles = _default_model_profiles()
        return {"profiles": profiles, "roles": roles}

    def __getattr__(self, item: str) -> ModelProfileConfig:
        if item in self.roles:
            profile_name = self.roles[item]
            if profile_name in self.profiles:
                return self.profiles[profile_name]
        raise AttributeError(item)

    def get_profile(self, name: str) -> ModelProfileConfig | None:
        return self.profiles.get(name)

    def get_role_profile(self, role: str) -> ModelProfileConfig:
        profile_name = self.roles.get(role, role)
        profile = self.profiles.get(profile_name)
        return profile if profile is not None else ModelProfileConfig()


class ProvidersConfig(RootModel[dict[str, ProviderInstanceConfig]]):
    """Named provider instance registry."""

    root: dict[str, ProviderInstanceConfig] = Field(default_factory=dict)

    def get(
        self,
        name: str,
        default: ProviderInstanceConfig | None = None,
    ) -> ProviderInstanceConfig | None:
        return self.root.get(name, default)

    def items(self) -> Iterable[tuple[str, ProviderInstanceConfig]]:
        return self.root.items()

    def values(self) -> Iterable[ProviderInstanceConfig]:
        return self.root.values()

    def keys(self) -> Iterable[str]:
        return self.root.keys()

    def __contains__(self, item: object) -> bool:
        return item in self.root

    def __getattr__(self, item: str) -> ProviderInstanceConfig:
        try:
            return self.root[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def __iter__(self):
        return iter(self.root)


class HeartbeatConfig(Base):
    """Heartbeat service configuration."""

    enabled: bool = True
    interval_s: int = 30 * 60  # 30 minutes


class GatewayConfig(Base):
    """Gateway/server configuration."""

    host: str = "0.0.0.0"
    port: int = 18790
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


class WebSearchConfig(Base):
    """Web search tool configuration."""

    api_key: str = ""  # Brave Search API key
    max_results: int = 5


class WebToolsConfig(Base):
    """Web tools configuration."""

    proxy: str | None = (
        None  # HTTP/SOCKS5 proxy URL, e.g. "http://127.0.0.1:7890" or "socks5://127.0.0.1:1080"
    )
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ExecToolConfig(Base):
    """Shell exec tool configuration."""

    timeout: int = 60
    path_append: str = ""


class MCPServerConfig(Base):
    """MCP server connection configuration (stdio or HTTP)."""

    type: Literal["stdio", "sse", "streamableHttp"] | None = None  # auto-detected if omitted
    command: str = ""  # Stdio: command to run (e.g. "npx")
    args: list[str] = Field(default_factory=list)  # Stdio: command arguments
    env: dict[str, str] = Field(default_factory=dict)  # Stdio: extra env vars
    url: str = ""  # HTTP/SSE: endpoint URL
    headers: dict[str, str] = Field(default_factory=dict)  # HTTP/SSE: custom headers
    tool_timeout: int = 30  # seconds before a tool call is cancelled


class MoaPresetConfig(Base):
    """MOA preset configuration."""

    worker_models: list[str] = Field(default_factory=list)
    judge_model: str = ""
    parallelism: int = 3
    include_reasoning: bool = False
    return_candidates: bool = False
    worker_max_tokens: int | None = None
    judge_max_tokens: int | None = None
    temperature_override: float | None = None


class MoaToolConfig(Base):
    """Configuration for the MOA tool."""

    enabled: bool = True
    default_preset: str = "default"
    presets: dict[str, MoaPresetConfig] = Field(
        default_factory=lambda: {
            "default": MoaPresetConfig(
                worker_models=["main", "shadow", "workflow_light"],
                judge_model="main",
                parallelism=3,
            )
        }
    )


class ToolsConfig(Base):
    """Tools configuration."""

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = False  # If true, restrict all tool access to workspace directory
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)
    moa: MoaToolConfig = Field(default_factory=MoaToolConfig)


class MemoryShadowContextConfig(Base):
    """Shadow-context retrieval configuration."""

    enabled: bool = True
    fast_model: str = ""
    max_tokens: int = 400


class FileMemoryConfig(Base):
    """File memory configuration."""

    enabled: bool = True


class VectorMemoryConfig(Base):
    """Vector memory configuration."""

    enabled: bool = True
    backend: Literal["embedded"] = "embedded"
    collection: str = "memory"
    embedding_model: str = ""
    embedding_api_base: str = ""
    embedding_api_key: str = ""
    embedding_dimensions: int = 0
    embedding_extra_headers: dict[str, str] = Field(default_factory=dict)
    batch_size: int = 16
    request_timeout_s: int = 30
    cache_ttl_s: int = 0


class GraphMemoryConfig(Base):
    """Graph memory configuration."""

    enabled: bool = True
    backend: Literal["graphiti-neo4j", "local"] = "local"
    group_strategy: str = "workspace"
    uri: str = ""
    username: str = ""
    password: str = ""


class MemoryIngestConfig(Base):
    """Background ingest configuration."""

    async_enabled: bool = True
    max_retries: int = 3


class MemoryRetrievalConfig(Base):
    """Retrieval tuning configuration."""

    top_k: int = 5
    rerank_enabled: bool = True


class MemoryBackfillConfig(Base):
    """Backfill controls."""

    batch_size: int = 100


class MemoryRouterConfig(Base):
    """Query-aware routing configuration."""

    enabled: bool = True
    default_strategy: Literal["cheap", "balanced", "evidence_first"] = "balanced"
    raw_evidence_escalation: bool = True


class MemorySearchV2Config(Base):
    """Advanced memory search settings."""

    enabled: bool = True
    default_top_k: int = 6
    max_raw_artifacts: int = 4


class MemoryWorkflowStateConfig(Base):
    """Workflow snapshot controls."""

    enabled: bool = True
    snapshot_every_n_tools: int = 6
    include_tool_results: bool = False


class MemoryExperienceConfig(Base):
    """Experience memory controls."""

    enabled: bool = True
    min_repeat_count: int = 2
    write_policy: Literal["only_repeated_patterns", "all_recoveries", "manual_important"] = "only_repeated_patterns"


class MemoryTaskGraphConfig(Base):
    """Task graph controls."""

    enabled: bool = True
    scope: Literal["session", "project", "workspace"] = "session"


class MemoryAutoSummarizeConfig(Base):
    """Automatic post-turn summarization controls."""

    enabled: bool = True
    model_role: str = "auto_summarize"
    trigger_ratio: float = 0.8
    max_context_tokens: int = 1000000
    min_new_messages: int = 12
    archive_mode: Literal["archive_continue", "summary_only", "hard_rotate"] = "archive_continue"
    summary_max_tokens: int = 1200
    include_open_threads: bool = True


class MemoryConfig(Base):
    """Top-level memory subsystem configuration."""

    enabled: bool = True
    shadow_context: MemoryShadowContextConfig = Field(default_factory=MemoryShadowContextConfig)
    file_memory: FileMemoryConfig = Field(default_factory=FileMemoryConfig)
    vector: VectorMemoryConfig = Field(default_factory=VectorMemoryConfig)
    graph: GraphMemoryConfig = Field(default_factory=GraphMemoryConfig)
    ingest: MemoryIngestConfig = Field(default_factory=MemoryIngestConfig)
    retrieval: MemoryRetrievalConfig = Field(default_factory=MemoryRetrievalConfig)
    backfill: MemoryBackfillConfig = Field(default_factory=MemoryBackfillConfig)
    router: MemoryRouterConfig = Field(default_factory=MemoryRouterConfig)
    search_v2: MemorySearchV2Config = Field(default_factory=MemorySearchV2Config)
    workflow_state: MemoryWorkflowStateConfig = Field(default_factory=MemoryWorkflowStateConfig)
    experience: MemoryExperienceConfig = Field(default_factory=MemoryExperienceConfig)
    task_graph: MemoryTaskGraphConfig = Field(default_factory=MemoryTaskGraphConfig)
    auto_summarize: MemoryAutoSummarizeConfig = Field(default_factory=MemoryAutoSummarizeConfig)


class Config(BaseSettings):
    """Root configuration for fagent."""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)

    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        return Path(self.agents.defaults.workspace).expanduser()

    def _providers_by_kind(self, provider_kind: str) -> list[tuple[str, ProviderInstanceConfig]]:
        normalized = provider_kind.lower().replace("-", "_")
        return [
            (name, cfg)
            for name, cfg in self.providers.items()
            if cfg.provider_kind.lower().replace("-", "_") == normalized
        ]

    def _match_provider(
        self,
        model: str | None = None,
        forced_provider: str | None = None,
    ) -> tuple["ProviderInstanceConfig | None", str | None, str | None]:
        """Match provider instance. Returns (instance, provider_kind, instance_name)."""
        from fagent.providers.registry import PROVIDERS

        forced = forced_provider if forced_provider is not None else self.agents.defaults.provider
        if forced != "auto":
            provider = self.providers.get(forced)
            if provider:
                return provider, provider.provider_kind or forced, forced
            return None, None, None

        model_lower = (model or self.agents.defaults.model).lower()
        model_normalized = model_lower.replace("-", "_")
        model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
        normalized_prefix = model_prefix.replace("-", "_")

        def _kw_matches(kw: str) -> bool:
            kw = kw.lower()
            return kw in model_lower or kw.replace("-", "_") in model_normalized

        # Explicit provider prefix wins — prevents `github-copilot/...codex` matching openai_codex.
        for spec in PROVIDERS:
            matches = self._providers_by_kind(spec.name)
            if model_prefix and normalized_prefix == spec.name:
                if spec.is_oauth and not matches:
                    return None, spec.name, None
                for instance_name, provider in matches:
                    if spec.is_oauth or provider.api_key:
                        return provider, spec.name, instance_name

        # Match by keyword (order follows PROVIDERS registry)
        for spec in PROVIDERS:
            matches = self._providers_by_kind(spec.name)
            if any(_kw_matches(kw) for kw in spec.keywords):
                if spec.is_oauth and not matches:
                    return None, spec.name, None
                for instance_name, provider in matches:
                    if spec.is_oauth or provider.api_key:
                        return provider, spec.name, instance_name

        # Fallback: gateways first, then others (follows registry order)
        # OAuth providers are NOT valid fallbacks — they require explicit model selection
        for spec in PROVIDERS:
            if spec.is_oauth:
                continue
            for instance_name, provider in self._providers_by_kind(spec.name):
                if provider.api_key:
                    return provider, spec.name, instance_name
        return None, None, None

    def get_provider(self, model: str | None = None) -> ProviderInstanceConfig | None:
        """Get matched provider instance. Falls back to first available."""
        p, _, _ = self._match_provider(model)
        return p

    def get_provider_instance_name(self, model: str | None = None) -> str | None:
        """Get matched provider instance id for a model."""
        _, _, instance_name = self._match_provider(model)
        return instance_name

    def get_model_config(self, role: str) -> ModelProfileConfig:
        """Get explicit model-role config with inherited defaults resolved lazily by callers."""
        return self.models.get_role_profile(role)

    def resolve_model_profile(
        self,
        profile_name: str,
        fallback_model: str | None = None,
    ) -> ModelProfileConfig:
        """Resolve a named model profile into concrete settings."""
        defaults = self.agents.defaults
        profile = self.models.get_profile(profile_name)
        if profile is None and profile_name in self.models.roles:
            profile = self.models.get_role_profile(profile_name)
        resolved = (profile or ModelProfileConfig()).model_copy(deep=True)

        if not resolved.model:
            resolved.model = fallback_model or defaults.model

        provider_instance: ProviderInstanceConfig | None = None
        provider_name: str | None = None
        provider_instance_name: str | None = None
        if resolved.provider:
            provider_instance_name = resolved.provider
            provider_instance = self.providers.get(resolved.provider)
            provider_name = provider_instance.provider_kind if provider_instance else None
        else:
            provider_instance, provider_name, provider_instance_name = self._match_provider(
                resolved.model,
                forced_provider=defaults.provider if defaults.provider != "auto" else None,
            )

        if provider_instance_name and not resolved.provider:
            resolved.provider = provider_instance_name
        if resolved.provider_kind in ("", "inherit"):
            resolved.provider_kind = provider_name or "inherit"
        if provider_instance:
            if not resolved.api_key:
                resolved.api_key = provider_instance.api_key
            if not resolved.api_base:
                resolved.api_base = provider_instance.api_base or self.get_api_base(
                    resolved.model,
                    provider_override=resolved.provider,
                )
            if not resolved.extra_headers and provider_instance.extra_headers:
                resolved.extra_headers = dict(provider_instance.extra_headers)
        return resolved

    def resolve_model_role(self, role: str, fallback_model: str | None = None) -> ModelProfileConfig:
        """Resolve a runtime role to concrete settings while staying backward compatible."""
        role_cfg = self.resolve_model_profile(self.models.roles.get(role, role), fallback_model)

        if role == "embeddings":
            if not role_cfg.model:
                role_cfg.model = self.memory.vector.embedding_model
            if not role_cfg.api_base:
                role_cfg.api_base = self.memory.vector.embedding_api_base or None
            if not role_cfg.api_key:
                role_cfg.api_key = self.memory.vector.embedding_api_key
            if not role_cfg.extra_headers:
                role_cfg.extra_headers = dict(self.memory.vector.embedding_extra_headers)
            if role_cfg.dimensions is None and self.memory.vector.embedding_dimensions:
                role_cfg.dimensions = self.memory.vector.embedding_dimensions
            role_cfg.timeout_s = role_cfg.timeout_s or self.memory.vector.request_timeout_s
        return role_cfg

    def get_provider_name(self, model: str | None = None) -> str | None:
        """Get the registry name of the matched provider (e.g. "deepseek", "openrouter")."""
        _, name, _ = self._match_provider(model)
        return name

    def get_api_key(self, model: str | None = None) -> str | None:
        """Get API key for the given model. Falls back to first available key."""
        p = self.get_provider(model)
        return p.api_key if p else None

    def get_api_base(self, model: str | None = None, provider_override: str | None = None) -> str | None:
        """Get API base URL for the given model. Applies default URLs for known gateways."""
        from fagent.providers.registry import find_by_name

        p, name, _ = self._match_provider(model, forced_provider=provider_override)
        if p and p.api_base:
            return p.api_base
        # Only gateways get a default api_base here. Standard providers
        # (like Moonshot) set their base URL via env vars in _setup_env
        # to avoid polluting the global litellm.api_base.
        if name:
            spec = find_by_name(name)
            if spec and spec.is_gateway and spec.default_api_base:
                return spec.default_api_base
        return None

    model_config = ConfigDict(env_prefix="FAGENT_", env_nested_delimiter="__")
