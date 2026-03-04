"""
Module 12 Lab B — MCP Protocol Explorer
=========================================
Explore the MCP protocol by inspecting a live server.
Useful for understanding what an MCP server exposes before building a client.

Tasks:
  1. Connect and initialize
  2. List and display all tools with their schemas
  3. List and display all resources
  4. Interactively call tools

Run with: uv run python src/mcp_explore.py --server http://localhost:3000
"""

import argparse
import json
import os

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

# Import the client we built in Lab A
from src.mcp_client import MCPClient

load_dotenv()

console = Console()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def display_tools(tools: list[dict]) -> None:
    """Render tool list as a rich table with schema details."""
    if not tools:
        console.print("[dim]No tools available.[/dim]")
        return

    table = Table(title=f"Tools ({len(tools)})", show_lines=True)
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Description")
    table.add_column("Input Schema", overflow="fold")

    for tool in tools:
        schema_str = json.dumps(tool.get("inputSchema", {}), indent=2)
        table.add_row(
            tool.get("name", "—"),
            tool.get("description", "—"),
            schema_str,
        )

    console.print(table)


def display_resources(resources: list[dict]) -> None:
    """Render resource list as a rich table."""
    if not resources:
        console.print("[dim]No resources available.[/dim]")
        return

    table = Table(title=f"Resources ({len(resources)})", show_lines=True)
    table.add_column("URI", style="bold cyan")
    table.add_column("Name")
    table.add_column("Description")
    table.add_column("MIME Type")

    for res in resources:
        table.add_row(
            res.get("uri", "—"),
            res.get("name", "—"),
            res.get("description", "—"),
            res.get("mimeType", "—"),
        )

    console.print(table)


def interactive_tool_call(client: MCPClient, tools: list[dict]) -> None:
    """
    Task 4: Simple interactive REPL for calling tools.

    Prompts the user to pick a tool and enter JSON arguments,
    then calls client.call_tool() and displays the result.
    """
    if not tools:
        console.print("[yellow]No tools to call.[/yellow]")
        return

    console.print("\n[bold]Interactive Tool Caller[/bold] (Ctrl+C to exit)\n")
    tool_map = {t["name"]: t for t in tools}

    while True:
        try:
            # Pick tool
            console.print("Available tools: " + ", ".join(f"[cyan]{n}[/cyan]" for n in tool_map))
            tool_name = console.input("[bold]Tool name[/bold] (or 'quit'): ").strip()
            if tool_name.lower() in ("quit", "q", "exit"):
                break
            if tool_name not in tool_map:
                console.print(f"[red]Unknown tool: {tool_name}[/red]")
                continue

            # Show input schema
            schema = tool_map[tool_name].get("inputSchema", {})
            console.print(
                Syntax(json.dumps(schema, indent=2), "json", theme="monokai"),
            )

            # Get arguments
            raw_args = console.input("[bold]Arguments (JSON)[/bold]: ").strip()
            try:
                arguments = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError as exc:
                console.print(f"[red]Invalid JSON: {exc}[/red]")
                continue

            # Call tool
            console.print(f"\nCalling [cyan]{tool_name}[/cyan]...")
            try:
                result = client.call_tool(tool_name, arguments)
                console.print(Panel(result, title="Result", border_style="green"))
            except NotImplementedError as exc:
                console.print(f"[yellow]Not implemented: {exc}[/yellow]")
                console.print("[dim]Complete Task 3 in mcp_client.py first.[/dim]")
            except Exception as exc:
                console.print(f"[red]Tool call failed: {exc}[/red]")

            console.print()

        except KeyboardInterrupt:
            console.print("\n[dim]Exiting interactive mode.[/dim]")
            break


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="MCP protocol explorer — inspect a live MCP server")
    parser.add_argument(
        "--server",
        default=os.environ.get("MCP_SERVER_URL", "http://localhost:3000/mcp"),
        help="MCP server endpoint URL",
    )
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Enter interactive tool-call mode after listing")
    args = parser.parse_args()

    client = MCPClient(args.server)

    console.rule("[bold]MCP Protocol Explorer[/bold]")
    console.print(f"Server: [cyan]{args.server}[/cyan]\n")

    # Task 1: Initialize
    console.print("[bold]Step 1: Initialize[/bold]")
    try:
        capabilities = client.initialize()
        console.print("[green]Connected successfully.[/green]")
        console.print(
            Panel(
                json.dumps(capabilities, indent=2),
                title="Server Capabilities",
                border_style="cyan",
            )
        )
    except NotImplementedError as exc:
        console.print(f"[yellow]Not implemented: {exc}[/yellow]")
        console.print("[dim]Implement Task 1 in mcp_client.py to continue.[/dim]")
        return
    except Exception as exc:
        console.print(f"[red]Failed to connect: {exc}[/red]")
        console.print(f"[yellow]Is an MCP server running at {args.server}?[/yellow]")
        return

    # Task 2: List tools
    console.print("\n[bold]Step 2: Tools[/bold]")
    try:
        tools = client.list_tools()
        display_tools(tools)
    except NotImplementedError as exc:
        console.print(f"[yellow]Not implemented: {exc}[/yellow]")
        tools = []

    # Task 3: List resources
    console.print("\n[bold]Step 3: Resources[/bold]")
    try:
        resources = client.list_resources()
        display_resources(resources)

        # Show contents of first resource as a sample
        if resources:
            first_uri = resources[0].get("uri", "")
            console.print(f"\nReading resource: [cyan]{first_uri}[/cyan]")
            try:
                content = client.read_resource(first_uri)
                console.print(Panel(content[:500] + ("…" if len(content) > 500 else ""),
                                    title=f"Resource: {first_uri}", border_style="dim"))
            except NotImplementedError as exc:
                console.print(f"[yellow]Not implemented: {exc}[/yellow]")
    except NotImplementedError as exc:
        console.print(f"[yellow]Not implemented: {exc}[/yellow]")

    # Task 4: Interactive mode
    if args.interactive:
        console.print("\n[bold]Step 4: Interactive Tool Calls[/bold]")
        interactive_tool_call(client, tools)


if __name__ == "__main__":
    main()
