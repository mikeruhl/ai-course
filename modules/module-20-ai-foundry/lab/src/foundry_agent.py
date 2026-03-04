"""
Module 20 Lab — Azure AI Foundry Agent Service
=================================================
Explore managed agent patterns: agent creation, thread management, multi-agent handoff.

Tasks:
  A. Agent Creation    — build a tool-calling agent mimicking the Foundry managed pattern
  B. Thread Management — create threads, add messages, run agent across conversation turns
  C. Multi-Agent Handoff — route tasks to specialized agents via an orchestrator

Run with:
    uv run foundry --task A
    uv run foundry --task B
    uv run foundry --task C
"""

import argparse
import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

load_dotenv()

ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
API_KEY = os.environ["AZURE_OPENAI_KEY"]
DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")

CHAT_URL = f"{ENDPOINT}/openai/deployments/{DEPLOYMENT}/chat/completions?api-version={API_VERSION}"
HEADERS = {"Content-Type": "application/json", "api-key": API_KEY}

console = Console()

# ---------------------------------------------------------------------------
# Simulated Foundry primitives
# ---------------------------------------------------------------------------
# Azure AI Foundry Agent Service manages agents, threads, and runs as
# server-side objects. We simulate this pattern locally to teach the concepts
# without requiring the full Foundry SDK.

@dataclass
class AgentDefinition:
    """Mirrors an AI Foundry agent definition."""
    id: str
    name: str
    instructions: str
    model: str
    tools: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class Message:
    role: str
    content: str
    name: str | None = None
    tool_calls: list | None = None
    tool_call_id: str | None = None


@dataclass
class Thread:
    """Mimics an AI Foundry thread — a persistent conversation."""
    id: str
    messages: list[Message] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def add_message(self, role: str, content: str, **kwargs):
        self.messages.append(Message(role=role, content=content, **kwargs))


@dataclass
class Run:
    """Mimics an AI Foundry run — one agent execution against a thread."""
    id: str
    agent_id: str
    thread_id: str
    status: str = "queued"
    usage: dict = field(default_factory=dict)


# Tool definitions for the code interpreter / function calling demo
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a mathematical expression. Simulates code interpreter.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "Math expression to evaluate"}},
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": "Search internal documentation by keyword.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_date",
            "description": "Return the current date in ISO format.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def execute_tool(name: str, args: dict) -> str:
    if name == "calculate":
        try:
            result = eval(args["expression"], {"__builtins__": {}})
            return json.dumps({"result": result})
        except Exception as e:
            return json.dumps({"error": str(e)})
    elif name == "search_docs":
        return json.dumps({
            "results": [
                {"title": "Azure OpenAI Pricing", "snippet": "GPT-4o-mini: $0.15/1M input, $0.60/1M output tokens."},
                {"title": "Rate Limits", "snippet": "GPT-4o-mini default: 60 RPM, 300K TPM."},
            ]
        })
    elif name == "get_current_date":
        return json.dumps({"date": time.strftime("%Y-%m-%d")})
    return json.dumps({"error": f"Unknown tool: {name}"})


async def run_agent(client: httpx.AsyncClient, agent: AgentDefinition, thread: Thread) -> str:
    """Execute an agent against a thread — the core Foundry 'run' pattern."""
    run = Run(id=str(uuid.uuid4())[:8], agent_id=agent.id, thread_id=thread.id, status="in_progress")
    messages = [{"role": "system", "content": agent.instructions}]
    messages += [{"role": m.role, "content": m.content} for m in thread.messages]

    for step in range(10):
        body: dict = {"messages": messages, "temperature": 0}
        if agent.tools:
            body["tools"] = agent.tools

        resp = await client.post(CHAT_URL, headers=HEADERS, json=body, timeout=60)
        resp.raise_for_status()
        choice = resp.json()["choices"][0]
        msg = choice["message"]

        if msg.get("tool_calls"):
            messages.append(msg)
            for tc in msg["tool_calls"]:
                fn_name = tc["function"]["name"]
                fn_args = json.loads(tc["function"]["arguments"])
                console.print(f"  [dim]Tool call:[/dim] {fn_name}({json.dumps(fn_args)})")
                result = execute_tool(fn_name, fn_args)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            continue

        final = msg.get("content", "")
        thread.add_message("assistant", final)
        run.status = "completed"
        return final

    run.status = "failed"
    return "[Agent exceeded maximum steps]"


# ---------------------------------------------------------------------------
# Task A — Agent creation and tool calling
# ---------------------------------------------------------------------------

async def task_a():
    """Create an agent with tools and run it."""
    console.print(Panel("Task A — Agent Creation + Tool Calling", style="bold cyan"))

    agent = AgentDefinition(
        id="agent-001",
        name="Research Assistant",
        instructions=(
            "You are a research assistant with access to a calculator, document search, "
            "and date lookup. Use tools when needed to answer questions accurately."
        ),
        model=DEPLOYMENT,
        tools=TOOLS,
    )

    console.print(f"[bold]Agent:[/bold] {agent.name} (id={agent.id})")
    console.print(f"[bold]Tools:[/bold] {[t['function']['name'] for t in TOOLS]}\n")

    thread = Thread(id=str(uuid.uuid4())[:8])
    queries = [
        "What is 1024 * 768 and what is today's date?",
        "Search for Azure OpenAI pricing information.",
        "If GPT-4o-mini costs $0.15 per million input tokens, how much do 500,000 tokens cost?",
    ]

    async with httpx.AsyncClient() as client:
        for query in queries:
            console.print(f"[yellow]User:[/yellow] {query}")
            thread.add_message("user", query)
            answer = await run_agent(client, agent, thread)
            console.print(Panel(answer, title="Agent Response", border_style="green"))
            console.print()


# ---------------------------------------------------------------------------
# Task B — Thread management
# ---------------------------------------------------------------------------

async def task_b():
    """Demonstrate thread lifecycle — create, converse, fork."""
    console.print(Panel("Task B — Thread Management", style="bold cyan"))

    agent = AgentDefinition(
        id="agent-002",
        name="Conversational Agent",
        instructions="You are a helpful assistant. Remember context from earlier in the conversation.",
        model=DEPLOYMENT,
        tools=[],
    )

    thread = Thread(id=str(uuid.uuid4())[:8], metadata={"user": "mike", "session": "demo"})
    console.print(f"[bold]Thread created:[/bold] {thread.id}")
    console.print(f"[bold]Metadata:[/bold] {thread.metadata}\n")

    conversation = [
        "My name is Mike and I'm building a multi-agent system.",
        "What are the main architectural patterns I should consider?",
        "Which one works best for my use case of code review?",
        "What was my name again?",  # Tests context retention
    ]

    async with httpx.AsyncClient() as client:
        for msg in conversation:
            console.print(f"[yellow]User:[/yellow] {msg}")
            thread.add_message("user", msg)
            answer = await run_agent(client, agent, thread)
            console.print(f"[green]Agent:[/green] {answer}\n")

    # Show thread state
    table = Table(title=f"Thread {thread.id} — {len(thread.messages)} messages")
    table.add_column("Role", width=10)
    table.add_column("Content", max_width=70)
    for m in thread.messages:
        table.add_row(m.role, m.content[:70] + ("..." if len(m.content) > 70 else ""))
    console.print(table)


# ---------------------------------------------------------------------------
# Task C — Multi-agent handoff
# ---------------------------------------------------------------------------

SPECIALIST_AGENTS = {
    "code_review": AgentDefinition(
        id="specialist-code",
        name="Code Reviewer",
        instructions="You are an expert code reviewer. Analyze code for bugs, style, and performance. Be specific and actionable.",
        model=DEPLOYMENT,
    ),
    "security": AgentDefinition(
        id="specialist-security",
        name="Security Analyst",
        instructions="You are a security analyst. Identify vulnerabilities, injection risks, and suggest mitigations. Reference OWASP when applicable.",
        model=DEPLOYMENT,
    ),
    "architecture": AgentDefinition(
        id="specialist-arch",
        name="Architecture Advisor",
        instructions="You are a software architect. Evaluate design decisions, suggest patterns, and identify scalability concerns.",
        model=DEPLOYMENT,
    ),
}

ROUTER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "route_to_specialist",
            "description": "Route the user's request to a specialist agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "specialist": {
                        "type": "string",
                        "enum": ["code_review", "security", "architecture"],
                        "description": "Which specialist to route to",
                    },
                    "task_summary": {"type": "string", "description": "Summary of what the specialist should do"},
                },
                "required": ["specialist", "task_summary"],
            },
        },
    },
]


async def task_c():
    """Orchestrator routes to specialist agents — the Foundry multi-agent pattern."""
    console.print(Panel("Task C — Multi-Agent Handoff", style="bold cyan"))

    orchestrator = AgentDefinition(
        id="orchestrator",
        name="Orchestrator",
        instructions=(
            "You are an orchestrator that routes requests to specialist agents. "
            "Analyze the user's request and call route_to_specialist with the appropriate specialist. "
            "Available specialists: code_review, security, architecture."
        ),
        model=DEPLOYMENT,
        tools=ROUTER_TOOLS,
    )

    requests = [
        "Review this Python function for bugs:\n```python\ndef process(data):\n    result = eval(data['expression'])\n    return {'output': result}\n```",
        "Is it safe to store API keys in environment variables on Azure Container Apps?",
        "Should I use event sourcing or CRUD for my agent's state management?",
    ]

    async with httpx.AsyncClient() as client:
        for user_request in requests:
            console.print(f"\n[yellow]User:[/yellow] {user_request[:80]}...")

            # Step 1: Orchestrator decides routing
            router_thread = Thread(id=str(uuid.uuid4())[:8])
            router_thread.add_message("user", user_request)

            messages = [{"role": "system", "content": orchestrator.instructions}]
            messages.append({"role": "user", "content": user_request})

            resp = await client.post(
                CHAT_URL, headers=HEADERS,
                json={"messages": messages, "temperature": 0, "tools": ROUTER_TOOLS},
                timeout=60,
            )
            resp.raise_for_status()
            choice = resp.json()["choices"][0]["message"]

            if choice.get("tool_calls"):
                tc = choice["tool_calls"][0]
                args = json.loads(tc["function"]["arguments"])
                specialist_key = args["specialist"]
                task_summary = args.get("task_summary", user_request)
                console.print(f"  [dim]Routed to:[/dim] {specialist_key}")

                # Step 2: Specialist handles the request
                specialist = SPECIALIST_AGENTS[specialist_key]
                spec_thread = Thread(id=str(uuid.uuid4())[:8])
                spec_thread.add_message("user", f"{task_summary}\n\nOriginal request:\n{user_request}")
                answer = await run_agent(client, specialist, spec_thread)
            else:
                answer = choice.get("content", "No routing decision made.")

            console.print(Panel(answer, title="Specialist Response", border_style="green"))

    # Show the agent topology
    tree = Tree("[bold]Agent Topology[/bold]")
    orch = tree.add(f"Orchestrator ({orchestrator.id})")
    for key, agent in SPECIALIST_AGENTS.items():
        orch.add(f"{agent.name} ({agent.id}) — handles: {key}")
    console.print(tree)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Module 20 — Azure AI Foundry Agent Service Lab")
    parser.add_argument("--task", choices=["A", "B", "C"], required=True)
    args = parser.parse_args()

    dispatch = {"A": task_a, "B": task_b, "C": task_c}
    asyncio.run(dispatch[args.task]())


if __name__ == "__main__":
    main()
