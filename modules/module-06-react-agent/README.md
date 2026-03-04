# Module 06: ReAct Agent (from Scratch)

**Phase 2 — Agentic Patterns | Week 3**

## Prerequisites

- Module 01–05 complete
- Azure OpenAI resource running (reuses module-01 infrastructure)
- Python 3.11+, `uv` installed

---

## Learning Objectives

By the end of this module you will be able to:

1. Explain the ReAct pattern from the original Yao et al. (2022) paper — interleaving reasoning traces with actions
2. Implement ReAct from scratch in Python using two approaches: prompt-text parsing and native tool_calls
3. Articulate how ReAct differs from the raw tool-calling loop (explicit Thought before each Action, vs. silent model decisions)
4. Implement the scratchpad pattern and explain why it improves multi-step reasoning
5. Know when ReAct is worth the extra token cost and when a plain tool loop suffices

---

## Concepts

### 1. The ReAct Paper (Yao et al. 2022)

ReAct = **Re**ason + **Act**. The core insight is that language models perform significantly better on multi-step tasks when they are forced to write down their reasoning *before* each action, and then observe the result before reasoning again.

The loop:

```
Thought: I need to find out who wrote Hamlet. Let me search for it.
Action: search[Hamlet author]
Observation: Hamlet was written by William Shakespeare around 1600.
Thought: Now I know the author. I should check if the question asks for anything else.
Action: finish[William Shakespeare]
```

Why this works:

- Writing the thought forces the model to commit to a rationale, which reduces random tool selection
- The observation is anchored to the specific thought that triggered the action — the model sees the full chain
- Errors are visible: if an observation contradicts the thought, the next thought can correct course
- The trace is a debuggable artifact — you can see *why* the model did what it did

Compare to a plain tool loop: the model emits `tool_calls` with no visible reasoning. The decision is opaque. You get the right answer or you don't, but you can't tell which part of the reasoning was wrong.

### 2. Two Implementation Approaches

**Approach A: Prompt-text parsing (no tool_calls API)**

You craft a system prompt that tells the model to output a strict text format:

```
Thought: <reasoning here>
Action: tool_name[argument]
```

Your Python code parses the output line by line, identifies when an `Action:` line appears, executes the tool, and injects the result as `Observation: <result>` back into the conversation. The model sees the full transcript and continues.

This works with any model, including models that don't support the tool_calls API. It is also the format closest to the original ReAct paper.

Downsides: brittle parsing, model sometimes drifts from the format, harder to handle structured arguments.

**Approach B: Native tool_calls + CoT system prompt**

Azure OpenAI natively supports function calling. You instruct the model to "think step by step before calling any tool" in the system prompt. The model emits a `content` field (its reasoning) *followed by* `tool_calls` in the same assistant message. This is Chain-of-Thought + tool use.

Example message from the model:
```json
{
  "role": "assistant",
  "content": "The question asks for the population of Tokyo. I should look this up with the search tool rather than relying on potentially stale training data.",
  "tool_calls": [
    {
      "id": "call_abc",
      "type": "function",
      "function": { "name": "search", "arguments": "{\"query\": \"Tokyo population 2024\"}" }
    }
  ]
}
```

The `content` field is the Thought. The `tool_calls` is the Action. You execute, return the Observation, and the loop continues.

This is more reliable (structured arguments, no parsing), but the reasoning appears in `content` only when the model decides to write it — you can encourage this but not fully enforce it.

### 3. When ReAct Wins

ReAct outperforms a plain tool loop when:

| Scenario | Why ReAct helps |
|---|---|
| Multi-hop reasoning ("find X, then use X to find Y") | Model tracks the chain of dependencies in thoughts |
| First tool choice matters (wrong choice = wasted calls) | Explicit reasoning before action reduces wrong first choices |
| Intermediate results change the plan | Model writes new thought after each observation, adjusting strategy |
| Debugging is important | Full thought/action/observation trace is a readable audit log |

ReAct does NOT help (and costs more tokens) when:

| Scenario | Why plain tool loop is fine |
|---|---|
| Single-tool tasks ("what is the weather in Paris?") | No reasoning chain needed, one tool call suffices |
| Highly structured pipelines with known steps | Planning pattern is better (Module 07) |
| Latency-critical paths | Reasoning traces add output tokens = more latency |
| Simple lookup tasks | Overhead not worth it |

### 4. The Scratchpad Pattern

A scratchpad is a persistent record of the agent's reasoning chain that is prepended to the system prompt (or injected as an assistant message) at the start of each new session or task.

```python
scratchpad = []

# After each Thought/Action/Observation cycle:
scratchpad.append(f"Thought: {thought}")
scratchpad.append(f"Action: {action}")
scratchpad.append(f"Observation: {observation}")

# Inject into context for next call:
scratchpad_text = "\n".join(scratchpad)
system_prompt = BASE_SYSTEM_PROMPT + f"\n\nPrevious reasoning:\n{scratchpad_text}"
```

This helps for tasks that span multiple model calls where you don't want to pass the entire conversation history but do want the model to remember its prior conclusions.

Note: the growing scratchpad costs tokens. You will eventually need to summarize it (see Module 08).

### 5. Prompt-Only ReAct (Text Parsing Loop)

For models without tool_calls support, the full ReAct loop is implemented as:

```python
def react_step(messages: list[dict]) -> tuple[str, str | None, str | None]:
    """
    Make one model call and parse the output.
    Returns: (full_text, thought, action_line)
    action_line is None if the model has finished.
    """
    response = call_model(messages)
    text = response["choices"][0]["message"]["content"]

    thought = extract_between("Thought:", "Action:", text)
    action = extract_after("Action:", text)

    if action and action.strip().lower().startswith("finish"):
        return text, thought, None  # done

    return text, thought, action
```

The outer loop appends the model output plus the observation back into messages and calls again until the model emits a `finish` action or a step limit is reached.

---

## Lab Setup

```bash
cd modules/module-06-react-agent/lab
cp .env.example .env
# Fill in .env with your Azure OpenAI values from module-01 terraform output
uv sync
uv run python src/react_agent.py
```

---

## Lab Tasks

### Task 1: ReAct via Prompt Parsing

Implement the full ReAct loop using only text prompts and output parsing. No tool_calls API.

In `src/react_agent.py`, complete the `parse_react_output()` function and the `run_react_prompt()` loop.

The agent has three simulated tools:
- `search[query]` — returns a fake Wikipedia result for the query
- `lookup[term]` — looks up a specific term in the fake knowledge base
- `finish[answer]` — terminates the loop with a final answer

Test it with: *"Who invented the telephone and in what year?"*

Verify: print each Thought/Action/Observation on its own line as it happens. The output should read like a human reasoning trace.

**Checkpoint:** The agent reaches a `finish` action in 3–5 steps without any parsing errors.

### Task 2: ReAct via Native tool_calls + CoT System Prompt

Implement the same research agent using the tool_calls API (from Module 03) but with a system prompt that explicitly instructs the model to write its reasoning in the `content` field before every tool call.

In `src/react_native.py`, implement `run_react_native()`.

Compare the two approaches:
- Which produces more consistent output format?
- Which gives you more debuggable reasoning?
- Which uses fewer tokens for the same task?

Add a token counter and print total token usage for each approach on the same query.

**Checkpoint:** The native implementation produces non-empty `content` on at least 80% of tool calls when run with 5 different queries.

### Task 3: Multi-Source Research Agent

Build a research agent that, given a question, must consult *multiple simulated sources* and synthesize a final answer that cites each source.

Simulated tools:
- `search_wikipedia(query)` — returns a short paragraph
- `search_encyclopedia(query)` — returns a different source with different framing
- `follow_link(title)` — returns a related article
- `synthesize(sources)` — signals the agent to write a final answer

In `src/research_agent.py`, implement this agent using the approach from Task 2.

Test query: *"Explain the causes of the First World War and name three major triggering events."*

The agent must call at least two search tools before synthesizing. The final answer must contain at least two source citations.

**Checkpoint:** Running with 3 different history questions, the agent always cites at least two sources.

### Task 4: Growing Scratchpad

Extend the research agent from Task 3 to maintain a scratchpad across multiple user questions in the same session.

In `src/scratchpad_agent.py`:

1. After each question is answered, save the key conclusions to a `scratchpad: list[str]`
2. On the next question, inject the scratchpad as context at the top of the system prompt
3. Run a two-question sequence where question 2 depends on the answer to question 1

Example sequence:
- Q1: "Who was the primary architect of the US Constitution?"
- Q2: "What other documents did that person write?" (agent must recall the answer from Q1 via scratchpad)

Print the scratchpad contents before each call so you can see it growing.

**Checkpoint:** The agent correctly answers Q2 using information from the scratchpad without re-searching for Q1's answer.

### Task 5: ReAct vs Plain Tool Loop Benchmark

Run the same 10 reasoning tasks through two agents:
1. Plain tool loop (from Module 03 pattern — no reasoning trace in content)
2. ReAct with CoT system prompt

For each task, record:
- Number of tool calls made
- Whether the final answer was correct (manual check)
- Total tokens used

Print a comparison table using `rich`.

The 10 tasks are pre-loaded in `src/benchmark.py`. Three of them are multi-hop (require chaining 2+ facts). Three are single-hop. Four are ambiguous.

**Checkpoint:** ReAct makes fewer incorrect tool call choices on multi-hop tasks. Document what you observe in a comment at the top of `benchmark.py`.

---

## Conceptual Checkpoints

- [ ] Can explain why writing a thought before an action improves reasoning (not just recite it — explain the mechanism)
- [ ] Can describe the difference between Approach A (text parsing) and Approach B (native tool_calls) and when to use each
- [ ] Can explain the scratchpad pattern and its token cost tradeoff
- [ ] Can identify 3 task types where ReAct is not worth the overhead
- [ ] Can draw the Thought/Action/Observation loop from memory

---

## Resources

- ReAct: Synergizing Reasoning and Acting in Language Models (Yao et al. 2022): https://arxiv.org/abs/2210.03629
- Chain-of-Thought Prompting Elicits Reasoning in Large Language Models (Wei et al. 2022): https://arxiv.org/abs/2201.11903
- Azure OpenAI Function Calling: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/function-calling
- ReAct paper implementation notes: https://react-lm.github.io/
