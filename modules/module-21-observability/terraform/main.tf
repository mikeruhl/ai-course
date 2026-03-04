terraform {
  required_version = ">= 1.6"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
  # Authentication via Azure CLI: run `az login` before `terraform apply`
}

# ---------------------------------------------------------------------------
# Resource Group
# ---------------------------------------------------------------------------
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    course  = "ai-engineering"
    module  = "21"
    managed = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Log Analytics Workspace
# All Application Insights data flows through Log Analytics — this is the
# storage and query layer. App Insights is the ingestion + query UI on top.
# PerGB2018 SKU: pay only for data ingested (no per-node charge).
# ---------------------------------------------------------------------------
resource "azurerm_log_analytics_workspace" "main" {
  name                = var.log_analytics_workspace_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = {
    course  = "ai-engineering"
    module  = "21"
    managed = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Application Insights
# Linked to the Log Analytics workspace above (workspace-based mode).
# application_type = "web" is the standard for HTTP-based services and agents.
# The connection_string output is what your Python code uses to send telemetry.
# ---------------------------------------------------------------------------
resource "azurerm_application_insights" "main" {
  name                = var.app_insights_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.main.id

  tags = {
    course  = "ai-engineering"
    module  = "21"
    managed = "terraform"
  }
}
