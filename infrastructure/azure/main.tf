terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 3.0"
    }
  }

  backend "azurerm" {
    # Configured at init time via -backend-config flags in the workflow.
    # Run the one-time setup below before first deploy.
  }
}

provider "azurerm" {
  features {}
}

# ── Resource group ────────────────────────────────────────────────────────────

resource "azurerm_resource_group" "na" {
  name     = var.resource_group_name
  location = var.location
}

# ── Networking ────────────────────────────────────────────────────────────────

resource "azurerm_virtual_network" "na" {
  name                = "${var.name}-vnet"
  location            = azurerm_resource_group.na.location
  resource_group_name = azurerm_resource_group.na.name
  address_space       = ["10.0.0.0/16"]
}

resource "azurerm_subnet" "na" {
  name                 = "${var.name}-subnet"
  resource_group_name  = azurerm_resource_group.na.name
  virtual_network_name = azurerm_virtual_network.na.name
  address_prefixes     = ["10.0.1.0/24"]
}

resource "azurerm_public_ip" "na" {
  name                = "${var.name}-pip"
  location            = azurerm_resource_group.na.location
  resource_group_name = azurerm_resource_group.na.name
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_network_security_group" "na" {
  name                = "${var.name}-nsg"
  location            = azurerm_resource_group.na.location
  resource_group_name = azurerm_resource_group.na.name

  security_rule {
    name                       = "SSH"
    priority                   = 1001
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.admin_cidr
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "HTTP"
    priority                   = 1002
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "HTTPS"
    priority                   = 1003
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_network_interface" "na" {
  name                = "${var.name}-nic"
  location            = azurerm_resource_group.na.location
  resource_group_name = azurerm_resource_group.na.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.na.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.na.id
  }
}

resource "azurerm_network_interface_security_group_association" "na" {
  network_interface_id      = azurerm_network_interface.na.id
  network_security_group_id = azurerm_network_security_group.na.id
}

# ── VM ────────────────────────────────────────────────────────────────────────

resource "azurerm_linux_virtual_machine" "na" {
  name                = var.name
  location            = azurerm_resource_group.na.location
  resource_group_name = azurerm_resource_group.na.name
  size                = var.vm_size

  admin_username                  = "azureuser"
  disable_password_authentication = true

  admin_ssh_key {
    username   = "azureuser"
    public_key = var.ssh_public_key
  }

  network_interface_ids = [azurerm_network_interface.na.id]

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    disk_size_gb         = 30
  }

  custom_data = base64encode(templatefile(
    "${path.module}/../universal_boot.sh",
    {
      bootstrap_endpoint = var.bootstrap_endpoint
      genesis_uri        = var.genesis_uri
    }
  ))

  tags = {
    role    = "network-authority"
    project = "genesis-mesh"
  }
}
