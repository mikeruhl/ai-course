variable "prefix" {
  description = "Short prefix for all resource names (e.g. 'ailearn'). Must be lowercase alphanumeric, 3-8 chars. Used to build globally-unique names."
  type        = string
}

variable "location" {
  description = "Azure region. eastus2 has broad model availability and AI Search support."
  type        = string
  default     = "eastus2"
}

variable "subscription_id" {
  description = "Azure subscription ID. Find with: az account show --query id -o tsv"
  type        = string
}
