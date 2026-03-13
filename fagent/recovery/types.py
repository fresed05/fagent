"""Data types for recovery state tracking."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


@dataclass
class SessionState:
    """State of a single session."""
    session_key: str
    status: str  # "processing" | "idle" | "error"
    started_at: datetime
    last_heartbeat: datetime
    channel: str
    chat_id: str
    turn_id: Optional[str] = None
    task_count: int = 0
    health: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "session_key": self.session_key,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "channel": self.channel,
            "chat_id": self.chat_id,
            "turn_id": self.turn_id,
            "task_count": self.task_count,
            "health": self.health,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SessionState":
        return cls(
            session_key=data["session_key"],
            status=data["status"],
            started_at=datetime.fromisoformat(data["started_at"]),
            last_heartbeat=datetime.fromisoformat(data["last_heartbeat"]),
            channel=data["channel"],
            chat_id=data["chat_id"],
            turn_id=data.get("turn_id"),
            task_count=data.get("task_count", 0),
            health=data.get("health"),
        )


@dataclass
class RecoveryState:
    """Root recovery state structure."""
    version: str
    gateway_pid: int
    gateway_start_time: datetime
    last_updated: datetime
    sessions: Dict[str, SessionState] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "version": self.version,
            "gateway_pid": self.gateway_pid,
            "gateway_start_time": self.gateway_start_time.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "sessions": {k: v.to_dict() for k, v in self.sessions.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "RecoveryState":
        sessions = {
            k: SessionState.from_dict(v) for k, v in data.get("sessions", {}).items()
        }
        return cls(
            version=data["version"],
            gateway_pid=data["gateway_pid"],
            gateway_start_time=datetime.fromisoformat(data["gateway_start_time"]),
            last_updated=datetime.fromisoformat(data["last_updated"]),
            sessions=sessions,
        )


@dataclass
class InterruptedSession:
    """Information about an interrupted session."""
    session_key: str
    channel: str
    chat_id: str
    turn_id: Optional[str]
    duration_seconds: float
    last_heartbeat: datetime
