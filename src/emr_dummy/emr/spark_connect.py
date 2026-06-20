"""Client helpers for interactive PySpark via Spark Connect on EMR Serverless.

Spark Connect (EMR release 7.13.0 and later) lets a local PySpark client talk
to a Spark driver running on EMR Serverless over a gRPC/TLS endpoint. Your
DataFrame and SQL code runs locally as the client and is executed remotely --
so you debug with ordinary local breakpoints, with no VPC, bastion, or tunnel.

The flow is: ``StartSession`` -> poll ``GetSession`` until ready ->
``GetSessionEndpoint`` for the URL and auth token -> connect a
``SparkSession`` to the ``sc://`` URL. Sessions cost money until terminated or
idle-timed-out, so always ``TerminateSession`` when finished (use
``session_scope`` to do this automatically).
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator

import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

logger = logging.getLogger(__name__)

DEFAULT_PORT = 443
READY_STATES = ("STARTED", "IDLE")
FAILED_STATES = ("FAILED", "TERMINATED")


def build_connect_url(endpoint: str, auth_token: str) -> str:
    """Build a Spark Connect ``sc://`` URL from an endpoint and auth token.

    ``GetSessionEndpoint`` returns an HTTPS URL without a port. The PySpark
    client defaults to port 15002 (not reachable on EMR Serverless), so the
    port must be pinned to 443.

    Parameters
    ----------
    endpoint
        The endpoint URL returned by ``GetSessionEndpoint`` (e.g.
        ``https://hostname``).
    auth_token
        The session authentication token from ``GetSessionEndpoint``.

    Returns
    -------
    str
        A connection URL of the form
        ``sc://host:443/;use_ssl=true;x-aws-proxy-auth=<token>``.

    Examples
    --------
    >>> build_connect_url("https://example.amazonaws.com", "tok")
    'sc://example.amazonaws.com:443/;use_ssl=true;x-aws-proxy-auth=tok'
    """
    netloc = endpoint.split("://", 1)[-1].strip("/").split("/", 1)[0]
    if ":" not in netloc:
        netloc = f"{netloc}:{DEFAULT_PORT}"
    return f"sc://{netloc}/;use_ssl=true;x-aws-proxy-auth={auth_token}"


def start_session(
    client: boto3.client,
    application_id: str,
    execution_role: str,
) -> str:
    """Start a Spark Connect session on an EMR Serverless application.

    Parameters
    ----------
    client
        A boto3 ``emr-serverless`` client.
    application_id
        The EMR Serverless application ID (must have ``sessionEnabled``).
    execution_role
        IAM execution role ARN the session assumes to access your data.

    Returns
    -------
    str
        The new session ID.
    """
    resp = client.start_session(
        applicationId=application_id,
        executionRoleArn=execution_role,
    )
    session_id = resp["sessionId"]
    logger.info(f"Started Spark Connect session {session_id}")
    return session_id


def wait_for_session(
    client: boto3.client,
    application_id: str,
    session_id: str,
    timeout_seconds: int = 300,
    poll_seconds: int = 5,
) -> str:
    """Poll a session until it is ready to accept connections.

    Parameters
    ----------
    client
        A boto3 ``emr-serverless`` client.
    application_id
        The EMR Serverless application ID.
    session_id
        The session ID to poll.
    timeout_seconds
        Maximum time to wait for the session to become ready.
        Default is 300.
    poll_seconds
        Delay between polls. Default is 5.

    Returns
    -------
    str
        The ready state reached (``STARTED`` or ``IDLE``).

    Raises
    ------
    RuntimeError
        If the session reaches a ``FAILED`` or ``TERMINATED`` state.
    TimeoutError
        If the session does not become ready within ``timeout_seconds``.
    """
    start = time.time()
    while time.time() - start < timeout_seconds:
        session = client.get_session(
            applicationId=application_id,
            sessionId=session_id,
        )["session"]
        state = session["state"]
        if state in READY_STATES:
            logger.info(f"Session {session_id} is {state}")
            return state
        if state in FAILED_STATES:
            details = session.get("stateDetails", "unknown")
            error_msg = f"Session {session_id} entered {state}: {details}"
            raise RuntimeError(error_msg)
        logger.info(f"Session {session_id} is {state}, waiting...")
        time.sleep(poll_seconds)
    error_msg = f"Timed out waiting for session {session_id} to become ready."
    raise TimeoutError(error_msg)


def get_connection_url(
    client: boto3.client,
    application_id: str,
    session_id: str,
) -> tuple[str, Any]:
    """Retrieve the Spark Connect URL and token expiry for a session.

    Parameters
    ----------
    client
        A boto3 ``emr-serverless`` client.
    application_id
        The EMR Serverless application ID.
    session_id
        The session ID.

    Returns
    -------
    tuple[str, Any]
        The ``sc://`` connection URL and the token expiry time (as returned
        by the API, or ``None`` if absent). Tokens expire after one hour.
    """
    resp = client.get_session_endpoint(
        applicationId=application_id,
        sessionId=session_id,
    )
    url = build_connect_url(resp["endpoint"], resp["authToken"])
    return url, resp.get("authTokenExpiresAt")


def terminate_session(
    client: boto3.client,
    application_id: str,
    session_id: str,
) -> None:
    """Terminate a Spark Connect session to stop billing.

    Parameters
    ----------
    client
        A boto3 ``emr-serverless`` client.
    application_id
        The EMR Serverless application ID.
    session_id
        The session ID to terminate.
    """
    try:
        client.terminate_session(
            applicationId=application_id,
            sessionId=session_id,
        )
        logger.info(f"Terminated session {session_id}")
    except ClientError as err:
        if err.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.warning(f"Session {session_id} not found, may already be gone.")
        else:
            raise


def list_sessions(
    client: boto3.client,
    application_id: str,
) -> list[dict]:
    """List sessions on an EMR Serverless application.

    Parameters
    ----------
    client
        A boto3 ``emr-serverless`` client.
    application_id
        The EMR Serverless application ID.

    Returns
    -------
    list[dict]
        The session summaries returned by ``ListSessions``.
    """
    resp = client.list_sessions(applicationId=application_id)
    return resp.get("sessions", [])


@contextmanager
def session_scope(
    application_id: str,
    execution_role: str,
    region: str,
    timeout_seconds: int = 300,
) -> Iterator[SparkSession]:
    """Yield a connected ``SparkSession``, terminating the session on exit.

    Starts a Spark Connect session, waits for it to be ready, connects a
    local ``SparkSession`` to it, and -- whatever happens -- terminates the
    EMR Serverless session afterwards so it stops incurring charges.

    Parameters
    ----------
    application_id
        The EMR Serverless application ID (must have ``sessionEnabled``).
    execution_role
        IAM execution role ARN the session assumes to access your data.
    region
        The AWS region of the application.
    timeout_seconds
        Maximum time to wait for the session to become ready.
        Default is 300.

    Yields
    ------
    SparkSession
        A Spark session connected to the remote EMR Serverless driver.

    Examples
    --------
    >>> with session_scope(app_id, role, "eu-west-2") as spark:  # doctest: +SKIP
    ...     spark.range(10).show()
    """
    from pyspark.sql import SparkSession

    client = boto3.client("emr-serverless", region_name=region)
    session_id = start_session(client, application_id, execution_role)
    try:
        wait_for_session(client, application_id, session_id, timeout_seconds)
        url, _ = get_connection_url(client, application_id, session_id)
        spark = SparkSession.builder.remote(url).getOrCreate()
        try:
            yield spark
        finally:
            spark.stop()
    finally:
        terminate_session(client, application_id, session_id)
