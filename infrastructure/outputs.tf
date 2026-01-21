# AWS Outputs
output "aws_instance_id" {
  description = "AWS instance ID"
  value       = local.is_aws ? aws_instance.sovereign[0].id : null
}

output "aws_public_ip" {
  description = "AWS instance public IP address"
  value       = local.is_aws ? aws_instance.sovereign[0].public_ip : null
}

output "aws_private_ip" {
  description = "AWS instance private IP address"
  value       = local.is_aws ? aws_instance.sovereign[0].private_ip : null
}

# Azure Outputs
output "azure_vm_id" {
  description = "Azure VM resource ID"
  value       = local.is_azure ? azurerm_linux_virtual_machine.sovereign[0].id : null
}

output "azure_public_ip" {
  description = "Azure VM public IP address (if configured)"
  value       = local.is_azure ? azurerm_linux_virtual_machine.sovereign[0].public_ip_address : null
}

output "azure_private_ip" {
  description = "Azure VM private IP address"
  value       = local.is_azure ? azurerm_linux_virtual_machine.sovereign[0].private_ip_address : null
}

# GCP Outputs
output "gcp_instance_id" {
  description = "GCP instance ID"
  value       = local.is_gcp ? google_compute_instance.sovereign[0].instance_id : null
}

output "gcp_public_ip" {
  description = "GCP instance public IP address"
  value       = local.is_gcp ? google_compute_instance.sovereign[0].network_interface[0].access_config[0].nat_ip : null
}

output "gcp_private_ip" {
  description = "GCP instance private IP address"
  value       = local.is_gcp ? google_compute_instance.sovereign[0].network_interface[0].network_ip : null
}

output "gcp_self_link" {
  description = "GCP instance self link"
  value       = local.is_gcp ? google_compute_instance.sovereign[0].self_link : null
}

# Alibaba Outputs
output "alibaba_instance_id" {
  description = "Alibaba Cloud instance ID"
  value       = local.is_alibaba ? alicloud_instance.sovereign[0].id : null
}

output "alibaba_public_ip" {
  description = "Alibaba Cloud instance public IP address"
  value       = local.is_alibaba ? alicloud_instance.sovereign[0].public_ip : null
}

output "alibaba_private_ip" {
  description = "Alibaba Cloud instance private IP address"
  value       = local.is_alibaba ? alicloud_instance.sovereign[0].private_ip : null
}

# Generic SSH Outputs
output "generic_ssh_host" {
  description = "Generic SSH host address"
  value       = local.is_generic_ssh ? var.generic_ssh_host : null
}

# Common Outputs
output "node_name" {
  description = "Name of the deployed sovereign node"
  value       = var.node_name
}

output "target_provider" {
  description = "Target cloud provider used for deployment"
  value       = var.target_provider
}

output "bootstrap_endpoint" {
  description = "Bootstrap endpoint configured for the node"
  value       = var.bootstrap_endpoint
}
