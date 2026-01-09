-- Disable FleetPro integration
-- Purpose: Prevent development database from interacting with production FleetPro systems

UPDATE fleetProIntegration 
SET active = 0;
