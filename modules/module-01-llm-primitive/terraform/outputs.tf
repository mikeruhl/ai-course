output "openai_endpoint" {
  description = "Azure OpenAI endpoint URL. Set as AZURE_OPENAI_ENDPOINT in your .env file."
  value       = azurerm_cognitive_account.openai.endpoint
}

output "openai_deployment_name" {
  description = "The model deployment name. Set as AZURE_OPENAI_DEPLOYMENT in your .env file."
  value       = azurerm_cognitive_deployment.gpt4o_mini.name
}

output "openai_api_key" {
  description = "Azure OpenAI primary API key. Set as AZURE_OPENAI_KEY in your .env file."
  value       = azurerm_cognitive_account.openai.primary_access_key
  sensitive   = true
}

output "resource_group_name" {
  description = "Resource group name — needed by later modules in this week."
  value       = azurerm_resource_group.main.name
}
