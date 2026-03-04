variable "resource_group_name" {
  description = "Name of the Azure resource group for module-21 observability resources."
  type        = string
  default     = "rg-ai-course-module21"
}

variable "location" {
  description = "Azure region. Use eastus for widest availability."
  type        = string
  default     = "eastus"
}

variable "log_analytics_workspace_name" {
  description = "Name of the Log Analytics workspace. Must be globally unique within the subscription."
  type        = string
  # No default — set in terraform.tfvars
}

variable "app_insights_name" {
  description = "Name of the Application Insights resource. Must be unique within the resource group."
  type        = string
  # No default — set in terraform.tfvars
}
