# Провайдеры и роли моделей

[English version](./providers-and-model-roles.md)

`fagent` разделяет provider instances и model roles, чтобы можно было настраивать рантайм без переписывания всего конфига.

## Provider instances

Provider instance определяет конкретную точку подключения:

- семейство провайдера
- API key
- API base URL
- extra headers

Примеры:

- hosted gateways
- прямые vendor API
- локальные OpenAI-compatible endpoints
- несколько аккаунтов одного provider family

## Model profiles

Model profiles — это именованные переиспользуемые определения моделей.

Типичные поля:

- `provider`
- `model`
- `maxTokens`
- `temperature`
- `dimensions`
- `timeoutS`

## Model roles

Ключевые роли:

- `main`
- `shadow`
- `workflowLight`
- `graphExtract`
- `graphNormalize`
- `embeddings`
- `autoSummarize`

## Почему это важно

Такая схема позволяет:

- использовать сильную модель для `main`
- поставить более дешёвую для `workflowLight`
- вынести embeddings на отдельный endpoint
- отделить стоимость graph extraction от chat cost
- запускать auto-summary на другом провайдере

## Рекомендуемые схемы

### Маленькая локальная схема

- один provider instance
- один main profile
- локальный graph backend
- включённая vector memory

### Workflow-heavy, cost-sensitive схема

- отдельные `main` и `workflowLight`
- отдельный `embeddings`
- включённый shadow
- включённая experience memory

### Retrieval-heavy схема

- сильный `shadow`
- отдельный `graphExtract`
- отдельный `embeddings`
- активное использование Graph UI для инспекции

## Связанные документы

- Предыдущий: [Subagents и workflows](./subagents-and-workflows.ru.md)
- Следующий: [CLI и observability](./cli-and-observability.ru.md)
- Также см.: [Конфигурация](../CONFIGURATION.ru.md)
