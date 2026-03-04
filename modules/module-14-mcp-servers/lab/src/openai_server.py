"""
Module 14 Lab — MCP Server wrapping Azure OpenAI
=================================================
This file implements an MCP server that exposes Azure OpenAI capabilities as
MCP Tools, Resources, and Prompts.

Run with MCP Inspector:
    npx @modelcontextprotocol/inspector uv run python src/openai_server.py

Or run directly for stdio testing:
    uv run python src/openai_server.py

Tasks covered: 1 (Tools), 2 (Resources), 3 (Prompts)
"""

import os
import pathlib
from typing import Any

import httpx
import tiktoken
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp import types as mcp_types
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
EMBED_URL = f"{ENDPOINT}/openai/deployments/text-embedding-3-small/embeddings?api-version={API_VERSION}"
MODELS_URL = f"{ENDPOINT}/openai/models?api-version={API_VERSION}"
HEADERS = {"api-key": API_KEY, "Content-Type": "application/json"}

# Knowledge base path — markdown files exposed as MCP Resources
KB_PATH = pathlib.Path(os.environ.get("KB_PATH", "./knowledge_base")).resolve()

# ---------------------------------------------------------------------------
# FastMCP server instance
# The name appears in MCP Inspector and client discovery
# ---------------------------------------------------------------------------
mcp = FastMCP("azure-openai-server")


# ===========================================================================
# TASK 1: Tools
# ===========================================================================

@mcp.tool()
def count_tokens(text: str) -> int:
    """
    Count the number of tokens in the given text using the cl100k_base encoding.

    This is a local operation — no API call is made. Use this to estimate costs
    before sending large payloads to Azure OpenAI.

    Args:
        text: The text to count tokens for.

    Returns:
        Integer token count.
    """
    # tiktoken is the same tokenizer used by GPT-4o and GPT-4o-mini
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

    Use this when you need the LLM to generate text, answer a question, or
    perform a reasoning task. For simple queries, prefer search_azure_openai.

    Args:
        user_message: The user's message to send to the model.
        system_message: The system prompt that defines the assistant's behavior.
            Defaults to a generic helpful assistant.
        temperature: Sampling temperature 0.0–1.0. Use 0 for deterministic output,
            higher values for creative tasks. Default 0.
        max_tokens: Maximum tokens in the response. Default 500.

    Returns:
        The assistant's reply as a plain string.
    """
    # TODO: Implement the chat completion call using httpx
    # Hint: POST to CHAT_URL with {"messages": [...], "temperature": ..., "max_tokens": ...}
    # Return response["choices"][0]["message"]["content"]
    raise NotImplementedError("Task 1: implement chat_completion")


@mcp.tool()
def search_azure_openai(query: str, max_tokens: int = 300) -> str:
    """
    Convenience wrapper: ask Azure OpenAI a question and return the answer.

    Use this for quick single-turn queries where you just want an answer.
    For multi-turn conversations or custom system prompts, use chat_completion.

    Args:
        query: The question or task to send to Azure OpenAI.
        max_tokens: Maximum tokens in the response. Default 300.

    Returns:
        The model's response as a plain string.
    """
    # TODO: Implement as a thin wrapper over chat_completion
    # Use a system message like: "Answer concisely and precisely."
    raise NotImplementedError("Task 1: implement search_azure_openai")


@mcp.tool()
def embed_text(text: str) -> list[float]:
    """
    Generate an embedding vector for the given text using Azure OpenAI.

    Embeddings represent text as a dense numeric vector. Use these for:
    - Semantic similarity comparisons
    - Storing in a vector database (e.g., Azure AI Search)
    - Clustering or classification tasks

    Args:
        text: The text to embed. Keep under 8,000 tokens for best results.

    Returns:
        A list of floats representing the embedding vector (1536 dimensions for
        text-embedding-3-small).
    """
    # TODO: Implement embedding call
    # POST to EMBED_URL with {"input": text}
    # Return response["data"][0]["embedding"]
    # Note: you may need a different deployment name for the embedding model.
    # Check your Azure OpenAI resource for available deployments.
    raise NotImplementedError("Task 1: implement embed_text")


@mcp.tool()
def list_models() -> list[dict]:
    """
    List all model deployments available in the Azure OpenAI account.

    Use this to discover what models are available before deciding which
    deployment to target in chat_completion.

    Returns:
        List of deployment objects, each with 'id', 'model', and 'status' fields.
    """
    # TODO: GET MODELS_URL, return the list of model objects
    # response["data"] contains the deployment list
    raise NotImplementedError("Task 1: implement list_models")


# ===========================================================================
# TASK 2: Resources — Knowledge Base
# ===========================================================================

@mcp.resource("kb:///index")
def kb_index() -> str:
    """
    List all documents available in the knowledge base.

    Returns a newline-separated list of available filenames.
    Clients can use these filenames with the kb:///{filename} resource.
    """
    # TODO: List all .md and .txt files in KB_PATH
    # Return them as a formatted string, one filename per line
    # Handle the case where KB_PATH does not exist
    raise NotImplementedError("Task 2: implement kb_index")


@mcp.resource("kb:///{filename}")
def kb_document(filename: str) -> str:
    """
    Return the contents of a knowledge base document.

    Args:
        filename: The document filename (e.g., 'intro.md', 'faq.txt').
            Use kb:///index first to discover available files.

    Returns:
        The full text content of the document.
    """
    # TODO: Read and return the file at KB_PATH / filename
    # IMPORTANT: validate the path to prevent directory traversal
    # (safe_path = (KB_PATH / filename).resolve() — check it starts with KB_PATH)
    # Raise mcp_types.McpError(mcp_types.ErrorCode.InvalidParams, ...) on bad path
    # Raise mcp_types.McpError(mcp_types.ErrorCode.InternalError, ...) if file not found
    raise NotImplementedError("Task 2: implement kb_document")


@mcp.tool()
def list_kb_documents() -> list[str]:
    """
    List all documents available in the knowledge base.

    Use this tool to discover what knowledge base documents exist before
    requesting their content via the kb:///{filename} resource.

    Returns:
        List of filenames available in the knowledge base.
    """
    # TODO: Return a list of filenames from KB_PATH
    # This duplicates kb_index but as a Tool (callable by the LLM in tool-call mode)
    # vs a Resource (readable as content via resources/read)
    raise NotImplementedError("Task 2: implement list_kb_documents")


# ===========================================================================
# TASK 3: Prompts
# ===========================================================================

@mcp.prompt()
def code_review(diff: str, language: str, focus_area: str = "all") -> list[Message]:
    """
    Generate a structured code review prompt.

    Args:
        diff: The unified diff output to review (from `git diff`).
        language: The programming language of the changed code
            (e.g., 'python', 'typescript', 'go', 'rust').
        focus_area: What aspect to focus on:
            - 'security' — look for vulnerabilities, injection risks, auth issues
            - 'performance' — look for inefficiencies, N+1 queries, memory issues
            - 'correctness' — look for bugs, edge cases, incorrect logic
            - 'all' — comprehensive review (default)

    Returns:
        A list of messages that, when sent to an LLM, produce a structured review.
    """
    # TODO: Build and return a list[Message] that sets up the code review.
    # The message should include:
    # - A clear instruction to perform a code review
    # - The language and focus area as context
    # - The diff content in a code block
    # - A requested output format: (1) summary, (2) issues with severity, (3) suggestions
    #
    # Example structure:
    # return [
    #     Message(
    #         role="user",
    #         content=TextContent(type="text", text=f"...")
    #     )
    # ]
    raise NotImplementedError("Task 3: implement code_review prompt")


@mcp.prompt()
def summarize(content: str, max_words: int = 150) -> list[Message]:
    """
    Generate a summarization prompt.

    Args:
        content: The text content to summarize.
        max_words: Target length of the summary in words. Default 150.

    Returns:
        A list of messages that, when sent to an LLM, produce a concise summary.
    """
    # TODO: Build and return a list[Message] that instructs the LLM to:
    # - Summarize the content concisely
    # - Stay within max_words words
    # - Preserve the key points and any important numbers or names
    raise NotImplementedError("Task 3: implement summarize prompt")


# ===========================================================================
# Entrypoint
# ===========================================================================

if __name__ == "__main__":
    # Run with stdio transport (default)
    # To use HTTP+SSE instead (Module 15): mcp.run(transport="sse", host="0.0.0.0", port=8080)
    mcp.run()
