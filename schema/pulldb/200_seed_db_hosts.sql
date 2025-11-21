-- 200_seed_db_hosts.sql
-- Seed data for db_hosts table

INSERT INTO db_hosts (id, hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('550e8400-e29b-41d4-a716-446655440003',
     'localhost',
    'aws-secretsmanager:/pulldb/mysql/localhost-test',
     1,
     TRUE);

INSERT INTO db_hosts (id, hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('550e8400-e29b-41d4-a716-446655440000',
     'db-mysql-db3-dev-vpc-us-east-1-aurora.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com',
     'aws-secretsmanager:/pulldb/mysql/db3-dev',
     1,
     FALSE);

INSERT INTO db_hosts (id, hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('550e8400-e29b-41d4-a716-446655440001',
     'db-mysql-db4-dev-vpc-us-east-1-aurora.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com',
     'aws-secretsmanager:/pulldb/mysql/db4-dev',
     1,
     FALSE);

INSERT INTO db_hosts (id, hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('550e8400-e29b-41d4-a716-446655440002',
     'db-mysql-db5-dev-vpc-us-east-1-aurora.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com',
     'aws-secretsmanager:/pulldb/mysql/db5-dev',
     1,
     FALSE);
