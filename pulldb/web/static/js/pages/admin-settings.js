/**
 * Admin Settings Page - Tabbed Category Layout
 * HCA Layer: pages (Layer 4)
 * 
 * Manages system settings with:
 * - Tabbed category navigation with URL state
 * - Global search with tab badge counts and auto-switch
 * - Inline edit/save/reset for each setting
 * - Dangerous setting confirmation modal
 * - Directory creation modal
 * - Export functionality
 */
(function() {
    'use strict';

    // ==========================================================================
    // State
    // ==========================================================================

    let currentTab = 'job_limits';
    let pendingSave = null;
    let pendingCreateDir = null;

    // ==========================================================================
    // Tab Management
    // ==========================================================================

    window.switchTab = function(category) {
        // Update tab buttons
        document.querySelectorAll('.tab').forEach(tab => {
            tab.classList.toggle('tab-active', tab.dataset.category === category);
        });
        
        // Update tab panels
        document.querySelectorAll('.tab-content').forEach(panel => {
            panel.classList.toggle('active', panel.dataset.category === category);
        });
        
        currentTab = category;
        
        // Update URL without reload (for bookmarking)
        const url = new URL(window.location);
        url.searchParams.set('tab', category);
        history.replaceState({}, '', url);
    };

    // ==========================================================================
    // Search with Badge Counts and Auto-Switch
    // ==========================================================================

    window.searchSettings = function(query) {
        query = query.toLowerCase().trim();
        
        // Track matches per category
        const matchCounts = {};
        let firstMatchCategory = null;
        
        document.querySelectorAll('.setting-row').forEach(row => {
            const key = (row.dataset.key || '').toLowerCase();
            const desc = (row.querySelector('.setting-description')?.textContent || '').toLowerCase();
            const matches = query === '' || key.includes(query) || desc.includes(query);
            
            row.classList.toggle('hidden', !matches);
            
            if (matches) {
                const category = row.closest('.tab-content')?.dataset.category;
                if (category) {
                    matchCounts[category] = (matchCounts[category] || 0) + 1;
                    if (!firstMatchCategory) {
                        firstMatchCategory = category;
                    }
                }
            }
        });
        
        // Dim tabs with no matches when searching
        document.querySelectorAll('.tab').forEach(tab => {
            const category = tab.dataset.category;
            const count = matchCounts[category] || 0;
            tab.classList.toggle('no-matches', query && count === 0);
        });
        
        // Auto-switch to first matching tab if current has no matches
        if (query && firstMatchCategory) {
            const currentMatches = matchCounts[currentTab] || 0;
            if (currentMatches === 0) {
                switchTab(firstMatchCategory);
            }
        }
    };

    // Debounced search
    let searchTimeout = null;
    window.handleSearchInput = function(input) {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => searchSettings(input.value), 150);
    };

    // ==========================================================================
    // Edit Mode
    // ==========================================================================

    window.startEdit = function(key) {
        const row = document.querySelector(`.setting-row[data-key="${key}"]`);
        if (!row) return;
        
        row.querySelector('.setting-view')?.classList.add('js-hidden');
        row.querySelector('.setting-edit')?.classList.remove('js-hidden');
        row.querySelector('.edit-btn')?.classList.add('js-hidden');
        row.querySelector('.edit-input')?.focus();
    };

    window.cancelEdit = function(key) {
        const row = document.querySelector(`.setting-row[data-key="${key}"]`);
        if (!row) return;
        
        row.querySelector('.setting-view')?.classList.remove('js-hidden');
        row.querySelector('.setting-edit')?.classList.add('js-hidden');
        row.querySelector('.edit-btn')?.classList.remove('js-hidden');
        
        // Clear validation message
        const validationMsg = row.querySelector('.validation-message');
        if (validationMsg) {
            validationMsg.textContent = '';
            validationMsg.className = 'validation-message';
        }
    };

    // ==========================================================================
    // Save Setting
    // ==========================================================================

    window.saveSetting = async function(event, key) {
        event.preventDefault();
        
        const row = document.querySelector(`.setting-row[data-key="${key}"]`);
        if (!row) return false;
        
        const form = row.querySelector('.edit-form');
        const value = form.querySelector('input[name="value"]').value;
        const isDangerous = row.dataset.dangerous === 'true';
        const validationMsg = row.querySelector('.validation-message');
        
        // Validate first
        try {
            const validateResponse = await fetch(`/web/admin/settings/${key}/validate`, {
                method: 'POST',
                body: new FormData(form),
            });
            const validateResult = await validateResponse.json();
            
            if (!validateResult.valid) {
                validationMsg.textContent = validateResult.error;
                validationMsg.className = 'validation-message error';
                
                if (validateResult.can_create) {
                    validationMsg.innerHTML = `${validateResult.error} <button type="button" class="btn btn-xs btn-primary" onclick="showCreateDirModal('${key}', '${value}')">Create Directory</button>`;
                    validationMsg.className = 'validation-message can-create';
                }
                return false;
            }
        } catch (e) {
            validationMsg.textContent = 'Validation failed';
            validationMsg.className = 'validation-message error';
            return false;
        }
        
        // If dangerous, show confirmation
        if (isDangerous) {
            pendingSave = { key, form, value };
            document.getElementById('confirm-detail').textContent = `Setting: ${key}\nNew value: ${value}`;
            showModal('confirm-modal');
            return false;
        }
        
        // Save directly
        await performSave(key, form);
        return false;
    };

    async function performSave(key, form) {
        const row = document.querySelector(`.setting-row[data-key="${key}"]`);
        const validationMsg = row?.querySelector('.validation-message');
        
        try {
            const response = await fetch(`/web/admin/settings/${key}`, {
                method: 'POST',
                body: new FormData(form),
            });
            const result = await response.json();
            
            if (result.success) {
                showToast(result.message, 'success');
                window.location.reload();
            } else {
                if (validationMsg) {
                    validationMsg.textContent = result.error;
                    validationMsg.className = 'validation-message error';
                    
                    if (result.can_create) {
                        const value = form.querySelector('input[name="value"]').value;
                        validationMsg.innerHTML = `${result.error} <button type="button" class="btn btn-xs btn-primary" onclick="showCreateDirModal('${key}', '${value}')">Create Directory</button>`;
                        validationMsg.className = 'validation-message can-create';
                    }
                }
            }
        } catch (e) {
            if (validationMsg) {
                validationMsg.textContent = 'Failed to save setting';
                validationMsg.className = 'validation-message error';
            }
        }
    }

    // ==========================================================================
    // Reset Setting
    // ==========================================================================

    window.resetSetting = async function(key) {
        const row = document.querySelector(`.setting-row[data-key="${key}"]`);
        if (!row) return;
        
        const isDangerous = row.dataset.dangerous === 'true';
        
        if (isDangerous) {
            pendingSave = { key, isReset: true };
            document.getElementById('confirm-detail').textContent = `Setting: ${key}\nAction: Reset to default`;
            showModal('confirm-modal');
            return;
        }
        
        const confirmed = await showConfirm(`Reset "${key}" to its default value?`, {
            title: 'Reset Setting',
            okText: 'Reset',
            type: 'warning'
        });
        if (confirmed) {
            await performReset(key);
        }
    };

    async function performReset(key) {
        try {
            const response = await fetch(`/web/admin/settings/${key}`, {
                method: 'DELETE',
            });
            const result = await response.json();
            
            if (result.success) {
                showToast(result.message, 'success');
                window.location.reload();
            } else {
                showToast(result.error, 'error');
            }
        } catch (e) {
            showToast('Failed to reset setting', 'error');
        }
    }

    // ==========================================================================
    // Modal Management
    // ==========================================================================

    function showModal(id) {
        document.getElementById(id)?.classList.remove('hidden');
    }

    function hideModal(id) {
        document.getElementById(id)?.classList.add('hidden');
    }

    window.closeConfirmModal = function() {
        hideModal('confirm-modal');
        pendingSave = null;
    };

    window.confirmProceed = async function() {
        if (!pendingSave) return;
        
        hideModal('confirm-modal');
        
        if (pendingSave.isReset) {
            await performReset(pendingSave.key);
        } else {
            await performSave(pendingSave.key, pendingSave.form);
        }
        
        pendingSave = null;
    };

    window.showCreateDirModal = function(key, path) {
        pendingCreateDir = { key, path };
        document.getElementById('create-dir-path').textContent = path;
        showModal('create-dir-modal');
    };

    window.closeCreateDirModal = function() {
        hideModal('create-dir-modal');
        pendingCreateDir = null;
    };

    window.createDirectory = async function() {
        if (!pendingCreateDir) return;
        
        const { key, path } = pendingCreateDir;
        hideModal('create-dir-modal');
        
        try {
            const formData = new FormData();
            formData.append('path', path);
            
            const response = await fetch(`/web/admin/settings/${key}/create-directory`, {
                method: 'POST',
                body: formData,
            });
            const result = await response.json();
            
            if (result.success) {
                showToast(result.message, 'success');
                // Re-trigger save
                const row = document.querySelector(`.setting-row[data-key="${key}"]`);
                const form = row?.querySelector('.edit-form');
                if (form) {
                    await performSave(key, form);
                }
            } else {
                showToast(result.error, 'error');
            }
        } catch (e) {
            showToast('Failed to create directory', 'error');
        }
        
        pendingCreateDir = null;
    };

    // ==========================================================================
    // Export Settings
    // ==========================================================================

    window.exportSettings = function() {
        const settings = {};
        document.querySelectorAll('.setting-row').forEach(row => {
            const key = row.dataset.key;
            const valueEl = row.querySelector('.setting-value');
            const value = valueEl?.textContent?.trim();
            if (value && value !== '(not set)') {
                settings[key] = value;
            }
        });
        
        const blob = new Blob([JSON.stringify(settings, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'pulldb-settings.json';
        a.click();
        URL.revokeObjectURL(url);
    };

    // ==========================================================================
    // Toast Notifications
    // ==========================================================================

    window.showToast = window.showToast || function(message, type = 'info') {
        // Fallback implementation if not defined globally
        const container = document.getElementById('toast-container') || createToastContainer();
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
            <span>${message}</span>
            <button type="button" onclick="this.parentElement.remove()" class="toast-close">&times;</button>
        `;
        container.appendChild(toast);
        
        setTimeout(() => toast.remove(), 5000);
    };

    function createToastContainer() {
        const container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
        return container;
    }

    // ==========================================================================
    // Keyboard Shortcuts
    // ==========================================================================

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            closeConfirmModal();
            closeCreateDirModal();
            // Cancel any active edits
            document.querySelectorAll('.setting-edit:not(.js-hidden)').forEach(edit => {
                const key = edit.closest('.setting-row')?.dataset.key;
                if (key) cancelEdit(key);
            });
        }
    });

    // ==========================================================================
    // Initialize
    // ==========================================================================

    document.addEventListener('DOMContentLoaded', function() {
        // Check URL for initial tab
        const urlParams = new URLSearchParams(window.location.search);
        const tabParam = urlParams.get('tab');
        if (tabParam) {
            switchTab(tabParam);
        }
    });

})();
