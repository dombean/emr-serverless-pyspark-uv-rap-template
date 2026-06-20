"""Tests for the emr_dummy.emr.spark_connect module."""

import pytest

from emr_dummy.emr import spark_connect


class TestBuildConnectUrl:
    """Tests for the build_connect_url function."""

    def test_appends_port_443_when_missing(self) -> None:
        """A portless endpoint should get :443 pinned (not the 15002 default)."""
        url = spark_connect.build_connect_url("https://host.example.com", "tok")
        assert url == "sc://host.example.com:443/;use_ssl=true;x-aws-proxy-auth=tok"

    def test_preserves_existing_port(self) -> None:
        """An endpoint that already has a port is left as-is."""
        url = spark_connect.build_connect_url("https://host.example.com:8443", "t")
        assert url.startswith("sc://host.example.com:8443/")

    def test_strips_scheme_and_trailing_slash(self) -> None:
        """The scheme is rewritten to sc:// and trailing slashes dropped."""
        url = spark_connect.build_connect_url("https://host/", "tok")
        assert url == "sc://host:443/;use_ssl=true;x-aws-proxy-auth=tok"


class FakeClient:
    """Minimal stand-in for a boto3 emr-serverless client."""

    def __init__(self, states: list[str]) -> None:
        self._states = states
        self.terminated: list[str] = []

    def start_session(self, applicationId: str, executionRoleArn: str) -> dict:
        return {"sessionId": "sess-1"}

    def get_session(self, applicationId: str, sessionId: str) -> dict:
        state = self._states.pop(0)
        return {"session": {"state": state, "stateDetails": "boom"}}

    def get_session_endpoint(self, applicationId: str, sessionId: str) -> dict:
        return {
            "endpoint": "https://host",
            "authToken": "tok",
            "authTokenExpiresAt": "x",
        }

    def terminate_session(self, applicationId: str, sessionId: str) -> dict:
        self.terminated.append(sessionId)
        return {}

    def list_sessions(self, applicationId: str) -> dict:
        return {"sessions": [{"sessionId": "sess-1", "state": "STARTED"}]}


class TestSessionLifecycle:
    """Tests for the session start/wait/connect helpers."""

    def test_start_session_returns_id(self) -> None:
        """start_session returns the new session ID."""
        client = FakeClient([])
        assert spark_connect.start_session(client, "app", "role") == "sess-1"

    def test_wait_returns_when_ready(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """wait_for_session returns once the session reaches a ready state."""
        monkeypatch.setattr(spark_connect.time, "sleep", lambda _: None)
        client = FakeClient(["STARTING", "STARTED"])
        assert spark_connect.wait_for_session(client, "app", "sess-1") == "STARTED"

    def test_wait_raises_on_failed_state(self) -> None:
        """wait_for_session raises RuntimeError if the session fails."""
        client = FakeClient(["FAILED"])
        with pytest.raises(RuntimeError, match="boom"):
            spark_connect.wait_for_session(client, "app", "sess-1")

    def test_wait_times_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """wait_for_session raises TimeoutError if never ready."""
        monkeypatch.setattr(spark_connect.time, "sleep", lambda _: None)
        client = FakeClient(["STARTING"] * 50)
        with pytest.raises(TimeoutError):
            spark_connect.wait_for_session(
                client,
                "app",
                "sess-1",
                timeout_seconds=0,
            )

    def test_get_connection_url_builds_sc_url(self) -> None:
        """get_connection_url returns a port-pinned sc:// URL and expiry."""
        client = FakeClient([])
        url, expires = spark_connect.get_connection_url(client, "app", "sess-1")
        assert url == "sc://host:443/;use_ssl=true;x-aws-proxy-auth=tok"
        assert expires == "x"

    def test_list_sessions_returns_summaries(self) -> None:
        """list_sessions returns the session summaries."""
        client = FakeClient([])
        sessions = spark_connect.list_sessions(client, "app")
        assert sessions[0]["sessionId"] == "sess-1"
