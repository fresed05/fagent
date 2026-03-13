# Agent Management Skill

## Overview

This skill enables multi-agent orchestration using the A2A (Agent-to-Agent) protocol. Create, configure, and coordinate multiple specialized agents for complex tasks.

## Trigger Phrases

- "create an agent"
- "spawn a new agent"
- "set up multi-agent system"
- "coordinate multiple agents"
- "agent-to-agent communication"

## Core Concepts

### A2A Protocol

The Agent-to-Agent protocol enables:
- Dynamic agent creation with custom configurations
- Inter-agent communication via message bus
- Specialized agents for different tasks
- Parallel task execution

### Agent Types

**Main Agent**: The primary orchestrator
**Subagents**: Background task executors (limited tools, auto-cleanup)
**Named Agents**: Persistent agents with full configuration

## Tools

### create_agent

Create a new persistent agent with custom configuration.

```python
create_agent(
    name="researcher",
    model="anthropic/claude-sonnet-4",
    temperature=0.7,
    disable_vector_memory=False
)
```

### send_to_agent

Send messages to other agents.

```python
send_to_agent(
    agent_id="abc123",
    message="Analyze this data and report findings"
)
```

### list_agents

List all registered agents and their status.

### spawn

Create temporary subagent for background tasks.

```python
spawn(
    task="Research topic X and summarize",
    label="Research Task",
    model="anthropic/claude-haiku-4"  # Optional model override
)
```

## Configuration

### Agent Config (config.toml)

```toml
[agents.defaults]
model = "anthropic/claude-opus-4-5"
temperature = 0.1
max_tokens = 8192

[agents.agents.researcher]
model = "anthropic/claude-sonnet-4"
temperature = 0.7
disable_vector_memory = true

[agents.agents.coder]
model = "anthropic/claude-opus-4-5"
temperature = 0.1
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

## Patterns

### Sequential Delegation

```
1. Main agent receives complex task
2. Creates specialized agents (researcher, analyst, writer)
3. Delegates subtasks sequentially
4. Aggregates results
```

### Parallel Execution

```
1. Identify independent subtasks
2. Spawn multiple subagents with different models
3. Execute in parallel
4. Collect and synthesize results
```

### Hierarchical Coordination

```
Main Agent (Orchestrator)
├── Research Agent (gather data)
├── Analysis Agent (process data)
└── Report Agent (generate output)
```

## Best Practices

1. **Model Selection**: Use faster/cheaper models for simple tasks
2. **Memory Management**: Disable vector memory for stateless agents
3. **Task Boundaries**: Keep agent tasks focused and well-defined
4. **Error Handling**: Monitor agent status and handle failures
5. **Resource Limits**: Limit concurrent agents to avoid overload

## Examples

### Example 1: Research Team

```
Main: "Create a research team to analyze market trends"

1. create_agent(name="data_collector", model="haiku")
2. create_agent(name="analyst", model="sonnet")
3. send_to_agent(data_collector, "Gather market data for Q1 2026")
4. Wait for response
5. send_to_agent(analyst, "Analyze this data: {data}")
6. Synthesize final report
```

### Example 2: Code Review System

```
1. spawn(task="Run tests", model="haiku")
2. spawn(task="Check security", model="sonnet")
3. spawn(task="Review architecture", model="opus")
4. Aggregate feedback from all subagents
```

## Limitations

- Agents share the same workspace
- No cross-workspace communication
- Message bus is in-memory (not persistent)
- Subagents have limited tool access

## Related Skills

- `subagents-and-workflows`: Background task execution
- `cron`: Scheduled agent tasks
- `workflow`: Sequential tool chains
