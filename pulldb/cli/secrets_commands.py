"""AWS Secrets Manager CLI commands.

Provides commands to view, create, update, and delete secrets in AWS Secrets Manager.
Supports the pullDB credential format for MySQL connections.

Configuration Hierarchy for Secrets:
    CLI → Web → API (last to update wins)
    Both CLI and Web update the same secrets in AWS Secrets Manager.

Usage:
    pulldb-admin secrets list              # List all /pulldb/* secrets
    pulldb-admin secrets get <secret-id>   # Get secret value
    pulldb-admin secrets set <secret-id>   # Create/update secret
    pulldb-admin secrets delete <secret-id> # Delete secret
    pulldb-admin secrets test <secret-id>  # Test secret connectivity
"""

from __future__ import annotations

import json
import os
import secrets as secrets_module
import string
import sys
import typing as t
from dataclasses import dataclass

import boto3
import click
import mysql.connector
from botocore.exceptions import ClientError

# Constants
PASSWORD_MASK_LENGTH = 4
DEFAULT_PASSWORD_LENGTH = 32
DEFAULT_RECOVERY_DAYS = 7


def _mask_password(password: str) -> str:
    """Mask password showing only last few characters."""
    if len(password) > PASSWORD_MASK_LENGTH:
        return "****" + password[-PASSWORD_MASK_LENGTH:]
    return "****"


def _get_aws_session(profile: str | None = None, region: str | None = None) -> t.Any:
    """Get boto3 session with profile and region."""
    profile = profile or os.getenv("PULLDB_AWS_PROFILE")
    region = region or os.getenv("PULLDB_AWS_REGION", "us-east-1")

    return boto3.Session(profile_name=profile, region_name=region)


def _get_secrets_manager_client(
    profile: str | None = None, region: str | None = None
) -> t.Any:
    """Get Secrets Manager client."""
    session = _get_aws_session(profile, region)
    return session.client("secretsmanager")


@dataclass
class SecretParams:
    """Parameters for creating/updating a secret."""

    secret_id: str
    host: str
    password: str
    port: int
    username: str | None
    description: str | None
    create_only: bool
    update_only: bool


@click.group(name="secrets", help="Manage AWS Secrets Manager credentials")
@click.option(
    "--profile",
    envvar="PULLDB_AWS_PROFILE",
    help="AWS profile to use",
)
@click.option(
    "--region",
    envvar="PULLDB_AWS_REGION",
    default="us-east-1",
    help="AWS region",
)
@click.pass_context
def secrets_group(ctx: click.Context, profile: str | None, region: str) -> None:
    """Secrets management command group."""
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile
    ctx.obj["region"] = region


@secrets_group.command("list")
@click.option(
    "--prefix",
    default="/pulldb/",
    show_default=True,
    help="Secret name prefix to filter",
)
@click.option("--json", "json_out", is_flag=True, help="Output as JSON")
@click.pass_context
def list_secrets(ctx: click.Context, prefix: str, json_out: bool) -> None:
    """List all secrets with the given prefix.

    By default lists all /pulldb/* secrets.
    """
    client = _get_secrets_manager_client(ctx.obj["profile"], ctx.obj["region"])

    try:
        secrets: list[dict[str, t.Any]] = []
        paginator = client.get_paginator("list_secrets")

        for page in paginator.paginate(
            Filters=[{"Key": "name", "Values": [prefix]}],
            SortOrder="asc",
        ):
            for secret in page.get("SecretList", []):
                secrets.append(
                    {
                        "name": secret["Name"],
                        "description": secret.get("Description", ""),
                        "created": secret.get("CreatedDate", "").isoformat()
                        if secret.get("CreatedDate")
                        else "",
                        "updated": secret.get("LastChangedDate", "").isoformat()
                        if secret.get("LastChangedDate")
                        else "",
                    }
                )

        if json_out:
            click.echo(json.dumps(secrets, indent=2))
            return

        if not secrets:
            click.echo(f"No secrets found with prefix '{prefix}'")
            click.echo(f"\nTo create: pulldb-admin secrets set {prefix}mysql/myhost")
            return

        # Table output
        click.echo(f"Secrets with prefix '{prefix}':\n")
        name_width = max(len(s["name"]) for s in secrets)
        click.echo(f"{'NAME':<{name_width}}  {'UPDATED':<20}  DESCRIPTION")
        click.echo(f"{'-' * name_width}  {'-' * 20}  {'-' * 30}")

        for secret in secrets:
            updated = secret["updated"][:19] if secret["updated"] else "(unknown)"
            desc = secret["description"][:30] if secret["description"] else ""
            click.echo(f"{secret['name']:<{name_width}}  {updated:<20}  {desc}")

        click.echo(f"\n{len(secrets)} secret(s) found.")

    except ClientError as e:
        raise click.ClickException(f"AWS error: {e}") from e


@secrets_group.command("get")
@click.argument("secret_id")
@click.option("--json", "json_out", is_flag=True, help="Output raw JSON")
@click.option("--show-password", is_flag=True, help="Show password in plain text")
@click.pass_context
def get_secret(
    ctx: click.Context, secret_id: str, json_out: bool, show_password: bool
) -> None:
    """Get a secret's value.

    SECRET_ID is the secret name (e.g., /pulldb/mysql/coordination-db)
    """
    client = _get_secrets_manager_client(ctx.obj["profile"], ctx.obj["region"])

    try:
        response = client.get_secret_value(SecretId=secret_id)
        secret_string = response["SecretString"]

        if json_out:
            click.echo(secret_string)
            return

        # Parse and display
        try:
            secret_data = json.loads(secret_string)
        except json.JSONDecodeError:
            click.echo(f"Secret '{secret_id}' (raw string):")
            click.echo(secret_string)
            return

        click.echo(f"Secret: {secret_id}")
        click.echo(f"ARN: {response.get('ARN', '(unknown)')}")
        click.echo("")
        click.echo("Values:")

        for key, value in secret_data.items():
            if key == "password" and not show_password:
                display_value = _mask_password(str(value))
            else:
                display_value = str(value)
            click.echo(f"  {key}: {display_value}")

        if not show_password and "password" in secret_data:
            click.echo("\n(Use --show-password to reveal full password)")

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        if error_code == "ResourceNotFoundException":
            raise click.ClickException(f"Secret not found: {secret_id}") from e
        if error_code == "AccessDeniedException":
            raise click.ClickException(
                f"Access denied to secret: {secret_id}. "
                "Check IAM permissions for secretsmanager:GetSecretValue."
            ) from e
        raise click.ClickException(f"AWS error: {e}") from e


def _process_set_secret(ctx: click.Context, params: SecretParams) -> None:
    """Process the set_secret command logic."""
    # Handle password from stdin
    password = params.password
    if password == "-":
        password = sys.stdin.read().strip()
        if not password:
            raise click.ClickException("No password provided via stdin")

    # Build secret value
    secret_data: dict[str, t.Any] = {
        "host": params.host,
        "password": password,
        "port": params.port,
    }
    if params.username:
        secret_data["username"] = params.username

    secret_string = json.dumps(secret_data)

    client = _get_secrets_manager_client(ctx.obj["profile"], ctx.obj["region"])

    # Check if secret exists
    exists = True
    try:
        client.describe_secret(SecretId=params.secret_id)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            exists = False
        else:
            raise

    if params.create_only and exists:
        raise click.ClickException(
            f"Secret '{params.secret_id}' already exists. Use --update to modify."
        )
    if params.update_only and not exists:
        raise click.ClickException(
            f"Secret '{params.secret_id}' does not exist. Remove --update to create."
        )

    if exists:
        # Update existing secret
        client.put_secret_value(SecretId=params.secret_id, SecretString=secret_string)
        click.echo(f"✓ Updated secret: {params.secret_id}")
    else:
        # Create new secret
        create_args: dict[str, t.Any] = {
            "Name": params.secret_id,
            "SecretString": secret_string,
        }
        if params.description:
            create_args["Description"] = params.description

        response = client.create_secret(**create_args)
        click.echo(f"✓ Created secret: {params.secret_id}")
        click.echo(f"  ARN: {response['ARN']}")

    click.echo("")
    click.echo("Secret contents:")
    click.echo(f"  host: {params.host}")
    click.echo(f"  port: {params.port}")
    if params.username:
        click.echo(f"  username: {params.username}")
    click.echo(f"  password: {_mask_password(password)}")


@secrets_group.command("set")
@click.argument("secret_id")
@click.option("--host", required=True, help="MySQL host")
@click.option("--password", required=True, help="MySQL password (use - for stdin)")
@click.option("--port", type=int, default=3306, help="MySQL port")
@click.option("--username", help="MySQL username (optional)")
@click.option("--description", "-d", help="Secret description")
@click.option("--create", "create_only", is_flag=True, help="Create only (error if exists)")
@click.option("--update", "update_only", is_flag=True, help="Update only (error if not exists)")
@click.pass_context
def set_secret(
    ctx: click.Context,
    secret_id: str,
    host: str,
    password: str,
    port: int,
    username: str | None,
    description: str | None,
    create_only: bool,
    update_only: bool,
) -> None:
    """Create or update a secret.

    SECRET_ID is the secret name (e.g., /pulldb/mysql/coordination-db)

    The secret will contain:
      - host: MySQL server hostname
      - password: MySQL password
      - port: MySQL port (optional)
      - username: MySQL username (optional)

    Examples:
        pulldb-admin secrets set /pulldb/mysql/prod-db --host=mysql.example.com --password=secret123
        echo "mypassword" | pulldb-admin secrets set /pulldb/mysql/prod-db --host=mysql.example.com --password=-
    """
    if create_only and update_only:
        raise click.ClickException("Cannot specify both --create and --update")

    try:
        params = SecretParams(
            secret_id=secret_id,
            host=host,
            password=password,
            port=port,
            username=username,
            description=description,
            create_only=create_only,
            update_only=update_only,
        )
        _process_set_secret(ctx, params)

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        if error_code == "AccessDeniedException":
            raise click.ClickException(
                "Access denied. Check IAM permissions for "
                "secretsmanager:CreateSecret and secretsmanager:PutSecretValue."
            ) from e
        raise click.ClickException(f"AWS error: {e}") from e


@secrets_group.command("delete")
@click.argument("secret_id")
@click.option(
    "--force",
    is_flag=True,
    help="Immediately delete (no recovery window)",
)
@click.option(
    "--recovery-days",
    type=int,
    default=DEFAULT_RECOVERY_DAYS,
    help="Recovery window in days (7-30)",
)
@click.confirmation_option(prompt="Are you sure you want to delete this secret?")
@click.pass_context
def delete_secret(
    ctx: click.Context,
    secret_id: str,
    force: bool,
    recovery_days: int,
) -> None:
    """Delete a secret.

    SECRET_ID is the secret name (e.g., /pulldb/mysql/old-db)

    By default, secrets are scheduled for deletion with a recovery window.
    Use --force for immediate deletion (no recovery).
    """
    client = _get_secrets_manager_client(ctx.obj["profile"], ctx.obj["region"])

    try:
        delete_args: dict[str, t.Any] = {"SecretId": secret_id}

        if force:
            delete_args["ForceDeleteWithoutRecovery"] = True
            click.echo(f"⚠ Immediately deleting secret: {secret_id}")
        else:
            delete_args["RecoveryWindowInDays"] = recovery_days
            click.echo(f"Scheduling secret for deletion: {secret_id}")
            click.echo(f"Recovery window: {recovery_days} days")

        response = client.delete_secret(**delete_args)

        if force:
            click.echo("✓ Secret deleted immediately")
        else:
            deletion_date = response.get("DeletionDate", "")
            click.echo(f"✓ Secret scheduled for deletion on: {deletion_date}")
            click.echo(
                "\nTo cancel: aws secretsmanager restore-secret "
                f"--secret-id {secret_id}"
            )

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        if error_code == "ResourceNotFoundException":
            raise click.ClickException(f"Secret not found: {secret_id}") from e
        raise click.ClickException(f"AWS error: {e}") from e


@secrets_group.command("test")
@click.argument("secret_id")
@click.option("--username", help="MySQL username to test with")
@click.option("--database", default="information_schema", help="Database to connect to")
@click.pass_context
def test_secret(
    ctx: click.Context,
    secret_id: str,
    username: str | None,
    database: str,
) -> None:
    """Test MySQL connectivity using a secret.

    SECRET_ID is the secret name (e.g., /pulldb/mysql/coordination-db)

    Tests that the credentials in the secret can connect to MySQL.
    """
    client = _get_secrets_manager_client(ctx.obj["profile"], ctx.obj["region"])

    # Get secret
    try:
        click.echo(f"Fetching secret: {secret_id}")
        response = client.get_secret_value(SecretId=secret_id)
        secret_data = json.loads(response["SecretString"])
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        if error_code == "ResourceNotFoundException":
            raise click.ClickException(f"Secret not found: {secret_id}") from e
        raise click.ClickException(f"AWS error: {e}") from e

    host = secret_data.get("host")
    password = secret_data.get("password")
    port = secret_data.get("port", 3306)
    secret_username = secret_data.get("username")

    # Use provided username or fall back to secret username
    test_username = username or secret_username
    if not test_username:
        raise click.ClickException(
            "No username in secret and --username not provided. "
            "Use --username to specify a MySQL user."
        )

    click.echo(f"Testing connection to {host}:{port} as {test_username}...")

    # Test MySQL connection
    try:
        conn = mysql.connector.connect(
            host=host,
            port=port,
            user=test_username,
            password=password,
            database=database,
            connect_timeout=10,
        )

        cursor = conn.cursor()
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()[0]
        cursor.close()
        conn.close()

        click.echo("✓ Connection successful!")
        click.echo(f"  MySQL version: {version}")

    except Exception as e:
        click.echo(f"✗ Connection failed: {e}")
        raise click.ClickException("MySQL connection test failed") from e


@secrets_group.command("rotate-host")
@click.argument("hostname")
@click.option("--new-password", help="New password (generates random if not provided)")
@click.option(
    "--length",
    type=int,
    default=DEFAULT_PASSWORD_LENGTH,
    help="Generated password length (16-64)",
)
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    help="Output JSON instead of formatted text",
)
@click.confirmation_option(prompt="Rotate host credentials? This will update MySQL and AWS.")
def rotate_host_secret(
    hostname: str,
    new_password: str | None,
    length: int,
    json_out: bool,
) -> None:
    """Safely rotate credentials for a database host.

    HOSTNAME is the database host identifier (short name, hostname, or host_id).

    This performs ATOMIC credential rotation:

    \b
    1. Fetch current credentials from AWS Secrets Manager
    2. Validate current credentials work on MySQL
    3. Verify user has ALTER USER privilege
    4. Generate or use provided new password
    5. Update MySQL user password (ALTER USER)
    6. Verify new password works on MySQL
    7. Update AWS Secrets Manager
    8. Final round-trip verification (AWS → MySQL)

    If step 5-6 succeeds but step 7 fails, provides manual fix instructions.
    Includes automatic rollback if verification fails after MySQL update.

    \b
    Examples:
        pulldb-admin secrets rotate-host mydb        # By short name
        pulldb-admin secrets rotate-host db.example.com  # By hostname
        pulldb-admin secrets rotate-host --length 48 mydb  # Custom length
    """
    from pulldb.domain.services.secret_rotation import rotate_host_secret as do_rotation
    from pulldb.infra.factory import get_host_repository

    # Look up host by alias, hostname, or id
    repo = get_host_repository()
    host = None

    # Try by alias first (most common usage)
    host = repo.get_host_by_alias(hostname)

    # Try by hostname
    if not host:
        host = repo.get_host_by_hostname(hostname)

    # Try by host_id (if available)
    if not host and hasattr(repo, "get_host_by_id"):
        host = repo.get_host_by_id(hostname)

    if not host:
        raise click.ClickException(
            f"Host not found: {hostname}\n"
            f"Use 'pulldb-admin hosts list' to see available hosts."
        )

    if not host.credential_ref:
        raise click.ClickException(
            f"Host {host.host_alias or host.hostname} does not have a credential reference configured.\n"
            "Configure credentials in Admin → Hosts → Edit Host."
        )

    if not host.credential_ref.startswith("aws-secretsmanager:"):
        raise click.ClickException(
            f"Host {host.host_alias or host.hostname} credential reference is not AWS Secrets Manager.\n"
            f"  Current: {host.credential_ref}\n"
            "Only aws-secretsmanager:// references are supported for rotation."
        )

    click.echo(f"Rotating credentials for host: {click.style(host.host_alias or host.hostname, fg='cyan', bold=True)}")
    click.echo(f"  Hostname: {host.hostname}")
    click.echo(f"  Credential ref: {host.credential_ref}")
    click.echo("")

    # Execute rotation
    result = do_rotation(
        host_id=host.id,
        hostname=host.hostname,
        credential_ref=host.credential_ref,
        new_password=new_password,
        password_length=length,
    )

    if json_out:
        import json as json_module
        output = {
            "success": result.success,
            "message": result.message,
            "error": result.error,
            "phase": result.phase,
            "suggestions": result.suggestions,
            "manual_fix_required": result.manual_fix_required,
            "timing": result.timing,
        }
        click.echo(json_module.dumps(output, indent=2))
        if not result.success:
            raise SystemExit(1)
        return

    if result.success:
        click.echo(click.style("✓ Credentials rotated successfully!", fg="green", bold=True))
        click.echo("")
        click.echo("Rotation phases completed:")
        for phase, duration in (result.timing or {}).items():
            click.echo(f"  ✓ {phase}: {duration:.2f}s")
    else:
        click.echo(click.style("✗ Rotation failed!", fg="red", bold=True))
        click.echo(f"  Phase: {result.phase}")
        click.echo(f"  Error: {result.error}")

        if result.suggestions:
            click.echo("")
            click.echo(click.style("Suggestions:", fg="yellow"))
            for suggestion in result.suggestions:
                click.echo(f"  • {suggestion}")

        if result.manual_fix_required and result.manual_fix_instructions:
            click.echo("")
            click.echo(click.style("⚠ MANUAL FIX REQUIRED:", fg="red", bold=True))
            click.echo(result.manual_fix_instructions)

        raise SystemExit(1)
