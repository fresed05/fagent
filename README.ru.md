# fagent

[English README](./README.md)

<div align="center">
  <h1>fagent: быстрый персональный AI-ассистент</h1>
</div>

`fagent` — это лёгкий фреймворк персонального AI-ассистента для CLI, чатов, автоматизации, памяти и tool-driven workflow.

## Дополнительная документация

- [Почему `fagent` выигрывает в практической работе](./WHY_FAGENT.md)
- [Русская версия сравнения и преимуществ](./WHY_FAGENT.ru.md)
- [Полная настройка конфига](./CONFIGURATION.md)
- [Русская версия настройки конфига](./CONFIGURATION.ru.md)

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

### Клонирование с GitHub

```bash
git clone https://github.com/fresed05/fagent.git
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
    "openrouter_main": {
      "providerKind": "openrouter",
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter_main"
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

## MOA tool

В `fagent` появился встроенный `moa` tool для mixture-of-agents сценариев. Основная модель вызывает его явно, когда нужен более сильный ответ, чем от одной модели.

`moa` отправляет один и тот же запрос нескольким named model profiles, затем передаёт их ответы отдельной judge model. Worker и judge модели могут жить на разных provider instances, включая несколько аккаунтов или gateway одного и того же provider family.

Пример:

```json
{
  "providers": {
    "openrouter_main": {
      "providerKind": "openrouter",
      "apiKey": "sk-or-v1-xxx"
    },
    "custom_local": {
      "providerKind": "custom",
      "apiKey": "local-key",
      "apiBase": "http://localhost:8000/v1"
    }
  },
  "models": {
    "profiles": {
      "opus_main": {
        "provider": "openrouter_main",
        "model": "anthropic/claude-opus-4-5"
      },
      "gemini_fast": {
        "provider": "openrouter_main",
        "model": "google/gemini-2.5-pro"
      },
      "local_reasoner": {
        "provider": "custom_local",
        "model": "gpt-5.4"
      }
    },
    "roles": {
      "main": "opus_main"
    }
  },
  "tools": {
    "moa": {
      "defaultPreset": "default",
      "presets": {
        "default": {
          "workerModels": ["opus_main", "gemini_fast", "local_reasoner"],
          "judgeModel": "opus_main",
          "parallelism": 3,
          "returnCandidates": true
        }
      }
    }
  }
}
```

## Почему `fagent` часто удобнее крупных агентных стеков

Подробная версия вынесена в [WHY_FAGENT.md](./WHY_FAGENT.md).

- `fagent` проще разворачивать и поддерживать, чем более тяжёлые платформы вроде [OpenClaw](https://github.com/openclaw/openclaw), потому что здесь один понятный Python runtime, один конфиг и одна рабочая модель workspace.
- Память здесь — это не только история сообщений. Используются file memory, vector retrieval, graph memory, workflow snapshots, task graph, experience patterns и shadow-context сжатие перед основным вызовом модели.
- Встроенный workflow tool умеет выполнять последовательность шагов и подключать более лёгкую модель для локального ремонта шага, не тратя основной контекст на каждую мелкую ошибку.

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
