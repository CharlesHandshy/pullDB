-- Remove customer emails and phone numbers
-- Purpose: Sanitize customer personally identifiable information (PII)

UPDATE customers 
SET email = '', 
    phone1 = '', 
    phone2 = '';
