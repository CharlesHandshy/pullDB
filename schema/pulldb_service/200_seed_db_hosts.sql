-- 200_seed_db_hosts.sql
-- Seed data for db_hosts table

INSERT INTO db_hosts (id, hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('550e8400-e29b-41d4-a716-446655440003',
     'localhost',
    'aws-secretsmanager:/pulldb/mysql/localhost-test',
     1,
     TRUE);


