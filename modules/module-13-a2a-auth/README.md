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

---

### Lab 13A: App Registration Setup

**Goal:** Create the App Registrations for agent-a and agent-b using az CLI.

**Tasks:**

1. Create the App Registration for agent-b (the server that needs to be protected):
   ```bash
   # Create the App Registration
   az ad app create --display-name "agent-b" \
     --identifier-uris "api://agent-b"

   # Note the appId (client ID)
   AGENT_B_APP_ID=$(az ad app list --display-name "agent-b" --query "[0].appId" -o tsv)

   # Create a service principal (needed for role assignments)
   az ad sp create --id $AGENT_B_APP_ID
   ```

2. Add the `agent.invoke` App Role to agent-b:
   ```bash
   # Add app role via manifest update
   az ad app update --id $AGENT_B_APP_ID --app-roles @app-role.json
   ```
   Create `app-role.json` with the role definition (see README template in
   starter file).

3. Create the App Registration for agent-a (the caller):
   ```bash
   az ad app create --display-name "agent-a"
   AGENT_A_APP_ID=$(az ad app list --display-name "agent-a" --query "[0].appId" -o tsv)
   az ad sp create --id $AGENT_A_APP_ID

   # Create a client secret
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

**File:** `lab/src/setup_app_registrations.sh` (reference script with commands)

---

### Lab 13B: OAuth Client Credentials Flow

**Goal:** Implement token acquisition and injection in agent-a.

**Tasks:**

1. Implement `acquire_token(tenant_id, client_id, client_secret, scope) -> str`:
   - POST to `https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token`
   - Body: `grant_type=client_credentials&client_id=...&client_secret=...&scope=...`
   - Return the `access_token` string

2. Add token caching: cache the token with its expiry time. Re-acquire only
   when the token expires (or 60 seconds before expiry as a buffer):
   ```python
   class TokenCache:
       def get_token(self, ...) -> str: ...
       # Returns cached token if valid, otherwise acquires a new one
   ```

3. Build agent-a's request function: `call_agent_b(task: dict) -> dict`
   - Acquires a token using the cache
   - POSTs to agent-b's `/tasks/send` endpoint
   - Includes `Authorization: Bearer {token}` header
   - Returns the completed task

4. Test by running a standalone script (before agent-b validates tokens):
   - Acquire a token
   - Decode it (without verification) and print the claims
   - Verify the `aud`, `iss`, `roles`, and `exp` claims are correct

5. Print the decoded token in a rich table: claim name, value, human-readable
   description of what it means.

**File:** `lab/src/token_client.py`

---

### Lab 13C: JWT Validation in Agent B

**Goal:** Implement token validation middleware in agent-b's FastAPI server.

**Tasks:**

1. Implement `validate_bearer_token(authorization_header: str) -> dict`:
   - Extract the token from `Authorization: Bearer {token}`
   - Use `PyJWKClient` to fetch signing keys from Azure AD JWKS endpoint
   - Use `jwt.decode()` with audience, issuer, and RS256 algorithm
   - Check the `roles` claim contains `agent.invoke`
   - Return the validated payload on success
   - Raise `TokenValidationError` (custom exception) on any failure

2. Add a FastAPI dependency that validates the token:
   ```python
   async def require_auth(authorization: str = Header(...)) -> dict:
       return validate_bearer_token(authorization)
   ```

3. Build agent-b as a FastAPI server with:
   - `GET /.well-known/agent.json` — unprotected Agent Card
   - `POST /tasks/send` — protected, requires valid token with `agent.invoke` role
   - Returns 401 with `{"error": "unauthorized", "detail": "..."}` for auth failures
   - Returns 403 with `{"error": "forbidden", "detail": "Missing role: agent.invoke"}` for missing role

4. Add auth logging: log each request with: caller appid, roles present,
   validation result (success/failure), task id.

5. Test the full flow: run agent-b locally, run agent-a's token_client.py
   against it. Verify:
   - Valid token succeeds
   - Expired token (manipulate the `exp` claim) returns 401
   - Token without the role returns 403
   - No token returns 401

**File:** `lab/src/agent_b_server.py`

---

### Lab 13D: Managed Identity on Container Apps

**Goal:** Deploy both agents to Azure Container Apps and switch to Managed Identity.

**Prerequisites:** Run `terraform apply` in the `terraform/` directory first.

**Tasks:**

1. Create container images for agent-a and agent-b:
   ```bash
   # Build both images
   docker build -t agent-a:latest -f Dockerfile.agent-a .
   docker build -t agent-b:latest -f Dockerfile.agent-b .

   # Push to Azure Container Registry (or Docker Hub for dev)
   az acr build --registry YOUR_ACR_NAME --image agent-a:latest -f Dockerfile.agent-a .
   az acr build --registry YOUR_ACR_NAME --image agent-b:latest -f Dockerfile.agent-b .
   ```

2. Implement Managed Identity token acquisition in agent-a:
   ```python
   def acquire_token_managed_identity(resource: str) -> str:
       """Get a token from IMDS (only works inside Azure Container Apps)."""
       response = httpx.get(
           "http://169.254.169.254/metadata/identity/oauth2/token",
           params={"api-version": "2018-02-01", "resource": resource},
           headers={"Metadata": "true"},
           timeout=10
       )
       response.raise_for_status()
       return response.json()["access_token"]
   ```

3. Add environment detection: use Managed Identity if `AZURE_CONTAINER_APP`
   env var is set, fall back to client credentials for local development:
   ```python
   def get_token(resource: str) -> str:
       if os.getenv("AZURE_CONTAINER_APP"):
           return acquire_token_managed_identity(resource)
       return token_cache.get_token(...)  # client credentials
   ```

4. Assign the Managed Identity of agent-a to the `agent.invoke` role on
   agent-b's App Registration:
   ```bash
   MANAGED_IDENTITY_A_SP_ID=$(az identity show \
     --resource-group YOUR_RG \
     --name agent-a-identity \
     --query "principalId" -o tsv)

   az rest --method POST \
     --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$AGENT_B_SP_ID/appRoleAssignedTo" \
     --body "{\"principalId\": \"$MANAGED_IDENTITY_A_SP_ID\", ...}"
   ```

5. Deploy the updated images to Container Apps:
   ```bash
   # Update the container app to use the real image
   az containerapp update \
     --name agent-a \
     --resource-group YOUR_RG \
     --image YOUR_ACR_NAME.azurecr.io/agent-a:latest
   ```

   Test the deployed system: call agent-a's URL (from Terraform output), verify
   it successfully calls agent-b with a Managed Identity token.

**File:** `lab/src/agent_a_managed_identity.py`

---

### Lab 13E: End-to-End Authenticated Task Flow

**Goal:** Build a complete, observable authenticated task flow.

**Tasks:**

1. Build a test harness that exercises the complete flow:
   - Client calls agent-a with an unauthenticated request (gets 401)
   - Client calls agent-a with a valid task
   - Agent-a acquires a Managed Identity token
   - Agent-a calls agent-b's `/tasks/send` with the token
   - Agent-b validates the token and processes the task
   - Agent-b returns the completed task
   - Agent-a assembles and returns the final response

2. Add observability: log a structured trace for each task:
   ```json
   {
     "task_id": "uuid",
     "caller": "external-client",
     "agent_a_token_acquisition_ms": 45,
     "agent_a_to_agent_b_latency_ms": 234,
     "agent_b_validation_result": "success",
     "agent_b_caller_appid": "managed-identity-client-id",
     "total_latency_ms": 312,
     "status": "completed"
   }
   ```

3. Test security boundaries:
   - Verify a token intended for a different audience is rejected
   - Verify a token with a missing role is rejected with 403 (not 401)
   - Verify token replay is not possible (tokens expire — test with a 1-second
     expiry if your identity provider allows it)

4. Document the zero-secret architecture: write a brief summary (as a code
   comment in the test harness) explaining why there are no secrets in the
   deployed system and what an attacker would need to compromise it.

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
