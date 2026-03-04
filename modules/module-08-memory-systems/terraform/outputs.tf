output "search_endpoint" {
  description = "Azure AI Search endpoint URL. Set as AZURE_SEARCH_ENDPOINT in your .env file."
  value       = local.search_endpoint
}

output "search_admin_key" {
  description = "Azure AI Search admin key. Set as AZURE_SEARCH_KEY in your .env file."
  value       = local.search_admin_key
  sensitive   = true
}

output "search_name" {
  description = "Azure AI Search service name."
  value       = azurerm_search_service.main.name
}

output "resource_group_name" {
  description = "Resource group name — needed if you reference this infrastructure from other modules."
  value       = azurerm_resource_group.main.name
}
