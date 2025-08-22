"""Utilities for packaging, uploading, and submitting EMR Serverless Spark jobs."""

import datetime
import json
import logging
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def build_and_push_docker_image(
    image_uri: str,
    region: str,
    arch: str = "linux/amd64",
    root_path: str = ".",
) -> None:
    """Build and push a Docker image to AWS ECR.

    Parameters
    ----------
    image_uri
        The URI of the ECR image repository
        (e.g., "123456789012.dkr.ecr.eu-west-2.amazonaws.com/my-image:latest").
    region
        The AWS region where the ECR repository is located (e.g., "eu-west-2").
    arch
        The target architecture for the Docker image build.
        Default is "linux/amd64".
    root_path
        The root path for the Docker build context/
        Default is ".".

    Returns
    -------
    None

    Examples
    --------
    >>> build_and_push_docker_image(
    ...     image_uri="123456789012.dkr.ecr.us-west-2.amazonaws.com/my-image:latest",
    ...     region="eu-west-2"
    ... )
    >>> build_and_push_docker_image(
    ...     image_uri="123456789012.dkr.ecr.us-west-2.amazonaws.com/my-image:latest",
    ...     region="eu-west-2",
    ...     arch="linux/arm64",
    ...     root_path="./docker"
    ... )
    """
    logger.info("Logging in to ECR...")
    account_id = image_uri.split(".")[0]
    login_password = subprocess.check_output(
        ["aws", "ecr", "get-login-password", "--region", region],
        text=True,
    ).strip()
    subprocess.run(
        [
            "docker",
            "login",
            "--username",
            "AWS",
            "--password-stdin",
            f"{account_id}.dkr.ecr.{region}.amazonaws.com",
        ],
        input=login_password,
        text=True,
        check=True,
    )
    logger.info("Login successful.")

    logger.info("Building and pushing Docker image: %s", image_uri)
    subprocess.run(
        [
            "docker",
            "buildx",
            "build",
            "--platform",
            arch,
            "-t",
            image_uri,
            "--push",
            root_path,
        ],
        check=True,
    )
    logger.info(f"Build and push complete: {image_uri} (platform {arch})")


def create_or_update_emr_app(
    app_name: str,
    image_uri: str,
    release_label: str,
    region: str,
) -> str:
    """Create or update an EMR Serverless application.

    Parameters
    ----------
    app_name
        The name of the EMR Serverless application.
    image_uri
        The URI of the ECR image to use for the application.
    release_label
        The EMR release label (e.g., "emr-7.9.0").
    region
        The AWS region in which to create or update the application.

    Returns
    -------
    str
        The application ID of the created or existing EMR Serverless application.

    Examples
    --------
    >>> app_id = create_or_update_emr_app(
    ...     app_name="my-emr-app",
    ...     image_uri="123456789012.dkr.ecr.eu-west-2.amazonaws.com/my-image:latest",
    ...     release_label="emr-7.9.0",
    ...     region="eu-west-2"
    ... )
    >>> print(app_id)
    '00f1abcd1234efgh'
    """
    emr_client = boto3.client("emr-serverless", region_name=region)
    try:
        response = emr_client.list_applications(
            states=["CREATING", "CREATED", "STARTING", "STARTED"],
        )
        app = next((a for a in response["applications"] if a["name"] == app_name), None)
        if app:
            logger.info(f"Found existing application: {app['id']}")
            return app["id"]
    except Exception as e:
        logger.warning(f"Could not list applications: {e}")

    logger.info(f"Creating application {app_name} with image {image_uri}")
    response = emr_client.create_application(
        name=app_name,
        type="SPARK",
        releaseLabel=release_label,
        imageConfiguration={"imageUri": image_uri},
    )
    return response["applicationId"]


def _wait_for_application_state(
    client: boto3.client,
    app_id: str,
    target_state: str,
    timeout_seconds: int = 300,
):
    """Poll an EMR Serverless application until it reaches a target state.

    This function repeatedly calls the EMR Serverless `get_application` API
    until the specified application reaches the desired state or a timeout
    occurs. It is useful when deploying or terminating EMR Serverless
    applications where state transitions may take time.

    Parameters
    ----------
    client
        A boto3 EMR Serverless client instance with a `get_application` method.
    app_id
        The unique identifier of the EMR Serverless application to monitor.
    target_state
        The desired state to wait for (e.g., "RUNNING", "TERMINATED").
    timeout_seconds
        The maximum number of seconds to wait for the application to reach
        the target state.
        Default is 300.

    Raises
    ------
    TimeoutError
        If the application does not reach the target state within the
        specified timeout.
    ClientError
        If an unexpected AWS client error occurs during polling.

    Examples
    --------
    >>> from my_module import _wait_for_application_state
    >>> import boto3
    >>> client = boto3.client("emr-serverless")
    >>> app_id = "00f1abcd1234wxyz"
    >>> _wait_for_application_state(client, app_id, target_state, timeout_seconds=120)
    """
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        try:
            response = client.get_application(applicationId=app_id)
            current_state = response["application"]["state"]
            if current_state == target_state:
                return
            logger.info(
                f"Application {app_id} is in state {current_state}, "
                f"waiting for {target_state}...",
            )
            time.sleep(10)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                if target_state == "TERMINATED":
                    return  # This is the expected state after deletion
                else:
                    raise
            else:
                raise
    error_msg = (
        f"Timed out waiting for application {app_id} to reach state {target_state}."
    )
    logger.error(error_msg)
    raise TimeoutError(error_msg)


def delete_emr_app(app_id: str, region: str) -> None:
    """Stop and delete an EMR Serverless application.

    This function first attempts to stop the specified EMR Serverless
    application, waiting until its state becomes `STOPPED`. It then
    deletes the application and waits for it to reach the `TERMINATED`
    state. If the application is already stopped or deleted, warnings are
    logged instead of raising an error.

    Parameters
    ----------
    app_id
        The unique identifier of the EMR Serverless application to delete.
    region
        The AWS region where the EMR Serverless application is deployed.

    Raises
    ------
    ClientError
        If an unexpected AWS client error occurs while stopping or
        deleting the application.
    TimeoutError
        If the application does not reach the expected target state
        (`STOPPED` or `TERMINATED`) within the configured timeout.

    Examples
    --------
    >>> delete_emr_app(app_id="00f1abcd1234wxyz", region="eu-west-2")
    Application 00f1abcd1234wxyz stopped.
    Successfully deleted application 00f1abcd1234wxyz.
    """
    client = boto3.client("emr-serverless", region_name=region)
    try:
        logger.info(f"Stopping application {app_id}...")
        client.stop_application(applicationId=app_id)
        _wait_for_application_state(client, app_id, "STOPPED")
        logger.info(f"Application {app_id} stopped.")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.warning(f"Application {app_id} not found, may already be deleted.")
        elif (
            e.response["Error"]["Code"] == "ValidationException"
            and "is already stopped" in e.response["Error"]["Message"]
        ):
            logger.warning(f"Application {app_id} already stopped.")
        else:
            raise

    try:
        logger.info(f"Deleting application {app_id}...")
        client.delete_application(applicationId=app_id)
        _wait_for_application_state(client, app_id, "TERMINATED")
        logger.info(f"Successfully deleted application {app_id}.")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.warning(f"Application {app_id} was already deleted.")
        else:
            raise


def build_package(
    package_name: str,
    build_dir: Path,
) -> Path:
    """Build and zip the application source code for EMR Serverless.

    This function copies the contents of the ``src/`` directory into a
    staging directory, applying ignore patterns to exclude build artifacts
    (e.g., ``*.egg-info`` and ``__pycache__``). The staging directory is then
    zipped into a versioned archive suitable for upload to EMR Serverless.
    Dependencies are not packaged and are expected to be provided by the
    runtime environment (e.g., via the container image).

    Parameters
    ----------
    package_name
        Logical name for the staged source directory inside ``build_dir``.
    build_dir
        Path to the build directory. If it already exists, it will be
        deleted and recreated before staging.

    Returns
    -------
    Path
        Absolute path to the zipped application package.

    Raises
    ------
    FileNotFoundError
        If the ``src/`` directory does not exist at the project root.

    Notes
    -----
    - This function is designed for packaging PySpark or Python code that
      will run on EMR Serverless. It assumes dependencies are managed
      externally.
    - The generated archive is named with a timestamp to avoid collisions.

    Examples
    --------
    >>> from pathlib import Path
    >>> build_dir = Path("build")
    >>> package_zip = build_package("my_app", build_dir)
    >>> package_zip.exists()
    True
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    stage_dir = build_dir / package_name
    zip_path = build_dir / f"code_{timestamp}.zip"

    # Clean and recreate build directory
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    src_root = Path("src")
    if not src_root.exists():
        error_msg = "src/ directory not found. It should be at the project root."
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)

    # Ignore patterns (applies to root entries too)
    ignore_patterns = shutil.ignore_patterns(
        "*.egg-info",
        "*.dist-info",
        "__pycache__",
        "*.pyc",
    )

    # Copy the entire src tree into the staging directory
    shutil.copytree(src_root, stage_dir, ignore=ignore_patterns, dirs_exist_ok=True)

    # Zip the cleaned staging directory
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in stage_dir.rglob("*"):
            zf.write(path, arcname=path.relative_to(stage_dir))

    logger.info(f"Built application source package at {zip_path}")
    return zip_path


def submit_emr_job(
    code_s3_uri: str,
    entry_s3_uri: str,
    spark_submit_parameters: Optional[str],
    emr_app_id: str,
    execution_role: str,
    region: str,
    log_uri: str,
    *,
    enable_cloudwatch_logging: bool = True,
    application_arguments: Optional[List[str]] = None,
    dry_run_payload: Optional[Dict] = None,
) -> str:
    """Submit a job to an EMR Serverless application.

    This function constructs a Spark submit payload and launches a job on an
    EMR Serverless application. It optionally supports a dry run mode, which
    logs the payload instead of submitting it.

    Parameters
    ----------
    code_s3_uri
        S3 URI of the Python ZIP archive to add to `PYTHONPATH` via
        `--py-files`.
    entry_s3_uri
        S3 URI of the main entry script for the Spark job.
    spark_submit_parameters
        Additional parameters passed to Spark via `sparkSubmitParameters`
        (e.g., `"--py-files ..." --conf ...`). If None, defaults to
        `"--py-files {code_s3_uri}"`.
    emr_app_id
        The EMR Serverless application ID.
    execution_role
        IAM role ARN used as the execution role for the EMR Serverless job.
    region
        The AWS region in which the EMR Serverless application is running.
    log_uri
        S3 URI where EMR Serverless job logs should be written.
    enable_cloudwatch_logging
        Whether to enable CloudWatch logging in the job configuration.
        Default is True.
    application_arguments
        Arguments passed to the job entry point, available as
        `sys.argv` within the script.
    dry_run_payload
        If provided, the function will not call the EMR Serverless API.
        Instead, it logs the payload and returns a dummy job ID
        (`"dry-run-job-id"`).

    Returns
    -------
    str
        The EMR Serverless job run ID. Returns `"dry-run-job-id"` if
        `dry_run_payload` is set.

    Raises
    ------
    ClientError
        If the EMR Serverless API request fails (when not in dry run mode).

    Examples
    --------
    >>> from my_module import submit_emr_job
    >>> job_id = submit_emr_job(
    ...     code_s3_uri="s3://my-bucket/code/app.zip",
    ...     entry_s3_uri="s3://my-bucket/code/main.py",
    ...     spark_submit_parameters=None,
    ...     emr_app_id="00f1abcd1234wxyz",
    ...     execution_role="arn:aws:iam::123456789012:role/EMRServerlessExecutionRole",
    ...     region="eu-west-2",
    ...     log_uri="s3://my-bucket/logs/",
    ...     application_arguments=["--config", "s3://my-bucket/config.toml"],
    ... )
    >>> print(job_id)
    'jr-1234567890abcdef'
    """
    client = boto3.client("emr-serverless", region_name=region)

    payload = {
        "applicationId": emr_app_id,
        "executionRoleArn": execution_role,
        "jobDriver": {
            "sparkSubmit": {
                "entryPoint": entry_s3_uri,
                "entryPointArguments": application_arguments or [],
                "sparkSubmitParameters": (
                    spark_submit_parameters or f"--py-files {code_s3_uri}"
                ),
            },
        },
        "configurationOverrides": {
            "monitoringConfiguration": {
                "s3MonitoringConfiguration": {"logUri": log_uri},
                "cloudWatchLoggingConfiguration": {
                    "enabled": enable_cloudwatch_logging,
                },
            },
        },
    }

    if dry_run_payload is not None:
        logger.info("Dry-run payload:\n%s", json.dumps(payload, indent=2))
        return "dry-run-job-id"

    resp = client.start_job_run(**payload)
    job_id = resp["jobRunId"]
    logger.info("Started EMR Serverless job: %s", job_id)
    return job_id
