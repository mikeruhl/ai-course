"""
Module 12 Lab A — MCP Client Implementation
============================================
Implement an MCP client that connects to an MCP server via HTTP+SSE transport.
No SDK — raw HTTP so you understand the protocol.

MCP uses JSON-RPC 2.0 over HTTP with SSE for server → client messages.

Tasks:
  1. Implement initialize handshake
  2. Implement tools/list — discover available tools
  3. Implement tools/call — execute a tool
  4. Implement resources/list and resources/read
  5. Build a simple LLM agent that uses MCP tools

Run with: uv run python src/mcp_client.py --server http://localhost:3000
"""

import argparse
import json
import os

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

console = Console()

# ---------------------------------------------------------------------------
# LLM connection — defaults to Azure OpenAI. Set LLM_PROVIDER=vertex for Vertex AI.
# Used by the agent loop in run_agent_with_mcp().
# ---------------------------------------------------------------------------
PROVIDER = os.environ.get("LLM_PROVIDER", "azure")

if PROVIDER == "vertex":
    import google.auth
    import google.auth.transport.requests
    GCP_PROJECT = os.environ["GCP_PROJECT_ID"]
    GCP_REGION = os.environ.get("GCP_REGION", "us-central1")
    _credentials, _ = google.auth.default()
    _credentials.refresh(google.auth.transport.requests.Request())
    _CHAT_URL = (
        f"https://{GCP_REGION}-aiplatform.googleapis.com/v1/projects/{GCP_PROJECT}"
        f"/locations/{GCP_REGION}/endpoints/openapi/chat/completions"
    )
    _CHAT_HEADERS = {"Authorization": f"Bearer {_credentials.token}", "Content-Type": "application/json"}
    _MODEL = os.environ.get("VERTEX_MODEL", "google/gemini-2.0-flash")
else:  # azure (default)
    _endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    _api_key = os.environ.get("AZURE_OPENAI_KEY", "")
    _deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    _api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")
    _CHAT_URL = f"{_endpoint}/openai/deployments/{_deployment}/chat/completions?api-version={_api_version}"
    _CHAT_HEADERS = {
        "Content-Type": "application/json",
        "api-key": _api_key,
    }
    _MODEL = _deployment


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 helpers
# ---------------------------------------------------------------------------

def make_request(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    """Build a JSON-RPC 2.0 request."""
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


def extract_result(response: dict) -> dict:
    """
    Unwrap a JSON-RPC 2.0 response.
    Raises ValueError if the response contains an error.
    """
    if "error" in response:
        err = response["error"]
        raise ValueError(f"JSON-RPC error {err.get('code')}: {err.get('message')}")
    return response.get("result", {})


# ---------------------------------------------------------------------------
# MCP Client
# ---------------------------------------------------------------------------

class MCPClient:
    """
    Minimal MCP client over HTTP (Streamable HTTP transport).

    MCP servers accept JSON-RPC 2.0 requests at a single endpoint (e.g. /mcp).
    Responses are either plain JSON or SSE streams depending on the server
    implementation.  This client targets plain JSON responses for simplicity.
    """

    def __init__(self, server_url: str):
        self.server_url = server_url.rstrip("/")
        self.session_id: str | None = None
        self._request_counter = 0

    def _next_id(self) -> int:
        self._request_counter += 1
        return self._request_counter

    def _post(self, method: str, params: dict | None = None) -> dict:
        """
        Send a JSON-RPC request to the MCP server and return the parsed response.
        Includes the session_id header if one has been negotiated.
        """
        headers = {"Content-Type": "application/json"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        payload = make_request(method, params, request_id=self._next_id())

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(self.server_url, json=payload, headers=headers)
            resp.raise_for_status()

            # Capture session ID from response headers if present
            if "Mcp-Session-Id" in resp.headers:
                self.session_id = resp.headers["Mcp-Session-Id"]

            return resp.json()

    # ------------------------------------------------------------------
    # Task 1: Initialize
    # ------------------------------------------------------------------

    def initialize(self) -> dict:
        """
        Task 1: Send the MCP initialize request and return server capabilities.

        The initialize handshake tells the server about this client and receives
        the server's capabilities and protocol version in return.

        Request params:
          {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-client", "version": "1.0"}
          }

        After receiving a successful response, send an "initialized" notification
        (a JSON-RPC notification has no "id" field):
          {"jsonrpc": "2.0", "method": "notifications/initialized"}

        Steps:
          1. POST initialize request using self._post()
          2. Extract result with extract_result()
          3. Send notifications/initialized (fire-and-forget, ignore response)
          4. Return the server capabilities dict

        Hint: a notification is just a request with no id — you can POST it
        directly without waiting for a response, or use a dedicated _notify() method.
        """
        raise NotImplementedError("Task 1: implement initialize")

    # ------------------------------------------------------------------
    # Task 2: Tools
    # ------------------------------------------------------------------

    def list_tools(self) -> list[dict]:
        """
        Task 2: Fetch the list of tools the server exposes.

        POST tools/list, extract result["tools"].
        Each tool has: name, description, inputSchema (JSON Schema).
        """
        raise NotImplementedError("Task 2: implement list_tools")

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """
        Task 3: Execute a named tool with the given arguments.

        Request params: {"name": tool_name, "arguments": arguments}
        The response result has a "content" array of content blocks.
        Extract and concatenate the text from blocks where type == "text".

        Returns the combined text output as a single string.
        """
        raise NotImplementedError("Task 3: implement call_tool")

    # ------------------------------------------------------------------
    # Task 4: Resources
    # ------------------------------------------------------------------

    def list_resources(self) -> list[dict]:
        """
        Task 4: Fetch available resources from the server.

        POST resources/list, extract result["resources"].
        Each resource has: uri, name, description, mimeType.
        """
        raise NotImplementedError("Task 4: implement list_resources")

    def read_resource(self, uri: str) -> str:
        """
        Task 4: Read the contents of a resource by URI.

        Request params: {"uri": uri}
        Extract text from result["contents"][0]["text"] (or iterate contents).
        """
        raise NotImplementedError("Task 4: implement read_resource")


# ---------------------------------------------------------------------------
# Task 5: LLM agent loop using MCP tools
# ---------------------------------------------------------------------------

def mcp_tool_to_openai_schema(tool: dict) -> dict:
    """
    Convert an MCP tool definition to OpenAI function-calling format.

    MCP tool:
      {"name": "...", "description": "...", "inputSchema": {<JSON Schema>}}

    OpenAI tool:
      {"type": "function", "function": {"name": "...", "description": "...", "parameters": {<JSON Schema>}}}
    """
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
        },
    }


def run_agent_with_mcp(query: str, client: MCPClient) -> str:
    """
    Task 5: Agentic loop — use MCP tools to answer a query.

    Steps:
      1. Fetch available tools via client.list_tools()
      2. Convert them to OpenAI tool format using mcp_tool_to_openai_schema()
      3. Send the user query to Azure OpenAI with the tools attached
      4. If the model responds with tool_calls:
           a. For each tool call, call client.call_tool(name, arguments)
           b. Append the tool result as a "tool" role message
           c. Send the updated conversation back to the model
      5. Repeat until the model produces a text response (no more tool calls)
      6. Return the final text

    LLM REST endpoint (use module-level config):
      POST _CHAT_URL with headers=_CHAT_HEADERS

    Raises NotImplementedError until you implement it.
    """
    raise NotImplementedError("Task 5: implement agent loop with MCP tools")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="MCP client — connect to an MCP server")
    parser.add_argument("--server", default=os.environ.get("MCP_SERVER_URL", "http://localhost:3000/mcp"),
                        help="MCP server URL")
    parser.add_argument("--query", default="What tools are available?",
                        help="Query to run through the MCP agent")
    parser.add_argument("--list-tools", action="store_true", help="List available tools and exit")
    args = parser.parse_args()

    client = MCPClient(args.server)

    console.rule("[bold]MCP Client[/bold]")
    console.print(f"Server: [cyan]{args.server}[/cyan]\n")

    # Initialize
    console.print("[bold]Initializing...[/bold]")
    try:
        capabilities = client.initialize()
        console.print(f"Server capabilities: {json.dumps(capabilities, indent=2)}")
    except NotImplementedError as exc:
        console.print(f"[yellow]Not implemented: {exc}[/yellow]")
        console.print("[dim]Complete Task 1 first.[/dim]")
        return
    except Exception as exc:
        console.print(f"[red]Init failed: {exc}[/red]")
        return

    # List tools
    console.print("\n[bold]Available Tools:[/bold]")
    try:
        tools = client.list_tools()
        table = Table(show_lines=True)
        table.add_column("Name", style="bold cyan")
        table.add_column("Description")
        for t in tools:
            table.add_row(t.get("name", "—"), t.get("description", "—"))
        console.print(table)
    except NotImplementedError as exc:
        console.print(f"[yellow]Not implemented: {exc}[/yellow]")
        tools = []

    if args.list_tools:
        return

    # Run agent
    console.print(f"\n[bold]Running agent:[/bold] [italic]{args.query}[/italic]")
    try:
        result = run_agent_with_mcp(args.query, client)
        console.print(Panel(result, title="Agent Response", border_style="green"))
    except NotImplementedError as exc:
        console.print(f"[yellow]Not implemented: {exc}[/yellow]")
        console.print("[dim]Complete Task 5 to run the full agent loop.[/dim]")


if __name__ == "__main__":
    main()
