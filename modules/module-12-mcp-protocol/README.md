# Module 12: MCP Protocol

## Overview

MCP (Model Context Protocol) is Anthropic's open standard for connecting AI
models to external tools and data. Where the OpenAI function-calling API
bakes tools into each application, MCP defines a reusable server that any
MCP-compatible client can connect to. This module builds an MCP server with
all three primitives — Tools, Resources, and Prompts — using the official
Python SDK, and tests it with both the MCP Inspector and Claude Desktop.

By the end: you have a working MCP server that exposes filesystem capabilities,
connects to Claude Desktop, and demonstrates the difference between MCP and
the ad-hoc tool calling you've been doing.

---

## Concepts

### 1. What MCP Is

MCP separates capability exposure from application logic:

**Without MCP (what you built in Modules 1-9):**
```
Your App
  ├── LLM call logic
  ├── Tool definitions (JSON schemas)
  ├── Tool execution (Python functions)
  └── All tightly coupled
```

**With MCP:**
```
MCP Server (reusable, shareable)
  ├── Tool: read_file
  ├── Tool: search_files
  ├── Resource: /course/files
  └── Prompt: code-review-template

MCP Client (your app, Claude Desktop, VS Code, etc.)
  ├── Connects to MCP server
  ├── Discovers capabilities automatically
  └── Calls tools/resources/prompts via standard protocol
```

The MCP server can be shared across teams, published for others to use, or
connected to multiple clients simultaneously. This is the same value
proposition as REST APIs, applied to AI capabilities.

---

### 2. Three MCP Primitives

#### Tools

Functions the LLM can invoke. Identical in concept to OpenAI function calling,
but now defined in the server and usable by any MCP client.

```python
@mcp.tool()
def read_file(path: str, encoding: str = "utf-8") -> str:
    """Read the contents of a file at the given path."""
    with open(path, encoding=encoding) as f:
        return f.read()
```

Key difference from function calling: the tool is defined once in the server,
not per-application. Any client connecting to this server gets the tool.

Tools are **model-controlled** — the LLM decides when to call them based on
the task.

#### Resources

Read-only data endpoints that the LLM (or the user's application) can access.
Think of them as REST GET endpoints, but registered in the MCP server.

```python
@mcp.resource("course://modules/{module_id}/readme")
def get_module_readme(module_id: str) -> str:
    """Get the README for a specific course module."""
    path = f"modules/module-{module_id}/README.md"
    with open(path) as f:
        return f.read()
```

Resources differ from tools: they're **application-controlled**, not
model-controlled. The client application decides which resources to read and
pass to the model as context. Resources don't get invoked during tool-calling
loops — they're fetched upfront and included in the prompt.

Common resource patterns:
- File system browsing
- Database record retrieval
- Configuration reading
- API response caching

#### Prompts

Reusable prompt templates with typed parameters. The LLM or client requests
a prompt template, fills in parameters, and uses the resulting messages.

```python
@mcp.prompt()
def code_review_prompt(diff: str, context: str = "") -> list[dict]:
    """Generate a code review prompt for the given diff."""
    return [
        {
            "role": "user",
            "content": f"""Review this code diff and identify issues:

{f'Context: {context}' if context else ''}

Diff:
{diff}

Focus on: bugs, security vulnerabilities, performance issues, and code clarity.
Respond with a JSON object with an 'issues' array."""
        }
    ]
```

Prompts are valuable for:
- Standardizing prompts across an organization
- Making prompts discoverable (tools can list available prompts)
- Versioning prompts independently of application code

---

### 3. MCP Transports

#### stdio Transport

The MCP server runs as a subprocess. The client communicates via stdin/stdout.

```
MCP Client (e.g., Claude Desktop)
  │
  │  spawns subprocess
  ▼
MCP Server (your Python script)
  ├── reads JSON-RPC requests from stdin
  └── writes JSON-RPC responses to stdout
```

Pros: Simple to set up, zero network config, works on any OS, secure (no
network exposure), used by all IDE integrations and Claude Desktop.

Cons: Local only, single client, no remote deployment.

Use case: local tools, development, personal productivity.

#### HTTP + SSE Transport

The MCP server runs as a web service. Clients connect over HTTP.

```
MCP Client A ──┐
MCP Client B ──┼──► HTTP Server ──► MCP Server logic
MCP Client C ──┘
```

Pros: Remote deployment, multiple simultaneous clients, works across networks.

Cons: More setup, needs auth, more complex deployment.

Use case: shared team tools, production deployments, Azure Container Apps.

You'll build the HTTP transport in Module 14-15. For this module: stdio only.

---

### 4. JSON-RPC 2.0 Under the Hood

MCP uses JSON-RPC 2.0 as its message format. Understanding this helps when
debugging.

A request from client to server:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "read_file",
    "arguments": {"path": "/tmp/test.txt"}
  }
}
```

The server's response:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {"type": "text", "text": "file contents here"}
    ]
  }
}
```

The SDK handles all of this for you. But when something breaks, reading the
raw JSON-RPC messages in the MCP Inspector is how you debug it.

---

### 5. MCP Server Architecture

The Python MCP SDK gives you a `Server` object. You register handlers using
decorators, then run the server with a transport.

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

app = Server("my-server")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="read_file",
            description="Read file contents",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"}
                },
                "required": ["path"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "read_file":
        with open(arguments["path"]) as f:
            return [types.TextContent(type="text", text=f.read())]
    raise ValueError(f"Unknown tool: {name}")

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

The MCP SDK decorators (`@app.list_tools()`, `@app.call_tool()`) map JSON-RPC
methods to your Python functions. The `stdio_server()` context manager handles
the transport.

---

### 6. Connecting to Claude Desktop

Claude Desktop supports MCP servers via its config file. Add your server:

**macOS/Linux:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "course-filesystem": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/module-12-mcp-protocol/lab",
        "run",
        "mcp_server.py"
      ]
    }
  }
}
```

After saving the config and restarting Claude Desktop, your tools appear in
the tool list. You can then ask Claude to "read the README for module 10" and
it will use your MCP server to do it.

---

## Lab Tasks

### Setup

```bash
cd modules/module-12-mcp-protocol/lab
cp .env.example .env
uv sync
```

### Option B: Google Vertex AI

Use Vertex AI's OpenAI-compatible endpoint instead of Azure OpenAI for the
LLM calls. Azure-specific services (AI Search, embeddings) still require Azure.

1. Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)
2. Authenticate:
   ```bash
   gcloud auth login
   gcloud auth application-default login
   ```
3. Enable the Vertex AI API:
   ```bash
   gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID
   ```
4. Set `LLM_PROVIDER=vertex` in your `.env` file and fill in `GCP_PROJECT_ID`.

No Azure OpenAI calls in this module — the MCP server itself doesn't call LLMs.
The LLM (Claude Desktop or your own app) connects to your MCP server and calls
the tools. The `.env` is included for consistency but not required for Labs A-D.

---

### Lab 12A: MCP Client Implementation

**Goal:** Build a raw MCP client over HTTP that speaks JSON-RPC 2.0 to an MCP server — no SDK magic, so you understand the wire protocol.

**What to do:**

1. Open `lab/src/mcp_client.py`. Find the `MCPClient.initialize()` method.
   Implement the MCP initialize handshake: POST a JSON-RPC request with method
   `initialize`, then send a `notifications/initialized` notification.
   ```bash
   uv run python src/mcp_client.py --server http://localhost:3000/mcp --list-tools
   ```

2. Implement `MCPClient.list_tools()` — POST `tools/list` and extract the
   `result["tools"]` array.

3. Implement `MCPClient.call_tool(tool_name, arguments)` — POST `tools/call`
   with `{"name": tool_name, "arguments": arguments}` and concatenate
   the text content blocks from the response.

4. Implement `MCPClient.list_resources()` and `MCPClient.read_resource(uri)` —
   POST `resources/list` and `resources/read` respectively.

5. Implement `run_agent_with_mcp(query, client)` — an agentic loop that
   converts MCP tools to OpenAI function-calling format (using
   `mcp_tool_to_openai_schema()`), sends them to Azure OpenAI, and
   dispatches tool calls back through the MCP client.
   ```bash
   uv run python src/mcp_client.py --query "Read the README for module 10"
   ```

**Expected result:**
- `--list-tools` prints a rich table of tools with name and description columns
- `--query` runs the agent loop; you see tool calls dispatched (e.g., `read_file`) followed by a final text response in a green-bordered panel
- Sample output:
  ```
  ── MCP Client ──
  Server: http://localhost:3000/mcp
  Initializing...
  Server capabilities: {"tools": {}, "resources": {}}
  Available Tools:
  ┌──────────────┬────────────────────────────────┐
  │ Name         │ Description                    │
  ├──────────────┼────────────────────────────────┤
  │ read_file    │ Read file contents             │
  │ list_dir     │ List directory entries          │
  │ search_files │ Search for files by pattern    │
  └──────────────┴────────────────────────────────┘
  ```

**Why this matters:**
MCP abstracts the protocol behind SDKs. Building the raw HTTP + JSON-RPC layer first means you can debug protocol issues, write custom transports, and understand exactly what the SDK does for you — critical when MCP servers misbehave in production.

**File:** `lab/src/mcp_client.py`

---

### Lab 12B: MCP Protocol Explorer

**Goal:** Use the MCP client from Lab 12A to build an interactive protocol explorer that inspects a live server's tools, resources, and schemas.

**What to do:**

1. Open `lab/src/mcp_explore.py`. This script imports `MCPClient` from
   `mcp_client.py`, so Lab 12A tasks 1-4 must be complete first.

2. Run the explorer against a running MCP server:
   ```bash
   uv run python src/mcp_explore.py --server http://localhost:3000/mcp
   ```
   The script auto-discovers tools (via `display_tools()`) and resources
   (via `display_resources()`), printing rich tables with schemas.

3. Review `display_tools()` and `display_resources()` — these render the
   tool input schemas and resource metadata. Confirm the output matches
   the server's registered capabilities.

4. Launch interactive mode to call tools manually:
   ```bash
   uv run python src/mcp_explore.py --server http://localhost:3000/mcp -i
   ```
   The `interactive_tool_call()` function prompts you for a tool name and
   JSON arguments, then calls `client.call_tool()` and displays the result.

**Expected result:**
- The explorer prints a three-column table: Name, Description, Input Schema (formatted JSON)
- Resources table shows URI, Name, Description, MIME Type
- The first resource's content is automatically fetched and displayed (truncated to 500 chars)
- Interactive mode example:
  ```
  Available tools: read_file, list_dir, search_files
  Tool name (or 'quit'): read_file
  {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
  Arguments (JSON): {"path": "README.md"}
  Calling read_file...
  ╭─ Result ──────────────────────────────╮
  │ # Module 12: MCP Protocol ...        │
  ╰──────────────────────────────────────╯
  ```

**Why this matters:**
In production, you frequently need to inspect what an MCP server actually exposes versus what its documentation claims. An explorer tool is the MCP equivalent of Swagger UI — essential for debugging integration issues and verifying schema contracts.

**File:** `lab/src/mcp_explore.py`

---

### Lab 12C: Prompt Templates

**Goal:** Add reusable prompt templates to your MCP server so prompt engineering is centralized and discoverable.

**What to do:**

1. Open `lab/src/mcp_server.py` (you extend the server from earlier labs).
   Add a `code_review` prompt template with parameters:
   - `diff: str` (required) — the code diff to review
   - `language: str` (optional, default "python")
   - `focus: str` (optional) — specific aspect to focus on

2. Add a `summarize_module` prompt template:
   - `module_id: str` (required)
   - Internally reads the module's README using the `read_file` tool, then
     wraps the content in a summarization prompt.

3. Add a `generate_quiz` prompt template:
   - `topic: str` (required), `num_questions: int` (optional, default 5)

4. Test all prompts with the MCP Inspector:
   ```bash
   npx @modelcontextprotocol/inspector uv run mcp_server.py
   ```

5. Write a client script that fetches the `code_review` prompt template
   and uses it to review a small code diff end-to-end.

**Expected result:**
- In the MCP Inspector, the Prompts tab shows three entries: `code_review`, `summarize_module`, `generate_quiz`
- Selecting `code_review` shows its parameter schema with `diff` marked required
- Filling in parameters and requesting the prompt returns a structured message array ready to send to an LLM
- Inspector output example:
  ```json
  [
    {
      "role": "user",
      "content": "Review this python code diff and identify issues:\n\nDiff:\n- x = input()\n+ x = int(input())\n\nFocus on: bugs, security vulnerabilities, performance issues, and code clarity."
    }
  ]
  ```

**Why this matters:**
Prompt templates as MCP primitives mean your organization's prompt engineering lives in a discoverable, versioned server — not scattered across application code. Any MCP client (Claude Desktop, VS Code, custom apps) gets the same reviewed prompts without copy-paste drift.

**File:** Extend `lab/src/mcp_server.py`

---

### Lab 12D: MCP Inspector Testing and Debugging

**Goal:** Master the MCP Inspector workflow for testing and debugging MCP servers via raw JSON-RPC inspection.

**What to do:**

1. Run the MCP Inspector against your server:
   ```bash
   npx @modelcontextprotocol/inspector uv run mcp_server.py
   ```

2. For each tool, verify in the Inspector:
   - Tool appears in the tools list with correct description
   - Input schema is correct (required fields, types, descriptions)
   - Tool executes successfully with valid inputs
   - Tool returns a clear error for invalid inputs (path outside root, etc.)

3. For each resource, verify:
   - Resource appears in the resources/resource templates list
   - Resource content loads correctly
   - URIs with parameters work correctly

4. Introduce an intentional bug (e.g., a tool that raises an unhandled
   exception) and use the Inspector to identify it from the raw JSON-RPC
   messages.

5. Add structured logging to your server (log to stderr, not stdout — stdout
   is the MCP transport channel). Observe the logs while using the Inspector.

**Expected result:**
- The Inspector UI lists all tools with their JSON Schema input definitions
- Calling `read_file` with a valid path returns file contents; calling it with a path outside `MCP_ROOT_DIR` returns an error message (not a Python traceback)
- The raw JSON-RPC tab shows the request/response pairs:
  ```json
  → {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"read_file","arguments":{"path":"/etc/passwd"}}}
  ← {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"Error: path is outside allowed root directory"}]}}
  ```
- After introducing a bug, the Inspector shows a JSON-RPC error response with code and message fields
- stderr logs appear in the terminal (not in the Inspector transport)

**Why this matters:**
The MCP Inspector is your primary debugging tool for MCP development. When a client reports that a tool "doesn't work," the Inspector shows the exact JSON-RPC exchange — signature mismatches, missing fields, and unhandled exceptions are immediately visible.

**No new file** — this lab uses the server from Labs 12A-12C.

---

### Lab 12E: Claude Desktop Integration

**Goal:** Connect your MCP server to Claude Desktop and verify end-to-end tool invocation by a live LLM.

Note: this lab requires Claude Desktop to be installed. If unavailable, use
the Python MCP client from Lab 12A as the alternate path.

**What to do:**

1. Add your MCP server to Claude Desktop's config file:
   ```json
   {
     "mcpServers": {
       "ai-course": {
         "command": "uv",
         "args": ["--directory", "<absolute-path-to-lab>", "run", "mcp_server.py"],
         "env": {
           "MCP_ROOT_DIR": "<absolute-path-to-ai-course>"
         }
       }
     }
   }
   ```

2. Restart Claude Desktop. Verify the tools icon shows your 3 tools.

3. Test with these prompts:
   - "List all the modules in the AI course"
   - "Read the README for module 10 and summarize the key concepts"
   - "Find all Python files in the module-10-multi-agent lab"

4. Observe how Claude autonomously calls your tools (watch the tool call
   notifications in Claude Desktop).

5. Test an error case: ask Claude to read a file outside the allowed directory.
   Verify your root restriction error is shown properly.

**Alternate (Python MCP Client):**

If Claude Desktop is unavailable, use the client from Lab 12A:
```bash
uv run python src/mcp_client.py --query "Find all Python files in the ai-course repo that import httpx"
```

**Expected result:**
- Claude Desktop shows a hammer icon with a badge count matching your tool count (3)
- Asking "List all the modules" triggers a `list_directory` or `search_files` tool call — you see the tool invocation notification in the chat
- Claude returns a formatted list of modules with descriptions pulled from your filesystem
- Asking to read a file outside `MCP_ROOT_DIR` results in Claude reporting the error message from your tool, not a crash
- Sample Claude Desktop interaction:
  ```
  User: Read the README for module 10 and summarize the key concepts
  [Claude calls read_file with path "modules/module-10-.../README.md"]
  Claude: Module 10 covers multi-agent orchestration patterns including...
  ```

**Why this matters:**
Claude Desktop integration is the most common MCP deployment path. Validating that your server works with a real LLM client — not just the Inspector — catches issues like ambiguous tool descriptions that cause the model to pick the wrong tool, or missing schema constraints that lead to invalid arguments.

**File:** `lab/src/test_mcp_client.py` (alternate path)

---

## Conceptual Checkpoints

Answer these before moving to Module 13:

1. **MCP vs. function calling**: You've built tool-calling agents using raw
   JSON schemas in the request (Modules 1-9) and now via MCP. What are the
   concrete engineering trade-offs? When would you choose MCP over direct
   function calling in a production system?

2. **Tools vs. Resources**: Explain the philosophical difference between MCP
   Tools and MCP Resources. Given this distinction, categorize the following
   as tool or resource: (a) a function that queries a database for a customer
   record, (b) a function that sends an email, (c) a function that returns
   the current system time, (d) a function that reads an S3 object.

3. **stdio limitations**: Your MCP server uses stdio transport. Describe
   three concrete production scenarios where stdio is insufficient and HTTP
   transport is required. What would you change in your server code to switch
   transports?

4. **Security boundary**: Your `read_file` tool restricts access to
   `MCP_ROOT_DIR`. Is this a sufficient security control? What additional
   safeguards would you add before exposing this MCP server on a network?
   Consider: what can an LLM (which controls tool calls) do that a human
   user can't?

5. **Prompt templates as infrastructure**: In a large team, who should own
   MCP Prompt templates? How would you version them, test them, and roll
   them back? How is this different from versioning code?

---

## Resources

- MCP specification:
  https://spec.modelcontextprotocol.io/
- MCP Python SDK:
  https://github.com/modelcontextprotocol/python-sdk
- MCP Inspector:
  https://github.com/modelcontextprotocol/inspector
- Claude Desktop MCP configuration:
  https://modelcontextprotocol.io/quickstart/user
- MCP servers registry (community servers):
  https://github.com/modelcontextprotocol/servers
