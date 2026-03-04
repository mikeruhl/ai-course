# Module 20: Azure AI Foundry Agent Service

## Overview

Azure AI Foundry Agent Service is Microsoft's managed platform for building,
deploying, and operating AI agents. Instead of writing your own agent loop
(tool dispatch, conversation state, error handling), the service provides
server-side primitives: **agents**, **threads**, and **runs**.

The mental model: you define an agent (instructions + tools + model), create
a thread (persistent conversation), and submit a run (one execution of the
agent against the thread). The service handles the tool-calling loop, state
persistence, and streaming — you just read the results.

By the end of this module you will understand when to use a managed agent
service vs building from scratch, how the thread/run model works, and how
to orchestrate multiple managed agents.

---

## Concepts

### 1. Why Managed Agent Services Exist

Building a production agent from scratch requires solving the same problems
every time:

```
Raw agent loop (you own all of this):
  ┌────────────────────────────────────┐
  │ 1. Send messages to LLM            │
  │ 2. Parse tool_calls from response   │
  │ 3. Execute tools                    │
  │ 4. Append tool results              │
  │ 5. Loop until finish_reason="stop"  │
  │ 6. Handle errors, retries, timeouts │
  │ 7. Persist conversation state       │
  │ 8. Manage file uploads/retrieval    │
  └────────────────────────────────────┘

Managed agent service (you own instructions + tools):
  ┌────────────────────────────────────┐
  │ 1. Create agent (instructions,     │
  │    model, tools)                   │
  │ 2. Create thread                   │
  │ 3. Add message                     │
  │ 4. Create run → service handles    │
  │    the entire loop                 │
  │ 5. Read result                     │
  └────────────────────────────────────┘
```

The tradeoff is control vs operational burden. A managed service handles
retries, state persistence, file storage, and code execution — but you lose
fine-grained control over the agent loop.

### 2. Core Primitives

#### Agents

An agent definition consists of:
- **Instructions**: the system prompt
- **Model**: which deployment to use (e.g., gpt-4o-mini)
- **Tools**: function definitions, code interpreter, file search
- **Metadata**: key-value pairs for your own tracking

Agents are reusable — one agent definition can serve many threads.

#### Threads

A thread is a persistent conversation. It stores the full message history
server-side, so you don't need to resend the entire context on each request.

```
Thread "thread_abc123"
  ├── message 1: user "Analyze this CSV file"
  ├── message 2: assistant "I'll use code interpreter to analyze..."
  ├── message 3: assistant [code_interpreter output]
  └── message 4: assistant "Here are the key findings..."
```

Threads persist across sessions. You can return to a thread days later
and the agent retains full context.

#### Runs

A run is one execution of an agent against a thread. When you create a run:
1. The service reads the thread's messages
2. Sends them to the model with the agent's instructions and tools
3. Executes the full tool-calling loop
4. Appends all generated messages to the thread
5. Returns the final status (completed, failed, requires_action)

### 3. Tool Integration

AI Foundry supports several tool types:

**Code Interpreter** — executes Python code in a sandboxed environment.
The agent can write and run code to analyze data, generate charts, or
perform calculations. Files uploaded to the thread are accessible.

**File Search** — vector search over uploaded files. The service handles
chunking, embedding, and indexing. Useful for RAG over user-uploaded
documents without building your own pipeline.

**Function Calling** — same as raw function calling, but the service
manages the loop. When the agent calls a function, the run enters
`requires_action` status. You execute the function locally and submit
the result, then the run continues.

**Azure Functions** — connect serverless functions as tools. The agent
can invoke HTTP-triggered Azure Functions directly.

**OpenAPI** — expose any REST API as a tool by providing its OpenAPI spec.

### 4. Multi-Agent Orchestration

AI Foundry supports multi-agent patterns through several mechanisms:

**Sequential handoff**: One agent completes its work, then a different
agent takes over the same thread with different instructions and tools.

```
Thread "support-case-42"
  → Run with "Triage Agent" (classifies the issue)
  → Run with "Technical Agent" (solves the issue)
  → Run with "QA Agent" (verifies the solution)
```

**Parallel fan-out**: Create multiple threads from the same user input,
run different agents in parallel, then aggregate results.

**Orchestrator pattern**: A router agent decides which specialist agent
to invoke, passes the task, and synthesizes the specialist's response.

### 5. When to Use AI Foundry vs Rolling Your Own

| Factor | AI Foundry | Custom Agent Loop |
|---|---|---|
| Time to prototype | Fast — no loop code needed | Slower — build from scratch |
| Code interpreter | Built-in, sandboxed | Must implement yourself |
| File search / RAG | Built-in | Build your own pipeline |
| State persistence | Managed (threads) | You manage (database, files) |
| Fine-grained control | Limited | Full control |
| Custom tool execution | Requires round-trip | In-process |
| Cost | Service charges + token costs | Token costs only |
| Vendor lock-in | High (Azure-specific) | Low |
| Latency | Higher (network round-trips) | Lower (in-process) |

**Use AI Foundry when**: you need code interpreter, file search, or rapid
prototyping and don't need sub-second tool execution.

**Use custom loops when**: you need full control over the agent loop,
minimal latency, or want to avoid vendor lock-in.

### 6. Monitoring and Evaluation

AI Foundry provides built-in telemetry:
- **Run metrics**: token usage, step count, duration per run
- **Tool usage**: which tools were called, success/failure rates
- **Thread analytics**: conversation length, resolution rates
- **Azure Monitor integration**: export metrics to Log Analytics

For evaluation, AI Foundry integrates with Azure AI Evaluation SDK to
measure quality metrics like groundedness, relevance, and coherence.

---

## Lab

### Setup
```bash
cp lab/.env.example lab/.env
# Fill in your Azure OpenAI credentials
cd lab && uv sync
```

### Tasks

| Task | Command | What you'll build |
|---|---|---|
| A | `uv run foundry --task A` | Agent with tools (calculator, search, date) |
| B | `uv run foundry --task B` | Thread lifecycle — multi-turn conversation with context retention |
| C | `uv run foundry --task C` | Multi-agent handoff — orchestrator routes to specialist agents |

### Task A: Agent Creation + Tool Calling

Create an agent with three tools (calculator, document search, date lookup)
and run it against several queries. Observe how the agent decides which
tools to call and how it combines tool results.

### Task B: Thread Management

Create a persistent thread and hold a multi-turn conversation. Verify that
the agent retains context from earlier messages (e.g., remembers your name).
This demonstrates the thread-as-state pattern.

### Task C: Multi-Agent Handoff

Build an orchestrator that routes requests to specialist agents (code reviewer,
security analyst, architecture advisor). The orchestrator uses a routing tool
to decide which specialist handles each request.

---

## Key Takeaways

1. AI Foundry abstracts the agent loop into server-side primitives (agents,
   threads, runs) — you define behavior, the service handles execution.
2. Built-in tools (code interpreter, file search) eliminate common
   infrastructure work but introduce vendor lock-in.
3. Multi-agent orchestration works through thread sharing and sequential/parallel
   runs — the same patterns you'd build manually, but with managed state.
4. The decision between managed and custom depends on your latency requirements,
   control needs, and willingness to accept vendor coupling.

---

## Further Reading

- Azure AI Foundry documentation
- OpenAI Assistants API (the pattern AI Foundry extends)
- Semantic Kernel Agent Framework (Module 17) for an alternative approach
