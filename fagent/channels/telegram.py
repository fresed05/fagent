"""Telegram channel implementation using python-telegram-bot."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from html import escape as html_escape
import re
import unicodedata

from loguru import logger
from telegram import BotCommand, ReplyParameters, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.helpers import escape_markdown
from telegram.request import HTTPXRequest

from fagent.bus.events import OutboundMessage
from fagent.bus.queue import MessageBus
from fagent.channels.base import BaseChannel
from fagent.config.paths import get_media_dir
from fagent.config.schema import TelegramConfig
from fagent.utils.helpers import split_message

TELEGRAM_MAX_MESSAGE_LEN = 4000
TELEGRAM_RENDER_LIMIT = 3800
POST_TURN_STAGES = {
    "Updating file notes",
    "Building graph",
    "Writing vectors",
    "Summarizing session",
}
POST_TURN_LABELS = {
    "Updating file notes": "Notes",
    "Building graph": "Graph",
    "Writing vectors": "Vector",
    "Summarizing session": "Summary",
}
POST_TURN_ICONS = {
    "Saving file memory": "🗂️",
    "Building graph": "🕸️",
    "Writing vectors": "📦",
    "Summarizing session": "📝",
}


@dataclass(slots=True)
class _TelegramTurnState:
    progress_message_id: int | None = None
    progress_lines: list[str] = field(default_factory=list)
    archived_progress_lines: list[str] = field(default_factory=list)
    last_progress_fingerprint: str = ""
    final_sent: bool = False
    post_turn_summary: dict[str, str] = field(default_factory=dict)
    post_turn_message_id: int | None = None


def _strip_md(s: str) -> str:
    """Strip markdown inline formatting from text."""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"__(.+?)__", r"\1", s)
    s = re.sub(r"~~(.+?)~~", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    return s.strip()


def _render_table_box(table_lines: list[str]) -> str:
    """Convert markdown pipe-table to compact aligned text for monospaced display."""

    def dw(s: str) -> int:
        return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)

    rows: list[list[str]] = []
    has_sep = False
    for line in table_lines:
        cells = [_strip_md(c) for c in line.strip().strip("|").split("|")]
        if all(re.match(r"^:?-+:?$", c) for c in cells if c):
            has_sep = True
            continue
        rows.append(cells)
    if not rows or not has_sep:
        return "\n".join(table_lines)

    ncols = max(len(r) for r in rows)
    for row in rows:
        row.extend([""] * (ncols - len(row)))
    widths = [max(dw(row[c]) for row in rows) for c in range(ncols)]

    def dr(cells: list[str]) -> str:
        return "  ".join(f"{c}{' ' * (w - dw(c))}" for c, w in zip(cells, widths))

    out = [dr(rows[0])]
    out.append("  ".join("─" * w for w in widths))
    for row in rows[1:]:
        out.append(dr(row))
    return "\n".join(out)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _escape_pre_html(text: str) -> str:
    return html_escape(text, quote=False)


def _render_pre_block(lines: list[str]) -> str:
    body = "\n".join(line.rstrip() for line in lines if line is not None).strip()
    return f"<pre>{_escape_pre_html(body or '...')}</pre>"


def _sanitize_not_triggered(text: str) -> str:
    raw = _normalize_whitespace(text)
    lowered = raw.lower()
    if "threshold=" in lowered:
        metrics = {key: value for key, value in re.findall(r"([a-z_]+)=([0-9]+)", raw)}
        current = metrics.get("last_prompt_tokens") or metrics.get("current_tokens") or "n/a"
        threshold = metrics.get("threshold") or "n/a"
        return f"below summarize threshold ({current}/{threshold} tokens)"
    if "usage_unavailable" in lowered:
        return "usage metrics unavailable"
    if "not enough new messages" in lowered:
        return "not enough new messages"
    if "empty slice" in lowered:
        return "nothing new to summarize"
    return raw.removeprefix("not_triggered:").strip() or "not triggered"


def _format_post_turn_value(status: str, detail: str) -> str:
    clean = _normalize_whitespace(detail)
    if status == "started":
        return "pending"
    if status == "running":
        return clean or "running"
    if status == "not_triggered":
        return _sanitize_not_triggered(clean)
    if status in {"failed", "error", "retry", "skipped"}:
        message = clean.removeprefix(f"{status}:").strip() or status
        return f"{status}: {message}"
    return clean or status or "done"


def _progress_stage_icon(stage: str, status: str = "") -> str:
    if stage == "Pre-search":
        return "🔎"
    if stage == "Thinking":
        return "🧠"
    if stage == "Turn complete":
        return "✅"
    if status in {"failed", "error"}:
        return "❌"
    if status in {"retry", "skipped", "not_triggered"}:
        return "⚠️"
    return "✨"


def _progress_fingerprint(event: dict) -> str:
    return "|".join(
        [
            str(event.get("event", "")),
            str(event.get("stage", "")),
            str(event.get("status", "")),
            str(event.get("tool_name", "")),
            _normalize_whitespace(str(event.get("arguments_preview", "") or event.get("content", ""))),
        ]
    )


def _format_progress_line(event: dict) -> str | None:
    event_type = str(event.get("event", "stage") or "stage")
    stage = str(event.get("stage", "") or "")
    status = str(event.get("status", "running") or "running")
    content = str(event.get("content", "") or "").strip()
    extra = event.get("extra") if isinstance(event.get("extra"), dict) else {}

    if event_type == "tool":
        if status not in {"running", "started"}:
            return None
        preview = str(event.get("arguments_preview", "") or event.get("tool_name", "")).strip()
        return f"🔧 {preview}" if preview else None

    if stage in POST_TURN_STAGES or stage == "Draft ready":
        return None

    if stage == "Pre-search":
        stores = extra.get("used_stores") if isinstance(extra.get("used_stores"), list) else []
        count = int(extra.get("count", 0) or 0)
        confidence = float(extra.get("confidence", 0.0) or 0.0)
        stores_text = ",".join(str(item) for item in stores) if stores else "-"
        return f"🔎 memory: stores={stores_text} | results={count} | confidence={confidence:.2f}"

    if stage == "Thinking":
        text = _normalize_whitespace(content)
        if not text:
            return None
        if text.lower() == "running main loop":
            return "🤖 running main loop"
        return f"🧠 {text}"

    if stage == "Turn complete":
        return "✅ turn complete"

    label = stage or "stage"
    detail = _normalize_whitespace(content)
    if detail.lower() == label.lower():
        detail = ""
    icon = _progress_stage_icon(stage, status=status)
    return f"{icon} {label}: {detail}".rstrip(": ")


def _split_pre_lines(lines: list[str], max_len: int = TELEGRAM_RENDER_LIMIT) -> list[str]:
    if not lines:
        return [_render_pre_block(["..."])]
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if len(_render_pre_block([line])) > max_len:
            for piece in split_message(line, max_len=max(400, max_len - 32)):
                if current:
                    chunks.append(current)
                    current = []
                chunks.append([piece])
            continue
        candidate = current + [line]
        if current and len(_render_pre_block(candidate)) > max_len:
            chunks.append(current)
            current = [line]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return [_render_pre_block(chunk) for chunk in chunks if chunk]


def _escape_markdown_v2_text(text: str) -> str:
    return escape_markdown(text, version=2)


def _escape_markdown_v2_url(url: str) -> str:
    return url.replace("\\", "\\\\").replace(")", "\\)")


def _render_markdown_v2_inline(text: str) -> str:
    normalized_lines: list[str] = []
    for line in text.splitlines():
        heading = re.match(r"^#{1,6}\s+(.+)$", line)
        if heading:
            normalized_lines.append(f"**{heading.group(1).strip()}**")
        else:
            normalized_lines.append(line)
    normalized = "\n".join(normalized_lines)

    pattern = re.compile(
        r"`([^`]+)`"
        r"|\[([^\]]+)\]\(([^)]+)\)"
        r"|\*\*(.+?)\*\*"
        r"|__(.+?)__"
        r"|~~(.+?)~~"
        r"|(?<!\w)_([^_\n]+)_(?!\w)"
    )

    parts: list[str] = []
    last = 0
    for match in pattern.finditer(normalized):
        if match.start() > last:
            parts.append(_escape_markdown_v2_text(normalized[last:match.start()]))
        if match.group(1) is not None:
            code = escape_markdown(match.group(1), version=2, entity_type="code")
            parts.append(f"`{code}`")
        elif match.group(2) is not None and match.group(3) is not None:
            label = _escape_markdown_v2_text(match.group(2))
            url = _escape_markdown_v2_url(match.group(3).strip())
            parts.append(f"[{label}]({url})")
        elif match.group(4) is not None:
            parts.append(f"*{_escape_markdown_v2_text(match.group(4))}*")
        elif match.group(5) is not None:
            parts.append(f"*{_escape_markdown_v2_text(match.group(5))}*")
        elif match.group(6) is not None:
            parts.append(f"~{_escape_markdown_v2_text(match.group(6))}~")
        elif match.group(7) is not None:
            parts.append(f"_{_escape_markdown_v2_text(match.group(7))}_")
        last = match.end()
    if last < len(normalized):
        parts.append(_escape_markdown_v2_text(normalized[last:]))
    return "".join(parts)


def _split_markdown_blocks(text: str) -> list[tuple[str, str, str]]:
    blocks: list[tuple[str, str, str]] = []
    pattern = re.compile(r"```([\w+-]*)\n?([\s\S]*?)```", re.MULTILINE)
    last = 0
    for match in pattern.finditer(text):
        if match.start() > last:
            prose = text[last:match.start()]
            if prose.strip():
                blocks.append(("text", "", prose))
        blocks.append(("code", match.group(1) or "", match.group(2)))
        last = match.end()
    tail = text[last:]
    if tail.strip():
        blocks.append(("text", "", tail))
    return blocks or [("text", "", text)]


def _render_code_block_markdown_v2(language: str, text: str) -> str:
    escaped = escape_markdown(text, version=2, entity_type="pre")
    return f"```{language}\n{escaped}\n```"


def _prepend_skill_reads(text: str, skill_reads: list[str] | None) -> str:
    items = []
    seen: set[str] = set()
    for item in skill_reads or []:
        if not isinstance(item, str):
            continue
        clean = item.strip().strip("/")
        if not clean or clean in seen:
            continue
        seen.add(clean)
        items.append(clean)
    if not items:
        return text
    block = "Skills read:\n" + "\n".join(f"- {item}" for item in items)
    return f"{block}\n\n{text}" if text else block


def _split_markdown_v2_message(text: str, max_len: int = TELEGRAM_RENDER_LIMIT) -> list[str]:
    chunks: list[str] = []
    current = ""
    for kind, language, raw in _split_markdown_blocks(text):
        if kind == "code":
            lines = raw.splitlines() or [""]
            segment_lines: list[str] = []
            for line in lines:
                candidate_lines = segment_lines + [line]
                rendered_candidate = _render_code_block_markdown_v2(language, "\n".join(candidate_lines))
                if segment_lines and len(rendered_candidate) > max_len:
                    rendered = _render_code_block_markdown_v2(language, "\n".join(segment_lines))
                    if current and len(current) + 2 + len(rendered) <= max_len:
                        current = f"{current}\n\n{rendered}"
                    else:
                        if current:
                            chunks.append(current)
                        current = rendered
                    segment_lines = [line]
                else:
                    segment_lines = candidate_lines
            if segment_lines:
                rendered = _render_code_block_markdown_v2(language, "\n".join(segment_lines))
                if current and len(current) + 2 + len(rendered) <= max_len:
                    current = f"{current}\n\n{rendered}"
                else:
                    if current:
                        chunks.append(current)
                    current = rendered
            continue

        paragraphs = [segment for segment in re.split(r"\n{2,}", raw) if segment.strip()]
        for paragraph in paragraphs:
            lines = paragraph.splitlines() or [paragraph]
            rolling = ""
            rendered_parts: list[str] = []
            for line in lines:
                candidate = f"{rolling}\n{line}".strip() if rolling else line
                rendered_candidate = _render_markdown_v2_inline(candidate)
                if rolling and len(rendered_candidate) > max_len:
                    rendered_parts.append(_render_markdown_v2_inline(rolling))
                    rolling = line
                elif not rolling and len(rendered_candidate) > max_len:
                    for piece in split_message(line, max_len=max(300, max_len - 16)):
                        rendered_parts.append(_render_markdown_v2_inline(piece))
                    rolling = ""
                else:
                    rolling = candidate
            if rolling:
                rendered_parts.append(_render_markdown_v2_inline(rolling))
            for part in rendered_parts:
                if current and len(current) + 2 + len(part) <= max_len:
                    current = f"{current}\n\n{part}"
                else:
                    if current:
                        chunks.append(current)
                    current = part
    if current:
        chunks.append(current)
    return chunks or [_render_markdown_v2_inline(text)]


class TelegramChannel(BaseChannel):
    """
    Telegram channel using long polling.

    Simple and reliable - no webhook/public IP needed.
    """

    name = "telegram"

    BOT_COMMANDS = [
        BotCommand("start", "Start the bot"),
        BotCommand("new", "Start a new conversation"),
        BotCommand("stop", "Stop the current task"),
        BotCommand("help", "Show available commands"),
    ]

    def __init__(
        self,
        config: TelegramConfig,
        bus: MessageBus,
        groq_api_key: str = "",
    ):
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self.groq_api_key = groq_api_key
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._media_group_buffers: dict[str, dict] = {}
        self._media_group_tasks: dict[str, asyncio.Task] = {}
        self._message_threads: dict[tuple[str, int], int] = {}
        self._turn_states: dict[tuple[str, int | None, int | None], _TelegramTurnState] = {}

    def is_allowed(self, sender_id: str) -> bool:
        """Preserve Telegram's legacy id|username allowlist matching."""
        if super().is_allowed(sender_id):
            return True

        allow_list = getattr(self.config, "allow_from", [])
        if not allow_list or "*" in allow_list:
            return False

        sender_str = str(sender_id)
        if sender_str.count("|") != 1:
            return False

        sid, username = sender_str.split("|", 1)
        if not sid.isdigit() or not username:
            return False

        return sid in allow_list or username in allow_list

    async def start(self) -> None:
        """Start the Telegram bot with long polling."""
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return

        self._running = True
        req = HTTPXRequest(
            connection_pool_size=16,
            pool_timeout=5.0,
            connect_timeout=30.0,
            read_timeout=30.0,
            proxy=self.config.proxy if self.config.proxy else None,
        )
        builder = Application.builder().token(self.config.token).request(req).get_updates_request(req)
        self._app = builder.build()
        self._app.add_error_handler(self._on_error)

        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("new", self._forward_command))
        self._app.add_handler(CommandHandler("stop", self._forward_command))
        self._app.add_handler(CommandHandler("help", self._on_help))
        self._app.add_handler(
            MessageHandler(
                (filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL)
                & ~filters.COMMAND,
                self._on_message,
            )
        )

        logger.info("Starting Telegram bot (polling mode)...")
        await self._app.initialize()
        await self._app.start()

        bot_info = await self._app.bot.get_me()
        logger.info("Telegram bot @{} connected", bot_info.username)

        try:
            await self._app.bot.set_my_commands(self.BOT_COMMANDS)
            logger.debug("Telegram bot commands registered")
        except Exception as exc:
            logger.warning("Failed to register bot commands: {}", exc)

        await self._app.updater.start_polling(
            allowed_updates=["message"],
            drop_pending_updates=True,
        )

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False

        for chat_id in list(self._typing_tasks):
            self._stop_typing(chat_id)

        for task in self._media_group_tasks.values():
            task.cancel()
        self._media_group_tasks.clear()
        self._media_group_buffers.clear()
        self._turn_states.clear()

        if self._app:
            logger.info("Stopping Telegram bot...")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

    @staticmethod
    def _get_media_type(path: str) -> str:
        """Guess media type from file extension."""
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext in ("jpg", "jpeg", "png", "gif", "webp"):
            return "photo"
        if ext == "ogg":
            return "voice"
        if ext in ("mp3", "m4a", "wav", "aac"):
            return "audio"
        return "document"

    @staticmethod
    def _turn_key(chat_id: str, message_thread_id: int | None, reply_to_message_id: int | None) -> tuple[str, int | None, int | None]:
        return (chat_id, message_thread_id, reply_to_message_id)

    async def _send_html_message(
        self,
        *,
        chat_id: int,
        html: str,
        reply_params=None,
        thread_kwargs: dict | None = None,
    ) -> int | None:
        message = await self._app.bot.send_message(
            chat_id=chat_id,
            text=html,
            parse_mode=ParseMode.HTML,
            reply_parameters=reply_params,
            **(thread_kwargs or {}),
        )
        return getattr(message, "message_id", None)

    async def _edit_html_message(
        self,
        *,
        chat_id: int,
        message_id: int,
        html: str,
    ) -> None:
        await self._app.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=html,
            parse_mode=ParseMode.HTML,
        )

    async def _send_markdown_v2_chunks(
        self,
        *,
        chat_id: int,
        text: str,
        reply_params=None,
        thread_kwargs: dict | None = None,
    ) -> list[int | None]:
        message_ids: list[int | None] = []
        for chunk in _split_markdown_v2_message(text, TELEGRAM_RENDER_LIMIT):
            message = await self._app.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_parameters=reply_params,
                **(thread_kwargs or {}),
            )
            message_ids.append(getattr(message, "message_id", None))
        return message_ids

    async def _flush_archived_progress(
        self,
        *,
        state: _TelegramTurnState,
        chat_id: int,
        reply_params,
        thread_kwargs: dict,
    ) -> None:
        if not state.archived_progress_lines:
            return
        for html in _split_pre_lines(state.archived_progress_lines, TELEGRAM_RENDER_LIMIT):
            await self._send_html_message(
                chat_id=chat_id,
                html=html,
                reply_params=reply_params,
                thread_kwargs=thread_kwargs,
            )
        state.archived_progress_lines.clear()

    async def _send_progress_update(
        self,
        *,
        state: _TelegramTurnState,
        chat_id: int,
        line: str,
        reply_params,
        thread_kwargs: dict,
    ) -> None:
        if state.progress_lines and state.progress_lines[-1] == line:
            return

        state.progress_lines.append(line)
        while len(_render_pre_block(state.progress_lines)) > TELEGRAM_RENDER_LIMIT and len(state.progress_lines) > 1:
            state.archived_progress_lines.append(state.progress_lines.pop(0))
        if state.archived_progress_lines:
            await self._flush_archived_progress(
                state=state,
                chat_id=chat_id,
                reply_params=reply_params,
                thread_kwargs=thread_kwargs,
            )

        current_html = _render_pre_block(state.progress_lines)
        if state.progress_message_id is None:
            state.progress_message_id = await self._send_html_message(
                chat_id=chat_id,
                html=current_html,
                reply_params=reply_params,
                thread_kwargs=thread_kwargs,
            )
        else:
            await self._edit_html_message(
                chat_id=chat_id,
                message_id=state.progress_message_id,
                html=current_html,
            )

    async def _send_or_update_post_turn_summary(
        self,
        *,
        state: _TelegramTurnState,
        chat_id: int,
        reply_params,
        thread_kwargs: dict,
    ) -> None:
        lines = ["Post-turn retrieval indexing"]
        for stage in (
            "Building graph",
            "Writing vectors",
            "Summarizing session",
        ):
            value = state.post_turn_summary.get(stage, "pending")
            lines.append(f"{POST_TURN_ICONS[stage]} {POST_TURN_LABELS[stage]}: {value}")

        html = _render_pre_block(lines)
        if state.post_turn_message_id is None:
            state.post_turn_message_id = await self._send_html_message(
                chat_id=chat_id,
                html=html,
                reply_params=reply_params,
                thread_kwargs=thread_kwargs,
            )
        else:
            await self._edit_html_message(
                chat_id=chat_id,
                message_id=state.post_turn_message_id,
                html=html,
            )

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Telegram."""
        if not self._app:
            logger.warning("Telegram bot not running")
            return

        if not msg.metadata.get("_progress", False):
            self._stop_typing(msg.chat_id)

        try:
            chat_id = int(msg.chat_id)
        except ValueError:
            logger.error("Invalid chat_id: {}", msg.chat_id)
            return

        reply_to_message_id = msg.metadata.get("message_id")
        message_thread_id = msg.metadata.get("message_thread_id")
        if message_thread_id is None and reply_to_message_id is not None:
            message_thread_id = self._message_threads.get((msg.chat_id, reply_to_message_id))
        thread_kwargs = {"message_thread_id": message_thread_id} if message_thread_id is not None else {}
        reply_params = None
        if self.config.reply_to_message and reply_to_message_id:
            reply_params = ReplyParameters(
                message_id=reply_to_message_id,
                allow_sending_without_reply=True,
            )

        turn_key = self._turn_key(msg.chat_id, message_thread_id, reply_to_message_id)
        state = self._turn_states.setdefault(turn_key, _TelegramTurnState())

        for media_path in (msg.media or []):
            try:
                media_type = self._get_media_type(media_path)
                sender = {
                    "photo": self._app.bot.send_photo,
                    "voice": self._app.bot.send_voice,
                    "audio": self._app.bot.send_audio,
                }.get(media_type, self._app.bot.send_document)
                param = "photo" if media_type == "photo" else media_type if media_type in ("voice", "audio") else "document"
                with open(media_path, "rb") as file_obj:
                    await sender(
                        chat_id=chat_id,
                        **{param: file_obj},
                        reply_parameters=reply_params,
                        **thread_kwargs,
                    )
            except Exception as exc:
                filename = media_path.rsplit("/", 1)[-1]
                logger.error("Failed to send media {}: {}", media_path, exc)
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=f"[Failed to send: {filename}]",
                    reply_parameters=reply_params,
                    **thread_kwargs,
                )

        if not msg.content or msg.content == "[empty message]":
            return

        if msg.metadata.get("_progress", False):
            event = dict(msg.metadata.get("_progress_event") or {})
            fingerprint = _progress_fingerprint(event)
            if fingerprint == state.last_progress_fingerprint:
                return
            state.last_progress_fingerprint = fingerprint
            stage = str(event.get("stage", "") or "")
            status = str(event.get("status", "running") or "running")
            content = str(event.get("content", msg.content) or msg.content)
            if stage in POST_TURN_STAGES:
                if content.strip() or status not in {"ok", "done"}:
                    state.post_turn_summary[stage] = _format_post_turn_value(status, content)
                if state.final_sent:
                    await self._send_or_update_post_turn_summary(
                        state=state,
                        chat_id=chat_id,
                        reply_params=reply_params,
                        thread_kwargs=thread_kwargs,
                    )
                return

            line = _format_progress_line({**event, "content": content})
            if line:
                await self._send_progress_update(
                    state=state,
                    chat_id=chat_id,
                    line=line,
                    reply_params=reply_params,
                    thread_kwargs=thread_kwargs,
                )
            return

        state.final_sent = True
        final_text = _prepend_skill_reads(msg.content, msg.metadata.get("_skill_reads"))
        await self._send_markdown_v2_chunks(
            chat_id=chat_id,
            text=final_text,
            reply_params=reply_params,
            thread_kwargs=thread_kwargs,
        )
        if state.post_turn_summary:
            await self._send_or_update_post_turn_summary(
                state=state,
                chat_id=chat_id,
                reply_params=reply_params,
                thread_kwargs=thread_kwargs,
            )

    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.message or not update.effective_user:
            return

        user = update.effective_user
        await update.message.reply_text(
            f"👋 Hi {user.first_name}! I'm fagent.\n\n"
            "Send me a message and I'll respond!\n"
            "Type /help to see available commands."
        )

    async def _on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command, bypassing ACL so all users can access it."""
        if not update.message:
            return
        await update.message.reply_text(
            "🐈 fagent commands:\n"
            "/new — Start a new conversation\n"
            "/stop — Stop the current task\n"
            "/help — Show available commands"
        )

    @staticmethod
    def _sender_id(user) -> str:
        """Build sender_id with username for allowlist matching."""
        sid = str(user.id)
        return f"{sid}|{user.username}" if user.username else sid

    @staticmethod
    def _derive_topic_session_key(message) -> str | None:
        """Derive topic-scoped session key for non-private Telegram chats."""
        message_thread_id = getattr(message, "message_thread_id", None)
        if message.chat.type == "private" or message_thread_id is None:
            return None
        return f"telegram:{message.chat_id}:topic:{message_thread_id}"

    @staticmethod
    def _build_message_metadata(message, user) -> dict:
        """Build common Telegram inbound metadata payload."""
        return {
            "message_id": message.message_id,
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "is_group": message.chat.type != "private",
            "message_thread_id": getattr(message, "message_thread_id", None),
            "is_forum": bool(getattr(message.chat, "is_forum", False)),
        }

    def _remember_thread_context(self, message) -> None:
        """Cache topic thread id by chat/message id for follow-up replies."""
        message_thread_id = getattr(message, "message_thread_id", None)
        if message_thread_id is None:
            return
        key = (str(message.chat_id), message.message_id)
        self._message_threads[key] = message_thread_id
        if len(self._message_threads) > 1000:
            self._message_threads.pop(next(iter(self._message_threads)))

    async def _forward_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Forward slash commands to the bus for unified handling in AgentLoop."""
        if not update.message or not update.effective_user:
            return
        message = update.message
        user = update.effective_user
        self._remember_thread_context(message)
        await self._handle_message(
            sender_id=self._sender_id(user),
            chat_id=str(message.chat_id),
            content=message.text,
            metadata=self._build_message_metadata(message, user),
            session_key=self._derive_topic_session_key(message),
        )

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages (text, photos, voice, documents)."""
        if not update.message or not update.effective_user:
            return

        message = update.message
        user = update.effective_user
        chat_id = message.chat_id
        sender_id = self._sender_id(user)
        self._remember_thread_context(message)
        self._chat_ids[sender_id] = chat_id

        content_parts = []
        media_paths = []

        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)

        media_file = None
        media_type = None

        if message.photo:
            media_file = message.photo[-1]
            media_type = "image"
        elif message.voice:
            media_file = message.voice
            media_type = "voice"
        elif message.audio:
            media_file = message.audio
            media_type = "audio"
        elif message.document:
            media_file = message.document
            media_type = "file"

        if media_file and self._app:
            try:
                file = await self._app.bot.get_file(media_file.file_id)
                ext = self._get_extension(
                    media_type,
                    getattr(media_file, "mime_type", None),
                    getattr(media_file, "file_name", None),
                )
                media_dir = get_media_dir("telegram")
                file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
                await file.download_to_drive(str(file_path))

                media_paths.append(str(file_path))
                if media_type in {"voice", "audio"}:
                    from fagent.providers.transcription import GroqTranscriptionProvider

                    transcriber = GroqTranscriptionProvider(api_key=self.groq_api_key)
                    transcription = await transcriber.transcribe(file_path)
                    if transcription:
                        logger.info("Transcribed {}: {}...", media_type, transcription[:50])
                        content_parts.append(f"[transcription: {transcription}]")
                    else:
                        content_parts.append(f"[{media_type}: {file_path}]")
                else:
                    content_parts.append(f"[{media_type}: {file_path}]")
                logger.debug("Downloaded {} to {}", media_type, file_path)
            except Exception as exc:
                logger.error("Failed to download media: {}", exc)
                content_parts.append(f"[{media_type}: download failed]")

        content = "\n".join(content_parts) if content_parts else "[empty message]"
        logger.debug("Telegram message from {}: {}...", sender_id, content[:50])

        str_chat_id = str(chat_id)
        metadata = self._build_message_metadata(message, user)
        session_key = self._derive_topic_session_key(message)

        if media_group_id := getattr(message, "media_group_id", None):
            key = f"{str_chat_id}:{media_group_id}"
            if key not in self._media_group_buffers:
                self._media_group_buffers[key] = {
                    "sender_id": sender_id,
                    "chat_id": str_chat_id,
                    "contents": [],
                    "media": [],
                    "metadata": metadata,
                    "session_key": session_key,
                }
                self._start_typing(str_chat_id)
            buf = self._media_group_buffers[key]
            if content and content != "[empty message]":
                buf["contents"].append(content)
            buf["media"].extend(media_paths)
            if key not in self._media_group_tasks:
                self._media_group_tasks[key] = asyncio.create_task(self._flush_media_group(key))
            return

        self._start_typing(str_chat_id)
        await self._handle_message(
            sender_id=sender_id,
            chat_id=str_chat_id,
            content=content,
            media=media_paths,
            metadata=metadata,
            session_key=session_key,
        )

    async def _flush_media_group(self, key: str) -> None:
        """Wait briefly, then forward buffered media-group as one turn."""
        try:
            await asyncio.sleep(0.6)
            if not (buf := self._media_group_buffers.pop(key, None)):
                return
            content = "\n".join(buf["contents"]) or "[empty message]"
            await self._handle_message(
                sender_id=buf["sender_id"],
                chat_id=buf["chat_id"],
                content=content,
                media=list(dict.fromkeys(buf["media"])),
                metadata=buf["metadata"],
                session_key=buf.get("session_key"),
            )
        finally:
            self._media_group_tasks.pop(key, None)

    def _start_typing(self, chat_id: str) -> None:
        """Start sending 'typing...' indicator for a chat."""
        self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    def _stop_typing(self, chat_id: str) -> None:
        """Stop the typing indicator for a chat."""
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    async def _typing_loop(self, chat_id: str) -> None:
        """Repeatedly send 'typing' action until cancelled."""
        try:
            while self._app:
                await self._app.bot.send_chat_action(chat_id=int(chat_id), action="typing")
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Typing indicator stopped for {}: {}", chat_id, exc)

    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log polling / handler errors instead of silently swallowing them."""
        logger.error("Telegram error: {}", context.error)

    def _get_extension(
        self,
        media_type: str,
        mime_type: str | None,
        filename: str | None = None,
    ) -> str:
        """Get file extension based on media type or original filename."""
        if mime_type:
            ext_map = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "audio/ogg": ".ogg",
                "audio/mpeg": ".mp3",
                "audio/mp4": ".m4a",
            }
            if mime_type in ext_map:
                return ext_map[mime_type]

        type_map = {"image": ".jpg", "voice": ".ogg", "audio": ".mp3", "file": ""}
        if ext := type_map.get(media_type, ""):
            return ext

        if filename:
            from pathlib import Path

            return "".join(Path(filename).suffixes)

        return ""
