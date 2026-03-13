# AI Engineering Course

> **Disclaimer:** This course was generated with the assistance of AI and is
> currently under human review. Content, labs, and instructions may contain
> errors or inaccuracies. Use with appropriate skepticism and report issues
> via the repository's issue tracker.

A hands-on, Azure-native curriculum for software engineers learning to build
production agentic systems. Designed for engineers with strong fundamentals
who want to understand the *why* behind every concept, not just the how.

## What You'll Build

By the end of this course you will have built (from scratch, then with
frameworks):

- A raw LLM tool-calling agent loop
- A production-quality RAG pipeline over real data
- Multi-agent systems with orchestrators, subagents, and handoffs
- MCP (Model Context Protocol) servers deployed to Azure Container Apps
- Agent-to-agent authentication using Azure Managed Identity
- Durable, long-running agent workflows using Azure Durable Functions
- Observability and eval pipelines for non-deterministic systems

## Prerequisites

Before starting Module 1, complete the [course setup](./setup/README.md).

**Software:**
- [uv](https://docs.astral.sh/uv/) — Python toolchain (install + project management)
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) — `az`
- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.6
- [Git](https://git-scm.com/)

**Azure:**
- Active Azure subscription with permission to create resources
- Contributor role on a subscription or resource group

**Knowledge:**
- Comfortable with Python
- Familiarity with REST APIs and JSON
- Basic understanding of cloud infrastructure (VMs, networking, IAM)

## Curriculum

See [CURRICULUM.md](./CURRICULUM.md) for the full outline.

## Folder Structure

```
ai-course/
├── README.md                   ← This file
├── CURRICULUM.md               ← Full course outline
├── setup/
│   └── README.md               ← One-time environment setup
└── modules/
    ├── module-01-llm-primitive/
    │   ├── README.md           ← Concepts + lab instructions
    │   ├── terraform/          ← Azure resource provisioning
    │   └── lab/                ← Python project (uv)
    ├── module-02-prompt-engineering/
    │   ├── README.md
    │   └── lab/
    ├── module-03-tool-use/
    │   ├── README.md
    │   └── lab/
    └── ...
```

## How to Use This Course

Each module is self-contained:

1. Read the module `README.md` — concepts come first
2. Run `terraform apply` if the module has a `terraform/` directory
3. `cd lab && uv sync` to install dependencies
4. Copy `.env.example` to `.env` and fill in your values
5. Work through the lab tasks in the README
6. Check your understanding with the conceptual checkpoints

Modules within the same chapter share Azure resources. Only the first module
in a chapter typically has Terraform — later modules reference those outputs.

## Cost Estimate

All labs use Azure pay-as-you-go. Rough estimates per module:

| Resource | Estimated cost |
|---|---|
| Azure OpenAI (gpt-4o-mini, dev usage) | < $1 per module |
| Azure AI Search (Basic tier) | ~$0.25/day while running |
| Azure Container Apps | Free tier covers most labs |

**Always run `terraform destroy` after completing a module if you won't
be returning to it within a day or two.**
