-- Reset SendGrid configuration
-- Purpose: Replace production SendGrid keys with safe development key

TRUNCATE TABLE sendGridKey;

INSERT INTO sendGridKey 
VALUES ('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');
