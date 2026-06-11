# Remote Debugging Guide

Set breakpoints in your IDE and step through a PySpark driver running on EMR
Serverless, using the reverse-SSH-tunnel pattern from AWS's
[remote-debugging-with-emr](https://github.com/aws-samples/remote-debugging-with-emr)
sample -- implemented here in Terraform instead of CDK.

## How it works

EMR Serverless workers normally run in an AWS-managed network with no route to
you. To debug them live, the application is attached to a VPC you own, and the
Spark driver opens an **outbound** TCP connection to a small bastion instance.
The bastion forwards that connection back to your laptop through a reverse SSH
tunnel, where your IDE's debug server is listening.

```
laptop                          bastion (public subnet)        EMR Serverless driver
IDE listens on :3535  <==SSM==  sshd, reverse tunnel :3535  <--TCP--  (private subnet)
```

Nothing is exposed to the internet: the bastion accepts no inbound SSH (access
is via SSM Session Manager only), and port 3535 only accepts connections from
the EMR workers' security group.

## Costs

The debug stack runs a NAT gateway (~$0.05/hour + data) and a `t3.micro`
bastion. It is created only when `enable_remote_debugging = true` -- turn it
off (the default) when you are not debugging.

## 1. Provision the infrastructure

```bash
cd terraform
terraform apply \
  -var enable_remote_debugging=true \
  -var "bastion_ssh_public_key=$(cat ~/.ssh/id_ed25519.pub)"
terraform output
```

Copy the debug outputs into your `.env`:

```bash
DEBUG_SUBNET_IDS=<terraform output DEBUG_SUBNET_IDS>
DEBUG_EMR_SECURITY_GROUP_ID=<terraform output DEBUG_EMR_SECURITY_GROUP_ID>
DEBUG_HOST=<terraform output DEBUG_HOST>
DEBUG_PORT=3535
DEBUGGER=pydevd   # or debugpy for VS Code
```

## 2. Attach the EMR application to the debug VPC

The application needs a network configuration so its workers get ENIs in the
private subnets (and can therefore reach the bastion). With `DEBUG_SUBNET_IDS`
and `DEBUG_EMR_SECURITY_GROUP_ID` set in `.env`:

```bash
deploy-to-emr --create-app
```

If the application already exists, it is updated in place -- but EMR
Serverless only allows updates while the application is in the `CREATED` or
`STOPPED` state. Stop it first if needed:

```bash
aws emr-serverless stop-application --application-id <EMR_APP_ID>
```

!!! note
    While the application has a network configuration, **all** its jobs run
    through this VPC (S3 traffic uses the free gateway endpoint; everything
    else goes via NAT). To revert, stop the application and update it, or use
    a separate application for debugging.

## 3. Build the image with the debug agents

The `Dockerfile` installs the `debug` extra (`pydevd-pycharm` and `debugpy`).
They do nothing unless `DEBUG_HOST` is set, so it is safe to keep them in the
image. Rebuild and push:

```bash
deploy-to-emr --build-image
```

For PyCharm, pin `pydevd-pycharm` in `pyproject.toml` to the version matching
your PyCharm build (PyCharm tells you the exact version in the Debug Server
run configuration, e.g. `pydevd-pycharm~=233.13763.11`).

## 4. Open the reverse tunnel

SSH access to the bastion goes over SSM, so install the
[Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
and add this to `~/.ssh/config` (instance ID from
`terraform output DEBUG_BASTION_INSTANCE_ID`):

```
Host emr-debug-bastion
    HostName i-0123456789abcdef0
    User ec2-user
    ProxyCommand sh -c "aws ssm start-session --target %h --document-name AWS-StartSSHSession --parameters 'portNumber=%p'"
```

Then start the tunnel and leave it running:

```bash
ssh -N -R 3535:localhost:3535 emr-debug-bastion
```

The bastion's sshd is configured with `GatewayPorts yes`, so the remote end of
the tunnel binds on the bastion's private IP -- exactly where the driver will
connect.

## 5. Start your IDE's debug listener

### PyCharm Professional (pydevd)

1. Run/Debug Configurations -> add **Python Debug Server**.
2. Host: `localhost`, port: `3535`.
3. Path mappings: local `src/emr_dummy` -> `/home/hadoop/src/emr_dummy`
   (where the image's editable install puts the package).
4. Start the configuration -- it waits for the driver to connect.

Set `DEBUGGER=pydevd` in `.env`.

### VS Code (debugpy)

Add a listening attach configuration to `.vscode/launch.json`:

```json
{
    "name": "EMR Serverless: wait for driver",
    "type": "debugpy",
    "request": "attach",
    "listen": { "host": "localhost", "port": 3535 },
    "pathMappings": [
        { "localRoot": "${workspaceFolder}/src", "remoteRoot": "/home/hadoop/src" }
    ]
}
```

Start it (it waits for the connection) and set `DEBUGGER=debugpy` in `.env`.

## 6. Submit the job with debugging enabled

```bash
deploy-to-emr --package --submit --debug
```

The `--debug` flag injects `DEBUG_HOST`, `DEBUG_PORT`, and `DEBUGGER` into the
driver environment (via `spark.emr-serverless.driverEnv.*`) and relaxes
`spark.network.timeout` so executors survive long pauses at breakpoints. The
entry point (`main.py`) calls `attach_remote_debugger()` before the job
starts; once the driver boots (typically 1-2 minutes), it connects to your
IDE and your breakpoints become live.

## Limitations and troubleshooting

- **Driver only.** Breakpoints fire in driver-side code (everything outside
  UDFs/`mapPartitions`). Executor processes are not attached.
- **Driver never connects.** Check, in order: the tunnel is up (`ssh -N -R
  ...` still running), the IDE listener is running on port 3535, and the job
  actually started (`aws emr-serverless get-job-run`). The attach hook raises
  a `RuntimeError` with the reason in the driver stderr logs
  (`s3://<bucket>/.../SPARK_DRIVER/stderr.gz`).
- **Breakpoints not hit but connection works.** Path mappings are wrong, or
  the driver is importing your package from the `--py-files` zip rather than
  the image install. Either map to the zip's extraction path shown in
  `sys.path`, or submit without `--py-files` while debugging so the
  image-installed copy (at `/home/hadoop/src`) is used.
- **`update_application` validation error.** The app must be `STOPPED` or
  `CREATED` to change its network configuration -- stop it and re-run
  `deploy-to-emr --create-app`.
- **Job hangs at startup with no logs.** The workers may not reach S3/EMR
  endpoints -- check the private subnets' route to the NAT gateway and the S3
  gateway endpoint association.

## Teardown

```bash
cd terraform
terraform apply -var enable_remote_debugging=false
```

Remember to also remove the network configuration from the EMR application
(stop it, then update without a VPC, or simply delete and recreate the app
with `deploy-to-emr --cleanup` followed by `--create-app` with the debug
variables unset).
