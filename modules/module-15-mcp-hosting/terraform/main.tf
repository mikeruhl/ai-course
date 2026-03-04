# Deployment workflow:
# 1. terraform apply — provisions infrastructure
# 2. Build and push Docker image:
#    docker build -t ${prefix}acr.azurecr.io/mcp-server:latest ./lab
#    az acr login --name ${prefix}acr
#    docker push ${prefix}acr.azurecr.io/mcp-server:latest
# 3. Update container app to use new image:
#    az containerapp update --name ${prefix}-mcp-server \
#      --resource-group ${prefix}-rg \
#      --image ${prefix}acr.azurecr.io/mcp-server:latest

terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~>4.0"
    }
  }
}

provider "azurerm" {
  subscription_id = var.subscription_id
  features {
    key_vault {
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = false
    }
  }
}

# ---------------------------------------------------------------------------
# Resource Group
# ---------------------------------------------------------------------------
resource "azurerm_resource_group" "main" {
  name     = "${var.prefix}-rg"
  location = var.location
}

# ---------------------------------------------------------------------------
# Container Registry — stores the MCP server Docker image
# ---------------------------------------------------------------------------
resource "azurerm_container_registry" "main" {
  name                = "${var.prefix}acr"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = true
}

# ---------------------------------------------------------------------------
# Log Analytics Workspace — used by the Container App Environment
# ---------------------------------------------------------------------------
resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.prefix}-logs"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

# ---------------------------------------------------------------------------
# Container App Environment — the hosting boundary for Container Apps
# ---------------------------------------------------------------------------
resource "azurerm_container_app_environment" "main" {
  name                       = "${var.prefix}-cae"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
}

# ---------------------------------------------------------------------------
# Key Vault — stores secrets (Azure OpenAI key, etc.)
# ---------------------------------------------------------------------------
data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "main" {
  name                        = "${var.prefix}-kv"
  resource_group_name         = azurerm_resource_group.main.name
  location                    = azurerm_resource_group.main.location
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  sku_name                    = "standard"
  soft_delete_retention_days  = 7
  purge_protection_enabled    = false
}

# Store the Azure OpenAI key in Key Vault
resource "azurerm_key_vault_secret" "azure_openai_key" {
  name         = "azure-openai-key"
  value        = var.azure_openai_key
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault_access_policy.deployer]
}

# Allow the Terraform runner (deployer) to manage secrets during apply
resource "azurerm_key_vault_access_policy" "deployer" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  secret_permissions = ["Get", "List", "Set", "Delete", "Purge"]
}

# ---------------------------------------------------------------------------
# User-Assigned Managed Identity — the MCP server's runtime identity
# ---------------------------------------------------------------------------
resource "azurerm_user_assigned_identity" "main" {
  name                = "${var.prefix}-mcp-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
}

# Grant the MCP server identity read access to Key Vault secrets
resource "azurerm_key_vault_access_policy" "mcp_server" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_user_assigned_identity.main.principal_id

  secret_permissions = ["Get", "List"]
}

# ---------------------------------------------------------------------------
# Container App — runs the MCP server
# ---------------------------------------------------------------------------
resource "azurerm_container_app" "main" {
  name                         = "${var.prefix}-mcp-server"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  # Attach the user-assigned managed identity so the container can
  # authenticate to Key Vault and Azure OpenAI without a stored credential.
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.main.id]
  }

  # Secrets registered at the Container App level.
  # The Key Vault reference pattern: pull the secret value into a Container App
  # secret, then surface it as an env var inside the container.
  secret {
    name                = "azure-openai-key"
    key_vault_secret_id = azurerm_key_vault_secret.azure_openai_key.id
    identity            = azurerm_user_assigned_identity.main.id
  }

  ingress {
    external_enabled = true
    target_port      = 3000
    transport        = "http"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = 0
    max_replicas = 3

    container {
      name   = "mcp-server"
      image  = "${azurerm_container_registry.main.login_server}/mcp-server:latest"
      cpu    = 0.25
      memory = "0.5Gi"

      # The managed identity client ID tells the Azure SDK which identity to
      # use when the container has multiple identities assigned.
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.main.client_id
      }

      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = var.azure_openai_endpoint
      }

      # Reference the Container App secret (which is itself sourced from Key Vault).
      # This keeps the raw key value out of Terraform state and out of the
      # container's environment in plain text at the infra-definition layer.
      env {
        name        = "AZURE_OPENAI_KEY"
        secret_name = "azure-openai-key"
      }
    }
  }

  depends_on = [
    azurerm_key_vault_access_policy.mcp_server,
    azurerm_key_vault_secret.azure_openai_key,
  ]
}
