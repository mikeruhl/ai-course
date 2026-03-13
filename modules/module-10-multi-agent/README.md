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

**Goal:** Build an orchestrator that routes queries to one of three specialists based on LLM-driven confidence scoring.

**What to do:**

1. Open `lab/src/orchestrator_subagent.py`. Find the three specialist functions:
   `code_reviewer_agent()`, `security_analyst_agent()`, and `performance_advisor_agent()`.
   Each has a TODO comment at Task 1 — update the user message in each to include
   the `query` parameter so the specialist focuses on the developer's actual concern.

2. Study the `orchestrator()` function. It already handles high-confidence routing
   (confidence >= 0.7). Find the `NotImplementedError` at Task 3 and implement
   the low-confidence path: call all three specialists and merge their results
   into a list.

3. Run:
   ```bash
   cd modules/module-10-multi-agent/lab
   uv run python src/orchestrator_subagent.py
   ```

**Expected result:**
- Three test cases run sequentially. For each you see a routing table and specialist findings:
  ```
  Test Case 1: Code quality concern
  Routed to   code_reviewer
  Confidence  95%
  Reason      The query is about code readability and improvement
  Latency     2.14s
  ┌─ Specialist findings ─────────────────────────────────────┐
  │ {                                                         │
  │   "findings": ["Single-letter variable names", ...],      │
  │   "overall_grade": "D",                                   │
  │   "top_recommendation": "Use descriptive variable names"  │
  │ }                                                         │
  └───────────────────────────────────────────────────────────┘
  ```
- Test Case 2 routes to `security_analyst`, Test Case 3 routes to `performance_advisor`.
- If any query produces confidence < 0.7 (after Task 3), all three specialists run and you see a merged result list.

**Why this matters:**
LLM-based routing replaces brittle keyword matching with semantic understanding of intent. The confidence threshold pattern is how production systems decide between specialist routing and broad-spectrum analysis — the same pattern appears in customer service triage, incident response, and code review pipelines.

---

### Lab 10B: Handoff Chain

**Goal:** Build a 3-stage pipeline (planner, researcher, writer) where agents hand off context through a shared dict.

**What to do:**

1. Open `lab/src/handoff_chain.py`. Study the `AgentContext` TypedDict and
   `AgentMetadata` TypedDict at the top — these define the shared state contract.

2. Find `researcher_agent()` (the TODO at Task 2). Improve its system prompt to
   instruct the model to cite concrete technical details, flag uncertainty, and
   target senior engineers familiar with Python.

3. Find `run_pipeline()` (the TODO at Task 3). Add a `rich.progress` display so
   each stage shows progress in real time.

4. Run:
   ```bash
   cd modules/module-10-multi-agent/lab
   uv run python src/handoff_chain.py
   ```

**Expected result:**
- Console logs show each stage running sequentially with token counts:
  ```
  [14:22:01] Running stage: planner
  [14:22:04] Stage complete: planner (tokens so far: 847)
  [14:22:04] Running stage: researcher
  [14:22:12] Stage complete: researcher (tokens so far: 2341)
  [14:22:12] Running stage: writer
  [14:22:22] Stage complete: writer (tokens so far: 4105)
  ```
- A summary table prints with columns: Agent, Tokens, Output preview.
- The final draft panel shows a polished ~800-word blog post about Python's GIL removal.
- Total elapsed time and total tokens appear at the bottom.

**Why this matters:**
Handoff chains are the most common multi-agent pattern in production — document processing pipelines, ETL with LLM enrichment, and content generation all use this shape. The `HandoffError` validation between stages prevents the silent context-loss failures that plague real systems when one stage produces empty output and the next stage hallucinates to fill the gap.

---

### Lab 10C: Peer Debate

**Goal:** Build a 2-agent debate system with a judge to explore trade-offs in a technical decision.

**What to do:**

1. Open `lab/src/peer_debate.py`. Find `advocate_for()` and `advocate_against()`
   (both have TODO at Task 1). Update the system prompts to be round-specific:
   round 1 should establish the strongest case, round 2 should directly counter
   the opponent's points, round 3 should summarize memorably.

2. Find `judge_agent()` (TODO at Task 3). Consider whether the judge should
   weigh later rounds more heavily and instruct it to state which round was
   most decisive.

3. Run:
   ```bash
   cd modules/module-10-multi-agent/lab
   uv run python src/peer_debate.py
   ```

**Expected result:**
- Three rounds of debate print with FOR (green) and AGAINST (red) panels:
  ```
  Round 1: Opening Statement
  ┌─ FOR ──────────────────────────────────────────────────┐
  │ Message queues provide natural resilience through       │
  │ decoupling. When the order service publishes an event,  │
  │ the inventory service can process it at its own pace... │
  └────────────────────────────────────────────────────────┘
  ┌─ AGAINST ──────────────────────────────────────────────┐
  │ Direct HTTP calls offer immediate consistency and       │
  │ simpler debugging. With a message queue, you trade      │
  │ simplicity for eventual consistency...                  │
  └────────────────────────────────────────────────────────┘
  ```
- After 3 rounds, the judge's verdict panel shows winner, reason, and key points.
- Total debate time is ~15-25 seconds (7 LLM calls: 3 rounds x 2 advocates + 1 judge).

**Why this matters:**
Debate patterns force the LLM to steelman both sides of a decision, producing higher-quality analysis than a single prompt. Production uses include architecture decision records, risk assessment, and code review where you want to surface trade-offs rather than a single opinion. The cost is 7+ LLM calls per decision — reserve this for high-stakes choices.

---

### Lab 10D: Agent Cards

**Goal:** Replace hardcoded routing with data-driven Agent Cards loaded from JSON files.

**What to do:**

1. Open `lab/src/cards/` and examine the three JSON files:
   `code_reviewer.json`, `security_analyst.json`, `performance_advisor.json`.
   Each has `name`, `description`, `skills`, `input_schema`, `output_schema`,
   and `cost_tier` fields.

2. Open `lab/src/agent_cards.py`. Find `CardRegistry.find_best_match()` (TODO
   at Task 2). Implement it by:
   a. Building a summary string of all agent names + descriptions.
   b. Calling `call_llm()` with a prompt asking for the best agent name.
   c. Validating the returned name is in `list_agents()`.

3. To test extensibility (Task 4), create `lab/src/cards/architecture_reviewer.json`
   with the same schema — no orchestrator code changes needed.

4. Run:
   ```bash
   cd modules/module-10-multi-agent/lab
   uv run python src/agent_cards.py
   ```

**Expected result:**
- Step 1 shows three agent card panels with name, description, cost tier, and skills.
- Step 2 lists: `['code_reviewer', 'performance_advisor', 'security_analyst']`.
- Step 3 routes three demo queries and displays a table:
  ```
  ┌─ Routing Results ──────────────────────────────────────────┐
  │ Query                                       │ Best match   │
  ├─────────────────────────────────────────────┼──────────────┤
  │ Is there a SQL injection vulnerability...   │ security_a…  │
  │ This nested loop is taking 30 seconds...    │ performance… │
  │ Can you review this function for readab...  │ code_review… │
  └─────────────────────────────────────────────┴──────────────┘
  ```
- Step 4 explains how adding a new JSON card file extends routing with zero code changes.

**Why this matters:**
Agent Cards decouple routing policy from orchestrator code. In production, this means new specialists can be deployed by dropping a JSON file into a registry — the same pattern used by service meshes and API gateways. It also makes routing decisions auditable: you can inspect exactly what descriptions the LLM saw when it made a routing choice.

---

### Lab 10E: Failure Detection and Circuit Breaker

**Goal:** Detect delegation loops and prevent cascading failures with a circuit breaker state machine.

**What to do:**

1. Open `lab/src/circuit_breaker.py`. Study `check_for_cycles()` — it uses
   `Counter` to detect when any agent exceeds `max_calls` invocations.

2. Find `AgentCircuitBreaker.call()` (TODO at Task 2). Implement the 5-step
   state machine described in its docstring: check OPEN state, record latency,
   try the call, handle success (reset to CLOSED), handle failure (increment
   count, transition to OPEN at threshold).

3. Study `looping_agent()` — it always raises `ValueError`, simulating a
   permanently broken subagent.

4. Run:
   ```bash
   cd modules/module-10-multi-agent/lab
   uv run python src/circuit_breaker.py
   ```

**Expected result:**
- Part A (cycle detection) shows two sequences:
  ```
  Sequence ['planner', 'researcher', 'writer'] → OK — no cycle detected
  Sequence ['planner', 'researcher', 'planner', 'researcher', 'planner'] → CyclicDelegationError
  ```
- Part B calls `looping_agent` 5 times through the circuit breaker:
  ```
  Call 1 | state before: closed   → ValueError (agent failed)   → state after: closed
  Call 2 | state before: closed   → ValueError (agent failed)   → state after: closed
  Call 3 | state before: closed   → ValueError (agent failed)   → state after: open
                                    State transition: closed → open
  Call 4 | state before: open     → CircuitOpenError             → state after: open
  Call 5 | state before: open     → CircuitOpenError             → state after: open
  ```
- The telemetry table shows 3 rows (calls 4 and 5 are rejected before invocation).
- Calls 4 and 5 complete in <1ms because no LLM call is made.

**Why this matters:**
Without circuit breakers, a failing subagent consumes tokens and latency on every retry. In production multi-agent systems, one broken specialist can cascade into orchestrator timeouts and user-facing errors. The CLOSED/OPEN/HALF_OPEN state machine is the same pattern used by Polly (.NET), resilience4j (Java), and Azure API Management — understanding it here transfers directly.

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
