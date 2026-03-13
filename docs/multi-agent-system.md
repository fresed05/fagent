# Multi-Agent System and A2A Protocol

[Русская версия](./multi-agent-system.ru.md)

`fagent` supports multi-agent orchestration through the A2A (Agent-to-Agent) protocol, enabling dynamic agent creation, inter-agent communication, and parallel task execution.

## Overview

The multi-agent system extends fagent's capabilities beyond single-agent and subagent patterns:

- **Subagents**: Temporary background workers with limited tools
- **Named Agents**: Persistent agents with full configuration
- **A2A Protocol**: Standardized agent-to-agent communication

## Agent Types

### Main Agent

The primary orchestrator that coordinates other agents.

### Subagents

Background task executors spawned with `spawn()`:

```python
spawn(
    task="Research topic X",
    label="Research",
    model="anthropic/claude-haiku-4"  # Optional model override
)
```

**Features:**
- Limited tool access (no spawn, no message)
- Auto-cleanup after completion
- Model selection per subagent

### Named Agents

Persistent agents created with `create_agent()`:

```python
create_agent(
    name="researcher",
    model="anthropic/claude-sonnet-4",
    temperature=0.7,
    disable_vector_memory=True
)
```

## A2A Protocol Tools

### create_agent

Create a new persistent agent with custom configuration.

**Parameters:**
- `name`: Agent identifier
- `model`: Model to use
- `temperature`: Optional temperature override
- `max_tokens`: Optional token limit
- `disable_vector_memory`: Disable vector memory
- `disable_shadow_context`: Disable shadow context

### send_to_agent

Send messages to other agents via message bus.

**Parameters:**
- `agent_id`: Target agent ID
- `message`: Message content

### list_agents

List all registered agents with their status.

## Configuration

### Per-Agent Config

```toml
[agents.defaults]
model = "anthropic/claude-opus-4-5"
temperature = 0.1

[agents.agents.researcher]
model = "anthropic/claude-sonnet-4"
temperature = 0.7
disable_vector_memory = true
disable_shadow_context = false

[agents.agents.coder]
model = "anthropic/claude-opus-4-5"
max_tokens = 16384
```

### CLI Commands

```bash
# Create agent
fagent agent create researcher --model anthropic/claude-sonnet-4

# List agents
fagent agent list

# Show config
fagent agent config researcher

# Delete agent
fagent agent delete researcher
```

## Orchestration Patterns

### Sequential Delegation

```
1. Main agent receives complex task
2. Creates specialized agents
3. Delegates subtasks sequentially
4. Aggregates results
```

### Parallel Execution

```
1. Identify independent subtasks
2. Spawn multiple subagents
3. Execute in parallel
4. Collect results
```

### Hierarchical Coordination

```
Main Agent (Orchestrator)
├── Research Agent (data gathering)
├── Analysis Agent (data processing)
└── Report Agent (output generation)
```

## Implementation

### AgentRegistry

Manages agent lifecycle:

```python
from fagent.agent.registry import AgentRegistry

registry = AgentRegistry(bus=message_bus, workspace=workspace)
agent_id = registry.register_agent(name, model, config)
```

### Message Bus Integration

Agents communicate via `MessageBus`:

```python
await registry.send_message_to_agent(
    agent_id="abc123",
    content="Analyze this data",
    sender_id="main"
)
```

## Best Practices

1. **Model Selection**: Use faster models (haiku) for simple tasks
2. **Memory Management**: Disable unused memory systems for stateless agents
3. **Task Boundaries**: Keep agent tasks focused and well-defined
4. **Resource Limits**: Monitor concurrent agent count
5. **Error Handling**: Check agent status and handle failures

## Example: Research Team

```python
# Create specialized agents
create_agent(name="data_collector", model="haiku")
create_agent(name="analyst", model="sonnet")

# Delegate tasks
send_to_agent(data_collector, "Gather market data for Q1 2026")
# Wait for response
send_to_agent(analyst, "Analyze this data: {data}")

# Synthesize results
```

## Limitations

- Agents share the same workspace
- No cross-workspace communication
- Message bus is in-memory (not persistent)
- Subagents have limited tool access

## Related Documentation

- Previous: [Subagents and Workflows](./subagents-and-workflows.md)
- Next: [Providers and Model Roles](./providers-and-model-roles.md)
- See also: [CLI and Observability](./cli-and-observability.md)
