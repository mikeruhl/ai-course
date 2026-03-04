# Module 14: Building MCP Servers

**Week 9 · Phase 4 — MCP Deep Dive**

---

## Learning Objectives

By the end of this module you will:

- Build production-quality MCP servers using the Python `mcp` SDK
- Implement all three MCP primitives: Tools, Resources, and Prompts
- Build an MCP server that wraps Azure OpenAI (giving any MCP client LLM access)
- Build an MCP server that wraps Azure AI Search (from module 09)
- Understand stdio vs HTTP transports and when to use each
- Write proper tool schemas that guide client LLMs to correct usage

---

## Prerequisites

- Module 01 (Azure OpenAI) infrastructure still running, or re-provisioned
- Module 09 (RAG / Azure AI Search) infrastructure and familiarity with the Search SDK
- `uv` installed and working
- MCP Inspector installed: `npx @modelcontextprotocol/inspector`

---

## Concepts

### What MCP Actually Is

The Model Context Protocol (MCP) is a JSON-RPC 2.0 based protocol that standardises
how LLM clients discover and call capabilities (tools, resources, prompts) exposed
by external servers. Think of it as a typed, discoverable API contract optimised for
LLM consumption.

Before MCP, every agent framework invented its own tool-calling format. Claude had
one schema, OpenAI had another, LangChain had a third. MCP is the attempt to fix that:
write a server once, any compliant client can use it.

The protocol defines three primitive types. Everything in MCP is one of these three.

### Primitive 1: Tools

Tools are callable functions. The client LLM decides when to call them based on
the tool schema (description + JSON Schema for arguments).

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-server")

@mcp.tool()
def count_tokens(text: str) -> int:
    """Count the number of tokens in the given text using the cl100k_base encoding."""
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))
```

The decorator does three things:
1. Registers the function in the server's tool registry
2. Generates a JSON Schema from the type annotations
3. Uses the docstring as the tool description (what the LLM reads to decide whether to call it)

**Tool schema quality is a first-class concern.** A vague description produces random
tool calls. A precise description with concrete examples produces reliable tool calls.
Treat your docstrings as API contracts for LLMs.

Error handling in tools: raise `mcp.types.McpError` with appropriate error codes:

```python
from mcp import types as mcp_types

@mcp.tool()
def read_file(path: str) -> str:
    """Read a file from the knowledge base. Path must be relative, e.g. 'docs/intro.md'."""
    import pathlib
    safe_base = pathlib.Path("/kb")
    target = (safe_base / path).resolve()
    if not str(target).startswith(str(safe_base)):
        raise mcp_types.McpError(
            mcp_types.ErrorCode.InvalidParams,
            f"Path traversal detected: {path}"
        )
    return target.read_text()
```

MCP error codes: `InvalidParams` (bad arguments), `InternalError` (server fault),
`MethodNotFound` (no such tool), `InvalidRequest` (malformed request).

Return types: `str`, `int`, `float`, `bool`, `list`, `dict`, or explicitly typed
`TextContent`, `ImageContent`, `EmbeddedResource`. For most tools returning text,
a plain `str` is sufficient — the SDK wraps it in `TextContent` automatically.

### Primitive 2: Resources

Resources are URI-addressable content that the client can read. They are analogous
to GET endpoints — read-only, identified by a URI, returning content that the LLM
can include in its context.

```python
@mcp.resource("kb:///{filename}")
def get_kb_document(filename: str) -> str:
    """Return the contents of a knowledge base document."""
    import pathlib
    path = pathlib.Path("knowledge_base") / filename
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {filename}")
    return path.read_text()
```

The URI template `kb:///{filename}` defines the addressing scheme. Clients can
list resources (`resources/list`) and read them (`resources/read`). Static resources
have fixed URIs; dynamic resources use parameterised templates.

Resource subscriptions: clients can subscribe to a resource URI and receive
notifications when its content changes. This is how an MCP server powering a live
dashboard works — the server pushes updates rather than the client polling.

When to use Resources vs Tools:
- **Resources** — read-only content that the LLM wants to include in context
  (documents, configs, data files, API responses)
- **Tools** — actions that have side effects or require arguments to compute
  (write file, search, create record, call external API)

### Primitive 3: Prompts

Prompts are reusable message templates. The client requests a prompt by name,
passes argument values, and receives back a list of `Message` objects ready to
pass to an LLM.

```python
from mcp.types import Message, TextContent

@mcp.prompt()
def code_review(diff: str, language: str, focus_area: str = "all") -> list[Message]:
    """
    A structured code review prompt.

    Args:
        diff: The unified diff to review
        language: Programming language (python, typescript, go, etc.)
        focus_area: What to focus on: security | performance | correctness | all
    """
    return [
        Message(
            role="user",
            content=TextContent(
                type="text",
                text=(
                    f"Please review the following {language} code diff.\n"
                    f"Focus area: {focus_area}\n\n"
                    f"```diff\n{diff}\n```\n\n"
                    "Respond with: (1) summary of changes, (2) issues found with severity, "
                    "(3) suggested improvements."
                )
            )
        )
    ]
```

Prompts are valuable for:
- Standardising task templates across a team (everyone uses the same code_review format)
- Storing prompt logic server-side so clients don't need to know the details
- Version-controlling prompts alongside the server code that generated the context

### The FastMCP vs Low-Level API

The `mcp` SDK ships two layers:

| Layer | Class | Use when |
|---|---|---|
| High-level | `FastMCP` | 95% of cases — handles JSON-RPC, schema gen, transport |
| Low-level | `Server` | You need direct protocol control (custom transport, request interception) |

Always start with `FastMCP`. Drop to `Server` only when you have a specific reason.

### Transport Selection

MCP supports two transports:

**stdio** (standard input/output):
- Server process is spawned by the client, communicates over stdin/stdout
- No network, no auth, no TLS — the OS process model is the security boundary
- Best for: local tools (Claude Desktop, VS Code plugins, CLI agents)
- Latency: microseconds (IPC)

**HTTP + SSE** (Server-Sent Events):
- Server runs as a persistent HTTP service
- Two endpoints: `POST /messages` (client sends requests), `GET /sse` (server pushes responses)
- Supports multiple simultaneous clients
- Requires auth (Bearer tokens) for remote deployments
- Best for: shared team servers, cloud deployments, multi-user environments
- Module 15 deploys HTTP+SSE to Azure Container Apps

Converting from stdio to HTTP+SSE is literally changing the last two lines of your
server file. The tool/resource/prompt logic is identical.

```python
# stdio
mcp.run()  # reads from stdin, writes to stdout

# HTTP+SSE
mcp.run(transport="sse", host="0.0.0.0", port=8080)
```

### Wrapping Azure OpenAI as an MCP Server

This pattern is powerful: you expose Azure OpenAI capabilities as MCP tools so that
any MCP client (even one that uses a different LLM) gets access to OpenAI's models.

```
Claude Desktop -> MCP Server (your code) -> Azure OpenAI
VS Code Agent  -> MCP Server (your code) -> Azure OpenAI
Custom client  -> MCP Server (your code) -> Azure OpenAI
```

This is composability: your MCP server becomes a capability layer others can build on.

### Tool Schema Design for LLMs

The LLM (the MCP client's model) reads your tool schemas to decide which tool to
call and with what arguments. Schema quality directly affects reliability.

Bad schema:
```python
@mcp.tool()
def search(q: str) -> str:
    """Search."""
    ...
```

Good schema:
```python
@mcp.tool()
def search_documents(
    query: str,
    max_results: int = 5,
    filter_field: str | None = None,
    filter_value: str | None = None,
) -> list[dict]:
    """
    Search the Azure AI Search index for documents matching the query.

    Use this when the user asks about topics in the knowledge base, wants to find
    documents, or asks questions that require looking up stored information.

    Args:
        query: Natural language search query. Be specific — include relevant terms.
        max_results: Number of results to return (1-20, default 5).
        filter_field: Optional field name to filter on (e.g. 'category', 'author').
        filter_value: Value for the filter field. Required if filter_field is set.

    Returns:
        List of matching documents with id, title, content (snippet), and score fields.
    """
    ...
```

Rules for good tool schemas:
1. Name is a verb phrase describing what the tool does (`search_documents` not `search`)
2. Description answers: when should I call this? what does it do? what does it return?
3. All parameters have types and docstring descriptions
4. Optional parameters have sensible defaults
5. Return type and structure are documented so the LLM can interpret the result

---

## Azure Setup

This module reuses the Azure OpenAI deployment from Module 01. No new infrastructure.

If you tore down Module 01's Terraform:

```bash
cd modules/module-01-llm-primitive/terraform
terraform apply   # re-provision
```

For the search MCP server (Task 4), you also need the Azure AI Search index from
Module 09. If that's not available, you can skip Task 4 or mock the search client.

---

## Lab

### Setup

```bash
cd modules/module-14-mcp-servers/lab
cp .env.example .env
# Fill in .env with your Azure OpenAI values from module-01 terraform output
uv sync
```

### Install MCP Inspector (one-time)

```bash
npm install -g @modelcontextprotocol/inspector
# or use npx each time: npx @modelcontextprotocol/inspector
```

### Task 1: Build the Azure OpenAI MCP Server (5 tools)

File: `lab/src/openai_server.py`

Build an MCP server with these five tools:

| Tool | Description |
|---|---|
| `chat_completion` | Send messages to Azure OpenAI, return the assistant reply |
| `embed_text` | Embed a string, return the vector as a list of floats |
| `count_tokens` | Count tokens in text using tiktoken (no API call) |
| `list_models` | List available deployments from the Azure OpenAI account |
| `search_azure_openai` | Query the Azure OpenAI API with a single user message (convenience wrapper) |

Test with MCP Inspector:
```bash
npx @modelcontextprotocol/inspector uv run python src/openai_server.py
```

The Inspector UI will appear. Verify each tool appears in the "Tools" tab and
can be called successfully.

### Task 2: Add Resources (Knowledge Base)

File: `lab/src/openai_server.py` (extend) or `lab/src/kb_resources.py`

Add a `knowledge_base/` directory with three markdown files. Expose them as
resources using the URI scheme `kb:///{filename}`.

Implement:
- A static resource `kb:///index` that lists all available documents
- A dynamic resource `kb:///{filename}` that returns document content
- A tool `list_kb_documents` that returns available filenames (so the LLM
  can discover what to request as resources)

Verify in MCP Inspector: the "Resources" tab should show your documents.

### Task 3: Add Prompts

File: `lab/src/openai_server.py` (extend)

Add two prompts:

**`code_review` prompt**: args: `diff` (str), `language` (str), `focus_area` (str, default "all")
Returns a message list that sets up a structured code review.

**`summarize` prompt**: args: `content` (str), `max_words` (int, default 150)
Returns a message list instructing the LLM to summarise content concisely.

Verify in MCP Inspector: both prompts appear in the "Prompts" tab and return
correctly structured messages when called with arguments.

### Task 4: Build the Azure AI Search MCP Server

File: `lab/src/search_server.py`

Build a separate MCP server wrapping Azure AI Search with these tools:

| Tool | Args | Description |
|---|---|---|
| `search` | query, top (default 5), filter (optional) | Full-text + vector hybrid search |
| `index_document` | id, title, content, metadata (dict) | Add or update a document in the index |
| `delete_document` | document_id | Remove a document by ID |
| `list_indices` | — | List all indices in the search service |
| `get_document` | document_id | Retrieve a specific document by ID |

Add the Azure AI Search variables to `.env.example`:
```
AZURE_SEARCH_ENDPOINT=https://<name>.search.windows.net
AZURE_SEARCH_KEY=<admin-key>
AZURE_SEARCH_INDEX=<index-name>
```

### Task 5: Write Integration Tests

File: `lab/src/test_servers.py`

Use the `mcp` Python SDK as a client (not just a server) to test your servers
programmatically. The SDK provides a client interface:

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def test_openai_server():
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "python", "src/openai_server.py"],
        env=dict(os.environ)
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # List tools
            tools = await session.list_tools()
            assert len(tools.tools) >= 5
            # Call count_tokens
            result = await session.call_tool("count_tokens", {"text": "hello world"})
            assert result.content[0].text == "2"
```

Write tests for:
- All 5 tools on the OpenAI server (at minimum: assert they return without error)
- Resource listing and reading on the KB server
- Prompt generation for both prompts
- Error handling: call a tool with invalid args, assert the error response is correct

Run: `uv run pytest src/test_servers.py -v`

---

## Checkpoints

After each task, verify:

- [ ] Task 1: All 5 tools visible and callable in MCP Inspector
- [ ] Task 2: `kb:///index` resource returns a document list; `kb:///{filename}` returns content
- [ ] Task 3: Both prompts return valid message lists with correct roles
- [ ] Task 4: `search` tool returns results from your Azure AI Search index
- [ ] Task 5: All integration tests pass (`pytest -v`)

Final checkpoint: your MCP server is a reusable capability layer. Any MCP client
can discover and use your tools without knowing they're backed by Azure OpenAI.
This is the key architecture insight of MCP.

---

## Key Concepts Summary

| Concept | One-line summary |
|---|---|
| Tool | A callable function the LLM invokes; has side effects; uses JSON Schema |
| Resource | URI-addressable read-only content the LLM includes in context |
| Prompt | A reusable message template with typed argument slots |
| FastMCP | High-level SDK class; handles JSON-RPC, schema gen, transport wiring |
| stdio transport | IPC via stdin/stdout; local only; no auth needed |
| HTTP+SSE transport | Network transport; supports remote/multi-client; requires auth |
| Tool schema quality | Docstring + type annotations directly impact LLM reliability |

---

## Resources

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Specification](https://spec.modelcontextprotocol.io)
- [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
- [FastMCP documentation](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs)
- [Azure OpenAI REST API reference](https://learn.microsoft.com/en-us/azure/ai-services/openai/reference)
- [Azure AI Search Python SDK](https://learn.microsoft.com/en-us/python/api/overview/azure/search-documents-readme)
