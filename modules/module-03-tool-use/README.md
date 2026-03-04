# Module 3: Function Calling / Tool Use

**Week 1 · Phase 1 — Foundations**

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

In `src/agent.py`, implement the `run_agent()` function.
The skeleton is provided. You need to:

1. Loop until `finish_reason == "stop"` or max iterations
2. On `tool_calls`: execute each tool, append results, continue
3. On `stop`: return the final message content
4. Handle errors from tool execution gracefully

Do not modify the tool implementations — focus on the loop logic.

### Task 2: Fix the tool schemas

The starter file has intentionally weak tool descriptions.
Run the agent on the provided test queries. Note where it makes
wrong tool selection decisions or uses wrong arguments.

Improve the descriptions and re-run. Measure whether decisions improve.

### Task 3: Handle parallel tool calls

The starter loop handles one tool call at a time.
Modify it to handle multiple simultaneous tool calls.

Verify it works by adding a `print` statement that shows how many
tool calls were in each response. Some queries should trigger 2–3.

### Task 4: Add error resilience

Modify `call_tool()` to:
1. Catch all exceptions and return them as error strings
2. Validate arguments before executing (e.g., path traversal check)
3. Add a per-tool timeout

Test with edge cases:
- A path that doesn't exist
- A binary file (read_file should handle gracefully)
- A very large file (implement a size cap)

### Task 5: The main challenge — codebase Q&A

Using your completed agent, answer these questions about the course
repository itself:

1. *"How many Python files are in the modules directory?"*
2. *"What dependencies does module-02 use?"*
3. *"Find all files that contain the word 'terraform' and list their paths."*
4. *"What is the learning objective of module-01?"*

Log the full message history for each. Study how the model reasons
through multi-step problems.

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

**Next:** [Week 2 — Structured Outputs, Async Agents, Streaming](../../weeks/week-02.md)
