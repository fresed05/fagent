from types import SimpleNamespace

import pytest

from fagent.bus.events import OutboundMessage
from fagent.bus.queue import MessageBus
from fagent.channels.telegram import TelegramChannel, _split_markdown_v2_message, _split_pre_lines
from fagent.config.schema import TelegramConfig


class _FakeHTTPXRequest:
    instances: list["_FakeHTTPXRequest"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.__class__.instances.append(self)


class _FakeUpdater:
    def __init__(self, on_start_polling) -> None:
        self._on_start_polling = on_start_polling

    async def start_polling(self, **kwargs) -> None:
        self._on_start_polling()


class _FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []
        self.edited_messages: list[dict] = []
        self._message_id = 100

    async def get_me(self):
        return SimpleNamespace(username="fagent_test")

    async def set_my_commands(self, commands) -> None:
        self.commands = commands

    async def send_message(self, **kwargs):
        self._message_id += 1
        payload = {**kwargs, "message_id": self._message_id}
        self.sent_messages.append(payload)
        return SimpleNamespace(message_id=self._message_id)

    async def edit_message_text(self, **kwargs) -> None:
        self.edited_messages.append(kwargs)


class _FakeApp:
    def __init__(self, on_start_polling) -> None:
        self.bot = _FakeBot()
        self.updater = _FakeUpdater(on_start_polling)
        self.handlers = []
        self.error_handlers = []

    def add_error_handler(self, handler) -> None:
        self.error_handlers.append(handler)

    def add_handler(self, handler) -> None:
        self.handlers.append(handler)

    async def initialize(self) -> None:
        pass

    async def start(self) -> None:
        pass


class _FakeBuilder:
    def __init__(self, app: _FakeApp) -> None:
        self.app = app
        self.token_value = None
        self.request_value = None
        self.get_updates_request_value = None

    def token(self, token: str):
        self.token_value = token
        return self

    def request(self, request):
        self.request_value = request
        return self

    def get_updates_request(self, request):
        self.get_updates_request_value = request
        return self

    def proxy(self, _proxy):
        raise AssertionError("builder.proxy should not be called when request is set")

    def get_updates_proxy(self, _proxy):
        raise AssertionError("builder.get_updates_proxy should not be called when request is set")

    def build(self):
        return self.app


@pytest.mark.asyncio
async def test_start_uses_request_proxy_without_builder_proxy(monkeypatch) -> None:
    config = TelegramConfig(
        enabled=True,
        token="123:abc",
        allow_from=["*"],
        proxy="http://127.0.0.1:7890",
    )
    bus = MessageBus()
    channel = TelegramChannel(config, bus)
    app = _FakeApp(lambda: setattr(channel, "_running", False))
    builder = _FakeBuilder(app)

    monkeypatch.setattr("fagent.channels.telegram.HTTPXRequest", _FakeHTTPXRequest)
    monkeypatch.setattr(
        "fagent.channels.telegram.Application",
        SimpleNamespace(builder=lambda: builder),
    )

    await channel.start()

    assert len(_FakeHTTPXRequest.instances) == 1
    assert _FakeHTTPXRequest.instances[0].kwargs["proxy"] == config.proxy
    assert builder.request_value is _FakeHTTPXRequest.instances[0]
    assert builder.get_updates_request_value is _FakeHTTPXRequest.instances[0]


def test_derive_topic_session_key_uses_thread_id() -> None:
    message = SimpleNamespace(
        chat=SimpleNamespace(type="supergroup"),
        chat_id=-100123,
        message_thread_id=42,
    )

    assert TelegramChannel._derive_topic_session_key(message) == "telegram:-100123:topic:42"


def test_get_extension_falls_back_to_original_filename() -> None:
    channel = TelegramChannel(TelegramConfig(), MessageBus())

    assert channel._get_extension("file", None, "report.pdf") == ".pdf"
    assert channel._get_extension("file", None, "archive.tar.gz") == ".tar.gz"


def test_is_allowed_accepts_legacy_telegram_id_username_formats() -> None:
    channel = TelegramChannel(TelegramConfig(allow_from=["12345", "alice", "67890|bob"]), MessageBus())

    assert channel.is_allowed("12345|carol") is True
    assert channel.is_allowed("99999|alice") is True
    assert channel.is_allowed("67890|bob") is True


def test_is_allowed_rejects_invalid_legacy_telegram_sender_shapes() -> None:
    channel = TelegramChannel(TelegramConfig(allow_from=["alice"]), MessageBus())

    assert channel.is_allowed("attacker|alice|extra") is False
    assert channel.is_allowed("not-a-number|alice") is False


@pytest.mark.asyncio
async def test_send_progress_keeps_message_in_topic_and_edits_single_message() -> None:
    config = TelegramConfig(enabled=True, token="123:abc", allow_from=["*"])
    channel = TelegramChannel(config, MessageBus())
    channel._app = _FakeApp(lambda: None)

    metadata = {
        "_progress": True,
        "message_thread_id": 42,
        "message_id": 10,
        "_progress_event": {
            "event": "stage",
            "stage": "Thinking",
            "status": "running",
            "content": "Checking current deployment state.",
        },
    }
    await channel.send(OutboundMessage(channel="telegram", chat_id="123", content="one", metadata=metadata))
    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="two",
            metadata={
                **metadata,
                "_progress_event": {
                    "event": "tool",
                    "stage": "Tool execution",
                    "status": "running",
                    "tool_name": "exec",
                    "arguments_preview": 'exec("systemctl status")',
                },
            },
        )
    )

    assert len(channel._app.bot.sent_messages) == 1
    assert channel._app.bot.sent_messages[0]["message_thread_id"] == 42
    assert channel._app.bot.sent_messages[0]["parse_mode"] == "HTML"
    assert len(channel._app.bot.edited_messages) == 1
    assert "exec" in channel._app.bot.edited_messages[0]["text"]


@pytest.mark.asyncio
async def test_progress_deduplicates_identical_events() -> None:
    channel = TelegramChannel(TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]), MessageBus())
    channel._app = _FakeApp(lambda: None)

    msg = OutboundMessage(
        channel="telegram",
        chat_id="123",
        content="duplicate",
        metadata={
            "_progress": True,
            "message_id": 55,
            "_progress_event": {
                "event": "tool",
                "stage": "Tool execution",
                "status": "running",
                "tool_name": "exec",
                "arguments_preview": 'exec("uptime")',
            },
        },
    )

    await channel.send(msg)
    await channel.send(msg)

    assert len(channel._app.bot.sent_messages) == 1
    assert channel._app.bot.edited_messages == []


@pytest.mark.asyncio
async def test_send_reply_infers_topic_from_message_id_cache_and_final_uses_markdown_v2() -> None:
    config = TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], reply_to_message=True)
    channel = TelegramChannel(config, MessageBus())
    channel._app = _FakeApp(lambda: None)
    channel._message_threads[("123", 10)] = 42

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="**Ready** and `safe`",
            metadata={"message_id": 10},
        )
    )

    sent = channel._app.bot.sent_messages[0]
    assert sent["message_thread_id"] == 42
    assert sent["reply_parameters"].message_id == 10
    assert sent["parse_mode"] == "MarkdownV2"


@pytest.mark.asyncio
async def test_post_turn_summary_sent_as_separate_message_after_final() -> None:
    channel = TelegramChannel(TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]), MessageBus())
    channel._app = _FakeApp(lambda: None)

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="Thinking",
            metadata={
                "_progress": True,
                "message_id": 77,
                "_progress_event": {
                    "event": "stage",
                    "stage": "Thinking",
                    "status": "running",
                    "content": "Preparing answer",
                },
            },
        )
    )
    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="Final answer",
            metadata={"message_id": 77},
        )
    )
    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="Wrote 2 artifacts",
            metadata={
                "_progress": True,
                "message_id": 77,
                "_progress_event": {
                    "event": "stage",
                    "stage": "Saving file memory",
                    "status": "ok",
                    "content": "Wrote 2 artifacts",
                },
            },
        )
    )

    assert len(channel._app.bot.sent_messages) == 3
    assert channel._app.bot.sent_messages[1]["parse_mode"] == "MarkdownV2"
    assert channel._app.bot.sent_messages[2]["parse_mode"] == "HTML"
    assert "Post-turn memory" in channel._app.bot.sent_messages[2]["text"]
    assert "Wrote 2 artifacts" in channel._app.bot.sent_messages[2]["text"]


def test_split_pre_lines_keeps_chunks_renderable() -> None:
    lines = [f"line {i} " + ("x" * 250) for i in range(40)]

    chunks = _split_pre_lines(lines, max_len=600)

    assert len(chunks) > 1
    assert all(chunk.startswith("<pre>") and chunk.endswith("</pre>") for chunk in chunks)
    assert all(len(chunk) <= 600 for chunk in chunks)


def test_split_markdown_v2_message_preserves_code_blocks_and_chunk_limit() -> None:
    text = (
        "# Deploy Result\n\n"
        "Status **ok** with `cli-proxy-api`.\n\n"
        "```bash\n"
        + "\n".join(f"echo line {i}" for i in range(60))
        + "\n```\n\n"
        + "\n".join(f"- item {i}" for i in range(60))
    )

    chunks = _split_markdown_v2_message(text, max_len=700)

    assert len(chunks) > 1
    assert all(len(chunk) <= 700 for chunk in chunks)
    assert any("```bash" in chunk for chunk in chunks)
