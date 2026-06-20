# Spark Connect Guide

Develop and debug PySpark interactively from your laptop -- VS Code, PyCharm,
or a Jupyter notebook -- against a Spark engine running on EMR Serverless,
using [Spark Connect](https://docs.aws.amazon.com/emr/latest/EMR-Serverless-UserGuide/spark-connect.html)
(EMR release `emr-7.13.0` and later).

## How it works

Spark Connect uses a client-server split. Your PySpark **client** runs locally;
DataFrame and SQL operations are sent over a **gRPC/TLS** endpoint to a Spark
driver running on EMR Serverless, which executes them and streams results back.

```
laptop (PySpark client, your IDE)  --gRPC/TLS over sc://...:443-->  EMR Serverless (driver + executors)
```

Because your client code runs locally, you debug it with **ordinary local
breakpoints** -- there is no VPC, bastion, NAT gateway, or SSH tunnel. The
connection is an outbound HTTPS/gRPC call authenticated with a short-lived
token.

!!! note "Spark Connect vs. a batch job"
    With Spark Connect your *driver code* runs on your laptop and only the
    Spark compute is remote -- ideal for interactive/exploratory work. A
    normal `deploy-to-emr --submit` batch job still runs the entire driver on
    EMR; use that for scheduled/production runs.

## Prerequisites

- An EMR Serverless application on **`emr-7.13.0` or later** with Spark
  Connect sessions enabled (see below).
- A local Python **3.10+** environment (the session APIs need `boto3>=1.43`,
  which requires 3.10+). Installed via the `dev` extra:
  ```bash
  uv pip install -e ".[dev]"
  ```
- The local `pyspark[connect]` version **must exactly match** the application's
  Spark version (`3.5.6` for `emr-7.13.0`) -- already pinned in the `dev` extra.
- IAM permissions on your caller identity (see [IAM](#iam-permissions)).

## 1. Enable Spark Connect on the application

Set the flag before creating/updating the app so it exposes interactive
endpoints:

```bash
# .env
RELEASE_LABEL=emr-7.13.0
SPARK_CONNECT_ENABLED=true

deploy-to-emr --build-image   # image must be emr-7.13.0-based
deploy-to-emr --create-app
```

`--create-app` sets `interactiveConfiguration.sessionEnabled = true`. If the
application already exists, it is updated in place -- but EMR Serverless only
allows updates while it is in the `CREATED` or `STOPPED` state, so stop it
first if needed:

```bash
aws emr-serverless stop-application --application-id <EMR_APP_ID>
```

## 2. Connect

### Option A -- drop into a shell (quickest)

```bash
spark-connect shell
```

This starts a session, waits for it, opens a Python REPL with a connected
`spark` object, and **terminates the session when you exit** (Ctrl-D):

```python
>>> spark.range(5).show()
>>> spark.sql("SELECT 1 + 1 AS result").show()
```

### Option B -- get a URL for your IDE / notebook

```bash
spark-connect start
```

This prints a session ID and an `export SPARK_REMOTE='sc://...:443/...'` line.
Export it, and any `SparkSession.builder.getOrCreate()` (or the `pyspark`
shell) connects automatically:

```python
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()  # uses SPARK_REMOTE
spark.range(10).show()
```

The session keeps running after `start` returns. **Stop it when done** so you
stop paying:

```bash
spark-connect list                 # see active sessions
spark-connect stop <SESSION_ID>
```

### Option C -- programmatic, auto-terminating

Use the context manager from `emr_dummy.emr.spark_connect` directly:

```python
from emr_dummy.emr.spark_connect import session_scope

with session_scope(app_id, execution_role, region="eu-west-2") as spark:
    spark.range(1000).filter("id % 2 = 0").count()
# session terminated automatically here
```

## Debugging

Set a breakpoint anywhere in your client code and run under your IDE's
debugger as normal -- it's a local process. When execution hits a
`df.show()`/`.count()`/`.collect()`, the work runs remotely and the result
comes back to your debugger. Use `GetResourceDashboard` (or the EMR Serverless
console) to open the live Spark UI for a session.

## IAM permissions

The identity that *starts sessions* (your laptop's role/user) needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["emr-serverless:StartSession", "emr-serverless:ListSessions"],
      "Resource": "arn:aws:emr-serverless:{region}:{account}:/applications/{app-id}"
    },
    {
      "Effect": "Allow",
      "Action": [
        "emr-serverless:GetSession",
        "emr-serverless:GetSessionEndpoint",
        "emr-serverless:TerminateSession",
        "emr-serverless:GetResourceDashboard"
      ],
      "Resource": "arn:aws:emr-serverless:{region}:{account}:/applications/{app-id}/sessions/*"
    },
    {
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::{account}:role/{EMRServerlessExecutionRole}",
      "Condition": {
        "StringLike": { "iam:PassedToService": "emr-serverless.amazonaws.com" }
      }
    }
  ]
}
```

The execution role passed to the session is your existing `EMR_EXECUTION_ROLE`
-- it grants access to your data (S3, Glue, Iceberg).

## Limitations and gotchas

- **EMR `7.13.0`+ only**, Spark engine only.
- **DataFrame and SQL APIs only** -- RDD APIs are not supported.
- **Auth tokens expire after 1 hour**; sessions also have a configurable idle
  timeout (1 hour default) and a 24-hour hard cap. `spark-connect shell`/the
  context manager handle teardown; for `start`, remember to `stop`.
- **Port `:443` is required** in the URL -- without it the client defaults to
  15002, which isn't reachable. The helper handles this for you.
- **Python UDFs** need your local Python *minor* version to match the workers.
  The EMR `7.x` image runs **Python 3.9** by default, while this client needs
  3.10+, so `@udf`/`spark.udf.register` will raise `PYTHON_VERSION_MISMATCH`
  unless you build a [custom image](https://docs.aws.amazon.com/emr/latest/EMR-Serverless-UserGuide/application-custom-image.html)
  with a matching Python. Built-in SQL and DataFrame operations are unaffected.
- **No extra charge** for Spark Connect -- you pay only for the EMR Serverless
  compute consumed while a session is active.
- Lake Formation fine-grained access control and Trusted Identity Propagation
  are not supported for Spark Connect sessions.
