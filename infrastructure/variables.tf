variable "target_provider" {
  description = "Target provider to deploy (aws, azure, gcp, alibaba, generic_ssh)."
  type        = string
}

variable "node_name" {
  description = "Name for the sovereign node instance."
  type        = string
  default     = "sovereign-edge-node"
}

variable "bootstrap_endpoint" {
  description = "Bootstrap endpoint for the node."
  type        = string
}

variable "genesis_uri" {
  description = "URI where genesis.signed.json can be retrieved."
  type        = string
}

variable "aws_ami" {
  type        = string
  default     = ""
}

variable "aws_instance_type" {
  type        = string
  default     = "t3.large"
}

variable "aws_subnet_id" {
  type        = string
  default     = ""
}

variable "aws_security_group_ids" {
  type        = list(string)
  default     = []
}

variable "azure_resource_group_name" {
  type        = string
  default     = ""
}

variable "azure_location" {
  type        = string
  default     = ""
}

variable "azure_vm_size" {
  type        = string
  default     = "Standard_D4s_v5"
}

variable "azure_subnet_id" {
  type        = string
  default     = ""
}

variable "azure_ssh_public_key" {
  type        = string
  default     = ""
  description = "SSH public key for Azure VM admin user authentication"
}

variable "gcp_project" {
  type        = string
  default     = ""
}

variable "gcp_zone" {
  type        = string
  default     = ""
}

variable "gcp_machine_type" {
  type        = string
  default     = "e2-standard-4"
}

variable "gcp_network" {
  type        = string
  default     = "default"
}

variable "alibaba_instance_type" {
  type        = string
  default     = "ecs.c7.large"
}

variable "alibaba_image_id" {
  type        = string
  default     = ""
}

variable "alibaba_vswitch_id" {
  type        = string
  default     = ""
}

variable "generic_ssh_host" {
  type        = string
  default     = ""
}

variable "generic_ssh_user" {
  type        = string
  default     = "root"
}

variable "generic_ssh_private_key" {
  type        = string
  default     = ""
}
