# Course Setup

One-time environment setup. Do this before starting Module 1.

---

## 1. Install uv (Python toolchain)

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Verify:
```bash
uv --version   # should print uv 0.5.x or later
```

uv replaces pip, venv, pip-tools, and pyenv in one tool. Each module lab
is a uv-managed Python project with a `pyproject.toml`.

---

## 2. Install Azure CLI

```bash
# macOS
brew install azure-cli

# Windows (winget)
winget install Microsoft.AzureCLI

# Linux
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

Verify:
```bash
az --version
```

Login to your Azure subscription:
```bash
az login

# If you have multiple subscriptions, set the one for this course:
az account set --subscription "<your-subscription-name-or-id>"
az account show   # confirm the right subscription is active
```

---

## 3. Install Terraform

```bash
# macOS
brew tap hashicorp/tap && brew install hashicorp/tap/terraform

# Windows (winget)
winget install Hashicorp.Terraform

# Linux — see https://developer.hashicorp.com/terraform/install
```

Verify:
```bash
terraform --version   # should be >= 1.6
```

---

## 4. Configure Terraform Azure Authentication

Terraform will authenticate to Azure using your Azure CLI session.
No additional setup needed — when you run `terraform apply`, it uses
the same credentials as `az login`.

For CI/CD or shared environments, use a service principal instead. That's
covered in Module 9 (A2A Authentication).

---

## 5. Verify Everything

```bash
az account show                        # Azure CLI logged in
terraform --version                    # Terraform installed
uv --version                           # uv installed
python --version                       # should be 3.11+ via uv
```

---

## 6. Register Azure OpenAI (One-time)

Azure OpenAI requires feature registration. Check if already registered:

```bash
az provider show --namespace Microsoft.CognitiveServices --query "registrationState"
```

If not `"Registered"`:
```bash
az provider register --namespace Microsoft.CognitiveServices
# Wait ~2 minutes, then re-check
```

Some regions require an explicit application for Azure OpenAI access.
If your first `terraform apply` in Module 1 fails with a quota or access
error, visit:
https://aka.ms/oai/access

---

## 7. Choose Your Azure Region

Azure OpenAI model availability varies by region. Recommended regions
with broad model availability (as of early 2026):

- `eastus` — widest model availability, recommended default
- `eastus2` — good availability
- `swedencentral` — good for European users

You'll set this in each module's `terraform/terraform.tfvars`.

---

## Done

You're ready to start [Module 1](../modules/module-01-llm-primitive/README.md).
