# Magic Castle Benchmark

Deploying [Magic Castle](https://github.com/ComputeCanada/magic_castle) periodically on the Digital Research Alliance of Canada (DRAC) infrastructure.

The goal is to monitor infrastructure performance over time to detect performance anomalies. The results must be saved and made accessible, but visualization is not required for the initial version.

# Self-Hosted Runner

We use self-hosted runner to deploy this project to reduces the usage of GitGub CI credit.

To add a new runner, we need to install some dependancies for this project:
```
sudo yum update -y && sudo yum install docker git libicu -y && sudo systemctl enable docker
sudo usermod -aG docker $USER
```

Then follow the instruction on the [Github new runner page](https://github.com/ComputeCanada/magic-castle-benchmark/settings/actions/runners/new).
To start the runner at boot run: `sudo ./svc.sh install`.
A reboot is required to apply the docker permission.
