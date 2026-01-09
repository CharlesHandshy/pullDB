-- Remove billTo contact information
-- Purpose: Sanitize billing contact PII

UPDATE billTos 
SET billingEmail = '', 
    billingPhone = '';
