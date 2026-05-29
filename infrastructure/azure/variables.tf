variable "name" {
  description = "Name prefix for all resources."
  type        = string
  default     = "genesis-mesh-na"
}

variable "resource_group_name" {
  description = "Azure resource group name."
  type        = string
  default     = "genesis-mesh-rg"
}

variable "location" {
  description = "Azure region."
  type        = string
  default     = "swedencentral"
}

variable "vm_size" {
  description = "Azure VM size. Standard_B1ms (1 vCPU, 2 GB) is the minimum for Gunicorn."
  type        = string
  default     = "Standard_B2s"
}

variable "ssh_public_key" {
  description = "SSH public key for the azureuser account."
  type        = string
}

variable "admin_cidr" {
  description = "CIDR allowed to reach SSH (port 22). Restrict to your IP."
  type        = string
  default     = "*"
}

variable "bootstrap_endpoint" {
  description = "Bootstrap endpoint passed to the boot script."
  type        = string
  default     = ""
}

variable "genesis_uri" {
  description = "URI from which genesis.signed.json is downloaded on boot."
  type        = string
  default     = ""
}
