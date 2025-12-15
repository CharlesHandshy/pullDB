/**
 * Theme Toggle - Dark/Light Mode Switcher
 * HCA Layer: shared (infrastructure)
 * 
 * Handles theme persistence via localStorage and system preference detection.
 * Toggles data-theme attribute on <html> element.
 * 
 * Priority order:
 * 1. localStorage (user's explicit preference override)
 * 2. data-admin-theme-default attribute (admin-configured default)
 * 3. System preference (prefers-color-scheme)
 * 4. Light mode fallback
 */

(function() {
    'use strict';

    const THEME_KEY = 'pulldb-theme';
    const DARK = 'dark';
    const LIGHT = 'light';

    /**
     * Get the admin-configured default theme from data attribute
     */
    function getAdminDefault() {
        const adminDefault = document.documentElement.getAttribute('data-admin-theme-default');
        if (adminDefault === DARK || adminDefault === LIGHT) {
            return adminDefault;
        }
        return null;
    }

    /**
     * Get the preferred theme from storage, admin default, or system preference
     */
    function getPreferredTheme() {
        // 1. Check localStorage first (user override)
        const stored = localStorage.getItem(THEME_KEY);
        if (stored === DARK || stored === LIGHT) {
            return stored;
        }
        
        // 2. Check admin-configured default
        const adminDefault = getAdminDefault();
        if (adminDefault) {
            return adminDefault;
        }
        
        // 3. Respect system preference
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return DARK;
        }
        
        // 4. Default to light
        return LIGHT;
    }

    /**
     * Apply theme to the document
     */
    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem(THEME_KEY, theme);
        
        // Update toggle button icon if it exists
        const toggleBtn = document.getElementById('theme-toggle');
        if (toggleBtn) {
            // Support both direct SVG children and span wrappers
            const lightIcon = toggleBtn.querySelector('.theme-icon-light') || toggleBtn.querySelector('[data-icon="sun"]');
            const darkIcon = toggleBtn.querySelector('.theme-icon-dark') || toggleBtn.querySelector('[data-icon="moon"]');
            
            if (lightIcon && darkIcon) {
                if (theme === DARK) {
                    lightIcon.style.display = 'flex';
                    darkIcon.style.display = 'none';
                } else {
                    lightIcon.style.display = 'none';
                    darkIcon.style.display = 'flex';
                }
            }
        }
    }

    /**
     * Toggle between dark and light themes
     */
    function toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme') || LIGHT;
        const next = current === DARK ? LIGHT : DARK;
        applyTheme(next);
    }

    // Apply initial theme immediately to prevent flash
    applyTheme(getPreferredTheme());

    // Listen for system preference changes
    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
            // Only auto-switch if user hasn't manually set a preference
            if (!localStorage.getItem(THEME_KEY)) {
                applyTheme(e.matches ? DARK : LIGHT);
            }
        });
    }

    // Expose toggle function globally
    window.toggleTheme = toggleTheme;

    // Auto-bind to theme toggle button when DOM is ready
    document.addEventListener('DOMContentLoaded', function() {
        const toggleBtn = document.getElementById('theme-toggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', toggleTheme);
            
            // Set initial icon state
            const theme = document.documentElement.getAttribute('data-theme') || LIGHT;
            const lightIcon = toggleBtn.querySelector('.theme-icon-light') || toggleBtn.querySelector('[data-icon="sun"]');
            const darkIcon = toggleBtn.querySelector('.theme-icon-dark') || toggleBtn.querySelector('[data-icon="moon"]');
            
            if (lightIcon && darkIcon) {
                lightIcon.style.display = theme === DARK ? 'flex' : 'none';
                darkIcon.style.display = theme === DARK ? 'none' : 'flex';
            }
        }
    });
})();
