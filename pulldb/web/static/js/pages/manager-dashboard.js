/**
 * Manager Dashboard Page - LazyTable Implementation
 * HCA Layer: pages (Layer 4)
 * 
 * Manages the team members table using LazyTable widget with:
 * - Paginated data fetching from /api/manager/team
 * - Action buttons for enable/disable and password reset
 * - Event delegation for action handling
 */
(function() {
    'use strict';

    // ==========================================================================
    // SVG Icons
    // ==========================================================================

    const icons = {
        // Key icon SVG (for setting password reset)
        key: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>',
        // Lock icon SVG (for clearing password reset / temp password)
        lock: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>',
        // Server icon SVG (for managing database hosts)
        server: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"></rect><rect x="2" y="14" width="20" height="8" rx="2" ry="2"></rect><line x1="6" y1="6" x2="6.01" y2="6"></line><line x1="6" y1="18" x2="6.01" y2="18"></line></svg>'
    };

    // ==========================================================================
    // Column Renderers
    // ==========================================================================

    /**
     * Render username with entity-cell styling
     */
    function renderUsername(val) {
        return '<span class="entity-cell entity-cell-name">' + (val || '-') + '</span>';
    }

    /**
     * Render user code
     */
    function renderUserCode(val) {
        return '<code class="entity-cell entity-cell-code">' + (val || '-') + '</code>';
    }

    /**
     * Render job count
     */
    function renderJobCount(val) {
        return '<span class="entity-cell entity-cell-count">' + (val || 0) + '</span>';
    }

    /**
     * Render status badge (clickable to toggle)
     */
    function renderStatus(val, row) {
        const isDisabled = !!row.disabled_at;
        const userId = row.user_id;
        const username = row.username || '';
        
        if (isDisabled) {
            return '<button class="team-action-btn" data-action="enable" data-user-id="' + userId + '" data-username="' + username + '" title="Click to enable user">' +
                '<span class="status-badge status-badge-disabled">Disabled</span>' +
                '</button>';
        } else {
            return '<button class="team-action-btn" data-action="disable" data-user-id="' + userId + '" data-username="' + username + '" title="Click to disable user">' +
                '<span class="status-badge status-badge-active">Active</span>' +
                '</button>';
        }
    }

    /**
     * Render action buttons
     */
    function renderActions(val, row) {
        const userId = row.user_id;
        const username = row.username || '';
        const resetPending = row.password_reset_pending;
        
        let html = '';
        
        // Password reset toggle
        if (resetPending) {
            // Red key - active/pending, clicking clears the reset requirement
            html += '<button class="team-action-btn action-btn-danger" data-action="clear-password-reset" data-user-id="' + userId + '" data-username="' + username + '" title="Password Reset Pending - Click to Clear">' + icons.key + '</button>';
        } else {
            // Grey key - inactive, clicking sets the reset requirement
            html += '<button class="team-action-btn action-btn-muted" data-action="reset-password" data-user-id="' + userId + '" data-username="' + username + '" title="Force Password Reset">' + icons.key + '</button>';
        }
        
        // Temp password button
        html += '<button class="team-action-btn action-btn-primary-muted" data-action="assign-temp-password" data-user-id="' + userId + '" data-username="' + username + '" title="Assign Temporary Password">' + icons.lock + '</button>';
        
        // Manage hosts button
        html += '<button class="team-action-btn action-btn-primary" data-action="manage-hosts" data-user-id="' + userId + '" data-username="' + username + '" title="Manage Database Hosts">' + icons.server + '</button>';
        
        return html;
    }

    // ==========================================================================
    // Column Definitions
    // ==========================================================================

    const columns = [
        { 
            key: 'username', 
            label: 'User', 
            sortable: true, 
            filterable: true,
            render: renderUsername
        },
        { 
            key: 'user_code', 
            label: 'Code', 
            sortable: true, 
            filterable: true,
            width: '100px',
            render: renderUserCode
        },
        { 
            key: 'active_jobs', 
            label: 'Jobs', 
            sortable: true,
            width: '100px',
            render: renderJobCount
        },
        { 
            key: 'status', 
            label: 'Status', 
            sortable: true,
            width: '100px',
            render: renderStatus
        },
        { 
            key: 'actions', 
            label: 'Actions', 
            sortable: false,
            width: '120px',
            render: renderActions
        }
    ];

    // ==========================================================================
    // LazyTable Initialization
    // ==========================================================================

    const container = document.getElementById('team-table-container');
    if (!container) {
        console.error('[manager-dashboard] Container #team-table-container not found');
        return;
    }

    const table = new LazyTable({
        container: container,
        columns: columns,
        fetchUrl: '/web/manager/api/team',
        rowHeight: 48,
        rowIdKey: 'user_id',
        emptyMessage: 'You are not managing any users.'
    });

    // Store reference globally for debugging
    window.teamTable = table;

    // ==========================================================================
    // Event Delegation for Action Buttons
    // ==========================================================================

    container.addEventListener('click', async (e) => {
        const btn = e.target.closest('.team-action-btn');
        if (!btn) return;
        
        const action = btn.dataset.action;
        const userId = btn.dataset.userId;
        const username = btn.dataset.username;
        
        // Confirm for disable action
        if (action === 'disable') {
            const confirmed = await showConfirm('Are you sure you want to disable ' + username + '? They will not be able to log in.', {
                title: 'Disable User',
                okText: 'Disable',
                type: 'warning'
            });
            if (!confirmed) return;
        }
        
        // Confirm for reset-password action
        if (action === 'reset-password') {
            const confirmed = await showConfirm('Force password reset for ' + username + '?', {
                title: 'Force Password Reset',
                okText: 'Force Reset',
                type: 'warning'
            });
            if (!confirmed) return;
        }
        
        // Confirm for assign-temp-password action
        if (action === 'assign-temp-password') {
            const confirmed = await showConfirm('Assign a temporary password to ' + username + '?\n\nThis will generate a new password that you must share with the user. The user will be required to change it on next login.', {
                title: 'Assign Temporary Password',
                okText: 'Assign Password',
                type: 'warning'
            });
            if (!confirmed) return;
        }
        
        // Handle manage-hosts action - opens modal, not an endpoint
        if (action === 'manage-hosts') {
            showHostsModal(userId, username);
            return;
        }
        
        // Map action to endpoint
        const endpoints = {
            'enable': '/web/manager/my-team/' + userId + '/enable',
            'disable': '/web/manager/my-team/' + userId + '/disable',
            'reset-password': '/web/manager/my-team/' + userId + '/reset-password',
            'clear-password-reset': '/web/manager/my-team/' + userId + '/clear-password-reset',
            'assign-temp-password': '/web/manager/my-team/' + userId + '/assign-temp-password'
        };
        
        const endpoint = endpoints[action];
        if (!endpoint) return;
        
        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                credentials: 'same-origin'
            });
            
            // Handle assign-temp-password specially - show the generated password
            if (action === 'assign-temp-password') {
                const data = await response.json();
                if (data.success) {
                    showTempPasswordModal(data.username, data.temp_password);
                    table.refresh();
                } else {
                    alert(data.message || 'Failed to assign temp password');
                }
                return;
            }
            
            if (response.ok || response.redirected) {
                // Refresh the table to show updated data
                table.refresh();
            } else {
                console.error('Action failed:', response.status);
            }
        } catch (err) {
            console.error('Action error:', err);
        }
    });
    
    // ==========================================================================
    // Temp Password Modal Functions
    // ==========================================================================
    
    function showTempPasswordModal(username, password) {
        const modal = document.getElementById('temp-password-modal');
        if (modal) {
            document.getElementById('temp-password-username').textContent = username;
            document.getElementById('temp-password-value').textContent = password;
            modal.classList.remove('modal-hidden');
        } else {
            // Fallback if modal not in page
            alert('Temporary password for ' + username + ':\n\n' + password + '\n\nPlease copy this and share with the user securely.');
        }
    }
    
    window.closeTempPasswordModal = function() {
        const modal = document.getElementById('temp-password-modal');
        if (modal) modal.classList.add('modal-hidden');
    };
    
    window.copyTempPassword = async function() {
        const password = document.getElementById('temp-password-value').textContent;
        try {
            await navigator.clipboard.writeText(password);
            alert('Password copied to clipboard');
        } catch (e) {
            // Fallback
            const el = document.createElement('textarea');
            el.value = password;
            document.body.appendChild(el);
            el.select();
            document.execCommand('copy');
            document.body.removeChild(el);
            alert('Password copied to clipboard');
        }
    };

    // ==========================================================================
    // Expose table for external use
    // ==========================================================================

    window.refreshTeamTable = function() {
        if (table) table.refresh();
    };

    // ==========================================================================
    // Manage Database Hosts Modal
    // ==========================================================================

    let allHosts = null;
    let currentHostsUserId = null;
    let currentHostsUsername = null;

    async function loadManagerHosts() {
        if (allHosts !== null) return allHosts;
        try {
            const resp = await fetch('/web/manager/api/hosts');
            const data = await resp.json();
            if (data.success) {
                allHosts = data.hosts;
                return allHosts;
            }
        } catch (e) {
            console.error('Failed to load hosts:', e);
        }
        return [];
    }

    async function loadUserHosts(userId) {
        try {
            const resp = await fetch('/web/manager/my-team/' + userId + '/hosts');
            const data = await resp.json();
            if (data.success) {
                return {
                    host_ids: data.host_ids || [],
                    default_host_id: data.default_host_id
                };
            }
        } catch (e) {
            console.error('Failed to load user hosts:', e);
        }
        return { host_ids: [], default_host_id: null };
    }

    function renderHostsList(hosts, userHostIds, defaultHostId) {
        const listEl = document.getElementById('hosts-list');

        if (!hosts || hosts.length === 0) {
            listEl.innerHTML = '<div class="hosts-empty">No database hosts available. You need host assignments before you can assign hosts to team members.</div>';
            return;
        }

        let html = '\n' +
            '<div class="hosts-header">\n' +
            '    <div class="hosts-header-default">Default</div>\n' +
            '    <div class="hosts-header-auth">Authorized</div>\n' +
            '    <div style="flex: 1;">Host</div>\n' +
            '</div>';

        hosts.forEach(function(host) {
            var isChecked = userHostIds.includes(host.id);
            var isDefault = host.id === defaultHostId;
            var isEnabled = host.enabled !== false;
            var displayName = host.display_name || host.hostname;
            var canBeDefault = isEnabled && isChecked;

            html += '\n<div class="host-item ' + (isEnabled ? '' : 'inactive') + '" data-enabled="' + isEnabled + '">' +
                '<div class="host-item-default ' + (canBeDefault ? '' : 'disabled') + '" id="default-' + host.id + '">' +
                '<input type="radio" name="default_host" value="' + host.id + '"' +
                (canBeDefault ? '' : ' disabled') +
                (isDefault && canBeDefault ? ' checked' : '') + '>' +
                '</div>' +
                '<div class="host-item-auth ' + (isEnabled ? '' : 'disabled') + '">' +
                '<input type="checkbox" id="host-' + host.id + '" value="' + host.id + '"' +
                ' data-enabled="' + isEnabled + '"' +
                (isChecked && isEnabled ? ' checked' : '') +
                (isEnabled ? '' : ' disabled') +
                ' onchange="updateHostSelection()">' +
                '</div>' +
                '<label class="host-item-label" for="host-' + host.id + '">' + displayName + (isEnabled ? '' : ' (inactive)') + '</label>' +
                '</div>';
        });

        listEl.innerHTML = html;
        updateHostSelection();
    }

    window.updateHostSelection = function() {
        var checkboxes = document.querySelectorAll('#hosts-list input[type="checkbox"]');
        var checkedBoxes = document.querySelectorAll('#hosts-list input[type="checkbox"]:checked');

        checkboxes.forEach(function(cb) {
            var isEnabled = cb.dataset.enabled === 'true';
            var defaultDiv = document.getElementById('default-' + cb.value);
            var radio = defaultDiv ? defaultDiv.querySelector('input[type="radio"]') : null;
            if (defaultDiv && radio) {
                var canBeDefault = isEnabled && cb.checked;
                if (canBeDefault) {
                    defaultDiv.classList.remove('disabled');
                    radio.disabled = false;
                } else {
                    defaultDiv.classList.add('disabled');
                    radio.disabled = true;
                    if (radio.checked) radio.checked = false;
                }
            }
        });

        if (checkedBoxes.length === 1) {
            var cb = checkedBoxes[0];
            if (cb.dataset.enabled === 'true') {
                var radio = document.querySelector('#default-' + cb.value + ' input[type="radio"]');
                if (radio) radio.checked = true;
            }
        }

        updateSelectedCount();
    };

    function updateSelectedCount() {
        var checked = document.querySelectorAll('#hosts-list input[type="checkbox"]:checked').length;
        var hasDefault = document.querySelector('#hosts-list input[type="radio"]:checked') !== null;
        var countEl = document.getElementById('hosts-selected-count');

        var text = checked + ' host' + (checked !== 1 ? 's' : '') + ' selected';
        if (checked === 1) {
            text += ' (will be default)';
            countEl.classList.remove('needs-default');
        } else if (checked > 1 && !hasDefault) {
            text += ' \u2014 select a default';
            countEl.classList.add('needs-default');
        } else {
            countEl.classList.remove('needs-default');
        }
        countEl.textContent = text;
    }

    function showHostsModal(userId, username) {
        currentHostsUserId = userId;
        currentHostsUsername = username;

        document.getElementById('hosts-modal-username').textContent = username;
        document.getElementById('hosts-list').innerHTML = '<div class="hosts-empty">Loading hosts...</div>';
        document.getElementById('hosts-modal').classList.remove('modal-hidden');

        Promise.all([
            loadManagerHosts(),
            loadUserHosts(userId)
        ]).then(function(results) {
            renderHostsList(results[0], results[1].host_ids, results[1].default_host_id);
        });
    }

    window.hideHostsModal = function() {
        document.getElementById('hosts-modal').classList.add('modal-hidden');
        currentHostsUserId = null;
        currentHostsUsername = null;
    };

    window.saveUserHosts = async function() {
        if (!currentHostsUserId) return;

        var checkboxes = document.querySelectorAll('#hosts-list input[type="checkbox"]:checked');
        var hostIds = Array.from(checkboxes).map(function(cb) { return cb.value; });

        var defaultRadio = document.querySelector('#hosts-list input[type="radio"]:checked');
        var defaultHostId = defaultRadio ? defaultRadio.value : null;

        if (hostIds.length > 1 && !defaultHostId) {
            showToast('Please select a default host', 'error');
            return;
        }

        var saveBtn = document.getElementById('save-hosts-btn');
        var originalText = saveBtn.innerHTML;
        saveBtn.disabled = true;
        saveBtn.innerHTML = 'Saving...';

        try {
            var resp = await fetch('/web/manager/my-team/' + currentHostsUserId + '/hosts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    host_ids: hostIds,
                    default_host_id: defaultHostId
                })
            });
            var data = await resp.json();

            if (data.success) {
                showToast('Host assignments updated', 'success');
                hideHostsModal();
                table.refresh();
            } else {
                showToast(data.message || 'Failed to update hosts', 'error');
            }
        } catch (e) {
            showToast('Error: ' + e.message, 'error');
        } finally {
            saveBtn.disabled = false;
            saveBtn.innerHTML = originalText;
        }
    };
})();
