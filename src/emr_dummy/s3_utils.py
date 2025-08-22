"""Utilities for working with Amazon S3 URIs and objects."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

import boto3
import tomli as _toml
from botocore.exceptions import ClientError
from rdsa_utils.cdp.helpers.s3_utils import create_s3_uri, split_s3_uri, upload_file

logger = logging.getLogger(__name__)


def read_toml_from_s3(
    client: boto3.client,
    s3_uri: str,
    encoding: str = "utf-8",
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Read a TOML file from Amazon S3 using a provided client.

    Downloads an object from S3, decodes it, parses it as TOML, and returns
    both the parsed configuration and audit metadata.

    Parameters
    ----------
    client
        An initialised boto3 S3 client.
    s3_uri
        S3 URI to the TOML file.
    encoding
        The encoding to use for decoding the file. Defaults to "utf-8".

    Returns
    -------
    Tuple[Dict[str, Any], Dict[str, str]]
        A tuple containing:
        - The parsed TOML as a dictionary.
        - Audit metadata including "sha256", "etag", and "version_id". The
          checksum is calculated using the SHA-256 algorithm.

    Raises
    ------
    ClientError
        If the S3 get_object request fails.
    ValueError
        If `s3_uri` is not a valid S3 URI.

    Examples
    --------
    >>> import boto3
    >>> client = boto3.client("s3")
    >>> config, meta = read_toml_from_s3(client, "s3://my-bucket/config.toml")
    """
    bucket, key = split_s3_uri(s3_uri)
    try:
        obj = client.get_object(Bucket=bucket, Key=key)
        body: bytes = obj["Body"].read()

        config = _toml.loads(body.decode(encoding))

        meta: Dict[str, str] = {
            "sha256": hashlib.sha256(body).hexdigest(),
            "etag": obj.get("ETag", "").strip('"'),
        }
        if version_id := obj.get("VersionId"):
            meta["version_id"] = str(version_id)

        logger.info(f"Loaded S3 config: {s3_uri} (sha256={meta['sha256']})")
        return config, meta
    except ClientError as e:
        logger.error(f"Failed to read TOML from {s3_uri}: {e}")
        raise
    except (_toml.TOMLDecodeError, UnicodeDecodeError) as e:
        logger.error(f"Failed to parse TOML file from {s3_uri}: {e}")
        raise


def upload_file_to_s3_key(
    client: boto3.client,
    file_path: Union[str, Path],
    bucket: str,
    key: str,
) -> Tuple[bool, Optional[str]]:
    """Upload a file to an exact S3 key, returning its URI.

    This function provides a clear interface for uploading to a precise S3
    location by calling the general `upload_file` utility.

    Parameters
    ----------
    client
        An initialised boto3 S3 client.
    file_path
        The local path of the file to upload.
    bucket
        The name of the target S3 bucket.
    key
        The exact S3 key (path within the bucket) for the uploaded file.

    Returns
    -------
    Tuple[bool, Optional[str]]
        A tuple containing:
        - A boolean indicating if the upload was successful.
        - The S3 URI of the uploaded object, or None on failure.

    Examples
    --------
    >>> # from pathlib import Path
    >>> # client = boto3.client("s3")
    >>> # Path("local.txt").touch()
    >>> # success, uri = upload_file_to_s3_key(
    ... #     client, "local.txt", "my-bucket", "archive/report.txt"
    ... # )
    """
    success = upload_file(client, bucket, str(file_path), key, overwrite=True)
    if success:
        uri = create_s3_uri(bucket, key)
        logger.info(f"Uploaded {file_path} -> {uri}")
        return True, uri
    return False, None


def upload_json(
    client: boto3.client,
    bucket: str,
    key: str,
    data: dict,
    indent: Optional[int] = 2,
    encoding: str = "utf-8",
) -> Tuple[bool, Optional[str]]:
    """Upload a JSON object to Amazon S3.

    The input dictionary is serialised into a JSON string and uploaded
    to the specified S3 bucket and key.

    Parameters
    ----------
    client
        An initialised boto3 S3 client.
    bucket
        The name of the target S3 bucket.
    key
        The exact S3 key (path within the bucket) where the JSON object
        should be stored.
    data
        The dictionary to serialise and upload as JSON.
    indent
        The indentation level for pretty-printing the JSON. Defaults to 2.
    encoding
        The encoding to use for the uploaded file. Defaults to "utf-8".

    Returns
    -------
    Tuple[bool, Optional[str]]
        A tuple containing:
        - A boolean indicating if the upload was successful.
        - The S3 URI of the uploaded object, or None on failure.

    Examples
    --------
    >>> # client = boto3.client("s3")
    >>> # payload = {"name": "Alice", "age": 30}
    >>> # success, uri = upload_json(client, "my-bucket", "users/alice.json", payload)
    """
    try:
        body = json.dumps(data, indent=indent).encode(encoding)
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
        )
        uri = create_s3_uri(bucket, key)
        logger.info(f"Uploaded JSON -> {uri}")
        return True, uri
    except ClientError as e:
        logger.error(f"Failed to upload JSON to s3://{bucket}/{key}: {e}")
        return False, None
