variable "environment" {
  type = string
}

variable "project" {
  type = string
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${var.project}-${var.environment}"
  location            = "eastus"
  resource_group_name = "rg-${var.project}-${var.environment}"
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_application_insights" "main" {
  name                = "appi-${var.project}-${var.environment}"
  location            = "eastus"
  resource_group_name = "rg-${var.project}-${var.environment}"
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
}

output "app_insights_key" {
  value     = azurerm_application_insights.main.instrumentation_key
  sensitive = true
}
