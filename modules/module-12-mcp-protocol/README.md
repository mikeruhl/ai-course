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

No Azure OpenAI calls in this module — the MCP server itself doesn't call LLMs.
The LLM (Claude Desktop or your own app) connects to your MCP server and calls
the tools. The `.env` is included for consistency but not required for Labs A-D.

---

### Lab 12A: MCP Server with Three Tools

**Goal:** Build a working MCP server exposing filesystem tools.

**Tasks:**

1. Implement an MCP server with three tools using the Python `mcp` SDK:
   - `read_file(path: str) -> str` — read a file, cap at 10,000 characters
   - `list_directory(path: str) -> list[dict]` — list files with name, type,
     size. Return as JSON-serialized list.
   - `search_files(directory: str, pattern: str) -> list[str]` — find files
     matching a glob pattern, return list of paths

2. Add input validation to each tool:
   - `read_file`: reject paths outside a safe root directory (configurable via env var `MCP_ROOT_DIR`)
   - `list_directory`: same root restriction
   - `search_files`: limit results to 100 files maximum

3. Add proper error handling: return `types.TextContent` with an error
   description rather than raising Python exceptions (MCP clients may not
   handle exceptions gracefully).

4. Test the server using the MCP Inspector:
   ```bash
   npx @modelcontextprotocol/inspector uv run mcp_server.py
   ```
   Verify all three tools appear, have correct schemas, and work correctly.

5. Write a second test script (`test_mcp_client.py`) that connects to your
   server programmatically using the MCP Python SDK client and calls each tool.

**File:** `lab/src/mcp_server.py`

---

### Lab 12B: Resource Exposure

**Goal:** Expose the course directory as a browseable resource tree.

**Tasks:**

1. Add a resource that lists all modules:
   - URI: `course://modules`
   - Returns: JSON list of `{id, name, path}` for each module directory

2. Add a resource for individual module READMEs:
   - URI template: `course://modules/{module_id}/readme`
   - Returns: the raw README.md content for that module

3. Add a resource for lab files:
   - URI template: `course://modules/{module_id}/lab/{filename}`
   - Returns: the content of a specific lab file

4. Implement `list_resources()` and `list_resource_templates()` handlers so
   clients can discover all available resources without knowing the URI scheme.

5. Test with the MCP Inspector: browse the resource tree, open individual
   module READMEs, confirm the content is correct.

**File:** Extend `lab/src/mcp_server.py`

---

### Lab 12C: Prompt Templates

**Goal:** Add reusable prompt templates to the MCP server.

**Tasks:**

1. Add a `code_review` prompt template:
   - Parameter: `diff: str` (required) — the code diff to review
   - Parameter: `language: str` (optional, default "python") — programming language
   - Parameter: `focus: str` (optional) — specific aspect to focus on
   - Returns a well-structured user message that instructs the model to do
     a thorough code review

2. Add a `summarize_module` prompt template:
   - Parameter: `module_id: str` (required)
   - Uses the `read_file` tool internally to fetch the README, then wraps it
     in a summarization prompt
   - Returns a user message asking for a concise module summary

3. Add a `generate_quiz` prompt template:
   - Parameter: `topic: str` (required)
   - Parameter: `num_questions: int` (optional, default 5)
   - Returns a prompt that asks the model to generate a quiz on the topic

4. Test all prompts with the MCP Inspector.

5. Demonstrate using a prompt from a client: write a script that fetches
   the `code_review` prompt template and uses it to review a small code diff.

**File:** Extend `lab/src/mcp_server.py`

---

### Lab 12D: MCP Inspector Testing and Debugging

**Goal:** Master the MCP Inspector workflow for testing and debugging.

**Tasks:**

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

**No new file** — this lab uses the server from Labs 12A-12C.

---

### Lab 12E: Claude Desktop Integration

**Goal:** Connect your MCP server to Claude Desktop and test end-to-end.

Note: this lab requires Claude Desktop to be installed. If unavailable, build
a Python MCP client instead (see alternate instructions below).

**Tasks (Claude Desktop):**

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

If Claude Desktop is unavailable, build a Python MCP client that connects to
your server and drives a multi-tool conversation:

```bash
uv run test_mcp_client.py "Find all Python files in the ai-course repo that import httpx"
```

The client should run an agent loop that calls your MCP tools until it can
answer the query.

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
