terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
  }
}

provider "azurerm" {
  features {}
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${var.prefix}-mod23"
  location = var.location
  tags     = var.tags
}

# Storage account — required by Azure Durable Functions for state persistence
resource "azurerm_storage_account" "main" {
  name                     = "${var.prefix}mod23stor"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  tags                     = var.tags
}

# Application Insights for function monitoring
resource "azurerm_application_insights" "main" {
  name                = "${var.prefix}-mod23-insights"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  application_type    = "web"
  tags                = var.tags
}

# Consumption plan for Azure Functions
resource "azurerm_service_plan" "main" {
  name                = "${var.prefix}-mod23-plan"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = "Y1"
  tags                = var.tags
}

# Function App — hosts Durable Functions orchestrations
resource "azurerm_linux_function_app" "main" {
  name                       = "${var.prefix}-mod23-func"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  service_plan_id            = azurerm_service_plan.main.id
  storage_account_name       = azurerm_storage_account.main.name
  storage_account_access_key = azurerm_storage_account.main.primary_access_key
  tags                       = var.tags

  site_config {
    application_stack {
      python_version = "3.11"
    }
  }

  app_settings = {
    "FUNCTIONS_WORKER_RUNTIME"           = "python"
    "APPINSIGHTS_INSTRUMENTATIONKEY"     = azurerm_application_insights.main.instrumentation_key
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.main.connection_string
  }
}
