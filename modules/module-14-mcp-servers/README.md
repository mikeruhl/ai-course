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

**Goal:** Implement five MCP tools that wrap Azure OpenAI, making its capabilities discoverable and callable by any MCP client.

**What to do:**
1. Open `lab/src/openai_server.py` — find the `# TASK 1: Tools` section (around line 53)
2. Implement the five `@mcp.tool()` functions:
   - `count_tokens` — already complete; uses `tiktoken.get_encoding("cl100k_base")` locally
   - `chat_completion` — POST to `CHAT_URL` with messages, temperature, max_tokens via `httpx`; return `response["choices"][0]["message"]["content"]`
   - `search_azure_openai` — thin wrapper that calls `chat_completion` with a concise system message
   - `embed_text` — POST to `EMBED_URL` with `{"input": text}`; return `response["data"][0]["embedding"]`
   - `list_models` — GET `MODELS_URL`; return `response["data"]`
3. Run:
   ```bash
   npx @modelcontextprotocol/inspector uv run python src/openai_server.py
   ```

**Expected result:**
- MCP Inspector opens in the browser showing 5 tools in the "Tools" tab
- Calling `count_tokens` with text `"hello world"` returns `2`
- Calling `chat_completion` with `user_message="Say hello"` returns a greeting from the model
- Calling `list_models` returns a JSON array of deployment objects like `[{"id": "gpt-4o-mini", "model": "gpt-4o-mini", ...}]`

**Why this matters:**
- Wrapping Azure OpenAI as MCP tools decouples LLM access from client implementation. Any MCP-compliant client (Claude Desktop, VS Code, custom agents) can discover and call your tools without knowing the Azure SDK or endpoint details. This is the composability pattern MCP enables.

### Task 2: Add Resources (Knowledge Base)

**Goal:** Expose a local knowledge base as MCP Resources, demonstrating the difference between read-only content (Resources) and callable actions (Tools).

**What to do:**
1. Create a `lab/knowledge_base/` directory with 2-3 markdown files (e.g., `intro.md`, `faq.md`, `architecture.md`)
2. Open `lab/src/openai_server.py` — find the `# TASK 2: Resources` section (around line 167)
3. Implement three functions:
   - `kb_index()` — decorated with `@mcp.resource("kb:///index")`. List all `.md` and `.txt` files in `KB_PATH`, return filenames as a newline-separated string. Handle `KB_PATH` not existing.
   - `kb_document(filename)` — decorated with `@mcp.resource("kb:///{filename}")`. Read `KB_PATH / filename`. Validate path with `resolve()` + `is_relative_to(KB_PATH)` to block traversal. Raise `mcp_types.McpError` on bad paths or missing files.
   - `list_kb_documents()` — decorated with `@mcp.tool()`. Return a `list[str]` of filenames (duplicates `kb_index` but as a tool so the LLM can call it during tool-use mode).
4. Run:
   ```bash
   npx @modelcontextprotocol/inspector uv run python src/openai_server.py
   ```

**Expected result:**
- The "Resources" tab in Inspector shows `kb:///index`
- Reading `kb:///index` returns something like: `intro.md\nfaq.md\narchitecture.md`
- Reading `kb:///intro.md` returns the file content
- The `list_kb_documents` tool appears in the "Tools" tab and returns `["intro.md", "faq.md", "architecture.md"]`

**Why this matters:**
- Resources are how MCP servers expose contextual data the LLM can pull into its context window — documents, configs, data snapshots. Providing both a Resource and a Tool for discovery gives clients flexibility: some clients support resource listing, others only support tool calls. Path validation here is a preview of the security hardening in Module 16.

### Task 3: Add Prompts

**Goal:** Implement reusable prompt templates as MCP Prompts, enabling clients to request pre-structured message lists for common tasks.

**What to do:**
1. Open `lab/src/openai_server.py` — find the `# TASK 3: Prompts` section (around line 222)
2. Implement two `@mcp.prompt()` functions:
   - `code_review(diff, language, focus_area="all")` — return a `list[Message]` with a single `Message(role="user", content=TextContent(...))` that includes the language, focus area, the diff in a code block, and a requested output format (summary, issues with severity, suggestions)
   - `summarize(content, max_words=150)` — return a `list[Message]` instructing the LLM to summarize within the word limit, preserving key points and numbers
3. Run:
   ```bash
   npx @modelcontextprotocol/inspector uv run python src/openai_server.py
   ```

**Expected result:**
- The "Prompts" tab in Inspector shows `code_review` and `summarize`
- Calling `code_review` with `diff="- old\n+ new"`, `language="python"`, `focus_area="security"` returns a message list like:
  ```json
  [{"role": "user", "content": {"type": "text", "text": "Please review the following python code diff.\nFocus area: security\n\n```diff\n- old\n+ new\n```\n\nRespond with: (1) summary, (2) issues with severity, (3) suggestions."}}]
  ```
- Calling `summarize` with `content="Long text..."`, `max_words=50` returns a message mentioning the 50-word limit

**Why this matters:**
- Prompts let teams standardize how they interact with LLMs — everyone uses the same code review format, the same summarization template. Version-controlling prompts alongside server code means prompt changes are reviewable, testable, and deployable like any other code change.

### Task 4: Build the Azure AI Search MCP Server

**Goal:** Build a second MCP server that wraps Azure AI Search, demonstrating how MCP servers can expose any backend service as discoverable tools.

**What to do:**
1. Open `lab/src/search_server.py` — find the `# TASK 4: Azure AI Search Tools` section (around line 74)
2. Implement five `@mcp.tool()` functions using the helper clients `_get_search_client()` and `_get_index_client()`:
   - `search(query, top=5, filter=None)` — call `client.search(search_text=query, top=top, filter=filter)`, iterate results into a list of dicts with id, title, content (truncated to 500 chars), and `@search.score`
   - `index_document(doc_id, title, content, metadata=None)` — build a document dict, merge metadata if provided, call `client.upload_documents(documents=[doc])`
   - `delete_document(document_id)` — call `client.delete_documents(documents=[{"id": document_id}])`
   - `get_document(document_id)` — call `client.get_document(key=document_id)`, catch `ResourceNotFoundError` and raise `McpError`
   - `list_indices()` — call `index_client.list_index_names()`, collect into a list of strings
3. Add to `.env`:
   ```
   AZURE_SEARCH_ENDPOINT=https://<name>.search.windows.net
   AZURE_SEARCH_KEY=<admin-key>
   AZURE_SEARCH_INDEX=<index-name>
   ```
4. Run:
   ```bash
   npx @modelcontextprotocol/inspector uv run python src/search_server.py
   ```

**Expected result:**
- Inspector shows 5 tools: `search`, `index_document`, `delete_document`, `get_document`, `list_indices`
- Calling `list_indices` returns `["mcp-lab-index"]` (or your index name)
- Calling `search` with `query="test"` returns a list like:
  ```json
  [{"id": "doc-001", "title": "Test Doc", "content": "...", "score": 0.82}]
  ```
- Calling `index_document` with a new doc and then `get_document` with the same ID retrieves it

**Why this matters:**
- This pattern — wrapping a backend service as MCP tools — is how teams share infrastructure capabilities across agents. A search MCP server lets any agent search your knowledge base without importing the Azure SDK or managing credentials directly. The server becomes the capability boundary.

### Task 5: Write Integration Tests

**Goal:** Test MCP servers programmatically using the SDK's client interface, proving the server contract works end-to-end over stdio transport.

**What to do:**
1. Open `lab/src/test_servers.py` — the file defines `connected_session()` (line 54), a context manager that spawns a server subprocess and returns an initialized `ClientSession`
2. Implement the test functions across five groups:
   - **5a** (`test_openai_server_has_required_tools`, line 67) — assert `expected_tools` is a subset of registered tool names from `session.list_tools()`
   - **5a** (`test_openai_server_has_resources`, line 86) — assert `"kb:///index"` appears in `session.list_resources()` URIs
   - **5a** (`test_openai_server_has_prompts`, line 97) — assert `{"code_review", "summarize"}` is a subset of registered prompt names
   - **5b** (`test_count_tokens_basic`, line 111) — call `session.call_tool("count_tokens", {"text": "hello world"})`, assert `result.content[0].text == "2"`
   - **5b** (`test_count_tokens_empty_string`, line 120) — same pattern, assert result is `"0"`
   - **5c** (`test_kb_index_resource`, line 134) — call `session.read_resource("kb:///index")`, assert content is non-empty
   - **5d** (`test_code_review_prompt`, line 148) — call `session.get_prompt("code_review", arguments={...})`, assert at least one message with role `"user"` containing `"python"`
   - **5d** (`test_summarize_prompt`, line 167) — assert `"50"` appears in the prompt message text
   - **5e** (`test_invalid_tool_arguments`, line 184) — call `count_tokens` with `{"text": 12345}`, assert an error response (check `result.isError`)
   - **5f** (`test_chat_completion`, line 199) — marked `@pytest.mark.azure`, calls `chat_completion` and asserts a non-empty response
   - **5f** (`test_search_server_tools`, line 211) — verifies all 5 search tools are registered
3. Run:
   ```bash
   uv run pytest src/test_servers.py -v           # structural tests only
   uv run pytest src/test_servers.py -v -m azure  # include Azure API tests
   ```

**Expected result:**
- Structural tests (5a-5e) pass without Azure credentials since they test registration and local tools:
  ```
  test_openai_server_has_required_tools PASSED
  test_openai_server_has_resources PASSED
  test_openai_server_has_prompts PASSED
  test_count_tokens_basic PASSED
  test_count_tokens_empty_string PASSED
  test_kb_index_resource PASSED
  test_code_review_prompt PASSED
  test_summarize_prompt PASSED
  test_invalid_tool_arguments PASSED
  ```
- Azure-marked tests pass when credentials are configured

**Why this matters:**
- The same MCP SDK that builds servers also tests them. This means your CI pipeline can verify MCP contract compliance (tool names, schemas, return types) without deploying. Structural tests catch regressions like renamed tools or changed argument schemas before they break downstream clients.

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
