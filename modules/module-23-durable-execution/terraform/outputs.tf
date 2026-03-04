output "function_app_url" {
  description = "Function App default hostname"
  value       = "https://${azurerm_linux_function_app.main.default_hostname}"
}

output "function_app_name" {
  description = "Function App name"
  value       = azurerm_linux_function_app.main.name
}

output "storage_account_name" {
  description = "Storage account name (used by Durable Functions)"
  value       = azurerm_storage_account.main.name
}

output "application_insights_connection_string" {
  description = "Application Insights connection string"
  value       = azurerm_application_insights.main.connection_string
  sensitive   = true
}
