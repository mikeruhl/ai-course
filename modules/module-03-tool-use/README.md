# Module 3: Function Calling / Tool Use

**Chapter 1 — Foundations**

---

## Learning Objectives

By the end of this module you will:

- Understand the tool-calling protocol at the wire level
- Implement the complete agent loop from scratch — no frameworks
- Write tool schemas that guide the model to correct tool selection
- Handle parallel tool calls, tool errors, and loop termination
- Have built a real working agent that answers questions about the filesystem

---

## Prerequisites

- [Module 1](../module-01-llm-primitive/README.md) and [Module 2](../module-02-prompt-engineering/README.md) complete
- Azure OpenAI resources from Module 1 still running

---

## Concepts

### The Core Primitive

Tool use is the bridge between LLM reasoning and real-world action.

Everything in agentic AI — from LangChain agents to AutoGen conversations
to Semantic Kernel planners — is built on top of this single primitive.
Before you touch any framework, you need to understand the raw loop.

### The Protocol

1. You send the model a list of available tools as JSON schemas
2. The model decides which tool to call (or none) and returns structured JSON
3. You execute the tool call in your code
4. You return the result to the model as a tool result message
5. The model decides: call another tool, or give a final answer
6. Repeat until the model returns a regular text response

**The model never executes code. It only requests execution.**

This is the security boundary. You — the application — decide whether
to actually run a tool call. This is where you enforce authorization,
rate limiting, sandboxing, and approval gates.

### The Wire Format

**Your request to the API includes tools:**
```json
{
  "messages": [...],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "read_file",
        "description": "Read the contents of a file at the given path.",
        "parameters": {
          "type": "object",
          "properties": {
            "path": {
              "type": "string",
              "description": "Absolute or relative file path"
            }
          },
          "required": ["path"]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

**The model responds with a tool call:**
```json
{
  "choices": [{
    "finish_reason": "tool_calls",
    "message": {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {
          "id": "call_abc123",
          "type": "function",
          "function": {
            "name": "read_file",
            "arguments": "{\"path\": \"./README.md\"}"
          }
        }
      ]
    }
  }]
}
```

**You execute the tool and return the result:**
```json
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "<file contents here>"
}
```

**Key details:**
- `finish_reason: "tool_calls"` — model wants to call a tool (not done yet)
- `finish_reason: "stop"` — model is giving a final answer (done)
- Tool arguments are **a JSON-encoded string**, not an object — always `json.loads()`
- `tool_call_id` must match exactly — the model tracks which result goes with which call
- The assistant message with `tool_calls` must be appended to the conversation
  *before* appending the tool results

### Tool Schema Design

The description field is the most important part of the schema.
The model selects tools based primarily on the description.

**Bad description:**
```json
"description": "Gets files"
```

**Good description:**
```json
"description": "Read the full contents of a file on the local filesystem.
Use this when you need to examine the code or content of a specific file.
Do NOT use this to list directory contents — use list_directory instead."
```

Notice the "Do NOT use this for X" pattern. Telling the model when
*not* to call a tool reduces mistakes and unnecessary calls.

### Parallel Tool Calls

A single model response can request multiple tool calls simultaneously:

```json
"tool_calls": [
  {"id": "call_1", "function": {"name": "read_file", "arguments": "{...}"}},
  {"id": "call_2", "function": {"name": "read_file", "arguments": "{...}"}},
  {"id": "call_3", "function": {"name": "search_files", "arguments": "{...}"}}
]
```

Your loop must:
1. Execute all tool calls (optionally in parallel with `asyncio.gather`)
2. Return all results before the next model call
3. Results can be returned in any order — the `tool_call_id` is the link

### Error Handling

When a tool fails:

```python
try:
    result = execute_tool(name, args)
except Exception as e:
    result = f"Error: {e}"  # Return error as string, don't raise
```

Return the error as the tool result. Let the model handle it.
The model might retry with corrected arguments, use a different tool,
or tell the user it can't complete the task.

### Termination and Safety

Without guards, an agent can loop indefinitely. Always implement:

```python
MAX_ITERATIONS = 10
iteration = 0

while iteration < MAX_ITERATIONS:
    iteration += 1
    response = call_model(messages)
    if finish_reason == "stop":
        break
    # handle tool calls...

if iteration >= MAX_ITERATIONS:
    return "Error: agent exceeded maximum iterations"
```

### tool_choice Parameter

| Value | Behavior |
|---|---|
| `"auto"` | Model decides whether to call a tool (default, use this) |
| `"required"` | Model must call at least one tool |
| `"none"` | Model must not call any tools |
| `{"type": "function", "function": {"name": "..."}}` | Force a specific tool |

For most agent loops: `"auto"`. Use `"required"` when you know the model
should always use a tool (e.g., the first step of a structured pipeline).

---

## Azure Setup

No new Terraform needed. Uses the Azure OpenAI resources from Module 1.

---

## Lab Setup

```bash
cd modules/module-03-tool-use/lab
cp .env.example .env
uv sync
```

---

## Lab Tasks

### Task 1: Implement the agent loop

**Goal:** Build the core tool-calling agent loop from scratch — no frameworks, just the raw API protocol.

**What to do:**
1. Open `lab/src/agent.py` and locate the `run_agent()` function starting at line 196
2. Review the function skeleton — it has TODO comments at lines 218-242 for each implementation step
3. Implement the loop logic:
   - Line 218: Call `httpx.post(BASE_URL, headers=HEADERS, json=payload, timeout=30)` where `payload` contains `messages`, `model: MODEL`, `tools: TOOLS`, and `tool_choice: "auto"`
   - Line 225: Extract `message` from `response.json()["choices"][0]["message"]` and `finish_reason` from `response.json()["choices"][0]["finish_reason"]`
   - Line 229: Append the assistant message to `messages` with `messages.append(message)`
   - Line 231: If `finish_reason == "stop"`, return `message["content"]`
   - Line 233: If `finish_reason == "tool_calls"`, iterate over `message["tool_calls"]`, parse `call["function"]["arguments"]` with `json.loads()`, execute via `call_tool(name, args)`, and append each tool result as `{"role": "tool", "tool_call_id": call["id"], "content": result}`
4. Do not modify the tool implementations at lines 131-177 (`tool_list_directory`, `tool_read_file`, `tool_search_files`) or the `call_tool()` dispatcher at line 180
5. Run:
   ```bash
   cd modules/module-03-tool-use/lab
   uv run python src/agent.py
   ```

**Expected result:**
```
╭─ Query: What files are in the modules directory? ─╮
╰────────────────────────────────────────────────────╯

--- Iteration 1 ---
Tool call: list_directory({"path": "modules"})
Result: dir  module-01-llm-primitive
        dir  module-02-prompt-engineering
        dir  module-03-tool-use

--- Iteration 2 ---
Finish reason: stop

╭─ Final Answer ─╮
│ The modules directory contains three subdirectories:
│ - module-01-llm-primitive
│ - module-02-prompt-engineering
│ - module-03-tool-use
╰────────────────╯
```
- The loop should terminate when `finish_reason == "stop"`
- Each iteration prints the tool call name, arguments, and result
- The final answer incorporates information gathered from tool calls

**Why this matters:**
Every agent framework (LangChain, Semantic Kernel, AutoGen) wraps this exact loop. Building it raw ensures you understand the protocol — message ordering, `tool_call_id` matching, finish reason branching — so you can debug framework issues instead of being blocked by them.

### Task 2: Fix the tool schemas

**Goal:** Demonstrate that tool description quality directly controls the model's tool selection accuracy.

**What to do:**
1. Open `lab/src/agent.py` and locate the `TOOLS` list starting at line 56
2. Review the three tool definitions (lines 56-112). Each has intentionally weak descriptions:
   - `list_directory` at line 61: `"Lists files."` (weak)
   - Parameter description at line 67: `"The path."` (weak)
   - `read_file` at line 78: `"Reads a file."` (weak)
   - Parameter description at line 84: `"Path to file."` (weak)
   - `search_files` at line 95: `"Searches files."` (weak)
   - Parameter descriptions at lines 101 and 105: `"Where to search."` and `"What to search for."` (weak)
3. Run the agent with these weak descriptions on a few queries and observe incorrect tool selection:
   ```bash
   cd modules/module-03-tool-use/lab
   uv run python src/agent.py
   ```
4. Improve the descriptions. Add: what the tool does, when to use it, when NOT to use it, and what the parameters mean. For example, `list_directory` should clarify it lists immediate children of a directory (not recursive), and `read_file` should note it returns file contents as text (not for listing directories). Include "Do NOT use this for X" clauses.
5. Re-run the same queries and compare tool selection decisions.

**Expected result:**
```
Before (weak descriptions):
  Query: "Find all Python files in modules/"
  Tool called: read_file({"path": "modules/"})     ← WRONG tool
  Result: Error: path is a directory, not a file

After (improved descriptions):
  Query: "Find all Python files in modules/"
  Tool called: search_files({"directory": "modules/", "pattern": "*.py"})  ← CORRECT
  Result: modules/module-01-llm-primitive/lab/src/main.py
          modules/module-02-prompt-engineering/lab/src/prompts.py
          ...
```
- Wrong tool selections should decrease after improving descriptions
- The "Do NOT use this for X" pattern in descriptions is particularly effective

**Why this matters:**
In production agentic systems, the model picks tools based on descriptions, not implementation. A vague description is like a poorly documented API — callers will misuse it. Writing precise tool descriptions is the tool-use equivalent of writing a good system prompt.

### Task 3: Handle parallel tool calls

**Goal:** Extend the agent loop to process multiple tool calls returned in a single model response.

**What to do:**
1. Open `lab/src/agent.py` and locate the `run_agent()` function (line 196)
2. In your tool-call handling section (around line 233), modify the code to iterate over all items in `message["tool_calls"]` — it's a list, not a single object, so use a `for` loop
3. Add a print statement before the loop showing the count:
   ```python
   console.print(f"Tool calls in this response: {len(message['tool_calls'])}")
   ```
4. Execute all tool calls in the loop and append all results to `messages` before the next API call (before the loop continues back to line 215)
5. Modify the test query at line 262 to trigger parallel calls, such as: *"Read the README files from both module-01 and module-02"*
6. Run:
   ```bash
   cd modules/module-03-tool-use/lab
   uv run python src/agent.py
   ```

**Expected result:**
```
--- Iteration 1 ---
Tool calls in this response: 2
Tool call: read_file({"path": "modules/module-01-llm-primitive/README.md"})
Tool call: read_file({"path": "modules/module-02-prompt-engineering/README.md"})
Result [call_abc]: # Module 1: The LLM as a Primitive...
Result [call_def]: # Module 2: Prompt Engineering at Staff Level...

--- Iteration 2 ---
Finish reason: stop
```
- Multi-file queries should show `Tool calls in this response: 2` or `3`
- All tool results must be appended with their matching `tool_call_id` before the next API call

**Why this matters:**
Parallel tool calls reduce round-trips to the model. A 3-file read that takes 3 iterations serially completes in 1 iteration with parallel calls. In production, this directly impacts agent latency — and you can execute the tool calls concurrently with `asyncio.gather` for even more speedup.

### Task 4: Add error resilience

**Goal:** Make the agent robust to tool failures so errors become information, not crashes.

**What to do:**
1. Open `lab/src/agent.py` and locate the `call_tool()` function at line 180
2. Wrap the tool dispatch logic (lines 182-189) in a `try/except` block that catches all exceptions and returns the error as a formatted string (e.g., `f"Error: {e}"`)
3. Note that argument validation already exists:
   - `_safe_path()` at line 123 checks for path traversal and raises `ValueError` if the path is outside `SAFE_ROOT`
   - `tool_read_file()` at line 146 checks file size against `MAX_FILE_SIZE_BYTES` (defined at line 119)
   - Tool implementations at lines 131-177 already return error strings for common failures
4. Ensure your try/except in `call_tool()` catches exceptions from `_safe_path()` and the tool implementations
5. Test with edge cases by modifying the query at line 262:
   ```bash
   cd modules/module-03-tool-use/lab
   uv run python src/agent.py
   ```
   Use queries like: *"Read the file /etc/passwd"*, *"Read the file nonexistent.txt"*, *"Read a .pyc file"*

**Expected result:**
```
--- Iteration 1 ---
Tool call: read_file({"path": "/etc/passwd"})
Result: Error: Path '/etc/passwd' is outside the allowed directory

--- Iteration 2 ---
Tool call: read_file({"path": "nonexistent.txt"})
Result: Error: file does not exist: nonexistent.txt

--- Iteration 3 ---
Finish reason: stop
Final Answer: I was unable to read those files. /etc/passwd is outside the
allowed directory, and nonexistent.txt does not exist.
```
- Tool errors return as strings, never raise exceptions that crash the loop
- The model receives the error message and adapts — it may retry, try a different tool, or explain the failure to the user
- Path traversal attempts are blocked by `_safe_path()`

**Why this matters:**
Agents in production encounter file-not-found, permission denied, timeouts, and malformed arguments constantly. If a tool exception kills the loop, the user gets nothing. Returning errors as tool results lets the model reason about failures and give useful responses — the same pattern used by Claude Code, Copilot, and every production agent.

### Task 5: The main challenge — codebase Q&A

**Goal:** Use your completed agent to answer multi-step questions about a real codebase, observing how the model chains tool calls.

**What to do:**
1. Open `lab/src/agent.py` and locate the `QUERIES` list at line 251 and the commented-out loop at line 267
2. Review the four queries already defined in the `QUERIES` list (lines 251-256):
   - *"How many Python files are in the modules directory? List their paths."*
   - *"What Python dependencies does module-02 use? Check its pyproject.toml."*
   - *"Find all files that contain the word 'terraform' in their name."*
   - *"What are the learning objectives of module-01? Check its README."*
3. Uncomment lines 267-270 (the `for query in QUERIES:` loop) and comment out the single test query at lines 262-264
4. Optionally, add message logging to observe the full conversation history — insert `console.print(json.dumps(messages, indent=2))` at line 244 (just before the `return` statement) to dump the message array
5. Run all queries:
   ```bash
   cd modules/module-03-tool-use/lab
   uv run python src/agent.py
   ```

**Expected result:**
```
Query: "How many Python files are in the modules directory?"
  Iteration 1: search_files({"directory": "modules", "pattern": "*.py"})
  Iteration 2: stop
  Answer: There are 5 Python files in the modules directory:
    - modules/module-01-llm-primitive/lab/src/main.py
    - modules/module-02-prompt-engineering/lab/src/prompts.py
    - modules/module-02-prompt-engineering/lab/src/harness.py
    - modules/module-02-prompt-engineering/lab/src/injection_demo.py
    - modules/module-03-tool-use/lab/src/agent.py

Query: "What Python dependencies does module-02 use?"
  Iteration 1: read_file({"path": "modules/module-02-prompt-engineering/lab/pyproject.toml"})
  Iteration 2: stop
  Answer: module-02 depends on httpx, python-dotenv, and rich.
```
- Study how the model picks tools: does it search first or list directories first?
- Note multi-step reasoning: for "learning objectives," it must list the directory, find the README, then read it
- Compare the message array length across queries — more steps means more messages

**Why this matters:**
This is the core pattern behind code assistants, internal knowledge bots, and autonomous debugging agents. The model decomposes a question into tool calls, gathers evidence, and synthesizes an answer. Understanding this message flow — and its failure modes — is the foundation for every agentic system you will build.

---

## Conceptual Checkpoints

1. Why must the assistant message (with `tool_calls`) be appended to the
   conversation *before* the tool result messages?
2. What happens if you forget to include `tool_call_id` in the tool result?
3. Why should tool errors be returned as strings rather than raised as exceptions?
4. What does `tool_choice: "required"` do, and when would you use it?
5. Trace through the message array after a 3-tool-call sequence. Draw it out.
   How many messages are in the array before the model gives its final answer?

---

## Resources

- [Azure OpenAI function calling guide](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/function-calling)
- [OpenAI parallel function calling docs](https://platform.openai.com/docs/guides/function-calling/parallel-function-calling)

---

**Next:** [Module 04 — Async Agent Loops + Streaming](../module-04-async-streaming/README.md)
