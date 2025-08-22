"""Minimal PySpark job that writes to an Iceberg table."""

import argparse
import logging
import os
from importlib import resources as ir
from typing import Any, Dict, Tuple

import pyspark.sql.functions as F
import tomli as _toml
from pyspark.sql import SparkSession
from rdsa_utils.helpers.pyspark import create_spark_session

from emr_dummy.s3_utils import read_toml_from_s3

logger = logging.getLogger(__name__)


def get_full_table_name_sql(catalog: str, database: str, table: str) -> str:
    """Construct a full SQL table name from catalog, database, and table components.

    Parameters
    ----------
    catalog
        The catalog name.
    database
        The database name.
    table
        The table name.

    Returns
    -------
    str
        The fully qualified SQL table name.

    Examples
    --------
    >>> get_full_table_name_sql("awsdatacatalog", "mydb", "users")
    'awsdatacatalog.`mydb`.users'
    """
    return f"{catalog}.`{database}`.{table}"


def get_full_table_name_df(catalog: str, database: str, table: str) -> str:
    """Construct the full table name from catalog, database, and table strings.

    Parameters
    ----------
    catalog
        The catalog name.
    database
        The database name.
    table
        The table name.

    Returns
    -------
    str
        The full table name in the format 'catalog.database.table'.

    Examples
    --------
    >>> get_full_table_name_df("awsdatacatalog", "mydb", "mytable")
    'awsdatacatalog.mydb.mytable'
    """
    return f"{catalog}.{database}.{table}"


def get_catalog_and_db(spark: SparkSession) -> Tuple[str, str]:
    """Retrieve the Iceberg catalog name and Glue database from Spark configuration.

    Parameters
    ----------
    spark
        The Spark session from which to retrieve configuration values.

    Returns
    -------
    Tuple[str, str]
        The Iceberg catalog name and Glue database name.

    Raises
    ------
    RuntimeError
        If the Glue database configuration ("spark.emr_dummy.ICEBERG_GLUE_DB")
        is missing.

    Examples
    --------
    >>> catalog, db = get_catalog_and_db(spark)
    >>> print(catalog, db)
    glue_catalog my_glue_db
    """
    catalog_name = spark.conf.get(
        "spark.emr_dummy.ICEBERG_CATALOG_NAME",
        "glue_catalog",
    )
    glue_db = spark.conf.get("spark.emr_dummy.ICEBERG_GLUE_DB", None)
    if not glue_db:
        error_msg = "Missing spark.emr_dummy.ICEBERG_GLUE_DB (provide via --conf)"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    return catalog_name, glue_db


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the dummy EMR job.

    Returns
    -------
    argparse.Namespace
        Parsed arguments with attributes such as `config_s3`.

    Examples
    --------
    >>> args = _parse_args()
    >>> args.config_s3
    's3://my-bucket/config.toml'
    """
    p = argparse.ArgumentParser(prog="emr-dummy-job")
    p.add_argument(
        "--config-s3",
        type=str,
        help="S3 URI to config.toml (s3://bucket/key)",
    )
    return p.parse_args()


def _load_config(args: argparse.Namespace) -> Dict[str, Any]:
    """Load configuration for the EMR dummy job.

    Prefers a config file from S3 (via CLI `--config-s3` or
    `CONFIG_S3_URI` env var). Falls back to a packaged `config.toml`
    under `emr_dummy`.

    Parameters
    ----------
    args
        CLI arguments, expected to have a `config_s3` attribute.

    Returns
    -------
    Dict[str, Any]
        Parsed TOML configuration as a dictionary.

    Raises
    ------
    ClientError
        If S3 retrieval fails.
    SystemExit
        If the TOML is malformed.

    Examples
    --------
    >>> args = argparse.Namespace(config_s3="s3://bucket/config.toml")
    >>> cfg = _load_config(args)
    >>> isinstance(cfg, dict)
    True
    """
    # Prefer CLI argument over environment variable, otherwise fallback to
    # packaged config.toml
    uri = args.config_s3 or os.getenv("CONFIG_S3_URI")
    if uri:
        cfg, meta = read_toml_from_s3(uri)
        logger.info(
            f"Loaded config from S3: {uri} (sha256={meta.get('sha256')}, "
            f"etag={meta.get('etag')}, version={meta.get('version_id')})",
        )
        return cfg

    # Fallback: load config.toml packaged within the emr_dummy module
    with ir.files("emr_dummy").joinpath("config.toml").open("rb") as f:
        content = f.read()
    cfg = _toml.loads(content.decode("utf-8"))
    logger.warning("Loaded packaged config.toml (S3 config not provided)")
    return cfg


def _require(cfg: Dict[str, Any], dotted_key: str) -> Any:
    """Retrieve a required configuration value by dotted key.

    Performs a simple dotted-path lookup (e.g., `"iceberg.table_name"`).
    Raises `SystemExit` if the key is missing.

    Parameters
    ----------
    cfg
        The configuration dictionary.
    dotted_key
        A dotted key path to retrieve.

    Returns
    -------
    Any
        The configuration value at the specified key.

    Raises
    ------
    SystemExit
        If the key does not exist.

    Examples
    --------
    >>> cfg = {"iceberg": {"table_name": "my_table"}}
    >>> _require(cfg, "iceberg.table_name")
    'my_table'
    """
    logger.info(f"Retrieving config value for key: {dotted_key}")
    keys = dotted_key.split(".")
    value: Any = cfg
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            error_msg = f"Config error: missing required key: {dotted_key}"
            logger.error(error_msg)
            raise SystemExit(error_msg)
        value = value[key]
    return value


def main() -> None:
    """Run the dummy EMR job.

    Parses arguments, loads configuration (from S3 or packaged file),
    retrieves Iceberg catalog and database from Spark configuration,
    creates the target Iceberg table if needed, and appends data.

    Notes
    -----
    - Writes 1,000 rows with schema `(id BIGINT, double BIGINT)`.
    - Creates the table if it does not exist.
    - Stops the Spark session at the end.
    """
    # Parse CLI arguments and load configuration
    args = _parse_args()
    cfg = _load_config(args)

    # Retrieve required table name from config
    table_name = _require(cfg, "iceberg.table_name")

    # Create Spark session
    spark = create_spark_session(app_name="emr-dummy-job")

    try:
        # Get Iceberg catalog and Glue DB from Spark config
        catalog_name, glue_db = get_catalog_and_db(spark)

        # Build full table names for SQL and DataFrame APIs
        full_table_name_sql = get_full_table_name_sql(catalog_name, glue_db, table_name)
        full_table_name_df = get_full_table_name_df(catalog_name, glue_db, table_name)

        # Create DataFrame with 1,000 rows: (id, double)
        df = spark.range(0, 1000).withColumn("double", F.col("id") * 2)

        # Ensure Iceberg table exists (create if not)
        spark.sql(
            f"""
            CREATE TABLE IF NOT EXISTS {full_table_name_sql} (
                id bigint,
                double bigint
            )
            USING iceberg
            """,
        )

        # Append data to Iceberg table
        df.writeTo(full_table_name_df).append()
        logger.info(f"[SUCCESS] Wrote to Iceberg table: {full_table_name_df}")

    except Exception as e:
        logger.error(f"Job failed: {e}", exc_info=True)
        raise
    finally:
        # Always stop Spark session
        spark.stop()
