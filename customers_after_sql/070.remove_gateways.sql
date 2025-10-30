-- Remove payment gateways
-- Purpose: Delete all payment gateway configurations to prevent accidental charges

DELETE FROM gateways;
