terraform {
  required_version = ">= 1.4.0"
}

module "openstack" {
  source         = "git::https://github.com/ComputeCanada/magic_castle.git//openstack"
  config_git_url = "https://github.com/ComputeCanada/puppet-magic_castle.git"
  config_version = "main"

  cluster_name = "mcspeed"
  domain       = "calculquebec.cloud"
  image        = "Rocky-9"

  instances = {
    mgmt  = { type = "4c-8G", tags = ["puppet", "mgmt", "nfs"], count = 1 }
    login = { type = "4c-8G", tags = ["login", "public", "proxy"], count = 1 }
    node  = { type = "2c-4G", tags = ["node"], count = 1 }
  }

  volumes = {
    nfs = {
      home    = { size = 10 }
      project = { size = 5 }
      scratch = { size = 5 }
    }
  }

  public_keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIL7dd00/9CXlTohQEgj5scMu1gOqrixPDVxF6Hrh67sD mcspeed",
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBblyJ+6JynjS7kxzawodNvRrOTGVGj7266zcFJuq01N 1password_ed25519"
  ]

  hieradata = file("./hieradata.yaml")
  subnet_id = "a7f9fef1-a43e-4502-83a9-e47c936b635d"

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
