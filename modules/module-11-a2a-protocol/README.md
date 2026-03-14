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

### Option B: Google Vertex AI

Use Vertex AI's OpenAI-compatible endpoint instead of Azure OpenAI for the
LLM calls. Azure-specific services (AI Search, embeddings) still require Azure.

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

For labs B-E, you'll run multiple processes (the server and the client).
Use separate terminal windows or run the server in the background.

---

### Lab 11A: Minimal A2A Server

**Goal:** Implement a working A2A-compliant agent server using raw `http.server` so you see every protocol detail.

**What to do:**

1. Open `lab/src/a2a_server.py`. Study the `AGENT_CARD` dict at the top — it
   defines the agent's identity, capabilities, and skills as served at
   `/.well-known/agent.json`.

2. Study `A2ARequestHandler.handle_send()` — it parses the A2A message schema
   (`id`, `message.parts[].text`), calls `run_research_agent()` via Azure
   OpenAI, and returns a completed `Task` dataclass.

3. Find `handle_send_subscribe()` (TODO at Task 3). Implement SSE streaming:
   send response headers with `Content-Type: text/event-stream`, then emit
   `data: <json>\n\n` events for each status transition (submitted, working,
   completed/failed), flushing after each event.

4. Run the server:
   ```bash
   cd modules/module-11-a2a-protocol/lab
   uv run python src/a2a_server.py
   ```

5. Test manually in another terminal:
   ```bash
   curl http://localhost:8080/.well-known/agent.json
   curl -X POST http://localhost:8080/tasks/send \
     -H "Content-Type: application/json" \
     -d '{"id":"test-1","message":{"role":"user","parts":[{"type":"text","text":"What is RAG?"}]}}'
   ```

**Expected result:**
- The server starts and prints:
  ```
  A2A Agent Server running on port 8080
    Agent Card: http://localhost:8080/.well-known/agent.json
    Send task:  POST http://localhost:8080/tasks/send
    Streaming:  POST http://localhost:8080/tasks/sendSubscribe
  ```
- The Agent Card curl returns JSON with `name: "researcher-agent"`, `capabilities.streaming: true`, and one skill `"research"`.
- The task POST returns a JSON object with `status: "completed"`, the original `input`, and an `output` field containing the LLM's answer about RAG.
- Server console shows: `Task test-1… submitted: What is RAG?` then `Task test-1… completed`.

**Why this matters:**
Building an A2A server from `http.server` (no FastAPI, no SDK) forces you to understand exactly what the protocol requires: the well-known discovery endpoint, the message/parts schema, and the task state machine. Every A2A SDK hides these details — knowing them means you can debug interoperability issues between agents built by different teams or in different languages.

---

### Lab 11B: A2A Client

**Goal:** Build a client that discovers an agent via its card and submits tasks using the A2A protocol.

**What to do:**

1. Open `lab/src/a2a_client.py`. Study `discover_agent()` — it fetches the
   Agent Card from `/.well-known/agent.json` and returns the parsed dict.

2. Study `submit_task()` — it constructs the A2A message payload with
   `id`, `message.role`, and `message.parts[]`, POSTs to `/tasks/send`,
   and returns the completed task dict.

3. Find `submit_task_streaming()` (TODO at Task 3). Implement it: open a
   streaming POST to `/tasks/sendSubscribe`, iterate response lines, parse
   `data: <json>` lines, and print each status update.

4. Start the server from Lab 11A in one terminal, then run the client:
   ```bash
   # Terminal 1:
   cd modules/module-11-a2a-protocol/lab
   uv run python src/a2a_server.py

   # Terminal 2:
   cd modules/module-11-a2a-protocol/lab
   uv run python src/a2a_client.py --server http://localhost:8080 --query "What is eventual consistency?"
   ```

**Expected result:**
- Step 1 (Agent Discovery) prints a table:
  ```
  Agent: researcher-agent
  Description     Answers research questions by searching a knowledge base...
  Version         1.0.0
  URL             http://localhost:8080
  Streaming       True
  Skills          [research] Research Question: Research and answer a question...
  ```
- Step 2 (Task Submission) prints the task ID, status `completed`, and a
  Result panel containing the LLM's explanation of eventual consistency.
- If the server is not running, the client prints: `Could not connect to http://localhost:8080` with a hint to start the server.

**Why this matters:**
The client demonstrates A2A's value proposition: discover capabilities at runtime, submit work using a standardized schema, and handle results uniformly regardless of what the agent does internally. This is the same pattern that lets you swap agent implementations (Python to C#, OpenAI to Anthropic) without changing client code.

---

### Lab 11C: Streaming with SSE

**Goal:** Add SSE streaming to the A2A server and consume it from the client for real-time output.

**What to do:**

1. Open `lab/src/a2a_server.py`. Find `handle_send_subscribe()` (the TODO at
   Task 3). Implement it:
   - Send response headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache`
   - Emit `data: <json>\n\n` for each status transition: submitted, working, completed/failed
   - Call `self.wfile.flush()` after each event
   - Close the connection when done

2. Open `lab/src/a2a_client.py`. Find `submit_task_streaming()` (the TODO at
   Task 3). Implement the SSE consumer: open a streaming POST with
   `stream=True`, iterate response lines, parse `data:` lines as JSON, and
   print each status update.

3. Start the server and run the client with `--stream`:
   ```bash
   # Terminal 1:
   cd modules/module-11-a2a-protocol/lab
   uv run python src/a2a_server.py

   # Terminal 2:
   cd modules/module-11-a2a-protocol/lab
   uv run python src/a2a_client.py --server http://localhost:8080 --query "Explain the CAP theorem" --stream
   ```

**Expected result:**
- The client prints status updates as they arrive in real time:
  ```
  Streaming mode (Task 3)
  Status: submitted
  Status: working
  Output: The CAP theorem, also known as Brewer's theorem...
  Status: completed
  ```
- Time-to-first-token is noticeably faster than the synchronous `/tasks/send` path because the server begins emitting events as soon as the LLM starts generating.

**Why this matters:**
SSE streaming is how production agent systems deliver progressive output — the same mechanism behind ChatGPT's typing effect. For long-running agent tasks (30+ seconds), streaming prevents HTTP timeouts and gives users visible progress. A2A standardizes the event names (`task_status_update`, `task_artifact_update`) so any compliant client can consume any compliant server's stream.

---

### Lab 11D: Two-Agent Delegation System

**Goal:** Build a planner agent that delegates research subtasks to a researcher agent over the network via A2A.

**What to do:**

1. This lab requires creating two new server files. The researcher agent
   (port 8002) serves an Agent Card with skill `"research"` and processes
   research queries via Azure OpenAI, returning artifacts with `findings`,
   `confidence`, and `sources_consulted`.

2. The planner agent (port 8001) receives a complex task, uses the LLM to
   decompose it into 2-3 research questions, calls the researcher via
   `submit_task()` from `lab/src/a2a_client.py` for each question, and
   assembles the results.

3. Add bearer token authentication: the planner includes an `Authorization`
   header, and the researcher validates it before processing.

4. Run both servers and test:
   ```bash
   # Terminal 1 (researcher):
   cd modules/module-11-a2a-protocol/lab
   A2A_SERVER_PORT=8002 uv run python src/researcher_agent.py

   # Terminal 2 (planner):
   cd modules/module-11-a2a-protocol/lab
   A2A_SERVER_PORT=8001 uv run python src/planner_agent.py

   # Terminal 3 (client):
   curl -X POST http://localhost:8001/tasks/send \
     -H "Content-Type: application/json" \
     -d '{"id":"test-1","message":{"role":"user","parts":[{"type":"text","text":"What are the trade-offs between PostgreSQL and MongoDB for a high-volume time-series workload?"}]}}'
   ```

**Expected result:**
- The planner decomposes the query into 2-3 sub-questions (visible in its server logs).
- The planner's logs show outbound A2A calls to `http://localhost:8002/tasks/send`.
- The researcher's logs show incoming tasks and completions.
- The final response assembles all research findings into a synthesized answer covering write throughput, query patterns, storage efficiency, and operational complexity.

**Why this matters:**
This is the canonical A2A use case: agents as independent services calling each other over HTTP. In production, the planner and researcher could be maintained by different teams, written in different languages, and scaled independently. The bearer token adds a minimal auth layer — real systems use OAuth2 or managed identity, covered in Module 13.

---

### Lab 11E: Dynamic Discovery

**Goal:** Build an orchestrator that discovers available agents at runtime and routes tasks to the best match.

**What to do:**

1. Open `lab/src/a2a_discover.py`. Study `discover_agent()` — it fetches a
   single Agent Card and stashes the `_discovered_url` for later use.
   `discover_all_agents()` probes a list of URLs and collects reachable cards.

2. Find `select_agent_for_task()` (TODO at Task 3). Implement LLM-based
   selection: build a prompt listing each agent's name, description, and skills,
   ask the LLM to respond with just the agent name, and match it back to
   the agents list.

3. Start the researcher server from Lab 11A, then run discovery:
   ```bash
   # Terminal 1:
   cd modules/module-11-a2a-protocol/lab
   uv run python src/a2a_server.py

   # Terminal 2:
   cd modules/module-11-a2a-protocol/lab
   uv run python src/a2a_discover.py
   ```

**Expected result:**
- Step 1 probes three URLs. Only `localhost:8080` responds; the others show `unreachable`:
  ```
  Probing http://localhost:8080 … found (researcher-agent)
  Probing http://localhost:8081 … unreachable
  Probing http://localhost:8082 … unreachable
  ```
- A Discovered Agents table shows the single reachable agent with its name, URL, skills, and streaming capability.
- Step 3 (after implementing Task 3) selects `researcher-agent` for the sample task.
- Step 4 submits a real query to the selected agent and prints the result.

**Why this matters:**
Dynamic discovery is what makes multi-agent systems elastic. In production, agents register with a service registry (Consul, Azure Service Bus, Kubernetes DNS), and orchestrators query it at runtime. This means you can deploy a new specialist agent without restarting or reconfiguring the orchestrator — the same principle behind microservice discovery, applied to AI agents.

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
