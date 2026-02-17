/**
 * Admin Overlord Companies Page - LazyTable Implementation
 * HCA Layer: pages (Layer 4)
 * 
 * Manages the overlord companies table with:
 * - Paginated data from /web/admin/api/overlord/companies/paginated
 * - Managed/Unmanaged row distinction
 * - CRUD actions (create, view/edit, delete)
 * - Claim/Release operations
 * - Stats update on data load
 */
(function() {
    'use strict';

    // ==========================================================================
    // SVG Icons
    // ==========================================================================

    const icons = {
        managed: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>',
        unmanaged: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>',
        view: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
        edit: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
        company: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 20a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8l-7 5V8l-7 5V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/></svg>',
    };

    // ==========================================================================
    // Column Renderers
    // ==========================================================================

    function renderManagedStatus(val, row) {
        if (row._managed) {
            const status = row._tracking_status || 'claimed';
            const badgeClass = status === 'synced' ? 'managed' : 'claimed';
            const label = status === 'synced' ? 'Managed' : 'Claimed';
            return `<span class="badge-managed ${badgeClass}" title="Managed by job ${row._job_id || 'unknown'}">${icons.managed} ${label}</span>`;
        }
        return `<span class="badge-managed unmanaged">${icons.unmanaged} Unmanaged</span>`;
    }

    function renderDatabase(val, row) {
        const name = val || '';
        const companyName = row.company || '';
        const subtitle = companyName && companyName !== name ? `<div class="db-subtitle text-muted text-xs" title="${escapeHtml(companyName)}">${escapeHtml(companyName)}</div>` : '';
        return `<span class="host-cell">
            <div class="host-icon-sm">${icons.company}</div>
            <span>
                <span class="host-alias" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
                ${subtitle}
            </span>
        </span>`;
    }

    function renderHost(val) {
        if (!val) return '<span class="text-muted">—</span>';
        // Shorten long hostnames for display
        const display = val.length > 35 ? val.substring(0, 32) + '...' : val;
        return `<span title="${escapeHtml(val)}">${escapeHtml(display)}</span>`;
    }

    function renderSubdomain(val) {
        if (!val) return '<span class="text-muted">—</span>';
        return `<code>${escapeHtml(val)}</code>`;
    }

    function renderVisible(val) {
        if (val === 1 || val === '1') return '<span class="text-success">Yes</span>';
        if (val === 0 || val === '0') return '<span class="text-muted">No</span>';
        return '<span class="text-muted">—</span>';
    }

    function renderUserCode(val, row) {
        if (!val) return '<span class="text-muted">—</span>';
        return `<code style="font-size: var(--text-xs); background: var(--bg-muted); padding: 2px 6px; border-radius: var(--radius-sm);">${escapeHtml(val)}</code>`;
    }

    function renderActions(val, row) {
        const id = row.companyID;
        if (row._managed) {
            return `<div class="cell-actions">
                <button class="action-btn action-btn-view" title="Edit" onclick="viewCompany(${id}, event)">
                    ${icons.edit}
                </button>
            </div>`;
        }
        return `<div class="cell-actions">
            <button class="action-btn action-btn-view" title="View" onclick="viewCompany(${id}, event)">
                ${icons.view}
            </button>
        </div>`;
    }

    function escapeHtml(str) {
        if (!str) return '';
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    // ==========================================================================
    // Column Definitions
    // ==========================================================================

    const columns = [
        {
            key: '_managed',
            label: 'Status',
            sortable: true,
            filterable: true,
            width: '110px',
            render: renderManagedStatus
        },
        {
            key: 'companyID',
            label: 'ID',
            sortable: true,
            width: '60px',
        },
        {
            key: 'database',
            label: 'Database',
            sortable: true,
            filterable: true,
            filterType: 'text',
            width: '200px',
            render: renderDatabase
        },
        {
            key: 'subdomain',
            label: 'Subdomain',
            sortable: true,
            filterable: true,
            filterType: 'text',
            width: '120px',
            render: renderSubdomain
        },
        {
            key: 'dbHost',
            label: 'DB Host',
            sortable: true,
            filterable: true,
            filterType: 'text',
            width: '200px',
            render: renderHost
        },
        {
            key: 'dbHostRead',
            label: 'DB Host Read',
            sortable: true,
            width: '180px',
            render: renderHost
        },
        {
            key: 'visible',
            label: 'Vis',
            sortable: true,
            filterable: true,
            width: '55px',
            tooltip: 'Visible flag — whether the company is active in the routing table',
            render: renderVisible
        },
        {
            key: '_user_code',
            label: 'User',
            sortable: true,
            filterable: true,
            filterType: 'text',
            width: '90px',
            tooltip: 'User code of the job owner (managed rows only)',
            render: renderUserCode
        },
        {
            key: '_actions',
            label: '',
            sortable: false,
            filterable: false,
            width: '60px',
            render: renderActions
        }
    ];

    // ==========================================================================
    // Stats Update
    // ==========================================================================

    function updateStats(data) {
        if (data.stats) {
            const statsMap = {
                'stat-total': data.stats.total,
                'stat-managed': data.stats.managed,
                'stat-unmanaged': data.stats.unmanaged,
            };
            for (const [id, value] of Object.entries(statsMap)) {
                const el = document.getElementById(id);
                if (el) el.textContent = value;
            }
        }
    }

    // ==========================================================================
    // LazyTable Initialization
    // ==========================================================================

    let table = null;

    function initTable() {
        const container = document.getElementById('companies-table-container');
        if (!container) return; // Overlord not enabled

        table = new LazyTable({
            container: container,
            columns: columns,
            fetchUrl: '/web/admin/api/overlord/companies/paginated',
            rowHeight: 52,
            rowIdKey: 'companyID',
            emptyMessage: 'No companies found in the overlord table',
            onDataLoaded: updateStats,
            onRowClick: (row) => {
                window.location.href = `/web/admin/overlord/companies/${row.companyID}`;
            },
            onRowRendered: (tr, row) => {
                tr.setAttribute('data-managed', row._managed ? 'true' : 'false');
            }
        });
    }

    // ==========================================================================
    // Action Handlers
    // ==========================================================================

    window.viewCompany = function(companyId, event) {
        if (event) event.stopPropagation();
        window.location.href = `/web/admin/overlord/companies/${companyId}`;
    };

    // ==========================================================================
    // Create Modal
    // ==========================================================================

    window.showCreateModal = function() {
        const modal = document.getElementById('create-company-modal');
        if (modal) {
            modal.classList.remove('hidden');
            const form = document.getElementById('create-company-form');
            if (form) form.reset();
        }
    };

    window.hideCreateModal = function() {
        const modal = document.getElementById('create-company-modal');
        if (modal) modal.classList.add('hidden');
    };

    window.createCompany = async function(event) {
        event.preventDefault();

        const form = document.getElementById('create-company-form');
        const formData = new FormData(form);
        const btn = document.getElementById('create-btn');
        const btnText = document.getElementById('create-btn-text');

        // Build JSON body from form
        const body = {};
        for (const [key, value] of formData.entries()) {
            if (value !== '') {
                body[key] = key === 'visible' ? parseInt(value, 10) : value;
            }
        }

        btn.classList.add('loading');
        btnText.textContent = 'Creating...';

        try {
            const resp = await fetch('/web/admin/api/overlord/companies/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();

            if (data.success) {
                showToast(data.message, 'success');
                hideCreateModal();
                if (data.company_id) {
                    window.location.href = `/web/admin/overlord/companies/${data.company_id}`;
                } else if (table) {
                    table.refresh();
                }
            } else {
                showToast(data.message || 'Create failed', 'error');
                btn.classList.remove('loading');
                btnText.textContent = 'Create Company';
            }
        } catch (e) {
            showToast('Error: ' + e.message, 'error');
            btn.classList.remove('loading');
            btnText.textContent = 'Create Company';
        }
    };

    // ==========================================================================
    // Event Listeners
    // ==========================================================================

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') hideCreateModal();
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initTable);
    } else {
        initTable();
    }

    window.refreshCompaniesTable = function() {
        if (table) table.refresh();
    };

})();
