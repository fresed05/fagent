"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import time
import weakref
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from fagent.agent.context import ContextBuilder
from fagent.agent.memory import consolidate_session_memory
from fagent.agent.subagent import SubagentManager
from fagent.recovery.tracker import StateTracker
from fagent.agent.tools.cron import CronTool
from fagent.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from fagent.agent.tools.memory_search import (
    MemoryGetArtifactTool,
    MemoryGetEntityTool,
    MemorySearchTool,
)
from fagent.agent.tools.message import MessageTool
from fagent.agent.tools.moa import MoaTool
from fagent.agent.tools.registry import ToolRegistry
from fagent.agent.tools.shell import ExecTool
from fagent.agent.tools.spawn import SpawnTool
from fagent.agent.tools.web import WebFetchTool, WebSearchTool
from fagent.agent.tools.workflow import WorkflowTool
from fagent.bus.events import InboundMessage, OutboundMessage
from fagent.bus.queue import MessageBus
from fagent.memory.graph_ui import get_graph_ui_manager
from fagent.providers.factory import ProviderFactory
from fagent.providers.base import LLMProvider
from fagent.memory.orchestrator import MemoryOrchestrator, NullMemoryOrchestrator
from fagent.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from fagent.config.schema import ChannelsConfig, Config, ExecToolConfig, MemoryConfig
    from fagent.cron.service import CronService


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    _TOOL_RESULT_MAX_CHARS = 1600

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        memory_window: int = 100,
        reasoning_effort: str | None = None,
        brave_api_key: str | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        memory_config: MemoryConfig | None = None,
        app_config: Config | None = None,
    ):
        from fagent.config.schema import ExecToolConfig
        self.bus = bus
        self.channels_config = channels_config
        self.memory_config = memory_config
        self.app_config = app_config
        self.provider_factory = ProviderFactory(app_config) if app_config else None
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.reasoning_effort = reasoning_effort
        self.brave_api_key = brave_api_key
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace

        self.context = ContextBuilder(workspace)
        self.sessions = session_manager or SessionManager(workspace)
        try:
            self.memory = MemoryOrchestrator(
                workspace=workspace,
                provider=provider,
                config=memory_config,
                model=self.model,
                app_config=app_config,
                provider_factory=self.provider_factory,
            )
        except Exception as exc:
            logger.warning("Memory subsystem unavailable, continuing without it: {}", exc)
            self.memory = NullMemoryOrchestrator()
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            reasoning_effort=reasoning_effort,
            brave_api_key=brave_api_key,
            web_proxy=web_proxy,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress
        self._consolidation_tasks: set[asyncio.Task] = set()  # Strong refs to in-flight tasks
        self._consolidation_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._session_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._post_turn_tasks: set[asyncio.Task] = set()
        self._state_tracker = StateTracker(workspace, os.getpid())
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
            path_append=self.exec_config.path_append,
        ))
        self.tools.register(WebSearchTool(api_key=self.brave_api_key, proxy=self.web_proxy))
        self.tools.register(WebFetchTool(proxy=self.web_proxy))
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        self.tools.register(MemorySearchTool(memory=self.memory))
        self.tools.register(MemoryGetArtifactTool(memory=self.memory))
        self.tools.register(MemoryGetEntityTool(memory=self.memory))
        workflow_light_role = self.app_config.resolve_model_role("workflow_light", self.model) if self.app_config else None
        workflow_provider = self.provider
        if self.provider_factory and workflow_light_role and workflow_light_role.provider_kind not in ("", "inherit"):
            workflow_provider = self.provider_factory.build_from_profile(workflow_light_role)
        self.tools.register(WorkflowTool(
            tool_registry=self.tools,
            workspace=self.workspace,
            provider=workflow_provider,
            model=(workflow_light_role.model if workflow_light_role and workflow_light_role.model else self.model),
            max_tokens=min(1200, self.max_tokens),
            repair_callback=lambda category, trigger, recovery, session_key=None: self.memory.record_experience_event(
                category=category,
                session_key=session_key or "runtime",
                trigger_text=trigger,
                recovery_text=recovery,
                metadata={"source": "workflow_tool"},
            ),
        ))
        if self.provider_factory and self.app_config and self.app_config.tools.moa.enabled:
            self.tools.register(MoaTool(provider_factory=self.provider_factory, config=self.app_config.tools.moa))
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from fagent.agent.tools.mcp import connect_mcp_servers
        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
            self._mcp_connected = True
        except Exception as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    pass
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for all tools that need routing info."""
        for name in ("message", "spawn", "cron"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    tool.set_context(channel, chat_id, *([message_id] if name == "message" else []))
        if workflow_tool := self.tools.get("run_workflow"):
            if hasattr(workflow_tool, "set_context"):
                workflow_tool.set_context(f"{channel}:{chat_id}")

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Format tool calls as concise hint, e.g. 'web_search("query")'."""
        def _fmt(tc):
            args = (tc.arguments[0] if isinstance(tc.arguments, list) else tc.arguments) or {}
            val = next(iter(args.values()), None) if isinstance(args, dict) else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'
        return ", ".join(_fmt(tc) for tc in tool_calls)

    @staticmethod
    def _tool_preview(tool_name: str, arguments: dict[str, Any] | list[Any] | None) -> str:
        args = (arguments[0] if isinstance(arguments, list) and arguments else arguments) or {}
        if not isinstance(args, dict):
            return tool_name
        val = next(iter(args.values()), None) if args else None
        if not isinstance(val, str):
            return tool_name
        return f'{tool_name}("{val[:40]}...")' if len(val) > 40 else f'{tool_name}("{val}")'

    @staticmethod
    def _extract_skill_read(tool_name: str, arguments: dict[str, Any] | list[Any] | None) -> str | None:
        if tool_name != "read_file":
            return None
        args = (arguments[0] if isinstance(arguments, list) and arguments else arguments) or {}
        if not isinstance(args, dict):
            return None
        raw_path = args.get("path")
        if not isinstance(raw_path, str) or not raw_path.endswith("SKILL.md"):
            return None
        normalized = raw_path.replace("\\", "/")
        parts = [p for p in normalized.split("/") if p]
        try:
            idx = len(parts) - 1 - parts[::-1].index("skills")
        except ValueError:
            return None
        skill_parts = parts[idx + 1 : -1]
        if not skill_parts:
            return None
        return "/".join(skill_parts)

    async def _emit_progress(
        self,
        callback: Callable[..., Awaitable[None]] | None,
        content: str,
        *,
        stage: str,
        status: str = "running",
        event: str = "stage",
        **extra: Any,
    ) -> None:
        logger.bind(
            session_key=extra.get("session_key", ""),
            turn_id=extra.get("turn_id", ""),
            stage=stage,
            status=status,
            duration_ms=extra.get("duration_ms"),
            detail=str(content)[:240],
        ).info("turn_stage")
        if callback is None:
            return
        tool_hint = event == "tool"
        try:
            signature = inspect.signature(callback)
        except (TypeError, ValueError):
            signature = None
        if signature is None:
            await callback(content, stage=stage, status=status, event=event, tool_hint=tool_hint, **extra)
            return
        params = signature.parameters
        accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())
        if accepts_kwargs or "stage" in params or "status" in params or "event" in params:
            await callback(content, stage=stage, status=status, event=event, tool_hint=tool_hint, **extra)
            return
        if "tool_hint" in params:
            if tool_hint and status not in {"running", "started"}:
                return
            await callback(content, tool_hint=tool_hint)
            return
        await callback(content)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str], list[dict], dict[str, int], int]:
        """Run the agent iteration loop. Returns (final_content, tools_used, messages, usage, tool_call_count)."""
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []
        skill_reads: list[str] = []
        usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        max_prompt_tokens = 0
        last_prompt_tokens = 0
        usage_seen = False
        tool_call_count = 0

        while iteration < self.max_iterations:
            iteration += 1

            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                reasoning_effort=self.reasoning_effort,
            )
            for key in usage_totals:
                usage_totals[key] += int(response.usage.get(key, 0))
            current_prompt_tokens = int(response.usage.get("prompt_tokens", 0) or 0)
            if current_prompt_tokens > 0:
                usage_seen = True
                last_prompt_tokens = current_prompt_tokens
                max_prompt_tokens = max(max_prompt_tokens, current_prompt_tokens)

            if response.has_tool_calls:
                tool_call_count += len(response.tool_calls)
                if on_progress:
                    thought = self._strip_think(response.content)
                    if thought:
                        await self._emit_progress(on_progress, thought, stage="Thinking", status="running", event="thinking")

                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )

                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)
                    if skill_read := self._extract_skill_read(tool_call.name, tool_call.arguments):
                        if skill_read not in skill_reads:
                            skill_reads.append(skill_read)
                            if message_tool := self.tools.get("message"):
                                if isinstance(message_tool, MessageTool):
                                    message_tool.set_turn_metadata({"_skill_reads": list(skill_reads)})
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])
                    preview = self._tool_preview(tool_call.name, tool_call.arguments)
                    if on_progress:
                        await self._emit_progress(
                            on_progress,
                            preview,
                            stage="Tool execution",
                            status="running",
                            event="tool",
                            tool_name=tool_call.name,
                            arguments_preview=preview,
                            arguments_signature=args_str[:200],
                        )
                    started_at = time.perf_counter()
                    try:
                        result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    except Exception as exc:
                        if on_progress:
                            await self._emit_progress(
                                on_progress,
                                preview,
                                stage="Tool execution",
                                status="error",
                                event="tool",
                                tool_name=tool_call.name,
                                arguments_preview=preview,
                                arguments_signature=args_str[:200],
                                duration_ms=int((time.perf_counter() - started_at) * 1000),
                                error=str(exc)[:240],
                            )
                        raise
                    if on_progress:
                        await self._emit_progress(
                            on_progress,
                            preview,
                            stage="Tool execution",
                            status="ok",
                            event="tool",
                            tool_name=tool_call.name,
                            arguments_preview=preview,
                            arguments_signature=args_str[:200],
                            duration_ms=int((time.perf_counter() - started_at) * 1000),
                        )
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                clean = self._strip_think(response.content)
                # Don't persist error responses to session history — they can
                # poison the context and cause permanent 400 loops (#1303).
                if response.finish_reason == "error":
                    logger.error("LLM returned error: {}", (clean or "")[:200])
                    final_content = clean or "Sorry, I encountered an error calling the AI model."
                    break
                messages = self.context.add_assistant_message(
                    messages, clean, reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                final_content = clean
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )

        usage_totals["last_prompt_tokens"] = last_prompt_tokens
        usage_totals["max_prompt_tokens"] = max_prompt_tokens
        usage_totals["usage_seen"] = 1 if usage_seen else 0
        return final_content, tools_used, skill_reads, messages, usage_totals, tool_call_count

    async def run(self) -> None:
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if msg.content.strip().lower() == "/stop":
                await self._handle_stop(msg)
            else:
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                task.add_done_callback(lambda t, k=msg.session_key: self._active_tasks.get(k, []) and self._active_tasks[k].remove(t) if t in self._active_tasks.get(k, []) else None)

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Cancel all active tasks and subagents for the session."""
        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        sub_cancelled = await self.subagents.cancel_by_session(msg.session_key)
        total = cancelled + sub_cancelled
        # Mark session as completed after stopping
        self._state_tracker.mark_completed(msg.session_key)
        content = f"⏹ Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message under a session-scoped lock."""
        lock_key = msg.chat_id if msg.channel == "system" else msg.session_key
        lock = self._session_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            # Create turn_id for state tracking
            session = self.sessions.get_or_create(msg.session_key)
            turn_seq = int(session.metadata.get("turn_seq", 0)) + 1
            turn_id = f"turn-{turn_seq:06d}"

            # Mark session as processing
            self._state_tracker.mark_processing(
                msg.session_key, msg.channel, msg.chat_id, turn_id
            )

            try:
                response = await self._process_message(msg)
                if response is not None:
                    await self.bus.publish_outbound(response)
                elif msg.channel == "cli":
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id,
                        content="", metadata=msg.metadata or {},
                    ))
                # Mark session as completed
                self._state_tracker.mark_completed(msg.session_key)
            except asyncio.CancelledError:
                logger.info("Task cancelled for session {}", msg.session_key)
                self._state_tracker.mark_error(msg.session_key)
                raise
            except Exception:
                logger.exception("Error processing message for session {}", msg.session_key)
                self._state_tracker.mark_error(msg.session_key)
                await self.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Sorry, I encountered an error.",
                ))

    async def close_mcp(self) -> None:
        """Close MCP connections."""
        if self._post_turn_tasks:
            await asyncio.gather(*self._post_turn_tasks, return_exceptions=True)
        await self.memory.drain()
        self.memory.close()
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (msg.chat_id.split(":", 1) if ":" in msg.chat_id
                                else ("cli", msg.chat_id))
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            history = session.get_history(max_messages=self.memory_window)
            presearch = await self.memory.search_v2(msg.content, session_scope=key)
            await self._emit_progress(
                on_progress,
                f"scope={key} stores={','.join(presearch.get('used_stores', [])) or '-'} results={presearch.get('count', 0)} confidence={float(presearch.get('confidence', 0.0)):.2f}",
                stage="Pre-search",
                status="ok",
                event="stage",
                extra=presearch,
            )
            shadow = await self.memory.prepare_shadow_context(
                msg.content,
                key,
                {"channel": channel, "chat_id": chat_id},
                presearch_bundle=presearch,
            )
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content,
                shadow_context=shadow.to_prompt_block() if shadow else None,
                runtime_memory_context=self.memory.build_runtime_context(key),
                channel=channel,
                chat_id=chat_id,
            )
            await self._emit_progress(on_progress, "Running main loop", stage="Thinking", status="started")
            final_content, tools_used, skill_reads, all_msgs, usage_totals, tool_call_count = await self._run_agent_loop(
                messages,
                on_progress=on_progress,
            )
            turn_id, saved_entries = self._save_turn(session, all_msgs, 1 + len(history))
            self._update_session_usage(session, usage_totals)
            self.sessions.save(session)
            episode = self.memory.build_episode(key, turn_id, channel, chat_id, saved_entries)
            await self._emit_progress(on_progress, (final_content or "")[:120], stage="Draft ready", status="done")
            if not msg.metadata.get("_subagent_result"):
                await self._post_turn_memory_tasks(
                    session,
                    turn_id,
                    msg.content,
                    tools_used,
                    tool_call_count,
                    saved_entries,
                    episode=episode,
                    on_progress=on_progress,
                )
            await self._emit_progress(on_progress, "Turn complete", stage="Turn complete", status="done")
            return OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=final_content or "Background task completed.",
                metadata={"_skill_reads": skill_reads},
            )

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())
            self._consolidating.add(session.key)
            try:
                async with lock:
                    snapshot = session.messages[session.last_consolidated:]
                    if snapshot:
                        temp = Session(key=session.key)
                        temp.messages = list(snapshot)
                        if not await self._consolidate_memory(temp, archive_all=True):
                            return OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content="Memory archival failed, session not cleared. Please try again.",
                            )
            except Exception:
                logger.exception("/new archival failed for {}", session.key)
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Memory archival failed, session not cleared. Please try again.",
                )
            finally:
                self._consolidating.discard(session.key)

            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="New session started.")
        if cmd == "/help":
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="⚡ fagent commands:\n/new — Start a new conversation\n/stop — Stop the current task\n/graph [query] — Open local graph UI\n/help — Show available commands",
            )
        if cmd.startswith("/graph"):
            query = msg.content.strip()[len("/graph"):].strip() or None
            manager = get_graph_ui_manager(self.workspace)
            url = manager.start(
                self.memory,
                query=query,
                session_key=key,
                open_browser=(msg.channel == "cli"),
            )
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"Graph UI: {url}",
            )

        unconsolidated = len(session.messages) - session.last_consolidated
        if (unconsolidated >= self.memory_window and session.key not in self._consolidating):
            self._consolidating.add(session.key)
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())

            async def _consolidate_and_unlock():
                try:
                    async with lock:
                        await self._consolidate_memory(session)
                finally:
                    self._consolidating.discard(session.key)
                    _task = asyncio.current_task()
                    if _task is not None:
                        self._consolidation_tasks.discard(_task)

            _task = asyncio.create_task(_consolidate_and_unlock())
            self._consolidation_tasks.add(_task)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()
                message_tool.set_turn_metadata({})

        async def _bus_progress(content: str, **kwargs: Any) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_progress_event"] = {
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
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta,
            ))

        history = session.get_history(max_messages=self.memory_window)
        presearch = await self.memory.search_v2(msg.content, session_scope=key)
        await self._emit_progress(
            on_progress or _bus_progress,
            f"scope={key} stores={','.join(presearch.get('used_stores', [])) or '-'} results={presearch.get('count', 0)} confidence={float(presearch.get('confidence', 0.0)):.2f}",
            stage="Pre-search",
            status="ok",
            event="stage",
            extra=presearch,
        )
        shadow = await self.memory.prepare_shadow_context(
            msg.content,
            key,
            {"channel": msg.channel, "chat_id": msg.chat_id},
            presearch_bundle=presearch,
        )
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            shadow_context=shadow.to_prompt_block() if shadow else None,
            runtime_memory_context=self.memory.build_runtime_context(key),
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
        )

        await self._emit_progress(on_progress or _bus_progress, "Running main loop", stage="Thinking", status="started")
        final_content, tools_used, skill_reads, all_msgs, usage_totals, tool_call_count = await self._run_agent_loop(
            initial_messages, on_progress=on_progress or _bus_progress,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        turn_id, saved_entries = self._save_turn(session, all_msgs, 1 + len(history))
        self._update_session_usage(session, usage_totals)
        self.sessions.save(session)
        episode = self.memory.build_episode(key, turn_id, msg.channel, msg.chat_id, saved_entries)
        await self._emit_progress(on_progress or _bus_progress, final_content[:120], stage="Draft ready", status="done")
        if not msg.metadata.get("_subagent_result"):
            await self._post_turn_memory_tasks(
                session,
                turn_id,
                msg.content,
                tools_used,
                tool_call_count,
                saved_entries,
                episode=episode,
                on_progress=on_progress or _bus_progress,
            )
        await self._emit_progress(on_progress or _bus_progress, "Turn complete", stage="Turn complete", status="done")

        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        meta = dict(msg.metadata or {})
        if skill_reads:
            meta["_skill_reads"] = skill_reads
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=meta,
        )

    def _update_session_usage(self, session: Session, usage_totals: dict[str, int]) -> None:
        prompt_tokens = int(usage_totals.get("last_prompt_tokens", 0) or 0)
        max_prompt_tokens = int(usage_totals.get("max_prompt_tokens", 0) or 0)
        usage_seen = bool(int(usage_totals.get("usage_seen", 0) or 0))
        total_prompt_tokens = int(session.metadata.get("total_prompt_tokens", 0))
        total_completion_tokens = int(session.metadata.get("total_completion_tokens", 0))
        if usage_seen and prompt_tokens > 0:
            session.metadata["estimated_context_tokens"] = prompt_tokens
            session.metadata["last_prompt_tokens"] = prompt_tokens
            session.metadata["max_prompt_tokens_in_turn"] = max_prompt_tokens or prompt_tokens
        else:
            session.metadata["estimated_context_tokens"] = 0
            session.metadata["last_prompt_tokens"] = 0
            session.metadata["max_prompt_tokens_in_turn"] = 0
        session.metadata["total_prompt_tokens"] = total_prompt_tokens + int(usage_totals.get("prompt_tokens", 0))
        session.metadata["total_completion_tokens"] = total_completion_tokens + int(usage_totals.get("completion_tokens", 0))
        session.metadata["last_usage"] = dict(usage_totals)

    async def _post_turn_memory_tasks(
        self,
        session: Session,
        turn_id: str,
        user_goal: str,
        tools_used: list[str],
        tool_call_count: int,
        saved_entries: list[dict],
        *,
        episode: Any = None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        seed_artifacts = []
        if (
            tools_used
            and self.memory_config
            and self.memory_config.workflow_state.enabled
            and tool_call_count >= max(1, self.memory_config.workflow_state.snapshot_every_n_tools)
        ):
            blockers = [
                str(entry.get("content", ""))[:180]
                for entry in saved_entries
                if entry.get("role") == "tool" and str(entry.get("content", "")).startswith("Error")
            ]
            workflow_artifact = self.memory.record_workflow_snapshot(
                session_key=session.key,
                turn_id=turn_id,
                step_index=tool_call_count,
                goal=user_goal[:240],
                current_state=f"Tools used: {', '.join(tools_used[:12])}",
                open_blockers=blockers[:4],
                next_step="Continue from latest tool state",
                citations=[entry.get("turn_id", turn_id) for entry in saved_entries[-4:]],
                tools_used=tools_used,
            )
            if workflow_artifact is not None:
                seed_artifacts.append(workflow_artifact)

        if episode is None:
            return

        async def _runner() -> None:
            started_at = time.perf_counter()
            try:
                await self.memory.run_post_turn_pipeline(
                    session=session,
                    episode=episode,
                    on_progress=on_progress,
                    seed_artifacts=seed_artifacts,
                )
                self.sessions.save(session)
                logger.bind(
                    session_key=session.key,
                    turn_id=turn_id,
                    stage="post_turn_pipeline",
                    status="done",
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                    detail="background pipeline completed",
                ).info("turn_stage")
            except Exception as exc:
                logger.bind(
                    session_key=session.key,
                    turn_id=turn_id,
                    stage="post_turn_pipeline",
                    status="failed",
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                    detail=str(exc)[:240],
                ).warning("turn_stage")
            finally:
                task = asyncio.current_task()
                if task is not None:
                    self._post_turn_tasks.discard(task)

        task = asyncio.create_task(_runner())
        self._post_turn_tasks.add(task)

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> tuple[str, list[dict]]:
        """Save new-turn messages into session, truncating large tool results."""
        from datetime import datetime
        turn_seq = int(session.metadata.get("turn_seq", 0)) + 1
        session.metadata["turn_seq"] = turn_seq
        turn_id = f"turn-{turn_seq:06d}"
        saved_entries: list[dict] = []
        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                head = content[:900].rstrip()
                tail = content[-260:].lstrip()
                digest = json.dumps({"sha1": hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]})
                entry["content"] = f"{head}\n...\n{tail}\n[tool_result_summary] {digest}"
            elif role == "user":
                if isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                    # Strip the runtime-context prefix, keep only the user text.
                    parts = content.split("\n\n", 1)
                    if len(parts) > 1 and parts[1].strip():
                        entry["content"] = parts[1]
                    else:
                        continue
                if isinstance(content, list):
                    filtered = []
                    for c in content:
                        if c.get("type") == "text" and isinstance(c.get("text"), str) and c["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                            continue  # Strip runtime context from multimodal messages
                        if (c.get("type") == "image_url"
                                and c.get("image_url", {}).get("url", "").startswith("data:image/")):
                            filtered.append({"type": "text", "text": "[image]"})
                        else:
                            filtered.append(c)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            entry["turn_id"] = turn_id
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
            saved_entries.append(entry)
        session.updated_at = datetime.now()
        return turn_id, saved_entries

    async def _consolidate_memory(self, session, archive_all: bool = False) -> bool:
        """Delegate to MemoryStore.consolidate(). Returns True on success."""
        if archive_all:
            return await consolidate_session_memory(
                session,
                self.provider,
                self.workspace,
                self.model,
                self.memory_config,
            )
        return await consolidate_session_memory(
            session,
            self.provider,
            self.workspace,
            self.model,
            self.memory_config,
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self._connect_mcp()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(msg, session_key=session_key, on_progress=on_progress)
        return response.content if response else ""
