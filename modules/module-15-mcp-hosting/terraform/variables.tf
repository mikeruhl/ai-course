variable "prefix" {
  type        = string
  description = "Resource name prefix, e.g. 'mcplab'. Used for all resource names to avoid collisions."

  validation {
    condition     = can(regex("^[a-z0-9]{3,12}$", var.prefix))
    error_message = "prefix must be 3-12 lowercase alphanumeric characters (no hyphens — used in ACR name which disallows them)."
  }
}

variable "location" {
  type        = string
  default     = "eastus2"
  description = "Azure region for all resources."
}

variable "subscription_id" {
  type        = string
  description = "Azure subscription ID."
}

variable "azure_openai_key" {
  type        = string
  sensitive   = true
  description = "Azure OpenAI API key — stored in Key Vault, never written to container env directly."
}

variable "azure_openai_endpoint" {
  type        = string
  description = "Azure OpenAI endpoint URL, e.g. https://<account>.openai.azure.com"
}
