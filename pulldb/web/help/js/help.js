/**
 * pullDB Help Center - Main Application
 * Alpine.js powered interactivity
 */

// Initialize Alpine.js app data
function helpApp() {
    return {
        // Theme
        theme: localStorage.getItem('help-theme') || 
               (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'),
        
        // Search
        searchOpen: false,
        searchQuery: '',
        searchResults: [],
        selectedIndex: -1,
        searchIndex: [],

        // Keyboard shortcuts overlay
        shortcutsOpen: false,

        // Mobile nav
        mobileNavOpen: false,
        
        // Initialize
        init() {
            // Apply saved theme
            document.documentElement.setAttribute('data-theme', this.theme);
            
            // Load search index
            this.loadSearchIndex();
            
            // Initialize hero terminal animation
            if (document.getElementById('hero-terminal-body')) {
                setTimeout(() => initHeroTerminal(), 500);
            }
            
            // Watch for theme changes
            this.$watch('theme', (value) => {
                document.documentElement.setAttribute('data-theme', value);
                localStorage.setItem('help-theme', value);
            });
        },
        
        // Theme toggle
        toggleTheme() {
            this.theme = this.theme === 'light' ? 'dark' : 'light';
        },

        // Mobile nav
        openMobileNav() {
            this.mobileNavOpen = true;
            document.body.style.overflow = 'hidden';
        },

        closeMobileNav() {
            this.mobileNavOpen = false;
            document.body.style.overflow = '';
        },
        
        // Search methods
        openSearch() {
            this.searchOpen = true;
            this.searchQuery = '';
            this.searchResults = [];
            this.selectedIndex = -1;
            this.$nextTick(() => {
                const input = document.getElementById('help-search-input');
                if (input) input.focus();
            });
        },

        closeSearch() {
            this.searchOpen = false;
            this.searchQuery = '';
            this.searchResults = [];
            this.$nextTick(() => {
                const btn = document.querySelector('.search-trigger');
                if (btn) btn.focus();
            });
        },
        
        focusSearch() {
            if (!this.searchOpen) {
                this.openSearch();
            }
        },
        
        async loadSearchIndex() {
            try {
                const response = await fetch('/web/help/search-index.json');
                if (response.ok) {
                    this.searchIndex = await response.json();
                } else {
                    // Non-200 (e.g. 404) — fall back to inline data
                    this.searchIndex = getDefaultSearchIndex();
                }
            } catch (e) {
                // Network error — fall back to inline data
                this.searchIndex = getDefaultSearchIndex();
            }
        },
        
        openShortcuts() { this.shortcutsOpen = true; },
        closeShortcuts() { this.shortcutsOpen = false; },

        handleShortcutsKeydown(event) {
            if (!this.shortcutsOpen) return;
            if (event.key === 'Escape') {
                this.closeShortcuts();
                return;
            }
            if (event.key !== 'Tab') return;
            const modal = document.querySelector('.shortcuts-modal');
            if (!modal) return;
            const focusable = modal.querySelectorAll(
                'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
            );
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey) {
                if (document.activeElement === first) {
                    event.preventDefault();
                    last.focus();
                }
            } else {
                if (document.activeElement === last) {
                    event.preventDefault();
                    first.focus();
                }
            }
        },

        performSearch() {
            if (!this.searchQuery || this.searchQuery.trim().length < 2) {
                this.searchResults = [];
                return;
            }

            // Guard: skip if index hasn't loaded yet
            if (!Array.isArray(this.searchIndex) || this.searchIndex.length === 0) return;

            // Use the fuzzy search engine from search.js (window.searchDocs)
            const rawResults = window.searchDocs
                ? window.searchDocs(this.searchIndex, this.searchQuery)
                : [];

            // Map highlightedTitle → title so the template (x-html="result.title") renders highlights
            this.searchResults = rawResults.map(r => ({
                ...r,
                title: r.highlightedTitle || r.title
            }));
            this.selectedIndex = -1;
        },
        
        highlightMatch(text, query) {
            const regex = new RegExp(`(${this.escapeRegex(query)})`, 'gi');
            return text.replace(regex, '<mark>$1</mark>');
        },
        
        getPreview(content, query) {
            const index = content.toLowerCase().indexOf(query);
            if (index === -1) {
                return content.substring(0, 100) + '...';
            }
            
            const start = Math.max(0, index - 40);
            const end = Math.min(content.length, index + query.length + 60);
            let preview = content.substring(start, end);
            
            if (start > 0) preview = '...' + preview;
            if (end < content.length) preview = preview + '...';
            
            return this.highlightMatch(preview, query);
        },
        
        escapeRegex(string) {
            return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        },
        
        navigateResults(direction) {
            const newIndex = this.selectedIndex + direction;
            if (newIndex >= 0 && newIndex < this.searchResults.length) {
                this.selectedIndex = newIndex;
            }
        },
        
        selectResult() {
            if (this.searchResults[this.selectedIndex]) {
                window.location.href = this.searchResults[this.selectedIndex].url;
            }
        },

        handleSearchKeydown(event) {
            if (!this.searchOpen) return;
            if (event.key === 'Escape') {
                this.closeSearch();
                return;
            }
            // ArrowDown, ArrowUp, Enter are handled on the input element directly.
            // Only Tab (focus trap) needs modal-level handling.
            if (event.key !== 'Tab') return;
            // Find all focusable elements within the modal
            const modal = document.querySelector('.search-modal');
            if (!modal) return;
            const focusable = modal.querySelectorAll(
                'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
            );
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey) {
                if (document.activeElement === first) {
                    event.preventDefault();
                    last.focus();
                }
            } else {
                if (document.activeElement === last) {
                    event.preventDefault();
                    first.focus();
                }
            }
        }
    };
}

// Default search index (used before build script generates it)
function getDefaultSearchIndex() {
    return [
        {
            id: 'cli-restore',
            title: 'pulldb restore',
            content: 'Submit a restore job to download a backup from S3 and restore it to your development database. Use user= and customer= parameters.',
            url: 'pages/cli/index.html#restore',
            type: 'cli',
            category: 'CLI',
            keywords: ['restore', 'backup', 'submit', 'job', 's3']
        },
        {
            id: 'cli-status',
            title: 'pulldb status',
            content: 'Check the status of a specific job or view all active jobs. Shows progress, ETA, and current phase.',
            url: 'pages/cli/index.html#status',
            type: 'cli',
            category: 'CLI',
            keywords: ['status', 'check', 'progress', 'job']
        },
        {
            id: 'cli-cancel',
            title: 'pulldb cancel',
            content: 'Cancel a running or queued job. Gracefully stops the job and cleans up staging databases.',
            url: 'pages/cli/index.html#cancel',
            type: 'cli',
            category: 'CLI',
            keywords: ['cancel', 'stop', 'abort', 'job']
        },
        {
            id: 'cli-events',
            title: 'pulldb events',
            content: 'Stream real-time events for a job. Use --follow to continuously watch for new events.',
            url: 'pages/cli/index.html#events',
            type: 'cli',
            category: 'CLI',
            keywords: ['events', 'stream', 'watch', 'follow', 'logs']
        },
        {
            id: 'cli-history',
            title: 'pulldb history',
            content: 'View your completed jobs. Filter by status, date range, or customer.',
            url: 'pages/cli/index.html#history',
            type: 'cli',
            category: 'CLI',
            keywords: ['history', 'completed', 'past', 'jobs']
        },
        {
            id: 'api-auth',
            title: 'API Authentication',
            content: 'pullDB API supports two authentication modes: trusted headers for CLI and session-based for web. Use X-Pulldb-User header or login to get a session cookie.',
            url: 'pages/api/index.html#authentication',
            type: 'api',
            category: 'API',
            keywords: ['auth', 'authentication', 'login', 'session', 'header']
        },
        {
            id: 'api-jobs',
            title: 'Jobs API Endpoints',
            content: 'POST /api/jobs to submit a restore. GET /api/jobs to list jobs. GET /api/jobs/{id} for details. POST /api/jobs/{id}/cancel to cancel.',
            url: 'pages/api/index.html#jobs',
            type: 'api',
            category: 'API',
            keywords: ['jobs', 'api', 'endpoint', 'rest']
        },
        {
            id: 'concept-lifecycle',
            title: 'Job Lifecycle',
            content: 'Jobs progress through states: QUEUED → RUNNING (downloading, extracting, restoring, post_sql, finalizing) → COMPLETE/FAILED/CANCELED',
            url: 'pages/concepts/job-lifecycle.html',
            type: 'concept',
            category: 'Concepts',
            keywords: ['lifecycle', 'states', 'status', 'queued', 'running', 'complete']
        },
        {
            id: 'concept-atomic',
            title: 'Atomic Rename',
            content: 'pullDB uses atomic rename to ensure zero-downtime restores. Data is restored to a staging database, then atomically renamed.',
            url: 'pages/concepts/job-lifecycle.html#atomic-rename',
            type: 'concept',
            category: 'Concepts',
            keywords: ['atomic', 'rename', 'staging', 'zero-downtime']
        },
        {
            id: 'trouble-permission',
            title: 'Permission Denied Errors',
            content: 'If you get permission denied, check: 1) User is enabled in pullDB 2) AWS credentials are configured 3) Target host allows your user',
            url: 'pages/troubleshooting/index.html#permission-denied',
            type: 'guide',
            category: 'Troubleshooting',
            keywords: ['permission', 'denied', 'access', 'error', 'forbidden']
        },
        {
            id: 'trouble-failed',
            title: 'Job Failed Errors',
            content: 'Common job failure causes: S3 access denied, MySQL connection failed, disk space exhausted, myloader timeout.',
            url: 'pages/troubleshooting/index.html#job-failed',
            type: 'guide',
            category: 'Troubleshooting',
            keywords: ['failed', 'error', 'failure', 'job']
        },
        {
            id: 'getting-started',
            title: 'Getting Started',
            content: 'Install pullDB client, configure your credentials, and run your first restore in under 5 minutes.',
            url: 'pages/getting-started.html',
            type: 'guide',
            category: 'Guide',
            keywords: ['start', 'install', 'setup', 'first', 'begin']
        }
    ];
}

// Copy terminal command to clipboard
function copyTerminal(button) {
    const terminal = button.closest('.terminal-window');
    const commandLine = terminal.querySelector('.command');
    
    if (commandLine) {
        navigator.clipboard.writeText(commandLine.textContent).then(() => {
            button.classList.add('copied');
            const originalHTML = button.innerHTML;
            button.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="20 6 9 17 4 12"/>
                </svg>
            `;
            setTimeout(() => {
                button.classList.remove('copied');
                button.innerHTML = originalHTML;
            }, 2000);
        });
    }
}

// Accordion functionality
document.addEventListener('click', (e) => {
    const trigger = e.target.closest('.accordion-trigger');
    if (trigger) {
        const item = trigger.closest('.accordion-item');
        item.classList.toggle('open');
    }
});

// Smooth scroll for anchor links
document.addEventListener('click', (e) => {
    const link = e.target.closest('a[href^="#"]');
    if (link) {
        e.preventDefault();
        const target = document.querySelector(link.getAttribute('href'));
        if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            history.pushState(null, null, link.getAttribute('href'));
        }
    }
});
