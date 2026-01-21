terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 3.0"
    }
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
    alicloud = {
      source  = "aliyun/alicloud"
      version = ">= 1.0"
    }
    null = {
      source  = "hashicorp/null"
      version = ">= 3.0"
    }
  }
}

locals {
  user_data = templatefile("${path.module}/universal_boot.sh", {
    bootstrap_endpoint = var.bootstrap_endpoint
    genesis_uri        = var.genesis_uri
  })

  is_aws         = var.target_provider == "aws"
  is_azure       = var.target_provider == "azure"
  is_gcp         = var.target_provider == "gcp"
  is_alibaba     = var.target_provider == "alibaba"
  is_generic_ssh = var.target_provider == "generic_ssh"
}

resource "aws_instance" "sovereign" {
  count         = local.is_aws ? 1 : 0
  ami           = var.aws_ami
  instance_type = var.aws_instance_type
  subnet_id     = var.aws_subnet_id

  vpc_security_group_ids = var.aws_security_group_ids
  user_data              = local.user_data

  tags = {
    Name = var.node_name
  }
}

resource "azurerm_linux_virtual_machine" "sovereign" {
  count               = local.is_azure ? 1 : 0
  name                = var.node_name
  location            = var.azure_location
  resource_group_name = var.azure_resource_group_name
  size                = var.azure_vm_size

  admin_username                  = "azureuser"
  disable_password_authentication = true

  admin_ssh_key {
    username   = "azureuser"
    public_key = var.azure_ssh_public_key
  }

  network_interface_ids = [var.azure_subnet_id]
  custom_data           = base64encode(local.user_data)

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }
}

resource "google_compute_instance" "sovereign" {
  count        = local.is_gcp ? 1 : 0
  name         = var.node_name
  project      = var.gcp_project
  zone         = var.gcp_zone
  machine_type = var.gcp_machine_type

  boot_disk {
    initialize_params {
      image = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts"
    }
  }

  network_interface {
    network = var.gcp_network
    access_config {}
  }

  metadata_startup_script = local.user_data
}

resource "alicloud_instance" "sovereign" {
  count         = local.is_alibaba ? 1 : 0
  instance_name = var.node_name
  instance_type = var.alibaba_instance_type
  image_id      = var.alibaba_image_id
  vswitch_id    = var.alibaba_vswitch_id

  user_data = base64encode(local.user_data)
}

resource "null_resource" "generic_ssh" {
  count = local.is_generic_ssh ? 1 : 0

  connection {
    type        = "ssh"
    host        = var.generic_ssh_host
    user        = var.generic_ssh_user
    private_key = var.generic_ssh_private_key
  }

  provisioner "file" {
    content     = local.user_data
    destination = "/tmp/universal_boot.sh"
  }

  provisioner "remote-exec" {
    inline = [
      "chmod +x /tmp/universal_boot.sh",
      "/tmp/universal_boot.sh",
    ]
  }
}
