# Module 19: LangGraph — Stateful Agent Graphs

## Overview

LangChain built linear chains: A → B → C. That works for pipelines. It does not work for agents.

An agent that loops — calling tools, observing results, calling more tools — needs **cycles**. Python graphs with cycles are not chains. LangGraph exists to fill that gap.

LangGraph is a library from the LangChain team that lets you define agent behavior as a **directed graph** where nodes are Python functions and edges are transitions between them. Cycles are a first-class feature. So is persistent state, conditional branching, and human-in-the-loop interrupts.

---

## 1. Why LangGraph

### The problem with linear chains

A chain like `prompt → llm → output_parser` works when the computation is a straight line. But a ReAct agent looks like this:

```
think → act → observe → think → act → observe → ... → respond
```

That "think → act → observe → think" loop is a **cycle**. You cannot represent a cycle as a chain without awkward workarounds.

### When to use LangGraph

Use LangGraph when you need any of these:

| Need | LangGraph Feature |
|---|---|
| Agent loops (ReAct, etc.) | Cycles in the graph |
| Conditional routing (tool call vs done) | Conditional edges |
| Multi-turn memory | Checkpointing + thread IDs |
| Human approval gates | interrupt_before / interrupt_after |
| Visualization / debugging | graph.get_graph().draw_ascii() |
| Parallel branches | Fan-out / fan-in with Send API |

### When NOT to use LangGraph

If your pipeline is truly linear and stateless, a plain Python function is simpler. LangGraph adds structure — that structure pays off when you need its features, and adds overhead when you don't.

---

## 2. Core Abstractions

### State

The **State** is a TypedDict (or Pydantic model) that represents everything the agent knows at any point in time. It flows through every node in the graph.

```python
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    tool_calls_remaining: int
```

Key insight: `add_messages` is a **reducer**. Instead of replacing `state["messages"]` with a new list, it appends new messages to the existing list. This is how LangGraph accumulates conversation history across nodes.

Without a reducer, every node would have to return the full messages list. With a reducer, each node returns only the new messages, and LangGraph merges them.

### Node

A **Node** is a Python function with signature:

```python
def my_node(state: AgentState) -> dict:
    ...
    return {"messages": [new_message]}  # partial state update
```

Nodes return **partial state updates** — only the keys they want to change. LangGraph merges the return value into the current state using the reducer for each key.

### Edge

An **Edge** connects two nodes. There are three kinds:

1. **Fixed edge**: always go from A to B.
   ```python
   graph.add_edge("node_a", "node_b")
   ```

2. **Conditional edge**: a function decides which node comes next.
   ```python
   graph.add_conditional_edges("node_a", my_router_function)
   ```

3. **Entry / exit**: `START` is the virtual entry point, `END` is the virtual exit.
   ```python
   graph.add_edge(START, "agent")
   graph.add_edge("tools", END)
   ```

### Graph

```python
from langgraph.graph import StateGraph, START, END

graph_builder = StateGraph(AgentState)
graph_builder.add_node("agent", agent_node)
graph_builder.add_node("tools", tool_node)
graph_builder.add_edge(START, "agent")
graph_builder.add_conditional_edges("agent", should_continue)
graph_builder.add_edge("tools", "agent")  # cycle!

graph = graph_builder.compile()
```

`.compile()` validates the graph and returns a `CompiledGraph` you can invoke.

### Checkpointer

A **Checkpointer** persists graph state to storage after every step. This enables:

- **Multi-turn conversations**: resume a thread after the user sends another message
- **Human-in-the-loop**: pause execution, wait for human input, resume
- **Fault tolerance**: if the agent process crashes, state is not lost

```python
from langgraph.checkpoint.memory import MemorySaver

graph = graph_builder.compile(checkpointer=MemorySaver())

# Each conversation gets a thread_id
config = {"configurable": {"thread_id": "user-123"}}
result = graph.invoke({"messages": [HumanMessage("Hello")]}, config=config)
```

---

## 3. The ReAct Loop as a StateGraph

```
START
  │
  ▼
[agent_node] ─────── no tool calls ──────────────────► END
      │
   tool calls present
      │
      ▼
[tool_node]
      │
      └──────────────────────────────────────────────► [agent_node]
```

This loop is the core of a ReAct agent. The `agent_node` calls the LLM. The LLM decides whether to call tools. If yes, `tool_node` executes them and returns observations. The loop continues.

The routing logic lives in `should_continue`:

```python
def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"   # route to tool_node
    return END           # done
```

`add_conditional_edges("agent", should_continue)` wires this up: after every execution of `agent_node`, LangGraph calls `should_continue` with the current state and routes to whichever node the function returns.

---

## 4. Full Graph Construction Example

```python
from langchain_openai import AzureChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

llm = AzureChatOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    azure_deployment="gpt-4o-mini",
    api_version="2024-02-01",
)

tools = [search_knowledge_base, calculate]
llm_with_tools = llm.bind_tools(tools)

def agent_node(state: AgentState) -> dict:
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}

def should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END

graph_builder = StateGraph(AgentState)
graph_builder.add_node("agent", agent_node)
graph_builder.add_node("tools", ToolNode(tools))
graph_builder.add_edge(START, "agent")
graph_builder.add_conditional_edges("agent", should_continue)
graph_builder.add_edge("tools", "agent")

graph = graph_builder.compile()
```

`ToolNode` is a pre-built node from `langgraph.prebuilt` that:
1. Reads `tool_calls` from the last message
2. Executes each tool
3. Returns `ToolMessage` objects with the results

You could implement your own tool node, but `ToolNode` handles edge cases (parallel tool calls, error catching) correctly.

---

## 5. Conditional Routing in Detail

`add_conditional_edges` takes:
- The source node name
- A routing function `(state) -> str`
- Optional: a dict mapping return values to node names

```python
# Simple form: routing function returns node names directly
graph.add_conditional_edges("agent", should_continue)
# LangGraph uses the return value as the target node name.
# Return END to finish the graph.

# Explicit mapping form (useful for clarity or renaming):
graph.add_conditional_edges(
    "agent",
    should_continue,
    {
        "tools": "tools",      # if "tools" returned → go to tools node
        "end": END,            # if "end" returned → terminate
    }
)
```

---

## 6. Human-in-the-Loop (HITL)

Human-in-the-loop means pausing graph execution and waiting for a human to review or approve something before continuing.

```
[agent_node]
      │
      ▼
[review_node]  ◄── PAUSE HERE — human reviews
      │
      ▼  (after human approves)
[execute_node]
      │
      ▼
   END
```

### How interrupts work

Compile with `interrupt_before`:

```python
graph = graph_builder.compile(
    checkpointer=MemorySaver(),
    interrupt_before=["execute_node"],  # pause before this node runs
)
```

When LangGraph reaches `execute_node`, it saves the current state to the checkpointer and **raises an interrupt**. The graph is now paused.

To inspect the current state:

```python
config = {"configurable": {"thread_id": "my-thread"}}
snapshot = graph.get_state(config)
print(snapshot.values)  # see current state
```

To resume (after human approves):

```python
# Resume by invoking with None as input (state already saved)
graph.invoke(None, config=config)
```

To abort (human rejected):

```python
# Update state to mark as rejected, then let graph route to END
graph.update_state(config, {"approved": False})
graph.invoke(None, config=config)
```

### Why HITL is a reliability pattern (not just a UX feature)

Agents can be wrong. For irreversible actions (delete records, send emails, charge a payment), the cost of a wrong action is high. HITL is a safety net: the agent proposes, the human disposes. Once you trust the agent's reliability in a specific context, you can remove the interrupt.

---

## 7. Checkpointing and Threads

### Thread model

Every conversation is a **thread**. Threads are identified by a `thread_id` you provide:

```python
config = {"configurable": {"thread_id": "conversation-42"}}

# Turn 1
graph.invoke({"messages": [HumanMessage("My name is Alice")]}, config=config)

# Turn 2 — graph remembers "My name is Alice" from turn 1
graph.invoke({"messages": [HumanMessage("What did I just tell you?")]}, config=config)
```

This works because the checkpointer saves state after every step. On the second invocation, LangGraph loads the saved state for `thread_id="conversation-42"` and appends the new message.

### MemorySaver vs PostgresSaver

| Checkpointer | Use Case |
|---|---|
| `MemorySaver` | Development, testing (in-memory, lost on restart) |
| `SqliteSaver` | Local persistence, single-machine |
| `PostgresSaver` | Production (requires `langgraph-checkpoint-postgres`) |

For production on Azure, use PostgresSaver with Azure Database for PostgreSQL.

### State inspection

```python
# Get current state snapshot
snapshot = graph.get_state(config)
print(snapshot.values)      # dict: current state values
print(snapshot.next)        # tuple: which nodes execute next

# Get state history (all checkpoints for this thread)
for state in graph.get_state_history(config):
    print(state.values, state.metadata)
```

---

## 8. LangGraph vs Raw Python

| Aspect | Raw Python | LangGraph |
|---|---|---|
| Cycles | Manual while loop | First-class graph cycles |
| State management | You manage the dict | TypedDict with reducers |
| Checkpointing | You implement | Pluggable checkpointers |
| Visualization | None | `.draw_ascii()`, `.draw_mermaid_png()` |
| HITL | You implement pause/resume | `interrupt_before` built-in |
| Parallel branches | Manual asyncio | `Send` API |
| Debugging | Print statements | LangSmith tracing |

**The tradeoff**: LangGraph requires you to structure your agent as a graph. This adds some rigidity — you can't just write imperative code. But the benefits (checkpointing, visualization, HITL) are significant for production agents.

**Rule of thumb**: Use raw Python for prototypes and simple linear agents. Use LangGraph when you need checkpointing, HITL, or complex routing that would otherwise require a custom state machine.

---

## 9. Graph Visualization

```python
# ASCII art (works in any terminal)
print(graph.get_graph().draw_ascii())

# Mermaid diagram (renders in notebooks, GitHub, etc.)
print(graph.get_graph().draw_mermaid())

# PNG (requires graphviz)
graph.get_graph().draw_mermaid_png(output_file_path="agent_graph.png")
```

Example ASCII output for the ReAct loop:

```
         +-----------+
         | __start__ |
         +-----------+
               *
               *
               *
          +-------+
          | agent |
          +-------+
         *         .
        *            .
       *               .
 +-------+           +---------+
 | tools |           | __end__ |
 +-------+           +---------+
     *
     *
  (back to agent)
```

---

## 10. Lab Tasks

The lab is split across two files: `langgraph_agent.py` (core graph building) and `hitl_agent.py` (human-in-the-loop).

### Task A — Basic StateGraph

In `src/langgraph_agent.py`:

1. Implement `agent_node` to call `llm_with_tools.invoke(state["messages"])` and return the result.
2. Replace `llm_with_tools = None` with `llm.bind_tools(TOOLS)`.
3. Build the graph: `StateGraph(AgentState)` → add nodes → add edges → `compile()`.
4. In `main()`, invoke the graph with a user query and print the final response.

Expected result: the agent calls `search_knowledge_base` when asked about LangGraph topics.

### Task B — Conditional Routing

Implement `should_continue`:
- If the last message in `state["messages"]` has `tool_calls` and that list is non-empty → return `"tools"`.
- Otherwise → return `END`.

Wire it up with `add_conditional_edges("agent", should_continue)`.

Test: ask a question that requires a tool call, and one that doesn't. Verify routing.

### Task C — Checkpointing (Multi-Turn)

Implement `build_graph_with_memory()`:
1. Create `MemorySaver()` checkpointer.
2. Compile the graph with `checkpointer=MemorySaver()`.
3. Create a `config` with `thread_id="test-thread"`.
4. Invoke with "My favorite programming language is Python."
5. Invoke again with "What programming language did I just mention?"
6. Verify the agent correctly recalls from the previous turn.

### Task D — Graph Visualization

Implement `print_graph_structure(graph)`:
1. Call `graph.get_graph().draw_ascii()` and print it.
2. Print a summary of nodes and edges.

Compare the output to the ASCII diagram in this README.

### HITL Tasks (hitl_agent.py)

**Task 1**: Define `agent_node` that calls the LLM with `delete_records` and `send_notification` tools bound. Set `pending_action` in the state when a tool call is detected.

**Task 2**: Compile the graph with `interrupt_before=["execute_node"]`. The graph should pause before executing dangerous actions.

**Task 3**: Implement `approval_node` that uses `rich.prompt.Confirm` to ask the human whether to proceed. Set `state["approved"]` accordingly.

**Task 4**: After human approval, resume the graph with `graph.invoke(None, config=config)`. If rejected, update state to skip execution and route to END.

---

## Setup

```bash
cd modules/module-19-langgraph/lab
uv venv && uv pip install -e .
cp .env.example .env
# Fill in your Azure OpenAI credentials

# Run tasks
uv run python src/langgraph_agent.py --task A
uv run python src/langgraph_agent.py --task B
uv run python src/langgraph_agent.py --task C
uv run python src/langgraph_agent.py --task D
uv run python src/hitl_agent.py
```

---

## Key Takeaways

1. **State flows through nodes** — each node receives the full state, returns a partial update. Reducers merge updates.
2. **Conditional edges enable routing** — the routing function sees the current state and returns a node name. This is how you implement ReAct "stop when done".
3. **Checkpointers enable persistence** — thread_id isolates conversations. State survives between invocations.
4. **Interrupts enable HITL** — `interrupt_before` pauses execution at a node. Resume with `invoke(None, config)`.
5. **The graph IS the architecture** — visualizing it gives you a complete picture of the agent's possible execution paths.
