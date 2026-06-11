"""Hook for attaching the Spark driver to a remote debugger on EMR Serverless.

Implements the reverse-SSH-tunnel pattern from
https://github.com/aws-samples/remote-debugging-with-emr: the driver opens an
outbound TCP connection to the debug bastion's private IP, which the bastion's
sshd forwards back through a reverse tunnel to the IDE's debug server running
on your laptop.

The hook is driven entirely by environment variables injected at job
submission time (see the ``--debug`` flag on the deploy CLI):

- ``DEBUG_HOST``: private IP of the debug bastion. If unset, the hook is a
  no-op, so it is always safe to call.
- ``DEBUG_PORT``: TCP port of the tunnel (default ``3535``).
- ``DEBUGGER``: ``pydevd`` for PyCharm Professional (default) or ``debugpy``
  for VS Code.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_DEBUG_PORT = 3535


def attach_remote_debugger() -> None:
    """Attach this process to a remote debugger if one is configured.

    Reads ``DEBUG_HOST``, ``DEBUG_PORT``, and ``DEBUGGER`` from the
    environment and connects to the waiting IDE through the bastion's
    reverse SSH tunnel. Does nothing when ``DEBUG_HOST`` is unset, so it can
    be called unconditionally at the top of every job entry point.

    Raises
    ------
    RuntimeError
        If debugging was requested but the debugger package is missing from
        the image, or the bastion/tunnel is unreachable.

    Examples
    --------
    >>> attach_remote_debugger()  # no-op unless DEBUG_HOST is set
    """
    host = os.getenv("DEBUG_HOST")
    if not host:
        return

    port = int(os.getenv("DEBUG_PORT", str(DEFAULT_DEBUG_PORT)))
    debugger = os.getenv("DEBUGGER", "pydevd").strip().lower()
    logger.info(f"Attaching remote debugger ({debugger}) to {host}:{port}")

    if debugger == "debugpy":
        _attach_debugpy(host, port)
    else:
        _attach_pydevd(host, port)

    logger.info("Remote debugger attached.")


def _attach_pydevd(host: str, port: int) -> None:
    """Connect to a PyCharm Python Debug Server via pydevd.

    Parameters
    ----------
    host
        Private IP of the debug bastion.
    port
        TCP port of the reverse tunnel.

    Raises
    ------
    RuntimeError
        If pydevd-pycharm is not installed or the connection fails.
    """
    try:
        import pydevd_pycharm  # noqa: T100
    except ImportError as err:
        error_msg = (
            "DEBUG_HOST is set but pydevd-pycharm is not installed in the "
            "image. Rebuild with the 'debug' extra (see Dockerfile)."
        )
        raise RuntimeError(error_msg) from err

    try:
        pydevd_pycharm.settrace(
            host,
            port=port,
            stdoutToServer=True,
            stderrToServer=True,
            suspend=False,
        )
    except (ConnectionRefusedError, OSError, TimeoutError) as err:
        error_msg = (
            f"Could not reach the PyCharm debug server at {host}:{port}. "
            "Check that the reverse SSH tunnel to the bastion is running "
            "and the IDE debug server is listening."
        )
        raise RuntimeError(error_msg) from err


def _attach_debugpy(host: str, port: int) -> None:
    """Connect to a listening VS Code debug session via debugpy.

    Parameters
    ----------
    host
        Private IP of the debug bastion.
    port
        TCP port of the reverse tunnel.

    Raises
    ------
    RuntimeError
        If debugpy is not installed or the connection fails.
    """
    try:
        import debugpy  # noqa: T100
    except ImportError as err:
        error_msg = (
            "DEBUG_HOST is set but debugpy is not installed in the image. "
            "Rebuild with the 'debug' extra (see Dockerfile)."
        )
        raise RuntimeError(error_msg) from err

    try:
        debugpy.connect((host, port))
    except (ConnectionRefusedError, OSError, TimeoutError) as err:
        error_msg = (
            f"Could not reach the VS Code debug listener at {host}:{port}. "
            "Check that the reverse SSH tunnel to the bastion is running "
            "and the 'listen' attach configuration is active in VS Code."
        )
        raise RuntimeError(error_msg) from err
