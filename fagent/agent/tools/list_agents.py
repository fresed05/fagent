"""List agents tool for A2A protocol."""

from typing import TYPE_CHECKING, Any

from fagent.agent.tools.base import Tool

if TYPE_CHECKING:
    from fagent.agent.registry import AgentRegistry


class ListAgentsTool(Tool):
    """Tool to list all registered agents."""

    def __init__(self, registry: "AgentRegistry"):
        self._registry = registry

    @property
    def name(self) -> str:
        return "list_agents"

    @property
    def description(self) -> str:
        return "List all registered agents with their IDs, names, models, and status."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """List all agents."""
        agents = self._registry.list_agents()

        if not agents:
            return "No agents registered."

        lines = ["Registered agents:"]
        for agent in agents:
            lines.append(
                f"- {agent.name} (ID: {agent.agent_id}, Model: {agent.model}, "
                f"Status: {agent.status}, Tasks: {agent.task_count})"
            )

        return "\n".join(lines)
