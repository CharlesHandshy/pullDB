# Feature Requests Documentation

This directory contains detailed specifications for feature requests submitted by users.

## Naming Convention

Files are named using the pattern: `{request_id_prefix}-{short_name}.md`

- **request_id_prefix**: First 8 characters of the feature request UUID
- **short_name**: Brief descriptive name (lowercase, hyphens)

## Current Feature Requests

| ID | File | Title | Status |
|----|------|-------|--------|
| `54166071` | [54166071-overlord-companies.md](54166071-overlord-companies.md) | Overlord Companies Integration | In Progress |

## Workflow

1. **Review**: Use `tools/feature-requests-review.py` to fetch requests from production
2. **Research**: Have team research implementation requirements
3. **Document**: Create spec file in this directory
4. **Implement**: Follow the implementation plan in the spec
5. **Update**: Mark request as complete in production when done

## HCA Compliance

Feature request specs follow the standard documentation pattern:
- Stored in `docs/feature-requests/` (operational documentation)
- Named by feature request ID for traceability
- Contains architecture impact mapped to HCA layers
