"""
Module 19 Lab — LangGraph Agent
=================================
Build a ReAct agent using LangGraph StateGraph.

This module switches from raw httpx to LangGraph + langchain-openai
because the value of LangGraph is in its graph abstractions — not
the API call. You'll see that the graph structure IS the architecture.

Tasks:
  A. Build the basic StateGraph ReAct loop (agent_node → tool_node → agent_node)
  B. Add conditional routing (stop when no tool calls)
  C. Add MemorySaver checkpointing (multi-turn conversations)
  D. Visualize the graph structure

Run with: uv run python src/langgraph_agent.py --task A|B|C|D
"""
import os
from typing import Annotated

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from rich.console import Console
from rich.panel import Panel
from typing_extensions import TypedDict

load_dotenv()

console = Console()

llm = AzureChatOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
    api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
)


# ---------------------------------------------------------------------------
# Task A: Define State and basic graph structure
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    # add_messages is a reducer: it appends new messages to the list
    # instead of replacing it. This is how LangGraph handles conversation history.
    # Every node that returns {"messages": [...]} APPENDS to the list,
    # rather than replacing it. The full history is always in state["messages"].


# Define some simple tools — working implementations provided.
# You don't need to modify these. They are used by the agent to answer questions.

@tool
def search_knowledge_base(query: str) -> str:
    """Search the knowledge base for information about a topic."""
    # Simulated knowledge base — in a real system this would hit Azure AI Search
    kb = {
        "langgraph": (
            "LangGraph is a library for building stateful, multi-actor applications "
            "with LLMs. It models agent behavior as a directed graph where nodes are "
            "Python functions and edges are transitions between them. Cycles are "
            "supported, enabling ReAct loops and other iterative patterns."
        ),
        "checkpointing": (
            "LangGraph checkpointing saves graph state to persistent storage after "
            "every step. This enables pause/resume, multi-turn conversations across "
            "invocations, and human-in-the-loop interrupts. MemorySaver is used for "
            "development; PostgresSaver for production."
        ),
        "hitl": (
            "Human-in-the-loop (HITL) in LangGraph uses interrupt_before or "
            "interrupt_after to pause graph execution before a specified node. "
            "The graph state is saved to the checkpointer. Resume with "
            "graph.invoke(None, config=config) after the human has reviewed."
        ),
        "stategraph": (
            "StateGraph is the main graph class in LangGraph. You add nodes with "
            "add_node(), connect them with add_edge() or add_conditional_edges(), "
            "and compile the graph with compile(). The TypedDict you pass to "
            "StateGraph defines the shape of the state that flows between nodes."
        ),
        "toolnode": (
            "ToolNode is a pre-built LangGraph node that reads tool_calls from the "
            "last message in state, executes each tool, and returns ToolMessage "
            "objects with the results. It handles parallel tool calls and error "
            "catching automatically."
        ),
    }
    for key, value in kb.items():
        if key in query.lower():
            return value
    # Partial match fallback
    for key, value in kb.items():
        if any(word in query.lower() for word in key.split()):
            return value
    return f"No results found for '{query}' in the knowledge base."


@tool
def calculate(expression: str) -> str:
    """Safely evaluate a simple math expression (numbers and +, -, *, /, parentheses only)."""
    try:
        # Only allow safe math characters to prevent code injection
        allowed_chars = set("0123456789+-*/.(). ")
        if not all(c in allowed_chars for c in expression):
            return "Error: expression contains invalid characters. Only numbers and +-*/() are allowed."
        result = eval(expression)  # noqa: S307 - safe due to character allowlist above
        return str(result)
    except ZeroDivisionError:
        return "Error: division by zero"
    except Exception as e:
        return f"Error evaluating expression: {e}"


TOOLS = [search_knowledge_base, calculate]


# TODO Task A: bind tools to the LLM so it knows what tools are available.
# Replace this line:
#   llm_with_tools = None
# With:
#   llm_with_tools = llm.bind_tools(TOOLS)
# bind_tools() injects the tool schemas into the LLM's system context.
# When the LLM wants to call a tool, it returns an AIMessage with tool_calls populated.
llm_with_tools = None  # replace with llm.bind_tools(TOOLS)


# TODO Task A: implement agent_node.
# The agent_node calls the LLM and returns the response as a state update.
# Signature: (state: AgentState) -> dict
# Hint:
#   response = llm_with_tools.invoke(state["messages"])
#   return {"messages": [response]}
# The add_messages reducer will append `response` to the existing messages list.
def agent_node(state: AgentState) -> dict:
    """Call the LLM with current messages. Returns updated messages."""
    raise NotImplementedError(
        "Task A: implement agent_node. "
        "Call llm_with_tools.invoke(state['messages']) and return {'messages': [response]}."
    )


# TODO Task B: implement should_continue.
# This is the conditional routing function. It decides where the graph goes
# after agent_node runs. Return "tools" to execute tool calls, or END to stop.
# Hint: check state["messages"][-1].tool_calls
def should_continue(state: AgentState) -> str:
    """
    Route: if last message has tool_calls → 'tools' node. Else → END.

    This is what makes the ReAct loop work. The agent either:
    - Has tool calls → we must execute them (go to tools node)
    - Has no tool calls → the agent is done (end the graph)
    """
    raise NotImplementedError(
        "Task B: implement conditional routing. "
        "Check if state['messages'][-1] has non-empty tool_calls. "
        "Return 'tools' if yes, END if no."
    )


# TODO Task A: build the graph.
# Steps:
#   1. graph_builder = StateGraph(AgentState)
#   2. graph_builder.add_node("agent", agent_node)
#   3. graph_builder.add_node("tools", ToolNode(TOOLS))
#   4. graph_builder.add_edge(START, "agent")          # start → agent
#   5. graph_builder.add_conditional_edges("agent", should_continue)  # conditional
#   6. graph_builder.add_edge("tools", "agent")        # tools → back to agent (the cycle!)
#   7. graph = graph_builder.compile()
#
# The edge from "tools" back to "agent" is the cycle. This is why we need LangGraph —
# a simple chain cannot represent this loop.
graph: StateGraph | None = None  # replace with compiled graph


# ---------------------------------------------------------------------------
# Task C: Add checkpointing for multi-turn conversations
# ---------------------------------------------------------------------------


def build_graph_with_memory():
    """
    Build the same graph but with MemorySaver checkpointer.
    Returns (graph, config) where config contains the thread_id.

    With checkpointing, the graph remembers previous messages across
    separate .invoke() calls. This is how multi-turn chat works.

    Steps:
    1. from langgraph.checkpoint.memory import MemorySaver
    2. checkpointer = MemorySaver()
    3. graph = graph_builder.compile(checkpointer=checkpointer)
    4. config = {"configurable": {"thread_id": "demo-thread-1"}}
    5. Return (graph, config)
    """
    raise NotImplementedError(
        "Task C: implement build_graph_with_memory(). "
        "Build the graph with checkpointer=MemorySaver(), define a config with thread_id, "
        "then run two sequential invocations where the second message refers back to the first. "
        "Verify the agent recalls context from turn 1 in turn 2."
    )


# ---------------------------------------------------------------------------
# Task D: Visualize the graph structure
# ---------------------------------------------------------------------------


def print_graph_structure(compiled_graph) -> None:
    """
    Print a text representation of the graph structure.

    Useful for understanding and debugging agent architectures.
    In production you would use LangSmith for this, but ASCII art
    works fine for development.

    Steps:
    1. ascii_art = compiled_graph.get_graph().draw_ascii()
       print(ascii_art)
    2. Optionally also print nodes and edges manually:
       g = compiled_graph.get_graph()
       print("Nodes:", list(g.nodes.keys()))
       print("Edges:", [(e.source, e.target) for e in g.edges])
    """
    raise NotImplementedError(
        "Task D: implement print_graph_structure(). "
        "Call graph.get_graph().draw_ascii() and print the result. "
        "Also print the list of nodes and edges."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def invoke_and_print(compiled_graph, query: str, config: dict | None = None) -> str:
    """Invoke the graph with a query and pretty-print the result."""
    inputs = {"messages": [HumanMessage(content=query)]}
    kwargs = {"input": inputs}
    if config:
        kwargs["config"] = config

    console.print(f"\n[bold cyan]Query:[/bold cyan] {query}")

    final_state = compiled_graph.invoke(inputs, config=config)
    last_message = final_state["messages"][-1]
    response_text = last_message.content if hasattr(last_message, "content") else str(last_message)

    console.print(Panel(response_text, title="Agent Response", border_style="green"))
    return response_text


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Module 19 — LangGraph Agent")
    parser.add_argument(
        "--task",
        choices=["A", "B", "C", "D"],
        default="B",
        help="Which task to run (A=basic graph, B=routing, C=memory, D=visualize)",
    )
    parser.add_argument(
        "--query",
        default="What is LangGraph checkpointing and how does it work?",
        help="Query to send to the agent",
    )
    args = parser.parse_args()

    console.print(f"[bold]Module 19 — LangGraph Agent — Task {args.task}[/bold]")
    console.print(f"Query: {args.query}\n")

    if args.task in ("A", "B"):
        # Task A/B: basic graph without checkpointing
        if graph is None:
            console.print(
                "[red]graph is None — complete Task A first: build and compile the StateGraph.[/red]"
            )
            return
        invoke_and_print(graph, args.query)

    elif args.task == "C":
        # Task C: multi-turn with checkpointing
        console.print("[bold]Task C: Multi-turn conversation with MemorySaver[/bold]")
        # build_graph_with_memory() will raise NotImplementedError until implemented
        result = build_graph_with_memory()
        if result is not None:
            g, config = result
            console.print("\n[yellow]Turn 1:[/yellow]")
            invoke_and_print(g, "My favorite AI framework is LangGraph.", config=config)
            console.print("\n[yellow]Turn 2 (should recall Turn 1):[/yellow]")
            invoke_and_print(g, "What AI framework did I just mention?", config=config)

    elif args.task == "D":
        # Task D: visualize graph structure
        if graph is None:
            console.print(
                "[red]graph is None — complete Task A first, then run Task D.[/red]"
            )
            return
        console.print("[bold]Task D: Graph Structure[/bold]")
        print_graph_structure(graph)


if __name__ == "__main__":
    main()
