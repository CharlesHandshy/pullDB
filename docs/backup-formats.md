# Backup Format Compatibility

## Overview

pullDB must support multiple mydumper backup formats due to different environments being at different stages of the mydumper migration:

| Environment | Account ID | Older Format | Newer Format | Notes |
|------------|------------|--------------|--------------|-------|
| **Staging** | `333204494849` | ✅ Available | ✅ Available | **Use for development** - has both formats |
| **Production** | `448509429610` | ✅ Current | ❌ Future | Will migrate after pullDB is complete |

**Development Strategy**: Use **staging account** for development and testing since it contains both backup formats. This allows testing multi-format support without requiring production access.

## Development Environment Access

The development environment (`345321506926`) requires cross-account access to backups from **both** staging and production:

```
Dev Account (345321506926)
├── Read Access → Staging S3 (333204494849) [PRIMARY FOR DEVELOPMENT]
│   └── Bucket: pestroutesrdsdbs
│       └── Path: daily/stg/
│       └── Formats: Both older AND newer mydumper (for testing)
│
└── Read Access → Production S3 (448509429610) [FUTURE]
    └── Bucket: pestroutes-rds-backup-prod-vpc-us-east-1-s3
        └── Path: daily/prod/
        └── Format: Older mydumper (transitioning to newer)
```

**Prototype Development**: Configure cross-account access to **staging account first**. This provides access to both backup formats needed for development and testing.

## Format Differences

**Status**: Format specifications are TBD and will be documented during implementation.

### Older mydumper Format

- **Used by**: Production account (current), Staging account (available for testing)
- **Characteristics**: TBD
- **myloader Command**: TBD
- **Restore Flags**: TBD

### Newer mydumper Format

- **Used by**: Staging account (current and for testing), Production account (future)
- **Characteristics**: TBD
- **myloader Command**: TBD
- **Restore Flags**: TBD

## Implementation Strategy (Deferred)

See `design/roadmap.md` for detailed deferred feature documentation.

### Phase 1: Single Format Support (Prototype)

Start with single format using **staging account** (TBD which format to start with):
- Configure cross-account access to staging S3 bucket
- Focus on core restore workflow
- Validate daemon architecture
- Test MySQL coordination layer
- Prove staging database rename pattern
- Both formats available in staging for initial testing

### Phase 2: Multi-Format Support (Pre-Production)

Add format detection and dual support:
1. **Format Detection**: Analyze backup archive structure to identify format
2. **Strategy Selection**: Choose appropriate myloader binary/flags
3. **Validation**: Ensure successful restore regardless of format
4. **Testing**: Integration tests with sample backups from both formats

## Configuration (Future)

When multi-format support is implemented:

```bash
# Use staging backups (newer format)
pulldb user=jdoe customer=acme source=staging

# Use production backups (older format, then newer after migration)
pulldb user=jdoe customer=acme source=production
```

Environment variables:
```bash
# S3 URIs - Use staging for development (has both formats)
PULLDB_S3_BUCKET_PATH=s3://pestroutesrdsdbs/daily/stg/  # Development/Testing (has both formats)
# PULLDB_S3_BUCKET_PATH=s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/  # Production (future)
PULLDB_S3_STAGING_BUCKET_PATH=s3://pestroutesrdsdbs/daily/stg/

# Default to staging for development
PULLDB_BACKUP_SOURCE=staging  # Use staging for development/testing
```

AWS profiles (canonical staging-first pattern; see `aws-authentication-setup.md`):
```ini
[profile pr-staging]
role_arn = arn:aws:iam::333204494849:role/pulldb-cross-account-readonly
credential_source = Ec2InstanceMetadata
external_id = pulldb-dev-access-2025
region = us-east-1

[profile pr-prod]
role_arn = arn:aws:iam::448509429610:role/pulldb-cross-account-readonly
credential_source = Ec2InstanceMetadata
external_id = pulldb-dev-access-2025
region = us-east-1
```

**For Development**: Configure `pr-staging` profile first. Staging account has both backup formats available for testing.

## Testing Requirements

Before production deployment, must verify:

- [ ] Successful restore from older mydumper format (production backups)
- [ ] Successful restore from newer mydumper format (staging backups)
- [ ] Format detection works reliably
- [ ] Post-restore SQL scripts execute correctly for both formats
- [ ] Staging database rename pattern works with both formats
- [ ] Integration tests cover both formats

## Migration Path

When production migrates to newer mydumper format:

1. **Pre-Migration**: pullDB supports both formats, tested with production's older format
2. **Migration**: Production account updates backup process to newer format
3. **Post-Migration**: pullDB continues to work, now using newer format for production
4. **Cleanup**: After migration period, older format support can be deprecated (future decision)

## Open Questions

- [ ] What are the specific structural differences between formats?
- [ ] Do we need different myloader binaries or just different flags?
- [ ] How do we detect format from archive without full extraction?
- [ ] Should we support automatic fallback if format detection fails?
- [ ] Do both formats produce identical restored database schemas?
- [ ] Are there performance differences between formats?

## References

- [Design Roadmap - Multi-Format Support](../design/roadmap.md#multiple-mydumper-format-support)
- [AWS Authentication Setup](aws-authentication-setup.md) - Configuring access to multiple accounts
- [System Overview](../design/system-overview.md) - S3 backup discovery logic
