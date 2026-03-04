"""
Module 11 Lab A — A2A Server Implementation
============================================
Build an A2A-compliant agent server from scratch using only httpx + standard library.
No frameworks — raw HTTP so you understand the protocol.

The server exposes:
  GET  /.well-known/agent.json  — Agent Card discovery
  POST /tasks/send              — Submit a task (non-streaming)
  POST /tasks/sendSubscribe     — Submit a task with SSE streaming

Tasks:
  1. Implement the Agent Card endpoint
  2. Implement the /tasks/send handler (synchronous response)
  3. Implement the /tasks/sendSubscribe handler (SSE streaming)
  4. Test with a2a_client.py

Run with: uv run python src/a2a_server.py
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

console = Console()

# ---------------------------------------------------------------------------
# Agent Card — advertises this agent's identity, capabilities, and skills
# ---------------------------------------------------------------------------
AGENT_CARD = {
    "name": "researcher-agent",
    "description": "Answers research questions by searching a knowledge base and synthesizing information.",
    "version": "1.0.0",
    "url": "http://localhost:8080",
    "capabilities": {
        "streaming": True,
        "pushNotifications": False,
    },
    "skills": [
        {
            "id": "research",
            "name": "Research Question",
            "description": "Research and answer a question using the knowledge base.",
            "inputModes": ["text"],
            "outputModes": ["text"],
        }
    ],
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["text"],
}

# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------
@dataclass
class Task:
    id: str
    status: str          # submitted | working | completed | failed
    input: str
    output: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


# In-memory task store: task_id -> Task
TASKS: dict[str, Task] = {}

# ---------------------------------------------------------------------------
# Azure OpenAI helper
# ---------------------------------------------------------------------------

def run_research_agent(input_text: str) -> str:
    """Call Azure OpenAI to answer a research question."""
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")
    api_key = os.environ["AZURE_OPENAI_KEY"]

    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key,
    }
    payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a research assistant. Answer questions clearly and concisely, "
                    "citing reasoning where helpful. If you are unsure, say so."
                ),
            },
            {"role": "user", "content": input_text},
        ],
        "max_tokens": 512,
        "temperature": 0.2,
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class A2ARequestHandler(BaseHTTPRequestHandler):
    """Handles all incoming HTTP requests for the A2A agent server."""

    # Suppress default request logging — we use rich instead.
    def log_message(self, format: str, *args) -> None:
        console.print(f"[dim]{self.address_string()} - {format % args}[/dim]")

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def do_GET(self) -> None:
        if self.path == "/.well-known/agent.json":
            self.handle_agent_card()
        else:
            self._send_json({"error": "Not Found"}, status=404)

    def do_POST(self) -> None:
        if self.path == "/tasks/send":
            self.handle_send()
        elif self.path == "/tasks/sendSubscribe":
            self.handle_send_subscribe()
        else:
            self._send_json({"error": "Not Found"}, status=404)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def handle_agent_card(self) -> None:
        """Return the Agent Card as JSON — the discovery endpoint."""
        self._send_json(AGENT_CARD)

    def handle_send(self) -> None:
        """
        Accept a task, run the research agent synchronously, and return
        the completed task as JSON.

        Expected request body:
          {
            "id": "<uuid>",
            "message": {
              "role": "user",
              "parts": [{"type": "text", "text": "<question>"}]
            }
          }
        """
        try:
            body = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": f"Invalid JSON: {exc}"}, status=400)
            return

        task_id = body.get("id") or str(uuid.uuid4())
        message = body.get("message", {})
        parts = message.get("parts", [])
        input_text = next(
            (p["text"] for p in parts if p.get("type") == "text"), ""
        )

        if not input_text:
            self._send_json({"error": "No text input found in message.parts"}, status=400)
            return

        task = Task(id=task_id, status="submitted", input=input_text)
        TASKS[task_id] = task
        console.print(f"[green]Task {task_id[:8]}… submitted:[/green] {input_text[:80]}")

        # Transition to working
        task.status = "working"
        task.updated_at = time.time()

        try:
            result = run_research_agent(input_text)
            task.status = "completed"
            task.output = result
        except Exception as exc:
            console.print(f"[red]Agent error:[/red] {exc}")
            task.status = "failed"
            task.error = str(exc)

        task.updated_at = time.time()
        console.print(f"[blue]Task {task_id[:8]}… {task.status}[/blue]")
        self._send_json(task.to_dict())

    def handle_send_subscribe(self) -> None:
        """
        Task 3: Implement SSE streaming.

        Accept a task and stream status updates as Server-Sent Events.
        Each event should be a JSON-encoded task object.

        SSE format:
          data: <json>\n\n

        Steps:
          1. Parse request body (same schema as /tasks/send)
          2. Send SSE response headers:
               Content-Type: text/event-stream
               Cache-Control: no-cache
               X-Accel-Buffering: no
          3. Stream an event for each status transition:
               submitted -> working -> completed/failed
          4. Flush after each event (self.wfile.flush())
          5. Close the connection when done
        """
        raise NotImplementedError("Task 3: implement SSE streaming")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        return json.loads(raw)

    def _send_json(self, data: dict | list, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    port = int(os.environ.get("A2A_SERVER_PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), A2ARequestHandler)

    console.print(f"[bold green]A2A Agent Server running on port {port}[/bold green]")
    console.print(f"  Agent Card: [link]http://localhost:{port}/.well-known/agent.json[/link]")
    console.print(f"  Send task:  POST http://localhost:{port}/tasks/send")
    console.print(f"  Streaming:  POST http://localhost:{port}/tasks/sendSubscribe")
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped.[/yellow]")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
