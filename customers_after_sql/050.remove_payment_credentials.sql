-- Remove office payment credentials and sensitive settings
-- Purpose: Remove payment processing credentials from development environment

UPDATE preferences
SET elementAccountID = '',
    elementAccountToken = '',
    elementAcceptorID = '',
    elementTerminalID = '',
    anetLogin = '',
    brainMerchantID = '',
    brainPublicKey = '',
    brainPrivateKey = '',
    brainClientSideKey = '',
    brainMerchantAccountId = '',
    spreedlyGatewayToken = '',
    spreedlyEnvironmentKey = '',
    sentriconBranchCode = '',
    businessRegistrationNumber = 'AQICAHh7g05a5Gt9MxSFKR7NSimOVuFxQFE6KQLa6e2ZM/g7wgG6la+XTgBIJ5vGx159dOBbAAAAZzBlBgkqhkiG9w0BBwagWDBWAgEAMFEGCSqGSIb3DQEHATAeBglghkgBZQMEAS4wEQQMZL5gxj7q2ticP7JaAgEQgCSVMQdGgxy1byutiLj9LxhSss+DEFr3cXtWQ5HDIDwv6lFoxJk=';
