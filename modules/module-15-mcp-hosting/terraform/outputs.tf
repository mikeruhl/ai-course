output "mcp_server_url" {
  description = "Public HTTPS URL of the deployed MCP server."
  value       = "https://${azurerm_container_app.main.latest_revision_fqdn}"
}

output "container_registry_login_server" {
  description = "ACR login server hostname. Use this as the image prefix when pushing: docker push <login_server>/mcp-server:latest"
  value       = azurerm_container_registry.main.login_server
}

output "key_vault_uri" {
  description = "Key Vault URI. Use this to add additional secrets via az keyvault secret set."
  value       = azurerm_key_vault.main.vault_uri
}

output "identity_client_id" {
  description = "Client ID of the user-assigned managed identity. Set as AZURE_CLIENT_ID in the container so the Azure SDK selects the correct identity."
  value       = azurerm_user_assigned_identity.main.client_id
}
