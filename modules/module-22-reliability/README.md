# Module 22: Reliability Patterns

## Overview

AI agents are inherently unreliable. The LLM is non-deterministic, tool calls
can fail, APIs rate-limit, and the agent can hallucinate actions that don't
make sense. Traditional software has deterministic failure modes; agent
software has probabilistic ones.

Production agents need the same reliability patterns as any distributed
system — retries, circuit breakers, fallbacks, timeouts — plus new patterns
specific to LLMs: output validation, hallucination guards, and loop detection.

By the end of this module you will have implemented four core reliability
patterns and understand when to apply each one.

---

## Concepts

### 1. Why Agents Are Unreliable

An agent's failure surface is much larger than a traditional API:

```
Traditional API failure modes:
  → Network error
  → Timeout
  → 500 Internal Server Error
  → Rate limit (429)

Agent failure modes (all of the above, PLUS):
  → Model hallucates a tool name that doesn't exist
  → Model calls a tool with invalid arguments
  → Model ignores instructions and goes off-task
  → Model enters an infinite loop (calls same tool repeatedly)
  → Model generates unsafe/toxic content
  → Model returns valid JSON that means the wrong thing
  → Model's "reasoning" is correct but the final answer is wrong
  → Tool succeeds but returns data the model misinterprets
```

Each agent step compounds error probability. A 5-step agent where each step
has 95% reliability has an end-to-end success rate of 0.95^5 = 77%.

### 2. Retry with Exponential Backoff

The most fundamental reliability pattern. When a transient error occurs
(429, 500, network timeout), retry after an increasing delay.

```
Attempt 1: immediate
Attempt 2: wait ~1s
Attempt 3: wait ~2s
Attempt 4: wait ~4s
Attempt 5: wait ~8s
```

**Full jitter** randomizes the delay within [0, calculated_delay] to prevent
thundering herd — when many clients retry simultaneously after a shared
failure (e.g., Azure OpenAI regional outage recovery).

```
delay = random(0, min(max_delay, base_delay * 2^attempt))
```

**Retry budget**: set a maximum number of retries AND a maximum total time.
Without a budget, a slow failure can block the agent indefinitely.

**Retry-After header**: Azure OpenAI returns this on 429. Always use it
when present — it's the service telling you exactly when capacity will
be available.

### 3. Circuit Breaker

When a downstream service is failing consistently, stop calling it entirely
(fail fast) instead of wasting time on calls that will fail.

```
States:
  CLOSED    → normal operation, failures increment counter
  OPEN      → all calls rejected immediately (fail fast)
  HALF_OPEN → one probe call allowed; success resets, failure re-opens

State transitions:
  CLOSED  → OPEN:      failure_count >= threshold
  OPEN    → HALF_OPEN: recovery_timeout elapsed
  HALF_OPEN → CLOSED:  probe call succeeds
  HALF_OPEN → OPEN:    probe call fails
```

In agent systems, circuit breakers are essential for:
- Tool calls to external APIs (prevent cascading failures)
- Model calls (if a deployment is down, fail fast to fallback)
- Database operations in RAG pipelines

### 4. Timeout Strategies

Agents need timeouts at three levels:

| Level | What it bounds | Typical value |
|---|---|---|
| Per-call | Single LLM or tool call | 30-60s |
| Per-step | One iteration of the agent loop | 120s |
| Per-task | Entire agent execution | 5-15 min |

Without per-task timeouts, an agent in an infinite loop will run forever
and consume unlimited tokens.

### 5. Fallback Chains

When the primary path fails, fall back to progressively simpler alternatives:

```
Tier 1: GPT-4o with full system prompt
  ↓ (failure)
Tier 2: GPT-4o-mini with simplified prompt
  ↓ (failure)
Tier 3: Cached response for common queries
  ↓ (failure)
Tier 4: Static fallback message ("I'm experiencing issues, try again later")
```

Each tier trades quality for reliability. The key insight is that a degraded
response is almost always better than no response.

### 6. Idempotency

Agent actions (tool calls with side effects) must be idempotent — calling
them multiple times with the same arguments produces the same result.

Non-idempotent operations are dangerous because retries and replays can
cause duplicate side effects:
- Sending an email twice
- Creating duplicate database records
- Charging a customer twice

Strategies:
- **Idempotency keys**: attach a unique ID to each operation, reject
  duplicates server-side
- **Check-then-act**: verify the action hasn't already been performed
  before executing
- **Upsert instead of insert**: use merge operations instead of creates

### 7. Output Guardrails

LLM outputs are untrusted. Validate before acting on them.

```
Agent generates JSON:
  → Parse JSON (reject if invalid)
  → Validate against schema (reject if missing fields)
  → Check value ranges (reject if out of bounds)
  → Content safety check (reject if toxic/harmful)
  → Business logic validation (reject if nonsensical)
  → If invalid: retry with feedback OR escalate to human
```

The retry-with-feedback pattern appends the validation error to the
conversation and asks the model to fix its output. This works surprisingly
well — models correct schema violations on the second attempt ~95% of the
time.

### 8. Human-in-the-Loop Checkpoints

For high-stakes actions, pause the agent and require human approval:

```
Agent plan:
  Step 1: Search database ✓ (auto)
  Step 2: Draft email     ✓ (auto)
  Step 3: Send email      ⏸ (requires human approval)
  Step 4: Log action      ✓ (auto)
```

Criteria for requiring human approval:
- Irreversible actions (delete, send, publish)
- Financial actions (charge, refund, transfer)
- Actions affecting other users
- Actions outside the agent's confidence threshold

### 9. Dead Letter Queues

When an agent task fails after all retries and fallbacks, don't lose the
work. Send it to a dead letter queue for later investigation.

A dead letter entry should capture:
- The original request
- All agent steps taken before failure
- Error details and stack traces
- Token usage (for cost analysis)
- Timestamp and agent configuration

### 10. Loop Detection

Agents can enter infinite loops — calling the same tool with the same
arguments repeatedly, or oscillating between two states.

Detection strategies:
- **Step counter**: hard limit on agent loop iterations (e.g., max 20 steps)
- **Duplicate detection**: hash recent tool calls, abort if the same call
  appears N times
- **Token budget**: set a maximum token spend per task

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
| A | `uv run reliability --task A` | Retry with exponential backoff + jitter |
| B | `uv run reliability --task B` | Circuit breaker with state transitions |
| C | `uv run reliability --task C` | Fallback chain (primary → cheaper → cache) |
| D | `uv run reliability --task D` | Output guardrails with schema validation |

### Task A: Retry with Backoff

**Goal:** Implement exponential backoff with full jitter and observe how the delay schedule prevents thundering herd.

**What to do:**
1. Open `lab/src/reliability_patterns.py`
2. Look at `retry_with_backoff()` (line ~64) — it handles 429, 500+, and network errors with jittered delays, and respects the `Retry-After` header when present
3. Look at `task_a()` (line ~116) — it first prints a simulated backoff schedule table, then makes a real API call through the retry wrapper
4. Run: `uv run reliability --task A`

**Expected result:**
- A backoff schedule table showing how max delay doubles per attempt:
  ```
  Backoff Schedule (base=1s, max=60s)
  ┌──────────┬────────────┬───────────────┐
  │ Attempt  │ Max Delay  │ Sample Jitter │
  ├──────────┼────────────┼───────────────┤
  │ 1        │ 1.0s       │ 0.73s         │
  │ 2        │ 2.0s       │ 1.24s         │
  │ 3        │ 4.0s       │ 2.87s         │
  │ 4        │ 8.0s       │ 5.12s         │
  │ 5        │ 16.0s      │ 9.45s         │
  │ 6        │ 32.0s      │ 18.63s        │
  └──────────┴────────────┴───────────────┘
  ```
- A successful API call response: `Response: Retry test passed`
- If no errors occur, the retry wrapper returns on the first attempt with no delay

**Why this matters:**
Without jitter, all clients retry at the exact same intervals after a shared failure (e.g., Azure OpenAI regional outage recovery), causing a thundering herd that re-triggers the outage. Full jitter spreads retries across the delay window. The `Retry-After` header override is critical — it's the service telling you exactly when capacity returns.

### Task B: Circuit Breaker

**Goal:** Build a circuit breaker that transitions through CLOSED, OPEN, and HALF_OPEN states, preventing wasted calls to a known-failing dependency.

**What to do:**
1. Open `lab/src/reliability_patterns.py`
2. Look at the `CircuitBreaker` class (line ~152) — it tracks `failure_count`, transitions to OPEN when failures hit the threshold, and transitions to HALF_OPEN after `recovery_timeout` elapses
3. Look at `task_b()` (line ~215) — it runs 10 calls against a `flaky_tool` that fails every other call, with `failure_threshold=3` and `recovery_timeout=5.0`
4. Run: `uv run reliability --task B`

**Expected result:**
- Calls alternate between success and failure until 3 failures trip the circuit:
  ```
  Call 1: state=closed, result={'result': 'Success for: query-0'}
  Call 2: Failure recorded (1/3): Simulated failure on call 2
  Call 2: state=closed, result=None
  Call 3: state=closed, result={'result': 'Success for: query-2'}
  Call 4: Failure recorded (2/3): Simulated failure on call 4
  Call 5: state=closed, result={'result': 'Success for: query-4'}
  Call 6: Failure recorded (3/3): Simulated failure on call 6
         Circuit TRIPPED OPEN — will recover in 5.0s
         Waiting for recovery timeout (5.0s)...
  ```
- After the recovery timeout, the circuit moves to HALF_OPEN and allows a probe call
- A final stats table shows total calls, successes, failures, and final state

**Why this matters:**
When a downstream API is failing consistently, retrying every call wastes time and resources. A circuit breaker fails fast during outages, giving the dependency time to recover. In agent systems, this prevents cascading failures — if your RAG database is down, the agent should fall back immediately instead of timing out on every tool call.

### Task C: Fallback Chain

**Goal:** Implement a three-tier fallback that degrades gracefully from primary model to constrained model to local cache.

**What to do:**
1. Open `lab/src/reliability_patterns.py`
2. Look at `task_c()` (line ~255) — it defines three tiers: `try_primary()` (full model call), `try_fallback()` (same model with simplified prompt and `max_tokens=100`), and `try_cache()` (local dict lookup)
3. The cache is pre-populated with one entry: `"What is Azure OpenAI?"`. The other two prompts have no cache entry, so they rely on live model calls
4. Run: `uv run reliability --task C`

**Expected result:**
- All three prompts succeed at Tier 1 (primary) under normal conditions:
  ```
  Query: What is Azure OpenAI?
    Tier used: Primary
  ┌────────────────────────────────────────────────────────────┐
  │ Azure OpenAI Service provides REST API access to OpenAI's │
  │ models including GPT-4o, GPT-4o-mini...                   │
  └────────────────────────────────────────────────────────────┘

  Query: Explain the circuit breaker pattern in 2 sentences.
    Tier used: Primary
  ...
  ```
- To test fallback behavior, temporarily change `try_primary` to raise an exception — the chain should fall through to Fallback or Cache tiers

**Why this matters:**
A degraded response is almost always better than no response. In production, the primary model might be rate-limited or the deployment might be down. The fallback chain trades quality for reliability — a shorter answer from a constrained prompt beats a timeout. Pre-populating a cache with answers to your most common queries provides a safety net even when all live models are unavailable.

### Task D: Output Guardrails

**Goal:** Validate LLM outputs against a JSON schema and observe how the model self-corrects when validation fails.

**What to do:**
1. Open `lab/src/reliability_patterns.py`
2. Look at `EXPECTED_SCHEMA` (line ~333) — it requires `action` (enum: approve/reject/escalate), `confidence` (number 0-1), and `reasoning` (string)
3. Look at `validate_output()` (line ~344) — it strips markdown fencing, parses JSON, checks required fields, types, enums, and numeric ranges
4. Look at `task_d()` (line ~379) — it sends three code review scenarios and retries up to 3 times if validation fails
5. Run: `uv run reliability --task D`

**Expected result:**
- Three code review prompts are evaluated. Most pass on the first attempt:
  ```
  Review request: A user submitted a code change that adds eval()...
    Attempt 1: Valid
  ┌───────────┬──────────────────────────────────────────────────┐
  │ action    │ reject                                           │
  │ confidence│ 0.95                                             │
  │ reasoning │ Using eval() on user input is a code injection...│
  └───────────┴──────────────────────────────────────────────────┘

  Review request: A user wants to add a logging statement...
    Attempt 1: Valid
  ┌───────────┬──────────────────────────────────────────────────┐
  │ action    │ approve                                          │
  │ confidence│ 0.9                                              │
  │ reasoning │ Adding latency logging is a standard practice... │
  └───────────┴──────────────────────────────────────────────────┘
  ```
- If the model returns invalid JSON or a missing field, the output shows the validation error and retries
- After 3 failed attempts, escalation to human review is triggered

**Why this matters:**
LLM outputs are untrusted input. Without schema validation, an agent acting on malformed JSON will crash or — worse — silently do the wrong thing. The retry-with-feedback pattern works because models correct schema violations ~95% of the time on the second attempt. The 3-attempt cap with human escalation ensures you never loop indefinitely on a genuinely broken prompt.

---

## Key Takeaways

1. Agent reliability compounds per step — a 5-step agent at 95% per-step
   is only 77% end-to-end. Every reliability pattern you add buys back
   significant overall success rate.
2. Retry + circuit breaker + fallback covers most transient failures.
   Output guardrails cover most semantic failures.
3. Always set per-task timeouts and token budgets to prevent runaway agents.
4. Idempotency is non-negotiable for any agent that performs side effects.
5. Dead letter queues turn total failures into investigation opportunities.

---

## Further Reading

- Microsoft: Transient fault handling patterns
- Martin Fowler: Circuit Breaker pattern
- AWS: Exponential Backoff and Jitter
- OWASP: LLM Top 10 (Module 25)
