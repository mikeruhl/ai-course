variable "resource_group_name" {
  description = "Name of the Azure resource group. Shared across all Week 1 modules."
  type        = string
  default     = "rg-ai-course-week01"
}

variable "location" {
  description = "Azure region. Use eastus for widest model availability."
  type        = string
  default     = "eastus"
}

variable "openai_account_name" {
  description = "Name of the Azure OpenAI account. Must be globally unique."
  type        = string
  # No default — must be set in terraform.tfvars
}
