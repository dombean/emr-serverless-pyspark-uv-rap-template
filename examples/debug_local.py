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
from pyspark.sql import DataFrame, SparkSession

from emr_dummy.emr.spark_connect import session_scope

load_dotenv()


def build_doubles(spark: SparkSession) -> DataFrame:
    """Build a small example DataFrame to step through.

    Factoring your logic into functions that take ``spark`` is what makes it
    debuggable: set a breakpoint inside one and call it with the remote
    session below. Your real job's transforms should look like this.

    Parameters
    ----------
    spark
        A Spark session (here, connected to EMR Serverless via Spark Connect).

    Returns
    -------
    DataFrame
        A DataFrame of ``id`` and its double.
    """
    df_range = spark.range(0, 1000)
    df_doubled = df_range.withColumn("double", F.col("id") * 2)
    return df_doubled


def main() -> None:
    """Open a Spark Connect session and debug a transform against it."""
    app_id = os.getenv("EMR_APP_ID") or Path(".emr_app_id").read_text().strip()
    with session_scope(
        app_id,
        os.environ["EMR_EXECUTION_ROLE"],
        os.environ["REGION"],
    ) as spark:
        df_doubled = build_doubles(spark)
        breakpoint()  # inspect df_doubled here; e.g. df_doubled.show()
        df_doubled.show()


if __name__ == "__main__":
    main()
