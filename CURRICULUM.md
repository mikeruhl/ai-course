# AI Engineering Curriculum for Staff Engineers

## Goal
Transition from traditional software engineering to AI engineering —
specifically: agentic workflows, multi-agent systems, MCP servers, A2A auth,
and production-grade agent infrastructure on Azure.

## Philosophy
You're not learning *to use* AI — you're learning *to build systems where AI
is the runtime*. Instead of writing code that executes deterministically,
you're designing **agents** that reason, plan, call tools, and coordinate with
other agents. Your job becomes architecture, orchestration, and guardrails.

---

## Phase 1 — Foundations (Weeks 1–2)
*Goal: Understand how LLMs actually work as a runtime, not just an API.*

### Week 1: LLM Primitives + Tool Use
- [x] Module 01: LLM as a Compute Primitive
- [x] Module 02: Prompt Engineering at Staff Level
- [x] Module 03: Function Calling / Tool Use (raw agent loop)

### Week 2: Async Agents + Structured Outputs at Depth
- [ ] Module 04: Async Agent Loops + Streaming
- [ ] Module 05: Structured Outputs at Depth

---

## Phase 2 — Agentic Patterns (Weeks 3–5)
*Goal: Know every standard agentic architecture by name and when to use each.*

### Week 3: Core Agent Architectures
- [ ] Module 06: ReAct Agent (from scratch)
- [ ] Module 07: Planning Patterns (Plan-and-Execute, Reflexion, LATS)

### Week 4: Memory Systems
- [ ] Module 08: Memory Systems (in-context, episodic, semantic, procedural)
  - *New Azure: Azure AI Search (vector store)*

### Week 5: RAG
- [ ] Module 09: Retrieval-Augmented Generation
  - *Reuses Azure AI Search from Week 4*

---

## Phase 3 — Multi-Agent Systems (Weeks 6–8)
*Goal: Design systems where agents coordinate, delegate, and check each other.*

### Week 6: Multi-Agent Architectures
- [ ] Module 10: Multi-Agent Architectures

### Week 7: Agent Communication Protocols
- [ ] Module 11: A2A Protocol (Google open standard)
- [ ] Module 12: MCP Protocol (Anthropic)

### Week 8: A2A Authentication
- [ ] Module 13: A2A Authentication (Managed Identity, OAuth 2.0, mTLS)
  - *New Azure: Container Apps, Managed Identity, App Registrations*

---

## Phase 4 — MCP Deep Dive (Weeks 9–10)
*Goal: Build MCP servers that AI agents can consume.*

### Week 9: Building MCP Servers
- [ ] Module 14: Building MCP Servers (Python SDK)

### Week 10: MCP Hosting & Security
- [ ] Module 15: MCP Hosting (Container Apps, HTTP+SSE transport)
  - *New Azure: Container Registry, Container Apps Environment*
- [ ] Module 16: MCP Security (OAuth, sandboxing, injection hardening)

---

## Phase 5 — Orchestration Frameworks (Weeks 11–12)
*Goal: Pick the right framework; understand abstractions vs raw code.*

### Week 11: Microsoft Stack
- [ ] Module 17: Semantic Kernel
- [ ] Module 18: AutoGen

### Week 12: LangGraph + Azure AI Foundry
- [ ] Module 19: LangGraph
- [ ] Module 20: Azure AI Foundry Agent Service

---

## Phase 6 — Production & Operations (Weeks 13–15)
*Goal: Run agents reliably in production.*

### Week 13: Observability
- [ ] Module 21: Observability for Agents
  - *New Azure: Azure Monitor, Application Insights*

### Week 14: Reliability
- [ ] Module 22: Reliability Patterns

### Week 15: Durable Execution + Cost
- [ ] Module 23: Durable Execution (Azure Durable Functions, Temporal)
  - *New Azure: Azure Functions, Storage Account*
- [ ] Module 24: Cost & Performance

---

## Phase 7 — Security & Trust (Ongoing)
*Your biggest differentiator as a staff engineer.*

- [ ] Module 25: Security (prompt injection, STRIDE, PyRIT red-teaming)

---

## Azure Services by Phase

| Service | First introduced |
|---|---|
| Azure OpenAI | Module 01 |
| Azure AI Search | Module 08 |
| Azure Container Apps | Module 13 |
| Azure Container Registry | Module 15 |
| Azure Key Vault | Module 15 |
| Managed Identity + Entra ID | Module 13 |
| Azure Monitor + App Insights | Module 21 |
| Azure Functions + Storage | Module 23 |
| Azure AI Content Safety | Module 25 |

---

## Complete Modules Index

| Module | Name | Week | Phase | Terraform |
|---|---|---|---|---|
| 01 | LLM as a Compute Primitive | 1 | 1 | ✓ (Azure OpenAI) |
| 02 | Prompt Engineering at Staff Level | 1 | 1 | — |
| 03 | Function Calling / Tool Use | 1 | 1 | — |
| 04 | Async Agent Loops + Streaming | 2 | 1 | — |
| 05 | Structured Outputs at Depth | 2 | 1 | — |
| 06 | ReAct Agent | 3 | 2 | — |
| 07 | Planning Patterns | 3 | 2 | — |
| 08 | Memory Systems | 4 | 2 | ✓ (AI Search) |
| 09 | RAG | 5 | 2 | — |
| 10 | Multi-Agent Architectures | 6 | 3 | — |
| 11 | A2A Protocol | 7 | 3 | — |
| 12 | MCP Protocol | 7 | 3 | — |
| 13 | A2A Authentication | 8 | 3 | ✓ (Container Apps, Managed Identity) |
| 14 | Building MCP Servers | 9 | 4 | — |
| 15 | MCP Hosting | 10 | 4 | ✓ (Container Registry, Container Apps Env) |
| 16 | MCP Security | 10 | 4 | — |
| 17 | Semantic Kernel | 11 | 5 | — |
| 18 | AutoGen | 11 | 5 | — |
| 19 | LangGraph | 12 | 5 | — |
| 20 | Azure AI Foundry Agent Service | 12 | 5 | — |
| 21 | Observability for Agents | 13 | 6 | ✓ (Azure Monitor, App Insights) |
| 22 | Reliability Patterns | 14 | 6 | — |
| 23 | Durable Execution | 15 | 6 | ✓ (Azure Functions, Storage) |
| 24 | Cost & Performance | 15 | 6 | — |
| 25 | Security & Trust | ongoing | 7 | — |

---

## Module Files

- [module-01](./modules/module-01-llm-primitive/README.md)
- [module-02](./modules/module-02-prompt-engineering/README.md)
- [module-03](./modules/module-03-tool-use/README.md)
- [module-04](./modules/module-04-async-streaming/README.md)
- [module-05](./modules/module-05-structured-outputs/README.md)
- [module-06](./modules/module-06-react-agent/README.md)
- [module-07](./modules/module-07-planning-patterns/README.md)
- [module-08](./modules/module-08-memory-systems/README.md)
- [module-09](./modules/module-09-rag/README.md)
- [module-10](./modules/module-10-multi-agent/README.md)
- [module-11](./modules/module-11-a2a-protocol/README.md)
- [module-12](./modules/module-12-mcp-protocol/README.md)
- [module-13](./modules/module-13-a2a-auth/README.md)
- [module-14](./modules/module-14-mcp-servers/README.md)
- [module-15](./modules/module-15-mcp-hosting/README.md)
- [module-16](./modules/module-16-mcp-security/README.md)
- [module-17](./modules/module-17-semantic-kernel/README.md)
- [module-18](./modules/module-18-autogen/README.md)
- [module-19](./modules/module-19-langgraph/README.md)
- [module-20](./modules/module-20-ai-foundry/README.md)
- [module-21](./modules/module-21-observability/README.md)
- [module-22](./modules/module-22-reliability/README.md)
- [module-23](./modules/module-23-durable-execution/README.md)
- [module-24](./modules/module-24-cost-performance/README.md)
- [module-25](./modules/module-25-security/README.md)
