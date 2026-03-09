terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.75"
    }
  }

  backend "azurerm" {
    resource_group_name  = "rg-terraform-state"
    storage_account_name = "stterraformeastwood"
    container_name       = "tfstate"
    key                  = "layer01-keyvaults.tfstate"
  }
}

provider "azurerm" {
  features {}
}

variable "environment" {
  type        = string
  description = "Target environment (dev, staging, prod)"
}

variable "location" {
  type        = string
  default     = "eastus"
  description = "Azure region"
}

variable "project" {
  type        = string
  default     = "eastwood"
}

resource "azurerm_key_vault" "automation" {
  name                       = "kv-automation-${var.environment}"
  location                   = var.location
  resource_group_name        = "rg-${var.project}-${var.environment}"
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 90
  purge_protection_enabled   = true

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    secret_permissions = [
      "Get",
      "List",
      "Set",
      "Delete",
    ]
  }
}

resource "azurerm_key_vault_secret" "db_audit_service" {
  name         = "automation-${var.environment}-dbauditservice"
  value        = var.db_audit_connection_string
  key_vault_id = azurerm_key_vault.automation.id
}

resource "azurerm_key_vault_secret" "db_payment_service" {
  name         = "automation-${var.environment}-dbpaymentservice"
  value        = var.db_payment_connection_string
  key_vault_id = azurerm_key_vault.automation.id
}

resource "azurerm_key_vault_secret" "app_insights_key" {
  name         = "automation-${var.environment}-appinsightskey"
  value        = var.app_insights_instrumentation_key
  key_vault_id = azurerm_key_vault.automation.id
}

data "azurerm_client_config" "current" {}

variable "db_audit_connection_string" {
  type      = string
  sensitive = true
}

variable "db_payment_connection_string" {
  type      = string
  sensitive = true
}

variable "app_insights_instrumentation_key" {
  type      = string
  sensitive = true
}

output "key_vault_id" {
  value = azurerm_key_vault.automation.id
}

output "key_vault_uri" {
  value = azurerm_key_vault.automation.vault_uri
}
