#!/bin/bash
# Quick fix script for hostname/alias data correction
# Swaps hostname <-> host_alias for aurora-test to match schema intent

echo "=== Checking current aurora-test record ==="
sudo mysql pulldb_service -e "
SELECT 
    id,
    hostname,
    host_alias,
    credential_ref,
    enabled
FROM db_hosts 
WHERE hostname = 'aurora-test' OR host_alias = 'aurora-test';"

echo ""
echo "=== Applying fix: Setting hostname to full RDS endpoint ==="
echo "This ensures:"
echo "  - hostname field contains actual database endpoint"
echo "  - host_alias contains short friendly name"
echo "  - Existing jobs with dbhost='aurora-test' still work via resolve_hostname()"
echo ""

sudo mysql pulldb_service -e "
UPDATE db_hosts 
SET 
    hostname = 'db-mysql-db4-clone-pulldb-test-cluster.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com',
    host_alias = 'aurora-test'
WHERE hostname = 'aurora-test';"

if [ $? -eq 0 ]; then
    echo "✓ Database updated successfully"
else
    echo "✗ Database update failed"
    exit 1
fi

echo ""
echo "=== Verifying fix ==="
sudo mysql pulldb_service -e "
SELECT 
    id,
    LEFT(hostname, 50) as hostname,
    host_alias,
    LEFT(credential_ref, 40) as credential_ref,
    enabled
FROM db_hosts 
WHERE host_alias = 'aurora-test';"

echo ""
echo "=== Testing with CLI (should show full endpoint) ==="
pulldb hosts

echo ""
echo "=== Verification Complete ==="
echo "Users can now reference this host by:"
echo "  - Alias: dbhost=aurora-test"
echo "  - Full hostname: dbhost=db-mysql-db4-clone-pulldb-test-cluster..."
echo ""
echo "The API will display the actual endpoint resolved from AWS Secrets Manager."
