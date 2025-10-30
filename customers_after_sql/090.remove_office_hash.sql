-- Remove office hash values
-- Purpose: Clear office hash to prevent unauthorized access to production systems

UPDATE offices 
SET officeHash = '';
