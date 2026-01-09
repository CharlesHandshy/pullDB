-- Remove sensitive payment logs
-- Purpose: Delete payment account creation logs that may contain sensitive data

DELETE FROM myLog 
WHERE message LIKE '%PaymentAccountCreateResponse%';
