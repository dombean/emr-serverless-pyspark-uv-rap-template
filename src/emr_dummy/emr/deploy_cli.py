"""CLI for building and deploying a PySpark package to EMR Serverless."""

import datetime
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

import boto3
import click
from dotenv import load_dotenv
from rdsa_utils.helpers.python import (
    parse_pyproject_metadata,
    sha256_sum,
    validate_env_vars,
)

from emr_dummy.emr.emr_serverless_utils import (
    build_and_push_docker_image,
    build_package,
    create_or_update_emr_app,
    delete_emr_app,
    submit_emr_job,
)
from emr_dummy.s3_utils import upload_file_to_s3_key, upload_json

logger = logging.getLogger(__name__)

load_dotenv()  # Load .env if present


@click.command()
@click.option("--entry-point", default="main.py", show_default=True)
@click.option("--package-name", default="my_pipeline", show_default=True)
@click.option(
    "--pyproject",
    type=click.Path(exists=True),
    default="pyproject.toml",
    show_default=True,
    help="Path to pyproject.toml (uv build).",
)
@click.option(
    "--enable-cw/--no-enable-cw",
    default=(
        os.getenv("ENABLE_CLOUDWATCH_LOGGING", "true").lower()
        in ("1", "true", "yes", "on")
    ),
    show_default=True,
    help="Enable CloudWatch logging (overrides ENABLE_CLOUDWATCH_LOGGING env).",
)
@click.option(
    "--config-s3",
    default=os.getenv("CONFIG_S3_URI", None),
    help="S3 URI to config.toml for the job (overrides CONFIG_S3_URI).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print StartJobRun payload and exit without submitting.",
)
@click.option(
    "--deployment-note",
    type=str,
    default=None,
    help="Optional note recorded in manifest.json",
)
@click.option("--build-image", is_flag=True, help="Build and push the Docker image.")
@click.option(
    "--create-app",
    is_flag=True,
    help="Create or update the EMR Serverless app.",
)
@click.option(
    "--package",
    is_flag=True,
    help="Package the application and upload to S3.",
)
@click.option("--submit", is_flag=True, help="Submit the job to EMR Serverless.")
@click.option("--cleanup", is_flag=True, help="Stop and delete the EMR Serverless app.")
@click.option(
    "--debug",
    is_flag=True,
    help=(
        "Attach the Spark driver to a remote debugger via the bastion tunnel "
        "(requires DEBUG_HOST; see the remote debugging guide)."
    ),
)
def deploy(
    entry_point: str,
    package_name: str,
    pyproject: str,
    dry_run: bool,
    deployment_note: Optional[str],
    enable_cw: bool,
    config_s3: Optional[str],
    build_image: bool,
    create_app: bool,
    package: bool,
    submit: bool,
    cleanup: bool,
    debug: bool,
) -> None:
    r"""Build, package, and deploy an EMR Serverless Spark job via CLI.

    Orchestrates common deployment steps:
    Building/pushing a Docker image, creating/updating an EMR Serverless
    application, packaging Python code and uploading to S3, submitting a job,
    and optionally cleaning up the application. If no action flags are provided,
    all steps except cleanup are executed in sequence. A dry-run mode logs the
    computed payload (and manifest) without uploading or submitting.

    Parameters
    ----------
    entry_point : str
        Path to the driver script (e.g., `"main.py"`). Used when packaging.
    package_name : str
        Logical application/package name used to derive S3 prefixes and metadata.
    pyproject : str
        Path to `pyproject.toml` (used to extract name/version/requirements for
        the deployment manifest).
    dry_run : bool
        If True, print/log the StartJobRun payload and manifest and exit without
        uploading or submitting.
    deployment_note : str or None
        Optional note stored in the deployment manifest (e.g., change summary).
    enable_cw : bool
        Whether to enable CloudWatch logging on the EMR job submission payload.
    config_s3 : str or None
        S3 URI to a configuration file for the job; propagated to driver args and
        as `spark.emr-serverless.driverEnv.CONFIG_S3_URI`.
    build_image : bool
        Build and push the container image referenced by the EMR Serverless app.
    create_app : bool
        Create (or update) the EMR Serverless application.
    package : bool
        Package the code, upload artifacts (ZIP and entry script) to S3, and write
        manifest files.
    submit : bool
        Submit the Spark job to EMR Serverless using the packaged artifacts.
    cleanup : bool
        Stop and delete the EMR Serverless application and remove `.emr_app_id`.
    debug : bool
        Inject remote-debugging environment variables (`DEBUG_HOST`,
        `DEBUG_PORT`, `DEBUGGER`) into the Spark driver so it attaches to
        your IDE through the bastion's reverse SSH tunnel.

    Returns
    -------
    None

    Environment Variables
    ---------------------
    The following are read depending on selected actions:

    Core
        `REGION` : AWS Region.
        `DEPLOY_ENV` : Environment label for S3 prefixes (default: `"dev"`).

    Build Image (when `--build-image`)
        `IMAGE_URI`

    Create/Update App (when `--create-app`)
        `IMAGE_URI`, `APP_NAME`, `RELEASE_LABEL`

    Package/Submit (when `--package` or `--submit`)
        `S3_BUCKET`, `EMR_APP_ID`, `EMR_EXECUTION_ROLE`

    Optional Iceberg Integration (auto-detected)
        `ICEBERG_CATALOG_NAME`, `ICEBERG_GLUE_DB`,
        `ICEBERG_S3_BUCKET``, `ICEBERG_WAREHOUSE_PATH`

    Optional Config
        `CONFIG_S3_URI` (overridden by `--config-s3`)

    Remote Debugging (when `--debug` or `--create-app` with a debug VPC)
        `DEBUG_HOST` : Bastion private IP (terraform output `DEBUG_HOST`).
        `DEBUG_PORT` : Tunnel port (default: `3535`).
        `DEBUGGER` : `pydevd` (PyCharm) or `debugpy` (VS Code).
        `DEBUG_SUBNET_IDS` : Comma-separated private subnet IDs for the app.
        `DEBUG_EMR_SECURITY_GROUP_ID` : Worker security group ID.

    EMR Studio (when `--create-app`)
        `EMR_STUDIO_ENABLED` : Set to `true` to enable interactive
        endpoints so the application can run notebooks from EMR Studio.

    Logging
        `ENABLE_CLOUDWATCH_LOGGING` (overridden by `--enable-cw/--no-enable-cw`)

    Raises
    ------
    SystemExit
        If required environment variables are missing for a chosen step,
        or when cleanup cannot determine the application ID (neither
        `EMR_APP_ID` set nor `.emr_app_id` file present).

    Notes
    -----
    - When no action flags are provided, the tool runs: build image → create/update app
      → package → submit.
    - A successful `--create-app` writes the application ID to `.emr_app_id` and
      exports it to `EMR_APP_ID` for subsequent steps.
    - `--dry-run` prints the manifest and the EMR StartJobRun payload but does not
      upload artifacts or call the API.

    Examples
    --------
    Run all steps (build, create/update app, package, submit):
    >>> deploy()  # invoked via CLI with no flags

    Dry-run a job submission (no uploads or API calls):
    $ python -m my_module.deploy \\
        --package-name my_pipeline \\
        --entry-point main.py \\
        --dry-run

    Build image and (re)create app only:
    $ python -m my_module.deploy --build-image --create-app

    Package and submit using an external config:
    $ python -m my_module.deploy --package --submit --config-s3 s3://bucket/path/config.toml

    Clean up (stop & delete the EMR app):
    $ python -m my_module.deploy --cleanup
    """
    if cleanup:
        validate_env_vars(["REGION"])
        region = os.environ["REGION"]
        app_id_file = Path(".emr_app_id")
        app_id = os.environ.get("EMR_APP_ID")
        if not app_id and app_id_file.exists():
            app_id = app_id_file.read_text().strip()

        if not app_id:
            error_msg = (
                "ERROR: EMR_APP_ID not set and .emr_app_id file not found. "
                "Cannot determine which application to clean up."
            )
            logger.error(error_msg)
            raise SystemExit(error_msg)

        delete_emr_app(app_id, region)
        if app_id_file.exists():
            app_id_file.unlink()
            logger.info("Removed .emr_app_id file.")
        return

    if not any([build_image, create_app, package, submit]):
        logger.info("No action requested. Running all steps.")
        build_image = create_app = package = submit = True

    if build_image:
        validate_env_vars(["IMAGE_URI", "REGION"])
        image_uri = os.environ["IMAGE_URI"]
        region = os.environ["REGION"]
        build_and_push_docker_image(image_uri, region)

    if create_app:
        validate_env_vars(["IMAGE_URI", "REGION", "APP_NAME", "RELEASE_LABEL"])
        image_uri = os.environ["IMAGE_URI"]
        region = os.environ["REGION"]
        app_name = os.environ["APP_NAME"]
        release_label = os.environ["RELEASE_LABEL"]
        debug_subnet_ids = [
            s.strip() for s in os.getenv("DEBUG_SUBNET_IDS", "").split(",") if s.strip()
        ]
        debug_sg_id = os.getenv("DEBUG_EMR_SECURITY_GROUP_ID", "").strip()
        studio_enabled = os.getenv("EMR_STUDIO_ENABLED", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        app_id = create_or_update_emr_app(
            app_name,
            image_uri,
            release_label,
            region,
            subnet_ids=debug_subnet_ids or None,
            security_group_ids=[debug_sg_id] if debug_sg_id else None,
            studio_enabled=studio_enabled,
        )
        with open(".emr_app_id", "w") as f:
            f.write(app_id)
        logger.info(f"EMR Application ID: {app_id}")
        os.environ["EMR_APP_ID"] = app_id

    if package or submit:
        validate_env_vars(["REGION", "S3_BUCKET", "EMR_APP_ID", "EMR_EXECUTION_ROLE"])

        region = os.environ["REGION"].strip().strip('"').strip("'")
        s3_bucket = os.environ["S3_BUCKET"].strip()
        emr_app_id = os.environ["EMR_APP_ID"].strip()
        exec_role = os.environ["EMR_EXECUTION_ROLE"].strip().strip('"').strip("'")

        build_dir = Path(".emr_build")
        s3_prefix = f"emr-code/{package_name}/{os.environ.get('DEPLOY_ENV', 'dev')}"

        zip_path = build_package(
            package_name=package_name,
            build_dir=build_dir,
        )

        zip_hash = sha256_sum(zip_path)[:8]
        deployment_ts = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%d_%H%M%S",
        )
        deployment_id = f"{deployment_ts}-{zip_hash}"
        version_prefix = f"{s3_prefix}/releases/{deployment_id}"
        log_uri = f"s3://{s3_bucket}/{s3_prefix}/logs/{deployment_id}/"
        meta = parse_pyproject_metadata(Path(pyproject))
        manifest = {
            "deployment_id": deployment_id,
            "created_at_utc": deployment_ts,
            "app_name": package_name,
            "package_name_from_pyproject": meta.get("name"),
            "package_version": meta.get("package_version"),
            "python_requires": meta.get("requires_python"),
            "python_version": sys.version.split()[0],
            "region": region,
            "deploy_env": os.environ.get("DEPLOY_ENV", "dev"),
            "emr_app_id": emr_app_id,
            "code_key": f"{version_prefix}/code.zip",
            "entry_key": f"{version_prefix}/main.py",
            "log_prefix": f"{s3_prefix}/logs/{deployment_id}/",
            "deployment_note": deployment_note,
            "zip_sha256": sha256_sum(zip_path),
            "zip_size_bytes": Path(zip_path).stat().st_size,
        }

        app_args: List[str] = []
        driver_env_conf: List[str] = []
        if config_s3:
            app_args += ["--config-s3", config_s3]
            driver_env_conf += [
                "--conf",
                f"spark.emr-serverless.driverEnv.CONFIG_S3_URI={config_s3}",
            ]

        if debug:
            validate_env_vars(["DEBUG_HOST"])
            debug_host = os.environ["DEBUG_HOST"].strip()
            debug_port = os.getenv("DEBUG_PORT", "3535").strip()
            debugger = os.getenv("DEBUGGER", "pydevd").strip()
            driver_env_conf += [
                "--conf",
                f"spark.emr-serverless.driverEnv.DEBUG_HOST={debug_host}",
                "--conf",
                f"spark.emr-serverless.driverEnv.DEBUG_PORT={debug_port}",
                "--conf",
                f"spark.emr-serverless.driverEnv.DEBUGGER={debugger}",
                # Generous timeouts so executors survive driver breakpoints.
                "--conf",
                "spark.network.timeout=600s",
                "--conf",
                "spark.executor.heartbeatInterval=60s",
            ]
            logger.info(
                f"Remote debugging enabled: driver will attach to "
                f"{debug_host}:{debug_port} via {debugger}.",
            )

        iceberg_keys = [
            "ICEBERG_CATALOG_NAME",
            "ICEBERG_GLUE_DB",
            "ICEBERG_S3_BUCKET",
            "ICEBERG_WAREHOUSE_PATH",
        ]
        conf_parts: List[str] = []
        for k in iceberg_keys:
            v = os.getenv(k)
            if v:
                conf_parts.append(f"--conf spark.emr_dummy.{k}={v}")

        catalog_name = os.getenv("ICEBERG_CATALOG_NAME", "glue_catalog")
        warehouse_path = os.getenv("ICEBERG_WAREHOUSE_PATH")
        if not warehouse_path and os.getenv("ICEBERG_S3_BUCKET"):
            warehouse_path = f"s3://{os.getenv('ICEBERG_S3_BUCKET')}/iceberg/warehouse"
        # ruff: noqa: E501
        conf_parts += [
            f"--conf spark.sql.catalog.{catalog_name}=org.apache.iceberg.spark.SparkCatalog",
            f"--conf spark.sql.catalog.{catalog_name}.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog",
            f"--conf spark.sql.catalog.{catalog_name}.warehouse={warehouse_path}",
        ]

        code_s3_uri = f"s3://{s3_bucket}/{manifest['code_key']}"
        entry_s3_uri = f"s3://{s3_bucket}/{manifest['entry_key']}"

        if dry_run:
            logger.info(f"Manifest (dry-run):\n{json.dumps(manifest, indent=2)}")
            spark_submit_parameters = " ".join(
                ["--py-files", code_s3_uri] + driver_env_conf + conf_parts,
            )
            submit_emr_job(
                spark_submit_parameters=spark_submit_parameters,
                code_s3_uri=code_s3_uri,
                entry_s3_uri=entry_s3_uri,
                emr_app_id=emr_app_id,
                execution_role=exec_role,
                region=region,
                log_uri=log_uri,
                enable_cloudwatch_logging=enable_cw,
                application_arguments=app_args,
                dry_run_payload={},
            )
            logger.info("Dry-run: no uploads and no submission made.")
            return

        if package:
            client = boto3.client("s3", region_name=region)
            _entry_src = Path(entry_point)
            _entry_tmp_dir = Path(".emr_build") / "entry_tmp"
            _entry_tmp_dir.mkdir(parents=True, exist_ok=True)
            temp_entry_path = _entry_tmp_dir / f"main_{deployment_id}.py"
            shutil.copy2(_entry_src, temp_entry_path)

            _, code_s3_uri = upload_file_to_s3_key(
                client=client,
                file_path=zip_path,
                bucket=s3_bucket,
                key=manifest["code_key"],
            )
            _, entry_s3_uri = upload_file_to_s3_key(
                client=client,
                file_path=temp_entry_path,
                bucket=s3_bucket,
                key=manifest["entry_key"],
            )

            manifest_key = f"{version_prefix}/manifest.json"

            upload_json(
                client=client,
                bucket=s3_bucket,
                key=manifest_key,
                data=manifest,
            )
            upload_json(
                client=client,
                bucket=s3_bucket,
                key=f"{s3_prefix}/releases/latest.json",
                data={"deployment_id": deployment_id},
            )

        if submit:
            spark_submit_parameters = " ".join(
                ["--py-files", code_s3_uri] + driver_env_conf + conf_parts,
            )
            job_id = submit_emr_job(
                spark_submit_parameters=spark_submit_parameters,
                code_s3_uri=code_s3_uri,
                entry_s3_uri=entry_s3_uri,
                emr_app_id=emr_app_id,
                execution_role=exec_role,
                region=region,
                log_uri=log_uri,
                enable_cloudwatch_logging=enable_cw,
                application_arguments=app_args,
            )
            logger.info(f"Logs S3 URI: {log_uri}")
            logger.info(f"JobRunId: {job_id}")
