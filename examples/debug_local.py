"""Interactively debug PySpark against EMR Serverless via Spark Connect.

Run this under your IDE's debugger (set gutter breakpoints) or with
``python examples/debug_local.py`` (drops into pdb at ``breakpoint()``). Your
code runs locally, so breakpoints behave normally; only the Spark compute runs
on EMR Serverless. The session is terminated automatically on exit (including
on error), so you never leak a paid session.

Prerequisites (see docs/spark_connect_guide.md):

- A local Python 3.10+ env with the dev extra: ``uv pip install -e ".[dev]"``.
- An application created with Spark Connect enabled::

      SPARK_CONNECT_ENABLED=true deploy-to-emr --build-image --create-app

- A ``.env`` providing ``REGION`` and ``EMR_EXECUTION_ROLE``. ``EMR_APP_ID``
  is optional -- it falls back to the ``.emr_app_id`` file that
  ``--create-app`` writes.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyspark.sql.functions as F
from dotenv import load_dotenv

from emr_dummy.emr.spark_connect import session_scope

load_dotenv()


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
        # `run` takes `spark`, so you can debug exactly what the batch job runs.
        # The Iceberg catalog confs are normally injected via --conf at submit;
        # set them on the session first when debugging that path.
        #
        # from emr_dummy.job import run
        # spark.conf.set("spark.emr_dummy.ICEBERG_GLUE_DB", "your_glue_db")
        # spark.conf.set("spark.emr_dummy.ICEBERG_CATALOG_NAME", "glue_catalog")
        # run(spark, {"iceberg": {"table_name": "debug_table"}})


if __name__ == "__main__":
    main()
