"""Optional real S3 staging backup discovery test.

This test attempts to list real staging backups in the development AWS
account to provide early detection of credential / permission regressions
and filename pattern drift. It is OPTIONAL and will be **skipped** when:

* AWS credentials are not configured (NoCredentialsError)
* Access is denied to the bucket (AccessDenied)
* The bucket does not exist (wrong account / region)

Skipping keeps local/offline development fast while providing additional
signal in CI or properly configured developer environments.

We intentionally DO NOT fail the suite on missing objects; an empty result
emits an assertion error only if credentials and bucket access succeeded
but zero matching keys were returned (this might indicate an upstream
backup pipeline issue).
"""

from __future__ import annotations

import os
from datetime import datetime

import boto3
import pytest
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound

from pulldb.infra.s3 import BACKUP_FILENAME_REGEX


STAGING_BUCKET = os.environ.get(
    "PULLDB_STAGING_BUCKET", "pestroutesrdsdbs"
)  # default from docs
STAGING_PREFIX = os.environ.get("PULLDB_STAGING_PREFIX", "daily/stg/")
# S3 bucket access requires pr-staging profile (staging account 333204494849)
S3_AWS_PROFILE = os.environ.get("PULLDB_S3_AWS_PROFILE", "pr-staging")


@pytest.mark.timeout(30)
def test_real_staging_backup_listing_optional() -> None:  # pragma: no cover
    """List real staging backup objects and validate at least one tar present.

    Skips gracefully when AWS not configured or access errors occur.
    Uses PULLDB_S3_AWS_PROFILE (default: pr-staging) for S3 access.
    """
    try:
        # Use the S3-specific AWS profile for bucket access
        session = boto3.Session(profile_name=S3_AWS_PROFILE)
        s3 = session.client("s3")
        paginator = s3.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=STAGING_BUCKET, Prefix=STAGING_PREFIX)
    except ProfileNotFound as e:  # AWS profile doesn't exist in config
        pytest.skip(f"AWS profile not found (check ~/.aws/config): {e}")
    except NoCredentialsError as e:  # no AWS auth configured
        pytest.skip(f"AWS credentials not configured: {e}")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
            pytest.skip(f"Skipping real S3 listing due to access error: {code}")
        if code in {"NoSuchBucket"}:
            pytest.skip(f"Bucket '{STAGING_BUCKET}' not found (wrong account/region?)")
        # Unexpected client error -> fail hard for visibility
        raise

    matching_keys: list[str] = []
    try:
        for page in pages:
            for item in page.get("Contents", []) or []:
                key = item.get("Key")
                if not isinstance(key, str):
                    continue
                filename = key.rsplit("/", 1)[-1]
                if BACKUP_FILENAME_REGEX.match(filename):
                    matching_keys.append(key)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code == "AccessDenied":
            pytest.skip(
                "Skipping real S3 listing: AccessDenied during paginator iteration"
            )
        raise

    if not matching_keys:
        pytest.fail(
            "No staging backup objects matched pattern under "
            f"s3://{STAGING_BUCKET}/{STAGING_PREFIX}. "
            "Investigate upstream backup pipeline or adjust test if "
            "pattern changed."
        )

    # Basic invariant: newest timestamp sorts last when parsed & sorted
    def _extract_ts(key: str) -> datetime:
        """Extract timestamp from backup filename.

        Pattern: daily_mydumper_{target}_{ts}_{Day}_{dbN}.tar
        The target can contain underscores, so we use regex to extract ts.
        """
        filename = key.rsplit("/", 1)[-1]
        match = BACKUP_FILENAME_REGEX.match(filename)
        if not match:
            raise ValueError(f"Filename doesn't match pattern: {filename}")
        ts_part = match.group("ts")
        return datetime.strptime(ts_part, "%Y-%m-%dT%H-%M-%SZ")

    sorted_keys = sorted(matching_keys, key=_extract_ts)
    newest = sorted_keys[-1]
    assert newest in matching_keys  # sanity
    # Provide diagnostic output for human review (pytest -vv shows stdout)
    print(
        "Discovered {count} staging backups; newest={newest}".format(
            count=len(matching_keys), newest=newest.rsplit("/", 1)[-1]
        )
    )
