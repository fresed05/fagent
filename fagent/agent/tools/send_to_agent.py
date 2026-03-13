"""Send message to agent tool for A2A protocol."""

from typing import TYPE_CHECKING, Any

from fagent.agent.tools.base import Tool

if TYPE_CHECKING:
    from fagent.agent.registry import AgentRegistry


class SendToAgentTool(Tool):
    """Tool to send messages to other agents."""

    def __init__(self, registry: "AgentRegistry", sender_id: str = "main"):
        self._registry = registry
        self._sender_id = sender_id

    @property
    def name(self) -> str:
        return "send_to_agent"

    @property
    def description(self) -> str:
        return (
            "Send a message to another agent. "
            "Use this to communicate with agents you've created. "
            "The agent will receive the message and can respond."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "ID of the agent to send message to",
                },
                "message": {
                    "type": "string",
                    "description": "Message content to send",
                },
            },
            "required": ["agent_id", "message"],
        }

    async def execute(self, agent_id: str, message: str, **kwargs: Any) -> str:
        """Send message to an agent."""
        success = await self._registry.send_message_to_agent(
            agent_id=agent_id,
            content=message,
            sender_id=self._sender_id,
        )

        if success:
            return f"Message sent to agent {agent_id}"
        return f"Failed to send message: agent {agent_id} not found"
