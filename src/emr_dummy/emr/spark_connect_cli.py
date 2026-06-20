"""CLI for managing Spark Connect sessions on EMR Serverless.

Subcommands:

- ``start``  : start a session and print the connection URL / ``SPARK_REMOTE``
- ``shell``  : start a session and drop into a Python REPL with ``spark`` bound
- ``list``   : list sessions on the application
- ``stop``   : terminate a session

All commands read ``REGION``, ``EMR_APP_ID``, and ``EMR_EXECUTION_ROLE`` from
the environment (or a ``.env`` file), matching the deploy CLI.
"""

from __future__ import annotations

import code
import logging
import os

import boto3
import click
from dotenv import load_dotenv
from rdsa_utils.helpers.python import validate_env_vars

from emr_dummy.emr.spark_connect import (
    get_connection_url,
    list_sessions,
    session_scope,
    start_session,
    terminate_session,
    wait_for_session,
)

logger = logging.getLogger(__name__)

load_dotenv()


@click.group()
def cli() -> None:
    """Manage Spark Connect sessions on EMR Serverless."""


@cli.command()
@click.option(
    "--timeout",
    default=300,
    show_default=True,
    help="Seconds to wait for the session to become ready.",
)
def start(timeout: int) -> None:
    """Start a session and print its connection URL.

    The session keeps running after this command exits (until its idle
    timeout or an explicit ``stop``), so you can paste the URL into a
    notebook or IDE. Export ``SPARK_REMOTE`` and any
    ``SparkSession.builder.getOrCreate()`` (or the ``pyspark`` shell) will
    connect automatically.

    Parameters
    ----------
    timeout
        Seconds to wait for the session to become ready.
    """
    validate_env_vars(["REGION", "EMR_APP_ID", "EMR_EXECUTION_ROLE"])
    region = os.environ["REGION"].strip()
    app_id = os.environ["EMR_APP_ID"].strip()
    exec_role = os.environ["EMR_EXECUTION_ROLE"].strip()

    client = boto3.client("emr-serverless", region_name=region)
    session_id = start_session(client, app_id, exec_role)
    wait_for_session(client, app_id, session_id, timeout)
    url, expires_at = get_connection_url(client, app_id, session_id)

    click.echo(f"\nSession ID:  {session_id}")
    click.echo(f"Token expiry: {expires_at}  (sessions also idle-timeout)")
    click.echo(f"\nexport SPARK_REMOTE='{url}'\n")
    click.echo(f"Stop it when done:  spark-connect stop {session_id}")


@cli.command()
@click.option(
    "--timeout",
    default=300,
    show_default=True,
    help="Seconds to wait for the session to become ready.",
)
def shell(timeout: int) -> None:
    """Start a session and open a Python REPL with ``spark`` connected.

    The session is terminated automatically when you exit the REPL.

    Parameters
    ----------
    timeout
        Seconds to wait for the session to become ready.
    """
    validate_env_vars(["REGION", "EMR_APP_ID", "EMR_EXECUTION_ROLE"])
    region = os.environ["REGION"].strip()
    app_id = os.environ["EMR_APP_ID"].strip()
    exec_role = os.environ["EMR_EXECUTION_ROLE"].strip()

    with session_scope(app_id, exec_role, region, timeout) as spark:
        banner = (
            f"Spark Connect ready (version {spark.version}). "
            "The 'spark' session is connected to EMR Serverless.\n"
            "Exit (Ctrl-D) to terminate the session."
        )
        code.interact(banner=banner, local={"spark": spark})


@cli.command(name="list")
def list_cmd() -> None:
    """List sessions on the EMR Serverless application."""
    validate_env_vars(["REGION", "EMR_APP_ID"])
    region = os.environ["REGION"].strip()
    app_id = os.environ["EMR_APP_ID"].strip()

    client = boto3.client("emr-serverless", region_name=region)
    sessions = list_sessions(client, app_id)
    if not sessions:
        click.echo("No sessions.")
        return
    for session in sessions:
        click.echo(f"{session.get('sessionId')}  {session.get('state')}")


@cli.command()
@click.argument("session_id")
def stop(session_id: str) -> None:
    """Terminate a session by ID.

    Parameters
    ----------
    session_id
        The session ID to terminate.
    """
    validate_env_vars(["REGION", "EMR_APP_ID"])
    region = os.environ["REGION"].strip()
    app_id = os.environ["EMR_APP_ID"].strip()

    client = boto3.client("emr-serverless", region_name=region)
    terminate_session(client, app_id, session_id)
    click.echo(f"Terminated {session_id}")


if __name__ == "__main__":
    cli()
