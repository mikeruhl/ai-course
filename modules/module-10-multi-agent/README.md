# Module 10: Multi-Agent Architectures

## Overview

Single-agent systems with many tools start to break down as tasks grow more
complex. Multi-agent systems distribute work across specialized agents, enabling
parallelism, separation of concerns, and cleaner failure boundaries. This
module builds all four major topologies from scratch in plain Python — no
frameworks — so you understand what orchestration frameworks are actually doing.

By the end: you have working implementations of orchestrator-subagent,
handoff/swarm, peer-to-peer debate, and hierarchical patterns, plus the
tooling to detect and break coordination failure loops.

---

## Concepts

### 1. The Four Topologies

#### Orchestrator-Subagent

A central "orchestrator" LLM receives the user request, analyzes it, and
delegates to one or more specialist "subagent" LLMs. Each subagent has:
- A narrow, focused system prompt (its persona and expertise)
- A restricted tool set (only what it needs)
- A defined input/output contract

The orchestrator does not execute the task itself — it reasons about *which
specialist to invoke* and *what to pass them*.

```
User ──► Orchestrator ──► Specialist A (code reviewer)
                     ├──► Specialist B (security analyst)
                     └──► Specialist C (performance advisor)
```

Best for: customer service routing, multi-domain Q&A, parallel workloads
where subtasks are independent.

#### Handoff (Swarm Pattern)

Each agent in a pipeline handles one stage, then explicitly *transfers control*
to the next agent along with accumulated context. No central coordinator.

```
User ──► Planner ──► Researcher ──► Writer ──► User
         (adds     (adds           (produces
          plan)     findings)       output)
```

The "handoff" is explicit: the current agent decides *when it is done* and
*which agent comes next*. The key artifact is the shared context dict — each
agent reads what previous agents wrote and adds its own contribution.

Best for: sequential pipelines, document processing, multi-step transformations
where each stage's output is the next stage's input.

#### Peer-to-Peer (Debate / Critique)

Two or more agents communicate directly with each other, exchanging messages
over multiple rounds. Common patterns:
- **Debate**: agents argue opposing positions; a judge decides
- **Critique-revise**: agent A produces output, agent B critiques it, A revises
- **Consensus**: agents negotiate until they agree

```
Agent A ◄──► Agent B
             │
             ▼
           Judge Agent
```

Best for: improving output quality, exploring trade-offs, catching blind spots
in reasoning. Expensive (multiple LLM calls per output) — use when quality
justifies the cost.

#### Hierarchical

Orchestrators can themselves be subagents to a higher-level orchestrator.
Creates a tree structure where high-level planning at the top decomposes into
increasingly specific subtasks at lower levels.

```
Top-level Orchestrator
├── Domain Orchestrator A
│   ├── Specialist A1
│   └── Specialist A2
└── Domain Orchestrator B
    ├── Specialist B1
    └── Specialist B2
```

Best for: very large, complex tasks (e.g., full software development lifecycle,
research report generation). The complexity cost is real — only use when
simpler topologies genuinely can't handle the scope.

---

### 2. When to Split Into Multiple Agents

Split into multiple agents when:

| Condition | Reason |
|-----------|--------|
| Tasks require different system prompts or personas | Can't have "be a security expert" and "be a performance expert" active simultaneously with equal weight |
| Tasks benefit from parallel execution | Independent subtasks can run concurrently |
| You want to limit tool access per task type | Security principle: don't give the writer agent access to the database tool |
| Context windows would overflow | Long pipelines accumulate too much history |
| Tasks have different quality/cost profiles | Route cheap tasks to gpt-4o-mini, complex to gpt-4o |

Keep as one agent when:

| Condition | Reason |
|-----------|--------|
| Tasks are tightly sequential and share significant context | Splitting loses continuity and adds coordination overhead |
| The overhead of coordination exceeds the benefit | Serializing/deserializing context between agents is real work |
| The task is simple enough for one context window | Unnecessary complexity |
| You need strong consistency between steps | Context loss at handoff points is a real failure mode |

The most common mistake is premature decomposition — splitting into agents
because it "feels" like the right architecture before you've measured whether
a single agent actually fails.

---

### 3. Agent Communication Models

#### Shared State (Dict Passing)

Simplest. A Python dict is passed from agent to agent. Each agent reads and
writes keys. No network overhead.

```python
context = {"task": "...", "plan": None, "research": None, "draft": None}
context = planner_agent(context)    # sets context["plan"]
context = researcher_agent(context) # sets context["research"]
context = writer_agent(context)     # sets context["draft"]
```

Works well for single-process pipelines. Breaks down for distributed systems
(agents on different hosts) and for parallelism (concurrent writes need locking).

#### Message Passing

Each agent's output is the next agent's input message. No shared mutable state.
Cleaner interfaces, but requires each agent's system prompt to instruct it on
how to interpret the incoming message.

#### Shared Memory Store

External store (Redis, a database, Azure Blob) that agents read and write.
Enables distributed agents, natural persistence, auditability. Required for
production multi-agent systems that span services or need durability.

---

### 4. Agent Cards

An Agent Card is a JSON document describing an agent's capabilities. The
orchestrator uses cards to decide which agent to route to, without hardcoding
routing logic.

Minimum viable Agent Card:

```json
{
  "name": "security_analyst",
  "description": "Reviews code and configurations for security vulnerabilities. Specializes in OWASP Top 10, injection attacks, authentication flaws, and cryptographic issues.",
  "input_schema": {
    "type": "object",
    "properties": {
      "code": {"type": "string", "description": "Code or config to review"},
      "language": {"type": "string", "description": "Programming language"}
    },
    "required": ["code"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "findings": {"type": "array"},
      "risk_level": {"type": "string", "enum": ["low", "medium", "high", "critical"]}
    }
  },
  "skills": ["security-review", "vulnerability-assessment", "owasp"],
  "cost_tier": "medium"
}
```

The orchestrator reads the `description` and `skills` fields to make routing
decisions. This makes the system data-driven: add a new specialist by adding
a new card, without changing orchestrator code.

---

### 5. Failure Modes

#### Oscillation (Feedback Loop)

Agent A delegates to Agent B. Agent B decides it should delegate back to
Agent A. They loop forever.

Detection: track the sequence of agent invocations. If the same agent appears
twice in a row, or a cycle is detected in the delegation graph, break the loop.

Circuit breaker: if an agent has been called N times in this task execution,
refuse further calls to it and return an error.

#### Fanout Explosion

One orchestrator spawns 50 subagent calls. Each subagent spawns 10 more.
Your token budget and rate limits explode.

Prevention: enforce a maximum parallelism limit and a maximum total agent
invocations per task.

#### Context Loss at Handoff

When agent A passes context to agent B, critical information is dropped —
either because the context dict was incomplete or because agent B's system
prompt doesn't instruct it to look at the right keys.

Prevention: define explicit input/output contracts (as in Agent Cards),
validate the context dict before passing it to each agent.

#### Cascade Failure

One specialist fails. The orchestrator doesn't handle the error and passes
partial results to the next agent. The failure propagates silently and the
final output is garbage.

Prevention: validate each agent's output before proceeding. Return explicit
errors up the chain rather than continuing with bad data.

---

### 6. Implementation Pattern: Agents Are Functions

The key insight for clean implementation: an agent is a function.

```python
from typing import TypedDict

class AgentContext(TypedDict):
    task: str
    plan: str | None
    research: str | None
    draft: str | None
    errors: list[str]

def planner_agent(ctx: AgentContext) -> AgentContext:
    """Takes context, calls the LLM with planner persona, returns updated context."""
    # ... call LLM ...
    ctx["plan"] = llm_response
    return ctx
```

The orchestrator is also a function — it calls other functions:

```python
def orchestrator(ctx: AgentContext) -> AgentContext:
    selected_agent = route(ctx)  # returns a function
    return selected_agent(ctx)
```

No magic. No framework. Just Python functions that wrap LLM calls. When you
understand this, you understand what LangGraph, AutoGen, and Semantic Kernel
are doing under the hood.

---

## Lab Tasks

### Setup

```bash
cd modules/module-10-multi-agent/lab
cp .env.example .env
# Edit .env with your Azure OpenAI credentials
uv sync
```

---

### Lab 10A: Orchestrator-Subagent Routing

**Goal:** Build an orchestrator that routes queries to one of three specialists.

The orchestrator receives a user query and decides (via LLM reasoning) which
specialist to invoke:
- `code_reviewer`: analyzes code quality, patterns, and best practices
- `security_analyst`: identifies security vulnerabilities and risks
- `performance_advisor`: spots performance bottlenecks and optimization opportunities

**Tasks:**

1. Implement the three specialist agents, each with:
   - A distinct system prompt reflecting their expertise
   - A function signature: `agent_name(query: str, code: str) -> dict`
   - Structured JSON output (findings, severity, recommendation)

2. Implement the orchestrator agent that:
   - Receives the raw user query
   - Uses LLM reasoning to decide which specialist to invoke
   - Returns the routing decision as structured JSON: `{"agent": "...", "reason": "..."}`
   - Invokes the chosen specialist and returns the result

3. Test with three different queries that should route to different specialists:
   - "This function iterates over a list 10,000 times..."
   - "This endpoint accepts user input and builds a SQL query..."
   - "This class has 47 methods and 800 lines..."

4. Add confidence scoring: the orchestrator returns a confidence score
   (0.0-1.0) alongside its routing decision. If confidence < 0.7, invoke
   all three specialists and return all results.

**File:** `lab/src/orchestrator_subagent.py`

---

### Lab 10B: Handoff Chain

**Goal:** Build a 3-stage pipeline where agents hand off to each other via shared context.

Pipeline: `planner → researcher → writer`

Each stage reads the context, does its work, and adds to the context before
passing it to the next stage.

**Tasks:**

1. Define the context schema:
   ```python
   context = {
       "task": str,           # original user request (immutable)
       "plan": str | None,    # set by planner
       "research": str | None, # set by researcher
       "draft": str | None,   # set by writer
       "metadata": {
           "agents_run": list[str],
           "token_usage": dict,
           "start_time": float
       }
   }
   ```

2. Implement each agent as a function. Each agent:
   - Reads relevant context keys
   - Builds its system prompt referencing the prior stage's output
   - Calls the LLM
   - Writes its output to the appropriate context key
   - Appends its name to `metadata.agents_run`

3. Build the pipeline runner: a function that executes the chain in order
   and returns the final context dict.

4. Add validation between stages: after each agent, assert that the expected
   context key is non-empty. If not, raise a `HandoffError` with details.

5. Test with: "Write a technical blog post explaining why Python's GIL is
   being removed and what it means for async code."

Print a rich table showing: agent name, tokens used, output preview.

**File:** `lab/src/handoff_chain.py`

---

### Lab 10C: Peer Debate

**Goal:** Build a 2-agent debate system with a judge.

**Tasks:**

1. Implement two advocate agents:
   - `advocate_for(position, context)` — argues in favor of a technical decision
   - `advocate_against(position, context)` — argues against it

2. The debate runs for 3 rounds:
   - Round 1: each advocate makes their opening argument (no awareness of the other)
   - Round 2: each advocate is shown the other's Round 1 argument and responds
   - Round 3: each advocate makes a closing statement

3. Implement a judge agent that:
   - Receives all 6 messages (3 rounds × 2 advocates)
   - Returns: `{"winner": "for|against|tie", "reason": str, "key_points": list[str]}`

4. Test with: "Should we use a message queue (Kafka/Azure Service Bus) for
   inter-service communication in our microservices architecture, or use
   direct HTTP calls?"

5. Print the debate transcript with rich formatting: each round's arguments
   side by side, then the judge's verdict.

**File:** `lab/src/peer_debate.py`

---

### Lab 10D: Agent Cards

**Goal:** Make the orchestrator data-driven by reading Agent Cards.

**Tasks:**

1. Define Agent Card JSON files for each specialist (`cards/` directory):
   - `code_reviewer.json`
   - `security_analyst.json`
   - `performance_advisor.json`

   Each card must include: `name`, `description`, `skills`, `input_schema`,
   `output_schema`, `cost_tier` ("low", "medium", "high").

2. Build a card registry: a Python class that loads all cards from the
   directory and provides:
   - `list_agents()` → list of agent names
   - `get_card(name)` → dict
   - `find_best_match(query)` → uses LLM to pick the best agent given the query

3. Refactor the orchestrator from Lab 10A to use the card registry for routing
   instead of hardcoded logic. The orchestrator passes the cards' descriptions
   to the LLM as routing context.

4. Add a new card for a new specialist (`architecture_reviewer`) without
   changing any orchestrator code — verify routing works automatically.

**File:** `lab/src/agent_cards.py`

---

### Lab 10E: Failure Detection and Circuit Breaker

**Goal:** Simulate and detect coordination failures.

**Tasks:**

1. Implement a "looping agent" that always delegates back to the orchestrator
   (simulating an oscillation failure).

2. Add cycle detection to the orchestrator:
   - Track the sequence of agent invocations for this task
   - If any agent is invoked more than `max_calls` times (default: 2), raise
     `CyclicDelegationError`

3. Implement a circuit breaker class:
   ```python
   class AgentCircuitBreaker:
       def __init__(self, max_failures: int, reset_timeout_seconds: int): ...
       def call(self, agent_fn, *args) -> Any: ...
       # Raises CircuitOpenError if agent has failed max_failures times recently
   ```

4. Add invocation telemetry: after each agent call, log:
   - Agent name
   - Input context size (chars)
   - Output context size (chars)
   - Latency (ms)
   - Success/failure

5. Test the circuit breaker: make the looping agent fail 3 times, verify
   the circuit opens and subsequent calls are rejected without hitting the LLM.

**File:** `lab/src/circuit_breaker.py`

---

## Conceptual Checkpoints

Answer these before moving to Module 11:

1. **Topology selection**: A task requires generating a marketing campaign:
   first researching competitors, then drafting copy, then reviewing for legal
   compliance. Which topology fits best and why? What are the failure modes
   specific to that topology?

2. **Split criteria**: You have an agent with 12 tools. Response quality is
   declining and tool selection errors are increasing. You're considering
   splitting into 3 agents with 4 tools each. What questions do you need to
   answer before making that decision? What metrics would tell you whether
   the split helped?

3. **Context loss**: In a handoff chain, Agent B produces low-quality output
   because it "forgot" the original user intent. The planner's output was
   technically correct but didn't include the original task. How do you
   redesign the context schema to prevent this? What's the general principle?

4. **Failure modes**: Describe a realistic scenario where an orchestrator-
   subagent system enters an oscillation loop. What specific conditions in the
   system prompts would cause this? What is the minimum information you need
   in your invocation log to detect it?

5. **Agent Cards vs. hardcoding**: What are the concrete engineering benefits
   of using Agent Cards for routing vs. an if/elif chain in the orchestrator?
   In what situations might the Agent Card approach be overkill?

---

## Resources

- "Building Effective Agents" — Anthropic blog post on multi-agent patterns:
  https://www.anthropic.com/research/building-effective-agents
- Azure OpenAI API reference:
  https://learn.microsoft.com/en-us/azure/ai-services/openai/reference
- "Mixture of Agents" paper (multi-agent quality improvement):
  https://arxiv.org/abs/2406.04692
- AutoGen paper (peer-to-peer multi-agent):
  https://arxiv.org/abs/2308.08155
