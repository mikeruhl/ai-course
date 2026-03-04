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
}

# ---------------------------------------------------------------------------
# Resource Group
# ---------------------------------------------------------------------------
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    course  = "ai-engineering"
    module  = "01"
    managed = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Azure OpenAI Service
# Shared across all Week 1 modules (01, 02, 03)
# ---------------------------------------------------------------------------
resource "azurerm_cognitive_account" "openai" {
  name                = var.openai_account_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  kind                = "OpenAI"
  sku_name            = "S0"

  tags = {
    course  = "ai-engineering"
    module  = "01"
    managed = "terraform"
  }
}

# ---------------------------------------------------------------------------
# GPT-4o-mini deployment
# Used for all Week 1 labs. Low cost, fast, sufficient for all exercises.
# Swap for gpt-4o if you want higher capability at higher cost.
# ---------------------------------------------------------------------------
resource "azurerm_cognitive_deployment" "gpt4o_mini" {
  name                 = "gpt-4o-mini"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "gpt-4o-mini"
    version = "2024-07-18"
  }

  sku {
    name     = "GlobalStandard"
    capacity = 30 # tokens per minute in thousands (30 = 30k TPM)
  }
}
