/**
 * Admin Database Discovery Page — LazyTable Implementation
 * HCA Layer: pages (Layer 4)
 *
 * Manages the database discovery workflow:
 * - Host selection dropdown triggers LazyTable data load
 * - LazyTable provides sorting, filtering, virtual scrolling
 * - Claim, Assign, and Remove (placeholder) actions
 * - Stats bar updates on data load
 * - Staging database visual distinction
 * - URL state persistence via ?host= query parameter
 * - Multi-owner badge when multiple jobs target the same database
 */
(function() {
    'use strict';

    // ==========================================================================
    // State
    // ==========================================================================

    let currentHostname = '';
    let table = null;
    let usersCache = null;

    // Staging database pattern: name_<12-hex-chars>
    const STAGING_PATTERN = /^(.+)_([0-9a-f]{12})$/;

    // ==========================================================================
    // SVG Icons
    // ==========================================================================

    const icons = {
        managed: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>',
        unmanaged: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="4.93" x2="19.07" y1="4.93" y2="19.07"/></svg>',
        locked: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
        claim: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
        assign: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" x2="19" y1="8" y2="14"/><line x1="22" x2="16" y1="11" y2="11"/></svg>',
        remove: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>',
        database: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/></svg>',
    };

    // ==========================================================================
    // Utilities
    // ==========================================================================

    function escapeHtml(str) {
        if (!str) return '';
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    function escapeAttr(str) {
        if (!str) return '';
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatDate(isoStr) {
        if (!isoStr) return '—';
        try {
            const d = new Date(isoStr);
            return d.toLocaleDateString('en-US', {
                year: 'numeric', month: 'short', day: 'numeric'
            });
        } catch {
            return isoStr;
        }
    }

    // ==========================================================================
    // URL State Management
    // ==========================================================================

    function getHostFromUrl() {
        const params = new URLSearchParams(window.location.search);
        return params.get('host') || '';
    }

    function setHostInUrl(hostname) {
        const url = new URL(window.location);
        if (hostname) {
            url.searchParams.set('host', hostname);
        } else {
            url.searchParams.delete('host');
        }
        history.replaceState(null, '', url);
    }

    // ==========================================================================
    // Column Renderers
    // ==========================================================================

    function renderStatus(val, row) {
        let badge = '';
        if (row.locked) {
            badge = `<span class="badge-managed locked">${icons.locked} Locked</span>`;
        } else if (row.managed) {
            badge = `<span class="badge-managed managed">${icons.managed} Managed</span>`;
        } else {
            badge = `<span class="badge-managed unmanaged">${icons.unmanaged} Unmanaged</span>`;
        }
        // Show origin badge for claimed/assigned databases
        if (row.origin && row.origin !== 'restore') {
            const originLabel = row.origin === 'claim' ? 'Claimed' : 'Assigned';
            badge += ` <span class="badge-origin-${row.origin}" title="Tracked via Database Discovery (${row.origin})">${originLabel}</span>`;
        }
        return badge;
    }

    function renderDatabaseName(val, row) {
        const name = val || '';
        const staging = STAGING_PATTERN.test(name);
        const stagingBadge = staging
            ? ' <span class="badge-staging" title="Staging database (auto-generated suffix)">staging</span>'
            : '';
        const multiOwnerBadge = (row.owner_count && row.owner_count > 1)
            ? ` <span class="badge-multi-owner" title="${row.owner_count} users have deployed jobs targeting this database">${row.owner_count} owners</span>`
            : '';
        return `<span class="host-cell">
            <div class="host-icon-sm">${icons.database}</div>
            <span>
                <span class="host-alias" title="${escapeAttr(name)}">${escapeHtml(name)}${stagingBadge}${multiOwnerBadge}</span>
            </span>
        </span>`;
    }

    function renderOwner(val, row) {
        if (!val) return '<span class="text-muted">—</span>';
        return `<code class="user-code" title="${escapeAttr(row.owner_username || '')}">${escapeHtml(val)}</code>`;
    }

    function renderDate(val) {
        return formatDate(val);
    }

    function renderActions(val, row) {
        const safeDb = escapeAttr(row.name);

        if (row.managed) {
            return `<div class="cell-actions">
                <button class="action-btn action-btn-remove" title="Remove from management (coming soon)"
                        aria-label="Remove ${safeDb} from management"
                        data-action="remove" data-db="${safeDb}">
                    ${icons.remove}
                </button>
            </div>`;
        }

        return `<div class="cell-actions">
            <button class="action-btn action-btn-claim" title="Claim for myself"
                    aria-label="Claim ${safeDb} for myself"
                    data-action="claim" data-db="${safeDb}">
                ${icons.claim}
            </button>
            <button class="action-btn action-btn-assign" title="Assign to user"
                    aria-label="Assign ${safeDb} to user"
                    data-action="assign" data-db="${safeDb}">
                ${icons.assign}
            </button>
            <button class="action-btn action-btn-remove" title="Remove (coming soon)"
                    aria-label="Remove ${safeDb}"
                    data-action="remove" data-db="${safeDb}">
                ${icons.remove}
            </button>
        </div>`;
    }

    // ==========================================================================
    // Column Definitions
    // ==========================================================================

    const columns = [
        {
            key: 'status',
            label: 'Status',
            sortable: true,
            filterable: true,
            width: '110px',
            render: renderStatus
        },
        {
            key: 'name',
            label: 'Database',
            sortable: true,
            filterable: true,
            filterType: 'text',
            render: renderDatabaseName
        },
        {
            key: 'owner_user_code',
            label: 'Owner',
            sortable: true,
            filterable: true,
            filterType: 'text',
            width: '100px',
            render: renderOwner
        },
        {
            key: 'deployed_at',
            label: 'Deployed',
            sortable: true,
            width: '120px',
            render: renderDate
        },
        {
            key: 'expires_at',
            label: 'Expires',
            sortable: true,
            width: '120px',
            render: renderDate
        },
        {
            key: '_actions',
            label: '',
            sortable: false,
            filterable: false,
            width: '120px',
            render: renderActions
        }
    ];

    // ==========================================================================
    // Stats Update
    // ==========================================================================

    function updateStats(data) {
        if (!data.stats) return;

        const ids = ['stats-section', 'stats-divider', 'stats-managed-section', 'stats-unmanaged-section'];
        ids.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = '';
        });

        const map = {
            'stat-total': data.stats.total,
            'stat-managed': data.stats.managed,
            'stat-unmanaged': data.stats.unmanaged,
        };
        for (const [id, value] of Object.entries(map)) {
            const el = document.getElementById(id);
            if (el) el.textContent = value;
        }
    }

    function hideStats() {
        const ids = ['stats-section', 'stats-divider', 'stats-managed-section', 'stats-unmanaged-section'];
        ids.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
        });
    }

    // ==========================================================================
    // Host Selection
    // ==========================================================================

    window.onHostSelected = function(hostname) {
        currentHostname = hostname;
        setHostInUrl(hostname);

        if (!hostname) {
            destroyTable();
            hideStats();
            showEmptyState();
            return;
        }

        initOrUpdateTable(hostname);
    };

    window.refreshDatabases = function() {
        if (table) {
            table.refresh();
        }
    };

    // ==========================================================================
    // LazyTable Lifecycle
    // ==========================================================================

    function buildFetchUrl(hostname) {
        return `/web/admin/api/database-discovery/databases/paginated?hostname=${encodeURIComponent(hostname)}`;
    }

    function initOrUpdateTable(hostname) {
        const container = document.getElementById('db-table-container');
        if (!container) return;

        // Remove empty state if present
        const emptyEl = document.getElementById('db-empty-state');
        if (emptyEl) emptyEl.style.display = 'none';

        // Show table container
        const tableCard = document.getElementById('db-table-card');
        if (tableCard) tableCard.style.display = '';

        if (table) {
            // Reuse existing table — update URL and refresh
            table.setFetchUrl(buildFetchUrl(hostname));
            table.clearAllFilters();
            table.refresh();
        } else {
            table = new LazyTable({
                container: container,
                columns: columns,
                fetchUrl: buildFetchUrl(hostname),
                rowHeight: 48,
                rowIdKey: 'name',
                emptyMessage: 'No user databases found on this host.',
                onDataLoaded: updateStats,
                onRowRendered: function(tr, row) {
                    tr.setAttribute('data-managed', row.managed ? 'true' : 'false');
                    if (row.is_staging) {
                        tr.classList.add('staging-row');
                    }
                }
            });
        }
    }

    function destroyTable() {
        if (table) {
            table.destroy();
            table = null;
        }
        const tableCard = document.getElementById('db-table-card');
        if (tableCard) tableCard.style.display = 'none';
    }

    function showEmptyState() {
        const el = document.getElementById('db-empty-state');
        if (el) el.style.display = '';
    }

    // ==========================================================================
    // Delegated Click Handler (XSS-safe — no inline onclick)
    // ==========================================================================

    document.addEventListener('click', function(e) {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;

        const action = btn.dataset.action;
        const dbName = btn.dataset.db;
        if (!dbName) return;

        e.stopPropagation();

        switch (action) {
            case 'claim':
                handleClaim(dbName);
                break;
            case 'assign':
                handleAssign(dbName);
                break;
            case 'remove':
                handleRemove(dbName);
                break;
        }
    });

    // ==========================================================================
    // Claim Action
    // ==========================================================================

    async function handleClaim(dbName) {
        const confirmed = await showConfirm(`Claim database "${dbName}" for yourself?`, {
            title: 'Claim Database',
            okText: 'Claim',
            type: 'default'
        });
        if (!confirmed) return;

        try {
            const resp = await fetch('/web/admin/api/database-discovery/claim', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    hostname: currentHostname,
                    database: dbName,
                }),
            });
            const data = await resp.json();

            if (data.success) {
                showToast(data.message, 'success');
                if (table) table.refresh();
            } else {
                showToast(data.message || 'Claim failed', 'error');
            }
        } catch (err) {
            showToast('Error: ' + err.message, 'error');
        }
    }

    // ==========================================================================
    // Assign Modal
    // ==========================================================================

    let assignDbName = '';

    async function handleAssign(dbName) {
        assignDbName = dbName;

        const dbNameEl = document.getElementById('assign-db-name');
        const hostNameEl = document.getElementById('assign-host-name');
        if (dbNameEl) dbNameEl.textContent = dbName;
        if (hostNameEl) hostNameEl.textContent = currentHostname;

        const modal = document.getElementById('assign-modal');
        if (modal) modal.classList.remove('hidden');

        await loadUsersForAssign();
    }

    window.hideAssignModal = function() {
        const modal = document.getElementById('assign-modal');
        if (modal) modal.classList.add('hidden');
        assignDbName = '';
    };

    async function loadUsersForAssign() {
        const select = document.getElementById('assign-user-select');
        if (!select) return;

        if (usersCache) {
            populateUserSelect(select, usersCache);
            return;
        }

        select.innerHTML = '<option value="">Loading users...</option>';
        select.disabled = true;

        try {
            const resp = await fetch('/web/admin/api/database-discovery/users');
            const data = await resp.json();

            if (data.users) {
                usersCache = data.users;
                populateUserSelect(select, data.users);
            } else {
                select.innerHTML = '<option value="">Failed to load users</option>';
            }
        } catch (err) {
            select.innerHTML = '<option value="">Error loading users</option>';
        } finally {
            select.disabled = false;
        }
    }

    function populateUserSelect(select, users) {
        let html = '<option value="">— Select a user —</option>';
        for (const u of users) {
            html += `<option value="${escapeAttr(u.user_id)}">${escapeHtml(u.username)} (${escapeHtml(u.user_code)})</option>`;
        }
        select.innerHTML = html;
    }

    window.submitAssignment = async function(event) {
        event.preventDefault();

        const select = document.getElementById('assign-user-select');
        const targetUserId = select ? select.value : '';

        if (!targetUserId) {
            showToast('Please select a user', 'error');
            return;
        }

        const btn = document.getElementById('assign-btn');
        const btnText = document.getElementById('assign-btn-text');
        if (btn) btn.classList.add('loading');
        if (btnText) btnText.textContent = 'Assigning...';

        try {
            const resp = await fetch('/web/admin/api/database-discovery/assign', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    hostname: currentHostname,
                    database: assignDbName,
                    target_user_id: targetUserId,
                }),
            });
            const data = await resp.json();

            if (data.success) {
                showToast(data.message, 'success');
                hideAssignModal();
                if (table) table.refresh();
            } else {
                showToast(data.message || 'Assignment failed', 'error');
            }
        } catch (err) {
            showToast('Error: ' + err.message, 'error');
        }

        if (btn) btn.classList.remove('loading');
        if (btnText) btnText.textContent = 'Assign';
    };

    // ==========================================================================
    // Remove Action (Placeholder)
    // ==========================================================================

    async function handleRemove(dbName) {
        const confirmed = await showConfirm(`Remove database "${dbName}" from pullDB management?\n\nThis only removes tracking — the database itself is not affected.`, {
            title: 'Remove from pullDB',
            okText: 'Remove',
            type: 'warning'
        });
        if (!confirmed) return;

        try {
            const resp = await fetch('/web/admin/api/database-discovery/remove', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    hostname: currentHostname,
                    database: dbName,
                }),
            });
            const data = await resp.json();

            if (data.success) {
                showToast(data.message, 'success');
                if (table) table.refresh();
            } else {
                showToast(data.message || 'Remove failed', 'info');
            }
        } catch (err) {
            showToast('Error: ' + err.message, 'error');
        }
    }

    // ==========================================================================
    // Keyboard Handlers
    // ==========================================================================

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') hideAssignModal();
    });

    // ==========================================================================
    // Init: restore host from URL on page load
    // ==========================================================================

    (function init() {
        const hostFromUrl = getHostFromUrl();
        if (hostFromUrl) {
            const select = document.getElementById('host-select');
            if (select) {
                for (const opt of select.options) {
                    if (opt.value === hostFromUrl) {
                        select.value = hostFromUrl;
                        currentHostname = hostFromUrl;
                        initOrUpdateTable(hostFromUrl);
                        return;
                    }
                }
            }
        }
    })();

})();
