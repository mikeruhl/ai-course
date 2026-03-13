# Module 07: Planning Patterns

**Chapter 2 — Agentic Patterns**

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

**Goal:** Implement the Plan-and-Execute pattern to separate planning from execution, demonstrating how a global plan reduces wasted steps compared to reactive agents.

**What to do:**
1. Open `lab/src/plan_execute.py`
2. Implement `PlannerAgent.create_plan()` (line ~157): call the model with `PLANNER_SYSTEM` prompt and the goal, parse the JSON array response into a list of step strings. Handle JSON parse failures with a fallback 3-step plan.
3. Implement `PlannerAgent.revise_plan()` (line ~169): build a prompt showing the original plan, completed steps with results (first 200 chars each), and remaining steps. Call the model with `REVISE_PLANNER_SYSTEM`, parse the returned JSON array as the updated remaining steps.
4. Implement `ExecutorAgent.execute_step()` (line ~204): run a tool-calling loop with `EXECUTOR_TOOLS` (max 5 iterations per step), dispatch to `tool_search()` or `tool_write_section()` based on function name, return the final content when `finish_reason == "stop"`.
5. Complete the orchestrator TODO blocks in `run_plan_execute()` (line ~236): wire up `executor.execute_step()`, call `planner.revise_plan()` every 2 steps, track revisions.
6. Run:
   ```bash
   cd modules/module-07-planning-patterns/lab
   uv run python src/plan_execute.py
   ```

**Expected result:**
- Phase 1 prints an initial plan with 5+ steps:
  ```
  Phase 1: Planning
  Initial Plan:
    1. Search for underlying causes of WWI (MAIN acronym)
    2. Search for the assassination of Franz Ferdinand
    3. Search for the alliance cascade and mobilization
    4. Write section: Underlying Causes
    5. Write section: The Assassination
    6. Write section: The Alliance Cascade
    7. Review and assemble final outline
  ```
- Phase 2 executes each step, printing tool calls and results:
  ```
  Executing step 1: Search for underlying causes of WWI
  Result: WWI causes include: nationalism (especially in the Balkans)...
  Executing step 2: Search for the assassination of Franz Ferdinand
  Result: The assassination of Archduke Franz Ferdinand in Sarajevo on 28 June 1914...
  Checking if plan needs revision...
  Plan revised — updated remaining steps.
  ```
- Phase 3 shows written sections stored by `tool_write_section()` in the `written_sections` dict
- The planner revises at least once (the `revised_count` increments)
- The `written_sections` dict contains at least 3 entries

**Why this matters:**
Plan-and-Execute is the standard pattern for multi-step workflows where order matters (report writing, data pipelines, deployment sequences). The re-planning loop is critical — it handles the reality that execution reveals information that invalidates the original plan. This is how production document-generation and research agents work.

### Task 2: Reflexion for Code Generation

**Goal:** Implement the Reflexion loop — generate, evaluate, critique, retry — for code generation with automated test evaluation.

**What to do:**
1. Open `lab/src/reflexion.py`
2. Implement `generate_code()` (line ~135): call the model with `GENERATOR_SYSTEM` prompt and the problem description, return the text content (function definition only).
3. Implement `refine_code()` (line ~146): call the model with `REFLEXION_SYSTEM` prompt and a user message containing the problem, previous code, and error feedback. Return the corrected function code.
4. Implement `evaluate_code()` (line ~163): combine `code` + `test_harness` into a temp `.py` file, run it with `subprocess.run([sys.executable, tmpfile], capture_output=True, text=True, timeout=10)`. Return `(True, "All tests passed")` if `returncode == 0` and stdout contains `"ALL TESTS PASSED"`, otherwise return `(False, stderr_or_stdout)`. Handle `subprocess.TimeoutExpired`.
5. Complete the TODO blocks in `run_reflexion()` (line ~181): call `generate_code()` on first attempt, `refine_code()` on subsequent attempts, and `evaluate_code()` after each generation.
6. Run:
   ```bash
   uv run python src/reflexion.py
   ```

**Expected result:**
- Each problem shows attempt-by-attempt progress:
  ```
  Problem 1: reverse_words
  Attempt 1/3
   1 │ def reverse_words(s: str) -> str:
   2 │     return ' '.join(s.split()[::-1])
  PASSED on attempt 1

  Problem 2: flatten
  Attempt 1/3
   1 │ def flatten(nested: list) -> list:
   2 │     result = []
   3 │     for item in nested:
   4 │         if isinstance(item, list):
   5 │             result.extend(item)
   6 │         else:
   7 │             result.append(item)
   8 │     return result
  PASSED on attempt 1

  Problem 3: count_vowels
  Attempt 1/3
  ...
  PASSED on attempt 1
  ```
- The summary shows pass rate: `Problems passed: 3/3` (or at least 2/3)
- If a problem fails on attempt 1, the error feedback is printed and the model self-corrects on attempt 2 or 3
- On at least 2 of 3 problems, Reflexion either passes on first attempt or self-corrects within 3 attempts

**Why this matters:**
Reflexion is the go-to pattern for quality-critical single outputs (code, documents, SQL queries). The key insight is that automated evaluation (running tests, linting, type-checking) is cheap and objective compared to LLM-as-judge. Production code generation agents almost always include a test-execution feedback loop.

### Task 3: 2-Level LATS

**Goal:** Implement simplified LATS — generate candidate approaches, score them, execute the best one — to see how branching avoids naive first-choice errors.

**What to do:**
1. Open `lab/src/lats.py`
2. Implement `generate_approaches()` (line ~66): call the model with `APPROACH_GENERATOR_SYSTEM` (format the `{n}` placeholder) and the question, parse the JSON array response into a list of approach strings. Provide fallback approaches if parsing fails.
3. Implement `score_approach()` (line ~97): call the model with `SCORER_SYSTEM` and a user message containing the question and approach, parse the JSON response for `{"score": int, "reason": str}`. Default to `{"score": 5, "reason": "Could not evaluate"}` on parse failure.
4. Implement `execute_approach()` (line ~122): call the model with `EXECUTOR_SYSTEM` and a user message containing the question and selected approach, return the text content.
5. Complete the TODO blocks in `run_lats()` (line ~138): wire up the three phases — generate, score, execute.
6. Run:
   ```bash
   uv run python src/lats.py
   ```

**Expected result:**
- Three trick questions are tested. For the sheep puzzle, output looks like:
  ```
  Phase 1: Generating 3 approaches...
    1. Approach 1: Take the numbers literally — subtract 9 from 17
    2. Approach 2: Look for wordplay — "all but 9" means 9 remain
    3. Approach 3: Consider whether "die" changes ownership or just count

  Phase 2: Scoring approaches...
  ┌───┬────────┬──────────────────────────────────────────────────────────┬──────────────────────────────────────┐
  │ # │ Score  │ Approach                                               │ Reason                               │
  ├───┼────────┼──────────────────────────────────────────────────────── ┼──────────────────────────────────────┤
  │ 1 │ 3/10   │ Take the numbers literally — subtract 9 from 17...     │ Falls for the trick in the wording   │
  │ 2 │ 9/10   │ Look for wordplay — "all but 9" means 9 remain...     │ Correctly identifies the language... │
  │ 3 │ 5/10   │ Consider whether "die" changes ownership...            │ Partially relevant but overthinks    │
  └───┴────────┴────────────────────────────────────────────────────────┴──────────────────────────────────────┘

  Phase 3: Selected approach (score 9/10): Look for wordplay...
  Phase 4: Executing...
  Final Answer: 9 sheep are left. The trick is that "all but 9 die" means 9 survive...
  Total model calls: 5 (3 scoring + 1 generation + 1 execution)
  ```
- The scorer ranks the wordplay-aware approach highest for the sheep puzzle
- For "pound of feathers vs pound of gold," the scorer identifies that both weigh a pound (or notes the troy ounce distinction)

**Why this matters:**
LATS prevents the common failure mode where an agent commits to a naive first interpretation and never recovers. The 2-level simplification (generate-score-execute) captures most of the benefit at 5 model calls instead of the exponential cost of full tree search. Use this when the first approach matters and evaluation is cheap.

### Task 4: Document Writing Agent (Plan-and-Execute)

**Goal:** Combine Plan-and-Execute with a Reflexion critique pass to build a full document-writing pipeline, demonstrating how production agents compose multiple patterns.

**What to do:**
1. Create `lab/src/doc_writer.py` (this file does not yet exist — build it using the patterns from `plan_execute.py` and `reflexion.py` as reference)
2. Implement an agent that, given a topic:
   - Plans an outline using a planner LLM call (reuse the `PlannerAgent` pattern from `plan_execute.py`)
   - Researches each section using a simulated `research(query)` tool
   - Writes each section using a `write_section(title, content)` tool
   - Assembles the full document from written sections
   - Runs one Reflexion critique pass: call the LLM as a critic on the full draft, then call it again to revise based on the critique
   - Prints each phase as it progresses
3. Test topic: *"The role of artificial intelligence in modern software engineering"* (3 sections, ~150 words each)
4. Run:
   ```bash
   uv run python src/doc_writer.py
   ```

**Expected result:**
- Phase-by-phase console output:
  ```
  Phase 1: Planning outline...
    1. Research AI in code generation
    2. Research AI in testing and QA
    3. Research AI in operations/DevOps
    4. Write section: AI-Assisted Code Generation
    5. Write section: AI in Testing
    6. Write section: AI in Operations
    7. Assemble and review

  Phase 2: Executing plan...
  [step-by-step research and writing output]

  Phase 3: Critique...
  Critique: The introduction lacks a clear thesis statement. Section 2 does not mention specific tools.

  Phase 4: Revision...
  [revised document output]

  Document complete — 3 sections, revised once.
  ```
- The agent produces a document with at least 3 sections
- The critique identifies at least one concrete improvement (not generic praise)
- The final document differs from the initial draft

**Why this matters:**
Production AI writing systems are never single-shot. They combine planning (outline), execution (research + drafting), and self-critique (Reflexion). This task demonstrates the composition pattern: Plan-and-Execute for structure, Reflexion for quality. Most commercial document-generation products use exactly this architecture.

### Task 5: Token Cost Comparison

**Goal:** Run the same task through three patterns and measure token cost, providing concrete data for pattern selection decisions.

**What to do:**
1. Create `lab/src/cost_comparison.py` (this file does not yet exist — build it using the tool loop, ReAct, and Reflexion patterns from prior tasks)
2. Implement three agent functions that all answer the same question: *"Research and answer: What were the three main causes of World War I? For each cause, give one concrete example."*
   - `run_plain_loop()`: plain tool loop (no reasoning instructions), returns `(answer, calls, input_tokens, output_tokens)`
   - `run_react()`: ReAct with CoT system prompt, returns the same tuple
   - `run_reflexion()`: generate answer, critique once, revise, returns the same tuple
3. Use the same simulated `search` tool and knowledge base as `plan_execute.py`
4. Print a `rich.Table` comparing all three approaches: input tokens, output tokens, total tokens, model calls, and a placeholder column for manual quality rating (1-5)
5. Run:
   ```bash
   uv run python src/cost_comparison.py
   ```

**Expected result:**
- A comparison table:
  ```
  ┌────────────────┬──────────────┬───────────────┬──────────────┬───────┬─────────┐
  │ Pattern        │ Input Tokens │ Output Tokens │ Total Tokens │ Calls │ Quality │
  ├────────────────┼──────────────┼───────────────┼──────────────┼───────┼─────────┤
  │ Plain loop     │ 450          │ 180           │ 630          │ 2     │ ___/5   │
  │ ReAct          │ 820          │ 350           │ 1170         │ 3     │ ___/5   │
  │ Reflexion      │ 1100         │ 520           │ 1620         │ 3     │ ___/5   │
  └────────────────┴──────────────┴───────────────┴──────────────┴───────┴─────────┘
  ```
- All three approaches produce an answer about WWI causes
- You have concrete token numbers showing the cost multiplier of each pattern
- Add a comment at the top of the file with your conclusion: is the quality improvement worth the token overhead?

**Why this matters:**
Pattern selection without cost data is guessing. This exercise produces the exact numbers you need for a production cost-benefit analysis. A pattern that improves accuracy by 10% but costs 3x more tokens may not be justified at scale. Always benchmark before committing to a complex pattern in production.

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
