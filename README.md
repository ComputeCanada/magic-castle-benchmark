# Magic Castle Benchmark

Deploying [Magic Castle](https://github.com/ComputeCanada/magic_castle) periodically on the Digital Research Alliance of Canada (DRAC) infrastructure.

The goal is to monitor infrastructure performance over time to detect performance anomalies. The results must be saved and made accessible, but visualization is not required for the initial version.

## How does it work?

The project is organized around scheduled GitHub actions. The first action creates a cluster for a cloud by uploading a configuration to Terraform Cloud its corresponding workspace. The resulting Terraform logs are then retrieved and pushed as document in OpenSearch under the index `mcspeed`. The `mcspeed` index is a datastream that uses policies to auto rotates the indices. The configuration to push documents in OpenSearch is provided to the cluster. Once initial configuration is over for cloud-init and puppet, vector pushes their logs in OpenSearch.

After an hour, the cluster is destroyed regardless of wether it successfully completed its configuration or not.

A second index has been configured in OpenSearch for the project: `mcspeed_staging`. This index is used for development and test purpose. It differs from the `mcspeed` index as it is a normal index instead of data stream index.

## How to add a cloud?

1. Create a new folder under `workspace/daily`
2. In that folder, add a `main.tf` file for the new cloud.
3. Make sure to set `hieradata = file("hieradata.yaml")`, in the `main.tf`. This will configure vector.
4. In mcspeed Terraform Cloud organization, create a new workspace with the same name as the folder in 2.
5. Configure a variable with the cloud credentials in the workspace.

## How to debug?

1. Add your public SSH key to the main.tf of the cloud(s) you want to debug.
2. To launch a cluster that will push log in `mcspeed`, do:
    ```
    git tag -f daily_apply
    git push -f --tags
    ```
3. To launch a cluster that will push log in `mcspeed_staging`, do:
    ``` 
    git tag -f apply
    git push -f  --tags
    ```
4. Retrieve the public IP address from the latest [Terraform Cloud run](https://app.terraform.io/app/mcspeed/workspaces/).

Once you are done, to delete the cluster pushing to `mcspeed`:
```
git tag -f daily_destroy
git push -f  --tags
```
and to delete a cluster pushing documents to `mcscpeed_staging`:
```
git tag -f destroy
git push -f  --tags
```

## Self-Hosted Runner

We use self-hosted runner to deploy this project to reduces the usage of GitGub CI credit.

To add a new runner, we need to install some dependancies for this project:
```
sudo yum update -y && sudo yum install docker git libicu -y && sudo systemctl enable docker
sudo usermod -aG docker $USER
```

Then follow the instruction on the [Github new runner page](https://github.com/ComputeCanada/magic-castle-benchmark/settings/actions/runners/new).
To start the runner at boot run: `sudo ./svc.sh install`.
A reboot is required to apply the docker permission.
