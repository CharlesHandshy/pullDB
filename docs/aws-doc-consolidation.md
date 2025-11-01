# AWS Documentation Consolidation Summary (2025-11-01)

## Overview
All fragmented AWS setup guides have been consolidated. The project now has **one canonical authentication document** plus focused implementation guides for credential storage. This summary maps obsolete files to their replacements and captures rationale.

## Canonical & Active Docs
| Category | Active File | Purpose |
|----------|-------------|---------|
| Authentication & Roles | `aws-authentication-setup.md` | Full architecture: instance profile, cross-account roles, bucket/KMS access, profile config |
| Secrets (MySQL credentials) | `aws-secrets-manager-setup.md` | Creation, IAM policy additions, rotation, resolver integration |
| Parameter Store (non-secret config) | `parameter-store-setup.md` | Using SSM for configuration values (not test DB auth) |
| EC2 Deployment | `aws-ec2-deployment-setup.md` | Instance provisioning & service deployment |
| High-Level Recap | `SECRETS-MANAGER-SUMMARY.md` | Quick reference (keep minimal; defer to detailed guides) |

## Obsolete Files
| Obsolete File | Status | Replacement |
|---------------|--------|------------|
| `aws-setup.md.OBSOLETE` | Deprecated | `aws-authentication-setup.md` |
| `aws-service-role-setup.md.OBSOLETE` | Deprecated | `aws-authentication-setup.md` (Development Account Setup) |
| `aws-cross-account-setup.md.OBSOLETE` | Deprecated | `aws-authentication-setup.md` (Staging + Production Sections) |
| `aws-iam-setup.md.OBSOLETE` | Deprecated | `aws-authentication-setup.md` (IAM policies & trust) |

## Key Changes
- Removed duplicated IAM policy examples; single permission matrix lives in canonical guide.
- Standardized AWS profile names: `pr-staging` (primary prototype), `pr-prod` (production). Previous `pr-dev` references deprecated.
- Mandated test DB credential resolution via Secrets Manager secret: `/pulldb/mysql/coordination-db`.
- Added banners to active guides clarifying scope & canonical precedence.
- README updated to staging-first profile recommendation and test secret mandate.

## Contributor Guidance
1. Add new AWS-related content ONLY to `aws-authentication-setup.md` unless it is narrowly about storing/retrieving credentials (then update `aws-secrets-manager-setup.md`).
2. Do not resurrect obsolete guides; remove any lingering links pointing to `.OBSOLETE` files when encountered.
3. Keep profile naming consistent; avoid introducing additional profile labels unless documented here.
4. Integration tests failing due to secret access should reference IAM policy sections in `aws-authentication-setup.md`.

## Pending / Follow-Up
- Verify CI pipeline references (if any) align with `pr-staging` when running test suite.
- Remove any local developer scripts that still suggest `aws-cross-account-setup.md` or `aws-setup.md` (none identified yet).
- Audit `SECRETS-MANAGER-SUMMARY.md` for redundant architecture description; trim if necessary.

## Rationale for Consolidation
- Prevent documentation drift leading to inconsistent IAM grant patterns.
- Improve onboarding time—single source eliminates decision paralysis.
- Enforce security mandates (Secrets Manager test auth, external ID usage) uniformly.
- Simplify maintenance—future changes applied once.

## How to Update This Summary
When deprecating or adding an AWS document:
1. Edit the Active/Obsolete tables.
2. Add a changelog bullet under Key Changes with date.
3. Ensure banners added/updated in affected documents.

---
Last Updated: 2025-11-01
