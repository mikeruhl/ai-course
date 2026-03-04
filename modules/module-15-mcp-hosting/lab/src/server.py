"""
Module 15 Lab — MCP Server with HTTP+SSE Transport (Task 1)
============================================================
This is your module-14 MCP server converted from stdio to HTTP+SSE.
The tool/resource/prompt logic is IDENTICAL to module-14.
Only the transport (the last few lines) changes.

Run locally:
    uv run python src/server.py

Then connect via MCP Inspector:
    npx @modelcontextprotocol/inspector http://localhost:8080/sse

Or test directly:
    curl -N http://localhost:8080/sse        # SSE stream
    curl -X POST http://localhost:8080/messages  # send requests
"""

import os
import pathlib

import httpx
import tiktoken
from dotenv import load_dotenv
from mcp import types as mcp_types
from mcp.server.fastmcp import FastMCP
from mcp.types import Message, TextContent

load_dotenv()

# ---------------------------------------------------------------------------
# Azure OpenAI configuration
# ---------------------------------------------------------------------------
ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
API_KEY = os.environ["AZURE_OPENAI_KEY"]
DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")

CHAT_URL = f"{ENDPOINT}/openai/deployments/{DEPLOYMENT}/chat/completions?api-version={API_VERSION}"
HEADERS = {"api-key": API_KEY, "Content-Type": "application/json"}

KB_PATH = pathlib.Path(os.environ.get("KB_PATH", "./knowledge_base")).resolve()

HOST = os.environ.get("MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", "8080"))

# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP("azure-openai-server-http")


# ===========================================================================
# Tools (identical to module-14 — copy your completed implementations here)
# ===========================================================================

@mcp.tool()
def count_tokens(text: str) -> int:
    """
    Count the number of tokens in the given text using the cl100k_base encoding.

    This is a local operation — no API call is made.

    Args:
        text: The text to count tokens for.

    Returns:
        Integer token count.
    """
    # TODO: Copy your working implementation from module-14
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


@mcp.tool()
def chat_completion(
    user_message: str,
    system_message: str = "You are a helpful assistant.",
    temperature: float = 0.0,
    max_tokens: int = 500,
) -> str:
    """
    Send a message to Azure OpenAI and return the assistant's reply.

    Args:
        user_message: The user's message to send to the model.
        system_message: The system prompt. Defaults to a generic helpful assistant.
        temperature: Sampling temperature 0.0–1.0. Default 0.
        max_tokens: Maximum tokens in the response. Default 500.

    Returns:
        The assistant's reply as a plain string.
    """
    # TODO: Copy your working implementation from module-14
    raise NotImplementedError("Copy from module-14: chat_completion")


@mcp.tool()
def search_azure_openai(query: str, max_tokens: int = 300) -> str:
    """
    Ask Azure OpenAI a question and return the answer.

    Args:
        query: The question or task to send to Azure OpenAI.
        max_tokens: Maximum tokens in the response. Default 300.

    Returns:
        The model's response as a plain string.
    """
    # TODO: Copy your working implementation from module-14
    raise NotImplementedError("Copy from module-14: search_azure_openai")


@mcp.tool()
def count_tokens_with_model(text: str) -> int:
    """
    Count tokens. Alias kept for client compatibility.

    Args:
        text: Text to count tokens for.

    Returns:
        Integer token count.
    """
    return count_tokens(text)


# ===========================================================================
# Resources (identical to module-14)
# ===========================================================================

@mcp.resource("kb:///index")
def kb_index() -> str:
    """List all documents in the knowledge base."""
    # TODO: Copy your working implementation from module-14
    raise NotImplementedError("Copy from module-14: kb_index")


@mcp.resource("kb:///{filename}")
def kb_document(filename: str) -> str:
    """Return the contents of a knowledge base document."""
    # TODO: Copy your working implementation from module-14
    raise NotImplementedError("Copy from module-14: kb_document")


@mcp.tool()
def list_kb_documents() -> list[str]:
    """List all documents available in the knowledge base."""
    # TODO: Copy your working implementation from module-14
    raise NotImplementedError("Copy from module-14: list_kb_documents")


# ===========================================================================
# Prompts (identical to module-14)
# ===========================================================================

@mcp.prompt()
def code_review(diff: str, language: str, focus_area: str = "all") -> list[Message]:
    """Generate a structured code review prompt."""
    # TODO: Copy your working implementation from module-14
    raise NotImplementedError("Copy from module-14: code_review")


@mcp.prompt()
def summarize(content: str, max_words: int = 150) -> list[Message]:
    """Generate a summarization prompt."""
    # TODO: Copy your working implementation from module-14
    raise NotImplementedError("Copy from module-14: summarize")


# ===========================================================================
# Health check endpoint
# Container Apps uses HTTP probes — we add a /health route.
# FastMCP's SSE server is built on Starlette, so we can add custom routes.
# ===========================================================================

# TODO (optional, advanced): Add a /health route for Container Apps liveness probes
# The mcp SDK's SSE server exposes a Starlette app at mcp._sse_server.app
# You can add a route like:
#
# from starlette.responses import JSONResponse
# from starlette.routing import Route
#
# async def health(request):
#     return JSONResponse({"status": "ok", "server": "azure-openai-server-http"})


# ===========================================================================
# Entrypoint — HTTP+SSE transport
# This is the ONLY change from module-14's stdio version.
# ===========================================================================

if __name__ == "__main__":
    # Task 1: Change transport from stdio to HTTP+SSE
    # The host/port are read from environment variables so they work both
    # locally and in Container Apps.
    mcp.run(transport="sse", host=HOST, port=PORT)
