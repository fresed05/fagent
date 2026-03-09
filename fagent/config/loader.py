"""Configuration loading utilities."""

import json
from pathlib import Path

from fagent.config.schema import Config


# Global variable to store current config path (for multi-instance support)
_current_config_path: Path | None = None


def set_config_path(path: Path) -> None:
    """Set the current config path (used to derive data directory)."""
    global _current_config_path
    _current_config_path = path


def get_config_path() -> Path:
    """Get the configuration file path."""
    if _current_config_path:
        return _current_config_path
    return Path.home() / ".fagent" / "config.json"


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    path = config_path or get_config_path()

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = _migrate_config(data)
            return Config.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Warning: Failed to load config from {path}: {e}")
            print("Using default configuration.")

    return Config()


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
    """
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(by_alias=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")

    providers = data.get("providers")
    if isinstance(providers, dict):
        typed_provider_names = {
            "custom",
            "azureOpenai",
            "azure_openai",
            "anthropic",
            "openai",
            "openrouter",
            "deepseek",
            "groq",
            "zhipu",
            "dashscope",
            "vllm",
            "gemini",
            "moonshot",
            "minimax",
            "aihubmix",
            "siliconflow",
            "volcengine",
            "openaiCodex",
            "openai_codex",
            "githubCopilot",
            "github_copilot",
        }
        if any(key in typed_provider_names for key in providers):
            migrated_providers: dict[str, dict] = {}
            for name, cfg in providers.items():
                if not isinstance(cfg, dict):
                    continue
                provider_kind = (
                    name.replace("azureOpenai", "azure_openai")
                    .replace("openaiCodex", "openai_codex")
                    .replace("githubCopilot", "github_copilot")
                )
                migrated_providers[provider_kind] = {"providerKind": provider_kind, **cfg}
            data["providers"] = migrated_providers

    models = data.get("models")
    if isinstance(models, dict) and "profiles" not in models and "roles" not in models:
        profiles: dict[str, dict] = {}
        roles: dict[str, str] = {}
        for name, cfg in models.items():
            if not isinstance(cfg, dict):
                continue
            canonical = (
                name.replace("graphExtract", "graph_extract")
                .replace("graphNormalize", "graph_normalize")
                .replace("workflowLight", "workflow_light")
                .replace("autoSummarize", "auto_summarize")
            )
            profiles[canonical] = cfg
            roles[canonical] = canonical
        if profiles:
            data["models"] = {"profiles": profiles, "roles": roles}
    return data
