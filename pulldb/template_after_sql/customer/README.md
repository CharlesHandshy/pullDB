# Customer Post-Restore SQL Scripts

## Purpose

This directory contains SQL scripts executed after customer database restoration completes. These scripts sanitize restored production data for safe use in development/staging environments.

## Script Naming Convention

Scripts are executed in lexicographic order. Use the naming pattern:

```
NNN.descriptive_purpose.sql
```

Examples:
- `010.remove_customer_pii.sql` - Runs first
- `020.remove_billto_info.sql` - Runs second
- `030.remove_additional_contacts.sql` - Runs third

## Current Scripts

| Script | Purpose |
|--------|---------|
| `010.remove_customer_pii.sql` | Remove customer personal information (names, emails, phones) |
| `020.remove_billto_info.sql` | Clear billing contact details |
| `030.remove_additional_contacts.sql` | Remove additional customer contacts |
| `040.remove_employee_info.sql` | Clear employee personal data |
| `050.remove_payment_credentials.sql` | Remove payment gateway credentials and tokens |
| `060.disable_trigger_rules.sql` | Disable automated triggers that could send external communications |
| `070.remove_gateways.sql` | Clear payment gateway configurations |
| `080.remove_payment_logs.sql` | Remove payment transaction logs |
| `090.remove_office_hash.sql` | Clear office-specific hash values |
| `100.reset_sendgrid.sql` | Reset SendGrid email integration |
| `110.disable_fleetpro.sql` | Disable FleetPro integrations |
| `120.reset_business_registration.sql` | Reset business registration data |

## Writing New Scripts

1. **Be idempotent** - Scripts may run multiple times; they should produce the same result
2. **Handle missing tables** - Use `IF EXISTS` or error handling for tables that may not exist
3. **Include comments** - Document what data is being modified and why
4. **No external calls** - Scripts should only modify local database data

## Example Script Structure

```sql
-- =============================================================================
-- 130.example_sanitization.sql
-- Purpose: Description of what this script does
-- =============================================================================

-- Update sensitive data in example_table
UPDATE example_table 
SET sensitive_column = 'REDACTED'
WHERE sensitive_column IS NOT NULL;

-- Delete records that shouldn't exist in dev
DELETE FROM sensitive_audit_log
WHERE created_at < DATE_SUB(NOW(), INTERVAL 30 DAY);
```

## Configuration

The directory containing these scripts is configurable via:

```bash
PULLDB_CUSTOMERS_AFTER_SQL_DIR=/opt/pulldb.service/after_sql/customer
```

Scripts are copied from the template directory on initial install. Modify the installed copies to customize behavior for your environment.

## Security Notes

- These scripts run with the same MySQL credentials used for the restore
- All scripts execute within a single transaction when possible
- Failed scripts will cause the restore job to be marked as failed
- Logs are written to the job's log file for audit purposes
