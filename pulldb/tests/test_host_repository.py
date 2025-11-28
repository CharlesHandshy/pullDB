"""HostRepository tests.

Covers retrieval by hostname, secrets credential resolution, capacity check.

MANDATE: Uses AWS Secrets Manager for DB login via conftest.py fixtures.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import boto3

from pulldb.domain.models import Job, JobStatus
from pulldb.infra.mysql import HostRepository, JobRepository
from pulldb.infra.secrets import CredentialResolver, MySQLCredentials
from pulldb.tests.test_constants import TEST_USER_CODE, TEST_USER_ID, TEST_USERNAME


class TestHostRepository:
    def _cleanup_host(self, pool: Any, host_id: str, hostname: str) -> None:
        with pool.connection() as conn:
            cursor = conn.cursor()
            # Delete job_events for jobs on this host first (FK constraint)
            cursor.execute(
                (
                    "DELETE je FROM job_events je "
                    "JOIN jobs j ON je.job_id = j.id "
                    "WHERE j.dbhost = %s"
                ),
                (hostname,),
            )
            cursor.execute("DELETE FROM jobs WHERE dbhost = %s", (hostname,))
            cursor.execute("DELETE FROM db_hosts WHERE id = %s", (host_id,))
            conn.commit()
            cursor.close()

    def test_get_host_by_hostname_missing(self, mysql_pool: Any) -> None:
        repo = HostRepository(mysql_pool, CredentialResolver())
        assert repo.get_host_by_hostname("no-such-host") is None

    def test_get_host_by_hostname(self, mysql_pool: Any) -> None:
        host_id = str(uuid.uuid4())
        hostname = f"db-host-{host_id[:8]}"
        credential_ref = "aws-secretsmanager:/pulldb/mysql/test-host"
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                (
                    "INSERT INTO db_hosts (id, hostname, credential_ref, "
                    "max_concurrent_restores, enabled, created_at) VALUES "
                    "(%s,%s,%s,%s,TRUE,UTC_TIMESTAMP(6))"
                ),
                (host_id, hostname, credential_ref, 4),
            )
            conn.commit()
            cursor.close()
        repo = HostRepository(mysql_pool, CredentialResolver())
        host = repo.get_host_by_hostname(hostname)
        assert (
            host is not None
            and host.hostname == hostname
            and host.credential_ref == credential_ref
        )
        self._cleanup_host(mysql_pool, host_id, hostname)

    def test_get_host_credentials_secretsmanager(
        self, mysql_pool: Any, monkeypatch: Any
    ) -> None:
        # Secrets Manager stores host + password only.
        # Username is returned as empty string - caller sets it per-service
        # via PULLDB_API_MYSQL_USER or PULLDB_WORKER_MYSQL_USER.

        class FakeSecretsClient:
            def get_secret_value(self, SecretId: str) -> dict[str, str]:  # noqa: N803
                assert SecretId == "/pulldb/mysql/test-host"
                # Secrets Manager stores host + password only
                # Username is set by caller (API/Worker service)
                secret_json = (
                    '{"password": "secretpass", "host": "db-mysql-cred.example.com"}'
                )
                return {"SecretString": secret_json}

        class FakeSession:
            def __init__(self, profile_name: str | None = None):
                self.profile_name = profile_name

            def client(self, service_name: str) -> FakeSecretsClient:
                assert service_name == "secretsmanager"
                return FakeSecretsClient()

        monkeypatch.setattr(boto3, "Session", FakeSession)

        host_id = str(uuid.uuid4())
        hostname = f"db-cred-{host_id[:8]}"
        credential_ref = "aws-secretsmanager:/pulldb/mysql/test-host"
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                (
                    "INSERT INTO db_hosts (id, hostname, credential_ref, "
                    "max_concurrent_restores, enabled, created_at) VALUES "
                    "(%s,%s,%s,%s,TRUE,UTC_TIMESTAMP(6))"
                ),
                (host_id, hostname, credential_ref, 2),
            )
            conn.commit()
            cursor.close()
        repo = HostRepository(mysql_pool, CredentialResolver(aws_profile="default"))
        creds = repo.get_host_credentials(hostname)
        assert isinstance(creds, MySQLCredentials)
        # Username is empty - caller (API/Worker) sets it from service-specific env var
        assert creds.username == ""
        assert creds.host == "db-mysql-cred.example.com"
        self._cleanup_host(mysql_pool, host_id, hostname)

    def test_check_host_capacity(self, mysql_pool: Any) -> None:
        host_id = str(uuid.uuid4())
        hostname = f"db-cap-{host_id[:8]}"
        credential_ref = "aws-secretsmanager:/pulldb/mysql/test-host"
        with mysql_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                (
                    "INSERT INTO db_hosts (id, hostname, credential_ref, "
                    "max_concurrent_restores, enabled, created_at) VALUES "
                    "(%s,%s,%s,%s,TRUE,UTC_TIMESTAMP(6))"
                ),
                (host_id, hostname, credential_ref, 1),
            )
            conn.commit()
            cursor.close()
        job_repo = JobRepository(mysql_pool)
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            owner_user_id=TEST_USER_ID,
            owner_username=TEST_USERNAME,
            owner_user_code=TEST_USER_CODE,
            target=f"target_{job_id[:6]}",
            staging_name=f"target_{job_id[:6]}_{job_id[:12]}",
            dbhost=hostname,
            status=JobStatus.QUEUED,
            submitted_at=datetime.now(UTC),
        )
        job_repo.enqueue_job(job)
        job_repo.mark_job_running(job_id)
        host_repo = HostRepository(mysql_pool, CredentialResolver())
        assert host_repo.check_host_capacity(hostname) is False
        self._cleanup_host(mysql_pool, host_id, hostname)
