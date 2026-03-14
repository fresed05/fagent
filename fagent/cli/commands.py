"""CLI commands for fagent."""

import asyncio
from dataclasses import dataclass
import re
import os
import select
import signal
import sys
import time
from pathlib import Path

# Force UTF-8 encoding for Windows console
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        # Re-open stdout/stderr with UTF-8 encoding
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import typer
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.document import Document
from rich import box
from rich.console import Console
from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from typer.main import get_command as typer_get_command

from fagent import __logo__, __version__
from fagent.config.paths import get_workspace_path
from fagent.config.schema import Config
from fagent.utils.helpers import sync_workspace_templates

app = typer.Typer(
    name="fagent",
    help=f"{__logo__} fagent - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console(
    force_terminal=bool(getattr(sys.stdout, "isatty", lambda: False)()),
    color_system="auto" if bool(getattr(sys.stdout, "isatty", lambda: False)()) else None,
    no_color=not bool(getattr(sys.stdout, "isatty", lambda: False)()),
)
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}
BRAND_GRADIENT = "bold bright_white on blue"
ACCENT = "bright_cyan"


@dataclass(frozen=True, slots=True)
class _CommandEntry:
    name: str
    description: str
    category: str
    example: str
    aliases: tuple[str, ...] = ()


CHAT_COMMANDS: tuple[_CommandEntry, ...] = (
    _CommandEntry("/help", "Show interactive help and examples.", "chat", "/help"),
    _CommandEntry("/commands", "List chat commands and CLI shortcuts.", "chat", "/commands"),
    _CommandEntry("/clear", "Clear the terminal viewport.", "chat", "/clear"),
    _CommandEntry("/status", "Show the active interactive session state.", "chat", "/status"),
    _CommandEntry("/exit", "Exit interactive mode.", "chat", "/exit", aliases=("exit", "/quit", "quit", ":q")),
)

_PROMPT_CATALOG: tuple[_CommandEntry, ...] = ()


def _is_emoji_friendly() -> bool:
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
    return "utf" in encoding


def _icon(emoji: str, fallback: str) -> str:
    return emoji if _is_emoji_friendly() else fallback


def _status_chip(label: str, style: str) -> Text:
    text = Text()
    text.append("[", style="dim")
    text.append(label.upper(), style=style)
    text.append("]", style="dim")
    return text


class _HybridCommandCompleter(Completer):
    def __init__(self, entries: tuple[_CommandEntry, ...]):
        self.entries = entries

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        is_chat = text.startswith("/")
        entries = [entry for entry in self.entries if entry.name.startswith("/")] if is_chat else [
            entry for entry in self.entries if not entry.name.startswith("/")
        ]
        if not text:
            for entry in entries[:12]:
                yield Completion(
                    entry.name,
                    start_position=0,
                    display=entry.name,
                    display_meta=entry.description,
                )
            return

        lowered = text.lower()
        matches: list[tuple[_CommandEntry, str]] = []
        for entry in entries:
            candidates = (entry.name, *entry.aliases)
            for candidate in candidates:
                if candidate.lower().startswith(lowered):
                    matches.append((entry, candidate))
                    break
        seen: set[str] = set()
        for entry, candidate in matches:
            if entry.name in seen:
                continue
            seen.add(entry.name)
            yield Completion(
                entry.name,
                start_position=-len(document.text_before_cursor),
                display=entry.name,
                display_meta=entry.description,
            )


class _HybridAutoSuggest(AutoSuggest):
    def __init__(self, entries: tuple[_CommandEntry, ...]):
        self.entries = entries

    def get_suggestion(self, buffer, document):
        text = document.text_before_cursor.lstrip()
        if not text:
            return None
        pool = (
            [entry for entry in self.entries if entry.name.startswith("/")]
            if text.startswith("/")
            else [entry for entry in self.entries if not entry.name.startswith("/")]
        )
        lowered = text.lower()
        for entry in pool:
            for candidate in (entry.name, *entry.aliases):
                if candidate.lower().startswith(lowered) and entry.name != text:
                    return Suggestion(entry.name[len(text):])
        return None


class _TurnTimeline:
    _SUMMARY_STAGE_KEYS = {
        "Building graph": "graph",
        "Writing vectors": "vector",
        "Summarizing session": "summary",
    }

    def __init__(self, console_: Console):
        self.console = console_
        self._last_tool_key: tuple[str, str] | None = None
        self._last_tool_count = 0
        self._pending_tool_status = "running"
        self._turn_started_at = time.perf_counter()
        self._summary: dict[str, object] = {}
        self._summary_visible = False

    def start_turn(self) -> None:
        self._last_tool_key = None
        self._last_tool_count = 0
        self._pending_tool_status = "running"
        self._turn_started_at = time.perf_counter()
        self._summary = {}
        self._summary_visible = False

    def _stage_style(self, status: str) -> str:
        return {
            "started": "cyan",
            "running": "cyan",
            "ok": "green",
            "done": "green",
            "failed": "red",
            "error": "red",
            "retry": "yellow",
            "skipped": "yellow",
            "not_triggered": "dim",
        }.get(status, "dim")

    def _sanitize_error_text(self, text: str, *, stage: str = "") -> str:
        raw = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", (text or ""))
        raw = re.sub(r"\?\[[0-9;?]*[A-Za-z]", "", raw).strip()
        if not raw:
            return ""
        lowered = raw.lower()
        if stage == "Summarizing session" and "not_triggered" in lowered:
            if "threshold=" in lowered:
                metrics = {
                    key: value
                    for key, value in re.findall(r"([a-z_]+)=([0-9]+)", raw)
                }
                current = metrics.get("last_prompt_tokens") or metrics.get("current_tokens") or "n/a"
                threshold = metrics.get("threshold") or "n/a"
                return f"context below summarize threshold ({current}/{threshold} tokens)"
            if "usage_unavailable" in lowered:
                return "usage metrics unavailable"
            if "not enough new messages" in lowered:
                return "not enough new messages since the last rollup"
            if "empty slice" in lowered:
                return "nothing new to summarize"
        if "workflowstateartifact" in lowered and "attribute 'id'" in lowered:
            if stage == "Writing vectors":
                return "workflow snapshot normalization required"
            return "workflow snapshot metadata mismatch"
        if "object has no attribute" in lowered:
            return "artifact metadata mismatch"
        return raw

    def _tool_icon(self, tool_name: str) -> str:
        normalized = tool_name.lower()
        if any(token in normalized for token in ("exec", "shell", "bash")):
            return _icon("🛠️", "T")
        if any(token in normalized for token in ("read", "file", "write")):
            return _icon("📄", "F")
        if "memory" in normalized:
            return _icon("🧠", "M")
        if any(token in normalized for token in ("web", "search", "http")):
            return _icon("🌐", "W")
        return _icon("🔧", "*")

    def _stage_icon(self, stage: str, *, status: str = "") -> str:
        if stage == "Thinking":
            return _icon("🧠", ">")
        if stage == "Pre-search":
            return _icon("🔎", "?")
        if stage == "Saving file memory":
            return _icon("🗂️", "F")
        if stage == "Building graph":
            return _icon("🕸️", "G")
        if stage == "Writing vectors":
            return _icon("📦", "V")
        if stage == "Summarizing session":
            return _icon("📝", "S")
        if stage == "Turn complete":
            return _icon("✅", "+")
        return _icon("✨", "*")

    def _tool_style(self, tool_name: str, status: str) -> str:
        if status in {"error", "failed"}:
            return "bold red"
        if status == "retry":
            return "bold yellow"
        normalized = tool_name.lower()
        if any(token in normalized for token in ("exec", "shell", "bash")):
            return "bright_magenta"
        if any(token in normalized for token in ("read", "file", "write")):
            return "bright_blue"
        if "memory" in normalized:
            return "bright_cyan"
        if any(token in normalized for token in ("web", "search", "http")):
            return "bright_green"
        return "bright_white"

    def _render_line(self, icon: str, label: str, message: str, *, style: str, badge: Text | None = None) -> None:
        text = Text()
        text.append("  ")
        text.append(f"{icon} ", style=style)
        text.append(label, style=f"bold {style}")
        if message:
            text.append(" ")
            text.append(message, style="white")
        if badge is not None:
            text.append(" ")
            text.append_text(badge)
        self.console.print(text)

    def _flush_tool(self) -> None:
        if self._last_tool_key is None:
            return
        tool_name, preview = self._last_tool_key
        style = self._tool_style(tool_name, self._pending_tool_status)
        badge = _status_chip(
            f"x{self._last_tool_count}" if self._last_tool_count > 1 else self._pending_tool_status,
            self._stage_style(self._pending_tool_status),
        )
        self._render_line(
            self._tool_icon(tool_name),
            tool_name,
            preview,
            style=style,
            badge=badge,
        )
        self._last_tool_key = None
        self._last_tool_count = 0
        self._pending_tool_status = "running"

    @staticmethod
    def _clean_summary_value(value: object) -> str:
        text = str(value or "n/a").strip()
        return text or "n/a"

    @staticmethod
    def _format_summary_value(
        stage: str,
        status: str,
        content: str,
        error: str,
        extra: dict[str, object],
    ) -> str:
        text = content.strip() or str(error or "").strip()
        if text and text.lower() not in {status.lower(), stage.lower()}:
            return text
        if status == "started":
            return "pending (background)"
        if status == "running":
            return text or "running"
        if status in {"ok", "done"}:
            return text or status
        if status == "not_triggered":
            return f"skipped: {text or 'conditions not met'}"
        if status in {"skipped", "retry", "failed", "error"}:
            detail = text or str(extra.get("reason") or "").strip()
            return f"{status}: {detail}" if detail else status
        return text or status or "n/a"

    def _record_summary_stage(
        self,
        *,
        stage: str,
        status: str,
        content: str,
        extra: dict[str, object],
        error: str,
    ) -> None:
        key = self._SUMMARY_STAGE_KEYS.get(stage)
        if not key:
            return
        self._summary[key] = self._format_summary_value(stage, status, content, error, extra)

    def _render_presearch(self, extra: dict[str, object]) -> None:
        stores = extra.get("used_stores") if isinstance(extra.get("used_stores"), list) else []
        count = int(extra.get("count", 0) or 0)
        confidence = float(extra.get("confidence", 0.0) or 0.0)
        stores_text = ", ".join(str(item) for item in stores) if stores else "none"
        self._render_line(self._stage_icon("Pre-search"), "Memory", f"lookup: {stores_text}", style="bright_cyan")
        self._render_line(self._stage_icon("Pre-search"), "Memory", f"results: {count}; confidence {confidence:.2f}", style="bright_cyan")

    def _render_thinking(self, content: str) -> None:
        text = content.strip()
        if not text or text == "Running main loop":
            self._render_line(self._stage_icon("Thinking"), "Thought", "Planning response", style="bright_blue")
            return
        self._render_line(self._stage_icon("Thinking"), "Thought", text, style="bright_blue")

    def _render_post_turn_summary(self) -> None:
        graph_value = self._clean_summary_value(self._summary.get("graph", "pending (background)"))
        vector_value = self._clean_summary_value(self._summary.get("vector", "pending (background)"))
        summary_value = self._clean_summary_value(self._summary.get("summary", "pending (background)"))
        lines = [
            Text.assemble(f"{self._stage_icon('Building graph')} Graph: ", (graph_value, "white")),
            Text.assemble(f"{self._stage_icon('Writing vectors')} Vector: ", (vector_value, "white")),
            Text.assemble(f"{self._stage_icon('Summarizing session')} Summary: ", (summary_value, "white")),
        ]
        body = Group(*lines)
        self.console.print(
            Panel(
                body,
                title=f"{_icon('🗃️', '#')} Post-turn indexing",
                border_style="bright_black",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
        self._summary_visible = True

    def _render_background_stage_update(self, stage: str, status: str, message: str) -> None:
        stage_label = {
            "Building graph": "Graph",
            "Writing vectors": "Vector",
            "Summarizing session": "Summary",
        }.get(stage, stage)
        if stage == "Turn complete":
            return
        display_message = message
        if status == "not_triggered":
            display_message = f"skipped: {message.removeprefix('skipped: ').removeprefix('not_triggered: ').strip()}"
        self._render_line(
            self._stage_icon(stage, status=status),
            stage_label,
            display_message,
            style=self._stage_style(status),
            badge=_status_chip(status, self._stage_style(status)),
        )

    def handle_event(self, event: dict[str, object]) -> None:
        stage = str(event.get("stage", "") or "")
        status = str(event.get("status", "running") or "running")
        content = str(event.get("content", "") or "")
        event_type = str(event.get("event", "stage") or "stage")
        extra = event.get("extra") or {}
        error = self._sanitize_error_text(str(event.get("error", "") or ""), stage=stage)
        content = self._sanitize_error_text(content, stage=stage)
        if isinstance(extra, dict):
            self._record_summary_stage(
                stage=stage,
                status=status,
                content=content,
                extra=extra,
                error=error,
            )
        if event_type == "tool":
            tool_name = str(event.get("tool_name", "") or "")
            preview = str(event.get("arguments_preview", "") or tool_name or content)
            key = (tool_name, preview)
            if self._last_tool_key == key:
                self._last_tool_count += 1
                self._pending_tool_status = status
                return
            self._flush_tool()
            self._last_tool_key = key
            self._last_tool_count = 1
            self._pending_tool_status = status
            return
        self._flush_tool()
        if stage == "Draft ready":
            return
        if stage == "Pre-search":
            self._render_presearch(extra if isinstance(extra, dict) else {})
            return
        if stage in self._SUMMARY_STAGE_KEYS and status in {"started", "running", "ok", "done", "skipped"}:
            return
        if stage in self._SUMMARY_STAGE_KEYS and status in {"retry", "failed", "error", "skipped", "not_triggered"}:
            self._render_background_stage_update(stage, status, content or error or status)
            return
        if stage == "Thinking":
            self._render_thinking(content)
            return
        if stage == "Turn complete":
            elapsed = time.perf_counter() - self._turn_started_at
            self._render_post_turn_summary()
            self._render_line(self._stage_icon(stage), "Done", "Turn complete", style="green")
            self._render_line(_icon("⏱️", "t"), "Elapsed", f"{elapsed:.1f}s", style="bright_black")
            return
        style = self._stage_style(status)
        self._render_line(self._stage_icon(stage, status=status), stage, content, style=style)

# ---------------------------------------------------------------------------
# CLI input: prompt_toolkit for editing, paste, history, and display
# ---------------------------------------------------------------------------

_PROMPT_SESSION: PromptSession | None = None
_SAVED_TERM_ATTRS = None  # original termios settings, restored on exit


def _flush_pending_tty_input() -> None:
    """Drop unread keypresses typed while the model was generating output."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    try:
        import termios
        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break
    except Exception:
        return


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass


def _walk_click_commands(group, prefix: tuple[str, ...] = ()) -> list[_CommandEntry]:
    entries: list[_CommandEntry] = []
    commands = getattr(group, "commands", {}) or {}
    for name, command in commands.items():
        current = (*prefix, name)
        full_name = " ".join(current)
        description = (
            getattr(command, "short_help", None)
            or getattr(command, "help", None)
            or "No description available."
        )
        category = current[0]
        entries.append(
            _CommandEntry(
                name=full_name,
                description=str(description).strip(),
                category=category,
                example=f"fagent {full_name}",
            )
        )
        if getattr(command, "commands", None):
            entries.extend(_walk_click_commands(command, current))
    return entries


def _build_prompt_catalog() -> tuple[_CommandEntry, ...]:
    cli_root = typer_get_command(app)
    cli_entries = _walk_click_commands(cli_root)
    unique: dict[str, _CommandEntry] = {entry.name: entry for entry in CHAT_COMMANDS}
    for entry in cli_entries:
        unique.setdefault(entry.name, entry)
    return tuple(unique.values())


def _command_categories(entries: tuple[_CommandEntry, ...]) -> dict[str, list[_CommandEntry]]:
    grouped: dict[str, list[_CommandEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.category, []).append(entry)
    return grouped


def _best_command_match(text: str, entries: tuple[_CommandEntry, ...]) -> _CommandEntry | None:
    lowered = text.strip().lower()
    if not lowered:
        return None
    pool = [entry for entry in entries if entry.name.startswith("/")] if lowered.startswith("/") else [
        entry for entry in entries if not entry.name.startswith("/")
    ]
    for entry in pool:
        for candidate in (entry.name, *entry.aliases):
            if candidate.lower().startswith(lowered):
                return entry
    return None


def _bottom_toolbar() -> HTML:
    if _PROMPT_SESSION is None:
        return HTML("<style fg='ansibrightblack'>Tab to complete</style>")
    buffer = getattr(_PROMPT_SESSION, "default_buffer", None)
    document = buffer.document if buffer is not None else Document("")
    match = _best_command_match(document.text_before_cursor, _PROMPT_CATALOG)
    if match is None:
        return HTML(
            "<style fg='ansibrightblack'>Tab to complete | /help for interactive commands | shell completion: --install-completion</style>"
        )
    return HTML(
        f"<style fg='ansibrightblack'>Tab to complete</style> "
        f"<b fg='ansicyan'>{match.name}</b> "
        f"<style fg='ansibrightblack'>- {match.description}</style>"
    )


def _print_interactive_help(entries: tuple[_CommandEntry, ...]) -> None:
    grouped = _command_categories(entries)
    table = Table(box=box.SIMPLE_HEAVY, show_header=True, expand=True)
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description", style="white")
    table.add_column("Example", style="bright_black")
    for category in ("chat", "memory", "workflow", "channels", "provider", "agent", "gateway", "status", "onboard"):
        for entry in grouped.get(category, []):
            table.add_row(entry.name, entry.description, entry.example)
    console.print(
        Panel(
            table,
            title=f"{_icon('🧭', '?')} Interactive command guide",
            border_style=ACCENT,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )
    console.print(
        Panel.fit(
            "Use Tab for in-chat completion.\n"
            "Shell completion is still available via `fagent --install-completion` and `fagent --show-completion`.",
            title="Tips",
            border_style="bright_black",
            box=box.ROUNDED,
        )
    )


def _print_interactive_status(*, session_id: str, workspace: Path, model: str) -> None:
    table = Table(box=box.SIMPLE_HEAVY, show_header=False)
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Session", session_id)
    table.add_row("Workspace", str(workspace))
    table.add_row("Model", model)
    table.add_row("Completions", "Hybrid chat + CLI")
    console.print(
        Panel(
            table,
            title=f"{_icon('📍', '*')} Interactive status",
            border_style="bright_blue",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _PROMPT_SESSION, _PROMPT_CATALOG, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    try:
        import termios
        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    from fagent.config.paths import get_cli_history_path

    history_file = get_cli_history_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)
    _PROMPT_CATALOG = _build_prompt_catalog()

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,   # Enter submits (single line mode)
        completer=_HybridCommandCompleter(_PROMPT_CATALOG),
        auto_suggest=_HybridAutoSuggest(_PROMPT_CATALOG),
        bottom_toolbar=_bottom_toolbar,
    )


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """Render assistant response with consistent terminal styling."""
    content = response or ""
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(
        Panel(
            body,
            title=f"{__logo__} fagent",
            title_align="left",
            border_style=ACCENT,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )
    console.print()


def _print_brand_banner(tagline: str = "Lightning-fast personal AI assistant") -> None:
    """Render a branded CLI banner."""
    console.print(
        Panel.fit(
            f"[{BRAND_GRADIENT}] {__logo__} fagent [/{BRAND_GRADIENT}]\n"
            f"[dim]{tagline}[/dim]",
            border_style=ACCENT,
            box=box.DOUBLE,
            padding=(0, 2),
        )
    )


def _print_info(message: str) -> None:
    console.print(f"[cyan]{_icon('•', '-')}[/cyan] {message}")


def _print_success(message: str) -> None:
    console.print(f"[green]{_icon('✅', '+')}[/green] {message}")


def _print_warning(message: str) -> None:
    console.print(f"[yellow]{_icon('⚠️', '!')}[/yellow] {message}")


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


def _handle_interactive_command(command: str, *, session_id: str, workspace: Path, model: str) -> bool:
    normalized = command.strip().lower()
    if normalized in {"/help", "/commands"}:
        _print_interactive_help(_PROMPT_CATALOG)
        return True
    if normalized == "/clear":
        console.clear()
        _print_brand_banner("Interactive mode")
        return True
    if normalized == "/status":
        _print_interactive_status(session_id=session_id, workspace=workspace, model=model)
        return True
    return False


async def _read_interactive_input_async() -> str:
    """Read user input using prompt_toolkit (handles paste, history, display).

    prompt_toolkit natively handles:
    - Multiline paste (bracketed paste mode)
    - History navigation (up/down arrows)
    - Clean display (no ghost characters or artifacts)
    """
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiyellow'>You</b><style fg='ansibrightblack'> ></style>"),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc



def version_callback(value: bool):
    if value:
        console.print(
            Panel.fit(
                f"[bold]{__logo__} fagent[/bold] [dim]v{__version__}[/dim]",
                border_style=ACCENT,
                box=box.ROUNDED,
            )
        )
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
):
    """fagent - Personal AI Assistant."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard():
    """Initialize fagent configuration and workspace."""
    from fagent.config.loader import get_config_path, load_config, save_config
    from fagent.config.schema import Config

    config_path = get_config_path()
    _print_brand_banner("Bootstrap config, workspace, and templates in one pass")

    if config_path.exists():
        _print_warning(f"Config already exists at {config_path}")
        console.print("  [bold]y[/bold] = overwrite with defaults (existing values will be lost)")
        console.print("  [bold]N[/bold] = refresh config, keeping existing values and adding new fields")
        if typer.confirm("Overwrite?"):
            config = Config()
            save_config(config)
            _print_success(f"Config reset to defaults at {config_path}")
        else:
            config = load_config()
            save_config(config)
            _print_success(f"Config refreshed at {config_path} (existing values preserved)")
    else:
        save_config(Config())
        _print_success(f"Created config at {config_path}")

    # Create workspace
    workspace = get_workspace_path()

    if not workspace.exists():
        workspace.mkdir(parents=True, exist_ok=True)
        _print_success(f"Created workspace at {workspace}")

    sync_workspace_templates(workspace)

    console.print(Rule(style="bright_blue"))
    console.print(
        Panel.fit(
            "[bold bright_white]fagent is ready[/bold bright_white]\n"
            "[dim]`fagent onboard` writes the full default config tree: channels, providers, models, tools, gateway, and memory.[/dim]",
            title=f"{__logo__} Setup Complete",
            title_align="left",
            border_style="green",
            box=box.ROUNDED,
        )
    )
    table = Table(box=box.SIMPLE_HEAVY, show_header=False, pad_edge=False)
    table.add_column(style="bold white", no_wrap=True)
    table.add_column(style="cyan")
    table.add_row("Config", "~/.fagent/config.json")
    table.add_row("API key", "https://openrouter.ai/keys")
    table.add_row("Chat", 'fagent agent -m "Hello!"')
    table.add_row("Channels", "https://github.com/HKUDS/fagent#chat-apps")
    console.print(table)





def _make_provider(config: Config):
    """Create the appropriate LLM provider from config."""
    from fagent.providers.factory import ProviderFactory

    try:
        provider, _ = ProviderFactory(config).build_main_provider()
        return provider
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        _print_info("Set credentials in ~/.fagent/config.json under providers")
        raise typer.Exit(1) from exc


def _load_runtime_config(config: str | None = None, workspace: str | None = None) -> Config:
    """Load config and optionally override the active workspace."""
    from fagent.config.loader import load_config, set_config_path

    config_path = None
    if config:
        config_path = Path(config).expanduser().resolve()
        if not config_path.exists():
            console.print(f"[red]Error: Config file not found: {config_path}[/red]")
            raise typer.Exit(1)
        set_config_path(config_path)
        _print_info(f"Using config: {config_path}")

    loaded = load_config(config_path)
    if workspace:
        loaded.agents.defaults.workspace = workspace
    return loaded


def _get_graph_ui_manager(workspace: Path):
    from fagent.memory.graph_ui import get_graph_ui_manager

    return get_graph_ui_manager(workspace)


workflow_app = typer.Typer(help="Manage workflow.json definitions")
app.add_typer(workflow_app, name="workflow")


@workflow_app.command("migrate")
def workflow_migrate(
    target: str = typer.Argument(..., help="Legacy workflow markdown file or directory"),
):
    """Migrate legacy workflow prompt markdown files to one workflow.json."""
    from fagent.workflows import migrate_legacy_workflow_path

    workflow_path, deleted = migrate_legacy_workflow_path(Path(target))
    console.print(f"[green]✓[/green] Created {workflow_path}")
    for item in deleted:
        console.print(f"[dim]deleted[/dim] {item}")


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Start the fagent gateway."""
    from fagent.agent.loop import AgentLoop
    from fagent.bus.queue import MessageBus
    from fagent.channels.manager import ChannelManager
    from fagent.config.paths import get_cron_dir
    from fagent.cron.service import CronService
    from fagent.cron.types import CronJob
    from fagent.heartbeat.service import HeartbeatService
    from fagent.recovery.manager import RecoveryManager
    from fagent.runtime_logging import setup_runtime_logging
    from fagent.session.manager import SessionManager

    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)
    setup_runtime_logging(verbose=verbose, console_output=True)

    config = _load_runtime_config(config, workspace)

    _print_brand_banner(f"Gateway mode on port {port}")
    sync_workspace_templates(config.workspace_path)
    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(config.workspace_path)

    # Create cron service first (callback set after agent creation)
    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    # Create agent with cron service
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        reasoning_effort=config.agents.defaults.reasoning_effort,
        brave_api_key=config.tools.web.search.api_key or None,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        memory_config=config.memory,
        app_config=config,
    )

    # Set cron callback (needs agent)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        from fagent.agent.tools.cron import CronTool
        from fagent.agent.tools.message import MessageTool
        reminder_note = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' has been triggered.\n"
            f"Scheduled instruction: {job.payload.message}"
        )

        # Prevent the agent from scheduling new cron jobs during execution
        cron_tool = agent.tools.get("cron")
        cron_token = None
        if isinstance(cron_tool, CronTool):
            cron_token = cron_tool.set_cron_context(True)
        try:
            response = await agent.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to or "direct",
            )
        finally:
            if isinstance(cron_tool, CronTool) and cron_token is not None:
                cron_tool.reset_cron_context(cron_token)

        message_tool = agent.tools.get("message")
        if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
            return response

        if job.payload.deliver and job.payload.to and response:
            from fagent.bus.events import OutboundMessage
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to,
                content=response
            ))
        return response
    cron.on_job = on_cron_job

    # Create channel manager
    channels = ChannelManager(config, bus)

    def _pick_heartbeat_target() -> tuple[str, str]:
        """Pick a routable channel/chat target for heartbeat-triggered messages."""
        enabled = set(channels.enabled_channels)
        # Prefer the most recently updated non-internal session on an enabled channel.
        for item in session_manager.list_sessions():
            key = item.get("key") or ""
            if ":" not in key:
                continue
            channel, chat_id = key.split(":", 1)
            if channel in {"cli", "system"}:
                continue
            if channel in enabled and chat_id:
                return channel, chat_id
        # Fallback keeps prior behavior but remains explicit.
        return "cli", "direct"

    # Create heartbeat service
    async def on_heartbeat_execute(tasks: str) -> str:
        """Phase 2: execute heartbeat tasks through the full agent loop."""
        channel, chat_id = _pick_heartbeat_target()

        async def _silent(*_args, **_kwargs):
            pass

        return await agent.process_direct(
            tasks,
            session_key="heartbeat",
            channel=channel,
            chat_id=chat_id,
            on_progress=_silent,
        )

    async def on_heartbeat_notify(response: str) -> None:
        """Deliver a heartbeat response to the user's channel."""
        from fagent.bus.events import OutboundMessage
        channel, chat_id = _pick_heartbeat_target()
        if channel == "cli":
            return  # No external channel available to deliver to
        await bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content=response))

    hb_cfg = config.gateway.heartbeat
    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        provider=provider,
        model=agent.model,
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify,
        interval_s=hb_cfg.interval_s,
        enabled=hb_cfg.enabled,
    )

    if channels.enabled_channels:
        _print_success(f"Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        _print_warning("No channels enabled")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        _print_success(f"Cron: {cron_status['jobs']} scheduled jobs")

    _print_success(f"Heartbeat: every {hb_cfg.interval_s}s")

    # Auto-start graph UI if configured
    gui_cfg = config.gateway.graph_ui
    if gui_cfg.enabled:
        from fagent.memory.graph_ui import _STATIC_DIR
        if not (_STATIC_DIR / "index.html").exists():
            _print_warning(
                "Graph UI is enabled but not built. "
                "Run: fagent memory graph-ui-install"
            )
        else:
            try:
                gui_manager = _get_graph_ui_manager(config.workspace_path)
                # NOTE: orchestrator is created inside AgentLoop; we re-use the
                # existing manager pattern — the actual orchestrator is passed
                # lazily when the UI is first accessed.  Here we pre-start the
                # HTTP server so the port is open from gateway boot.
                gui_url = gui_manager.start(
                    agent.memory,
                    port=gui_cfg.port,
                    open_browser=gui_cfg.open_browser,
                )
                _print_success(f"Graph UI: {gui_url}")
            except Exception as _gui_err:  # pragma: no cover
                _print_warning(f"Graph UI failed to start: {_gui_err}")

    async def run():
        try:
            # Detect interrupted sessions from previous gateway run
            recovery = RecoveryManager(config.workspace_path)
            interrupted = recovery.detect_interrupted_sessions()

            if interrupted:
                logger.warning(f"Gateway restarted. Detected {len(interrupted)} interrupted session(s):")
                for session in interrupted:
                    logger.info(
                        f"  - {session.session_key} (turn {session.turn_id}, "
                        f"interrupted {session.duration_seconds:.1f}s ago)"
                    )

            # Clear old state
            recovery.clear_state()

            await cron.start()
            await heartbeat.start()
            await asyncio.gather(
                agent.run(),
                channels.start_all(),
            )
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        finally:
            await agent.close_mcp()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()

    asyncio.run(run())




# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show fagent runtime logs during chat"),
):
    """Interact with the agent directly."""
    from loguru import logger

    from fagent.agent.loop import AgentLoop
    from fagent.bus.queue import MessageBus
    from fagent.config.paths import get_cron_dir
    from fagent.cron.service import CronService
    from fagent.runtime_logging import setup_runtime_logging

    config = _load_runtime_config(config, workspace)
    sync_workspace_templates(config.workspace_path)
    setup_runtime_logging(verbose=logs, console_output=logs)

    bus = MessageBus()
    provider = _make_provider(config)

    # Create cron service for tool usage (no callback needed for CLI unless running)
    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    logger.enable("fagent")

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        reasoning_effort=config.agents.defaults.reasoning_effort,
        brave_api_key=config.tools.web.search.api_key or None,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        memory_config=config.memory,
        app_config=config,
    )

    # Show spinner when logs are off (no output to miss); skip when logs are on
    def _thinking_ctx():
        if logs:
            from contextlib import nullcontext
            return nullcontext()
        # Animated spinner is safe to use with prompt_toolkit input handling
        return console.status("[dim]fagent is thinking...[/dim]", spinner="dots")

    timeline = _TurnTimeline(console)

    async def _cli_progress(content: str, **kwargs) -> None:
        ch = agent_loop.channels_config
        event_channel = str(kwargs.get("channel", "cli") or "cli")
        event = {
            "content": content,
            "stage": kwargs.get("stage", ""),
            "status": kwargs.get("status", "running"),
            "event": kwargs.get("event", "stage"),
            "tool_name": kwargs.get("tool_name"),
            "arguments_preview": kwargs.get("arguments_preview"),
            "arguments_signature": kwargs.get("arguments_signature"),
            "duration_ms": kwargs.get("duration_ms"),
            "extra": kwargs.get("extra") or {},
            "error": kwargs.get("error", ""),
        }
        is_tool_hint = event["event"] == "tool"
        if ch and is_tool_hint and event_channel != "cli" and not ch.send_tool_hints:
            return
        if ch and event_channel != "cli" and not is_tool_hint and not ch.send_progress:
            return
        timeline.handle_event(event)

    if message:
        # Single message mode — direct call, no bus needed
        async def run_once():
            timeline.start_turn()
            with _thinking_ctx():
                response = await agent_loop.process_direct(message, session_id, on_progress=_cli_progress)
            timeline._flush_tool()
            _print_agent_response(response, render_markdown=markdown)
            await agent_loop.close_mcp()

        asyncio.run(run_once())
    else:
        # Interactive mode — route through bus like other channels
        from fagent.bus.events import InboundMessage
        _init_prompt_session()
        _print_brand_banner("Interactive mode")
        _print_info("Type /help for commands. Use Tab for hybrid chat + CLI completion.")
        _print_info("Type exit or press Ctrl+C to quit.")

        if ":" in session_id:
            cli_channel, cli_chat_id = session_id.split(":", 1)
        else:
            cli_channel, cli_chat_id = "cli", session_id

        def _handle_signal(signum, frame):
            sig_name = signal.Signals(signum).name
            _restore_terminal()
            console.print(f"\nReceived {sig_name}, goodbye!")
            sys.exit(0)

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        # SIGHUP is not available on Windows
        if hasattr(signal, 'SIGHUP'):
            signal.signal(signal.SIGHUP, _handle_signal)
        # Ignore SIGPIPE to prevent silent process termination when writing to closed pipes
        # SIGPIPE is not available on Windows
        if hasattr(signal, 'SIGPIPE'):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)

        async def run_interactive():
            bus_task = asyncio.create_task(agent_loop.run())
            turn_done = asyncio.Event()
            turn_done.set()
            turn_response: list[str] = []

            async def _consume_outbound():
                while True:
                    try:
                        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                        if msg.metadata.get("_progress"):
                            event = dict(msg.metadata.get("_progress_event") or {})
                            is_tool_hint = event.get("event") == "tool"
                            ch = agent_loop.channels_config
                            event_channel = str(msg.channel or "cli")
                            if ch and is_tool_hint and event_channel != "cli" and not ch.send_tool_hints:
                                pass
                            elif ch and event_channel != "cli" and not is_tool_hint and not ch.send_progress:
                                pass
                            else:
                                event.setdefault("content", msg.content)
                                timeline.handle_event(event)
                        elif not turn_done.is_set():
                            if msg.content:
                                turn_response.append(msg.content)
                            timeline._flush_tool()
                            turn_done.set()
                        elif msg.content:
                            console.print()
                            _print_agent_response(msg.content, render_markdown=markdown)
                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break

            outbound_task = asyncio.create_task(_consume_outbound())

            try:
                while True:
                    try:
                        _flush_pending_tty_input()
                        user_input = await _read_interactive_input_async()
                        command = user_input.strip()
                        if not command:
                            continue

                        if _is_exit_command(command):
                            _restore_terminal()
                            console.print("\nGoodbye!")
                            break
                        if _handle_interactive_command(
                            command,
                            session_id=session_id,
                            workspace=config.workspace_path,
                            model=config.agents.defaults.model,
                        ):
                            continue

                        turn_done.clear()
                        turn_response.clear()
                        timeline.start_turn()

                        await bus.publish_inbound(InboundMessage(
                            channel=cli_channel,
                            sender_id="user",
                            chat_id=cli_chat_id,
                            content=user_input,
                        ))

                        with _thinking_ctx():
                            await turn_done.wait()

                        timeline._flush_tool()
                        if turn_response:
                            _print_agent_response(turn_response[0], render_markdown=markdown)
                    except KeyboardInterrupt:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
                    except EOFError:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
            finally:
                agent_loop.stop()
                outbound_task.cancel()
                await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
                await agent_loop.close_mcp()

        asyncio.run(run_interactive())


# ============================================================================
# Memory Commands
# ============================================================================


memory_app = typer.Typer(help="Manage memory backends and artifacts")
app.add_typer(memory_app, name="memory")


def _build_memory_orchestrator(config_path: str | None = None, workspace: str | None = None):
    """Create a memory orchestrator from runtime config."""
    from fagent.memory.orchestrator import MemoryOrchestrator
    from fagent.providers.factory import ProviderFactory

    config = _load_runtime_config(config_path, workspace)
    sync_workspace_templates(config.workspace_path, silent=True)
    provider = None
    provider_factory = ProviderFactory(config)
    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    provider_cfg = config.get_provider(model)
    if provider_name == "openai_codex" or model.startswith("openai-codex/"):
        provider = _make_provider(config)
    elif provider_name == "custom":
        provider = _make_provider(config)
    elif provider_name == "azure_openai" and provider_cfg and provider_cfg.api_key and provider_cfg.api_base:
        provider = _make_provider(config)
    elif provider_cfg and provider_cfg.api_key:
        provider = _make_provider(config)
    return config, MemoryOrchestrator(
        workspace=config.workspace_path,
        provider=provider,
        config=config.memory,
        model=config.agents.defaults.model,
        app_config=config,
        provider_factory=provider_factory,
    )


@memory_app.command("doctor")
def memory_doctor(
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Show memory backend health."""
    _, orchestrator = _build_memory_orchestrator(config, workspace)
    status = orchestrator.doctor()
    table = Table(title="Memory Health")
    table.add_column("Backend", style="cyan")
    table.add_column("Healthy", style="green")
    for name, ok in status.items():
        table.add_row(name, "yes" if ok else "no")
    console.print(table)

    registry_table = Table(title="Memory Registry")
    registry_table.add_column("Metric", style="cyan")
    registry_table.add_column("Value", style="green")
    registry_table.add_row("Artifacts", str(len(orchestrator.registry.list_artifacts(limit=10000))))
    registry_table.add_row("Task Nodes", str(len(orchestrator.registry.search_task_nodes("", limit=1000))))
    registry_table.add_row("Experience Patterns", str(len(orchestrator.registry.list_experience_patterns(limit=1000))))
    console.print(registry_table)

    graph_jobs = orchestrator.registry.list_graph_jobs(limit=5)
    if graph_jobs:
        graph_table = Table(title="Recent Graph Jobs")
        graph_table.add_column("Episode", style="cyan")
        graph_table.add_column("Status", style="green")
        graph_table.add_column("Attempts", style="yellow")
        graph_table.add_column("Error", style="red")
        for row in graph_jobs:
            graph_table.add_row(str(row["episode_id"]), str(row["status"]), str(row["attempts"]), str(row["error"])[:80])
        console.print(graph_table)


@memory_app.command("query")
def memory_query(
    query: str = typer.Argument(..., help="Search query"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Query all memory stores."""
    _, orchestrator = _build_memory_orchestrator(config, workspace)
    results = orchestrator.query(query)
    if not results:
        console.print("[yellow]No memory matches found.[/yellow]")
        raise typer.Exit(0)
    for item in results:
        console.print(f"- {item}")


@memory_app.command("query-v2")
def memory_query_v2(
    query: str = typer.Argument(..., help="Search query"),
    session_scope: str | None = typer.Option(None, "--session", "-s", help="Limit retrieval to one session key"),
    strategy: str = typer.Option("balanced", "--strategy", help="cheap | balanced | evidence_first"),
    top_k: int = typer.Option(6, "--top-k", help="Max results"),
    allow_raw_escalation: bool = typer.Option(False, "--raw", help="Allow raw session evidence fallback"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Query memory with router-aware retrieval and evidence escalation."""
    _, orchestrator = _build_memory_orchestrator(config, workspace)

    async def _run():
        return await orchestrator.search_v2(
            query,
            strategy=strategy,
            top_k=top_k,
            session_scope=session_scope,
            allow_raw_escalation=allow_raw_escalation,
        )

    payload = asyncio.run(_run())
    console.print(f"[bold]Intent:[/bold] {payload['intent']}")
    console.print(f"[bold]Strategy:[/bold] {payload['retrieval_strategy']}")
    console.print(f"[bold]Confidence:[/bold] {payload['confidence']:.2f}")
    console.print(f"[bold]Stores:[/bold] {', '.join(payload['used_stores'])}")
    console.print(f"[bold]Raw escalated:[/bold] {'yes' if payload['raw_escalated'] else 'no'}")
    if not payload["results"]:
        console.print("[yellow]No memory matches found.[/yellow]")
        raise typer.Exit(0)

    table = Table(title="Memory Search V2")
    table.add_column("Artifact", style="cyan")
    table.add_column("Store", style="magenta")
    table.add_column("Score", style="green")
    table.add_column("Reason", style="yellow")
    table.add_column("Snippet", style="white")
    for item in payload["results"]:
        table.add_row(
            item.artifact_id,
            item.store,
            f"{item.score:.3f}",
            item.reason,
            item.snippet[:140],
        )
    console.print(table)


@memory_app.command("inspect-session")
def memory_inspect_session(
    session_key: str = typer.Argument(..., help="Session key, e.g. cli:direct"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Show summary, workflow state, and task state for one session."""
    _, orchestrator = _build_memory_orchestrator(config, workspace)
    summary = orchestrator.registry.latest_session_rollup(session_key)
    workflow_rows = orchestrator.registry.latest_workflow_snapshots(session_key, limit=5)
    task_rows = orchestrator.registry.list_task_nodes(session_key, limit=12)

    console.print(f"[bold]Session:[/bold] {session_key}")
    if summary is not None:
        console.print("\n[bold]Latest Summary[/bold]")
        console.print(summary["summary"])
    else:
        console.print("\n[yellow]No session summary found.[/yellow]")

    workflow_table = Table(title="Workflow Snapshots")
    workflow_table.add_column("Snapshot", style="cyan")
    workflow_table.add_column("Turn", style="magenta")
    workflow_table.add_column("State", style="white")
    workflow_table.add_column("Next", style="green")
    for row in workflow_rows:
        workflow_table.add_row(str(row["snapshot_id"]), str(row["turn_id"]), str(row["current_state"])[:120], str(row["next_step"])[:80])
    if workflow_rows:
        console.print(workflow_table)

    task_table = Table(title="Task Graph")
    task_table.add_column("Node", style="cyan")
    task_table.add_column("Type", style="magenta")
    task_table.add_column("Status", style="green")
    task_table.add_column("Summary", style="white")
    for row in task_rows:
        task_table.add_row(str(row["node_id"]), str(row["node_type"]), str(row["status"]), str(row["summary"])[:120])
    if task_rows:
        console.print(task_table)


@memory_app.command("inspect-task-graph")
def memory_inspect_task_graph(
    session_key: str = typer.Argument(..., help="Session key, e.g. cli:direct"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Inspect task graph nodes and edges for one session."""
    _, orchestrator = _build_memory_orchestrator(config, workspace)
    nodes = orchestrator.registry.list_task_nodes(session_key, limit=32)
    if not nodes:
        console.print("[yellow]No task graph nodes found.[/yellow]")
        raise typer.Exit(0)

    node_table = Table(title=f"Task Nodes: {session_key}")
    node_table.add_column("Node", style="cyan")
    node_table.add_column("Type", style="magenta")
    node_table.add_column("Status", style="green")
    node_table.add_column("Source", style="yellow")
    for row in nodes:
        node_table.add_row(str(row["node_id"]), str(row["node_type"]), str(row["status"]), str(row["source_artifact_id"]))
    console.print(node_table)

    edge_table = Table(title=f"Task Edges: {session_key}")
    edge_table.add_column("Source", style="cyan")
    edge_table.add_column("Relation", style="magenta")
    edge_table.add_column("Target", style="green")
    seen = 0
    for row in nodes:
        for edge in orchestrator.registry.get_task_edges_for_node(str(row["task_id"]), str(row["node_id"]), limit=16):
            edge_table.add_row(str(edge["source_node_id"]), str(edge["relation"]), str(edge["target_node_id"]))
            seen += 1
    if seen:
        console.print(edge_table)
    else:
        console.print("[yellow]No task graph edges found.[/yellow]")


@memory_app.command("inspect-experience")
def memory_inspect_experience(
    session_key: str | None = typer.Option(None, "--session", "-s", help="Optional session key filter"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Inspect repeated operational experience patterns."""
    _, orchestrator = _build_memory_orchestrator(config, workspace)
    patterns = orchestrator.registry.list_experience_patterns(session_key=session_key, limit=32)
    if not patterns:
        console.print("[yellow]No experience patterns found.[/yellow]")
        raise typer.Exit(0)
    table = Table(title="Experience Patterns")
    table.add_column("Pattern", style="cyan")
    table.add_column("Category", style="magenta")
    table.add_column("Evidence", style="green")
    table.add_column("Trigger", style="white")
    table.add_column("Recovery", style="yellow")
    for pattern in patterns:
        table.add_row(
            pattern.pattern_key,
            pattern.category,
            str(pattern.evidence_count),
            pattern.trigger[:80],
            pattern.recovery[:80],
        )
    console.print(table)


@memory_app.command("backfill")
def memory_backfill(
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Backfill sessions into file, vector, and graph memory."""
    from fagent.session.manager import SessionManager

    loaded, orchestrator = _build_memory_orchestrator(config, workspace)
    sessions = SessionManager(loaded.workspace_path).load_all_sessions()

    async def _run():
        return await orchestrator.backfill_sessions(sessions)

    count = asyncio.run(_run())
    console.print(f"[green]✓[/green] Backfilled {count} episode(s).")


@memory_app.command("rebuild-vectors")
def memory_rebuild_vectors(
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Rebuild the vector index from registered artifacts."""
    _, orchestrator = _build_memory_orchestrator(config, workspace)

    async def _run():
        return await orchestrator.rebuild_vectors()

    count = asyncio.run(_run())
    console.print(f"[green]✓[/green] Re-indexed {count} artifact(s) into vector memory.")


@memory_app.command("rebuild-graph")
def memory_rebuild_graph(
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Rebuild graph memory from stored session-turn artifacts."""
    _, orchestrator = _build_memory_orchestrator(config, workspace)

    async def _run():
        return await orchestrator.rebuild_graph()

    count = asyncio.run(_run())
    console.print(f"[green]✓[/green] Rebuilt graph memory for {count} episode(s).")


@memory_app.command("graph-ui")
def memory_graph_ui(
    query: str | None = typer.Option(None, "--query", help="Initial graph search query"),
    session_scope: str | None = typer.Option(None, "--session", "-s", help="Optional session filter"),
    port: int = typer.Option(0, "--port", "-p", help="Preferred local port (0 = auto)"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open browser automatically"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Start the local graph viewer/editor."""
    loaded, orchestrator = _build_memory_orchestrator(config, workspace)
    manager = _get_graph_ui_manager(loaded.workspace_path)
    url = manager.start(
        orchestrator,
        port=port,
        query=query,
        session_key=session_scope,
        open_browser=open_browser,
    )
    console.print(f"[green]✓[/green] Graph UI: {url}")
    try:
        manager.wait_forever()
    except KeyboardInterrupt:
        manager.stop()


@memory_app.command("graph-ui-install")
def memory_graph_ui_install(
    force: bool = typer.Option(False, "--force", "-f", help="Reinstall even if already built"),
):
    """Build the graph-ui-new frontend (requires Node.js >= 18 and npm).

    Run this once after installing/upgrading fagent to compile the new graph UI.
    The compiled files are placed in fagent/static/graph-ui-new/out/ and served
    automatically by the graph UI server.
    """
    import shutil
    import subprocess

    # Resolve the source directory for graph-ui-new
    # Works both from an installed package and from the development repo
    pkg_ui = Path(__file__).parent.parent / "static" / "graph-ui-new"  # installed package
    src_ui = Path(__file__).parent.parent.parent / "fagent" / "static" / "graph-ui-new"  # dev repo

    ui_source: Path | None = None
    for candidate in (pkg_ui, src_ui):
        if (candidate / "package.json").exists():
            ui_source = candidate
            break

    if ui_source is None:
        console.print("[red]graph-ui-new source not found.[/red]")
        console.print("Try reinstalling: pip install --force-reinstall fagent")
        raise typer.Exit(1)

    out_dir = ui_source / "out"

    if out_dir.exists() and not force:
        console.print(f"[green]✓[/green] Graph UI already built at {out_dir}")
        console.print("Pass [bold]--force[/bold] to rebuild.")
        raise typer.Exit(0)

    # Check npm
    if not shutil.which("npm"):
        console.print("[red]npm not found. Please install Node.js >= 18.[/red]")
        console.print("  https://nodejs.org/en/download")
        raise typer.Exit(1)

    node_version = subprocess.run(
        ["node", "--version"], capture_output=True, text=True
    ).stdout.strip()
    npm_version = subprocess.run(
        ["npm", "--version"], capture_output=True, text=True
    ).stdout.strip()
    _print_info(f"Node.js {node_version}, npm {npm_version}")
    _print_info(f"Source: {ui_source}")

    _print_brand_banner("Graph UI build")

    # Install dependencies
    try:
        _print_info("Installing npm dependencies (this may take a minute)…")
        subprocess.run(
            ["npm", "install", "--legacy-peer-deps"],
            cwd=ui_source,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]npm install failed: {e}[/red]")
        raise typer.Exit(1)

    # Build static export
    try:
        _print_info("Building static export (next build)…")
        subprocess.run(
            ["npm", "run", "build"],
            cwd=ui_source,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        raise typer.Exit(1)

    if not out_dir.exists():
        console.print("[red]Build completed but out/ directory not found — check next.config.mjs.[/red]")
        raise typer.Exit(1)

    _print_success(f"Graph UI built successfully → {out_dir}")
    console.print("You can now run: [bold]fagent memory graph-ui[/bold]")


@memory_app.command("inspect-graph-jobs")
def memory_inspect_graph_jobs(
    limit: int = typer.Option(12, "--limit", "-n", help="Number of recent graph jobs"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Inspect recent graph extraction jobs."""
    _, orchestrator = _build_memory_orchestrator(config, workspace)
    rows = orchestrator.registry.list_graph_jobs(limit=limit)
    if not rows:
        console.print("[yellow]No graph jobs found.[/yellow]")
        raise typer.Exit(0)
    table = Table(title="Graph Jobs")
    table.add_column("Episode", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Attempts", style="yellow")
    table.add_column("Updated", style="magenta")
    table.add_column("Error", style="red")
    for row in rows:
        table.add_row(
            str(row["episode_id"]),
            str(row["status"]),
            str(row["attempts"]),
            str(row["updated_at"]),
            str(row["error"])[:120],
        )
    console.print(table)


# ============================================================================
# Channel Commands
# ============================================================================


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status():
    """Show channel status."""
    from fagent.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Configuration", style="yellow")

    # WhatsApp
    wa = config.channels.whatsapp
    table.add_row(
        "WhatsApp",
        "✓" if wa.enabled else "✗",
        wa.bridge_url
    )

    dc = config.channels.discord
    table.add_row(
        "Discord",
        "✓" if dc.enabled else "✗",
        dc.gateway_url
    )

    # Feishu
    fs = config.channels.feishu
    fs_config = f"app_id: {fs.app_id[:10]}..." if fs.app_id else "[dim]not configured[/dim]"
    table.add_row(
        "Feishu",
        "✓" if fs.enabled else "✗",
        fs_config
    )

    # Mochat
    mc = config.channels.mochat
    mc_base = mc.base_url or "[dim]not configured[/dim]"
    table.add_row(
        "Mochat",
        "✓" if mc.enabled else "✗",
        mc_base
    )

    # Telegram
    tg = config.channels.telegram
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
    table.add_row(
        "Telegram",
        "✓" if tg.enabled else "✗",
        tg_config
    )

    # Slack
    slack = config.channels.slack
    slack_config = "socket" if slack.app_token and slack.bot_token else "[dim]not configured[/dim]"
    table.add_row(
        "Slack",
        "✓" if slack.enabled else "✗",
        slack_config
    )

    # DingTalk
    dt = config.channels.dingtalk
    dt_config = f"client_id: {dt.client_id[:10]}..." if dt.client_id else "[dim]not configured[/dim]"
    table.add_row(
        "DingTalk",
        "✓" if dt.enabled else "✗",
        dt_config
    )

    # QQ
    qq = config.channels.qq
    qq_config = f"app_id: {qq.app_id[:10]}..." if qq.app_id else "[dim]not configured[/dim]"
    table.add_row(
        "QQ",
        "✓" if qq.enabled else "✗",
        qq_config
    )

    # Email
    em = config.channels.email
    em_config = em.imap_host if em.imap_host else "[dim]not configured[/dim]"
    table.add_row(
        "Email",
        "✓" if em.enabled else "✗",
        em_config
    )

    console.print(table)


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    import shutil
    import subprocess

    # User's bridge location
    from fagent.config.paths import get_bridge_install_dir

    user_bridge = get_bridge_install_dir()

    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge

    # Check for npm
    if not shutil.which("npm"):
        console.print("[red]npm not found. Please install Node.js >= 18.[/red]")
        raise typer.Exit(1)

    # Find source bridge: first check package data, then source dir
    pkg_bridge = Path(__file__).parent.parent / "bridge"  # fagent/bridge (installed)
    src_bridge = Path(__file__).parent.parent.parent / "bridge"  # repo root/bridge (dev)

    source = None
    if (pkg_bridge / "package.json").exists():
        source = pkg_bridge
    elif (src_bridge / "package.json").exists():
        source = src_bridge

    if not source:
        console.print("[red]Bridge source not found.[/red]")
        console.print("Try reinstalling: pip install --force-reinstall fagent")
        raise typer.Exit(1)

    _print_brand_banner("Bridge setup")

    # Copy to user directory
    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))

    # Install and build
    try:
        _print_info("Installing bridge dependencies...")
        subprocess.run(["npm", "install"], cwd=user_bridge, check=True, capture_output=True)

        _print_info("Building bridge bundle...")
        subprocess.run(["npm", "run", "build"], cwd=user_bridge, check=True, capture_output=True)

        _print_success("Bridge ready")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)

    return user_bridge


@channels_app.command("login")
def channels_login():
    """Link device via QR code."""
    import subprocess

    from fagent.config.loader import load_config
    from fagent.config.paths import get_runtime_subdir

    config = load_config()
    bridge_dir = _get_bridge_dir()

    _print_brand_banner("Bridge login")
    _print_info("Scan the QR code to connect.")

    env = {**os.environ}
    if config.channels.whatsapp.bridge_token:
        env["BRIDGE_TOKEN"] = config.channels.whatsapp.bridge_token
    env["AUTH_DIR"] = str(get_runtime_subdir("whatsapp-auth"))

    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True, env=env)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js.[/red]")


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show fagent status."""
    from fagent.config.loader import get_config_path, load_config

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    _print_brand_banner("Runtime status")
    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        from fagent.providers.registry import PROVIDERS

        console.print(f"Model: {config.agents.defaults.model}")

        # Check API keys from registry
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            if spec.is_oauth:
                console.print(f"{spec.label}: [green]✓ (OAuth)[/green]")
            elif spec.is_local:
                # Local deployments show api_base instead of api_key
                if p.api_base:
                    console.print(f"{spec.label}: [green]✓ {p.api_base}[/green]")
                else:
                    console.print(f"{spec.label}: [dim]not set[/dim]")
            else:
                has_key = bool(p.api_key)
                console.print(f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}")


@app.command()
def skills():
    """List available skills."""
    from fagent.config.loader import load_config
    from fagent.agent.skills import SkillsLoader

    config = load_config()
    workspace = config.workspace_path
    loader = SkillsLoader(workspace)

    _print_brand_banner("Available Skills")

    all_skills = loader.list_skills(filter_unavailable=False)

    if not all_skills:
        console.print("[dim]No skills found[/dim]")
        return

    table = Table(box=box.ROUNDED, show_header=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Description", style="white")
    table.add_column("Source", style="dim", no_wrap=True)
    table.add_column("Status", style="green", no_wrap=True)

    for skill in all_skills:
        name = skill["name"]
        desc = loader._get_skill_description(name)
        source = skill["source"]
        meta = loader._get_skill_meta(name)
        available = loader._check_requirements(meta)
        status = "✓" if available else "✗"
        status_style = "green" if available else "red"

        table.add_row(
            name,
            desc[:60] + "..." if len(desc) > 60 else desc,
            source,
            f"[{status_style}]{status}[/{status_style}]"
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(all_skills)} skills[/dim]")
    console.print(f"[dim]Workspace: {workspace / 'skills'}[/dim]")


# ============================================================================
# OAuth Login
# ============================================================================

provider_app = typer.Typer(help="Manage providers")
app.add_typer(provider_app, name="provider")


_LOGIN_HANDLERS: dict[str, callable] = {}


def _register_login(name: str):
    def decorator(fn):
        _LOGIN_HANDLERS[name] = fn
        return fn
    return decorator


@provider_app.command("login")
def provider_login(
    provider: str = typer.Argument(..., help="OAuth provider (e.g. 'openai-codex', 'github-copilot')"),
):
    """Authenticate with an OAuth provider."""
    from fagent.providers.registry import PROVIDERS

    key = provider.replace("-", "_")
    spec = next((s for s in PROVIDERS if s.name == key and s.is_oauth), None)
    if not spec:
        names = ", ".join(s.name.replace("_", "-") for s in PROVIDERS if s.is_oauth)
        console.print(f"[red]Unknown OAuth provider: {provider}[/red]  Supported: {names}")
        raise typer.Exit(1)

    handler = _LOGIN_HANDLERS.get(spec.name)
    if not handler:
        console.print(f"[red]Login not implemented for {spec.label}[/red]")
        raise typer.Exit(1)

    console.print(f"{__logo__} OAuth Login - {spec.label}\n")
    handler()


@_register_login("openai_codex")
def _login_openai_codex() -> None:
    try:
        from oauth_cli_kit import get_token, login_oauth_interactive
        token = None
        try:
            token = get_token()
        except Exception:
            pass
        if not (token and token.access):
            console.print("[cyan]Starting interactive OAuth login...[/cyan]\n")
            token = login_oauth_interactive(
                print_fn=lambda s: console.print(s),
                prompt_fn=lambda s: typer.prompt(s),
            )
        if not (token and token.access):
            console.print("[red]✗ Authentication failed[/red]")
            raise typer.Exit(1)
        console.print(f"[green]✓ Authenticated with OpenAI Codex[/green]  [dim]{token.account_id}[/dim]")
    except ImportError:
        console.print("[red]oauth_cli_kit not installed. Run: pip install oauth-cli-kit[/red]")
        raise typer.Exit(1)


@_register_login("github_copilot")
def _login_github_copilot() -> None:
    import asyncio

    console.print("[cyan]Starting GitHub Copilot device flow...[/cyan]\n")

    async def _trigger():
        from litellm import acompletion
        await acompletion(model="github_copilot/gpt-4o", messages=[{"role": "user", "content": "hi"}], max_tokens=1)

    try:
        asyncio.run(_trigger())
        console.print("[green]✓ Authenticated with GitHub Copilot[/green]")
    except Exception as e:
        console.print(f"[red]Authentication error: {e}[/red]")
        raise typer.Exit(1)


# ============================================================================
# Agent Management
# ============================================================================

agent_app = typer.Typer(help="Manage agents")
app.add_typer(agent_app, name="agent")


@agent_app.command("create")
def agent_create(
    name: str = typer.Argument(..., help="Agent name"),
    model: str = typer.Option(None, help="Model to use (e.g., 'anthropic/claude-sonnet-4')"),
):
    """Create a new agent configuration."""
    from fagent.config.loader import get_config_path, load_config, save_config
    from fagent.config.schema import AgentConfig

    config = load_config()

    if name in config.agents.agents:
        console.print(f"[red]Agent '{name}' already exists[/red]")
        raise typer.Exit(1)

    agent_config = AgentConfig(model=model)
    config.agents.agents[name] = agent_config

    save_config(config)
    console.print(f"[green]✓ Agent '{name}' created[/green]")
    if model:
        console.print(f"  Model: {model}")


@agent_app.command("list")
def agent_list():
    """List all configured agents."""
    from fagent.config.loader import load_config

    config = load_config()

    if not config.agents.agents:
        console.print("[dim]No agents configured[/dim]")
        return

    table = Table(title="Configured Agents", box=box.ROUNDED)
    table.add_column("Name", style="cyan")
    table.add_column("Model", style="green")
    table.add_column("Temperature", style="yellow")
    table.add_column("Max Tokens", style="blue")

    for name, agent_config in config.agents.agents.items():
        model = agent_config.model or config.agents.defaults.model
        temp = str(agent_config.temperature) if agent_config.temperature is not None else "default"
        tokens = str(agent_config.max_tokens) if agent_config.max_tokens is not None else "default"
        table.add_row(name, model, temp, tokens)

    console.print(table)


@agent_app.command("delete")
def agent_delete(name: str = typer.Argument(..., help="Agent name")):
    """Delete an agent configuration."""
    from fagent.config.loader import load_config, save_config

    config = load_config()

    if name not in config.agents.agents:
        console.print(f"[red]Agent '{name}' not found[/red]")
        raise typer.Exit(1)

    del config.agents.agents[name]
    save_config(config)
    console.print(f"[green]✓ Agent '{name}' deleted[/green]")


@agent_app.command("config")
def agent_config(name: str = typer.Argument(..., help="Agent name")):
    """Show agent configuration."""
    from fagent.config.loader import load_config

    config = load_config()

    if name not in config.agents.agents:
        console.print(f"[red]Agent '{name}' not found[/red]")
        raise typer.Exit(1)

    agent = config.agents.agents[name]
    defaults = config.agents.defaults

    console.print(f"\n[cyan]Agent: {name}[/cyan]\n")
    console.print(f"Model: {agent.model or defaults.model}")
    console.print(f"Temperature: {agent.temperature if agent.temperature is not None else defaults.temperature}")
    console.print(f"Max Tokens: {agent.max_tokens if agent.max_tokens is not None else defaults.max_tokens}")
    console.print(f"Vector Memory: {'disabled' if agent.disable_vector_memory else 'enabled'}")
    console.print(f"Shadow Context: {'disabled' if agent.disable_shadow_context else 'enabled'}")
    console.print(f"Graph Memory: {'disabled' if agent.disable_graph_memory else 'enabled'}")


if __name__ == "__main__":
    app()
