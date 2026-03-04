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
  subscription_id = var.subscription_id
}

# ---------------------------------------------------------------------------
# Resource Group
# ---------------------------------------------------------------------------
resource "azurerm_resource_group" "main" {
  name     = "${var.prefix}-rg"
  location = var.location

  tags = {
    course  = "ai-engineering"
    module  = "08"
    managed = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Azure AI Search
# Used as the vector store for semantic memory.
# Basic SKU supports 15 indexes, 2GB storage — sufficient for all lab exercises.
# Upgrade to "standard" if you need more capacity or replicas for HA.
# ---------------------------------------------------------------------------
resource "azurerm_search_service" "main" {
  name                = "${var.prefix}-search"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "basic"
  replica_count       = 1
  partition_count     = 1

  tags = {
    course  = "ai-engineering"
    module  = "08"
    managed = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Locals — convenience values used in outputs
# ---------------------------------------------------------------------------
locals {
  search_endpoint  = "https://${azurerm_search_service.main.name}.search.windows.net"
  search_admin_key = azurerm_search_service.main.primary_key
}
