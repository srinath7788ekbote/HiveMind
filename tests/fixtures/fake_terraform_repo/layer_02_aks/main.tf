terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.75"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
  }

  backend "azurerm" {
    resource_group_name  = "rg-terraform-state"
    storage_account_name = "stterraformeastwood"
    container_name       = "tfstate"
    key                  = "layer02-aks.tfstate"
  }
}

provider "azurerm" {
  features {}
}

variable "environment" {
  type = string
}

variable "location" {
  type    = string
  default = "eastus"
}

variable "project" {
  type    = string
  default = "eastwood"
}

variable "node_count" {
  type    = number
  default = 3
}

variable "vm_size" {
  type    = string
  default = "Standard_D4s_v5"
}

resource "azurerm_kubernetes_cluster" "main" {
  name                = "aks-${var.project}-${var.environment}"
  location            = var.location
  resource_group_name = "rg-${var.project}-${var.environment}"
  dns_prefix          = "${var.project}-${var.environment}"

  default_node_pool {
    name       = "default"
    node_count = var.node_count
    vm_size    = var.vm_size
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin = "azure"
    network_policy = "calico"
  }
}

data "azurerm_key_vault" "automation" {
  name                = "kv-automation-${var.environment}"
  resource_group_name = "rg-${var.project}-${var.environment}"
}

data "azurerm_key_vault_secret" "db_audit" {
  name         = "automation-${var.environment}-dbauditservice"
  key_vault_id = data.azurerm_key_vault.automation.id
}

data "azurerm_key_vault_secret" "db_payment" {
  name         = "automation-${var.environment}-dbpaymentservice"
  key_vault_id = data.azurerm_key_vault.automation.id
}

resource "kubernetes_secret" "audit_db" {
  metadata {
    name      = "audit-db-secret"
    namespace = "audit"
  }

  data = {
    connection_string = data.azurerm_key_vault_secret.db_audit.value
  }
}

resource "kubernetes_secret" "payment_db" {
  metadata {
    name      = "payment-db-secret"
    namespace = "payment"
  }

  data = {
    connection_string = data.azurerm_key_vault_secret.db_payment.value
  }
}

output "cluster_name" {
  value = azurerm_kubernetes_cluster.main.name
}

output "kube_config" {
  value     = azurerm_kubernetes_cluster.main.kube_config_raw
  sensitive = true
}
