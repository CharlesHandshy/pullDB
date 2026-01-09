-- Remove employee contact information
-- Purpose: Sanitize employee PII

UPDATE employees 
SET email = '', 
    phone = '';
