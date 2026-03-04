output "planner_agent_url" {
  description = "Public HTTPS URL of the planner agent Container App."
  value       = "https://${azurerm_container_app.planner.latest_revision_fqdn}"
}

output "researcher_agent_url" {
  description = "Public HTTPS URL of the researcher agent Container App."
  value       = "https://${azurerm_container_app.researcher.latest_revision_fqdn}"
}

output "identity_client_id" {
  description = "Client ID of the user-assigned managed identity (use as AZURE_CLIENT_ID in apps)."
  value       = azurerm_user_assigned_identity.agent.client_id
}

output "identity_principal_id" {
  description = "Principal (object) ID of the managed identity (use for RBAC assignments)."
  value       = azurerm_user_assigned_identity.agent.principal_id
}

output "key_vault_uri" {
  description = "URI of the Key Vault (e.g. https://<name>.vault.azure.net/)."
  value       = azurerm_key_vault.main.vault_uri
}
