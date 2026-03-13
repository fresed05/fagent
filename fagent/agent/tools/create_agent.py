"""Create agent tool for A2A protocol."""

from typing import TYPE_CHECKING, Any

from fagent.agent.tools.base import Tool
from fagent.config.schema import AgentConfig

if TYPE_CHECKING:
    from fagent.agent.registry import AgentRegistry


class CreateAgentTool(Tool):
    """Tool to create a new agent dynamically."""

    def __init__(self, registry: "AgentRegistry"):
        self._registry = registry

    @property
    def name(self) -> str:
        return "create_agent"

    @property
    def description(self) -> str:
        return (
            "Create a new agent with specific configuration. "
            "Use this to spawn specialized agents for different tasks. "
            "The agent will be registered and can receive messages."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the agent (e.g., 'researcher', 'coder', 'analyst')",
                },
                "model": {
                    "type": "string",
                    "description": "Model to use (e.g., 'anthropic/claude-sonnet-4', 'openai/gpt-4')",
                },
                "temperature": {
                    "type": "number",
                    "description": "Temperature for the model (0.0-1.0). Optional.",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Max tokens for responses. Optional.",
                },
                "disable_vector_memory": {
                    "type": "boolean",
                    "description": "Disable vector memory for this agent. Optional.",
                },
                "disable_shadow_context": {
                    "type": "boolean",
                    "description": "Disable shadow context for this agent. Optional.",
                },
            },
            "required": ["name", "model"],
        }

    async def execute(
        self,
        name: str,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        disable_vector_memory: bool = False,
        disable_shadow_context: bool = False,
        **kwargs: Any,
    ) -> str:
        """Create a new agent."""
        config = AgentConfig(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            disable_vector_memory=disable_vector_memory,
            disable_shadow_context=disable_shadow_context,
        )

        agent_id = self._registry.register_agent(name, model, config)
        return f"Agent '{name}' created successfully (ID: {agent_id}). You can now send messages to this agent."
