# fagent

[English README](./README.md)

<div align="center">
  <h1>fagent: быстрый персональный AI-ассистент</h1>
</div>

`fagent` — это лёгкий фреймворк персонального AI-ассистента для CLI, чатов, автоматизации, памяти и tool-driven workflow.

## Основа проекта

Проект основан на [nanobot](https://github.com/HKUDS/nanobot). Именно nanobot дал базовую лёгкую архитектуру агента, многоканальную модель рантайма и упаковку, на которой построен `fagent`.

Что изменено в `fagent`:

- завершён ребрендинг в package/runtime/docs
- CLI переведён на визуал с молнией вместо котика
- путь конфигурации и рабочей директории стандартизирован как `~/.fagent`
- документация переписана под `fagent`, но с явной ссылкой на исходный nanobot

Если нужен апстрим-проект, смотрите [HKUDS/nanobot](https://github.com/HKUDS/nanobot).

## Что умеет fagent

- лёгкое и понятное ядро, удобное для аудита и доработки
- каналы Telegram, Discord, WhatsApp, Feishu, DingTalk, Slack, QQ, Email, Mochat и Matrix
- несколько провайдеров моделей через LiteLLM и отдельные интеграции Azure OpenAI / OpenAI Codex
- MCP-серверы для подключения внешних инструментов
- система памяти с file, vector, graph, shadow и orchestration слоями
- cron и heartbeat для регулярных задач и фоновых напоминаний
- автоматическая синхронизация шаблонов рабочего пространства
- CLI-команды для чата, статуса, OAuth-логина, memory-инспекции и bridge-настройки

## Архитектура

Лёгкий рантайм агента с CLI, каналами, инструментами, памятью и фоновыми сервисами автоматизации вокруг пакета `fagent`.

## Установка

### Клонирование через GitHub CLI

`gh` уже установлен и авторизация выполнена, поэтому достаточно:

```bash
gh repo clone HKUDS/fagent
cd fagent
pip install -e .
```

### Установка из PyPI

```bash
pip install fagent-ai
```

### Установка через uv

```bash
uv tool install fagent-ai
```

## Быстрый старт

### 1. Сгенерировать конфиг и workspace

```bash
fagent onboard
```

Команда `fagent onboard` создаёт полный конфиг в `~/.fagent/config.json`. Это не урезанный шаблон: в файле сразу будут секции channels, providers, models, tools, gateway и memory со значениями по умолчанию.

### 2. Добавить ключи

Минимальный пример:

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

### 3. Запустить диалог

```bash
fagent agent
```

Одноразовый запрос:

```bash
fagent agent -m "Summarize this repository"
```

Проверка состояния:

```bash
fagent status
```

## Каналы

| Канал | Что обычно нужно |
| --- | --- |
| Telegram | токен бота от `@BotFather` |
| Discord | bot token и message content intent |
| WhatsApp | QR-логин через локальный bridge |
| Feishu | App ID и App Secret |
| DingTalk | App Key и App Secret |
| Slack | bot token и app token |
| QQ | App ID и App Secret |
| Email | IMAP/SMTP учётные данные |
| Mochat | Claw token |
| Matrix | homeserver, user и token |

Ссылки на сообщество и QR-коды: [COMMUNICATION.md](./COMMUNICATION.md).

## Полезные CLI-команды

- `fagent onboard`
- `fagent agent`
- `fagent gateway`
- `fagent status`
- `fagent channels login`
- `fagent auth login --provider ...`
- `fagent memory ...`

## Разработка

```bash
pip install -e ".[dev]"
pytest
python -m fagent --version
fagent --version
```

## Пути по умолчанию

- конфиг: `~/.fagent/config.json`
- workspace: `~/.fagent/workspace`
- bridge: `~/.fagent/bridge`
- gateway port: `18790`

## Лицензия

[MIT](./LICENSE)
