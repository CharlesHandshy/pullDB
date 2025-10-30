"""S3 client wrapper placeholder.

Will implement backup discovery & download in Milestone 5.
"""
from __future__ import annotations

import boto3


class S3Client:
    def __init__(self, profile: str | None = None) -> None:
        session = boto3.session.Session(profile_name=profile) if profile else boto3.session.Session()
        self._s3 = session.client("s3")

    def list_keys(self, bucket: str, prefix: str) -> list[str]:  # pragma: no cover - placeholder
        resp = self._s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        contents = resp.get("Contents", [])
        return [c["Key"] for c in contents]
