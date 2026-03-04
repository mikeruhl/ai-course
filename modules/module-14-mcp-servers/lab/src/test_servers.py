"""
Module 14 Lab — Integration Tests (Task 5)
==========================================
Tests the MCP servers programmatically using the mcp SDK as a client.
This demonstrates that MCP's client/server contract is language-agnostic:
the same SDK that builds servers also tests them.

Run:
    uv run pytest src/test_servers.py -v

These tests start your server as a subprocess and communicate over stdio.
They require your .env to be configured with working Azure credentials.

Note: Tests that call Azure OpenAI will incur token costs (very small).
To run only the structural tests (no API calls), use:
    uv run pytest src/test_servers.py -v -m "not azure"
"""

import os
import pathlib
import pytest
import pytest_asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Resolve paths relative to this file's location
SRC_DIR = pathlib.Path(__file__).parent
LAB_DIR = SRC_DIR.parent

OPENAI_SERVER = StdioServerParameters(
    command="uv",
    args=["run", "--project", str(LAB_DIR), "python", str(SRC_DIR / "openai_server.py")],
    env=dict(os.environ),
)

SEARCH_SERVER = StdioServerParameters(
    command="uv",
    args=["run", "--project", str(LAB_DIR), "python", str(SRC_DIR / "search_server.py")],
    env=dict(os.environ),
)


# ===========================================================================
# Helper: create a connected session
# ===========================================================================
# Usage:
#   async with connected_session(OPENAI_SERVER) as session:
#       tools = await session.list_tools()

from contextlib import asynccontextmanager

@asynccontextmanager
async def connected_session(server_params: StdioServerParameters):
    """Context manager that starts an MCP server and returns an initialized session."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


# ===========================================================================
# Task 5a: Test tool registration (structural — no Azure calls)
# ===========================================================================

@pytest.mark.asyncio
async def test_openai_server_has_required_tools():
    """Verify that all 5 expected tools are registered on the OpenAI server."""
    expected_tools = {
        "count_tokens",
        "chat_completion",
        "search_azure_openai",
        "embed_text",
        "list_models",
    }
    async with connected_session(OPENAI_SERVER) as session:
        result = await session.list_tools()
        registered = {tool.name for tool in result.tools}
        # TODO: assert expected_tools is a subset of registered
        # This should pass once your tools are implemented (even with raise NotImplementedError)
        # because the tools are registered at decoration time, not call time
        raise NotImplementedError("Task 5: implement test_openai_server_has_required_tools")


@pytest.mark.asyncio
async def test_openai_server_has_resources():
    """Verify that kb:///index and kb:///{filename} resources are registered."""
    async with connected_session(OPENAI_SERVER) as session:
        result = await session.list_resources()
        uris = [str(r.uri) for r in result.resources]
        # TODO: assert "kb:///index" is in uris
        raise NotImplementedError("Task 5: implement test_openai_server_has_resources")


@pytest.mark.asyncio
async def test_openai_server_has_prompts():
    """Verify that both prompts are registered."""
    expected_prompts = {"code_review", "summarize"}
    async with connected_session(OPENAI_SERVER) as session:
        result = await session.list_prompts()
        registered = {p.name for p in result.prompts}
        # TODO: assert expected_prompts is a subset of registered
        raise NotImplementedError("Task 5: implement test_openai_server_has_prompts")


# ===========================================================================
# Task 5b: Test count_tokens (local — no Azure call)
# ===========================================================================

@pytest.mark.asyncio
async def test_count_tokens_basic():
    """count_tokens is a local operation and should work without Azure credentials."""
    async with connected_session(OPENAI_SERVER) as session:
        result = await session.call_tool("count_tokens", {"text": "hello world"})
        # The result.content[0] should be a TextContent with the integer as string
        # TODO: assert the returned value equals 2 (tiktoken count for "hello world")
        raise NotImplementedError("Task 5: implement test_count_tokens_basic")


@pytest.mark.asyncio
async def test_count_tokens_empty_string():
    """count_tokens of empty string should return 0."""
    async with connected_session(OPENAI_SERVER) as session:
        result = await session.call_tool("count_tokens", {"text": ""})
        # TODO: assert the returned value equals 0
        raise NotImplementedError("Task 5: implement test_count_tokens_empty_string")


# ===========================================================================
# Task 5c: Test resources
# ===========================================================================

@pytest.mark.asyncio
async def test_kb_index_resource():
    """Reading kb:///index returns a non-empty string listing documents."""
    async with connected_session(OPENAI_SERVER) as session:
        result = await session.read_resource("kb:///index")
        # result.contents[0].text should be a string with filenames
        # TODO: assert the content is a non-empty string
        raise NotImplementedError("Task 5: implement test_kb_index_resource")


# ===========================================================================
# Task 5d: Test prompts
# ===========================================================================

@pytest.mark.asyncio
async def test_code_review_prompt():
    """code_review prompt returns a list with at least one message."""
    async with connected_session(OPENAI_SERVER) as session:
        result = await session.get_prompt(
            "code_review",
            arguments={
                "diff": "- old_line\n+ new_line",
                "language": "python",
                "focus_area": "correctness",
            }
        )
        # result.messages should be a list of Message objects
        # TODO: assert len(result.messages) >= 1
        # TODO: assert result.messages[0].role == "user"
        # TODO: assert "python" in result.messages[0].content.text
        raise NotImplementedError("Task 5: implement test_code_review_prompt")


@pytest.mark.asyncio
async def test_summarize_prompt():
    """summarize prompt returns a message that mentions the word limit."""
    async with connected_session(OPENAI_SERVER) as session:
        result = await session.get_prompt(
            "summarize",
            arguments={"content": "Some long text here.", "max_words": 50}
        )
        # TODO: assert len(result.messages) >= 1
        # TODO: assert "50" in result.messages[0].content.text  (the word limit appears)
        raise NotImplementedError("Task 5: implement test_summarize_prompt")


# ===========================================================================
# Task 5e: Test error handling
# ===========================================================================

@pytest.mark.asyncio
async def test_invalid_tool_arguments():
    """Calling a tool with wrong argument types should return an error, not crash."""
    async with connected_session(OPENAI_SERVER) as session:
        # TODO: call count_tokens with a non-string argument (e.g., {"text": 12345})
        # The server should return an error response, not raise an unhandled exception
        # Use pytest.raises or check result.isError
        raise NotImplementedError("Task 5: implement test_invalid_tool_arguments")


# ===========================================================================
# Task 5f: Azure-backed tools (requires real credentials, marked separately)
# ===========================================================================

@pytest.mark.asyncio
@pytest.mark.azure
async def test_chat_completion():
    """chat_completion calls Azure OpenAI and returns a non-empty string."""
    async with connected_session(OPENAI_SERVER) as session:
        result = await session.call_tool(
            "chat_completion",
            {"user_message": "Say exactly: HELLO", "max_tokens": 10}
        )
        # TODO: assert "HELLO" in result.content[0].text (or similar)
        raise NotImplementedError("Task 5: implement test_chat_completion")


@pytest.mark.asyncio
@pytest.mark.azure
async def test_search_server_tools():
    """Verify search server tools are registered and callable."""
    expected_tools = {"search", "index_document", "delete_document", "get_document", "list_indices"}
    async with connected_session(SEARCH_SERVER) as session:
        result = await session.list_tools()
        registered = {tool.name for tool in result.tools}
        # TODO: assert expected_tools is a subset of registered
        raise NotImplementedError("Task 5: implement test_search_server_tools")
