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

### Setup

```bash
cd modules/module-19-langgraph/lab
uv venv && uv pip install -e .
cp .env.example .env
# Fill in your Azure OpenAI credentials
```

### Task A: Basic StateGraph

**Goal:** Build the core ReAct loop as a LangGraph StateGraph with an agent node, a tool node, and the cycle that connects them.

**What to do:**
1. Open `C:\Users\MiRuh\source\learn\ai-course\modules\module-19-langgraph\lab\src\langgraph_agent.py` and locate line 132. Replace `llm_with_tools = None` with `llm_with_tools = llm.bind_tools(TOOLS)`. The `TOOLS` list (line 122) contains `search_knowledge_base` and `calculate`.
2. Implement `agent_node` (line 142): call `llm_with_tools.invoke(state["messages"])` and return `{"messages": [response]}`. The `add_messages` reducer will append the response to the existing message list.
3. Build the graph at line 181: create `graph_builder = StateGraph(AgentState)`, add two nodes with `graph_builder.add_node("agent", agent_node)` and `graph_builder.add_node("tools", ToolNode(TOOLS))`, add edges: `graph_builder.add_edge(START, "agent")`, `graph_builder.add_conditional_edges("agent", should_continue)`, and `graph_builder.add_edge("tools", "agent")` (the cycle). Compile with `graph = graph_builder.compile()`.
4. Run:
   ```bash
   uv run python src/langgraph_agent.py --task A
   ```

**Expected result:**
```
Module 19 — LangGraph Agent — Task A
Query: What is LangGraph checkpointing and how does it work?

Query: What is LangGraph checkpointing and how does it work?
╭──── Agent Response ────╮
│ LangGraph checkpointing saves graph state to persistent storage after every  │
│ step. This enables pause/resume, multi-turn conversations, and HITL          │
│ interrupts. MemorySaver is for development; PostgresSaver for production.    │
╰────────────────────────╯
```
- The agent calls `search_knowledge_base` with `"checkpointing"` as the query, receives the knowledge base entry, and synthesizes a response.
- The `tools → agent` edge is the cycle that makes this a ReAct loop, not a linear chain.

**Why this matters:**
The cycle from `tools` back to `agent` is what differentiates LangGraph from a simple chain. Without it, the agent could call a tool once but never iterate. In production ReAct agents, this cycle runs 2-5 times on average per query. The `should_continue` function (Task B) is what prevents infinite cycling.

### Task B: Conditional Routing

**Goal:** Implement the routing function that decides whether the agent should call more tools or return a final answer.

**What to do:**
1. Open `C:\Users\MiRuh\source\learn\ai-course\modules\module-19-langgraph\lab\src\langgraph_agent.py` and locate `should_continue` (line 154).
2. Check `state["messages"][-1]` for a `tool_calls` attribute. If `hasattr(last_message, "tool_calls")` and `last_message.tool_calls` is non-empty, return `"tools"`. Otherwise, return `END`.
3. Wire it up with `add_conditional_edges("agent", should_continue)` (this should already be in your graph from Task A at line 181).
4. Test with two queries — one that triggers a tool call and one that does not:
   ```bash
   uv run python src/langgraph_agent.py --task B --query "What is a StateGraph?"
   uv run python src/langgraph_agent.py --task B --query "What is 2 + 2?"
   ```

**Expected result:**
```
Query: What is a StateGraph?
╭──── Agent Response ────╮
│ StateGraph is the main graph class in LangGraph. You add nodes with          │
│ add_node(), connect them with add_edge() or add_conditional_edges()...       │
╰────────────────────────╯

Query: What is 2 + 2?
╭──── Agent Response ────╮
│ 4                                                                            │
╰────────────────────────╯
```
- The first query routes through `agent → tools → agent → END` (tool call for knowledge base lookup).
- The second query routes through `agent → tools → agent → END` (tool call to `calculate`), or possibly `agent → END` if the LLM answers directly.

**Why this matters:**
`should_continue` is the exit condition for the ReAct loop. A bug here — always returning `"tools"` or always returning `END` — either causes infinite looping or prevents any tool use. In production, add a maximum iteration counter to `AgentState` and check it in `should_continue` as a safety net against infinite loops.

### Task C: Checkpointing (Multi-Turn)

**Goal:** Add persistent state via `MemorySaver` so the agent remembers previous messages across separate `.invoke()` calls.

**What to do:**
1. Open `C:\Users\MiRuh\source\learn\ai-course\modules\module-19-langgraph\lab\src\langgraph_agent.py` and locate `build_graph_with_memory()` (line 189).
2. Import `MemorySaver` from `langgraph.checkpoint.memory`. Create `checkpointer = MemorySaver()` and build the same graph as Task A/B, but compile it with `graph = graph_builder.compile(checkpointer=checkpointer)`.
3. Create a config dict: `config = {"configurable": {"thread_id": "demo-thread-1"}}`.
4. Return `(graph, config)`. The `main()` function (line 298) handles the two-turn test automatically when you run Task C.
5. Run:
   ```bash
   uv run python src/langgraph_agent.py --task C
   ```

**Expected result:**
```
Task C: Multi-turn conversation with MemorySaver

Turn 1:
Query: My favorite AI framework is LangGraph.
╭──── Agent Response ────╮
│ That's great! LangGraph is a powerful framework for building stateful agents.│
╰────────────────────────╯

Turn 2 (should recall Turn 1):
Query: What AI framework did I just mention?
╭──── Agent Response ────╮
│ You mentioned LangGraph as your favorite AI framework.                       │
╰────────────────────────╯
```
- Turn 2 correctly recalls "LangGraph" from Turn 1 because the checkpointer persists messages across invocations under the same `thread_id`.
- Without the checkpointer, Turn 2 would have no context and could not answer.

**Why this matters:**
Checkpointing is what makes LangGraph agents usable in real applications. Without it, every invocation starts from scratch. In production, replace `MemorySaver` (in-memory, lost on restart) with `PostgresSaver` backed by Azure Database for PostgreSQL. The `thread_id` isolates conversations — critical for multi-tenant systems where user A must not see user B's state.

### Task D: Graph Visualization

**Goal:** Print the graph structure as ASCII art and inspect the node/edge topology to verify your graph matches the expected ReAct architecture.

**What to do:**
1. Open `C:\Users\MiRuh\source\learn\ai-course\modules\module-19-langgraph\lab\src\langgraph_agent.py` and locate `print_graph_structure()` (line 217).
2. Call `ascii_art = compiled_graph.get_graph().draw_ascii()` and print the result.
3. Also print the node list and edge list for a complete summary: `g = compiled_graph.get_graph()`, then print `list(g.nodes.keys())` and `[(e.source, e.target) for e in g.edges]`.
4. Run:
   ```bash
   uv run python src/langgraph_agent.py --task D
   ```

**Expected result:**
```
Task D: Graph Structure
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

Nodes: ['__start__', 'agent', 'tools', '__end__']
Edges: [('__start__', 'agent'), ('tools', 'agent')]
```
- The conditional edge from `agent` to either `tools` or `__end__` appears as the branch in the ASCII art.
- The `tools → agent` edge is the cycle.

**Why this matters:**
Graph visualization is a debugging tool. When an agent misbehaves in production, the first question is "what path did it take through the graph?" The ASCII output works in any terminal and CI log. For richer visualization, `draw_mermaid_png()` generates diagrams for documentation. LangSmith provides runtime tracing of actual execution paths, not just the static graph.

### Task 1 (HITL): Agent Node with Dangerous Tool Detection

**Goal:** Build an agent node that detects when the LLM proposes a dangerous action and marks it for human review.

**What to do:**
1. Open `C:\Users\MiRuh\source\learn\ai-course\modules\module-19-langgraph\lab\src\hitl_agent.py` and locate `agent_node` (line 106).
2. Call `response = llm_with_tools.invoke(state["messages"])`. The LLM has `delete_records` and `send_notification` tools bound (line 89).
3. If `response.tool_calls` is non-empty, build a human-readable `pending_action` string from the tool call name and arguments. For example: `f"{tc.name}({', '.join(f'{k}={v!r}' for k, v in tc.args.items())})"` would produce `"delete_records(table='users', condition='active=False')"`.
4. Return `{"messages": [response], "pending_action": pending_action_str or None}`.
5. This task is tested as part of the full HITL flow:
   ```bash
   uv run python src/hitl_agent.py
   ```

**Expected result:**
```
╭── Module 19 — Human-in-the-Loop Agent Demo ──╮

User: Please delete all inactive users from the 'users' table (condition: active=False)

[Agent proposes] pending_action: delete_records(table='users', condition='active=False')
```
- The agent node identifies the dangerous tool call and populates `pending_action` in the state.
- The action is not yet executed — it is only proposed.

**Why this matters:**
Separating "propose" from "execute" is the foundation of safe agent design. In production, the `pending_action` string is what gets shown in a Slack approval message, a web UI modal, or an audit log. The clearer this string, the better the human can evaluate whether to approve.

### Task 2 (HITL): Graph with interrupt_before

**Goal:** Build the HITL graph topology and compile it with `interrupt_before=["execute_node"]` to pause execution before dangerous actions.

**What to do:**
1. Open `C:\Users\MiRuh\source\learn\ai-course\modules\module-19-langgraph\lab\src\hitl_agent.py` and locate `after_agent_route` (line 206) and `build_hitl_graph` (line 243).
2. Implement `after_agent_route`: check `state["messages"][-1].tool_calls`. If non-empty, return `"approval"`; otherwise return `END`.
3. In `build_hitl_graph`, create `checkpointer = MemorySaver()`, then build `StateGraph(HITLState)` with three nodes: `graph_builder.add_node("agent", agent_node)`, `graph_builder.add_node("approval", approval_node)`, `graph_builder.add_node("execute", execute_node)`. Add edges: `graph_builder.add_edge(START, "agent")`, `graph_builder.add_conditional_edges("agent", after_agent_route)`, `graph_builder.add_edge("approval", "execute")`, `graph_builder.add_conditional_edges("execute", after_execute_route)`.
4. Compile with `graph = graph_builder.compile(checkpointer=checkpointer, interrupt_before=["execute"])`.
5. Create `config = {"configurable": {"thread_id": "hitl-demo-1"}}` and return `(graph, config)`.
6. Run:
   ```bash
   uv run python src/hitl_agent.py
   ```

**Expected result:**
```
Graph Structure:
  __start__ → agent → (approval OR __end__) → execute → (agent OR __end__)

(Graph interrupted: GraphInterrupt)
Graph paused at: ('execute_node',)
Approved: True
```
- The graph pauses before `execute_node` runs, even though `approval_node` already captured the human's decision.
- The interrupt structure demonstrates the production pattern where approval happens asynchronously (via web UI or Slack).

**Why this matters:**
`interrupt_before` enables asynchronous human approval. In production, the agent runs in a cloud function, proposes an action, and pauses. The state is persisted to PostgreSQL. Hours later, a human approves via a web UI. The graph resumes from the saved checkpoint. This decoupling of agent execution from human review is essential for enterprise workflows.

### Task 3 (HITL): Approval Node

**Goal:** Implement the interactive approval gate that presents the proposed action and captures the human's yes/no decision.

**What to do:**
1. Open `C:\Users\MiRuh\source\learn\ai-course\modules\module-19-langgraph\lab\src\hitl_agent.py` and locate `approval_node` (line 135).
2. Display `state["pending_action"]` in a `rich.Panel` with `console.print(Panel(state["pending_action"], title="Pending Action"))`.
3. Use `approved = Confirm.ask("Approve this action?")` (already imported from `rich.prompt` at line 37) to capture the human's decision.
4. Return `{"approved": approved}`.
5. Run:
   ```bash
   uv run python src/hitl_agent.py
   ```

**Expected result:**
```
╭── Pending Action ──╮
│ delete_records(table='users', condition='active=False') │
╰────────────────────╯
Approve this action? [y/n]: y
```
- Answering `y` sets `state["approved"] = True`. The graph will execute the tool call when resumed.
- Answering `n` sets `state["approved"] = False`. The graph will skip execution and route to END.

**Why this matters:**
The approval node is the safety net for irreversible actions. In this lab it uses a terminal prompt, but in production it would be a webhook callback, a Slack interactive message, or a web form. The pattern is the same: capture a boolean decision and store it in graph state.

### Task 4 (HITL): Execute and Resume

**Goal:** Implement the execute node that reads the approval flag and either runs the tool calls or aborts, then resume the graph after the interrupt.

**What to do:**
1. Open `C:\Users\MiRuh\source\learn\ai-course\modules\module-19-langgraph\lab\src\hitl_agent.py` and locate `execute_node` (line 165) and `after_execute_route` (line 188).
2. In `execute_node`: check `state["approved"]`. If `True`, find the last `AIMessage` in `state["messages"]` that has `tool_calls`, iterate through each tool call, find the matching tool in `DANGEROUS_TOOLS` by name, call it with the arguments, and build `ToolMessage` objects with `content=result` and `tool_call_id=tc.id`. Return `{"messages": [list of ToolMessages]}`. If `False`, return `{"messages": [AIMessage(content="Action rejected by human operator.")]}`.
3. In `after_execute_route`: check the last message in `state["messages"]`. If it is a `ToolMessage`, return `"agent"` (route back to agent for a final summary). If it is an `AIMessage` (rejection message), return `END`.
4. Run the full demo:
   ```bash
   uv run python src/hitl_agent.py
   ```

**Expected result:**
```
Resuming graph after approval decision...
EXECUTING: DELETE FROM users WHERE active=False
╭──── Agent Final Response ────╮
│ Done. Deleted 42 records from the 'users' table where active=False.         │
╰──────────────────────────────╯

User: Then send a notification to #ops-alerts saying the cleanup is complete.
Approve this action? [y/n]: n

╭──── Agent Final Response ────╮
│ Action rejected by human operator.                                           │
╰──────────────────────────────╯
```
- Approved actions execute the tool and route back to the agent for a summary response.
- Rejected actions skip execution entirely and terminate the graph.
- The two-message demo (`delete` then `notify`) shows both approval and rejection paths.

**Why this matters:**
This completes the HITL pattern: propose → pause → review → execute-or-abort. For irreversible operations (database deletes, payment charges, email sends), this pattern is not optional — it is a compliance requirement in most enterprise environments. The `interrupt_before` + checkpointer combination makes this pattern portable across process boundaries and restarts.

---

## Key Takeaways

1. **State flows through nodes** — each node receives the full state, returns a partial update. Reducers merge updates.
2. **Conditional edges enable routing** — the routing function sees the current state and returns a node name. This is how you implement ReAct "stop when done".
3. **Checkpointers enable persistence** — thread_id isolates conversations. State survives between invocations.
4. **Interrupts enable HITL** — `interrupt_before` pauses execution at a node. Resume with `invoke(None, config)`.
5. **The graph IS the architecture** — visualizing it gives you a complete picture of the agent's possible execution paths.
