"""Tests for the emr_dummy.job module."""

import argparse

import pytest

from emr_dummy import job


class TestTableNames:
    """Tests for the table-name helper functions."""

    def test_sql_name_backticks_database(self) -> None:
        """SQL form should backtick the database component."""
        result = job.get_full_table_name_sql("glue_catalog", "my_db", "users")
        assert result == "glue_catalog.`my_db`.users"

    def test_df_name_is_plain_dotted(self) -> None:
        """DataFrame form should be a plain dotted path."""
        result = job.get_full_table_name_df("glue_catalog", "my_db", "users")
        assert result == "glue_catalog.my_db.users"


class TestRequire:
    """Tests for the _require config lookup."""

    def test_returns_nested_value(self) -> None:
        """Dotted lookup should traverse nested dictionaries."""
        cfg = {"iceberg": {"table_name": "my_table"}}
        assert job._require(cfg, "iceberg.table_name") == "my_table"

    def test_missing_key_raises_system_exit(self) -> None:
        """SystemExit raised when a required key is absent."""
        with pytest.raises(SystemExit, match="iceberg.table_name"):
            job._require({}, "iceberg.table_name")


class TestLoadConfig:
    """Tests for the _load_config loader."""

    def test_falls_back_to_packaged_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Packaged config.toml used when no S3 URI is provided."""
        monkeypatch.delenv("CONFIG_S3_URI", raising=False)
        args = argparse.Namespace(config_s3=None)

        cfg = job._load_config(args)

        assert cfg["iceberg"]["table_name"] == "dom_iceberg_table"

    def test_s3_uri_passes_client_and_uri(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """S3 loader receives a boto3 client followed by the URI."""
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
        captured = {}

        def fake_read(client, uri):
            captured["client"] = client
            captured["uri"] = uri
            return {"iceberg": {"table_name": "from_s3"}}, {"sha256": "abc"}

        monkeypatch.setattr(job, "read_toml_from_s3", fake_read)
        args = argparse.Namespace(config_s3="s3://bucket/config.toml")

        cfg = job._load_config(args)

        assert cfg["iceberg"]["table_name"] == "from_s3"
        assert captured["uri"] == "s3://bucket/config.toml"
        assert captured["client"] is not None

    def test_cli_argument_overrides_environment(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """CLI --config-s3 takes precedence over CONFIG_S3_URI."""
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
        monkeypatch.setenv("CONFIG_S3_URI", "s3://bucket/from-env.toml")
        captured = {}

        def fake_read(client, uri):
            captured["uri"] = uri
            return {}, {}

        monkeypatch.setattr(job, "read_toml_from_s3", fake_read)
        args = argparse.Namespace(config_s3="s3://bucket/from-cli.toml")

        job._load_config(args)

        assert captured["uri"] == "s3://bucket/from-cli.toml"
