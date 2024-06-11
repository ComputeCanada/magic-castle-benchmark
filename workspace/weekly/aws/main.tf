terraform {
  required_version = ">= 1.4.0"
}

module "aws" {

  source         = "git::https://github.com/ComputeCanada/magic_castle.git//aws"
  config_git_url = "https://github.com/etiennedub/puppet-magic_castle.git"
  config_version = "vector"

  cluster_name = "mcspeed"
  domain       = "calculquebec.cloud"
  image        = "ami-09ada793eea1559e6"

  instances = {
    mgmt  = { type = "t3.large",  count = 1, tags = ["mgmt", "puppet", "nfs"] },
    login = { type = "t3.medium", count = 1, tags = ["login", "public", "proxy"] },
    node  = { type = "t3.medium", count = 1, tags = ["node"] }
  }

  volumes = {
    nfs = {
      home     = { size = 10, type = "gp2" }
      project  = { size = 50, type = "gp2" }
      scratch  = { size = 50, type = "gp2" }
    }
  }

  public_keys = ["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIL7dd00/9CXlTohQEgj5scMu1gOqrixPDVxF6Hrh67sD mcspeed"]
  generate_ssh_key = true

  nb_users     = 10
  # Shared password, randomly chosen if blank
  guest_passwd = ""

  hieradata = file("./hieradata.yaml")

  # AWS specifics
  region            = "ca-central-1"
}

output "accounts" {
  value = module.aws.accounts
}

output "public_ip" {
  value = module.aws.public_ip
}

## Uncomment to register your domain name with CloudFlare
# module "dns" {
#   source           = "git::https://github.com/ComputeCanada/magic_castle.git//dns/cloudflare"
#   name             = module.aws.cluster_name
#   domain           = module.aws.domain
#   bastions         = module.aws.bastions
#   public_instances = module.aws.public_instances
#   ssh_private_key  = module.aws.ssh_private_key
#   sudoer_username  = module.aws.accounts.sudoer.username
# }

## Uncomment to register your domain name with Google Cloud
# module "dns" {
#   source           = "git::https://github.com/ComputeCanada/magic_castle.git//dns/gcloud"
#   project          = "your-project-id"
#   zone_name        = "you-zone-name"
#   name             = module.aws.cluster_name
#   domain           = module.aws.domain
#   bastions         = module.aws.bastions
#   public_instances = module.aws.public_instances
#   ssh_private_key  = module.aws.ssh_private_key
#   sudoer_username  = module.aws.accounts.sudoer.username
# }
