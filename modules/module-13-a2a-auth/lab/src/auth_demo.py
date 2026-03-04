"""
Module 13 Lab — A2A Authentication
====================================
Implement OAuth 2.0 Client Credentials flow for agent-to-agent authentication.

Tasks:
  1. Implement get_access_token_client_credentials() — OAuth 2.0 Client Credentials
  2. Implement call_agent_authenticated() — add bearer token to A2A calls
  3. Implement JWT validation on the server side (see token_validator.py)
  4. Implement get_access_token_managed_identity() — IMDS token acquisition

Run with: uv run python src/auth_demo.py
"""

import asyncio
import json
import os
import uuid

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

console = Console()


# ---------------------------------------------------------------------------
# Task 1: OAuth 2.0 Client Credentials
# ---------------------------------------------------------------------------

async def get_access_token_client_credentials(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    scope: str,
) -> str:
    """
    Task 1: Get an OAuth 2.0 access token using the Client Credentials flow.

    This is the standard machine-to-machine authentication pattern.
    The agent (client) proves its identity using a client_id + client_secret
    registered in Entra ID (Azure AD).

    Token endpoint:
      POST https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token

    Request body (application/x-www-form-urlencoded):
      grant_type=client_credentials
      client_id={client_id}
      client_secret={client_secret}
      scope={scope}

    The scope for calling another Azure AD protected service looks like:
      api://<client-id-of-target-app>/.default

    Returns the access_token string from the JSON response.

    Steps:
      1. Build the token endpoint URL
      2. POST with form-encoded body (content-type: application/x-www-form-urlencoded)
      3. Parse the JSON response
      4. Raise httpx.HTTPStatusError on failure (response.raise_for_status())
      5. Return response["access_token"]
    """
    raise NotImplementedError("Task 1: implement client credentials flow")


# ---------------------------------------------------------------------------
# Task 4: Managed Identity (IMDS)
# ---------------------------------------------------------------------------

async def get_access_token_managed_identity(
    resource: str = "https://management.azure.com/",
) -> str:
    """
    Task 4: Acquire a token using Azure Managed Identity via IMDS.

    The Azure Instance Metadata Service (IMDS) is available inside Azure VMs,
    Container Apps, Azure Functions, and AKS pods.  It provides tokens without
    any stored credentials — the platform manages the identity.

    IMDS endpoint (only reachable inside Azure):
      GET http://169.254.169.254/metadata/identity/oauth2/token
          ?api-version=2018-02-01
          &resource={resource}
      Header: Metadata: true

    For user-assigned identity, add: &client_id={AZURE_CLIENT_ID}

    Local development fallback:
      Outside Azure, fall back to the Azure CLI token:
        az account get-access-token --resource {resource}
      Run: import subprocess, json
           result = subprocess.run(["az", "account", "get-access-token", "--resource", resource],
                                   capture_output=True, text=True)
           return json.loads(result.stdout)["accessToken"]

    Steps:
      1. Try the IMDS endpoint (short timeout — it fails fast outside Azure)
      2. On connection error, fall back to Azure CLI
      3. Return the access token string
    """
    raise NotImplementedError("Task 4: implement managed identity token acquisition")


# ---------------------------------------------------------------------------
# Task 2: Authenticated A2A calls
# ---------------------------------------------------------------------------

async def call_agent_authenticated(
    agent_url: str,
    task_input: str,
    token: str,
) -> dict:
    """
    Task 2: Call an A2A agent with bearer token authentication.

    Identical to the unauthenticated /tasks/send call from Module 11,
    except the Authorization header is included.

    Request:
      POST {agent_url}/tasks/send
      Authorization: Bearer {token}
      Content-Type: application/json

      Body:
        {
          "id": "<uuid>",
          "message": {
            "role": "user",
            "parts": [{"type": "text", "text": task_input}]
          }
        }

    Returns the parsed JSON response dict.

    Steps:
      1. Build the /tasks/send URL
      2. Build the A2A request payload
      3. Add Authorization: Bearer {token} to headers
      4. POST with httpx (async client)
      5. Raise on error, return parsed JSON
    """
    raise NotImplementedError("Task 2: implement authenticated agent call")


# ---------------------------------------------------------------------------
# Demonstration flow
# ---------------------------------------------------------------------------

async def demo_client_credentials() -> None:
    """Demonstrate the Client Credentials flow end-to-end."""
    console.rule("[bold]Task 1: OAuth 2.0 Client Credentials[/bold]")

    tenant_id = os.environ.get("AZURE_TENANT_ID", "")
    client_id = os.environ.get("AZURE_CLIENT_ID", "")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET", "")

    if not all([tenant_id, client_id, client_secret]):
        console.print("[yellow]Skipping: AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET not set.[/yellow]")
        console.print("[dim]Copy lab/.env.example to lab/.env and fill in your values.[/dim]")
        return

    # Scope targets the researcher agent's app registration.
    # In production, this is the Application ID URI of the target service.
    scope = f"api://{client_id}/.default"

    console.print(f"Tenant:    [cyan]{tenant_id}[/cyan]")
    console.print(f"Client ID: [cyan]{client_id}[/cyan]")
    console.print(f"Scope:     [cyan]{scope}[/cyan]\n")

    try:
        token = await get_access_token_client_credentials(tenant_id, client_id, client_secret, scope)
        # Show a truncated token so we don't accidentally expose full credentials in logs
        console.print(f"[green]Token acquired:[/green] {token[:40]}…")

        # Decode header + payload (no verification — just for display)
        import base64
        parts = token.split(".")
        if len(parts) == 3:
            # Pad base64 and decode
            def _decode_part(part: str) -> dict:
                padded = part + "=" * (-len(part) % 4)
                return json.loads(base64.urlsafe_b64decode(padded))

            header = _decode_part(parts[0])
            payload = _decode_part(parts[1])

            table = Table(title="JWT Claims (unverified)", show_header=False)
            table.add_column("Claim", style="bold cyan", width=12)
            table.add_column("Value")
            for key in ("iss", "aud", "appid", "tid", "exp", "iat"):
                if key in payload:
                    table.add_row(key, str(payload[key]))
            console.print(table)

    except NotImplementedError as exc:
        console.print(f"[yellow]Not implemented: {exc}[/yellow]")


async def demo_authenticated_call() -> None:
    """Demonstrate calling an agent with a bearer token."""
    console.rule("[bold]Task 2: Authenticated Agent Call[/bold]")

    tenant_id = os.environ.get("AZURE_TENANT_ID", "")
    client_id = os.environ.get("AZURE_CLIENT_ID", "")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET", "")
    researcher_url = os.environ.get("RESEARCHER_AGENT_URL", "http://localhost:8080")

    if not all([tenant_id, client_id, client_secret]):
        console.print("[yellow]Skipping: credentials not configured.[/yellow]")
        return

    scope = f"api://{client_id}/.default"

    try:
        console.print("Acquiring token...")
        token = await get_access_token_client_credentials(tenant_id, client_id, client_secret, scope)
        console.print("[green]Token acquired.[/green]")

        console.print(f"Calling researcher agent at [cyan]{researcher_url}[/cyan]...")
        result = await call_agent_authenticated(
            researcher_url,
            "What is OAuth 2.0 Client Credentials flow and when should I use it?",
            token,
        )

        status = result.get("status", "unknown")
        color = {"completed": "green", "failed": "red"}.get(status, "yellow")
        console.print(f"Status: [{color}]{status}[/{color}]")
        if result.get("output"):
            console.print(Panel(result["output"], title="Agent Response", border_style="green"))

    except NotImplementedError as exc:
        console.print(f"[yellow]Not implemented: {exc}[/yellow]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


async def demo_managed_identity() -> None:
    """Demonstrate managed identity token acquisition."""
    console.rule("[bold]Task 4: Managed Identity[/bold]")
    console.print("[dim]Note: IMDS only works inside Azure. Falls back to Azure CLI locally.[/dim]\n")

    try:
        token = await get_access_token_managed_identity("https://management.azure.com/")
        console.print(f"[green]Token acquired via managed identity:[/green] {token[:40]}…")
    except NotImplementedError as exc:
        console.print(f"[yellow]Not implemented: {exc}[/yellow]")
    except Exception as exc:
        console.print(f"[red]Error (expected outside Azure): {exc}[/red]")


def main() -> None:
    asyncio.run(_main())


async def _main() -> None:
    console.rule("[bold]Module 13 — A2A Authentication Demo[/bold]")
    await demo_client_credentials()
    await demo_authenticated_call()
    await demo_managed_identity()


if __name__ == "__main__":
    main()
