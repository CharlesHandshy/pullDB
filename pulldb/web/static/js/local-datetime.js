/**
 * Local DateTime Converter
 * 
 * Converts UTC timestamps to the user's local timezone.
 * Progressive enhancement: Falls back to showing UTC if JavaScript fails.
 * 
 * Usage in templates:
 *   <span data-utc="{{ timestamp.isoformat() }}Z" data-format="datetime">
 *       {{ timestamp.strftime('%Y-%m-%d %H:%M:%S') }} UTC
 *   </span>
 * 
 * Supported formats (data-format attribute):
 *   - "datetime" (default): "Jan 17, 2026, 2:30 PM"
 *   - "date": "Jan 17, 2026"
 *   - "time": "2:30 PM"
 *   - "short": "Jan 17, 2:30 PM"
 *   - "relative": "2 hours ago" (with fallback to datetime)
 */

(function() {
    'use strict';

    /**
     * Format a Date object according to the specified format
     */
    function formatDate(date, format) {
        if (isNaN(date.getTime())) return null;

        switch (format) {
            case 'date':
                return date.toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    year: '2-digit'
                });

            case 'time':
                return date.toLocaleTimeString('en-US', {
                    hour: 'numeric',
                    minute: '2-digit',
                    hour12: true
                });

            case 'short':
                return date.toLocaleString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit',
                    hour12: true
                });

            case 'relative':
                return getRelativeTime(date);

            case 'datetime':
            default:
                return date.toLocaleString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    year: '2-digit',
                    hour: 'numeric',
                    minute: '2-digit',
                    hour12: true
                });
        }
    }

    /**
     * Get relative time string (e.g., "2 hours ago", "in 3 days")
     */
    function getRelativeTime(date) {
        const now = new Date();
        const diffMs = now - date;
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHour = Math.floor(diffMin / 60);
        const diffDay = Math.floor(diffHour / 24);

        // Future dates
        if (diffMs < 0) {
            const absDiffDay = Math.abs(diffDay);
            if (absDiffDay === 0) return 'today';
            if (absDiffDay === 1) return 'tomorrow';
            if (absDiffDay < 7) return `in ${absDiffDay} days`;
            // Fall back to formatted date for far future
            return formatDate(date, 'short');
        }

        // Past dates
        if (diffSec < 60) return 'just now';
        if (diffMin < 60) return `${diffMin} minute${diffMin === 1 ? '' : 's'} ago`;
        if (diffHour < 24) return `${diffHour} hour${diffHour === 1 ? '' : 's'} ago`;
        if (diffDay === 1) return 'yesterday';
        if (diffDay < 7) return `${diffDay} days ago`;
        // Fall back to formatted date for old dates
        return formatDate(date, 'short');
    }

    /**
     * Convert all elements with data-utc attribute to local time
     */
    function convertToLocalTime() {
        document.querySelectorAll('[data-utc]').forEach(function(el) {
            const utcString = el.dataset.utc;
            if (!utcString) return;

            // Parse the UTC timestamp
            const date = new Date(utcString);
            if (isNaN(date.getTime())) return;

            // Get the desired format (default to 'datetime')
            const format = el.dataset.format || 'datetime';

            // Format the date
            const formatted = formatDate(date, format);
            if (!formatted) return;

            // Update the element
            el.textContent = formatted;

            // Set title to full ISO string for reference
            el.title = date.toLocaleString('en-US', {
                weekday: 'long',
                year: 'numeric',
                month: 'long',
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
                second: '2-digit',
                timeZoneName: 'short'
            });

            // Mark as converted to prevent re-processing
            el.dataset.utcConverted = 'true';
        });
    }

    /**
     * Initialize - run on DOM ready and after HTMX swaps
     */
    function init() {
        // Run immediately if DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', convertToLocalTime);
        } else {
            convertToLocalTime();
        }

        // Re-run after HTMX content swaps
        document.body.addEventListener('htmx:afterSwap', convertToLocalTime);
        document.body.addEventListener('htmx:afterSettle', convertToLocalTime);
    }

    // Export for manual use if needed
    window.LocalDateTime = {
        convert: convertToLocalTime,
        format: formatDate,
        relative: getRelativeTime
    };

    // Initialize
    init();

})();
