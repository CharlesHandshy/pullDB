#!/usr/bin/env bash
# Prod helper (review-only)
set -euo pipefail
# ASSUME_RESPONSE=$(aws sts assume-role --role-arn <ROLE> --external-id <EXT>)
# export AWS_ACCESS_KEY_ID=$(echo "$ASSUME_RESPONSE" | jq -r '.Credentials.AccessKeyId')
# export AWS_SECRET_ACCESS_KEY=$(echo "$ASSUME_RESPONSE" | jq -r '.Credentials.SecretAccessKey')
# export AWS_SESSION_TOKEN=$(echo "$ASSUME_RESPONSE" | jq -r '.Credentials.SessionToken')
# aws s3 ls s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/
