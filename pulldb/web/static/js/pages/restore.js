/**
 * pullDB Restore Page - Simplified Customer Database Selection
 * 
 * Flow:
 * 1. Date selection (default: 7 days ago to today)
 * 2. Customer search (debounced, starts at 3 chars)
 * 3. Backup selection from S3 results
 */
(function() {
    'use strict';

    // =============================================================================
    // Configuration
    // =============================================================================
    
    const config = window.restoreConfig || {};
    const MIN_SEARCH_CHARS = 3;
    const DEBOUNCE_MS = 400;

    // =============================================================================
    // State
    // =============================================================================
    
    let selectedCustomer = config.initialCustomer || '';
    let selectedBackup = null;
    let debounceTimer = null;
    let abortController = null;
    let isQaMode = false;

    // =============================================================================
    // DOM Helpers
    // =============================================================================
    
    const $ = (id) => document.getElementById(id);
    const show = (el) => el && el.classList.remove('js-hidden');
    const hide = (el) => el && el.classList.add('js-hidden');

    // =============================================================================
    // Date Functions
    // =============================================================================
    
    function getDefaultDate() {
        const d = new Date();
        d.setDate(d.getDate() - 7);
        return d.toISOString().split('T')[0];
    }

    function initDatePicker() {
        const dateInput = $('date-from');
        const resetBtn = $('reset-date-btn');
        
        if (!dateInput) return;
        
        // Set default to 7 days ago
        dateInput.value = getDefaultDate();
        
        // Reset button
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                dateInput.value = getDefaultDate();
                if (selectedCustomer) {
                    loadBackups();
                }
            });
        }
        
        // Reload backups when date changes
        dateInput.addEventListener('change', () => {
            if (!dateInput.value) {
                dateInput.value = getDefaultDate();
            }
            if (selectedCustomer) {
                clearBackupSelection();
                loadBackups();
            }
        });
    }

    // =============================================================================
    // Customer Search Functions
    // =============================================================================
    
    function initCustomerSearch() {
        const searchInput = $('customer-search');
        const clearBtn = $('clear-customer-btn');
        
        if (!searchInput) return;
        
        // Debounced search on input
        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.trim();
            
            if (debounceTimer) clearTimeout(debounceTimer);
            
            if (query.length < MIN_SEARCH_CHARS) {
                updateSearchStatus(query.length > 0 ? `Type ${MIN_SEARCH_CHARS - query.length} more...` : '');
                hideResults();
                return;
            }
            
            updateSearchStatus('Searching...');
            
            debounceTimer = setTimeout(() => {
                searchCustomers(query);
            }, DEBOUNCE_MS);
        });
        
        // Keyboard navigation
        searchInput.addEventListener('keydown', (e) => {
            const results = $('customer-results');
            const items = results ? results.querySelectorAll('.result-item') : [];
            const highlighted = results ? results.querySelector('.result-item.highlighted') : null;
            let idx = highlighted ? Array.from(items).indexOf(highlighted) : -1;
            
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                idx = Math.min(idx + 1, items.length - 1);
                highlightItem(items, idx);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                idx = Math.max(idx - 1, 0);
                highlightItem(items, idx);
            } else if (e.key === 'Enter' && highlighted) {
                e.preventDefault();
                highlighted.click();
            } else if (e.key === 'Escape') {
                hideResults();
            }
        });
        
        // Clear selection
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                clearCustomerSelection();
                searchInput.focus();
            });
        }
        
        // Click outside to close
        document.addEventListener('click', (e) => {
            const container = $('step-customer');
            if (container && !container.contains(e.target)) {
                hideResults();
            }
        });
    }
    
    async function searchCustomers(query) {
        if (abortController) abortController.abort();
        abortController = new AbortController();
        
        try {
            const url = `/web/restore/search-customers?q=${encodeURIComponent(query + '*')}&limit=20`;
            const response = await fetch(url, {
                signal: abortController.signal,
                headers: { 'Accept': 'application/json' }
            });
            
            if (!response.ok) throw new Error('Search failed');
            
            const data = await response.json();
            renderCustomerResults(data.results || [], query);
            
        } catch (err) {
            if (err.name !== 'AbortError') {
                console.error('Customer search error:', err);
                updateSearchStatus('Search failed');
            }
        }
    }
    
    function renderCustomerResults(results, query) {
        const container = $('customer-results');
        if (!container) return;
        
        if (results.length === 0) {
            container.innerHTML = '<div class="no-results">No customers found</div>';
            updateSearchStatus('0 found');
            showResults();
            return;
        }
        
        container.innerHTML = results.map((r, i) => {
            const name = r.value || r.label || r;
            return `<div class="result-item" data-value="${escapeAttr(name)}">${escapeHtml(name)}</div>`;
        }).join('');
        
        // Add click handlers
        container.querySelectorAll('.result-item').forEach(item => {
            item.addEventListener('click', () => {
                selectCustomer(item.dataset.value);
            });
            item.addEventListener('mouseenter', () => {
                container.querySelectorAll('.result-item').forEach(i => i.classList.remove('highlighted'));
                item.classList.add('highlighted');
            });
        });
        
        updateSearchStatus(`${results.length} found`);
        showResults();
    }
    
    function highlightMatch(text, query) {
        const escaped = escapeHtml(text);
        const q = query.toLowerCase().replace(/\*$/, '');
        const idx = text.toLowerCase().indexOf(q);
        if (idx === -1) return escaped;
        
        return escapeHtml(text.substring(0, idx)) + 
               '<mark>' + escapeHtml(text.substring(idx, idx + q.length)) + '</mark>' + 
               escapeHtml(text.substring(idx + q.length));
    }
    
    function highlightItem(items, idx) {
        items.forEach((item, i) => {
            item.classList.toggle('highlighted', i === idx);
        });
        if (items[idx]) {
            items[idx].scrollIntoView({ block: 'nearest' });
        }
    }
    
    function selectCustomer(name) {
        selectedCustomer = name;
        
        // Update hidden input
        const hidden = $('customer');
        if (hidden) hidden.value = name;
        
        // Update UI
        const nameEl = $('selected-customer-name');
        if (nameEl) nameEl.textContent = name;
        
        hide($('customer-search-mode'));
        show($('customer-selected-mode'));
        hideResults();
        
        // Load backups
        loadBackups();
        updateTargetPreview();
        updateSummary();
    }
    
    function clearCustomerSelection() {
        selectedCustomer = '';
        
        const hidden = $('customer');
        if (hidden) hidden.value = '';
        
        const searchInput = $('customer-search');
        if (searchInput) searchInput.value = '';
        
        show($('customer-search-mode'));
        hide($('customer-selected-mode'));
        updateSearchStatus('');
        
        clearBackupSelection();
        showBackupWaiting();
        hideTargetPreview();
        updateSummary();
    }
    
    function updateSearchStatus(text) {
        const el = $('search-status');
        if (el) el.textContent = text;
    }
    
    function showResults() {
        const el = $('customer-results');
        if (el) el.style.display = 'block';
    }
    
    function hideResults() {
        const el = $('customer-results');
        if (el) el.style.display = 'none';
    }

    // =============================================================================
    // Backup Functions
    // =============================================================================
    
    function loadBackups() {
        if (!selectedCustomer) return;
        
        // Show loading state
        hide($('backup-waiting'));
        show($('backup-loading'));
        hide($('backup-list'));
        hide($('backup-selected-mode'));
        
        const countEl = $('backup-count');
        if (countEl) countEl.textContent = '';
        
        // Build URL
        const dateInput = $('date-from');
        const dateValue = dateInput ? dateInput.value : '';
        const dateFrom = dateValue ? dateValue.replace(/-/g, '') : '';
        
        let url = `/web/restore/search-backups?customer=${encodeURIComponent(selectedCustomer)}&env=prod`;
        if (dateFrom) {
            url += `&date_from=${dateFrom}`;
        }
        
        // Use HTMX to load backups
        htmx.ajax('GET', url, {
            target: '#backup-list'
        }).then(() => {
            hide($('backup-loading'));
            show($('backup-list'));
            
            // Update count
            const list = $('backup-list');
            if (list) {
                const rows = list.querySelectorAll('tbody tr');
                const dataDiv = list.querySelector('[data-total-count]');
                const total = dataDiv ? dataDiv.dataset.totalCount : rows.length;
                if (countEl) countEl.textContent = `${rows.length} of ${total}`;
            }
        }).catch((err) => {
            console.error('Backup load error:', err);
            hide($('backup-loading'));
            const list = $('backup-list');
            if (list) {
                list.innerHTML = '<div class="backup-error">Failed to load backups</div>';
                show(list);
            }
        });
    }
    
    function showBackupWaiting() {
        show($('backup-waiting'));
        hide($('backup-loading'));
        hide($('backup-list'));
        hide($('backup-selected-mode'));
        hide($('target-callout'));
        
        const countEl = $('backup-count');
        if (countEl) countEl.textContent = '';
    }
    
    // Called from backup row click (via HTMX partial)
    window.selectBackup = function(key, env, date, size) {
        selectedBackup = key;
        
        // Update display
        const nameEl = $('selected-backup-name');
        const metaEl = $('selected-backup-meta');
        if (nameEl) nameEl.textContent = date;
        if (metaEl) metaEl.textContent = `${env} • ${size || 'Unknown size'}`;
        
        // Hide list, show selected
        hide($('backup-list'));
        hide($('backup-loading'));
        hide($('backup-waiting'));
        show($('backup-selected-mode'));
        
        // Set hidden input
        let backupInput = $('backup_key');
        if (!backupInput) {
            backupInput = document.createElement('input');
            backupInput.type = 'hidden';
            backupInput.id = 'backup_key';
            backupInput.name = 'backup_key';
            $('restore-form').appendChild(backupInput);
        }
        backupInput.value = key;
        
        // Show target callout
        updateTargetCallout();
        updateSummary();
    };
    
    function clearBackupSelection() {
        selectedBackup = null;
        
        const backupInput = $('backup_key');
        if (backupInput) backupInput.value = '';
        
        hide($('backup-selected-mode'));
        hide($('target-callout'));
        
        // Clear row selection
        const list = $('backup-list');
        if (list) {
            list.querySelectorAll('tr.is-selected').forEach(tr => tr.classList.remove('is-selected'));
        }
    }
    
    function initBackupClearBtn() {
        const clearBtn = $('clear-backup-btn');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                clearBackupSelection();
                show($('backup-list'));
            });
        }
    }

    // =============================================================================
    // Target Preview Functions
    // =============================================================================
    
    function getUserCode() {
        const selector = $('submit_as_user');
        if (selector && config.userCodeMap) {
            return config.userCodeMap[selector.value] || config.currentUserCode;
        }
        return config.currentUserCode || '';
    }
    
    function updateTargetCallout() {
        const callout = $('target-callout');
        if (!callout || !selectedCustomer || !selectedBackup) {
            hide(callout);
            return;
        }
        
        const userCode = getUserCode();
        const suffix = $('suffix') ? $('suffix').value : '';
        
        const userCodeEl = $('callout-user-code');
        const customerEl = $('callout-customer');
        const suffixEl = $('callout-suffix');
        
        if (userCodeEl) userCodeEl.textContent = userCode;
        if (customerEl) customerEl.textContent = selectedCustomer;
        if (suffixEl) suffixEl.textContent = suffix;
        
        show(callout);
    }
    
    function updateTargetPreview() {
        const preview = $('target-preview');
        if (!preview || !selectedCustomer) {
            hide(preview);
            return;
        }
        
        const userCode = getUserCode();
        const suffix = $('suffix') ? $('suffix').value : '';
        
        const userCodeEl = $('preview-user-code');
        const customerEl = $('preview-customer');
        const suffixEl = $('preview-suffix');
        
        if (userCodeEl) userCodeEl.textContent = userCode;
        if (customerEl) customerEl.textContent = selectedCustomer;
        if (suffixEl) suffixEl.textContent = suffix;
        
        show(preview);
    }
    
    function hideTargetPreview() {
        hide($('target-preview'));
    }

    // =============================================================================
    // Summary Functions
    // =============================================================================
    
    function updateSummary() {
        const summary = $('submit-summary');
        if (!summary) return;
        
        if (isQaMode) {
            // QA mode summary handled separately
            return;
        }
        
        if (selectedCustomer && selectedBackup) {
            const userCode = getUserCode();
            const suffix = $('suffix') ? $('suffix').value : '';
            const target = userCode + selectedCustomer + suffix;
            summary.innerHTML = `Ready to restore <strong>${escapeHtml(selectedCustomer)}</strong> as <strong>${escapeHtml(target)}</strong>`;
        } else if (selectedCustomer) {
            summary.textContent = 'Select a backup to continue';
        } else {
            summary.textContent = 'Select a customer and backup to queue restore';
        }
    }

    // =============================================================================
    // Tab Switching (Customer / QA Template)
    // =============================================================================
    
    function initTabs() {
        const tabs = document.querySelectorAll('.form-tab');
        
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const tabId = tab.dataset.tab;
                
                // Update active tab
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                
                // Show content
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                const content = $('tab-' + tabId);
                if (content) content.classList.add('active');
                
                // Update mode
                const qaInput = $('qatemplate-input');
                if (qaInput) qaInput.value = tabId === 'qatemplate' ? 'true' : 'false';
                isQaMode = tabId === 'qatemplate';
                
                // Handle mode switch
                if (isQaMode) {
                    const customerHidden = $('customer');
                    if (customerHidden) customerHidden.value = 'qatemplate';
                    loadQaBackups();
                } else {
                    const customerHidden = $('customer');
                    if (customerHidden) customerHidden.value = selectedCustomer;
                    updateSummary();
                }
            });
        });
    }

    // =============================================================================
    // QA Template Functions
    // =============================================================================
    
    function loadQaBackups() {
        const qaList = $('qa-backup-list');
        const qaCount = $('qa-backup-count');
        
        if (!qaList) return;
        
        if (qaCount) qaCount.textContent = 'Loading...';
        
        const qaDateInput = $('qa-date-from');
        const dateValue = qaDateInput ? qaDateInput.value : '';
        const dateFrom = dateValue ? dateValue.replace(/-/g, '') : '';
        
        let url = '/web/restore/search-backups?customer=qatemplate&env=prod';
        if (dateFrom) url += `&date_from=${dateFrom}`;
        
        htmx.ajax('GET', url, { target: '#qa-backup-list' }).then(() => {
            const rows = qaList.querySelectorAll('tbody tr');
            if (qaCount) qaCount.textContent = `${rows.length} found`;
        });
    }
    
    function initQaDatePicker() {
        const dateInput = $('qa-date-from');
        const resetBtn = $('qa-reset-date-btn');
        
        if (!dateInput) return;
        
        dateInput.value = getDefaultDate();
        
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                dateInput.value = getDefaultDate();
                if (isQaMode) loadQaBackups();
            });
        }
        
        dateInput.addEventListener('change', () => {
            if (!dateInput.value) dateInput.value = getDefaultDate();
            if (isQaMode) loadQaBackups();
        });
    }
    
    // QA backup selection
    window.selectQaBackup = function(key, env, date, size) {
        const nameEl = $('selected-qa-backup-name');
        const metaEl = $('selected-qa-backup-meta');
        if (nameEl) nameEl.textContent = date;
        if (metaEl) metaEl.textContent = `${env} • ${size || 'Unknown size'}`;
        
        hide($('qa-backup-search-container'));
        show($('selected-qa-backup-display'));
        
        let backupInput = $('backup_key');
        if (!backupInput) {
            backupInput = document.createElement('input');
            backupInput.type = 'hidden';
            backupInput.id = 'backup_key';
            backupInput.name = 'backup_key';
            $('restore-form').appendChild(backupInput);
        }
        backupInput.value = key;
        
        show($('qa-target-callout'));
        updateQaSummary();
    };
    
    function updateQaSummary() {
        const summary = $('submit-summary');
        if (!summary) return;
        
        const backupInput = $('backup_key');
        if (backupInput && backupInput.value) {
            const userCode = getUserCode();
            const suffix = $('suffix') ? $('suffix').value : '';
            const target = userCode + 'qatemplate' + suffix;
            summary.innerHTML = `Ready to restore QA template as <strong>${escapeHtml(target)}</strong>`;
        } else {
            summary.textContent = 'Select a QA template backup to continue';
        }
    }

    // =============================================================================
    // Suffix & Overwrite
    // =============================================================================
    
    function initSuffixInput() {
        const suffixInput = $('suffix');
        if (!suffixInput) return;
        
        suffixInput.addEventListener('input', (e) => {
            e.target.value = e.target.value.toLowerCase().replace(/[^a-z]/g, '');
            updateTargetPreview();
            updateTargetCallout();
            if (isQaMode) {
                updateQaSummary();
            } else {
                updateSummary();
            }
        });
    }
    
    function initOverwriteCheckbox() {
        const checkbox = $('overwrite');
        const warning = $('overwrite-warning');
        
        if (!checkbox) return;
        
        checkbox.addEventListener('change', () => {
            if (warning) warning.classList.toggle('is-visible', checkbox.checked);
        });
        
        if (checkbox.checked && warning) {
            warning.classList.add('is-visible');
        }
    }

    // =============================================================================
    // User Selector
    // =============================================================================
    
    function initUserSelector() {
        const selector = $('submit_as_user');
        if (!selector) return;
        
        selector.addEventListener('change', () => {
            updateTargetPreview();
            updateTargetCallout();
            updateSummary();
        });
    }

    // =============================================================================
    // Form Validation
    // =============================================================================
    
    function initFormValidation() {
        const form = $('restore-form');
        if (!form) return;
        
        form.addEventListener('submit', (e) => {
            const hostInput = $('dbhost');
            const overwrite = $('overwrite');
            const customerHidden = $('customer');
            const backupInput = $('backup_key');
            
            // Validate host
            if (!hostInput || !hostInput.value) {
                e.preventDefault();
                alert('Please select a database host');
                return;
            }
            
            // Validate based on mode
            if (isQaMode) {
                if (!backupInput || !backupInput.value) {
                    e.preventDefault();
                    alert('Please select a QA template backup');
                    return;
                }
                if (customerHidden) customerHidden.value = 'qatemplate';
            } else {
                if (!selectedCustomer) {
                    e.preventDefault();
                    alert('Please select a customer');
                    return;
                }
                if (!selectedBackup) {
                    e.preventDefault();
                    alert('Please select a backup');
                    return;
                }
            }
            
            // Confirm overwrite - async handler requires preventing default and manual submit
            if (overwrite && overwrite.checked) {
                e.preventDefault();
                const confirmed = await showConfirm('WARNING: Overwrite is enabled!\n\nAny existing data will be PERMANENTLY DELETED.\n\nContinue?', {
                    title: 'Confirm Overwrite',
                    okText: 'Proceed with Overwrite',
                    type: 'danger'
                });
                if (confirmed) {
                    form.submit();
                }
            }
        });
    }

    // =============================================================================
    // Utilities
    // =============================================================================
    
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    function escapeAttr(text) {
        return text.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // =============================================================================
    // Initialize
    // =============================================================================
    
    function init() {
        initDatePicker();
        initCustomerSearch();
        initBackupClearBtn();
        initTabs();
        initQaDatePicker();
        initSuffixInput();
        initOverwriteCheckbox();
        initUserSelector();
        initFormValidation();
        
        // Pre-fill if customer was set
        if (selectedCustomer) {
            selectCustomer(selectedCustomer);
        }
    }
    
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
