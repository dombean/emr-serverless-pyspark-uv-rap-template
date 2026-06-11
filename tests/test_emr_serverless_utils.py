"""Tests for the emr_dummy.emr.emr_serverless_utils module."""

import zipfile
from pathlib import Path

import pytest

from emr_dummy.emr.emr_serverless_utils import build_package, submit_emr_job


class TestBuildPackage:
    """Tests for the build_package source packager."""

    def test_zips_src_contents_at_archive_root(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Packages under src/ end up at the root of the archive."""
        monkeypatch.chdir(tmp_path)
        pkg = tmp_path / "src" / "my_pkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "module.py").write_text("VALUE = 1\n")

        zip_path = build_package("my_pkg", tmp_path / "build")

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        assert "my_pkg/module.py" in names
        assert "my_pkg/__init__.py" in names

    def test_excludes_pycache_artifacts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """__pycache__ directories and .pyc files are not packaged."""
        monkeypatch.chdir(tmp_path)
        pkg = tmp_path / "src" / "my_pkg"
        cache = pkg / "__pycache__"
        cache.mkdir(parents=True)
        (pkg / "module.py").write_text("VALUE = 1\n")
        (cache / "module.cpython-310.pyc").write_text("junk")

        zip_path = build_package("my_pkg", tmp_path / "build")

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)

    def test_missing_src_raises_file_not_found(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """FileNotFoundError raised when src/ does not exist."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError, match="src/"):
            build_package("my_pkg", tmp_path / "build")


class TestSubmitEmrJob:
    """Tests for the submit_emr_job dry-run behaviour."""

    def test_dry_run_makes_no_api_call(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Dry run returns the sentinel job ID without calling AWS."""
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
        job_id = submit_emr_job(
            code_s3_uri="s3://bucket/code.zip",
            entry_s3_uri="s3://bucket/main.py",
            spark_submit_parameters=None,
            emr_app_id="00fakeappid",
            execution_role="arn:aws:iam::123456789012:role/fake-role",
            region="eu-west-2",
            log_uri="s3://bucket/logs/",
            dry_run_payload={},
        )
        assert job_id == "dry-run-job-id"
