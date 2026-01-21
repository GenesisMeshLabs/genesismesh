# Sovereign Node Terraform (Polymorphic)

This folder contains a **single** Terraform module that deploys a Sovereign
Edge Cloud Node to AWS, Azure, GCP, Alibaba, or a generic SSH target based on
one switch variable: `target_provider`.

## Files

- `main.tf`: Polymorphic Terraform implementation (one logic path, many forms).
- `variables.tf`: Input variables including `target_provider`.
- `outputs.tf`: Output values for instance IPs, IDs, and connection information.
- `universal_boot.sh`: OS-agnostic bootstrap script for user_data/remote-exec.

## Usage (conceptual)

```hcl
module "sovereign_node" {
  source          = "./infrastructure"
  target_provider = "aws"

  bootstrap_endpoint = "https://na.example.com"
  genesis_uri         = "https://na.example.com/genesis.signed.json"

  aws_ami                = "ami-xxxxxxxx"
  aws_subnet_id          = "subnet-xxxxxxxx"
  aws_security_group_ids = ["sg-xxxxxxxx"]
}
```

For `azure`, set:

```hcl
module "sovereign_node" {
  source          = "./infrastructure"
  target_provider = "azure"

  bootstrap_endpoint = "https://na.example.com"
  genesis_uri        = "https://na.example.com/genesis.signed.json"

  azure_resource_group_name = "my-resource-group"
  azure_location            = "eastus"
  azure_subnet_id           = "/subscriptions/.../networkInterfaces/..."
  azure_ssh_public_key      = file("~/.ssh/id_rsa.pub")
}
```

For `gcp`, set:

```hcl
module "sovereign_node" {
  source          = "./infrastructure"
  target_provider = "gcp"

  bootstrap_endpoint = "https://na.example.com"
  genesis_uri        = "https://na.example.com/genesis.signed.json"

  gcp_project      = "my-project-id"
  gcp_zone         = "us-central1-a"
  gcp_machine_type = "e2-standard-4"
}
```

For `alibaba`, set:

```hcl
module "sovereign_node" {
  source          = "./infrastructure"
  target_provider = "alibaba"

  bootstrap_endpoint = "https://na.example.com"
  genesis_uri        = "https://na.example.com/genesis.signed.json"

  alibaba_instance_type = "ecs.c7.large"
  alibaba_image_id      = "ubuntu_22_04_x64_20G_alibase_xxxx"
  alibaba_vswitch_id    = "vsw-xxxxxxxx"
}
```

For `generic_ssh`, set:

```hcl
module "sovereign_node" {
  source          = "./infrastructure"
  target_provider = "generic_ssh"

  bootstrap_endpoint   = "https://na.example.com"
  genesis_uri          = "https://na.example.com/genesis.signed.json"
  generic_ssh_host        = "10.0.0.50"
  generic_ssh_user        = "ubuntu"
  generic_ssh_private_key = file("~/.ssh/id_rsa")
}
```

## Outputs

After deployment, the module provides the following outputs:

- **Instance IDs**: `aws_instance_id`, `azure_vm_id`, `gcp_instance_id`, `alibaba_instance_id`
- **Public IPs**: `aws_public_ip`, `azure_public_ip`, `gcp_public_ip`, `alibaba_public_ip`
- **Private IPs**: `aws_private_ip`, `azure_private_ip`, `gcp_private_ip`, `alibaba_private_ip`
- **Common**: `node_name`, `target_provider`, `bootstrap_endpoint`

Access outputs after deployment:

```bash
terraform output aws_public_ip
terraform output -json  # All outputs as JSON
```

## Required Variables by Provider

### AWS
- `aws_ami` - AMI ID (e.g., "ami-0c55b159cbfafe1f0")
- `aws_subnet_id` - VPC subnet ID
- `aws_security_group_ids` - List of security group IDs (optional, defaults to [])

### Azure
- `azure_resource_group_name` - Resource group name
- `azure_location` - Azure region (e.g., "eastus")
- `azure_subnet_id` - Network interface ID
- `azure_ssh_public_key` - SSH public key content (required)

### GCP
- `gcp_project` - GCP project ID
- `gcp_zone` - GCP zone (e.g., "us-central1-a")

### Alibaba Cloud
- `alibaba_instance_type` - Instance type (e.g., "ecs.c7.large")
- `alibaba_image_id` - Image ID
- `alibaba_vswitch_id` - VSwitch ID

### Generic SSH
- `generic_ssh_host` - Target host IP/hostname
- `generic_ssh_private_key` - SSH private key content (as string)
