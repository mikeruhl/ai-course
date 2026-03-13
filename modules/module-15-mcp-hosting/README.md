# Module 15: MCP Hosting on Azure Container Apps

**Chapter 4 — MCP Deep Dive**

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

**Goal:** Convert an MCP server from subprocess-based stdio to network-based HTTP+SSE transport, demonstrating that tool logic is transport-agnostic.

**What to do:**
1. Open `lab/src/server.py` — the entrypoint section is at line 193. The transport change is already done: `mcp.run(transport="sse", host=HOST, port=PORT)` where `HOST` defaults to `"0.0.0.0"` and `PORT` to `8080` (configurable via `MCP_HOST`/`MCP_PORT` env vars)
2. Copy your completed tool, resource, and prompt implementations from module-14's `openai_server.py` into the corresponding TODO stubs (lines 70, 94, 110, 136, 143, 150, 161, 167 — each says `"Copy from module-14"`)
3. Run locally:
   ```bash
   uv run python src/server.py &
   # In another terminal:
   npx @modelcontextprotocol/inspector http://localhost:8080/sse
   ```

**Expected result:**
- The server starts and logs: `Uvicorn running on http://0.0.0.0:8080`
- MCP Inspector connects to `http://localhost:8080/sse` and shows all tools, resources, and prompts
- Calling `count_tokens` with `"hello world"` returns `2` — identical to the stdio version
- `curl -N http://localhost:8080/sse` shows the SSE stream opening with `event: endpoint` data

**Why this matters:**
- The stdio-to-SSE switch is a two-line change, but it unlocks multi-client access, remote deployment, and horizontal scaling. In production, you run HTTP+SSE behind a load balancer so multiple agents (CI bots, developer tools, dashboards) share one MCP server instance instead of each spawning their own subprocess.

### Task 2: Containerise

**Goal:** Package the MCP server as a Docker container using a multi-stage build, then push it to Azure Container Registry.

**What to do:**
1. Open `lab/Dockerfile` — review the multi-stage build: stage 1 (`builder`) installs dependencies with `uv sync --no-dev --frozen`, stage 2 copies the venv and source
2. Build and test locally:
   ```bash
   docker build -t mcp-openai-server:latest .

   docker run -p 8080:8080 \
     -e AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT \
     -e AZURE_OPENAI_KEY=$AZURE_OPENAI_KEY \
     -e AZURE_OPENAI_DEPLOYMENT=$AZURE_OPENAI_DEPLOYMENT \
     -e AZURE_OPENAI_API_VERSION=$AZURE_OPENAI_API_VERSION \
     mcp-openai-server:latest
   ```
3. Verify with Inspector:
   ```bash
   npx @modelcontextprotocol/inspector http://localhost:8080/sse
   ```
4. Push to ACR:
   ```bash
   REGISTRY=$(terraform -chdir=terraform output -raw registry_login_server)
   REGISTRY_USER=$(terraform -chdir=terraform output -raw registry_admin_username)
   REGISTRY_PASS=$(az acr credential show --name ${REGISTRY%%.*} --query passwords[0].value -o tsv)

   docker login $REGISTRY -u $REGISTRY_USER -p $REGISTRY_PASS
   docker tag mcp-openai-server:latest $REGISTRY/mcp-openai-server:latest
   docker push $REGISTRY/mcp-openai-server:latest
   ```

**Expected result:**
- `docker build` completes with a final image size under 200MB (the multi-stage build excludes build tools)
- `docker run` starts the server; Inspector connects and tools work identically to the non-containerized version
- `docker push` succeeds; the image appears in ACR:
  ```
  mcp-openai-server  latest  sha256:abc123...  2 minutes ago
  ```

**Why this matters:**
- Multi-stage builds keep runtime images small and free of build-time tools (uv, pip, compilers), reducing attack surface and cold-start time. Testing the container locally before pushing catches environment issues (missing files, wrong paths, missing env vars) before they surface in a cloud deployment where debugging is slower.

### Task 3: Deploy to Container Apps

**Goal:** Deploy the containerized MCP server to Azure Container Apps with HTTPS ingress and verify remote connectivity.

**What to do:**
1. The Terraform in this module provisions a Container App with a placeholder image. Update it to use your pushed image:
   ```bash
   az containerapp update \
     --name mcp-server \
     --resource-group <your-rg> \
     --image $REGISTRY/mcp-openai-server:latest
   ```
   Alternatively, update `terraform/main.tf` to set the image reference and run `terraform apply`.
2. Get the deployed URL and verify:
   ```bash
   MCP_URL=$(terraform -chdir=terraform output -raw mcp_server_url)
   npx @modelcontextprotocol/inspector $MCP_URL/sse
   ```

**Expected result:**
- Container Apps provisions a TLS-terminated HTTPS endpoint like `https://mcp-server.<hash>.azurecontainerapps.io`
- `curl -i $MCP_URL/sse` returns HTTP 200 with `Content-Type: text/event-stream`
- MCP Inspector connects to the remote server and all tools work:
  ```
  Connected to: azure-openai-server-http
  Tools: count_tokens, chat_completion, search_azure_openai, ...
  ```

**Why this matters:**
- Container Apps gives you HTTPS, autoscaling, and managed infrastructure without configuring Nginx, TLS certificates, or Kubernetes manifests. The MCP server transitions from a local developer tool to a shared team resource accessible from any network location. Scale-to-zero means you only pay when agents are actively calling tools.

### Task 4: Store Secrets in Key Vault

**Goal:** Move the Azure OpenAI API key from environment variables into Key Vault, using managed identity for credential-free secret access.

**What to do:**
1. Store the secret in Key Vault:
   ```bash
   KV_URI=$(terraform -chdir=terraform output -raw key_vault_uri)

   az keyvault secret set \
     --vault-name ${KV_URI#https://} \
     --name openai-api-key \
     --value "$AZURE_OPENAI_KEY"
   ```
2. The Terraform already configures the Container App with a Key Vault secret reference and a user-assigned managed identity with "Key Vault Secrets User" role. Re-apply to wire it up:
   ```bash
   terraform apply
   ```
3. Verify the server still works — your code reads `os.environ["AZURE_OPENAI_KEY"]` unchanged; Azure injects the value at runtime:
   ```bash
   npx @modelcontextprotocol/inspector $MCP_URL/sse
   # Call chat_completion — should succeed using the Key Vault-sourced key
   ```

**Expected result:**
- `az keyvault secret show --vault-name <name> --name openai-api-key` shows the secret exists
- The Container App's env var `AZURE_OPENAI_KEY` resolves to the Key Vault value at runtime (not visible in `az containerapp show` output — it shows `secretref:openai-key`)
- `chat_completion` returns a valid LLM response, proving the secret was injected correctly

**Why this matters:**
- API keys in environment variables leak through CI logs, Terraform state, `docker inspect`, and crash dumps. Key Vault references mean the plaintext key never appears in your infrastructure configuration. The managed identity (user-assigned, so it survives resource recreation) authenticates to Key Vault without any credential exchange your code needs to manage.

### Task 5: Add Authentication

**Goal:** Add OAuth 2.0 authentication via Container Apps EasyAuth so unauthenticated requests are rejected before reaching your server code.

**What to do:**
1. Create an Azure AD App Registration:
   ```bash
   APP_ID=$(az ad app create \
     --display-name "mcp-server-auth" \
     --query appId -o tsv)
   ```
2. Configure EasyAuth on the Container App:
   ```bash
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
3. Test rejection (no token):
   ```bash
   curl -i $MCP_URL/sse
   ```
4. Test acceptance (valid token):
   ```bash
   TOKEN=$(az account get-access-token --resource $APP_ID --query accessToken -o tsv)
   curl -i -H "Authorization: Bearer $TOKEN" $MCP_URL/sse
   ```

**Expected result:**
- Unauthenticated request returns:
  ```
  HTTP/1.1 401 Unauthorized
  WWW-Authenticate: Bearer
  ```
- Authenticated request returns:
  ```
  HTTP/1.1 200 OK
  Content-Type: text/event-stream
  event: endpoint
  data: /messages?session_id=...
  ```
- Your server code (`server.py`) has zero auth-related changes — EasyAuth is a reverse proxy layer

**Why this matters:**
- EasyAuth moves authentication to the infrastructure layer, which means your MCP server code stays focused on tool logic. Token validation, JWKS fetching, and 401 responses are handled before a request reaches your container. This separation means you can change auth providers (Entra ID, Auth0, Okta) without touching tool implementations.

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
