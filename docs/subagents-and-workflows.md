# Subagents and Workflows

[Русская версия](./subagents-and-workflows.ru.md)

`fagent` has two runtime patterns for delegated or operational work:

- subagents for bounded background tasks
- workflow execution for ordered tool chains

They solve different problems but share the same goal: reduce waste in the main agent loop.

## Subagents

The subagent path is implemented through `SubagentManager` in `fagent/agent/subagent.py`.

## What a subagent does

A subagent can:

- take a focused task
- run in the background
- use a bounded tool set
- produce a final result
- send a brief result back into the main thread through the message bus

## Subagent lifecycle

At a high level:

1. The main runtime spawns a subagent task.
2. The subagent gets its own prompt and limited tool registry.
3. It runs its own local tool loop for a bounded number of iterations.
4. It completes or fails.
5. The result is summarized back into the main conversation.

## Why subagents matter

They help when:

- the work is parallelizable
- a bounded background task should not block the main exchange
- the main model should not carry all low-level intermediate details

## Workflows

The workflow path is implemented by the `run_workflow` tool in `fagent/agent/tools/workflow.py`.

## What `run_workflow` does

It executes ordered tool steps with:

- explicit `allowed_tools`
- step normalization
- argument inference
- optional lighter-model help
- repair attempts
- escalation control

This is not the same as a subagent. A workflow is a tightly controlled execution lane for tool sequences.

## Workflow execution loop

At a high level:

1. A workflow goal and steps are provided inline or loaded from a workflow file.
2. Each step is normalized.
3. The tool is checked against `allowed_tools`.
4. The step runs.
5. On failure, the tool can try heuristic repair or ask the lighter helper model.
6. The result either completes, retries, escalates, or fails fast.

## Why `workflowLight` matters

Many tool failures do not require the strongest model. `fagent` supports a separate model role for cheaper or faster workflow repair.

That means the main model does not need to spend expensive tokens on:

- interpreting rough workflow syntax
- fixing a malformed step
- recovering from local tool mismatch
- re-planning every operational micro-failure

## Workflow repair and experience memory

Workflow repair can emit telemetry into experience memory. Repeated recoveries can become durable operational knowledge.

## When to use which

Use a subagent when:

- the work is backgroundable
- the task is a bounded mini-mission
- the main thread only needs the end result

Use `run_workflow` when:

- the work is a controlled tool chain
- order matters
- repair and escalation policy should be explicit
- you want the runtime, not the main model, to own step execution

## Related docs

- Previous: [Graph memory and Graph UI](./graph-memory-and-gui.md)
- Next: [Providers and model roles](./providers-and-model-roles.md)
- Also see: [CLI and observability](./cli-and-observability.md)
