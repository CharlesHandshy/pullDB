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
    sentriconBranchCode = '';
