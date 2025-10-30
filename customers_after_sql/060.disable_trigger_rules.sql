-- Disable trigger rules
-- Purpose: Prevent production triggers from firing in development environment

UPDATE triggerRuleHeaders 
SET active = 0;

UPDATE triggerRuleItems 
SET itemActive = 0;
