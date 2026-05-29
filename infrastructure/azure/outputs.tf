output "public_ip" {
  description = "Public IP address of the Network Authority VM."
  value       = azurerm_public_ip.na.ip_address
}

output "ssh_command" {
  description = "SSH command to connect to the VM."
  value       = "ssh azureuser@${azurerm_public_ip.na.ip_address}"
}

output "na_endpoint" {
  description = "Network Authority HTTP endpoint."
  value       = "http://${azurerm_public_ip.na.ip_address}:8443"
}
