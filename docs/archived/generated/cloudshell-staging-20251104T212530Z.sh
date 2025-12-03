#!/usr/bin/env bash
# Staging helper (review-only)
set -euo pipefail
echo "Listing staging backups in s3://pestroutesrdsdbs/daily/stg/"
# aws s3 ls s3://pestroutesrdsdbs/daily/stg/ --no-sign-request || aws s3 ls s3://pestroutesrdsdbs/daily/stg/
# echo "aws sts assume-role --role-arn <ROLE> --external-id <EXT>"
