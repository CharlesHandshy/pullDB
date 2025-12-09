/**
 * Navigation Intent Utility
 * =========================
 * HCA Layer: shared (Layer 0) - infrastructure utility
 * 
 * Provides a clean way to pass navigation intent between pages using sessionStorage.
 * Replaces URL query parameters for filter passing, which persist incorrectly on tab switches.
 * 
 * Usage:
 *   Source page: NavIntent.set({ view: 'history', filters: { status: ['failed'] } });
 *   Target page: const intent = NavIntent.consume(); // Returns intent and clears it
 * 
 * Features:
 *   - Auto-expiry (30 seconds) to prevent stale intents
 *   - Immediate consumption (cleared on read)
 *   - Fallback-friendly (pages can still check URL params for external deep-links)
 */

const NavIntent = {
    KEY: 'pulldb_nav_intent',
    EXPIRY_MS: 30000, // 30 seconds
    
    /**
     * Store navigation intent before navigating to another page.
     * @param {Object} intent - The intent object to store
     * @param {string} [intent.view] - Target view (e.g., 'active', 'history')
     * @param {Object} [intent.filters] - Filter key-value pairs (e.g., { status: ['failed'] })
     */
    set(intent) {
        try {
            sessionStorage.setItem(this.KEY, JSON.stringify({
                ...intent,
                timestamp: Date.now()
            }));
        } catch (e) {
            // sessionStorage blocked or full - silently fail
            console.warn('NavIntent: Could not store intent', e);
        }
    },
    
    /**
     * Consume (read and clear) navigation intent.
     * Returns null if no intent, expired, or storage unavailable.
     * @returns {Object|null} The intent object or null
     */
    consume() {
        try {
            const raw = sessionStorage.getItem(this.KEY);
            sessionStorage.removeItem(this.KEY); // Always clear
            
            if (!raw) return null;
            
            const intent = JSON.parse(raw);
            
            // Check expiry
            if (Date.now() - intent.timestamp > this.EXPIRY_MS) {
                return null; // Expired
            }
            
            // Remove timestamp from returned object
            delete intent.timestamp;
            return intent;
        } catch (e) {
            // Storage blocked or parse error
            console.warn('NavIntent: Could not consume intent', e);
            return null;
        }
    },
    
    /**
     * Check if an intent exists without consuming it.
     * Useful for conditional logic before consumption.
     * @returns {boolean}
     */
    has() {
        try {
            const raw = sessionStorage.getItem(this.KEY);
            if (!raw) return false;
            
            const intent = JSON.parse(raw);
            return Date.now() - intent.timestamp <= this.EXPIRY_MS;
        } catch (e) {
            return false;
        }
    }
};

// Make available globally
window.NavIntent = NavIntent;
