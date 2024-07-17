terraform {
  required_version = ">= 1.4.0"
}

module "openstack" {
  source         = "git::https://github.com/ComputeCanada/magic_castle.git//openstack"
  config_git_url = "https://github.com/ComputeCanada/puppet-magic_castle.git"
  config_version = "main"

  cluster_name = "mcspeed"
  domain       = "calculquebec.cloud"
  image        = "Rocky-8"

  instances = {
    mgmt  = { type = "p4-6gb", tags = ["puppet", "mgmt", "nfs"], count = 1 }
    login = { type = "p4-6gb", tags = ["login", "public", "proxy"], count = 1 }
    node  = { type = "p2-3gb", tags = ["node"], count = 1 }
  }

  volumes = {
    nfs = {
      home    = { size = 10 }
      project = { size = 5 }
      scratch = { size = 5 }
    }
  }

  public_keys      = ["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIL7dd00/9CXlTohQEgj5scMu1gOqrixPDVxF6Hrh67sD mcspeed"]
  generate_ssh_key = true

  hieradata = file("./hieradata.yaml")

  nb_users = 10
  # Shared password, randomly chosen if blank
  guest_passwd = ""
}

output "accounts" {
  value = module.openstack.accounts
}

output "public_ip" {
  value = module.openstack.public_ip
}
