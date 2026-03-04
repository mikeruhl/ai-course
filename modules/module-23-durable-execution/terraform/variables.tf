variable "prefix" {
  description = "Resource name prefix"
  type        = string
  default     = "aicourse"
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus2"
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default = {
    project = "ai-course"
    module  = "23-durable-execution"
  }
}
