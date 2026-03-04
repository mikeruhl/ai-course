variable "prefix" {
  type        = string
  description = "Short prefix applied to all resource names (e.g. 'a2aauth'). Must be lowercase, 3-10 chars."
}

variable "location" {
  type        = string
  description = "Azure region to deploy resources into."
  default     = "eastus2"
}

variable "subscription_id" {
  type        = string
  description = "Azure subscription ID."
}

variable "tenant_id" {
  type        = string
  description = "Azure AD tenant ID for Entra authentication."
}
