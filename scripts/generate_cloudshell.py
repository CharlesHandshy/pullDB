#!/usr/bin/env python3
"""Generate reviewable CloudShell helper scripts for pullDB.

Writes three example shell scripts and a README into docs/generated/.
All generated scripts are templates only (commented/echo aws-cli lines).
This script never executes AWS commands.
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "docs" / "generated"
GENERATED.mkdir(parents=True, exist_ok=True)


def ask(prompt: str, default: str | None = None) -> str:
    """Prompt for input with optional default value."""
    if default is not None:
        resp = input(f"{prompt} [{default}]: ")
        return resp.strip() or default
    return input(f"{prompt}: ").strip()


def yesno(prompt: str, default: bool = True) -> bool:
    """Ask a yes/no question and return boolean."""
    hint = "Y/n" if default else "y/N"
    r = input(f"{prompt} ({hint}): ")
    if not r:
        return default
    return r.lower().startswith("y")


def _jq_export_line(cred_key: str) -> str:
    """Return a commented export line for credential extraction."""
    mapping = {
        "AWS_ACCESS_KEY_ID": "AccessKeyId",
        "AWS_SECRET_ACCESS_KEY": "SecretAccessKey",
        "AWS_SESSION_TOKEN": "SessionToken",
    }
    fld = mapping.get(cred_key, cred_key)
    cmd = f"echo \"$ASSUME_RESPONSE\" | jq -r '.Credentials.{fld}'"
    return f"# export {cred_key}=$({cmd})"


def _generate_dev(ctx: dict[str, Any], out: Path) -> Path:
    """Generate dev helper script."""
    p = out / f"cloudshell-dev-{ctx['timestamp']}.sh"
    secret_cmd = (
        f"aws secretsmanager get-secret-value --secret-id {ctx['coordination_secret']}"
    )
    lines = [
        "#!/usr/bin/env bash",
        "# Dev helper (review-only)",
        "set -euo pipefail",
        f'echo "Using AWS profile: {ctx["aws_profile"]}"',
        f"# export AWS_PROFILE={ctx['aws_profile']}",
        "# aws sts get-caller-identity",
        f"# {secret_cmd}",
    ]
    p.write_text("\n".join(lines) + "\n")
    p.chmod(0o750)
    return p


def _generate_staging(ctx: dict[str, Any], out: Path) -> Path:
    """Generate staging helper script."""
    p = out / f"cloudshell-staging-{ctx['timestamp']}.sh"
    s3 = f"s3://{ctx['staging_bucket']}/{ctx['staging_prefix']}"
    lines = [
        "#!/usr/bin/env bash",
        "# Staging helper (review-only)",
        "set -euo pipefail",
        f'echo "Listing staging backups in {s3}"',
        f"# aws s3 ls {s3} --no-sign-request || aws s3 ls {s3}",
        '# echo "aws sts assume-role --role-arn <ROLE> --external-id <EXT>"',
    ]
    p.write_text("\n".join(lines) + "\n")
    p.chmod(0o750)
    return p


def _generate_prod(ctx: dict[str, Any], out: Path) -> Path:
    """Generate production helper script."""
    p = out / f"cloudshell-prod-{ctx['timestamp']}.sh"
    prod_s3 = f"s3://{ctx['prod_bucket']}/{ctx['prod_prefix']}"
    lines = [
        "#!/usr/bin/env bash",
        "# Prod helper (review-only)",
        "set -euo pipefail",
        "# ASSUME_RESPONSE=$(aws sts assume-role --role-arn <ROLE> "
        "--external-id <EXT>)",
        _jq_export_line("AWS_ACCESS_KEY_ID"),
        _jq_export_line("AWS_SECRET_ACCESS_KEY"),
        _jq_export_line("AWS_SESSION_TOKEN"),
        f"# aws s3 ls {prod_s3}",
    ]
    p.write_text("\n".join(lines) + "\n")
    p.chmod(0o750)
    return p


def generate_scripts(ctx: dict[str, Any], out: Path) -> list[Path]:
    """Generate all three helper scripts."""
    return [
        _generate_dev(ctx, out),
        _generate_staging(ctx, out),
        _generate_prod(ctx, out),
    ]


def generate_readme(ctx: dict[str, Any], out: Path, scripts: list[Path]) -> Path:
    """Generate README documenting the generated scripts."""
    r = out / f"cloudshell-setup-{ctx['timestamp']}.md"
    parts = [
        f"# pullDB CloudShell helpers (generated {ctx['timestamp']})\n",
        "These scripts are templates. Inspect and edit before running.",
        "\n## Context\n",
        "```json\n",
        json.dumps(ctx, indent=2),
        "\n```\n",
        "## Scripts\n",
    ]
    for s in scripts:
        parts.append(f"- {s.name}\n")
    parts.append("\nReview scripts before executing in CloudShell.\n")
    r.write_text("\n".join(parts) + "\n")
    return r


def _collect_context(ts: str, non_interactive: bool = False) -> dict[str, Any]:
    """Collect context from user or use defaults."""
    defaults = {
        "development_account": "345321506926",
        "staging_account": "333204494849",
        "production_account": "448509429610",
        "staging_bucket": "pestroutesrdsdbs",
        "staging_prefix": "daily/stg/",
        "prod_bucket": "pestroutes-rds-backup-prod-vpc-us-east-1-s3",
        "prod_prefix": "daily/prod/",
        "aws_profile": "pr-dev",
        "coordination_secret": "/pulldb/mysql/coordination-db",
    }
    if non_interactive:
        external_id = uuid.uuid4().hex
        return {
            "timestamp": ts,
            "aws_profile": defaults["aws_profile"],
            "coordination_secret": defaults["coordination_secret"],
            "staging_bucket": defaults["staging_bucket"],
            "staging_prefix": defaults["staging_prefix"],
            "prod_bucket": defaults["prod_bucket"],
            "prod_prefix": defaults["prod_prefix"],
            "external_id": external_id,
        }
    profile = ask("Local AWS profile", defaults["aws_profile"])
    coord = ask("Coordination secret", defaults["coordination_secret"])
    st_bucket = ask("Staging S3 bucket", defaults["staging_bucket"])
    st_pref = ask("Staging S3 prefix", defaults["staging_prefix"])
    pr_bucket = ask("Prod S3 bucket", defaults["prod_bucket"])
    pr_pref = ask("Prod S3 prefix", defaults["prod_prefix"])
    ext = ask("External ID (leave blank to generate)", "")
    if not ext:
        ext = uuid.uuid4().hex
    return {
        "timestamp": ts,
        "aws_profile": profile,
        "coordination_secret": coord,
        "staging_bucket": st_bucket,
        "staging_prefix": st_pref,
        "prod_bucket": pr_bucket,
        "prod_prefix": pr_pref,
        "external_id": ext,
    }


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate reviewable CloudShell helpers for pullDB"
    )
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="Use defaults non-interactively",
    )
    args = parser.parse_args(argv)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    ctx = _collect_context(ts, non_interactive=args.defaults)
    print(json.dumps(ctx, indent=2))
    if not args.defaults and not yesno("Proceed to generate scripts and README?", True):
        print("Aborted")
        return 2
    scripts = generate_scripts(ctx, GENERATED)
    readme = generate_readme(ctx, GENERATED, scripts)
    print(f"Generated {len(scripts)} scripts and README at {GENERATED}")
    for s in scripts:
        print(" -", s.name)
    print(" -", readme.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
