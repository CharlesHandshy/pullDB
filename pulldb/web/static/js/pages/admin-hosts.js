/**
 * Admin Hosts Page - LazyTable Implementation
 * HCA Layer: pages (Layer 4)
 * 
 * Manages the hosts table using LazyTable widget with:
 * - Paginated data fetching from /web/admin/api/hosts/paginated
 * - Status toggle actions via fetch API
 * - Row click navigation to host detail
 * - Stats update on data load
 */
(function() {
    'use strict';

    // ==========================================================================
    // SVG Icons
    // ==========================================================================

    const icons = {
        database: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>',
        checkmark: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>',
        disabled: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="4.93" x2="19.07" y1="4.93" y2="19.07"/></svg>',
        view: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
        toggle: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 11-6.219-8.56"/><polyline points="21 3 21 9 15 9"/></svg>',
    };

    // ==========================================================================
    // Column Renderers
    // ==========================================================================

    /**
     * Render host cell with icon and alias/hostname
     */
    function renderHostCell(val, row) {
        const disabledClass = row.enabled ? '' : ' disabled';
        const displayName = row.host_alias || row.hostname;
        const tooltip = row.host_alias ? row.hostname : '';
        const titleAttr = tooltip ? ` title="${tooltip}"` : '';
        
        return `<span class="host-cell">
            <div class="host-icon-sm${disabledClass}">${icons.database}</div>
            <span class="host-alias"${titleAttr}>${displayName}</span>
        </span>`;
    }

    /**
     * Render status badge (clickable to toggle)
     */
    function renderStatus(val, row) {
        const isEnabled = row.enabled;
        const statusClass = isEnabled ? 'enabled' : 'disabled';
        const icon = isEnabled ? icons.checkmark : icons.disabled;
        const label = isEnabled ? 'Enabled' : 'Disabled';
        const tooltip = isEnabled ? 'Click to disable host' : 'Click to enable host';
        
        return `<span class="status-badge ${statusClass} clickable" 
                      title="${tooltip}" 
                      onclick="toggleHostStatus('${row.id}', '${row.display_name}', event)">
            ${icon}
            ${label}
        </span>`;
    }

    /**
     * Render job count (running/max)
     */
    function renderJobCount(val, row, key) {
        if (key === 'running_count') {
            const tooltip = `${row.running_count} running of ${row.max_running_jobs} max concurrent`;
            return `<span class="job-count" title="${tooltip}">${row.running_count}/${row.max_running_jobs}</span>`;
        } else if (key === 'active_restores') {
            const tooltip = `${row.active_restores} active of ${row.max_active_jobs} queue capacity`;
            return `<span class="job-count" title="${tooltip}">${row.active_restores}/${row.max_active_jobs}</span>`;
        }
        return `<span class="job-count">${val || 0}</span>`;
    }

    /**
     * Render date
     */
    function renderDate(val) {
        if (!val) return '-';
        const d = new Date(val);
        return d.toLocaleDateString();
    }

    /**
     * Render actions column
     */
    function renderActions(val, row) {
        return `<div class="cell-actions">
            <button class="action-btn action-btn-view" 
                    title="View Details" 
                    onclick="viewHost('${row.id}', event)">
                ${icons.view}
            </button>
        </div>`;
    }

    // ==========================================================================
    // Column Definitions
    // ==========================================================================

    const columns = [
        {
            key: 'display_name',
            label: 'Host',
            sortable: true,
            filterable: true,
            filterType: 'text',
            width: '200px',
            render: renderHostCell
        },
        {
            key: 'enabled',
            label: 'Status',
            sortable: true,
            filterable: true,
            width: '100px',
            render: renderStatus
        },
        {
            key: 'running_count',
            label: 'Run',
            sortable: true,
            width: '80px',
            tooltip: 'Running / Max Concurrent: Currently running jobs vs max allowed simultaneous restores',
            render: (val, row) => renderJobCount(val, row, 'running_count')
        },
        {
            key: 'active_restores',
            label: 'Act',
            sortable: true,
            width: '80px',
            tooltip: 'Active / Queue Size: Running + queued jobs vs max queue capacity',
            render: (val, row) => renderJobCount(val, row, 'active_restores')
        },
        {
            key: 'total_restores',
            label: 'Tot',
            sortable: true,
            width: '80px',
            tooltip: 'Total Restores: All-time completed restore count for this host',
            render: (val) => `<span class="job-count" title="${val || 0} total restores completed">${val || 0}</span>`
        },
        {
            key: 'created_at',
            label: 'Added',
            sortable: true,
            width: '100px',
            render: renderDate
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
                'stat-enabled': data.stats.enabled,
                'stat-disabled': data.stats.disabled,
                'stat-active': data.stats.active_restores,
            };
            
            for (const [id, value] of Object.entries(statsMap)) {
                const el = document.getElementById(id);
                if (el) {
                    el.textContent = value;
                }
            }
            
            // Show/hide active restores stat
            const activeContainer = document.getElementById('stat-active-container');
            if (activeContainer) {
                activeContainer.style.display = data.stats.active_restores > 0 ? '' : 'none';
            }
        }
    }

    // ==========================================================================
    // LazyTable Initialization
    // ==========================================================================

    let table = null;

    function initTable() {
        const container = document.getElementById('hosts-table-container');
        if (!container) {
            console.error('[admin-hosts] Container #hosts-table-container not found');
            return;
        }

        table = new LazyTable({
            container: container,
            columns: columns,
            fetchUrl: '/web/admin/api/hosts/paginated',
            rowHeight: 48,
            rowIdKey: 'id',
            emptyMessage: 'No hosts configured',
            onDataLoaded: updateStats,
            onRowClick: (row) => {
                window.location.href = `/web/admin/hosts/${row.id}`;
            }
        });
    }

    // ==========================================================================
    // Action Handlers
    // ==========================================================================

    /**
     * Toggle host enabled/disabled status
     */
    window.toggleHostStatus = async function(hostId, displayName, event) {
        // Stop row click propagation
        if (event) {
            event.stopPropagation();
        }

        try {
            const resp = await fetch(`/web/admin/api/hosts/${hostId}/toggle`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await resp.json();
            
            if (data.success) {
                showToast(data.message, 'success');
                if (table) {
                    table.refresh();
                }
            } else {
                showToast(data.message || 'Failed to toggle host status', 'error');
            }
        } catch (e) {
            showToast('Error: ' + e.message, 'error');
        }
    };

    /**
     * Navigate to host detail page
     */
    window.viewHost = function(hostId, event) {
        if (event) {
            event.stopPropagation();
        }
        window.location.href = `/web/admin/hosts/${hostId}`;
    };

    // ==========================================================================
    // Modal Functions
    // ==========================================================================

    window.showAddHostModal = function() {
        const modal = document.getElementById('add-host-modal');
        if (modal) {
            modal.classList.remove('modal-hidden');
            resetProvisionForm();
        }
    };

    window.hideAddHostModal = function() {
        const modal = document.getElementById('add-host-modal');
        if (modal) {
            modal.classList.add('modal-hidden');
            resetProvisionForm();
        }
    };

    function resetProvisionForm() {
        const form = document.getElementById('add-host-form');
        if (form) form.reset();
        
        const statusDiv = document.getElementById('provision-status');
        if (statusDiv) statusDiv.style.display = 'none';
        
        const stepsDiv = document.getElementById('provision-steps');
        if (stepsDiv) stepsDiv.innerHTML = '';
        
        const messageDiv = document.getElementById('provision-message');
        if (messageDiv) {
            messageDiv.innerHTML = '';
            messageDiv.className = 'provision-message';
        }
        
        const aliasStatus = document.getElementById('alias-status');
        if (aliasStatus) aliasStatus.innerHTML = '';
        
        const btn = document.getElementById('provision-btn');
        if (btn) btn.classList.remove('loading');
        
        const btnText = document.getElementById('provision-btn-text');
        if (btnText) btnText.textContent = 'Add Host';
    }

    // ==========================================================================
    // Provisioning Function
    // ==========================================================================

    window.provisionHost = async function(event) {
        event.preventDefault();
        
        const form = document.getElementById('add-host-form');
        const formData = new FormData(form);
        const btn = document.getElementById('provision-btn');
        const btnText = document.getElementById('provision-btn-text');
        const statusDiv = document.getElementById('provision-status');
        const stepsDiv = document.getElementById('provision-steps');
        const messageDiv = document.getElementById('provision-message');
        
        // Show loading state
        btn.classList.add('loading');
        btnText.textContent = 'Provisioning...';
        statusDiv.style.display = 'block';
        stepsDiv.innerHTML = `<div class="provision-step running">
            <div class="provision-step-icon">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 12a9 9 0 11-6.219-8.56"/>
                </svg>
            </div>
            <div class="provision-step-text">Starting provisioning...</div>
        </div>`;
        messageDiv.innerHTML = '';
        messageDiv.className = 'provision-message';
        
        try {
            const response = await fetch('/web/admin/hosts/provision', {
                method: 'POST',
                body: formData,
            });
            
            const result = await response.json();
            
            // Display steps
            stepsDiv.innerHTML = '';
            if (result.steps && result.steps.length > 0) {
                result.steps.forEach(step => {
                    const stepClass = step.success ? 'success' : 'error';
                    const icon = step.success 
                        ? '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>'
                        : '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" x2="9" y1="9" y2="15"/><line x1="9" x2="15" y1="9" y2="15"/></svg>';
                    
                    let stepHtml = `<div class="provision-step ${stepClass}">
                        <div class="provision-step-icon">${icon}</div>
                        <div class="provision-step-text">${step.message}`;
                    
                    if (step.details) {
                        stepHtml += `<div class="provision-step-details">${step.details}</div>`;
                    }
                    
                    stepHtml += '</div></div>';
                    stepsDiv.innerHTML += stepHtml;
                });
            }
            
            // Display final message
            if (result.success) {
                messageDiv.className = 'provision-message success';
                messageDiv.innerHTML = '✓ ' + result.message;
                
                // Redirect to host detail after short delay
                setTimeout(() => {
                    if (result.host_id) {
                        window.location.href = '/web/admin/hosts/' + result.host_id + '?added=1';
                    } else {
                        window.location.href = '/web/admin/hosts?added=1';
                    }
                }, 1500);
            } else {
                messageDiv.className = 'provision-message error';
                messageDiv.innerHTML = '✗ ' + result.message;
                
                // Reset button for retry
                btn.classList.remove('loading');
                btnText.textContent = 'Retry';
            }
            
        } catch (error) {
            stepsDiv.innerHTML = '';
            messageDiv.className = 'provision-message error';
            messageDiv.innerHTML = '✗ Network error: ' + error.message;
            btn.classList.remove('loading');
            btnText.textContent = 'Retry';
        }
    };

    // ==========================================================================
    // HTMX Alias Check Handler
    // ==========================================================================

    document.body.addEventListener('htmx:afterSwap', function(evt) {
        if (evt.detail.target.id === 'alias-status') {
            try {
                const data = JSON.parse(evt.detail.target.textContent);
                let statusClass = '';
                let statusText = '';
                
                if (data.status === 'new') {
                    statusClass = 'status-new';
                    statusText = '✓ New';
                } else if (data.status === 'existing') {
                    statusClass = 'status-existing';
                    statusText = '↻ Update';
                } else if (data.status === 'credentials_found') {
                    statusClass = 'status-credentials';
                    statusText = '⚡ Reuse';
                }
                
                evt.detail.target.className = 'input-status ' + statusClass;
                evt.detail.target.textContent = statusText;
                evt.detail.target.title = data.message || '';
            } catch (e) {
                // Not JSON, just display as-is
            }
        }
    });

    // ==========================================================================
    // Event Listeners
    // ==========================================================================

    // Close modal on Escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            hideAddHostModal();
        }
    });

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initTable);
    } else {
        initTable();
    }

    // Expose table refresh for external use
    window.refreshHostsTable = function() {
        if (table) {
            table.refresh();
        }
    };

})();
