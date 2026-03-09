# fagent

[Русская версия](./README.ru.md)

<div align="center">
  <h1>fagent: Lightning-Fast Personal AI Assistant</h1>
  <p>
    <a href="https://pypi.org/project/fagent-ai/"><img src="https://img.shields.io/pypi/v/fagent-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/fagent-ai"><img src="https://static.pepy.tech/badge/fagent-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-%E2%89%A53.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/Community-Chat-5865F2" alt="Community"></a>
  </p>
</div>

`fagent` is a lightweight AI assistant framework for terminal use, chat apps, automation, memory, and tool-driven workflows.

## Deep dives

- [Why fagent wins for focused agent work](./WHY_FAGENT.md)
- [Full configuration reference](./CONFIGURATION.md)

## Built on nanobot

This project is based on [nanobot](https://github.com/HKUDS/nanobot), which originally established the lightweight agent architecture, packaging shape, and multi-channel runtime model used here.

`fagent` keeps that foundation and extends it with its own branding and operating focus:

- cleaner `fagent` naming across package, Docker, config paths, and docs
- brighter CLI presentation centered on a lightning identity
- explicit workspace/bootstrap flow through `fagent onboard`
- bundled memory, cron, MCP, and multi-provider runtime ergonomics

If you want the upstream base project, see [HKUDS/nanobot](https://github.com/HKUDS/nanobot). If you want the forked and reworked experience described in this README, stay here.

## Why fagent

- Lightweight core with a small Python surface area that is easy to inspect and modify
- Multi-channel support for Telegram, Discord, WhatsApp, Feishu, DingTalk, Slack, QQ, Email, Mochat, and Matrix
- Multi-provider runtime with LiteLLM-based gateways plus dedicated Azure OpenAI and OpenAI Codex handling
- MCP server support for external tool ecosystems
- Built-in memory stack with file, vector, graph, shadow, and orchestration layers
- Cron and heartbeat services for recurring work and unattended follow-up
- Workspace template sync for fast bootstrap of agent files and memory scaffolding
- Rich CLI workflow for direct prompting, status checks, OAuth login, bridge setup, and memory inspection

## Architecture

A lightweight agent runtime with CLI, channels, tools, memory, and background automation services built around the `fagent` package.

## Install

### Clone with GitHub CLI

`gh` is already enough here. Clone the repo directly:

```bash
gh repo clone HKUDS/fagent
cd fagent
pip install -e .
```

### Install from PyPI

```bash
pip install fagent-ai
```

### Install with uv

```bash
uv tool install fagent-ai
```

## Quick start

### 1. Bootstrap config and workspace

```bash
fagent onboard
```

`fagent onboard` generates the full default config tree in `~/.fagent/config.json`. That file includes default sections for channels, providers, models, tools, gateway, and memory, so you start from a complete schema rather than a partial sample.

### 2. Add credentials

Minimal example:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

### 3. Start chatting

```bash
fagent agent
```

Single-shot mode:

```bash
fagent agent -m "Summarize this repository"
```

Check runtime status:

```bash
fagent status
```

## Chat apps

`fagent` can connect the same agent runtime to external channels.

| Channel | Typical credential |
| --- | --- |
| Telegram | Bot token from `@BotFather` |
| Discord | Bot token and message content intent |
| WhatsApp | QR login via local bridge |
| Feishu | App ID and App Secret |
| DingTalk | App Key and App Secret |
| Slack | Bot token and app token |
| QQ | App ID and App Secret |
| Email | IMAP/SMTP credentials |
| Mochat | Claw token |
| Matrix | Homeserver, user, and token |

For community links and QR codes, see [COMMUNICATION.md](./COMMUNICATION.md).

## CLI highlights

- `fagent onboard`: create config, workspace, and default templates
- `fagent agent`: direct interactive or one-shot agent chat
- `fagent gateway`: run the long-lived channel gateway
- `fagent status`: inspect config, workspace, model, and provider readiness
- `fagent channels login`: set up the WhatsApp bridge and QR login flow
- `fagent auth login --provider ...`: OAuth login for supported providers
- `fagent memory ...`: inspect and repair memory indexes and retrieval state

## Why fagent over bigger agent stacks

For the detailed version, see [WHY_FAGENT.md](./WHY_FAGENT.md).

- `fagent` is easier to deploy and reason about than larger agent platforms such as [OpenClaw](https://github.com/openclaw/openclaw) because it stays centered on one Python runtime, one config tree, and one workspace model.
- The memory system is not just "chat history". It combines file memory, vector retrieval, graph relationships, workflow snapshots, task graph state, experience patterns, and a shadow-context compression pass before the main model runs.
- The built-in workflow tool can execute ordered tool chains and use a lighter helper model for repair/recovery, so the main model does not need to burn full-context tokens on every small operational correction.

## Development

Editable install:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Useful smoke checks:

```bash
python -m fagent --version
fagent --version
fagent onboard
```

## Notes

- Default workspace path: `~/.fagent/workspace`
- Default config path: `~/.fagent/config.json`
- Default gateway port: `18790`
- WhatsApp uses a local Node.js bridge under `~/.fagent/bridge`

## License

[MIT](./LICENSE)
