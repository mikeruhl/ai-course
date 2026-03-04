# Module 11: A2A Protocol

## Overview

Multi-agent systems built inside a single process are useful for learning, but
production systems have agents running as independent services — different
codebases, different languages, different teams. The A2A (Agent-to-Agent)
protocol defines a standard way for one agent service to call another, just as
REST standardized service-to-service HTTP calls.

This module builds an A2A server and client from scratch, implements streaming
via SSE, and demonstrates dynamic agent discovery. No SDKs — raw HTTP + JSON
so you understand exactly what's happening.

By the end: you have a working two-agent system where a planner agent calls a
researcher agent over the network using the A2A protocol.

---

## Concepts

### 1. What A2A Is and Why It Exists

A2A (Agent-to-Agent Protocol) is an open standard initially proposed by Google
in 2024 for agent interoperability. The core problem it solves:

Without a standard, calling Agent B from Agent A requires:
- Both teams to agree on a custom API shape
- Agent A to know Agent B's specific request/response schema
- Agent A to know how to handle errors, streaming, partial results
- Both to agree on authentication conventions

With A2A:
- Agent B publishes an Agent Card at a well-known URL
- Any A2A-compliant client can discover Agent B's capabilities
- Task submission, streaming, and error handling follow a shared protocol
- Agents can be swapped or upgraded without changing client code

A2A is to agent services what OpenAPI is to REST services: a common contract
that enables interoperability.

---

### 2. Key A2A Objects

#### Agent Card

A JSON document served at `/.well-known/agent.json`. Think of it as the agent's
API documentation, but machine-readable and standardized.

```json
{
  "name": "research-agent",
  "description": "Conducts deep research on technical topics using web search and knowledge synthesis.",
  "version": "1.0.0",
  "url": "https://research-agent.example.com",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false
  },
  "authentication": {
    "schemes": ["bearer"]
  },
  "skills": [
    {
      "id": "technical-research",
      "name": "Technical Research",
      "description": "Research technical topics, architectural patterns, and best practices.",
      "inputModes": ["text"],
      "outputModes": ["text", "data"]
    }
  ]
}
```

Key fields:
- `capabilities.streaming`: whether the agent supports SSE streaming
- `authentication.schemes`: how callers should authenticate
- `skills`: the specific capabilities, with input/output modes

#### Task

The unit of work in A2A. A Task has:
- `id`: unique identifier (UUID)
- `status`: one of `submitted`, `working`, `input-required`, `completed`, `failed`, `canceled`
- `messages`: the conversation — list of Message objects
- `artifacts`: structured outputs the agent produced
- `metadata`: optional key-value pairs

```json
{
  "id": "task-abc-123",
  "status": "completed",
  "messages": [
    {
      "role": "user",
      "parts": [{"type": "text", "text": "Research the CAP theorem"}]
    },
    {
      "role": "agent",
      "parts": [{"type": "text", "text": "The CAP theorem states..."}]
    }
  ],
  "artifacts": [
    {
      "name": "research-summary",
      "description": "Structured research findings",
      "parts": [{"type": "data", "data": {"key_concepts": [...], "references": [...]}}]
    }
  ]
}
```

#### Message

A single turn in the task conversation.

```json
{
  "role": "user",     // or "agent"
  "parts": [
    {"type": "text", "text": "Explain database indexing"},
    {"type": "file", "file": {"name": "schema.sql", "bytes": "<base64>"}},
    {"type": "data", "data": {"context": "PostgreSQL 16", "max_length": 500}}
  ]
}
```

Parts allow mixing text, files, and structured data in a single message.

#### Artifact

A structured output that persists beyond the conversation.

```json
{
  "name": "analysis-report",
  "description": "Detailed analysis with actionable recommendations",
  "index": 0,
  "lastChunk": true,
  "parts": [
    {"type": "data", "data": {"findings": [...], "risk_level": "medium"}}
  ]
}
```

Artifacts differ from message content: they represent the agent's deliverable,
not conversational text. Callers can extract artifacts independently of the
full message history.

---

### 3. A2A Protocol Flow

#### Non-Streaming (tasks/send)

```
Client                          A2A Server (Agent B)
  │                                    │
  │── GET /.well-known/agent.json ────►│
  │◄─ Agent Card ──────────────────────│
  │                                    │
  │── POST /tasks/send ───────────────►│
  │   {id, message}                    │
  │                                    │   ┌──────────────────┐
  │                                    │──►│  LLM + tools     │
  │                                    │   │  (may take 30s+) │
  │                                    │◄──┘                  │
  │◄─ Completed Task ──────────────────│
  │   {id, status: "completed",        │
  │    messages, artifacts}            │
```

The entire task completes synchronously from the client's perspective. Fine
for tasks under a few seconds.

#### Streaming (tasks/sendSubscribe)

```
Client                          A2A Server (Agent B)
  │                                    │
  │── POST /tasks/sendSubscribe ──────►│
  │                                    │
  │◄─ SSE stream ──────────────────────│
  │   event: task_status_update        │
  │   data: {status: "working"}        │
  │                                    │
  │◄─ SSE event ───────────────────────│
  │   event: task_artifact_update      │
  │   data: {artifact: {parts: [...]}} │
  │                                    │
  │◄─ SSE event ───────────────────────│
  │   event: task_status_update        │
  │   data: {status: "completed",      │
  │           final: true}             │
```

The client receives a stream of events as the agent works. Required for
tasks that take more than a few seconds or produce progressive output.

---

### 4. A2A vs. MCP: The Distinction

| Aspect | A2A | MCP |
|--------|-----|-----|
| Connects | Agent to Agent | Agent to Tool/Resource |
| Counterpart | Another autonomous LLM agent | A function, file, or data source |
| Autonomy | Both sides are autonomous reasoners | Server side is deterministic |
| Protocol | HTTP + JSON + SSE | JSON-RPC over stdio or HTTP |
| Analogy | Calling a contractor (another professional) | Calling an API or reading a database |

They are complementary. A typical architecture:

```
User
 │
 ▼
Orchestrator Agent
 ├── calls Specialist Agent A (via A2A) ──► Specialist Agent A
 │                                          ├── uses MCP server for file reads
 │                                          └── uses MCP server for web search
 └── calls Specialist Agent B (via A2A) ──► Specialist Agent B
                                            └── uses MCP server for database
```

Use A2A when the counterpart is an autonomous LLM-based agent that makes its
own decisions. Use MCP when the counterpart is a deterministic tool or data
source.

---

### 5. Dynamic Discovery

The power of Agent Cards is discovery without prior coordination:

```python
agent_registry = [
    "https://research-agent.internal/.well-known/agent.json",
    "https://code-agent.internal/.well-known/agent.json",
    "https://data-agent.internal/.well-known/agent.json",
]

# Orchestrator dynamically selects the best agent for a task
cards = [fetch_agent_card(url) for url in agent_registry]
best_agent = select_best_agent(cards, task_description)
result = send_task(best_agent["url"], task)
```

This is the A2A equivalent of service discovery. The orchestrator doesn't
need to know ahead of time which agents exist — it queries their cards and
decides at runtime.

---

## Lab Tasks

### Setup

```bash
cd modules/module-11-a2a-protocol/lab
cp .env.example .env
# Edit .env with your Azure OpenAI credentials
uv sync
```

For labs B-E, you'll run multiple processes (the server and the client).
Use separate terminal windows or run the server in the background.

---

### Lab 11A: Minimal A2A Server

**Goal:** Implement a working A2A server in FastAPI that satisfies the core protocol.

**Tasks:**

1. Implement `GET /.well-known/agent.json` that returns a valid Agent Card.
   The agent should be a "technical summarizer" that summarizes technical
   documents.

2. Implement `POST /tasks/send` that:
   - Accepts a Task object (with `id` and at least one `messages` entry)
   - Extracts the text from the first user message
   - Calls your Azure OpenAI deployment to process the task
   - Returns a completed Task with the response as an agent message and
     as an artifact named "summary"

3. Add proper error responses:
   - 400 if the task is malformed
   - 422 if no user message is present
   - 500 with `{"status": "failed", "error": {...}}` if the LLM call fails

4. Add request logging middleware that logs: task id, message length,
   processing time (ms), status.

Test manually with httpx in a Python script before building the client in Lab 11B.

**File:** `lab/src/a2a_server.py`

Run with: `uvicorn a2a_server:app --port 8001 --reload`

---

### Lab 11B: A2A Client

**Goal:** Build a client that uses the A2A protocol to call the server from Lab 11A.

**Tasks:**

1. Implement `fetch_agent_card(base_url: str) -> dict` — fetches and validates
   the Agent Card from `{base_url}/.well-known/agent.json`.

2. Implement `send_task(agent_url: str, user_message: str, task_id: str | None = None) -> dict` that:
   - Generates a UUID task id if not provided
   - POSTs to `/tasks/send` with the correct A2A task structure
   - Returns the completed Task dict

3. Implement `extract_artifact(task: dict, artifact_name: str) -> Any` — finds
   and returns a specific artifact from a completed task.

4. Build a demo script that:
   - Fetches the Agent Card from your Lab 11A server
   - Prints the agent's capabilities
   - Sends a task: "Summarize the key points of eventual consistency in
     distributed systems"
   - Prints the artifact contents

5. Add retry logic with exponential backoff (max 3 retries) for transient
   failures (5xx responses, timeouts).

**File:** `lab/src/a2a_client.py`

---

### Lab 11C: Streaming with SSE

**Goal:** Add streaming to the A2A server and consume it from the client.

**Tasks:**

1. Add `POST /tasks/sendSubscribe` to the server:
   - Accepts the same Task input as `/tasks/send`
   - Returns a `StreamingResponse` with `media_type="text/event-stream"`
   - Emits SSE events in this sequence:
     1. `task_status_update` with `status: "working"`
     2. For each LLM response chunk: `task_artifact_update` with the partial text
     3. `task_status_update` with `status: "completed", final: true`

2. Azure OpenAI streaming: use `"stream": true` in the chat completions request.
   Consume the SSE stream from Azure OpenAI and forward chunks to your client.

3. Update the client to handle streaming:
   - `send_task_streaming(agent_url, user_message)` — calls `/tasks/sendSubscribe`
   - Yields events as they arrive
   - Assembles the final artifact from all `task_artifact_update` events

4. Build a demo that streams a summarization task and prints each chunk as it
   arrives (like a ChatGPT-style streaming UI in the terminal using rich).

5. Measure and compare latency: time-to-first-token for streaming vs.
   total-time for non-streaming on the same task.

**File:** `lab/src/a2a_streaming.py` (extends `a2a_server.py`)

---

### Lab 11D: Two-Agent Delegation System

**Goal:** Build a planner agent that delegates research subtasks to a researcher agent via A2A.

System architecture:
```
User ──► Planner Agent (port 8001) ──► Researcher Agent (port 8002)
         - receives complex tasks       - handles research queries
         - breaks them into steps       - returns structured findings
         - assembles final answer
```

**Tasks:**

1. Implement the Researcher Agent (port 8002):
   - Agent Card skill: "research" with input text, output data artifact
   - Accepts research queries, uses the LLM to synthesize a detailed response
   - Returns an artifact with `{"findings": str, "confidence": float, "sources_consulted": list}`

2. Implement the Planner Agent (port 8001):
   - Receives a complex user task
   - Uses LLM to break it into 2-3 research questions
   - Calls the Researcher Agent via A2A for each question (use the client
     from Lab 11B)
   - Assembles the researcher's artifacts into a final synthesized response
   - Returns the final response as its own artifact

3. Add agent-to-agent authentication: include a shared secret in the
   `Authorization` header (Bearer token, hardcoded for now — real auth is
   Module 13). The Researcher Agent validates the token before processing.

4. Test with: "What are the trade-offs between PostgreSQL and MongoDB for
   a high-volume time-series workload, and which should we choose for a
   system ingesting 100k events/minute?"

**Files:** `lab/src/planner_agent.py`, `lab/src/researcher_agent.py`

---

### Lab 11E: Dynamic Discovery

**Goal:** Orchestrator selects the best agent for a task by reading Agent Cards.

**Tasks:**

1. Build a small registry of 3 agents (you can simulate the ones from this
   module — they don't all need to be running):
   - Technical Summarizer (from Lab 11A)
   - Code Reviewer agent (add a stub server on port 8003)
   - Data Analyst agent (stub on port 8004)

2. Implement `discover_agents(registry_urls: list[str]) -> list[dict]`:
   - Fetches Agent Cards from all provided URLs concurrently (httpx async)
   - Returns list of cards, skipping unreachable agents

3. Implement `select_best_agent(cards: list[dict], task_description: str) -> dict`:
   - Passes the task description and all agent cards' descriptions/skills to the LLM
   - Asks the LLM to select the best agent and return its name + reasoning
   - Returns the selected card

4. Build an orchestrator that:
   - Discovers available agents from the registry
   - Takes a user task description
   - Selects the best agent
   - Routes the task to that agent via A2A
   - Returns the result

5. Test with 3 different tasks that should route to different agents.

**File:** `lab/src/dynamic_discovery.py`

---

## Conceptual Checkpoints

Answer these before moving to Module 12:

1. **Protocol design**: The A2A protocol uses SSE for streaming instead of
   WebSockets. What are the trade-offs of this choice? In what scenarios
   would WebSockets be a better fit? In what scenarios is SSE clearly better?

2. **A2A vs. direct HTTP**: An agent could call another agent by just POST-ing
   to a custom endpoint. What does A2A add that a custom REST call doesn't
   provide? Be specific about the concrete engineering benefits.

3. **Task state machine**: A Task moves through states: submitted → working →
   completed (or failed). What happens if a client calls `/tasks/send` and the
   server crashes mid-processing? How would you make the A2A server stateful
   enough to recover from this? What storage would you use in Azure?

4. **Discovery vs. hardcoding**: Your orchestrator currently has a hardcoded
   list of agent registry URLs. Describe a production-grade discovery system
   where agents self-register. What components would you need? What are the
   failure modes of self-registration?

5. **Artifact design**: What is the difference between putting the agent's
   response in a message vs. in an artifact? When should you use artifacts?
   Design the artifact schema for an agent that produces a financial analysis
   report with charts (as base64 images) and tabular data.

---

## Resources

- A2A Protocol specification:
  https://google.github.io/A2A/
- A2A GitHub repository (reference implementations):
  https://github.com/google-deepmind/a2a
- FastAPI Server-Sent Events:
  https://fastapi.tiangolo.com/advanced/custom-response/
- Azure OpenAI streaming:
  https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/streaming
