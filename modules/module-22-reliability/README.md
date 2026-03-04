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

### Tasks

| Task | Command | What you'll build |
|---|---|---|
| A | `uv run reliability --task A` | Retry with exponential backoff + jitter |
| B | `uv run reliability --task B` | Circuit breaker with state transitions |
| C | `uv run reliability --task C` | Fallback chain (primary → cheaper → cache) |
| D | `uv run reliability --task D` | Output guardrails with schema validation |

### Task A: Retry with Backoff

Implement the retry pattern with full jitter. Visualize the backoff schedule,
then make a real API call through the retry wrapper.

### Task B: Circuit Breaker

Build a circuit breaker with CLOSED/OPEN/HALF_OPEN states. Test it against
a simulated flaky tool that fails every other call. Observe state transitions.

### Task C: Fallback Chain

Implement a three-tier fallback: primary model → constrained model → local
cache. Each tier degrades gracefully when the previous tier fails.

### Task D: Output Guardrails

Validate LLM outputs against a JSON schema. When validation fails, retry
with the error message appended. Observe how the model self-corrects.

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
