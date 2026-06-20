"""Interactively debug PySpark against EMR Serverless via Spark Connect.

Run this under your IDE's debugger (set gutter breakpoints) or with
`python examples/debug_local.py` (drops into pdb at `breakpoint()`). Your
code runs locally, so breakpoints behave normally; only the Spark compute runs
on EMR Serverless. The session is terminated automatically on exit (including
on error), so you never leak a paid session.

Prerequisites (see docs/spark_connect_guide.md):

- A local Python 3.10+ env with the dev extra: `uv pip install -e ".[dev]"`.
- An application created with Spark Connect enabled:

      SPARK_CONNECT_ENABLED=true deploy-to-emr --build-image --create-app

- A `.env` providing `REGION` and `EMR_EXECUTION_ROLE`. `EMR_APP_ID`
  is optional -- it falls back to the `.emr_app_id` file that
  `--create-app` writes.
- For Option 2 (running the real job), set `ICEBERG_GLUE_DB` in `.env`
  (and optionally `ICEBERG_CATALOG_NAME` / `ICEBERG_S3_BUCKET` /
  `ICEBERG_WAREHOUSE_PATH`). These are normally injected via `--conf` at
  batch submit; here they are applied to the session from the environment.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pyspark.sql.functions as F
from dotenv import load_dotenv
from pyspark.sql import SparkSession

from emr_dummy.emr.spark_connect import session_scope
from emr_dummy.job import run

logger = logging.getLogger(__name__)

load_dotenv(override=True)  # .env wins over any stale shell vars


def configure_iceberg_from_env(spark: SparkSession) -> bool:
    """Apply the Iceberg/Glue Spark confs from environment variables.

    Mirrors what `deploy-to-emr` injects via `--conf` at batch submit, so the
    job's `get_catalog_and_db` and Iceberg writes work over a Spark Connect
    session. Reads `ICEBERG_GLUE_DB` (required), `ICEBERG_CATALOG_NAME`,
    `ICEBERG_WAREHOUSE_PATH`, and `ICEBERG_S3_BUCKET`.

    Parameters
    ----------
    spark
        The Spark Connect session to configure.

    Returns
    -------
    bool
        True if `ICEBERG_GLUE_DB` was set (confs applied), otherwise False.

    Notes
    -----
    The `spark.sql.catalog.*` plugin confs are ideally set when the session
    starts; applying them post-hoc may not register the catalog over Spark
    Connect. If an Iceberg write fails, start the session with these confs
    instead (the StartSession `runtimeConfiguration`).
    """
    glue_db = os.getenv("ICEBERG_GLUE_DB")
    if not glue_db:
        return False

    catalog = os.getenv("ICEBERG_CATALOG_NAME", "glue_catalog")
    warehouse = os.getenv("ICEBERG_WAREHOUSE_PATH")
    bucket = os.getenv("ICEBERG_S3_BUCKET")
    if not warehouse and bucket:
        warehouse = f"s3://{bucket}/iceberg/warehouse"

    # Read by job.get_catalog_and_db (plain confs; safe to set over Connect).
    spark.conf.set("spark.emr_dummy.ICEBERG_CATALOG_NAME", catalog)
    spark.conf.set("spark.emr_dummy.ICEBERG_GLUE_DB", glue_db)

    # Iceberg catalog plugin configuration.
    spark.conf.set(
        f"spark.sql.catalog.{catalog}",
        "org.apache.iceberg.spark.SparkCatalog",
    )
    spark.conf.set(
        f"spark.sql.catalog.{catalog}.catalog-impl",
        "org.apache.iceberg.aws.glue.GlueCatalog",
    )
    if warehouse:
        spark.conf.set(f"spark.sql.catalog.{catalog}.warehouse", warehouse)

    logger.info(f"Configured Iceberg catalog '{catalog}', Glue DB '{glue_db}'")
    return True


def main() -> None:
    """Open a Spark Connect session and debug the job's logic against it."""
    app_id = os.getenv("EMR_APP_ID") or Path(".emr_app_id").read_text().strip()
    with session_scope(
        app_id,
        os.environ["EMR_EXECUTION_ROLE"],
        os.environ["REGION"],
    ) as spark:
        # --- Option 1: poke around interactively -----------------------------
        # Plain DataFrame ops need no special config; great for a first check.
        df_doubled = spark.range(0, 1000).withColumn("double", F.col("id") * 2)
        breakpoint()  # inspect df_doubled here; e.g. df_doubled.show()
        df_doubled.show()

        # --- Option 2: step through the real job logic -----------------------
        # `run` takes `spark`, so you debug exactly what the batch job runs.
        # Set a breakpoint inside run() in src/emr_dummy/job.py. Runs only when
        # ICEBERG_GLUE_DB is set in your env (that is how the Glue DB is
        # provided), mirroring batch submit.
        if configure_iceberg_from_env(spark):
            table_name = os.getenv("DEBUG_TABLE_NAME", "debug_table")
            run(spark, {"iceberg": {"table_name": table_name}})
        else:
            logger.info("ICEBERG_GLUE_DB not set; skipping the job-logic run.")


if __name__ == "__main__":
    main()
