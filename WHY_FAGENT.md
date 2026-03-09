# Why fagent

This note explains where `fagent` is stronger than broader agent stacks such as [OpenClaw](https://github.com/openclaw/openclaw), how the memory system works, and why the built-in sequential workflow tool is useful in production.

## The short version

`fagent` wins when you want an agent that is easy to inspect, easy to configure, and strong at continuity across real work sessions.

That is a different optimization target from OpenClaw. OpenClaw presents itself as a broader ecosystem with apps for desktop, mobile, and web plus a large extension surface and multiple deployment targets. That is powerful, but it also means more moving parts, more product surface, and a heavier mental model for people who mainly want an agent runtime they can run, extend, and debug directly.

`fagent` is the opposite bet: fewer layers, tighter scope, and better operational clarity.

## Where fagent wins over OpenClaw and similar platforms

These are targeted advantages, not universal claims. OpenClaw is broader; `fagent` is tighter.

### 1. Smaller operational surface

`fagent` is centered on:

- one Python package
- one workspace
- one config tree under `~/.fagent`
- one CLI for bootstrap, direct chat, gateway mode, auth, channels, and memory tooling

That makes common work easier:

- onboarding is faster
- config drift is easier to see
- debugging is more local and less distributed
- extending the runtime is easier for a small team

By contrast, OpenClaw publicly emphasizes a much larger platform shape: cross-platform apps, extension bundles, remote auth helpers, and broader app/distribution surfaces. That is great for ecosystem reach, but `fagent` wins on simplicity.

### 2. Better fit for engineers who want to read the runtime

`fagent` is opinionated in a useful way:

- the main agent loop is readable
- tools are plain registered runtime objects
- memory is implemented as explicit layers, not an opaque black box
- config is fully materialized by `fagent onboard`

That matters when you need to answer questions like:

- why did the agent recall this?
- where did this memory come from?
- which model was used for shadow, embeddings, or workflow repair?
- why did a workflow step retry or escalate?

### 3. Stronger continuity for long-running work

Many agents can chat. Fewer agents stay coherent over repeated project work without forcing you to manually re-explain everything.

`fagent` pushes continuity through:

- file memory for durable human-readable notes
- vector memory for semantic retrieval
- graph memory for relationships and entities
- workflow snapshots for active problem solving state
- task graph state for goals, blockers, and decisions
- experience memory for repeated operational patterns and recoveries
- shadow-context compression before the main model call
- session auto-summarization for long threads

This gives `fagent` a practical advantage over agents that rely mostly on the current conversation window plus ad hoc summaries.

### 4. Better cost discipline during tool-heavy runs

`fagent` includes a built-in `run_workflow` tool that can execute ordered tool steps and use a smaller helper model for interpretation or recovery.

That means the main model does not need to:

- re-plan every tiny step
- burn expensive tokens on local tool repair
- repeatedly reason over the same operational error surface

The result is often lower latency, lower cost, and less noise in the main conversation.

## How the memory system works

`fagent` memory is layered, not monolithic.

### Layer 1: file memory

The file store writes human-readable artifacts into the workspace:

- `memory/HISTORY.md`
- `memory/MEMORY.md`
- `memory/daily/YYYY-MM-DD.md`

This is the most transparent layer. You can open it, inspect it, version it, and understand what was retained.

Why this matters:

- easy manual inspection
- good auditability
- robust fallback even if embeddings or graph retrieval fail

### Layer 2: vector memory

Artifacts and episodes are embedded into the vector backend for semantic recall.

This helps with:

- fuzzy retrieval
- recalling similar prior work even when the exact wording changed
- surfacing relevant prior attempts, not just exact string matches

Why it wins:

- more resilient than keyword-only history lookup
- useful for messy real-world phrasing
- supports retrieval beyond the current chat wording

### Layer 3: graph memory

`fagent` records graph-oriented memory for entities, relationships, and evolving structure. It can run locally or against Neo4j.

This is important when the user asks things like:

- how are these two pieces connected?
- what decision affected this blocker?
- which entity relates to this workflow?

Why it wins:

- relationship recall is not treated like plain text search
- entity-level continuity becomes possible
- decisions, blockers, and connected facts can be traversed more naturally

### Layer 4: workflow snapshots

During work, `fagent` can store workflow snapshots that capture:

- current state
- open blockers
- next step
- citations
- tools used

This is a major practical win because operational continuity is often not about facts; it is about current execution state.

Why it wins:

- easier resume-after-interruption behavior
- better recovery from partially completed tasks
- clearer continuity during debugging, migrations, or repair work

### Layer 5: task graph state

The memory registry stores task nodes and task edges for goals, steps, decisions, and blockers.

Why it wins:

- the agent can recall what is in progress, blocked, or decided
- continuity becomes task-aware, not just chat-aware
- project state can outlive a single conversation window

### Layer 6: experience memory

When operational patterns repeat, `fagent` records experience patterns such as:

- what failed
- what recovery worked
- how often that pattern was observed

This is especially valuable for recurring runtime issues and repair loops.

Why it wins:

- repeated failures become reusable knowledge
- the agent stops rediscovering the same fix from scratch
- recoveries can be ranked by evidence count, not only by recency

### Layer 7: shadow context

Before the main model runs, `fagent` can retrieve memory from file, vector, and graph layers and compress it using a lighter model into a compact shadow brief.

This shadow brief includes:

- summary
- facts
- open questions
- citations
- confidence
- contradictions
- store breakdown

Why it wins:

- the main model receives a compressed working brief instead of raw memory clutter
- token usage is more controlled
- contradictions can be surfaced before they poison the main answer
- low-confidence retrieval can be explicitly marked as weak

### Layer 8: query-aware routing

`fagent` does not hit every store in the same way for every question.

The memory router classifies requests into intents such as:

- temporal recall
- workflow recall
- relationship recall
- factual recall
- preference recall
- continuity
- broad synthesis

That classification changes:

- which stores are queried first
- which artifact types are preferred
- whether raw session evidence is allowed to escalate
- how many items should be retrieved

Why it wins:

- fewer irrelevant recalls
- better retrieval quality per query type
- less wasted context

## Why this memory design beats simpler agent memory

The main advantage is composability.

Simple agents usually have one or two memory tactics:

- chat history only
- chat history plus embeddings
- periodic summarization only

`fagent` combines multiple memory forms that each solve a different failure mode:

- file memory handles transparency
- vector memory handles semantic fuzziness
- graph memory handles relationships
- workflow memory handles in-progress execution
- experience memory handles repeated operational lessons
- shadow context handles compression
- routing handles relevance

This is why `fagent` can outperform more general agents in continuity-heavy engineering and operator workflows.

## The built-in sequential workflow tool

`fagent` includes a dedicated `run_workflow` tool for ordered tool execution.

It accepts:

- a goal
- ordered steps
- explicit `allowed_tools`
- an LLM assist mode
- an escalation policy

It can:

- normalize rough step syntax
- infer positional arguments
- run steps in order
- detect blocked or invalid steps
- retry with repaired steps
- ask a lighter helper model for recovery guidance
- escalate back to the main agent only when needed

## Why the workflow tool is a real advantage

### 1. It separates orchestration from big-model reasoning

The main model can decide what should happen. The workflow tool handles how a small multi-step tool chain is executed.

This reduces waste and keeps the main agent focused on higher-value reasoning.

### 2. It uses a smaller helper model where that makes sense

`workflow_light` is a separate model role. That lets you assign a cheaper/faster model for:

- ambiguous step interpretation
- recovery suggestions
- repair after tool errors

This is often the right tradeoff because many workflow failures do not require the strongest model.

### 3. It turns repeated tool errors into memory

When workflow repair happens, the tool can emit recovery telemetry into experience memory.

That means:

- failures become durable lessons
- the agent can recognize repeated patterns
- future recalls can surface a known recovery path

### 4. It keeps escalation explicit

The workflow tool can either fail fast or return control to the main agent.

This is better than silent, uncontrolled retry loops because you can tune:

- when local repair is allowed
- when the main agent should step in
- which tools are allowed at all

## Practical pluses for teams

`fagent` is especially strong when you care about:

- local-first debuggability
- predictable configuration
- recoverable long-running work
- cost control in tool-heavy flows
- transparent memory you can inspect on disk
- a clean path to adding new tools, channels, and model roles

## Source context for the comparison

The OpenClaw side of this comparison is based on its official public materials:

- [OpenClaw GitHub repository](https://github.com/openclaw/openclaw)
- [OpenClaw documentation site](https://docs.openclaw.ai)

The conclusion is not that `fagent` is universally better. The conclusion is that `fagent` is better optimized for engineers and operators who want a focused runtime with strong continuity, layered memory, and lower operational complexity.
