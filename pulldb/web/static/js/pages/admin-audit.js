/**
 * Admin Audit Page - LazyTable Implementation
 * HCA Layer: pages (Layer 4)
 * 
 * Manages the audit logs table using LazyTable widget with:
 * - Paginated data fetching from /web/admin/audit/api/logs
 * - Filter support for actor, target, and action
 * - URL state management for bookmarking
 * - Stats update on data load
 */
(function() {
    'use strict';

    // ==========================================================================
    // Configuration from Data Attributes
    // ==========================================================================

    const container = document.getElementById('audit-table-container');
    if (!container) {
        console.error('[admin-audit] Container #audit-table-container not found');
        return;
    }

    // Read initial filter values from data attributes (set by template)
    let currentActorId = container.dataset.filterActor || '';
    let currentTargetId = container.dataset.filterTarget || '';
    let currentAction = '';

    // ==========================================================================
    // Column Renderers
    // ==========================================================================

    /**
     * Format timestamp for display
     */
    const formatTime = (val) => {
        if (!val) return '-';
        const d = new Date(val);
        const date = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        const time = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
        return `<span class="cell-nowrap">${date} ${time}</span>`;
    };

    /**
     * Render actor username with link to filter
     */
    const renderActor = (val, row) => {
        if (!val || val === '(unknown)') return '<span class="cell-empty">-</span>';
        return `<a href="/web/admin/audit?actor_id=${row.actor_user_id}" class="user-link">${val}</a>`;
    };

    /**
     * Render target username with link to filter
     */
    const renderTarget = (val, row) => {
        if (!val || val === '-') return '<span class="cell-empty">-</span>';
        return `<a href="/web/admin/audit?target_id=${row.target_user_id}" class="user-link">${val}</a>`;
    };

    /**
     * Render action with badge color
     */
    const renderAction = (val) => {
        if (!val) return '-';
        
        // Determine badge class based on action prefix
        let badgeClass = '';
        if (val.includes('create') || val.includes('add')) badgeClass = 'create';
        else if (val.includes('update') || val.includes('change')) badgeClass = 'update';
        else if (val.includes('delete') || val.includes('remove')) badgeClass = 'delete';
        else if (val.includes('cancel')) badgeClass = 'cancel';
        else if (val.includes('submit')) badgeClass = 'submit';
        else if (val.includes('password') || val.includes('reset')) badgeClass = 'password';
        else if (val.includes('setting')) badgeClass = 'setting';
        
        return `<span class="action-badge ${badgeClass}">${val}</span>`;
    };

    /**
     * Render detail with truncation
     */
    const renderDetail = (val) => {
        if (!val || val === '-') return '<span class="cell-empty">-</span>';
        return `<span class="detail-cell" title="${val}">${val}</span>`;
    };

    // ==========================================================================
    // Column Definitions
    // ==========================================================================

    const columns = [
        { 
            key: 'created_at', 
            label: 'Time', 
            sortable: true,
            width: '140px',
            render: formatTime
        },
        { 
            key: 'actor_username', 
            label: 'Actor', 
            sortable: true,
            filterable: true,
            width: '140px',
            render: renderActor
        },
        { 
            key: 'action', 
            label: 'Action', 
            sortable: true,
            filterable: true,
            width: '180px',
            render: renderAction
        },
        { 
            key: 'target_username', 
            label: 'Target', 
            sortable: true,
            filterable: true,
            width: '140px',
            render: renderTarget
        },
        { 
            key: 'detail', 
            label: 'Detail', 
            sortable: false,
            filterable: false,
            render: renderDetail
        }
    ];

    // ==========================================================================
    // URL & Fetch Helpers
    // ==========================================================================

    /**
     * Build fetch URL with current filters
     */
    function buildFetchUrl() {
        let url = '/web/admin/audit/api/logs';
        const params = new URLSearchParams();
        
        if (currentActorId) params.append('actor_id', currentActorId);
        if (currentTargetId) params.append('target_id', currentTargetId);
        if (currentAction) params.append('action', currentAction);
        
        const queryString = params.toString();
        return queryString ? `${url}?${queryString}` : url;
    }

    // ==========================================================================
    // Stats Update
    // ==========================================================================

    /**
     * Update stats from response
     */
    function updateStats(data) {
        if (data.total !== undefined) {
            const statEl = document.getElementById('stat-total');
            if (statEl) {
                statEl.textContent = data.total;
            }
        }
    }

    // ==========================================================================
    // LazyTable Initialization
    // ==========================================================================

    let table = new LazyTable({
        container: container,
        columns: columns,
        fetchUrl: buildFetchUrl(),
        rowHeight: 48,
        rowIdKey: 'audit_id',
        emptyMessage: 'No audit logs found',
        onDataLoaded: updateStats
    });

    // ==========================================================================
    // Filter Functions (exposed globally for template event handlers)
    // ==========================================================================

    /**
     * Apply filters function
     */
    window.applyFilters = function() {
        currentActorId = document.getElementById('filter-actor').value;
        currentTargetId = document.getElementById('filter-target').value;
        currentAction = document.getElementById('filter-action').value;
        
        // Update URL without reload (for bookmarking)
        const params = new URLSearchParams();
        if (currentActorId) params.append('actor_id', currentActorId);
        if (currentTargetId) params.append('target_id', currentTargetId);
        if (currentAction) params.append('action', currentAction);
        
        const newUrl = params.toString() 
            ? `${window.location.pathname}?${params.toString()}`
            : window.location.pathname;
        window.history.replaceState({}, '', newUrl);
        
        // Re-initialize table with new URL
        table.destroy();
        table = new LazyTable({
            container: container,
            columns: columns,
            fetchUrl: buildFetchUrl(),
            rowHeight: 48,
            rowIdKey: 'audit_id',
            emptyMessage: 'No audit logs found',
            onDataLoaded: updateStats
        });
    };

    /**
     * Clear all filters
     */
    window.clearFilters = function() {
        document.getElementById('filter-actor').value = '';
        document.getElementById('filter-target').value = '';
        document.getElementById('filter-action').value = '';
        applyFilters();
    };

    // ==========================================================================
    // Expose table for external use
    // ==========================================================================

    window.auditTable = table;
    window.refreshAuditTable = function() {
        if (table) table.refresh();
    };
})();
