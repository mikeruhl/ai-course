output "app_insights_name" {
  description = "Application Insights resource name."
  value       = azurerm_application_insights.main.name
}

output "instrumentation_key" {
  description = "Application Insights instrumentation key. Use connection_string instead for new code."
  value       = azurerm_application_insights.main.instrumentation_key
  sensitive   = true
}

output "connection_string" {
  description = "Application Insights connection string. Set as APPLICATIONINSIGHTS_CONNECTION_STRING in your .env file."
  value       = azurerm_application_insights.main.connection_string
  sensitive   = true
}

output "log_analytics_workspace_id" {
  description = "Log Analytics workspace resource ID — needed if you add diagnostic settings to other resources."
  value       = azurerm_log_analytics_workspace.main.id
}

output "resource_group_name" {
  description = "Resource group name."
  value       = azurerm_resource_group.main.name
}
