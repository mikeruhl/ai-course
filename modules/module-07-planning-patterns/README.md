# Module 07: Planning Patterns

**Phase 2 — Agentic Patterns | Week 3**

## Prerequisites

- Module 06 (ReAct Agent) complete
- Azure OpenAI resource running (reuses module-01 infrastructure)
- Python 3.11+, `uv` installed

---

## Learning Objectives

By the end of this module you will be able to:

1. Implement Plan-and-Execute: separate the planning concern from the execution concern into distinct agent calls
2. Implement Reflexion: agent generates output, critiques it, and improves it in a loop
3. Explain LATS (Language Agent Tree Search) conceptually and implement a 2-level version
4. Choose the right pattern for a given task type based on concrete criteria
5. Measure and compare token costs across patterns — make cost-informed design decisions

---

## Concepts

### 1. Plan-and-Execute

The core idea: instead of one agent that reasons and acts simultaneously (ReAct), split the work into two distinct agents with different jobs:

- **Planner agent**: given the goal, creates a numbered, ordered list of steps
- **Executor agent**: takes each step from the plan and executes it, one at a time

```
User: "Write a report on climate change impacts on agriculture"

Planner output:
  1. Search for overview of climate change effects on global agriculture
  2. Search for specific crop yield statistics (wheat, rice, corn)
  3. Search for geographic regions most affected
  4. Search for adaptation strategies
  5. Write introduction section
  6. Write impact analysis section
  7. Write adaptation strategies section
  8. Write conclusion
  9. Review and revise the full draft

Executor: runs step 1, gets results, runs step 2, etc.
Planner (optional): after step 4, reviews results and may add/remove steps
```

**Why this is better than ReAct for long tasks:**

ReAct is reactive — it decides the next action based on the last observation. It can get stuck in local loops ("I searched for X, got partial info, search for X again") and does not have a global view of what needs to be done.

Plan-and-Execute has a global view from the start. The planner can reason about the full task structure before any execution happens. The executor can focus entirely on doing one thing well, without worrying about what comes next.

**The re-planning loop**: After execution, the planner can review what was accomplished and revise the remaining steps. This handles cases where execution reveals that the original plan was wrong.

```
Planner → Plan → Executor (step 1) → Observation → Planner (revise?) → Executor (step 2) → ...
```

### 2. Reflexion (Shinn et al. 2023)

Reflexion is a pattern for tasks where the output quality can be evaluated and the agent should try to improve its own work.

The loop:

```
1. Agent generates an attempt (e.g., a code solution)
2. Critic evaluates the attempt (run the code, or use LLM-as-judge)
3. Agent receives the critique + original attempt
4. Agent generates an improved attempt
5. Repeat up to N times or until the output passes
```

Key design decisions:

**Who is the critic?** Options:
- A program (run the code and check stderr/exit code — objective, cheap)
- An LLM (evaluate subjective quality, consistency, style — flexible but expensive)
- A human (highest quality but not automatable)

**What does the critique contain?** The most effective critiques are specific:
- "The function fails on empty input — you don't check if the list is None"
- vs. "This code has a bug" (too vague for useful improvement)

**When to stop?** Options:
- Fixed N iterations (simple, predictable cost)
- Until the evaluation passes a threshold (unbounded cost, but stops when done)
- Hybrid: max N with early exit if evaluation passes (recommended)

**Token cost**: Reflexion with 3 iterations = 3x the initial generation cost, plus 3x the evaluation cost. Budget accordingly. For expensive generation (code, long documents), 2-3 iterations is usually the sweet spot.

### 3. LATS: Language Agent Tree Search (Zhou et al. 2023)

LATS treats the agent's decision space as a tree. At each decision point, the agent generates multiple candidate next steps (branching), evaluates each candidate (scoring), and pursues the most promising branch.

```
Root: Initial state
├── Branch A: "search for climate data"      (score: 0.8)
│   ├── Branch A1: "focus on temperature"    (score: 0.7)
│   └── Branch A2: "focus on precipitation" (score: 0.9)  ← pursue this
├── Branch B: "search for economic impact"   (score: 0.6)
└── Branch C: "search for historical data"   (score: 0.5)
```

This is essentially a best-first search over the space of agent trajectories.

**When LATS is worth it:**
- Search-heavy problems where the first obvious path is frequently wrong
- Problems with clear evaluation functions (math correctness, code that must compile)
- Research tasks where you want the best answer, not just a good answer

**When LATS is not worth it:**
- Tasks with obvious single-path solutions (LATS will waste tokens exploring alternatives)
- Latency-sensitive tasks (branching multiplies latency)
- Tasks without a good evaluation function (you can't tell which branch is better)

**Token cost**: 3 branches × 5 steps = 15 agent calls vs 5 for a linear agent. For 3-level LATS with 3 branches each: 3^3 = 27 branches evaluated. Always budget.

A practical simplification: **2-level LATS** — generate 3 candidate approaches at the start, evaluate each with a quick scoring call, then execute the best one. This captures most of LATS's benefit at a fraction of the cost.

### 4. Choosing the Right Pattern

| Task Characteristics | Recommended Pattern |
|---|---|
| Interactive, unpredictable, observation-driven | ReAct |
| Long multi-step workflow, order matters | Plan-and-Execute |
| Quality-critical single output (code, documents) | Reflexion |
| Search-heavy, multiple valid paths | LATS |
| Simple single-tool lookups | Plain tool loop |
| Very latency-sensitive | Plain tool loop or async ReAct |

Real production systems often combine patterns. A document writing agent might use:
- Plan-and-Execute for the overall structure
- ReAct for each research step
- Reflexion for the final draft quality pass

### 5. Cost Implications

Token cost is a first-class engineering concern. A pattern that is 3x more accurate but 10x more expensive may not be the right choice.

Always measure:
- Tokens per task (input + output)
- Calls per task (latency × calls = total wall time)
- Quality improvement per token (is the extra cost worth it?)

For production systems, establish baselines before adopting complex patterns. A plain tool loop may be sufficient and significantly cheaper.

---

## Lab Setup

```bash
cd modules/module-07-planning-patterns/lab
cp .env.example .env
# Fill in .env with your Azure OpenAI values from module-01 terraform output
uv sync
uv run python src/plan_execute.py
```

---

## Lab Tasks

### Task 1: Plan-and-Execute

Implement the Plan-and-Execute pattern for a document research task.

In `src/plan_execute.py`:

1. `PlannerAgent.create_plan(goal)` — calls the model and returns a list of numbered steps
2. `ExecutorAgent.execute_step(step, context)` — executes one step using tools, returns result
3. `PlannerAgent.revise_plan(original_plan, completed_steps, observations)` — optionally revises remaining steps based on what's been learned
4. `run_plan_execute(goal)` — orchestrates the full loop

Test goal: *"Research and outline a 3-section report on the causes of World War I."*

The executor has access to: `search(query)`, `write_section(title, content)`.

Print the initial plan before execution starts. Print each step as it executes. After execution, print the final revised plan (if it changed).

**Checkpoint:** The planner creates a plan with at least 5 steps. The executor runs each step. The planner revises at least once during execution.

### Task 2: Reflexion for Code Generation

Implement the Reflexion loop for code generation with automated evaluation.

In `src/reflexion.py`:

1. `generate_code(problem)` — generates a Python solution
2. `evaluate_code(code, problem)` — runs the code in a subprocess, captures stdout/stderr, returns `(passed: bool, feedback: str)`
3. `run_reflexion(problem, max_attempts=3)` — generates code, evaluates, feeds errors back, tries again

Coding problems to test:
- "Write a function `reverse_words(s)` that reverses the order of words in a string"
- "Write a function `flatten(nested)` that flattens a nested list to one level"
- "Write a function `count_vowels(s)` that counts vowels (case-insensitive)"

For each problem, print attempt number, the generated code, whether it passed, and (if failed) the error feedback.

**Checkpoint:** On at least 2 of 3 problems, Reflexion either passes on first attempt or self-corrects within 3 attempts.

### Task 3: 2-Level LATS

Implement a simplified 2-level LATS for a reasoning task.

In `src/lats.py`:

1. `generate_approaches(question, n=3)` — generates 3 candidate problem-solving approaches
2. `score_approach(question, approach)` — uses the LLM to score the approach 0–10 (prompt: "Rate this approach for answering this question. Reply with a JSON: {score: int, reason: str}")
3. `execute_approach(question, approach)` — runs the selected approach to get an answer
4. `run_lats(question)` — generate candidates, score all, pick best, execute

Test question: *"A farmer has 17 sheep. All but 9 die. How many are left? Explain the trick in this question."*

Print all 3 candidate approaches with their scores. Show which one was selected and why. Print the final answer.

**Checkpoint:** The scoring correctly identifies a more nuanced approach over a naive literal interpretation approach (the "trick" is "all but 9 = 9 remaining").

### Task 4: Document Writing Agent (Plan-and-Execute)

Build a full document-writing agent using Plan-and-Execute.

In `src/doc_writer.py`:

Given a topic, the agent:
1. Plans an outline (sections, order)
2. Researches each section using simulated tools
3. Writes each section
4. Assembles the full document
5. Runs a single Reflexion critique pass on the full draft
6. Produces a final revised version

Tools available: `research(query)`, `write_section(title, content)`, `critique_document(document)`.

Test topic: *"The role of artificial intelligence in modern software engineering"* (3 sections, ~150 words each).

Print each phase (plan, research results, drafts, critique, final) as it progresses.

**Checkpoint:** The agent produces a document with at least 3 sections. The Reflexion critique identifies at least one concrete improvement. The final document differs from the initial draft.

### Task 5: Token Cost Comparison

Run the same complex task through three patterns and record total token usage.

In `src/cost_comparison.py`:

Task: *"Research and answer: What were the three main causes of World War I? For each cause, give one concrete example."*

Run this task with:
1. Plain tool loop (from Module 03 pattern)
2. ReAct (from Module 06)
3. Reflexion (1 critique pass)

For each, record: total input tokens, total output tokens, number of model calls, answer quality (manual 1–5 rating).

Print a rich table comparing all three. Add a comment with your conclusion: is the quality improvement worth the token overhead?

**Checkpoint:** All three approaches produce an answer. You have concrete token numbers to compare.

---

## Conceptual Checkpoints

- [ ] Can explain why Plan-and-Execute reduces wasted steps compared to ReAct for long tasks
- [ ] Can draw the Reflexion loop with critic and retry
- [ ] Can explain LATS and why branching factor × depth = exponential cost
- [ ] Can choose a pattern given a task description and justify the choice
- [ ] Can calculate expected token cost for N-iteration Reflexion vs plain generation

---

## Resources

- Reflexion: Language Agents with Verbal Reinforcement Learning (Shinn et al. 2023): https://arxiv.org/abs/2303.11366
- LATS: Language Agent Tree Search Unifies Reasoning, Acting, and Planning (Zhou et al. 2023): https://arxiv.org/abs/2310.04406
- Plan-and-Solve Prompting (Wang et al. 2023): https://arxiv.org/abs/2305.04091
- Tree of Thoughts (Yao et al. 2023): https://arxiv.org/abs/2305.10601
