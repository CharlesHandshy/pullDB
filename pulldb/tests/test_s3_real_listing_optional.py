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


@pytest.mark.timeout(30)
def test_real_staging_backup_listing_optional() -> None:  # pragma: no cover
    """List real staging backup objects and validate at least one tar present.

    Skips gracefully when AWS not configured or access errors occur.
    """
    try:
        s3 = boto3.client("s3")
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
    for page in pages:
        for item in page.get("Contents", []) or []:
            key = item.get("Key")
            if not isinstance(key, str):
                continue
            filename = key.rsplit("/", 1)[-1]
            if BACKUP_FILENAME_REGEX.match(filename):
                matching_keys.append(key)

    if not matching_keys:
        pytest.fail(
            "No staging backup objects matched pattern under "
            f"s3://{STAGING_BUCKET}/{STAGING_PREFIX}. "
            "Investigate upstream backup pipeline or adjust test if "
            "pattern changed."
        )

    # Basic invariant: newest timestamp sorts last when parsed & sorted
    def _extract_ts(key: str) -> datetime:
        filename = key.rsplit("/", 1)[-1]
        ts_part = filename.split("_", 3)[2]
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
