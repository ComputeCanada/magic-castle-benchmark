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
    mgmt  = { type = "p4-7.5gb", tags = ["puppet", "mgmt", "nfs"], count = 1 }
    login = { type = "p4-7.5gb", tags = ["login", "public", "proxy"], count = 1 }
    node  = { type = "p2-3.75gb", tags = ["node"], count = 1 }
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
  subnet_id = "f7412a24-e802-4a72-8e1f-f74bac4a0b5a"

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
