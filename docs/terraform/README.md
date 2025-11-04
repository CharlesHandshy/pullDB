Terraform examples (hints)
=========================

This folder contains minimal Terraform hints showing how to create the cross-account role and attach the policy templates in `docs/policies/`.

Important:
- These are examples only. Run them in the account that should own the resources (production account for prod role/policy).
- Replace placeholders `<ACCOUNT_ID>` and `<EXTERNAL_ID_HERE>` before applying.
- Do not commit secrets or KMS keys into state.

Files:
- `pulldb_cross_account.tf` — simple example creating role and managed policy attachment
