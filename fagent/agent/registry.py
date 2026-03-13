"""Agent registry for managing multiple agents."""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from fagent.agent.tools.registry import ToolRegistry
from fagent.bus.events import InboundMessage
from fagent.bus.queue import MessageBus
from fagent.config.schema import AgentConfig
from fagent.providers.base import LLMProvider


@dataclass
class AgentInfo:
    """Information about a registered agent."""

    agent_id: str
    name: str
    model: str
    config: AgentConfig
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "idle"  # idle, running, stopped
    task_count: int = 0


class AgentRegistry:
    """Registry for managing multiple agents."""

    def __init__(self, bus: MessageBus, workspace: Path):
        self.bus = bus
        self.workspace = workspace
        self._agents: dict[str, AgentInfo] = {}
        self._agent_tasks: dict[str, asyncio.Task] = {}

    def register_agent(
        self,
        name: str,
        model: str,
        config: AgentConfig,
    ) -> str:
        """Register a new agent."""
        agent_id = str(uuid.uuid4())[:8]
        agent_info = AgentInfo(
            agent_id=agent_id,
            name=name,
            model=model,
            config=config,
        )
        self._agents[agent_id] = agent_info
        logger.info("Registered agent [{}]: {}", agent_id, name)
        return agent_id

    def get_agent(self, agent_id: str) -> AgentInfo | None:
        """Get agent info by ID."""
        return self._agents.get(agent_id)

    def list_agents(self) -> list[AgentInfo]:
        """List all registered agents."""
        return list(self._agents.values())

    def remove_agent(self, agent_id: str) -> bool:
        """Remove an agent from registry."""
        if agent_id in self._agents:
            # Cancel running task if exists
            if agent_id in self._agent_tasks:
                self._agent_tasks[agent_id].cancel()
                del self._agent_tasks[agent_id]
            del self._agents[agent_id]
            logger.info("Removed agent [{}]", agent_id)
            return True
        return False

    async def send_message_to_agent(
        self,
        agent_id: str,
        content: str,
        sender_id: str = "system",
    ) -> bool:
        """Send a message to a specific agent."""
        agent = self.get_agent(agent_id)
        if not agent:
            return False

        msg = InboundMessage(
            channel="agent",
            sender_id=sender_id,
            chat_id=agent_id,
            content=content,
        )
        await self.bus.publish_inbound(msg)
        return True
