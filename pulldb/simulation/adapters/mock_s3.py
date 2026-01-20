"""Mock S3 Client for Simulation Mode.

Implements the S3Client protocol using in-memory state.

HCA Layer: shared
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any
from io import BytesIO

from pulldb.simulation.core.bus import EventType, get_event_bus
from pulldb.simulation.core.state import get_simulation_state

logger = logging.getLogger(__name__)


class S3Error(Exception):
    """Mock exception that mimics boto3 ClientError structure."""
    
    def __init__(self, error_code: str, message: str, operation: str = "Unknown") -> None:
        self.response = {
            "Error": {
                "Code": error_code,
                "Message": message,
            },
            "ResponseMetadata": {
                "HTTPStatusCode": 404 if error_code == "404" else 500,
            },
        }
        self.operation_name = operation
        super().__init__(f"An error occurred ({error_code}) when calling the {operation} operation: {message}")


class MockStreamingBody:
    """Mock for botocore.response.StreamingBody."""

    def __init__(self, content: bytes = b"") -> None:
        """Initialize with content."""
        self._stream = BytesIO(content)
        self._content = content

    def read(self, amt: int | None = None) -> bytes:
        """Read bytes from stream."""
        return self._stream.read(amt)

    def close(self) -> None:
        """Close the stream."""
        self._stream.close()

    def iter_lines(self, chunk_size: int = 1024) -> Iterator[bytes]:
        """Iterate over lines in the stream."""
        for line in self._content.splitlines():
            yield line

    def iter_chunks(self, chunk_size: int = 1024) -> Iterator[bytes]:
        """Iterate over chunks of the stream."""
        self._stream.seek(0)
        while True:
            chunk = self._stream.read(chunk_size)
            if not chunk:
                break
            yield chunk


class MockS3Client:
    """In-memory implementation of S3Client."""

    def __init__(self) -> None:
        """Initialize with shared simulation state."""
        self.state = get_simulation_state()
        self._bus = get_event_bus()

    def list_keys(
        self,
        bucket: str,
        prefix: str,
        profile: str | None = None,
        max_keys: int | None = None,
    ) -> list[str]:
        """Return keys under prefix (non recursive)."""
        with self.state.lock:
            keys = self.state.s3_buckets.get(bucket, [])

            # Filter by prefix
            matches = [k for k in keys if k.startswith(prefix)]

            # Simulate non-recursive listing (like CommonPrefixes)
            # If prefix is "backups/", and we have "backups/db1/full.xbstream",
            # we should return "backups/db1/" if we are simulating "directories".

            results: set[str] = set()
            prefix_len = len(prefix)

            for key in matches:
                suffix = key[prefix_len:]
                if "/" in suffix:
                    # It's a "subdirectory"
                    subdir = suffix.split("/", 1)[0] + "/"
                    results.add(prefix + subdir)
                else:
                    # It's a file at this level
                    results.add(key)

            sorted_results = sorted(results)
            # Apply max_keys limit if specified
            if max_keys is not None:
                sorted_results = sorted_results[:max_keys]
            self._bus.emit(
                EventType.S3_LIST_KEYS,
                source="MockS3Client",
                data={"bucket": bucket, "prefix": prefix, "count": len(sorted_results)},
            )
            return sorted_results

    def head_object(
        self, bucket: str, key: str, profile: str | None = None
    ) -> dict[str, Any]:
        """Return object metadata (HEAD)."""
        with self.state.lock:
            if bucket in self.state.s3_buckets and key in self.state.s3_buckets[bucket]:
                # Return mock metadata
                metadata = {
                    "ContentLength": 1024 * 1024 * 100,  # 100MB mock size
                    "ContentType": "application/octet-stream",
                    "LastModified": "2023-01-01T00:00:00Z",
                }
                self._bus.emit(
                    EventType.S3_HEAD_OBJECT,
                    source="MockS3Client",
                    data={"bucket": bucket, "key": key, "found": True},
                )
                return metadata
            # Raise S3Error that mimics boto3 ClientError structure
            self._bus.emit(
                EventType.S3_ERROR,
                source="MockS3Client",
                data={"bucket": bucket, "key": key, "error": "key_not_found"},
            )
            raise S3Error("404", f"Key {key} not found in bucket {bucket}", "HeadObject")

    def get_object(
        self, bucket: str, key: str, profile: str | None = None
    ) -> dict[str, Any]:
        """Return object (streaming body).
        
        Returns unique content per key for more realistic simulation.
        """
        with self.state.lock:
            if bucket in self.state.s3_buckets and key in self.state.s3_buckets[bucket]:
                self._bus.emit(
                    EventType.S3_GET_OBJECT,
                    source="MockS3Client",
                    data={"bucket": bucket, "key": key},
                )
                # Generate unique content based on key for more realistic simulation
                content = f"mock content for {bucket}/{key}".encode()
                return {
                    "Body": MockStreamingBody(content),
                    "ContentLength": len(content),
                    "ContentType": "application/octet-stream",
                }
            self._bus.emit(
                EventType.S3_ERROR,
                source="MockS3Client",
                data={"bucket": bucket, "key": key, "error": "key_not_found"},
            )
            raise S3Error("404", f"Key {key} not found in bucket {bucket}", "GetObject")

    def load_fixtures(self, bucket: str, keys: list[str]) -> None:
        """Load mock keys into a bucket."""
        with self.state.lock:
            if bucket not in self.state.s3_buckets:
                self.state.s3_buckets[bucket] = []

            # Add unique keys
            current = set(self.state.s3_buckets[bucket])
            for k in keys:
                if k not in current:
                    self.state.s3_buckets[bucket].append(k)
                    current.add(k)
