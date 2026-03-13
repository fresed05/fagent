"""Recovery manager for detecting interrupted sessions."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fagent.recovery.types import InterruptedSession, RecoveryState

logger = logging.getLogger(__name__)


class RecoveryManager:
    """Manages recovery state and detects interrupted sessions."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.state_file = workspace / "recovery" / "active_sessions.json"

    def load_state(self) -> Optional[RecoveryState]:
        """Load recovery state from disk."""
        if not self.state_file.exists():
            return None

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return RecoveryState.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to load recovery state: {e}")
            return None

    def detect_interrupted_sessions(
        self, max_age_seconds: int = 300
    ) -> List[InterruptedSession]:
        """Detect interrupted sessions from previous gateway run."""
        state = self.load_state()
        if not state:
            return []

        # Check if PID changed (actual restart)
        if state.gateway_pid == os.getpid():
            return []

        interrupted = []
        now = datetime.now()

        for session_state in state.sessions.values():
            if session_state.status != "processing":
                continue

            age = (now - session_state.last_heartbeat).total_seconds()
            if age > max_age_seconds:
                continue

            interrupted.append(
                InterruptedSession(
                    session_key=session_state.session_key,
                    channel=session_state.channel,
                    chat_id=session_state.chat_id,
                    turn_id=session_state.turn_id,
                    duration_seconds=age,
                    last_heartbeat=session_state.last_heartbeat,
                )
            )

        return interrupted

    def clear_state(self) -> None:
        """Clear recovery state file."""
        if self.state_file.exists():
            try:
                self.state_file.unlink()
            except OSError as e:
                logger.error(f"Failed to clear recovery state: {e}")
