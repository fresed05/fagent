# Providers and Model Roles

[Русская версия](./providers-and-model-roles.ru.md)

`fagent` separates provider instances from model roles so you can tune the runtime without rewriting the whole config.

## Provider instances

A provider instance defines a concrete connection target such as:

- provider family
- API key
- API base URL
- extra headers

Examples include:

- hosted gateways
- direct vendor APIs
- local OpenAI-compatible endpoints
- multiple accounts for the same provider family

## Model profiles

Model profiles are named reusable model definitions. They let you declare one profile once and reuse it across runtime roles and MOA presets.

Typical profile fields:

- `provider`
- `model`
- `maxTokens`
- `temperature`
- `dimensions`
- `timeoutS`

## Model roles

Important roles:

- `main`
- `shadow`
- `workflowLight`
- `graphExtract`
- `graphNormalize`
- `embeddings`
- `autoSummarize`

## Why this design matters

It lets you do things like:

- use a strong model for `main`
- use a cheaper model for `workflowLight`
- isolate embedding traffic to a different endpoint
- separate graph extraction costs from chat costs
- run auto-summary on a different provider

## Recommended setups

### Small local setup

- one provider instance
- one main profile
- local graph backend
- vector memory enabled

### Cost-sensitive workflow setup

- separate `main` and `workflowLight`
- separate `embeddings`
- shadow enabled
- experience memory enabled

### Retrieval-heavy setup

- strong `shadow`
- dedicated `graphExtract`
- dedicated `embeddings`
- graph UI used for inspection

## Related docs

- Previous: [Subagents and workflows](./subagents-and-workflows.md)
- Next: [CLI and observability](./cli-and-observability.md)
- Also see: [Configuration reference](../CONFIGURATION.md)
