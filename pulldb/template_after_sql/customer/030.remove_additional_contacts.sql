-- Remove additional contact information
-- Purpose: Sanitize additional contact PII

UPDATE additionalContacts 
SET email = '', 
    phone = '', 
    phone2 = '';
