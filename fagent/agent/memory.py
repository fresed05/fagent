"""Compatibility wrapper for file memory and session consolidation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger

from fagent.memory.file_store import FileMemoryStore
from fagent.memory.orchestrator import MemoryOrchestrator

if TYPE_CHECKING:
    from fagent.config.schema import MemoryConfig
    from fagent.providers.base import LLMProvider
    from fagent.session.manager import Session


_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save the memory consolidation result to persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph (2-5 sentences) summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated long-term memory as markdown. Include all existing "
                        "facts plus new ones. Return unchanged if nothing new.",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


class MemoryStore(FileMemoryStore):
    """Backward-compatible memory API with old consolidation behavior."""

    async def consolidate(
        self,
        session: "Session",
        provider: "LLMProvider",
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
    ) -> bool:
        """Consolidate old messages into MEMORY.md + HISTORY.md via LLM tool call."""
        if archive_all:
            old_messages = session.messages
            keep_count = 0
        else:
            keep_count = memory_window // 2
            if len(session.messages) <= keep_count:
                return True
            if len(session.messages) - session.last_consolidated <= 0:
                return True
            old_messages = session.messages[session.last_consolidated:-keep_count]
            if not old_messages:
                return True

        lines = []
        for message in old_messages:
            if not message.get("content"):
                continue
            tools = f" [tools: {', '.join(message['tools_used'])}]" if message.get("tools_used") else ""
            lines.append(
                f"[{message.get('timestamp', '?')[:16]}] {message['role'].upper()}{tools}: {message['content']}"
            )

        current_memory = self.read_long_term()
        prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

        try:
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a memory consolidation agent. Call the save_memory tool with your consolidation of the conversation.",
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = response.tool_calls[0].arguments
            if isinstance(args, str):
                args = json.loads(args)
            if isinstance(args, list):
                if args and isinstance(args[0], dict):
                    args = args[0]
                else:
                    logger.warning("Memory consolidation: unexpected arguments as empty or non-dict list")
                    return False
            if not isinstance(args, dict):
                logger.warning("Memory consolidation: unexpected arguments type {}", type(args).__name__)
                return False

            if entry := args.get("history_entry"):
                if not isinstance(entry, str):
                    entry = json.dumps(entry, ensure_ascii=False)
                self.append_history(entry)
            if update := args.get("memory_update"):
                if not isinstance(update, str):
                    update = json.dumps(update, ensure_ascii=False)
                if update != current_memory:
                    self.write_long_term(update)

            session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False


async def consolidate_session_memory(
    session: "Session",
    provider: "LLMProvider",
    workspace,
    model: str,
    config: "MemoryConfig | None" = None,
) -> bool:
    """Compatibility hook used by AgentLoop for old consolidation paths."""
    try:
        orchestrator = MemoryOrchestrator(workspace=workspace, provider=provider, config=config, model=model)
        return await orchestrator.consolidate_session(session)
    except Exception:
        logger.exception("Session memory consolidation failed")
        return False
