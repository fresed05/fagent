"""State tracker for active sessions."""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from fagent.recovery.types import RecoveryState, SessionState

logger = logging.getLogger(__name__)


class StateTracker:
    """Tracks active sessions and persists state to disk."""

    def __init__(self, workspace: Path, gateway_pid: int):
        self.workspace = workspace
        self.gateway_pid = gateway_pid
        self.gateway_start_time = datetime.now()
        self.state_dir = workspace / "recovery"
        self.state_file = self.state_dir / "active_sessions.json"
        self._sessions: Dict[str, SessionState] = {}
        self._write_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        self.state_dir.mkdir(parents=True, exist_ok=True)

    def mark_processing(
        self, session_key: str, channel: str, chat_id: str, turn_id: str
    ) -> None:
        """Mark session as processing."""
        now = datetime.now()
        self._sessions[session_key] = SessionState(
            session_key=session_key,
            status="processing",
            started_at=now,
            last_heartbeat=now,
            channel=channel,
            chat_id=chat_id,
            turn_id=turn_id,
            task_count=1,
        )
        self._schedule_write()

    def mark_completed(self, session_key: str) -> None:
        """Mark session as completed."""
        if session_key in self._sessions:
            self._sessions[session_key].status = "idle"
            self._sessions[session_key].last_heartbeat = datetime.now()
            self._schedule_write()

    def mark_error(self, session_key: str) -> None:
        """Mark session as error."""
        if session_key in self._sessions:
            self._sessions[session_key].status = "error"
            self._sessions[session_key].last_heartbeat = datetime.now()
            self._schedule_write()

    def update_health(self, session_key: str, health: Dict) -> None:
        """Update session health metrics."""
        if session_key in self._sessions:
            self._sessions[session_key].health = health
            self._sessions[session_key].last_heartbeat = datetime.now()
            self._schedule_write()

    def _schedule_write(self) -> None:
        """Schedule debounced write."""
        if self._write_task and not self._write_task.done():
            return

        async def _delayed_write():
            await asyncio.sleep(1.0)
            self._write_state()

        self._write_task = asyncio.create_task(_delayed_write())

    def _write_state(self) -> None:
        """Write state to disk atomically."""
        temp_path = self.state_file.with_suffix(".json.tmp")

        try:
            state = RecoveryState(
                version="1.0",
                gateway_pid=self.gateway_pid,
                gateway_start_time=self.gateway_start_time,
                last_updated=datetime.now(),
                sessions=self._sessions.copy(),
            )

            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, indent=2, default=str)

            temp_path.replace(self.state_file)
        except OSError as e:
            logger.error(f"Failed to write recovery state: {e}")
