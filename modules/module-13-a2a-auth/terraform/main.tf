terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~>4.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

# ---------------------------------------------------------------------------
# Resource Group
# ---------------------------------------------------------------------------
resource "azurerm_resource_group" "main" {
  name     = "${var.prefix}-rg"
  location = var.location
}

# ---------------------------------------------------------------------------
# User-Assigned Managed Identity
# Agents use this identity to authenticate with each other and Azure services.
# ---------------------------------------------------------------------------
resource "azurerm_user_assigned_identity" "agent" {
  name                = "${var.prefix}-agent-identity"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
}

# ---------------------------------------------------------------------------
# Container App Environment
# Shared networking layer for all agents in this module.
# ---------------------------------------------------------------------------
resource "azurerm_container_app_environment" "main" {
  name                = "${var.prefix}-cae"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  # infrastructure_subnet_id omitted — uses the default managed subnet.
  # Add a subnet_id here if you need VNet integration (Module 13 extension).
}

# ---------------------------------------------------------------------------
# Planner Agent — Container App
# ---------------------------------------------------------------------------
resource "azurerm_container_app" "planner" {
  name                         = "${var.prefix}-planner"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.agent.id]
  }

  template {
    container {
      name   = "planner-agent"
      image  = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.agent.client_id
      }
      env {
        name  = "AZURE_TENANT_ID"
        value = var.tenant_id
      }
      env {
        name  = "RESEARCHER_AGENT_URL"
        value = "https://${azurerm_container_app.researcher.latest_revision_fqdn}"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}

# ---------------------------------------------------------------------------
# Researcher Agent — Container App
# ---------------------------------------------------------------------------
resource "azurerm_container_app" "researcher" {
  name                         = "${var.prefix}-researcher"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.agent.id]
  }

  template {
    container {
      name   = "researcher-agent"
      image  = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.agent.client_id
      }
      env {
        name  = "AZURE_TENANT_ID"
        value = var.tenant_id
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}

# ---------------------------------------------------------------------------
# Key Vault
# Stores agent secrets and API keys. Managed Identity is granted access below.
# ---------------------------------------------------------------------------
resource "azurerm_key_vault" "main" {
  name                = "${var.prefix}-kv"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku_name            = "standard"
  tenant_id           = var.tenant_id

  # Soft-delete is required by azurerm ~>4.0 (enabled by default, 90-day retention).
  soft_delete_retention_days = 7
  purge_protection_enabled   = false

  access_policy {
    tenant_id = var.tenant_id
    object_id = azurerm_user_assigned_identity.agent.principal_id

    secret_permissions = [
      "Get",
      "List",
    ]
  }
}
