"""
Module 19 Lab — Human-in-the-Loop with LangGraph
====================================================
Build an agent that pauses for human approval before taking actions.

Use case: an agent that can delete records or send notifications should
require explicit human approval before executing those actions. An agent
that acts autonomously on dangerous operations is a liability.

The HITL pattern:
  1. Agent proposes an action (tool call)
  2. Graph PAUSES (interrupt_before) — state is saved to checkpointer
  3. Human reviews the proposed action in the terminal
  4. Human approves or rejects
  5. Graph RESUMES (or aborts) based on human decision

Tasks:
  1. Define agent_node that proposes actions (tool calls)
  2. Use interrupt_before=["execute_node"] to pause before execution
  3. Implement approval_node that prompts the human for confirmation
  4. Resume the graph after human approval, or abort on rejection

Run with: uv run python src/hitl_agent.py
"""
import os
from typing import Annotated

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
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
# State definition
# ---------------------------------------------------------------------------


class HITLState(TypedDict):
    messages: Annotated[list, add_messages]
    # pending_action: human-readable description of the action awaiting approval.
    # Set by agent_node when a dangerous tool call is detected.
    pending_action: str | None
    # approved: None = not yet reviewed; True = approved; False = rejected.
    approved: bool | None


# ---------------------------------------------------------------------------
# Simulated "dangerous" tools
# These tools perform irreversible actions, so they require human approval.
# In a real system these would hit databases, email APIs, payment processors, etc.
# ---------------------------------------------------------------------------


@tool
def delete_records(table: str, condition: str) -> str:
    """Delete records from a database table matching a condition. IRREVERSIBLE."""
    console.print(f"[red bold]EXECUTING: DELETE FROM {table} WHERE {condition}[/red bold]")
    return f"DELETED records from '{table}' WHERE {condition}. Rows affected: 42."


@tool
def send_notification(channel: str, message: str) -> str:
    """Send a notification to a Slack channel or email list."""
    console.print(f"[yellow bold]EXECUTING: SEND to {channel}: {message}[/yellow bold]")
    return f"SENT to '{channel}': {message}"


DANGEROUS_TOOLS = [delete_records, send_notification]
llm_with_tools = llm.bind_tools(DANGEROUS_TOOLS)


# ---------------------------------------------------------------------------
# Task 1: agent_node
# ---------------------------------------------------------------------------
# The agent_node calls the LLM and identifies when a dangerous tool call is proposed.
# It sets state["pending_action"] to a human-readable description so the approval_node
# can show the human exactly what is about to happen.
#
# Implementation steps:
#   1. response = llm_with_tools.invoke(state["messages"])
#   2. If response.tool_calls is non-empty, build a human-readable pending_action string.
#      Example: "delete_records(table='users', condition='active=False')"
#   3. Return {"messages": [response], "pending_action": pending_action_str or None}


def agent_node(state: HITLState) -> dict:
    """
    Call the LLM. If it proposes a tool call, mark it as a pending action
    so the approval_node can present it to the human before execution.
    """
    raise NotImplementedError(
        "Task 1: implement agent_node. "
        "Call llm_with_tools.invoke(state['messages']). "
        "If the response has tool_calls, build a pending_action string like: "
        "\"delete_records(table='users', condition='active=False')\". "
        "Return {'messages': [response], 'pending_action': pending_action_str or None}."
    )


# ---------------------------------------------------------------------------
# Task 3: approval_node
# ---------------------------------------------------------------------------
# The approval_node presents the pending action to the human and asks for confirmation.
# It sets state["approved"] = True or False based on the human's response.
#
# Implementation steps:
#   1. Display the pending action using rich Panel
#   2. Use rich.prompt.Confirm.ask() to get human input
#   3. Return {"approved": bool}
#
# Note: this node does NOT execute the tool. It only sets the approved flag.
# The execute_node (Task 4) reads the flag and decides whether to proceed.


def approval_node(state: HITLState) -> dict:
    """
    Present the pending action to the human and capture their decision.
    Sets state["approved"] = True if approved, False if rejected.
    """
    raise NotImplementedError(
        "Task 3: implement approval_node. "
        "Print state['pending_action'] in a rich Panel. "
        "Use Confirm.ask('Approve this action?') to get the human's decision. "
        "Return {'approved': <bool>}."
    )


# ---------------------------------------------------------------------------
# Task 4: execute_node
# ---------------------------------------------------------------------------
# The execute_node reads state["approved"] and either:
#   - Executes the tool call (approved=True): extract tool calls from last AIMessage,
#     run each tool, return ToolMessage results.
#   - Skips execution (approved=False): return a message explaining the action was rejected.
#
# Implementation steps (approved path):
#   1. Find the last AIMessage in state["messages"] (it has the tool_calls)
#   2. For each tool call, find the matching tool by name and call it with the arguments
#   3. Return {"messages": [ToolMessage(content=result, tool_call_id=tc.id), ...]}
#
# Implementation steps (rejected path):
#   1. Return {"messages": [AIMessage(content="Action rejected by human operator.")]}


def execute_node(state: HITLState) -> dict:
    """
    Execute or skip the pending tool calls based on human approval decision.
    If approved: run the tools and return ToolMessage results.
    If rejected: return a message indicating the action was skipped.
    """
    raise NotImplementedError(
        "Task 4: implement execute_node. "
        "Check state['approved']. If True, find the last AIMessage in state['messages'], "
        "execute each tool call using the DANGEROUS_TOOLS list, and return ToolMessages. "
        "If False, return an AIMessage saying the action was rejected."
    )


# ---------------------------------------------------------------------------
# Task 4: after_execute_node — route back to agent or to END
# ---------------------------------------------------------------------------
# After executing (or rejecting), should we continue the conversation?
# If the execute_node returned ToolMessages, route back to agent_node for
# the LLM to compose a final response. If it returned a rejection AIMessage,
# route to END.


def after_execute_route(state: HITLState) -> str:
    """Route after execute_node: continue to agent if tools ran, else END."""
    raise NotImplementedError(
        "Task 4: implement after_execute_route. "
        "Check the last message in state['messages']. "
        "If it's a ToolMessage → return 'agent'. "
        "If it's an AIMessage (rejection) → return END."
    )


# ---------------------------------------------------------------------------
# Task 2: Routing function — after agent_node
# ---------------------------------------------------------------------------
# Route based on what the agent returned:
#   - Has tool_calls → go to "approval" (the human must approve first)
#   - No tool_calls → go to END (the agent gave a direct answer)


def after_agent_route(state: HITLState) -> str:
    """Route after agent_node: approval gate if tool calls present, else END."""
    raise NotImplementedError(
        "Task 2: implement after_agent_route. "
        "Check state['messages'][-1].tool_calls. "
        "If non-empty: return 'approval'. "
        "If empty: return END."
    )


# ---------------------------------------------------------------------------
# Task 2: Build the graph with interrupt_before
# ---------------------------------------------------------------------------
# Graph topology:
#
#   START → agent_node
#   agent_node → (conditional) → approval_node OR END
#   approval_node → execute_node       ← PAUSE HERE (interrupt_before=["execute_node"])
#   execute_node → (conditional) → agent_node OR END
#
# The interrupt happens BEFORE execute_node. So:
#   - agent_node runs and proposes an action
#   - approval_node runs and captures human decision
#   - Graph PAUSES before execute_node
#   - Human reviews, then resumes: graph.invoke(None, config=config)
#   - execute_node runs with the approved flag set
#
# Wait — if approval_node already captures the decision interactively,
# why do we also need interrupt_before?
#
# Good question. In a real system, the approval would NOT be in the same process.
# The agent might be running in a cloud function, and the human would approve
# via a web UI or Slack bot. interrupt_before enables that async workflow.
# For this lab, approval_node captures it synchronously, but the interrupt
# structure demonstrates the production pattern.


def build_hitl_graph():
    """
    Build and compile the HITL graph.
    Returns (graph, config) where config has the thread_id.

    Steps:
    1. checkpointer = MemorySaver()
    2. Build StateGraph(HITLState) with all four nodes
    3. Add edges per the topology described above
    4. compile(checkpointer=checkpointer, interrupt_before=["execute_node"])
    5. config = {"configurable": {"thread_id": "hitl-demo-1"}}
    6. Return (graph, config)
    """
    raise NotImplementedError(
        "Task 2: implement build_hitl_graph(). "
        "Build StateGraph(HITLState), add nodes: agent, approval, execute. "
        "Add edges: START→agent, conditional agent→approval/END, approval→execute, "
        "conditional execute→agent/END. "
        "Compile with interrupt_before=['execute_node'] and MemorySaver checkpointer."
    )


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------


def main():
    console.print(Panel.fit(
        "[bold blue]Module 19 — Human-in-the-Loop Agent Demo[/bold blue]\n"
        "The agent will propose actions that require your approval.",
        border_style="blue",
    ))

    # Build the HITL graph (will raise NotImplementedError until Task 2 is done)
    graph, config = build_hitl_graph()

    # Show graph structure
    console.print("\n[bold]Graph Structure:[/bold]")
    console.print(graph.get_graph().draw_ascii())

    # Initial message: ask the agent to do something dangerous
    user_messages = [
        "Please delete all inactive users from the 'users' table (condition: active=False)",
        "Then send a notification to #ops-alerts saying the cleanup is complete.",
    ]

    for user_msg in user_messages:
        console.print(f"\n[bold cyan]User:[/bold cyan] {user_msg}")

        inputs = {"messages": [HumanMessage(content=user_msg)], "pending_action": None, "approved": None}

        # First invoke: runs agent_node → approval_node, then PAUSES before execute_node
        try:
            graph.invoke(inputs, config=config)
        except Exception as e:
            # LangGraph raises an interrupt — this is expected behavior
            # In production you would catch this and wait for async approval
            console.print(f"[dim](Graph interrupted: {type(e).__name__})[/dim]")

        # Check the current state
        snapshot = graph.get_state(config)
        console.print(f"[dim]Graph paused at: {snapshot.next}[/dim]")
        console.print(f"[dim]Approved: {snapshot.values.get('approved')}[/dim]")

        # Resume execution (runs execute_node, then back to agent for final response)
        console.print("\n[dim]Resuming graph after approval decision...[/dim]")
        final_state = graph.invoke(None, config=config)

        # Print final agent response
        last_message = final_state["messages"][-1]
        content = last_message.content if hasattr(last_message, "content") else str(last_message)
        console.print(Panel(content, title="Agent Final Response", border_style="green"))


if __name__ == "__main__":
    main()
