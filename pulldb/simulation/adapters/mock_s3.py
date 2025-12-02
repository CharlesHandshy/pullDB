"""Mock S3 Client for Simulation Mode.

Implements the S3Client protocol using in-memory state.
"""

from __future__ import annotations

import logging
import typing as t
from io import BytesIO

from pulldb.simulation.core.bus import EventType, get_event_bus
from pulldb.simulation.core.state import get_simulation_state

logger = logging.getLogger(__name__)


class MockStreamingBody:
    """Mock for botocore.response.StreamingBody."""

    def __init__(self, content: bytes = b"") -> None:
        """Initialize with content."""
        self._stream = BytesIO(content)

    def read(self, amt: int | None = None) -> bytes:
        """Read bytes from stream."""
        return self._stream.read(amt)

    def close(self) -> None:
        """Close the stream."""
        self._stream.close()


class MockS3Client:
    """In-memory implementation of S3Client."""

    def __init__(self) -> None:
        """Initialize with shared simulation state."""
        self.state = get_simulation_state()
        self._bus = get_event_bus()

    def list_keys(
        self, bucket: str, prefix: str, profile: str | None = None
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
            self._bus.emit(
                EventType.S3_LIST_KEYS,
                source="MockS3Client",
                data={"bucket": bucket, "prefix": prefix, "count": len(sorted_results)},
            )
            return sorted_results

    def head_object(
        self, bucket: str, key: str, profile: str | None = None
    ) -> dict[str, t.Any]:
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
            # Simulate boto3 exception? Or just raise generic for now.
            # The real implementation raises ClientError.
            self._bus.emit(
                EventType.S3_ERROR,
                source="MockS3Client",
                data={"bucket": bucket, "key": key, "error": "key_not_found"},
            )
            raise ValueError(f"Key {key} not found in bucket {bucket}")

    def get_object(
        self, bucket: str, key: str, profile: str | None = None
    ) -> dict[str, t.Any]:
        """Return object (streaming body)."""
        with self.state.lock:
            if bucket in self.state.s3_buckets and key in self.state.s3_buckets[bucket]:
                self._bus.emit(
                    EventType.S3_GET_OBJECT,
                    source="MockS3Client",
                    data={"bucket": bucket, "key": key},
                )
                return {
                    "Body": MockStreamingBody(b"mock content"),
                    "ContentLength": 12,
                    "ContentType": "application/octet-stream",
                }
            self._bus.emit(
                EventType.S3_ERROR,
                source="MockS3Client",
                data={"bucket": bucket, "key": key, "error": "key_not_found"},
            )
            raise ValueError(f"Key {key} not found in bucket {bucket}")

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
