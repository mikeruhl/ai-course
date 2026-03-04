"""
Module 13 Lab — JWT Token Validation
======================================
Server-side JWT validation for incoming A2A requests.

In production, every A2A agent server that accepts authenticated requests
must validate the caller's JWT before processing any task.  This module
implements that validation using Azure AD's public JWKS endpoint.

Tasks:
  1. Extract bearer token from Authorization header
  2. Fetch JWKS from Azure AD discovery endpoint
  3. Validate JWT signature, expiry, audience, and issuer
  4. Extract claims and use for authorization decisions

Run with: uv run python src/token_validator.py --token <jwt>
         uv run python src/token_validator.py --demo
"""

import argparse
import asyncio
import json
import os

import httpx
import jwt  # PyJWT
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

console = Console()


# ---------------------------------------------------------------------------
# Task 1: Extract bearer token
# ---------------------------------------------------------------------------

def extract_bearer_token(authorization_header: str) -> str:
    """
    Task 1: Parse the Authorization header and extract the bearer token.

    Expected format: "Bearer <token>"

    Raises ValueError if the header is missing, malformed, or not a Bearer token.
    """
    if not authorization_header:
        raise ValueError("Missing Authorization header")
    parts = authorization_header.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ValueError(f"Authorization header must be 'Bearer <token>', got: '{authorization_header[:40]}'")
    token = parts[1].strip()
    if not token:
        raise ValueError("Bearer token is empty")
    return token


# ---------------------------------------------------------------------------
# Task 2: Fetch JWKS
# ---------------------------------------------------------------------------

async def fetch_jwks(tenant_id: str) -> dict:
    """
    Task 2: Fetch the JSON Web Key Set (JWKS) from Azure AD.

    Azure AD publishes its public signing keys at:
      https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys

    These keys are used to verify JWT signatures without contacting the
    token issuer for every request.  In production, cache this response
    (it changes infrequently — Azure rotates keys on a ~6-week cycle).

    Steps:
      1. Build the JWKS URL
      2. GET the URL with httpx
      3. Raise on HTTP error
      4. Return the parsed JSON dict (has a "keys" array)
    """
    raise NotImplementedError("Task 2: implement JWKS fetching")


# ---------------------------------------------------------------------------
# Task 3: Validate JWT
# ---------------------------------------------------------------------------

def validate_token(token: str, jwks: dict, audience: str, issuer: str) -> dict:
    """
    Task 3: Validate a JWT and return its claims.

    Uses PyJWT to verify:
      - Signature (against one of the keys in jwks)
      - Expiry (exp claim)
      - Audience (aud claim must match audience)
      - Issuer (iss claim must match issuer)

    PyJWT usage:
      import jwt
      from jwt import PyJWKClient

      # Build a JWKClient from the JWKS URL (or from a dict)
      jwk_client = jwt.PyJWKClient(jwks_url)
      signing_key = jwk_client.get_signing_key_from_jwt(token)
      claims = jwt.decode(
          token,
          signing_key.key,
          algorithms=["RS256"],
          audience=audience,
          issuer=issuer,
      )

    Alternatively, build PyJWKClient from the already-fetched dict:
      # PyJWT >= 2.4 accepts a dict with a "keys" array
      jwk_client = jwt.PyJWKClient("")
      jwk_client.jwk_set_data = jwks

    Raises ValueError (wrapping jwt.exceptions.*) if validation fails.
    Returns the decoded claims dict on success.

    The Azure AD issuer for v2.0 tokens is:
      https://sts.windows.net/{tenant_id}/    (v1 endpoint)
      https://login.microsoftonline.com/{tenant_id}/v2.0  (v2 endpoint)
    Check which your token uses by inspecting the 'iss' claim.
    """
    raise NotImplementedError("Task 3: implement JWT validation")


# ---------------------------------------------------------------------------
# Task 3 (continued): Claims extraction
# ---------------------------------------------------------------------------

def extract_auth_context(claims: dict) -> dict:
    """
    Task 3: Extract a structured auth context from validated JWT claims.

    Azure AD access tokens contain these relevant claims:
      appid / azp  — the client application ID (who is calling)
      tid          — the tenant ID
      sub          — the subject (unique identifier for the app/user)
      roles        — app roles granted to the caller (list, may be absent)
      scp          — delegated scopes (present for user tokens, not app tokens)
      oid          — object ID of the service principal or user

    Returns a dict:
      {
        "app_id": str,       # appid or azp claim
        "tenant_id": str,    # tid claim
        "subject": str,      # sub claim
        "roles": list[str],  # roles claim, empty list if absent
      }
    """
    raise NotImplementedError("Task 3: implement claims extraction")


# ---------------------------------------------------------------------------
# Demo: validate a live token
# ---------------------------------------------------------------------------

async def demo_validate_token(token: str) -> None:
    """Full validation flow: JWKS fetch → validate → extract context."""
    tenant_id = os.environ.get("AZURE_TENANT_ID", "")
    client_id = os.environ.get("AZURE_CLIENT_ID", "")

    if not tenant_id:
        console.print("[red]AZURE_TENANT_ID not set in environment.[/red]")
        return

    # Decode header to find tenant (useful when tenant_id is unknown)
    import base64
    header_b64 = token.split(".")[0]
    padded = header_b64 + "=" * (-len(header_b64) % 4)
    header = json.loads(base64.urlsafe_b64decode(padded))
    console.print(f"JWT algorithm: [cyan]{header.get('alg')}[/cyan], key ID: [cyan]{header.get('kid')}[/cyan]\n")

    # Task 2: Fetch JWKS
    console.print("[bold]Step 2: Fetching JWKS...[/bold]")
    try:
        jwks = await fetch_jwks(tenant_id)
        console.print(f"[green]JWKS fetched[/green] ({len(jwks.get('keys', []))} keys)")
    except NotImplementedError as exc:
        console.print(f"[yellow]Not implemented: {exc}[/yellow]")
        return

    # Task 3: Validate
    console.print("\n[bold]Step 3: Validating token...[/bold]")
    issuer = f"https://sts.windows.net/{tenant_id}/"  # v1 tokens
    audience = client_id or f"api://{client_id}"

    try:
        claims = validate_token(token, jwks, audience=audience, issuer=issuer)
        console.print("[green]Token is valid.[/green]\n")

        # Display claims
        table = Table(title="JWT Claims", show_header=False)
        table.add_column("Claim", style="bold cyan", width=12)
        table.add_column("Value")
        important_claims = ["iss", "aud", "appid", "azp", "tid", "sub", "oid", "exp", "iat", "roles", "scp"]
        for claim in important_claims:
            if claim in claims:
                table.add_row(claim, str(claims[claim]))
        console.print(table)

    except NotImplementedError as exc:
        console.print(f"[yellow]Not implemented: {exc}[/yellow]")
        return
    except ValueError as exc:
        console.print(f"[red]Validation failed: {exc}[/red]")
        return

    # Task 3: Extract auth context
    console.print("\n[bold]Step 3 (continued): Extracting auth context...[/bold]")
    try:
        auth_ctx = extract_auth_context(claims)
        console.print(Panel(json.dumps(auth_ctx, indent=2), title="Auth Context", border_style="green"))
    except NotImplementedError as exc:
        console.print(f"[yellow]Not implemented: {exc}[/yellow]")


async def demo_extract_bearer() -> None:
    """Demonstrate bearer token extraction from a header string."""
    console.rule("[bold]Task 1: Bearer Token Extraction[/bold]")

    test_cases = [
        ("Bearer eyJhbGciOiJSUzI1NiJ9.test.sig", True),
        ("bearer eyJhbGciOiJSUzI1NiJ9.test.sig", True),   # lowercase
        ("Basic dXNlcjpwYXNz", False),                     # wrong scheme
        ("Bearer", False),                                  # missing token
        ("", False),                                        # empty
    ]

    table = Table(title="Bearer Token Extraction Tests", show_lines=True)
    table.add_column("Input", style="dim")
    table.add_column("Expected")
    table.add_column("Result")

    for header, should_succeed in test_cases:
        try:
            token = extract_bearer_token(header)
            result = f"[green]OK[/green] ({token[:20]}…)" if should_succeed else "[red]Should have failed[/red]"
        except ValueError as exc:
            result = f"[red]Error: {exc}[/red]" if should_succeed else f"[green]Correctly rejected:[/green] {exc}"

        table.add_row(header[:40] or "(empty)", "valid" if should_succeed else "invalid", result)

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(description="JWT token validator for A2A authentication")
    parser.add_argument("--token", help="JWT token string to validate")
    parser.add_argument("--demo", action="store_true", help="Run extraction demo only")
    args = parser.parse_args()

    asyncio.run(_main(args))


async def _main(args: argparse.Namespace) -> None:
    console.rule("[bold]Module 13 — JWT Token Validator[/bold]")

    await demo_extract_bearer()

    if args.token:
        console.rule("[bold]Token Validation[/bold]")
        await demo_validate_token(args.token)
    elif not args.demo:
        console.print(
            "\n[dim]Pass --token <jwt> to validate a real token, "
            "or --demo to run extraction tests only.[/dim]"
        )
        console.print(
            "[dim]To get a test token: run auth_demo.py Task 1 and copy the token.[/dim]"
        )


if __name__ == "__main__":
    main()
