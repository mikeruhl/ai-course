# Module 06: ReAct Agent (from Scratch)

**Chapter 2 — Agentic Patterns**

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

**Goal:** Implement the full ReAct loop using only text prompts and output parsing — no tool_calls API — to understand the pattern at its most fundamental level.

**What to do:**
1. Open `lab/src/react_agent.py`
2. Implement `execute_tool()` (line 106): parse action lines like `search[telephone invention]` using regex or string splitting, extract tool name and argument, dispatch to `tool_search()` or `tool_lookup()`
3. Implement `parse_react_output()` (line 125): extract `Thought:` and `Action:` from the model's text output, detect `finish[...]` as the termination signal, return `(thought, action, is_finished)` tuple
4. Complete the TODO blocks inside `run_react_prompt()` (line 183): call `chat()` with current messages (temperature=0), parse output with `parse_react_output()`, call `execute_tool()` to get observations, append assistant message and observation (as user message) to history
5. Run:
   ```bash
   cd modules/module-06-react-agent/lab
   uv run python src/react_agent.py
   ```

**Expected result:**
- The console prints a step-by-step trace like:
  ```
  --- Step 1 ---
  Thought: I need to find out who invented the telephone. I'll search for it.
  Action: search[telephone]
  Observation: The telephone was invented by Alexander Graham Bell. Bell was awarded the first patent for the electric telephone in 1876.
  --- Step 2 ---
  Thought: I now know Bell invented it and the patent year was 1876. I can finish.
  Action: finish[Alexander Graham Bell invented the telephone and received the patent in 1876.]
  Final answer: Alexander Graham Bell invented the telephone and received the patent in 1876.
  Total tokens used: ~350
  ```
- The agent reaches a `finish` action in 3-5 steps without parsing errors
- Each step shows a Thought before every Action — no silent tool calls

**Why this matters:**
Text-parsing ReAct works with any model, including ones without tool_calls support. Understanding this raw loop is essential because production agents often need custom parsing for non-standard model outputs. The format also maps directly to the original Yao et al. paper.

### Task 2: ReAct via Native tool_calls + CoT System Prompt

**Goal:** Implement the same research agent using the structured tool_calls API, then compare token cost and output consistency against the text-parsing approach.

**What to do:**
1. Open `lab/src/react_agent.py`
2. Complete the TODO blocks inside `run_react_native()` (line 317): call `chat_with_tools()` with `messages`, `tools=TOOLS_NATIVE`, temperature=0, extract message and finish_reason from response
3. Dispatch tool calls (line 361): for each `tool_call` in `message.get("tool_calls", [])`, extract function name and parse arguments JSON, call `tool_search(args["query"])` if name is "search" or `tool_lookup(args["term"])` if name is "lookup"
4. Append tool result messages (line 375): create message dict with `role="tool"`, `tool_call_id=tool_call["id"]`, `content=observation`, append to messages list
5. After both Task 1 and Task 2 run, update the comparison table at line 440 with actual token counts
6. Run the same command — both approaches execute sequentially:
   ```bash
   uv run python src/react_agent.py
   ```

**Expected result:**
- The native approach output looks like:
  ```
  --- Step 1 ---
  Thought: The question asks who invented the telephone and when the patent was received. I should search for this.
  Action: search({"query": "telephone"})
  Observation: The telephone was invented by Alexander Graham Bell...
  --- Step 2 ---
  Final answer: Alexander Graham Bell invented the telephone and received patent 174,465 in 1876.
  Total tokens: ~280
  ```
- The comparison table shows native tool_calls using ~20% fewer tokens (no format instructions overhead)
- The native approach produces non-empty `content` (reasoning) on at least 80% of tool call steps

**Why this matters:**
Native tool_calls eliminate parsing brittleness and give structured arguments, but the reasoning trace in `content` is not guaranteed — the model may skip it. Knowing both approaches lets you choose: text parsing when you need guaranteed reasoning traces, native when you need reliability and structured arguments.

### Task 3: Multi-Source Research Agent

**Goal:** Build an agent that must consult multiple simulated sources and produce a cited synthesis, demonstrating how ReAct handles multi-source research workflows.

**What to do:**
1. Open `lab/src/research_agent.py`
2. In `run_research_agent()` (line 226), complete the TODO at line 263: call `chat_with_tools(messages, RESEARCH_TOOLS, temperature=0, max_tokens=800)`, extract message and finish_reason from response
3. Append the assistant message to messages (line 273)
4. Dispatch tool calls (line 286): for each tool_call, extract function name and parse arguments JSON. Call `tool_search_wikipedia(args["query"])`, `tool_search_encyclopedia(args["query"])`, or `tool_follow_link(args["title"])` based on name. Each returns a dict with 'source', 'title', 'content'.
5. Track sources (line 292): append `result.get("source", name)` to `sources_consulted` list
6. Append tool result message (line 298): create message with `role="tool"`, `tool_call_id=tool_call["id"]`, `content=json.dumps(result)`
7. Run:
   ```bash
   uv run python src/research_agent.py
   ```
   (This runs both Task 3 and Task 4 demos)

**Expected result:**
- The agent calls at least two different search tools before producing its answer:
  ```
  --- Step 1 ---
  Thought: I need to research WWI causes. I'll start with Wikipedia.
  Action: search_wikipedia({"query": "first world war causes"})
  Observation: The First World War (1914–1918) had multiple causes...
  --- Step 2 ---
  Thought: I have one source. The rules require at least two. Let me check the encyclopedia.
  Action: search_encyclopedia({"query": "world war 1 triggers"})
  Observation: SOURCE: Oxford Reference. The specific triggers of WWI...
  --- Step 3 ---
  Answer: The causes of WWI included... [Wikipedia] ...three triggering events were... [Encyclopedia]
  Sources consulted: ['Wikipedia', 'Encyclopedia']
  ```
- The final answer contains at least two inline source citations (e.g., `[Wikipedia]`, `[Encyclopedia]`)
- Running with 3 different history questions, the agent always cites at least two sources

**Why this matters:**
Production RAG agents must synthesize across sources and cite them. This task forces the agent to plan its source coverage before answering. The multi-source requirement also demonstrates how the system prompt can enforce behavioral constraints on tool usage patterns.

### Task 4: Growing Scratchpad

**Goal:** Extend the research agent to maintain a persistent scratchpad across questions, demonstrating how agents preserve conclusions without re-searching.

**What to do:**
1. Open `lab/src/research_agent.py`
2. In `run_research_agent()` at line 244, complete the scratchpad injection TODO: if `scratchpad` is not empty, append notes to `system_content` using format `system_content += "\n\nPrevious session notes:\n" + "\n".join(f"- {note}" for note in scratchpad)`
3. At line 307, complete the scratchpad update TODO: create a new note summarizing the question and answer. Use format `note = f"Q: {question[:60]}... -> Key facts: {final_answer[:150]}..."`. Append note to `updated_scratchpad` (which is a copy of input scratchpad).
4. The `__main__` block (line 340) already runs a two-question sequence — Q1 asks about the Constitution's architect, Q2 asks "What other documents did that person write?" without naming anyone
5. Run:
   ```bash
   uv run python src/research_agent.py
   ```

**Expected result:**
- After Q1, the scratchpad contains a note like:
  ```
  Scratchpad after Q1:
    - Q: Who was the primary architect of the US Constitution? -> Key facts: James Madison is often called the 'Father of the Constitution'...
  ```
- During Q2, the agent uses the scratchpad to identify "that person" as James Madison without re-searching Q1:
  ```
  --- Step 1 ---
  Thought: From my previous notes, "that person" is James Madison. I should search for his other writings.
  Action: search_wikipedia({"query": "james madison writings"})
  ```
- The final scratchpad has 2 notes after both questions complete
- The agent correctly answers Q2 using scratchpad context

**Why this matters:**
The scratchpad pattern is how production agents maintain memory across turns without passing full conversation history. It trades token cost (growing context) for accuracy (preserved conclusions). This is a prerequisite for the summarization techniques in Module 08.

### Task 5: ReAct vs Plain Tool Loop Benchmark

**Goal:** Quantify the accuracy and token cost difference between ReAct and a plain tool loop across 10 tasks of varying complexity.

**What to do:**
1. Open `lab/src/benchmark.py`
2. Implement `run_plain_tool_loop()` (line 183): create messages with system prompt "You are a helpful assistant. Answer questions accurately." and user question. Loop: call `chat_with_tools(messages, BENCHMARK_TOOLS)`, if finish_reason is "tool_calls" extract function name and arguments, call `tool_search(args["query"])`, append tool result message with role="tool", continue. Track tool_call_count and accumulate total_tokens from each response. Return `(final_answer, tool_call_count, total_tokens)`.
3. Implement `run_react_tool_loop()` (line 196): same structure but use system prompt that requires reasoning before tool calls (e.g., "You are a helpful assistant. Before calling any tool, explain your reasoning in your response content."). Return same tuple.
4. Both functions use `BENCHMARK_TOOLS` (single `search` tool, line 161) and `tool_search()` (line 153) for dispatch
5. Run:
   ```bash
   uv run python src/benchmark.py
   ```

**Expected result:**
- A comparison table prints with all 10 tasks:
  ```
  ┌──────┬────────────┬──────────────┬─────────────┬──────────────┬──────────────┬─────────────┬──────────────┬────────────────┐
  │ Task │ Type       │ Plain Correct│ Plain Calls │ Plain Tokens │ ReAct Correct│ ReAct Calls │ ReAct Tokens │ Token Overhead │
  ├──────┼────────────┼──────────────┼─────────────┼──────────────┼──────────────┼─────────────┼──────────────┼────────────────┤
  │ 1    │ multi-hop  │ N            │ 1           │ 320          │ Y            │ 2           │ 580          │ 1.8x           │
  │ 2    │ single-hop │ Y            │ 1           │ 250          │ Y            │ 1           │ 410          │ 1.6x           │
  │ ...  │            │              │             │              │              │             │              │                │
  └──────┴────────────┴──────────────┴─────────────┴──────────────┴──────────────┴─────────────┴──────────────┴────────────────┘

  Multi-hop accuracy:
    Plain: 1/4
    ReAct: 3/4
  Overall token overhead: 1.7x
  ```
- ReAct shows higher accuracy on multi-hop tasks (IDs 1, 3, 6, 9) where chaining facts is required
- Single-hop tasks show similar accuracy for both, with ReAct using more tokens
- After running, fill in the observation comment block at the top of `benchmark.py` (line 13) with your findings

**Why this matters:**
This is the data you need to justify (or reject) ReAct in a production system. The tradeoff is concrete: ReAct costs ~1.5-2x more tokens but catches multi-hop reasoning failures that plain tool loops miss. For single-hop tasks, ReAct is pure overhead. Production systems should route simple queries to plain loops and reserve ReAct for complex reasoning chains.

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
