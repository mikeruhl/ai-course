# Module 23: Durable Execution

## Overview

Agents fail. Networks drop, processes crash, VMs restart, deployments roll.
If your agent is mid-task when this happens, what state is it in? Can you
resume, or do you start over? Did that partially-executed tool call actually
complete?

Durable execution solves this: agent state is persisted at each step so that
after any failure, execution resumes from the last checkpoint rather than
starting from scratch. This is essential for agents that run long tasks
(minutes to hours) or perform multi-step workflows with side effects.

By the end of this module you will have implemented event sourcing,
checkpoint-resume, and the saga pattern for agent workflows.

---

## Concepts

### 1. Why Agents Need Durable Execution

A typical agent task — "research this topic, write a report, email it to
the team" — takes 5-10 minutes and involves 10+ LLM calls and several tool
invocations. Any of these can fail:

```
Step 1: Search web (3 queries)      ← 2 min
Step 2: Summarize findings          ← 1 min
Step 3: Generate report             ← 2 min
Step 4: Review and revise           ← 2 min
Step 5: Email report                ← 30s
       ↑
       Process crashes here.
       Without durability: start over (7+ min wasted, tokens re-spent).
       With durability: resume from step 5 (30s to complete).
```

### 2. Event Sourcing

Instead of storing current state directly, store an append-only log of
every event (action) the agent takes. Current state is derived by replaying
the event log from the beginning.

```
Event Log:
  [0] message_added: {role: "user", content: "Research topic X"}
  [1] tool_executed: {tool: "web_search", args: {query: "topic X"}}
  [2] response_generated: {content: "Found 3 relevant papers..."}
  [3] tool_executed: {tool: "web_search", args: {query: "topic X details"}}
  [4] response_generated: {content: "Key findings are..."}

State (derived by replay):
  messages: [user msg, assistant msg, assistant msg]
  tool_results: {web_search: [...]}
  step_count: 4
```

Benefits:
- **Full audit trail**: every action is recorded with timestamp
- **Crash recovery**: replay log to reconstruct state
- **Debugging**: replay to any point in history
- **Time travel**: rewind to step N and replay differently

The key constraint: event handlers must be **deterministic**. Given the same
events in the same order, replay must produce the same state.

### 3. Azure Durable Functions

Azure Durable Functions provide durable execution as a managed service.
You write **orchestrator functions** (the workflow) and **activity functions**
(individual steps). The framework handles checkpointing, replay, and
failure recovery.

```python
# Orchestrator — defines the workflow
async def research_orchestrator(ctx: DurableOrchestrationContext):
    results = await ctx.call_activity("search_web", "topic X")
    summary = await ctx.call_activity("summarize", results)
    report = await ctx.call_activity("generate_report", summary)
    await ctx.call_activity("send_email", report)
    return report

# Activity — individual step (normal async function)
async def search_web(query: str):
    # actual web search logic
    return results
```

The orchestrator replays from the beginning on every wake-up, but
`call_activity` returns cached results for completed activities instead
of re-executing them. This is the **replay pattern**.

#### Key Patterns

**Fan-out / Fan-in**: run multiple activities in parallel, wait for all.

```python
tasks = [ctx.call_activity("analyze", doc) for doc in documents]
results = await asyncio.gather(*tasks)
summary = await ctx.call_activity("merge", results)
```

**Human Interaction**: pause the orchestrator until a human approves.

```python
approval = await ctx.wait_for_external_event("approval")
if approval == "approved":
    await ctx.call_activity("execute_action")
```

**Sub-orchestrations**: compose orchestrators hierarchically.

### 4. Temporal.io

Temporal is an open-source alternative to Durable Functions. Same concept
(workflows + activities), different execution model.

| Feature | Durable Functions | Temporal |
|---|---|---|
| Hosting | Azure Functions | Self-hosted or Temporal Cloud |
| Languages | C#, Python, JS, Java | Go, Java, Python, TypeScript |
| State backend | Azure Storage | PostgreSQL, MySQL, Cassandra |
| Replay model | Orchestrator replays | Workflow replays |
| Signals | External events | Signals + queries |
| Versioning | Task hub isolation | Workflow versioning |
| Vendor lock-in | Azure | None (open source) |

### 5. Checkpointing Strategies

Checkpoint frequency is a tradeoff between durability and performance:

| Strategy | Durability | Overhead |
|---|---|---|
| After every LLM call | High | High (many writes) |
| After every tool execution | Medium-High | Medium |
| After every agent step | Medium | Low |
| Manual (developer chooses) | Variable | Lowest |

For most agents, checkpointing after each **step** (one iteration of the
agent loop) is the right balance. Each checkpoint should capture:
- All messages in the conversation
- Results from completed tool calls
- Current step number
- Any accumulated state (summaries, extracted data)

### 6. Saga Pattern

When an agent performs a multi-step workflow with side effects, a failure
at step N may require undoing steps 1 through N-1. The saga pattern defines
a **compensation** (undo action) for each step.

```
Forward execution:
  Step 1: Create user account     → Compensation: Delete user account
  Step 2: Provision workspace     → Compensation: Delete workspace
  Step 3: Send welcome email      → Compensation: Send cancellation email
  Step 4: Setup billing           → FAILS

Compensation (reverse order):
  Undo Step 3: Send cancellation email
  Undo Step 2: Delete workspace
  Undo Step 1: Delete user account
```

Sagas are essential when agent actions are **not idempotent** — you can't
just retry the whole workflow because earlier steps have already taken
effect (emails sent, records created, money charged).

### 7. When to Use Durable Execution

| Scenario | Recommendation |
|---|---|
| < 1 minute, no side effects | Simple retry is sufficient |
| 1-5 minutes, few side effects | Checkpoint-resume |
| > 5 minutes, multiple side effects | Full durable execution (Durable Functions / Temporal) |
| Multi-step with irreversible actions | Saga pattern |
| Needs human approval gates | Durable execution with external events |

---

## Lab

### Setup
```bash
cp lab/.env.example lab/.env
# Fill in your Azure OpenAI credentials
cd lab && uv sync
```

### Option B: Google Vertex AI

Use Vertex AI's OpenAI-compatible endpoint instead of Azure OpenAI for the
LLM calls. Azure-specific services still require Azure.

1. Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)
2. Authenticate:
   ```bash
   gcloud auth login
   gcloud auth application-default login
   ```
3. Enable the Vertex AI API:
   ```bash
   gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID
   ```
4. Set `LLM_PROVIDER=vertex` in your `.env` file and fill in `GCP_PROJECT_ID`.

### Tasks

| Task | Command | What you'll build |
|---|---|---|
| A | `uv run durable --task A` | Event-sourced agent with replay |
| B | `uv run durable --task B` | Checkpoint-resume with simulated crash |
| C | `uv run durable --task C` | Saga pattern with compensation |

### Task A: Event-Sourced Agent

**Goal:** Demonstrate that an agent's full state can be reconstructed from an append-only event log after a crash.

**What to do:**
1. Open `lab/src/durable_patterns.py` and read the `EventSourcedAgent` class (line ~70) and the `task_a` function (line ~118)
2. Trace how `append_event` records every action and `replay` reconstructs `messages`, `tool_results`, and `step_count` from the log
3. Run:
   ```bash
   cd lab && uv run durable --task A
   ```

**Expected result:**
- Two LLM responses about agent memory types and episodic memory
- Event log saved to `./checkpoints/event_log.json` with 6+ events
- A "SIMULATED CRASH" message followed by recovery output showing the recovered agent with the correct step count and message count
- An Event Log table listing each event by index, type (`message_added`, `tool_executed`, `response_generated`), and data preview

```
Step 1 response: Agent memory can be categorized into three main types...
Step 2 response: Episodic memory in agents refers to the storage of...

--- SIMULATED CRASH ---

Recovered agent: 3 steps, 4 messages
```

**Why this matters:**
Event sourcing gives you a full audit trail and crash recovery by replaying a deterministic log. In production, this is how systems like Temporal and Azure Durable Functions recover orchestrators — they replay the event history rather than persisting mutable state.

### Task B: Checkpoint-Resume

**Goal:** Show that a multi-step agent can save progress to disk and resume from the last completed step after a crash.

**What to do:**
1. Open `lab/src/durable_patterns.py` and read the `CheckpointAgent` class (line ~180) and `task_b` function (line ~230)
2. Follow the `run` method — note how it saves a `Checkpoint` (task_id, current_step, results, messages) to JSON after every step, and how `simulate_crash_at` halts execution early
3. Run:
   ```bash
   cd lab && uv run durable --task B
   ```

**Expected result:**
- Run 1 completes steps 1 and 2, then crashes at step 3
- Run 2 loads the checkpoint, reports "resuming from step 3", and completes steps 3 and 4
- A Final Results table showing all four step results

```
Run 1 — will crash at step 3:
  Step 1/4: What are the 3 main cloud providers for AI workloads?
  Result: The three main cloud providers are Azure, AWS, and Google Cloud...
  Step 2/4: Compare their managed LLM services.
  Result: Azure offers Azure OpenAI Service, AWS has Amazon Bedrock...
  Step 3/4: Which one has the best support for multi-agent systems?
  CRASH at step 3!

Run 2 — resuming from checkpoint:
Checkpoint found: True, resuming from step 3
  Step 3/4: Which one has the best support for multi-agent systems?
  Result: Azure currently has the strongest multi-agent support with...
  Step 4/4: Summarize your findings in a table format.
  Result: | Provider | LLM Service | Multi-Agent | ...
```

**Why this matters:**
Checkpointing is simpler than full event sourcing and sufficient for most agent workloads. The key design decision is checkpoint granularity — this lab checkpoints per step, which balances durability against write overhead. In production, serializing the full conversation to a blob or database after each tool call is the most common pattern.

### Task C: Saga Pattern

**Goal:** Demonstrate that when a multi-step workflow with side effects fails partway through, completed steps must be undone in reverse order.

**What to do:**
1. Open `lab/src/durable_patterns.py` and read the `SagaOrchestrator` class (line ~286) and `task_c` function (line ~327)
2. Examine the four `SagaStep` definitions — each has an `action` prompt and a `compensation` prompt. Note how `compensate` iterates `self.completed` in reverse
3. Run:
   ```bash
   cd lab && uv run durable --task C
   ```

**Expected result:**
- Steps 1-3 (create account, provision workspace, send welcome email) execute successfully
- Step 4 (setup billing) fails, triggering compensation
- Compensation runs in reverse: undo email, undo workspace, undo account
- A Saga Execution Summary table showing steps 1-3 as executed + compensated, step 4 as not executed

```
Executing: Create user account
  Done: User account for john@example.com has been created...
Executing: Provision workspace
  Done: Workspace 'johns-workspace' created with default settings...
Executing: Send welcome email
  Done: Welcome email sent to john@example.com...
Executing: Setup billing
  FAILURE at 'Setup billing' — triggering compensation

Compensating 3 steps in reverse...
  Compensated 'Send welcome email': Cancellation email sent...
  Compensated 'Provision workspace': Workspace deleted...
  Compensated 'Create user account': User account deleted...

Saga completed: False
```

**Why this matters:**
Agent actions often have real-world side effects (sending emails, creating resources, charging payment methods). Unlike a database transaction, you cannot roll back an already-sent email. The saga pattern makes compensating actions explicit and ensures they run in the correct reverse order. Any production agent that performs multi-step mutations needs this pattern or something equivalent.

### Terraform (Azure Functions + Storage)

If you want to deploy Durable Functions:
```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
terraform init && terraform apply
```

This provisions: Resource Group, Storage Account, App Service Plan
(consumption), Function App, and Application Insights.

---

## Key Takeaways

1. Agent tasks that take more than a minute need some form of state
   persistence — crashes are not a matter of if, but when.
2. Event sourcing provides the strongest guarantees (full audit trail,
   replay, time travel) but requires deterministic event handlers.
3. Checkpointing is simpler to implement and sufficient for most agents.
4. The saga pattern is mandatory when agent actions have side effects
   that must be undone on failure.
5. Azure Durable Functions and Temporal provide managed durable execution —
   use them for production workloads instead of building your own.

---

## Further Reading

- Azure Durable Functions documentation
- Temporal.io documentation
- Martin Fowler: Event Sourcing
- Chris Richardson: Saga Pattern (microservices.io)
