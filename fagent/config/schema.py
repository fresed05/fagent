"""Configuration schema using Pydantic."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
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


class ProviderConfig(Base):
    """LLM provider configuration."""

    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None  # Custom headers (e.g. APP-Code for AiHubMix)


class ModelRoleConfig(Base):
    """Explicit model settings for one runtime role."""

    provider_kind: str = "inherit"
    api_base: str | None = None
    api_key: str = ""
    model: str = ""
    extra_headers: dict[str, str] = Field(default_factory=dict)
    timeout_s: int = 30
    max_tokens: int = 4096
    temperature: float = 0.1
    dimensions: int | None = None


class ModelsConfig(Base):
    """Central model registry for runtime roles."""

    main: ModelRoleConfig = Field(default_factory=ModelRoleConfig)
    shadow: ModelRoleConfig = Field(default_factory=ModelRoleConfig)
    graph_extract: ModelRoleConfig = Field(default_factory=ModelRoleConfig)
    graph_normalize: ModelRoleConfig = Field(default_factory=ModelRoleConfig)
    workflow_light: ModelRoleConfig = Field(default_factory=ModelRoleConfig)
    embeddings: ModelRoleConfig = Field(default_factory=ModelRoleConfig)
    auto_summarize: ModelRoleConfig = Field(default_factory=ModelRoleConfig)


class ProvidersConfig(Base):
    """Configuration for LLM providers."""

    custom: ProviderConfig = Field(default_factory=ProviderConfig)  # Any OpenAI-compatible endpoint
    azure_openai: ProviderConfig = Field(default_factory=ProviderConfig)  # Azure OpenAI (model = deployment name)
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    dashscope: ProviderConfig = Field(default_factory=ProviderConfig)  # 阿里云通义千问
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax: ProviderConfig = Field(default_factory=ProviderConfig)
    aihubmix: ProviderConfig = Field(default_factory=ProviderConfig)  # AiHubMix API gateway
    siliconflow: ProviderConfig = Field(default_factory=ProviderConfig)  # SiliconFlow (硅基流动)
    volcengine: ProviderConfig = Field(default_factory=ProviderConfig)  # VolcEngine (火山引擎)
    openai_codex: ProviderConfig = Field(default_factory=ProviderConfig)  # OpenAI Codex (OAuth)
    github_copilot: ProviderConfig = Field(default_factory=ProviderConfig)  # Github Copilot (OAuth)


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


class ToolsConfig(Base):
    """Tools configuration."""

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = False  # If true, restrict all tool access to workspace directory
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


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

    def _match_provider(
        self, model: str | None = None
    ) -> tuple["ProviderConfig | None", str | None]:
        """Match provider config and its registry name. Returns (config, spec_name)."""
        from fagent.providers.registry import PROVIDERS

        forced = self.agents.defaults.provider
        if forced != "auto":
            p = getattr(self.providers, forced, None)
            return (p, forced) if p else (None, None)

        model_lower = (model or self.agents.defaults.model).lower()
        model_normalized = model_lower.replace("-", "_")
        model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
        normalized_prefix = model_prefix.replace("-", "_")

        def _kw_matches(kw: str) -> bool:
            kw = kw.lower()
            return kw in model_lower or kw.replace("-", "_") in model_normalized

        # Explicit provider prefix wins — prevents `github-copilot/...codex` matching openai_codex.
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and model_prefix and normalized_prefix == spec.name:
                if spec.is_oauth or p.api_key:
                    return p, spec.name

        # Match by keyword (order follows PROVIDERS registry)
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and any(_kw_matches(kw) for kw in spec.keywords):
                if spec.is_oauth or p.api_key:
                    return p, spec.name

        # Fallback: gateways first, then others (follows registry order)
        # OAuth providers are NOT valid fallbacks — they require explicit model selection
        for spec in PROVIDERS:
            if spec.is_oauth:
                continue
            p = getattr(self.providers, spec.name, None)
            if p and p.api_key:
                return p, spec.name
        return None, None

    def get_provider(self, model: str | None = None) -> ProviderConfig | None:
        """Get matched provider config (api_key, api_base, extra_headers). Falls back to first available."""
        p, _ = self._match_provider(model)
        return p

    def get_model_config(self, role: str) -> ModelRoleConfig:
        """Get explicit model-role config with inherited defaults resolved lazily by callers."""
        return getattr(self.models, role, ModelRoleConfig())

    def resolve_model_role(self, role: str, fallback_model: str | None = None) -> ModelRoleConfig:
        """Resolve a runtime role to concrete settings while staying backward compatible."""
        role_cfg = self.get_model_config(role).model_copy(deep=True)
        defaults = self.agents.defaults

        if not role_cfg.model:
            role_cfg.model = fallback_model or defaults.model
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

        if role_cfg.provider_kind in ("", "inherit"):
            matched = self.get_provider(role_cfg.model)
            provider_name = self.get_provider_name(role_cfg.model)
            role_cfg.provider_kind = provider_name or "inherit"
            if matched:
                if not role_cfg.api_key:
                    role_cfg.api_key = matched.api_key
                if not role_cfg.api_base:
                    role_cfg.api_base = self.get_api_base(role_cfg.model)
                if not role_cfg.extra_headers and matched.extra_headers:
                    role_cfg.extra_headers = dict(matched.extra_headers)
        return role_cfg

    def get_provider_name(self, model: str | None = None) -> str | None:
        """Get the registry name of the matched provider (e.g. "deepseek", "openrouter")."""
        _, name = self._match_provider(model)
        return name

    def get_api_key(self, model: str | None = None) -> str | None:
        """Get API key for the given model. Falls back to first available key."""
        p = self.get_provider(model)
        return p.api_key if p else None

    def get_api_base(self, model: str | None = None) -> str | None:
        """Get API base URL for the given model. Applies default URLs for known gateways."""
        from fagent.providers.registry import find_by_name

        p, name = self._match_provider(model)
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
