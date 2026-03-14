# Module 13: A2A Authentication

## Overview

Agent-to-agent calls are service-to-service calls. Without authentication,
any process on your network can impersonate Agent A and call Agent B. This
module implements two levels of agent auth: OAuth 2.0 Client Credentials
(portable, works anywhere) and Azure Managed Identity (the right approach
for Azure workloads — no secrets, no rotation, no exposure).

By the end: two agents deployed to Azure Container Apps are calling each other
with zero secrets in code or environment variables, using Managed Identity
and validated JWT tokens at every hop.

---

## Concepts

### 1. Why Agent Auth Is Different

User authentication (OAuth, OIDC) answers: "Who is this human?"
Agent authentication answers: "Which service is making this call, and is it authorized?"

Key differences:

| Aspect | User Auth | Agent Auth |
|--------|-----------|------------|
| Authenticating party | A human with a browser | An automated service |
| Credentials | Username + password, MFA | Client ID + secret, or managed identity |
| Token lifetime | Short (1 hour), refreshed by user | Short (1 hour), refreshed automatically |
| "Login" UX | Browser redirect, consent screen | No UI — fully automated |
| Secret storage | User's brain / password manager | Environment variable, Key Vault, or no secret at all |
| Rotation | User changes password | Ops team rotates secrets (or managed identity handles it) |

The OAuth 2.0 **Client Credentials** flow is the standard for machine-to-machine
auth. It has no user interaction — the service authenticates directly to the
token endpoint using its own credentials.

---

### 2. OAuth 2.0 Client Credentials Flow

```
Agent A                    Azure AD (Entra ID)              Agent B
   │                              │                              │
   │─── POST /oauth2/token ──────►│                              │
   │    client_id=app-agent-a     │                              │
   │    client_secret=...         │                              │
   │    scope=api://agent-b/.default                             │
   │                              │                              │
   │◄── access_token (JWT) ───────│                              │
   │                              │                              │
   │─── POST /tasks/send ────────────────────────────────────────►│
   │    Authorization: Bearer <JWT>                               │
   │                              │                              │
   │                              │◄── validate token ──────────│
   │                              │    (check sig, iss, aud,     │
   │                              │     exp, scope)              │
   │                              │─── valid ──────────────────►│
   │                              │                              │
   │◄─── response ───────────────────────────────────────────────│
```

The key steps:
1. Agent A has a registered App Registration in Entra ID with a client secret
2. Agent A requests a token specifying Agent B's app ID as the audience (`scope`)
3. Azure AD issues a signed JWT that says "this token is for agent-a to call agent-b"
4. Agent B validates the JWT — if invalid, returns 401

---

### 3. JWT Token Anatomy

A JWT has three parts: header.payload.signature (base64url-encoded, dot-separated).

Typical payload from Azure AD Client Credentials flow:

```json
{
  "aud": "api://agent-b",          // audience — who the token is for
  "iss": "https://sts.windows.net/YOUR_TENANT_ID/",  // issuer — Azure AD
  "iat": 1700000000,               // issued at (Unix timestamp)
  "exp": 1700003600,               // expires at (issued + 1 hour)
  "appid": "CLIENT_ID_OF_AGENT_A", // the app registration that got this token
  "appidacr": "1",                 // auth method: 1 = client secret
  "scp": "",                       // scopes (empty for client credentials)
  "roles": ["agent.invoke"],       // app roles — use this for authorization
  "tid": "YOUR_TENANT_ID",         // tenant ID
  "ver": "1.0"
}
```

**Validation checklist for Agent B:**

1. **Signature**: verify using Azure AD's public keys (JWKS endpoint)
2. **Issuer (`iss`)**: must be `https://sts.windows.net/{your_tenant_id}/`
3. **Audience (`aud`)**: must be Agent B's app registration URI
4. **Expiry (`exp`)**: must be in the future
5. **Role/scope**: caller must have the required role (e.g., `agent.invoke`)

Never trust a token without validating all five. Especially the audience —
a token issued for Agent C is not valid for Agent B, even if correctly signed.

---

### 4. Azure Managed Identity

Managed Identity eliminates secrets entirely. Instead of a client ID + secret,
Azure assigns a cryptographic identity to your Container App. The service gets
tokens by calling the Instance Metadata Service (IMDS) — an HTTP endpoint
available inside the container.

```python
import httpx

# Inside an Azure Container App with managed identity enabled:
IMDS_ENDPOINT = "http://169.254.169.254/metadata/identity/oauth2/token"

response = httpx.get(
    IMDS_ENDPOINT,
    params={
        "api-version": "2018-02-01",
        "resource": "api://agent-b"  # the audience
    },
    headers={"Metadata": "true"},
    timeout=10
)
token = response.json()["access_token"]
```

No secrets. No rotation. No `.env` file. Azure handles the private key and
token issuance entirely. This is the correct pattern for Azure workloads.

Two types of managed identity:
- **System-assigned**: tied to the resource lifecycle. Deleted when Container
  App is deleted. Good for single-purpose identities.
- **User-assigned**: standalone resource. Can be assigned to multiple Container
  Apps. Survives redeployment. Better for shared identities and easier to
  assign RBAC roles before the Container App exists.

This module uses user-assigned managed identities (see Terraform).

---

### 5. App Roles vs. Scopes

In Client Credentials flow, there are no delegated scopes (no user to delegate
on behalf of). Instead, you use **App Roles** for authorization.

App Roles are defined on Agent B's App Registration:

```json
{
  "appRoles": [
    {
      "allowedMemberTypes": ["Application"],
      "description": "Allows an agent to invoke this agent's task endpoint",
      "displayName": "Agent Invoke",
      "id": "<uuid>",
      "isEnabled": true,
      "value": "agent.invoke"
    }
  ]
}
```

Agent A's App Registration is then granted the `agent.invoke` role on Agent B's
App Registration (an "app role assignment"). When Agent A gets a token, the role
appears in the `roles` claim of the JWT.

Agent B checks: `"agent.invoke" in token["roles"]`

This enables least-privilege: you can define fine-grained roles
(`tasks.submit`, `tasks.read`, `admin.cancel`) and grant each caller only
what it needs.

---

### 6. Token Validation with PyJWT and JWKS

Azure AD's public keys are available at:
```
https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys
```

The JWKS (JSON Web Key Set) contains the public keys. PyJWT's `PyJWKClient`
fetches and caches these keys, then verifies the token's signature.

```python
import jwt
from jwt import PyJWKClient

TENANT_ID = os.environ["AZURE_TENANT_ID"]
AGENT_B_APP_URI = "api://agent-b"

jwks_client = PyJWKClient(
    f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
)

def validate_token(token: str) -> dict:
    signing_key = jwks_client.get_signing_key_from_jwt(token)
    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=AGENT_B_APP_URI,
        issuer=f"https://sts.windows.net/{TENANT_ID}/"
    )
    # PyJWT already verified: signature, audience, issuer, expiry
    # Now check authorization
    if "agent.invoke" not in payload.get("roles", []):
        raise jwt.InvalidTokenError("Missing required role: agent.invoke")
    return payload
```

Cache the `PyJWKClient` — it fetches the JWKS on first use and caches the
keys. Don't create a new client per request.

---

### 7. mTLS (Conceptual)

Mutual TLS is an alternative where both sides have certificates:

```
Agent A ──TLS handshake──► Agent B
         presents client cert  validates A's cert
         ◄── presents server cert
         validates B's cert
```

Both sides must trust the other's CA. The "auth" is the mutual cert validation.

Advantages over JWT:
- No token expiry/refresh needed
- Transport-layer security (not just application-layer)
- Works without a central identity provider

Disadvantages:
- Certificate lifecycle management is complex
- Harder to implement fine-grained authorization (cert = identity, not
  permission)
- Revocation is harder (CRL/OCSP infrastructure needed)

For Azure workloads, Managed Identity + JWT is the recommended approach.
mTLS is common in service mesh configurations (Istio, Linkerd) where it's
handled transparently by the mesh.

---

## Terraform Infrastructure

The Terraform in this module provisions the Azure infrastructure needed for
Lab 13D (Managed Identity). You build and push the container images in the lab.

**What Terraform creates:**

- **Resource group** (or uses existing)
- **Container Apps Environment**: the hosting environment for both agents
- **User-Assigned Managed Identity** for agent-a
- **User-Assigned Managed Identity** for agent-b
- **Container App** for agent-a (initially runs a placeholder image)
- **Container App** for agent-b (initially runs a placeholder image)

**What Terraform does NOT create:**

- App Registrations (Entra objects — not in azurerm scope, use az CLI)
- Container Registry (use Azure Container Registry from your existing setup,
  or Docker Hub for development)

**Deploy:**

```bash
cd modules/module-13-a2a-auth/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars
az login
terraform init
terraform plan
terraform apply
```

---

## Lab Tasks

### Setup

```bash
cd modules/module-13-a2a-auth/lab
cp .env.example .env
# Edit .env
uv sync
```

Labs A-C run locally. Lab D requires Azure deployment.

### Option B: Google Vertex AI

Use Vertex AI's OpenAI-compatible endpoint instead of Azure OpenAI for the
LLM calls. Azure-specific services still require Azure.

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

---

### Lab 13A: App Registration Setup

**Goal:** Create the Entra ID App Registrations that establish agent identities and role-based authorization for A2A calls.

**What to do:**

1. Create the App Registration for agent-b (the server that needs to be protected):
   ```bash
   az ad app create --display-name "agent-b" \
     --identifier-uris "api://agent-b"
   AGENT_B_APP_ID=$(az ad app list --display-name "agent-b" --query "[0].appId" -o tsv)
   az ad sp create --id $AGENT_B_APP_ID
   ```

2. Add the `agent.invoke` App Role to agent-b:
   ```bash
   az ad app update --id $AGENT_B_APP_ID --app-roles @app-role.json
   ```
   Create `app-role.json` with the role definition (see starter file for template).

3. Create the App Registration for agent-a (the caller):
   ```bash
   az ad app create --display-name "agent-a"
   AGENT_A_APP_ID=$(az ad app list --display-name "agent-a" --query "[0].appId" -o tsv)
   az ad sp create --id $AGENT_A_APP_ID
   az ad app credential reset --id $AGENT_A_APP_ID --append
   # Save the secret — you'll only see it once
   ```

4. Grant agent-a the `agent.invoke` role on agent-b:
   ```bash
   AGENT_B_SP_ID=$(az ad sp show --id $AGENT_B_APP_ID --query "id" -o tsv)
   AGENT_A_SP_ID=$(az ad sp show --id $AGENT_A_APP_ID --query "id" -o tsv)
   ROLE_ID=$(az ad app show --id $AGENT_B_APP_ID \
     --query "appRoles[?value=='agent.invoke'].id" -o tsv)
   az rest --method POST \
     --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$AGENT_B_SP_ID/appRoleAssignedTo" \
     --body "{\"principalId\": \"$AGENT_A_SP_ID\", \"resourceId\": \"$AGENT_B_SP_ID\", \"appRoleId\": \"$ROLE_ID\"}"
   ```

5. Populate `.env` with:
   - `AZURE_TENANT_ID`
   - `AGENT_A_CLIENT_ID`
   - `AGENT_A_CLIENT_SECRET`
   - `AGENT_B_APP_URI` = `api://agent-b`

**Expected result:**
- `az ad app list --display-name "agent-b"` returns a JSON object with `appId` and `identifierUris: ["api://agent-b"]`
- `az ad app show --id $AGENT_B_APP_ID --query "appRoles"` shows the `agent.invoke` role with `allowedMemberTypes: ["Application"]`
- The role assignment call returns HTTP 201 with the assignment object:
  ```json
  {
    "appRoleId": "<role-uuid>",
    "principalId": "<agent-a-sp-id>",
    "resourceId": "<agent-b-sp-id>"
  }
  ```
- `.env` contains four populated variables, and the client secret is saved securely

**Why this matters:**
App Registrations are the identity foundation for all Azure service-to-service auth. Getting the role assignment wrong (e.g., granting the role on the wrong service principal) is the most common cause of "access denied" errors in production A2A flows. This lab forces you through each step explicitly.

**File:** `lab/src/setup_app_registrations.sh` (reference script with commands)

---

### Lab 13B: OAuth Client Credentials Flow

**Goal:** Implement token acquisition using the OAuth 2.0 Client Credentials flow and inject bearer tokens into A2A calls.

**What to do:**

1. Open `lab/src/auth_demo.py`. Find `get_access_token_client_credentials()`.
   Implement the token request: POST to
   `https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token` with
   form-encoded body (`grant_type=client_credentials&client_id=...&client_secret=...&scope=...`).
   Return the `access_token` string.

2. Find `call_agent_authenticated()` in the same file. Implement the
   authenticated A2A call: POST to `{agent_url}/tasks/send` with
   `Authorization: Bearer {token}` header and an A2A task payload.

3. Run the demo to test token acquisition:
   ```bash
   uv run python src/auth_demo.py
   ```
   The `demo_client_credentials()` function acquires a token, base64-decodes
   the JWT header and payload (without verification), and displays the claims
   in a rich table.

4. Verify the decoded token's `aud`, `iss`, `roles`, and `exp` claims match
   your App Registration setup from Lab 13A.

5. Test the authenticated call by pointing at a running agent-b (or observe
   the token acquisition succeed even without agent-b running).

**Expected result:**
- The script prints a truncated token and a claims table:
  ```
  ── Task 1: OAuth 2.0 Client Credentials ──
  Tenant:    <your-tenant-id>
  Client ID: <your-client-id>
  Scope:     api://<client-id>/.default

  Token acquired: eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVC...
  ┌─────── JWT Claims (unverified) ────────┐
  │ iss   │ https://sts.windows.net/<tid>/ │
  │ aud   │ api://<client-id>              │
  │ appid │ <agent-a-client-id>            │
  │ tid   │ <tenant-id>                    │
  │ exp   │ 1700003600                     │
  │ iat   │ 1700000000                     │
  └───────┴────────────────────────────────┘
  ```
- The `aud` claim matches the scope target, and `exp - iat` equals 3600 (1 hour)

**Why this matters:**
Client Credentials is the standard OAuth flow for machine-to-machine auth. Understanding the raw token request — not just calling an SDK wrapper — is essential for debugging auth failures. The most common production issue is a wrong `scope` value, which results in a valid token for the wrong audience.

**File:** `lab/src/auth_demo.py`

---

### Lab 13C: JWT Validation in Agent B

**Goal:** Implement server-side JWT validation that verifies signature, audience, issuer, expiry, and role claims for every incoming A2A request.

**What to do:**

1. Open `lab/src/token_validator.py`. The `extract_bearer_token()` function
   is already implemented — review it to understand the header parsing.
   Run the extraction demo:
   ```bash
   uv run python src/token_validator.py --demo
   ```

2. Find `fetch_jwks(tenant_id)`. Implement it: GET the JWKS from
   `https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys`
   and return the parsed JSON (contains a `keys` array).

3. Find `validate_token(token, jwks, audience, issuer)`. Implement it
   using PyJWT: build a `PyJWKClient`, get the signing key from the JWT's
   `kid` header, then call `jwt.decode()` with `algorithms=["RS256"]`,
   `audience`, and `issuer` parameters.

4. Find `extract_auth_context(claims)`. Implement it: extract `appid`/`azp`,
   `tid`, `sub`, and `roles` claims into a structured dict.

5. Validate a real token acquired from Lab 13B:
   ```bash
   uv run python src/token_validator.py --token <paste-jwt-from-lab-13b>
   ```

**Expected result:**
- `--demo` prints a test table showing bearer extraction for valid/invalid headers:
  ```
  ┌─── Bearer Token Extraction Tests ───────────────────────────┐
  │ Input                          │ Expected │ Result           │
  ├────────────────────────────────┼──────────┼──────────────────┤
  │ Bearer eyJhbGci...             │ valid    │ OK (eyJhbGciOiJS…│
  │ bearer eyJhbGci...             │ valid    │ OK (eyJhbGciOiJS…│
  │ Basic dXNlcjpwYXNz             │ invalid  │ Correctly rejected│
  │ Bearer                         │ invalid  │ Correctly rejected│
  │ (empty)                        │ invalid  │ Correctly rejected│
  └────────────────────────────────┴──────────┴──────────────────┘
  ```
- `--token` with a valid JWT prints: `Token is valid.` followed by a claims table and an auth context panel:
  ```json
  {
    "app_id": "<agent-a-client-id>",
    "tenant_id": "<tenant-id>",
    "subject": "<subject-id>",
    "roles": ["agent.invoke"]
  }
  ```
- An expired or tampered token prints: `Validation failed: Signature verification failed`

**Why this matters:**
Every A2A server must validate tokens — skipping any check (especially audience) means a token issued for Service C can be replayed against your service. This lab drills the five-point validation checklist (signature, issuer, audience, expiry, roles) that prevents token confusion attacks in production.

**File:** `lab/src/token_validator.py`

---

### Lab 13D: Managed Identity on Container Apps

**Goal:** Deploy both agents to Azure Container Apps and switch from client secrets to Managed Identity — zero secrets in code or environment.

**Prerequisites:** Run `terraform apply` in the `terraform/` directory first.

**What to do:**

1. Open `lab/src/auth_demo.py`. Find `get_access_token_managed_identity()`.
   Implement IMDS token acquisition: GET
   `http://169.254.169.254/metadata/identity/oauth2/token` with
   `Metadata: true` header. Add a fallback to `az account get-access-token`
   for local development.

2. Build and push container images:
   ```bash
   az acr build --registry YOUR_ACR_NAME --image agent-a:latest -f Dockerfile.agent-a .
   az acr build --registry YOUR_ACR_NAME --image agent-b:latest -f Dockerfile.agent-b .
   ```

3. Assign the Managed Identity of agent-a to the `agent.invoke` role on
   agent-b's App Registration:
   ```bash
   MANAGED_IDENTITY_A_SP_ID=$(az identity show \
     --resource-group YOUR_RG --name agent-a-identity \
     --query "principalId" -o tsv)
   az rest --method POST \
     --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$AGENT_B_SP_ID/appRoleAssignedTo" \
     --body "{\"principalId\": \"$MANAGED_IDENTITY_A_SP_ID\", \"resourceId\": \"$AGENT_B_SP_ID\", \"appRoleId\": \"$ROLE_ID\"}"
   ```

4. Deploy the updated images to Container Apps:
   ```bash
   az containerapp update --name agent-a --resource-group YOUR_RG \
     --image YOUR_ACR_NAME.azurecr.io/agent-a:latest
   ```

5. Test the deployed system — call agent-a's URL (from Terraform output)
   and verify it calls agent-b with a Managed Identity token:
   ```bash
   curl -X POST https://agent-a.<env>.azurecontainerapps.io/tasks/send \
     -H "Content-Type: application/json" \
     -d '{"id":"test-1","message":{"role":"user","parts":[{"type":"text","text":"hello"}]}}'
   ```

**Expected result:**
- Locally, `get_access_token_managed_identity()` falls back to Azure CLI and prints:
  ```
  ── Task 4: Managed Identity ──
  Note: IMDS only works inside Azure. Falls back to Azure CLI locally.
  Token acquired via managed identity: eyJhbGciOiJSUzI1NiIs...
  ```
- On Azure, the IMDS endpoint returns a token in ~50ms with no secrets involved
- The deployed agent-a successfully calls agent-b; the curl response contains a completed task:
  ```json
  {"id": "test-1", "status": "completed", "output": "..."}
  ```
- No `AZURE_CLIENT_SECRET` exists in the Container App's environment variables

**Why this matters:**
Client secrets are the weakest link in service-to-service auth — they can leak in logs, `.env` files, or CI artifacts. Managed Identity eliminates this entire attack surface. The pattern of IMDS-first with client-credentials-fallback lets you develop locally without changing code.

**File:** `lab/src/auth_demo.py`

---

### Lab 13E: End-to-End Authenticated Task Flow

**Goal:** Build a complete, observable, end-to-end authenticated task flow that exercises every auth component from Labs 13A-13D.

**What to do:**

1. Open `lab/src/e2e_test.py`. Build a test harness that exercises the full flow:
   - Client calls agent-a with no token (expects 401)
   - Client calls agent-a with a valid task
   - Agent-a acquires a Managed Identity token (or client credentials locally)
   - Agent-a calls agent-b's `/tasks/send` with the bearer token
   - Agent-b validates the token and processes the task
   - Agent-a assembles and returns the final response

2. Add observability: log a structured JSON trace for each task with timing
   for token acquisition, agent-to-agent latency, validation result,
   caller appid, and total latency.

3. Test security boundaries:
   - Verify a token intended for a different audience is rejected (401)
   - Verify a token with a missing role is rejected with 403 (not 401)
   - Verify an expired token returns 401

4. Document the zero-secret architecture as a code comment in the test harness:
   explain why no secrets exist in the deployed system and what an attacker
   would need to compromise to break the auth chain.

**Expected result:**
- The test harness prints a structured trace for a successful flow:
  ```json
  {
    "task_id": "a1b2c3d4-...",
    "caller": "external-client",
    "agent_a_token_acquisition_ms": 45,
    "agent_a_to_agent_b_latency_ms": 234,
    "agent_b_validation_result": "success",
    "agent_b_caller_appid": "<managed-identity-client-id>",
    "total_latency_ms": 312,
    "status": "completed"
  }
  ```
- Security boundary tests produce:
  ```
  No token:          401 {"error": "unauthorized", "detail": "Missing Authorization header"}
  Wrong audience:    401 {"error": "unauthorized", "detail": "Invalid audience"}
  Missing role:      403 {"error": "forbidden", "detail": "Missing role: agent.invoke"}
  Expired token:     401 {"error": "unauthorized", "detail": "Signature has expired"}
  Valid token:       200 {"id": "...", "status": "completed"}
  ```

**Why this matters:**
Auth bugs often only surface under specific conditions (wrong audience, expired token, missing role). A structured E2E test harness that explicitly exercises every rejection path is the only way to verify your auth layer before production. The structured trace also gives you the observability needed to debug latency issues in token acquisition vs. actual task processing.

**File:** `lab/src/e2e_test.py`

---

## Conceptual Checkpoints

Answer these before moving to Module 14:

1. **Client credentials vs. managed identity**: What is the concrete security
   advantage of Managed Identity over client credentials (client_id + secret)?
   Describe a specific attack scenario that client credentials are vulnerable
   to that Managed Identity prevents.

2. **Token validation order**: Agent B validates tokens in this order:
   signature → issuer → audience → expiry → roles. Why does this order matter?
   What happens if you check the roles before the signature? Give a concrete
   attack scenario.

3. **Least privilege**: Agent A has the `agent.invoke` role on Agent B. Describe
   how you would add a more granular permission model where Agent A can submit
   tasks but not cancel them, while Agent C can do both. What changes in Entra
   ID and what changes in Agent B's code?

4. **Token caching trade-offs**: Your token cache re-acquires tokens 60 seconds
   before expiry. What are the trade-offs of this buffer? What happens if you
   set it to 0 seconds? What happens if you set it to 30 minutes?

5. **mTLS vs. JWT**: Your current system uses JWT for auth. Your security team
   says they want mTLS instead. What are the operational costs of switching?
   What Azure services support mTLS natively? Is there a scenario where you'd
   use both?

---

## Resources

- Azure AD Client Credentials flow:
  https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-oauth2-client-creds-grant-flow
- Azure Container Apps managed identity:
  https://learn.microsoft.com/en-us/azure/container-apps/managed-identity
- PyJWT documentation:
  https://pyjwt.readthedocs.io/
- Azure App Roles:
  https://learn.microsoft.com/en-us/azure/active-directory/develop/howto-add-app-roles-in-apps
- Entra ID JWKS endpoint:
  https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys
- Terraform azurerm Container Apps:
  https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/container_app
