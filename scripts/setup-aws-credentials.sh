#!/bin/bash
# Setup and validate AWS credentials for pullDB
# This script checks AWS CLI installation, validates credentials, and ensures S3 access

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== pullDB AWS Credentials Setup ===${NC}\n"

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo -e "${RED}ERROR: AWS CLI is not installed${NC}"
    echo "Install it with: sudo scripts/setup-aws.sh"
    exit 1
fi

echo -e "${GREEN}✓ AWS CLI found:${NC} $(aws --version)"

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠ No .env file found${NC}"
    echo "Creating .env from template..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo -e "${GREEN}✓ Created .env from .env.example${NC}"
        echo -e "${YELLOW}⚠ Please edit .env and configure your AWS credentials${NC}"
        echo ""
        echo "Options:"
        echo "  Configure AWS profile:"
        echo "     - Run: aws configure --profile pr-prod"
        echo "     - Set PULLDB_AWS_PROFILE=pr-prod in .env"
        echo ""
        exit 0
    else
        echo -e "${RED}ERROR: .env.example not found${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}✓ Found .env file${NC}"

# Load environment variables from .env safely (no word splitting on values with spaces)
set -o allexport
grep -v '^#' .env | grep -E '^[A-Z_]+=.*' | while IFS= read -r line; do
    key="${line%%=*}"
    val="${line#*=}"
    printf -v "$key" '%s' "$val"
done
set +o allexport

# Validate AWS credentials
echo ""
echo "Validating AWS credentials..."

# Check if AWS profile is configured
if [ -n "$PULLDB_AWS_PROFILE" ]; then
    echo -e "${GREEN}Using AWS profile:${NC} $PULLDB_AWS_PROFILE"
    export AWS_PROFILE=$PULLDB_AWS_PROFILE
else
    echo -e "${RED}ERROR: No AWS profile configured${NC}"
    echo "Set PULLDB_AWS_PROFILE=<profile-name> in .env"
    echo "Example: PULLDB_AWS_PROFILE=pr-prod"
    exit 1
fi

# Test AWS credentials
echo ""
echo "Testing AWS credentials..."
if ! CALLER_IDENTITY=$(aws sts get-caller-identity 2>&1); then
    echo -e "${RED}ERROR: AWS credentials validation failed${NC}"
    echo "$CALLER_IDENTITY"
    exit 1
fi

echo -e "${GREEN}✓ AWS credentials valid${NC}"
if command -v jq >/dev/null 2>&1; then
    echo "$CALLER_IDENTITY" | jq '.'
else
    echo "(Install jq for pretty output) Raw identity:"
    echo "$CALLER_IDENTITY"
fi

# Test S3 access to backup bucket
echo ""
echo "Testing S3 bucket access..."
if [ -n "$PULLDB_S3_BUCKET_PATH" ]; then
    BUCKET_NAME=$(echo "$PULLDB_S3_BUCKET_PATH" | cut -d'/' -f1)
    echo "Checking access to bucket: $BUCKET_NAME"
    
    if aws s3 ls "s3://$BUCKET_NAME" --max-items 1 > /dev/null 2>&1; then
        echo -e "${GREEN}✓ S3 bucket accessible${NC}"
    else
        echo -e "${YELLOW}⚠ Cannot access S3 bucket: $BUCKET_NAME${NC}"
        echo "This may be expected if your credentials don't have S3 access yet"
        echo "Ensure your IAM user/role has s3:ListBucket and s3:GetObject permissions"
    fi
else
    echo -e "${YELLOW}⚠ PULLDB_S3_BUCKET_PATH not set in .env${NC}"
    echo "This value is typically loaded from the MySQL settings table"
fi

# Optional: test resolving a Parameter Store reference if MySQL host is a path (starts with /)
if [[ "$PULLDB_MYSQL_HOST" == /* ]]; then
    echo ""
    echo "Testing AWS Parameter Store resolution for PULLDB_MYSQL_HOST..."
    if MYSQL_HOST_VALUE=$(aws ssm get-parameter --name "$PULLDB_MYSQL_HOST" --with-decryption --query 'Parameter.Value' --output text 2>/dev/null); then
        echo -e "${GREEN}✓ Resolved MySQL host parameter: ${NC}$MYSQL_HOST_VALUE"
    else
        echo -e "${YELLOW}⚠ Failed to resolve parameter ${NC}$PULLDB_MYSQL_HOST"
        echo "Ensure IAM permissions include ssm:GetParameter and kms:Decrypt (if SecureString)."
    fi
fi

echo ""
echo -e "${GREEN}=== AWS Setup Complete ===${NC}"
echo ""
echo "Next steps:"
echo "  1. Verify .env settings: cat .env"
echo "  2. Test Python config loading: python3 -c 'from pulldb.domain.config import Config; print(Config.minimal_from_env())'"
echo "  3. Continue with: scripts/setup-python-project.sh"
