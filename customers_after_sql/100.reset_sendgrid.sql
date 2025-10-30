-- Reset SendGrid configuration
-- Purpose: Replace production SendGrid keys with safe development key

TRUNCATE TABLE sendGridKey;

INSERT INTO sendGridKey (officeID, sendGridKey) 
VALUES (1, 'SG.DEVELOPMENT_KEY_REPLACE_WITH_ACTUAL_DEV_KEY');
