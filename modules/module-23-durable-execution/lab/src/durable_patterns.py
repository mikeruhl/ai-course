"""
Module 23 Lab — Durable Execution Patterns
============================================
Build agents that survive crashes, resume from checkpoints, and compensate on failure.

Tasks:
  A. Event-Sourced Agent — log every action as an event, replay to reconstruct state
  B. Checkpoint-Resume  — multi-step agent saves state to disk, resumes after "crash"
  C. Saga Pattern       — multi-step with compensation (undo) on failure

Run with:
    uv run durable --task A
    uv run durable --task B
    uv run durable --task C
"""

import argparse
import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
API_KEY = os.environ["AZURE_OPENAI_KEY"]
DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")

CHAT_URL = f"{ENDPOINT}/openai/deployments/{DEPLOYMENT}/chat/completions?api-version={API_VERSION}"
HEADERS = {"Content-Type": "application/json", "api-key": API_KEY}

console = Console()
CHECKPOINT_DIR = Path("./checkpoints")


async def chat(client: httpx.AsyncClient, messages: list[dict]) -> str:
    resp = await client.post(
        CHAT_URL, headers=HEADERS,
        json={"messages": messages, "temperature": 0},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Task A — Event-sourced agent
# ---------------------------------------------------------------------------

@dataclass
class Event:
    timestamp: float
    event_type: str
    data: dict

    def to_dict(self) -> dict:
        return asdict(self)


class EventSourcedAgent:
    """
    Agent whose state is derived entirely from an append-only event log.
    To recover from a crash: replay all events from the log.
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.events: list[Event] = []
        self.messages: list[dict] = []
        self.tool_results: dict[str, str] = {}
        self.step_count = 0

    def append_event(self, event_type: str, data: dict):
        event = Event(timestamp=time.time(), event_type=event_type, data=data)
        self.events.append(event)

    def replay(self):
        """Reconstruct state from event log — the core of event sourcing."""
        self.messages = []
        self.tool_results = {}
        self.step_count = 0
        for event in self.events:
            if event.event_type == "message_added":
                self.messages.append(event.data)
            elif event.event_type == "tool_executed":
                self.tool_results[event.data["tool"]] = event.data["result"]
                self.step_count += 1
            elif event.event_type == "response_generated":
                self.messages.append({"role": "assistant", "content": event.data["content"]})
                self.step_count += 1

    def save_log(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump([e.to_dict() for e in self.events], f, indent=2)

    @classmethod
    def load_log(cls, agent_id: str, path: Path) -> "EventSourcedAgent":
        agent = cls(agent_id)
        if path.exists():
            with open(path) as f:
                raw = json.load(f)
            agent.events = [Event(**e) for e in raw]
            agent.replay()
        return agent


async def task_a():
    """Demonstrate event sourcing — log, crash, replay, continue."""
    console.print(Panel("Task A — Event-Sourced Agent", style="bold cyan"))

    agent = EventSourcedAgent("agent-es-001")
    log_path = CHECKPOINT_DIR / "event_log.json"

    # Simulate a research task
    agent.append_event("message_added", {"role": "system", "content": "You are a research assistant."})
    agent.append_event("message_added", {"role": "user", "content": "What are the three main types of agent memory?"})

    async with httpx.AsyncClient() as client:
        agent.replay()
        response = await chat(client, agent.messages)
        agent.append_event("response_generated", {"content": response})
        console.print(f"[green]Step 1 response:[/green] {response[:200]}...")

        # Simulate tool call
        agent.append_event("tool_executed", {"tool": "search", "result": "Found 3 papers on agent memory."})
        agent.append_event("message_added", {"role": "user", "content": "Now explain episodic memory in more detail."})

        agent.replay()
        response2 = await chat(client, agent.messages)
        agent.append_event("response_generated", {"content": response2})
        console.print(f"[green]Step 2 response:[/green] {response2[:200]}...")

    # Save log
    agent.save_log(log_path)
    console.print(f"\n[bold]Event log saved:[/bold] {log_path} ({len(agent.events)} events)")

    # Simulate crash + recovery
    console.print("\n[red]--- SIMULATED CRASH ---[/red]\n")
    recovered = EventSourcedAgent.load_log("agent-es-001", log_path)
    console.print(f"[green]Recovered agent:[/green] {recovered.step_count} steps, {len(recovered.messages)} messages")

    table = Table(title="Event Log")
    table.add_column("#", width=4)
    table.add_column("Type", width=20)
    table.add_column("Data Preview", max_width=60)
    for i, e in enumerate(recovered.events):
        preview = str(e.data)[:60]
        table.add_row(str(i), e.event_type, preview)
    console.print(table)

    # Clean up
    if log_path.exists():
        log_path.unlink()


# ---------------------------------------------------------------------------
# Task B — Checkpoint-resume
# ---------------------------------------------------------------------------

@dataclass
class Checkpoint:
    task_id: str
    current_step: int
    total_steps: int
    results: dict = field(default_factory=dict)
    messages: list[dict] = field(default_factory=list)


class CheckpointAgent:
    """Multi-step agent that saves state after each step and can resume."""

    def __init__(self, task_id: str, steps: list[str]):
        self.task_id = task_id
        self.steps = steps
        self.checkpoint = Checkpoint(task_id=task_id, current_step=0, total_steps=len(steps))
        self.checkpoint_path = CHECKPOINT_DIR / f"checkpoint_{task_id}.json"

    def save_checkpoint(self):
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self.checkpoint)
        with open(self.checkpoint_path, "w") as f:
            json.dump(data, f, indent=2)

    def load_checkpoint(self) -> bool:
        if self.checkpoint_path.exists():
            with open(self.checkpoint_path) as f:
                data = json.load(f)
            self.checkpoint = Checkpoint(**data)
            return True
        return False

    async def run(self, client: httpx.AsyncClient, simulate_crash_at: int = -1):
        """Execute steps, checkpointing after each. Optionally crash at a step."""
        start = self.checkpoint.current_step
        for i in range(start, len(self.steps)):
            step = self.steps[i]
            console.print(f"\n  [bold]Step {i + 1}/{len(self.steps)}:[/bold] {step}")

            if i == simulate_crash_at:
                console.print(f"  [red]CRASH at step {i + 1}![/red]")
                self.save_checkpoint()
                return False

            self.checkpoint.messages.append({"role": "user", "content": step})
            response = await chat(client, [
                {"role": "system", "content": "You are a research assistant. Be concise (1-2 sentences)."},
                *self.checkpoint.messages,
            ])
            self.checkpoint.messages.append({"role": "assistant", "content": response})
            self.checkpoint.results[f"step_{i}"] = response
            self.checkpoint.current_step = i + 1
            self.save_checkpoint()
            console.print(f"  [green]Result:[/green] {response[:100]}...")
            console.print(f"  [dim]Checkpoint saved (step {i + 1})[/dim]")

        return True


async def task_b():
    """Demonstrate checkpoint-resume with a simulated crash."""
    console.print(Panel("Task B — Checkpoint-Resume", style="bold cyan"))

    steps = [
        "What are the 3 main cloud providers for AI workloads?",
        "Compare their managed LLM services.",
        "Which one has the best support for multi-agent systems?",
        "Summarize your findings in a table format.",
    ]

    task_id = "research-001"

    # Run 1: crash at step 2
    console.print("[bold]Run 1 — will crash at step 3:[/bold]")
    agent = CheckpointAgent(task_id, steps)
    async with httpx.AsyncClient() as client:
        completed = await agent.run(client, simulate_crash_at=2)
        console.print(f"\nCompleted: {completed}")

    # Run 2: resume from checkpoint
    console.print("\n[bold]Run 2 — resuming from checkpoint:[/bold]")
    agent2 = CheckpointAgent(task_id, steps)
    resumed = agent2.load_checkpoint()
    console.print(f"Checkpoint found: {resumed}, resuming from step {agent2.checkpoint.current_step + 1}")

    async with httpx.AsyncClient() as client:
        completed = await agent2.run(client)
        console.print(f"\nCompleted: {completed}")

    table = Table(title="Final Results")
    table.add_column("Step", width=8)
    table.add_column("Result", max_width=70)
    for key, val in agent2.checkpoint.results.items():
        table.add_row(key, val[:70] + "...")
    console.print(table)

    # Clean up
    cp = CHECKPOINT_DIR / f"checkpoint_{task_id}.json"
    if cp.exists():
        cp.unlink()


# ---------------------------------------------------------------------------
# Task C — Saga pattern
# ---------------------------------------------------------------------------

@dataclass
class SagaStep:
    name: str
    action: str  # prompt for the action
    compensation: str  # prompt for the undo action
    result: str = ""
    compensated: bool = False


class SagaOrchestrator:
    """
    Saga pattern: execute a sequence of steps. If any step fails,
    compensate (undo) all previously completed steps in reverse order.
    """

    def __init__(self, steps: list[SagaStep]):
        self.steps = steps
        self.completed: list[SagaStep] = []

    async def execute(self, client: httpx.AsyncClient, fail_at: int = -1) -> bool:
        for i, step in enumerate(self.steps):
            console.print(f"\n  [bold]Executing:[/bold] {step.name}")

            if i == fail_at:
                console.print(f"  [red]FAILURE at '{step.name}' — triggering compensation[/red]")
                await self.compensate(client)
                return False

            response = await chat(client, [
                {"role": "system", "content": "Simulate executing this action. Respond with a brief confirmation."},
                {"role": "user", "content": step.action},
            ])
            step.result = response
            self.completed.append(step)
            console.print(f"  [green]Done:[/green] {response[:80]}")

        return True

    async def compensate(self, client: httpx.AsyncClient):
        """Undo completed steps in reverse order."""
        console.print(f"\n  [yellow]Compensating {len(self.completed)} steps in reverse...[/yellow]")
        for step in reversed(self.completed):
            response = await chat(client, [
                {"role": "system", "content": "Simulate undoing/compensating this action. Respond with a brief confirmation."},
                {"role": "user", "content": step.compensation},
            ])
            step.compensated = True
            console.print(f"  [yellow]Compensated '{step.name}':[/yellow] {response[:80]}")


async def task_c():
    """Demonstrate saga pattern with compensation on failure."""
    console.print(Panel("Task C — Saga Pattern with Compensation", style="bold cyan"))

    steps = [
        SagaStep(
            name="Create user account",
            action="Create a new user account for john@example.com in the auth system.",
            compensation="Delete the user account for john@example.com from the auth system.",
        ),
        SagaStep(
            name="Provision workspace",
            action="Create a new workspace 'johns-workspace' with default settings.",
            compensation="Delete workspace 'johns-workspace' and all its contents.",
        ),
        SagaStep(
            name="Send welcome email",
            action="Send a welcome email to john@example.com with onboarding instructions.",
            compensation="Send a cancellation email to john@example.com explaining the signup was rolled back.",
        ),
        SagaStep(
            name="Setup billing",
            action="Create a billing subscription for john@example.com on the Pro plan at $20/month.",
            compensation="Cancel the billing subscription for john@example.com and refund any charges.",
        ),
    ]

    # Run 1: fail at step 3 (send welcome email)
    console.print("[bold]Scenario: Failure at 'Setup billing' — triggers full rollback[/bold]")
    saga = SagaOrchestrator(steps)
    async with httpx.AsyncClient() as client:
        success = await saga.execute(client, fail_at=3)

    console.print(f"\n[bold]Saga completed: {success}[/bold]")

    table = Table(title="Saga Execution Summary")
    table.add_column("Step", width=25)
    table.add_column("Executed", width=10)
    table.add_column("Compensated", width=12)
    for step in steps:
        executed = "yes" if step.result else "no"
        compensated = "yes" if step.compensated else "no"
        table.add_row(step.name, executed, compensated)
    console.print(table)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Module 23 — Durable Execution Patterns Lab")
    parser.add_argument("--task", choices=["A", "B", "C"], required=True)
    args = parser.parse_args()

    dispatch = {"A": task_a, "B": task_b, "C": task_c}
    asyncio.run(dispatch[args.task]())


if __name__ == "__main__":
    main()
