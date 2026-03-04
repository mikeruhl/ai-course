# Model Context Protocol (MCP) Overview

MCP is an open protocol that standardises how LLM applications communicate with
external tools and data sources.

## Core Primitives

**Tools** — callable functions. The LLM invokes a tool by name with typed arguments.
Tools have side effects (search, write, compute). Defined with `@mcp.tool()`.

**Resources** — URI-addressable read-only content. The client reads resources and
includes them in context. Defined with `@mcp.resource("scheme:///{param}")`.

**Prompts** — reusable message templates with typed argument slots. The client requests
a prompt with arguments and receives back a structured message list. Defined with `@mcp.prompt()`.

## Transport Options

- **stdio**: process I/O, local only, no auth needed
- **HTTP+SSE**: network transport, multi-client, requires auth

## When to Use MCP

Use MCP when you want to expose capabilities that multiple different LLM clients
should be able to discover and use without embedding client-specific code.
