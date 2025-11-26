# QA Template Post-Restore SQL Scripts

## Purpose

This directory contains SQL scripts executed after QA template database restoration completes.

## Current Status

**No post-restore scripts are currently required for QA templates.**

QA templates are already sanitized production data that serve as a baseline for testing. Unlike customer databases (which contain production PII and credentials), QA templates:
- Are pre-sanitized in production
- Contain no real customer data
- Use safe development credentials
- Have integrations already disabled

## Adding Scripts

If future requirements necessitate post-restore modifications to QA templates:

1. Create files following the naming convention: `NNN.descriptive_purpose.sql`
   - `010.example_modification.sql`
   - `020.another_modification.sql`
   - etc.

2. Files execute in lexicographic order (010, 020, 030...)

3. Each file should:
   - Include header comment explaining purpose
   - Be idempotent (safe to run multiple times)
   - Handle missing tables/columns gracefully

## Reference Implementation

The legacy `pullQA-auth` tool performs no post-restore modifications, simply executing myloader to restore the database as-is from S3 backups.
