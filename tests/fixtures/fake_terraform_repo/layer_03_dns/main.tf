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
    key                  = "layer03-dns.tfstate"
  }
}

provider "azurerm" {
  features {}
}

variable "environment" {
  type = string
}

variable "project" {
  type    = string
  default = "eastwood"
}

variable "domain" {
  type    = string
  default = "eastwood.internal"
}

resource "azurerm_dns_zone" "main" {
  name                = "${var.environment}.${var.domain}"
  resource_group_name = "rg-${var.project}-${var.environment}"
}

resource "azurerm_dns_a_record" "audit" {
  name                = "audit-service"
  zone_name           = azurerm_dns_zone.main.name
  resource_group_name = "rg-${var.project}-${var.environment}"
  ttl                 = 300
  records             = ["10.0.1.100"]
}

resource "azurerm_dns_a_record" "payment" {
  name                = "payment-service"
  zone_name           = azurerm_dns_zone.main.name
  resource_group_name = "rg-${var.project}-${var.environment}"
  ttl                 = 300
  records             = ["10.0.1.101"]
}

module "monitoring" {
  source      = "../modules/monitoring"
  environment = var.environment
  project     = var.project
}

output "dns_zone_id" {
  value = azurerm_dns_zone.main.id
}
