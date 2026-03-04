"""
Module 14 Lab — MCP Server wrapping Azure AI Search (Task 4)
=============================================================
This server exposes Azure AI Search operations as MCP Tools, allowing any
MCP client to index, search, retrieve, and delete documents without knowing
the Azure Search SDK.

Run with MCP Inspector:
    npx @modelcontextprotocol/inspector uv run python src/search_server.py

Requires: AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, AZURE_SEARCH_INDEX in .env
"""

import os
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SearchFieldDataType,
    SimpleField,
    SearchableField,
)
from dotenv import load_dotenv
from mcp import types as mcp_types
from mcp.server.fastmcp import FastMCP

load_dotenv()

# ---------------------------------------------------------------------------
# Azure AI Search configuration
# ---------------------------------------------------------------------------
SEARCH_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
SEARCH_KEY = os.environ.get("AZURE_SEARCH_KEY", "")
INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX", "mcp-lab-index")

def _get_search_client() -> SearchClient:
    """Create and return an Azure AI Search client. Raises on missing config."""
    if not SEARCH_ENDPOINT or not SEARCH_KEY:
        raise mcp_types.McpError(
            mcp_types.ErrorCode.InternalError,
            "Azure Search not configured. Set AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY in .env"
        )
    return SearchClient(
        endpoint=SEARCH_ENDPOINT,
        index_name=INDEX_NAME,
        credential=AzureKeyCredential(SEARCH_KEY),
    )


def _get_index_client() -> SearchIndexClient:
    """Create and return an Azure AI Search index management client."""
    if not SEARCH_ENDPOINT or not SEARCH_KEY:
        raise mcp_types.McpError(
            mcp_types.ErrorCode.InternalError,
            "Azure Search not configured."
        )
    return SearchIndexClient(
        endpoint=SEARCH_ENDPOINT,
        credential=AzureKeyCredential(SEARCH_KEY),
    )


# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP("azure-search-server")


# ===========================================================================
# TASK 4: Azure AI Search Tools
# ===========================================================================

@mcp.tool()
def search(
    query: str,
    top: int = 5,
    filter: str | None = None,
) -> list[dict]:
    """
    Search the Azure AI Search index for documents matching the query.

    Use this when the user asks about topics in the knowledge base, wants to
    find documents, or asks questions that require looking up stored information.

    Args:
        query: Natural language search query. Be specific and include relevant terms.
        top: Number of results to return (1–20). Default 5.
        filter: Optional OData filter expression, e.g. "category eq 'docs'".
            Leave None for unfiltered search.

    Returns:
        List of matching documents. Each document has: id, title, content
        (a snippet), score (relevance 0–1), and any other indexed fields.
    """
    # TODO: Use _get_search_client() to perform the search
    # client.search(search_text=query, top=top, filter=filter)
    # Convert results to a list of dicts (iterate the result set)
    # Include at minimum: id, title, content (truncated to 500 chars), @search.score
    raise NotImplementedError("Task 4: implement search")


@mcp.tool()
def index_document(
    doc_id: str,
    title: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> dict:
    """
    Add or update a document in the Azure AI Search index.

    Use this to add new content to the searchable knowledge base. If a document
    with the same id already exists, it will be overwritten (upsert semantics).

    Args:
        doc_id: Unique identifier for the document (e.g., 'doc-001', 'readme-main').
            Must be URL-safe: alphanumeric, hyphens, underscores only.
        title: Human-readable title for the document.
        content: The full text content to index and make searchable.
        metadata: Optional dict of additional fields to store alongside the document
            (e.g., {"author": "Alice", "category": "tutorial"}).

    Returns:
        A result dict with 'key' (document id) and 'succeeded' (bool).
    """
    # TODO: Use _get_search_client() to upload the document
    # Build the document dict: {"id": doc_id, "title": title, "content": content}
    # Merge metadata if provided
    # client.upload_documents(documents=[document])
    # Return the result from the upload operation
    raise NotImplementedError("Task 4: implement index_document")


@mcp.tool()
def delete_document(document_id: str) -> dict:
    """
    Remove a document from the Azure AI Search index by its ID.

    Use this to remove outdated or incorrect documents from the knowledge base.

    Args:
        document_id: The unique ID of the document to delete (same id used
            when the document was indexed).

    Returns:
        A result dict with 'key' (document id) and 'succeeded' (bool).
    """
    # TODO: Use _get_search_client() to delete the document
    # client.delete_documents(documents=[{"id": document_id}])
    raise NotImplementedError("Task 4: implement delete_document")


@mcp.tool()
def get_document(document_id: str) -> dict:
    """
    Retrieve a specific document from the search index by its exact ID.

    Use this when you know the document ID and want its full content, not a
    search ranking. For keyword search, use the search tool instead.

    Args:
        document_id: The unique ID of the document to retrieve.

    Returns:
        The full document dict with all indexed fields, or an error if not found.
    """
    # TODO: Use _get_search_client() to get the document
    # client.get_document(key=document_id)
    # Catch azure.core.exceptions.ResourceNotFoundError and raise McpError
    raise NotImplementedError("Task 4: implement get_document")


@mcp.tool()
def list_indices() -> list[str]:
    """
    List all search index names available in the Azure AI Search service.

    Use this to discover what indices exist before performing a search.
    This is an administrative operation — it shows all indices, not documents.

    Returns:
        List of index name strings.
    """
    # TODO: Use _get_index_client() to list indices
    # index_client.list_index_names() returns an iterator of name strings
    raise NotImplementedError("Task 4: implement list_indices")


# ===========================================================================
# Entrypoint
# ===========================================================================

if __name__ == "__main__":
    mcp.run()
