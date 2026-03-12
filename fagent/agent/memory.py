"""Compatibility wrappers for explicit file memory and session consolidation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from fagent.memory.file_store import FileMemoryStore
from fagent.memory.orchestrator import MemoryOrchestrator

if TYPE_CHECKING:
    from fagent.config.schema import MemoryConfig
    from fagent.providers.base import LLMProvider
    from fagent.session.manager import Session


class MemoryStore(FileMemoryStore):
    """Backward-compatible handle for explicit file memory access."""

    async def consolidate(
        self,
        session: "Session",
        provider: "LLMProvider",
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
    ) -> bool:
        """Legacy consolidation no longer writes file memory automatically."""
        del session, provider, model, archive_all, memory_window
        return True


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
