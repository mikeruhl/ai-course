# Module 15: MCP Hosting on Azure Container Apps

**Week 9-10 · Phase 4 — MCP Deep Dive**

---

## Learning Objectives

By the end of this module you will:

- Convert an MCP server from stdio to HTTP+SSE transport (a 5-line change)
- Containerise the MCP server with a production Dockerfile
- Deploy to Azure Container Apps with HTTPS and autoscaling
- Manage secrets securely using Azure Key Vault references in Container Apps
- Add OAuth 2.0 authentication using Container Apps built-in EasyAuth
- Understand why and when to use HTTP+SSE vs stdio transport

---

## Prerequisites

- Module 14 lab completed (your MCP server with Tools, Resources, Prompts)
- Docker Desktop installed and running
- Azure CLI authenticated (`az login`)
- Terraform >= 1.6 installed
- An Azure Container Registry (provisioned by this module's Terraform)

---

## Concepts

### Why HTTP+SSE Transport?

The stdio transport from Module 14 works perfectly for local development:
Claude Desktop, VS Code extensions, and CLI agents spawn your server as a
subprocess and communicate over stdin/stdout. No network, no auth, no ports.

But stdio has hard limits:
- One client per server process (it's a 1:1 subprocess relationship)
- Server runs on the developer's machine — not accessible to teammates
- No remote deployment (no cloud, no CI agents)
- No horizontal scaling

HTTP+SSE solves all of these:

| Concern | stdio | HTTP+SSE |
|---|---|---|
| Clients | One per process | Many concurrent |
| Deployment | Local only | Any HTTPS endpoint |
| Auth | OS process model | Bearer tokens (OAuth) |
| Scaling | Not applicable | Scale to 0 / scale out |
| Discovery | Out-of-band config | Well-known URL |

The MCP spec defines exactly two endpoints for HTTP+SSE:
- `GET /sse` — client opens a Server-Sent Events stream; server pushes responses here
- `POST /messages` — client sends requests (tool calls, resource reads, etc.) here

### Converting stdio to HTTP+SSE

The entire change is the last two lines of your server file:

```python
# BEFORE (stdio)
if __name__ == "__main__":
    mcp.run()

# AFTER (HTTP+SSE)
if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8080)
```

That's it. Every `@mcp.tool()`, `@mcp.resource()`, and `@mcp.prompt()` definition
is transport-agnostic. The FastMCP abstraction handles the protocol differences.

Under the hood, `transport="sse"` starts a Starlette/FastAPI application with the
two SSE endpoints. The `mcp` SDK wires your handlers into this HTTP server.

### Dockerfile for MCP Servers

Multi-stage build to keep the image small:

```dockerfile
# Stage 1: build
FROM python:3.11-slim AS builder
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
RUN uv sync --no-dev --frozen

# Stage 2: runtime
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src/ src/
COPY knowledge_base/ knowledge_base/
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
CMD ["python", "src/server.py"]
```

Key points:
- `python:3.11-slim` not `python:3.11` — saves ~600MB
- Multi-stage means build tools (uv, pip) are not in the final image
- `--no-dev` excludes pytest and rich from the runtime image
- `EXPOSE 8080` documents the port; Azure Container Apps needs this for ingress config

### Azure Container Apps Architecture

Container Apps is Azure's serverless container platform. For an MCP server it gives:

- **HTTPS by default**: Container Apps provisions a TLS certificate automatically.
  Your MCP server never handles TLS — the Container Apps infrastructure terminates it.
- **Scale to zero**: when no clients are connected, the container stops. You pay
  for actual invocations, not idle time. (For a long-lived SSE connection, a minimum
  of 1 replica makes sense.)
- **Ingress**: HTTP ingress routes external HTTPS traffic to your container's port.
- **Managed identity**: the container can authenticate to Azure services (Key Vault,
  Storage, etc.) without credentials in environment variables.
- **Secrets**: Key Vault references mean the container never sees the raw secret value;
  Azure injects it at runtime.

The Container Apps Environment is the shared infrastructure (virtual network, log
analytics workspace) that multiple Container Apps share. You provision one environment
per region/project.

### Azure Key Vault for Secrets

Never put API keys in environment variables passed through CI/CD pipelines or
committed to Terraform state. Use Key Vault references instead.

The pattern:

```
Key Vault Secret: openai-api-key = "sk-..."
        |
        v
Container App Secret (Key Vault reference):
  name: openai-key
  key_vault_secret_id: <key vault secret URI>
        |
        v
Container App Environment Variable:
  AZURE_OPENAI_KEY = secretref:openai-key
        |
        v
Your code: os.environ["AZURE_OPENAI_KEY"]  # reads the actual value
```

The Managed Identity (a user-assigned identity attached to the Container App) must
have the "Key Vault Secrets User" role on the Key Vault. This role grants
`get` and `list` permissions on secrets.

Why user-assigned (not system-assigned) identity?
- User-assigned identity exists independently of the resource it's attached to
- You can pre-create it, assign roles to it, then attach it to new resources
- Useful when the identity needs to be granted access before the Container App exists

### OAuth 2.0 with Container Apps EasyAuth

EasyAuth (Container Apps Authentication) is a reverse proxy that sits in front of
your container. It intercepts all HTTP requests:

```
Client -> [Container Apps EasyAuth] -> Your container
```

When EasyAuth is configured with Azure AD:
- Unauthenticated requests receive HTTP 401 before reaching your code
- Authenticated requests have their claims forwarded in headers:
  `X-MS-CLIENT-PRINCIPAL`, `X-MS-TOKEN-AAD-ACCESS-TOKEN`

Your MCP server code needs zero changes. The auth is handled entirely at the
infrastructure layer.

Configuration (via `az containerapp auth update`):
```bash
az containerapp auth microsoft update \
  --name <app-name> \
  --resource-group <rg-name> \
  --client-id <app-registration-client-id> \
  --client-secret <app-registration-secret> \
  --tenant-id <your-tenant-id>
```

Testing the auth:
```bash
# Should return 401 (no token)
curl https://your-mcp-server.azurecontainerapps.io/sse

# Should succeed (valid token)
TOKEN=$(az account get-access-token --resource <client-id> --query accessToken -o tsv)
curl -H "Authorization: Bearer $TOKEN" https://your-mcp-server.azurecontainerapps.io/sse
```

---

## Infrastructure

This module provisions:

| Resource | Purpose |
|---|---|
| `azurerm_container_registry` | Store your Docker images |
| `azurerm_user_assigned_identity` | Managed identity for the Container App |
| `azurerm_key_vault` | Store secrets (OpenAI API key) |
| `azurerm_key_vault_secret` | The actual secret value |
| `azurerm_container_app_environment` | Shared network/logging infrastructure |
| `azurerm_container_app` | The running MCP server |
| Role assignment | Key Vault Secrets User on the managed identity |

### Provision

```bash
cd modules/module-15-mcp-hosting/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — see comments in the file
terraform init
terraform plan
terraform apply
```

Takes 3–5 minutes. On success:
- `registry_login_server` — push your images here
- `registry_admin_username` — for `docker login`
- `mcp_server_url` — your MCP server's public HTTPS URL
- `key_vault_uri` — the Key Vault for storing secrets

---

## Lab

### Setup

```bash
cd modules/module-15-mcp-hosting/lab
cp .env.example .env
uv sync
```

### Task 1: Convert to HTTP+SSE

File: `lab/src/server.py`

Copy your module-14 `openai_server.py` as the starting point, then:

1. Change the `mcp.run()` call to use `transport="sse"`, `host="0.0.0.0"`, `port=8080`
2. Test locally:
   ```bash
   uv run python src/server.py &
   # In another terminal:
   npx @modelcontextprotocol/inspector http://localhost:8080/sse
   ```
3. Verify all tools, resources, and prompts work identically to the stdio version

The SSE endpoint is `GET /sse`. The Inspector knows to use this URL format when
you give it an HTTP URL instead of a command to spawn.

### Task 2: Containerise

File: `lab/Dockerfile`

Build and test locally:

```bash
# Build
docker build -t mcp-openai-server:latest .

# Test locally (pass your .env values)
docker run -p 8080:8080 \
  -e AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT \
  -e AZURE_OPENAI_KEY=$AZURE_OPENAI_KEY \
  -e AZURE_OPENAI_DEPLOYMENT=$AZURE_OPENAI_DEPLOYMENT \
  -e AZURE_OPENAI_API_VERSION=$AZURE_OPENAI_API_VERSION \
  mcp-openai-server:latest

# Verify in Inspector
npx @modelcontextprotocol/inspector http://localhost:8080/sse
```

Then push to Azure Container Registry:

```bash
# Get registry details from terraform output
REGISTRY=$(terraform -chdir=terraform output -raw registry_login_server)
REGISTRY_USER=$(terraform -chdir=terraform output -raw registry_admin_username)
REGISTRY_PASS=$(az acr credential show --name ${REGISTRY%%.*} --query passwords[0].value -o tsv)

docker login $REGISTRY -u $REGISTRY_USER -p $REGISTRY_PASS
docker tag mcp-openai-server:latest $REGISTRY/mcp-openai-server:latest
docker push $REGISTRY/mcp-openai-server:latest
```

### Task 3: Deploy to Container Apps

The Terraform in this module provisions a Container App with a placeholder image.
Update it to use your real image:

```bash
# Update the container app to use your pushed image
az containerapp update \
  --name mcp-server \
  --resource-group <your-rg> \
  --image $REGISTRY/mcp-openai-server:latest
```

Or update `terraform/main.tf` to point to your image and re-apply.

Verify:
```bash
MCP_URL=$(terraform -chdir=terraform output -raw mcp_server_url)
npx @modelcontextprotocol/inspector $MCP_URL/sse
```

### Task 4: Store Secrets in Key Vault

The Terraform creates a Key Vault and a placeholder secret. Update it with
your real OpenAI API key:

```bash
KV_URI=$(terraform -chdir=terraform output -raw key_vault_uri)

az keyvault secret set \
  --vault-name ${KV_URI#https://} \
  --name openai-api-key \
  --value "$AZURE_OPENAI_KEY"
```

Then update the Container App to read the key from Key Vault instead of an
environment variable. In `terraform/main.tf`, the container app is already
configured with a Key Vault secret reference — re-apply after setting the secret:

```bash
terraform apply
```

Verify the container can still reach Azure OpenAI (the managed identity handles
Key Vault access; your server code reads `AZURE_OPENAI_KEY` as before).

### Task 5: Add Authentication

Configure Container Apps built-in auth to require Azure AD tokens:

```bash
# Create an App Registration for your MCP server
APP_ID=$(az ad app create \
  --display-name "mcp-server-auth" \
  --query appId -o tsv)

# Configure EasyAuth
az containerapp auth microsoft update \
  --name mcp-server \
  --resource-group <your-rg> \
  --client-id $APP_ID \
  --tenant-id $(az account show --query tenantId -o tsv) \
  --yes

az containerapp auth update \
  --name mcp-server \
  --resource-group <your-rg> \
  --unauthenticated-client-action Return401
```

Test rejection:
```bash
curl -i $MCP_URL/sse
# Expect: HTTP/1.1 401 Unauthorized
```

Test acceptance:
```bash
TOKEN=$(az account get-access-token --resource $APP_ID --query accessToken -o tsv)
curl -i -H "Authorization: Bearer $TOKEN" $MCP_URL/sse
# Expect: HTTP 200 with SSE stream starting
```

---

## Checkpoints

- [ ] Task 1: `http://localhost:8080/sse` serves the MCP SSE endpoint; all tools work
- [ ] Task 2: `docker run` on your image works; image pushed to ACR
- [ ] Task 3: `npx @modelcontextprotocol/inspector $MCP_URL/sse` connects to deployed server
- [ ] Task 4: OpenAI key is in Key Vault, not in container environment; server still works
- [ ] Task 5: Unauthenticated request returns 401; authenticated request succeeds

---

## Key Concepts Summary

| Concept | One-line summary |
|---|---|
| HTTP+SSE transport | Two endpoints: POST /messages (requests), GET /sse (responses) |
| EasyAuth | Container Apps reverse proxy that validates tokens before your code runs |
| Key Vault reference | Container reads secret name; Azure injects value — key never in env vars |
| User-assigned identity | Managed identity that exists independently; pre-assignable to resources |
| Scale to zero | Container App stops when idle; restarts on first request (~1–2s cold start) |
| ACR | Azure Container Registry — private Docker registry for your images |

---

## Resources

- [Azure Container Apps documentation](https://learn.microsoft.com/en-us/azure/container-apps/)
- [Container Apps managed identity](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity)
- [Key Vault references in Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets)
- [Container Apps authentication](https://learn.microsoft.com/en-us/azure/container-apps/authentication)
- [MCP HTTP+SSE transport spec](https://spec.modelcontextprotocol.io/specification/basic/transports/#http-with-sse)
- [azurerm_container_app Terraform docs](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/container_app)
