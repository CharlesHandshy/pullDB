/**
 * Theme Toggle - Dark/Light Mode Switcher
 * HCA Layer: shared (infrastructure)
 * 
 * Handles theme persistence via localStorage and system preference detection.
 * Toggles data-theme attribute on <html> element.
 * Dynamically swaps between manifest-light.css and manifest-dark.css.
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
    const THEME_VERSION_KEY = 'pulldb-theme-version';
    const THEME_COOKIE = 'pulldb_theme';
    const DARK = 'dark';
    const LIGHT = 'light';

    /**
     * Set a cookie with the given name and value
     */
    function setCookie(name, value, days) {
        const maxAge = days ? days * 24 * 60 * 60 : 31536000; // Default 1 year
        document.cookie = name + '=' + value + ';path=/;max-age=' + maxAge + ';SameSite=Lax';
    }

    /**
     * Get a cookie value by name
     */
    function getCookie(name) {
        const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? match[2] : null;
    }

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
     * Get current theme version for cache-busting
     */
    function getThemeVersion() {
        return localStorage.getItem(THEME_VERSION_KEY) || Date.now();
    }

    /**
     * Swap the theme CSS file based on mode
     */
    function swapThemeCSS(theme) {
        const themeLink = document.getElementById('theme-css');
        if (themeLink) {
            // Check if we're already on the correct theme file (ignore version query param)
            const currentHref = themeLink.href || '';
            const expectedFile = `manifest-${theme}.css`;
            if (currentHref.includes(expectedFile)) {
                // Already on correct theme CSS, no swap needed
                return;
            }
            
            const version = getThemeVersion();
            const newHref = `/static/css/generated/manifest-${theme}.css?v=${version}`;
            themeLink.href = newHref;
        }
    }

    /**
     * Apply theme to the document
     */
    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem(THEME_KEY, theme);
        
        // Sync to cookie for server-side detection
        setCookie(THEME_COOKIE, theme);
        
        // Swap the CSS file to the correct mode
        swapThemeCSS(theme);
        
        // Update toggle button icon if it exists
        const toggleBtn = document.getElementById('theme-toggle');
        if (toggleBtn) {
            // Support both direct SVG children and span wrappers
            const lightIcon = toggleBtn.querySelector('.theme-icon-light') || toggleBtn.querySelector('[data-icon="sun"]');
            const darkIcon = toggleBtn.querySelector('.theme-icon-dark') || toggleBtn.querySelector('[data-icon="moon"]');
            
            if (lightIcon && darkIcon) {
                if (theme === DARK) {
                    lightIcon.classList.remove('hidden');
                    darkIcon.classList.add('hidden');
                } else {
                    lightIcon.classList.add('hidden');
                    darkIcon.classList.remove('hidden');
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

    /**
     * Reload theme CSS from server (call after saving appearance settings)
     * Uses cache-busting to force browser to fetch fresh CSS
     * @param {number} version - Optional version number from generate-manifest response
     */
    function reloadThemeCSS(version) {
        const newVersion = version || Date.now();
        localStorage.setItem(THEME_VERSION_KEY, newVersion);
        
        const currentTheme = document.documentElement.getAttribute('data-theme') || LIGHT;
        const themeLink = document.getElementById('theme-css');
        
        if (themeLink) {
            // Force reload with new version
            themeLink.href = `/static/css/generated/manifest-${currentTheme}.css?v=${newVersion}`;
        }
    }

    /**
     * Apply preview CSS variables without persisting (DEPRECATED)
     * Preview is now isolated to demo gallery only - this is kept for backwards compatibility
     */
    function applyPreviewCSS(cssText) {
        console.warn('applyPreviewCSS is deprecated - preview is now isolated to demo gallery');
    }

    /**
     * Clear preview CSS (DEPRECATED - kept for backwards compatibility)
     */
    function clearPreviewCSS() {
        const previewStyle = document.getElementById('theme-preview-style');
        if (previewStyle) {
            previewStyle.remove();
        }
    }

    // Expose functions globally
    window.toggleTheme = toggleTheme;
    window.reloadThemeCSS = reloadThemeCSS;
    window.applyPreviewCSS = applyPreviewCSS;
    window.clearPreviewCSS = clearPreviewCSS;

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
                lightIcon.classList.toggle('hidden', theme !== DARK);
                darkIcon.classList.toggle('hidden', theme === DARK);
            }
        }
    });
})();
