"""
Module 11 Lab B — A2A Client Implementation
============================================
Discover and call an A2A agent server.

Tasks:
  1. Implement discover_agent() — fetch and parse Agent Card
  2. Implement submit_task() — POST to /tasks/send
  3. Implement submit_task_streaming() — POST to /tasks/sendSubscribe with SSE
  4. Run discovery + task submission against the server from Lab A

Run with: uv run python src/a2a_client.py --server http://localhost:8080 --query "What is RAG?"
"""

import argparse
import json
import uuid

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

console = Console()


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_agent(server_url: str) -> dict:
    """
    Fetch the Agent Card from /.well-known/agent.json.

    Returns the parsed card as a dict, or raises httpx.HTTPError on failure.
    """
    url = f"{server_url.rstrip('/')}/.well-known/agent.json"
    with httpx.Client(timeout=10.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def print_agent_card(card: dict) -> None:
    """Render an Agent Card using rich."""
    table = Table(title=f"Agent: {card.get('name', 'unknown')}", show_header=False)
    table.add_column("Field", style="bold cyan", width=20)
    table.add_column("Value")

    table.add_row("Description", card.get("description", "—"))
    table.add_row("Version", card.get("version", "—"))
    table.add_row("URL", card.get("url", "—"))

    caps = card.get("capabilities", {})
    table.add_row("Streaming", str(caps.get("streaming", False)))
    table.add_row("Push Notifications", str(caps.get("pushNotifications", False)))

    skills = card.get("skills", [])
    skill_lines = "\n".join(
        f"  [{s['id']}] {s['name']}: {s.get('description', '')}" for s in skills
    )
    table.add_row("Skills", skill_lines or "—")

    console.print(table)


# ---------------------------------------------------------------------------
# Task submission (synchronous)
# ---------------------------------------------------------------------------

def submit_task(server_url: str, input_text: str) -> dict:
    """
    POST a task to /tasks/send and return the completed task dict.

    Request body follows the A2A message schema:
      {
        "id": "<uuid>",
        "message": {
          "role": "user",
          "parts": [{"type": "text", "text": "<input_text>"}]
        }
      }
    """
    url = f"{server_url.rstrip('/')}/tasks/send"
    payload = {
        "id": str(uuid.uuid4()),
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": input_text}],
        },
    }

    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# Task submission (SSE streaming) — Task 3
# ---------------------------------------------------------------------------

def submit_task_streaming(server_url: str, input_text: str) -> None:
    """
    Task 3: Implement SSE streaming client.

    POST to /tasks/sendSubscribe and consume the Server-Sent Events stream.
    Print each status update as it arrives.

    SSE format from the server:
      data: <json>\n\n

    Steps:
      1. Build the same request payload as submit_task()
      2. Open a streaming POST (stream=True) to /tasks/sendSubscribe
      3. Iterate over response lines
      4. Parse lines that start with "data: " as JSON task objects
      5. Print each task status update
      6. Stop when status is "completed" or "failed"
    """
    raise NotImplementedError("Task 3: implement SSE streaming client")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="A2A client — discover and call an agent server")
    parser.add_argument("--server", default="http://localhost:8080", help="A2A server base URL")
    parser.add_argument("--query", default="What is retrieval-augmented generation (RAG)?",
                        help="Research question to submit")
    parser.add_argument("--stream", action="store_true", help="Use SSE streaming (Task 3)")
    args = parser.parse_args()

    server_url = args.server.rstrip("/")

    # Step 1: Discover agent
    console.rule("[bold]Step 1: Agent Discovery[/bold]")
    try:
        card = discover_agent(server_url)
        print_agent_card(card)
    except httpx.ConnectError:
        console.print(f"[red]Could not connect to {server_url}[/red]")
        console.print("[yellow]Is the server running? Try: uv run python src/a2a_server.py[/yellow]")
        return
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]Discovery failed: {exc.response.status_code}[/red]")
        return

    # Step 2: Submit task
    console.rule("[bold]Step 2: Task Submission[/bold]")
    console.print(f"Query: [italic]{args.query}[/italic]\n")

    if args.stream:
        # Task 3
        console.print("[cyan]Streaming mode (Task 3)[/cyan]")
        submit_task_streaming(server_url, args.query)
    else:
        try:
            task = submit_task(server_url, args.query)
        except httpx.HTTPStatusError as exc:
            console.print(f"[red]Task submission failed: {exc.response.status_code}[/red]")
            console.print(exc.response.text)
            return

        status = task.get("status", "unknown")
        status_color = {"completed": "green", "failed": "red", "working": "yellow"}.get(status, "white")

        console.print(f"Task ID: [dim]{task.get('id', '—')}[/dim]")
        console.print(f"Status:  [{status_color}]{status}[/{status_color}]")

        if task.get("output"):
            console.print(Panel(task["output"], title="Result", border_style="green"))
        elif task.get("error"):
            console.print(Panel(task["error"], title="Error", border_style="red"))


if __name__ == "__main__":
    main()
