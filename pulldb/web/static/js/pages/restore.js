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

    try {  // Error boundary to prevent total page breakage

    // =============================================================================
    // Configuration
    // =============================================================================
    
    const config = window.restoreConfig || {};
    const MIN_SEARCH_CHARS = 3;
    const DEBOUNCE_MS = 400;
    const MAX_CUSTOMER_LEN = 42;
    const TRUNCATE_LEN = 38;
    const HASH_SUFFIX_LEN = 4;

    // =============================================================================
    // State
    // =============================================================================
    
    let selectedCustomer = config.initialCustomer || '';
    let selectedBackup = null;
    let debounceTimer = null;
    let abortController = null;
    let isQaMode = false;

    // =============================================================================
    // Customer Name Normalization
    // =============================================================================
    
    /**
     * Compute a simple hash suffix from customer name (client-side preview only).
     * Uses lowercase letters only (a-z) to match server-side behavior.
     * Note: Must match server-side algorithm for actual submission preview.
     */
    function computeHashSuffix(name) {
        // Simple hash for preview purposes - actual hash comes from server
        let hash = 0;
        for (let i = 0; i < name.length; i++) {
            const char = name.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash; // Convert to 32bit integer
        }
        // Convert to 4 lowercase letters (a-z only)
        hash = Math.abs(hash);
        let result = '';
        for (let i = 0; i < HASH_SUFFIX_LEN; i++) {
            result += String.fromCharCode(97 + (hash % 26)); // 97 = 'a'
            hash = Math.floor(hash / 26);
        }
        return result;
    }
    
    /**
     * Normalize a customer name if it exceeds MAX_CUSTOMER_LEN.
     * Returns { normalized, wasNormalized, message }
     */
    function normalizeCustomerName(name) {
        if (name.length <= MAX_CUSTOMER_LEN) {
            return { normalized: name, wasNormalized: false, message: '' };
        }
        
        const truncated = name.substring(0, TRUNCATE_LEN);
        const suffix = computeHashSuffix(name);
        const normalized = truncated + suffix;
        
        return {
            normalized: normalized,
            wasNormalized: true,
            message: `Customer name '${name}' (${name.length} chars) exceeds ${MAX_CUSTOMER_LEN} character limit. Will be normalized to '${normalized}' for target database naming.`
        };
    }

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

    function getTodayDate() {
        return new Date().toISOString().split('T')[0];
    }

    /**
     * Toggle visibility of the "date-to" input and separator based on date mode.
     * @param {string} prefix - '' for customer tab, 'qa-' for QA tab
     */
    function updateDateModeUI(prefix) {
        const modeSelect = $(prefix + 'date-mode');
        const dateFrom = $(prefix + 'date-from');
        const dateTo = $(prefix + 'date-to');
        const sep = $(prefix + 'date-range-sep');
        if (!modeSelect) return;

        const mode = modeSelect.value;
        if (mode === 'between') {
            show(dateTo);
            show(sep);
            // Default the "to" date to today if empty
            if (dateTo && !dateTo.value) {
                dateTo.value = getTodayDate();
            }
        } else {
            hide(dateTo);
            hide(sep);
            // Clear stale date-to value when leaving "between" mode
            if (dateTo) dateTo.value = '';
        }

        // Smart default: adjust date-from based on mode
        if (dateFrom) {
            if (mode === 'on_or_before' || mode === 'on_date') {
                // Default to today — user wants to pick a specific cutoff/date
                if (dateFrom.value === getDefaultDate()) {
                    dateFrom.value = getTodayDate();
                }
            } else if (mode === 'on_or_after' || mode === 'between') {
                // Default to 7 days ago — user wants recent window
                if (dateFrom.value === getTodayDate()) {
                    dateFrom.value = getDefaultDate();
                }
            }
        }
    }

    function initDatePicker() {
        const dateInput = $('date-from');
        const dateToInput = $('date-to');
        const resetBtn = $('reset-date-btn');
        const modeSelect = $('date-mode');
        
        if (!dateInput) return;
        
        // Set default to 7 days ago
        dateInput.value = getDefaultDate();
        
        // Initialize date mode UI
        updateDateModeUI('');

        // Mode selector change
        if (modeSelect) {
            modeSelect.addEventListener('change', () => {
                updateDateModeUI('');
                if (selectedCustomer) {
                    clearBackupSelection();
                    loadBackups();
                }
            });
        }
        
        // Reset button
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                dateInput.value = getDefaultDate();
                if (modeSelect) modeSelect.value = 'on_or_after';
                if (dateToInput) dateToInput.value = '';
                updateDateModeUI('');
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

        // Reload backups when date-to changes
        if (dateToInput) {
            dateToInput.addEventListener('change', () => {
                if (selectedCustomer) {
                    clearBackupSelection();
                    loadBackups();
                }
            });
        }
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
        
        // Update hidden input (original name - server handles normalization)
        const hidden = $('customer');
        if (hidden) hidden.value = name;
        
        // Update UI
        const nameEl = $('selected-customer-name');
        if (nameEl) nameEl.textContent = name;
        
        hide($('customer-search-mode'));
        show($('customer-selected-mode'));
        hideResults();
        
        // Check for normalization and show warning
        updateNormalizationWarning(name);
        
        // Load backups
        loadBackups();
        updateTargetCallout();
        updateSummary();
    }
    
    function updateNormalizationWarning(name) {
        const warningEl = $('customer-normalization-warning');
        if (!warningEl) return;
        
        const result = normalizeCustomerName(name);
        if (result.wasNormalized) {
            warningEl.textContent = result.message;
            show(warningEl);
        } else {
            hide(warningEl);
        }
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
        
        // Hide normalization warning
        hide($('customer-normalization-warning'));
        
        clearBackupSelection();
        showBackupWaiting();
        hideTargetCallout();
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
        const dateToInput = $('date-to');
        const modeSelect = $('date-mode');
        const dateValue = dateInput ? dateInput.value : '';
        const dateFrom = dateValue ? dateValue.replace(/-/g, '') : '';
        const dateMode = modeSelect ? modeSelect.value : 'on_or_after';
        
        let url = `/web/restore/search-backups?customer=${encodeURIComponent(selectedCustomer)}&env=prod`;
        if (dateFrom) {
            url += `&date_from=${dateFrom}`;
        }
        url += `&date_mode=${dateMode}`;
        
        // Include date_to for "between" mode — require it before searching
        if (dateMode === 'between') {
            if (!dateToInput || !dateToInput.value) {
                hide($('backup-loading'));
                show($('backup-waiting'));
                return;
            }
            const dateTo = dateToInput.value.replace(/-/g, '');
            url += `&date_to=${dateTo}`;
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
        
        // Show target callout and target preview section
        updateTargetCallout();
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
        const autoPreview = $('auto-target-preview');
        if (!callout || !selectedCustomer || !selectedBackup) {
            hide(callout);
            return;
        }
        
        const userCode = getUserCode();
        const suffix = $('suffix') ? $('suffix').value : '';
        
        // Normalize customer name for preview
        const normResult = normalizeCustomerName(selectedCustomer);
        const displayCustomer = normResult.normalized;
        
        const userCodeEl = $('callout-user-code');
        const customerEl = $('callout-customer');
        const suffixEl = $('callout-suffix');
        
        if (userCodeEl) userCodeEl.textContent = userCode;
        if (customerEl) customerEl.textContent = displayCustomer;
        if (suffixEl) suffixEl.textContent = suffix;
        
        // Show callout, but auto preview only if not in custom mode
        show(callout);
        if (!customTargetEnabled && autoPreview) {
            show(autoPreview);
        }
    }
    
    function hideTargetCallout() {
        hide($('target-callout'));
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
            const customTarget = getCustomTarget();
            let target;
            
            if (customTarget) {
                target = customTarget;
            } else {
                const userCode = getUserCode();
                const suffix = $('suffix') ? $('suffix').value : '';
                target = userCode + selectedCustomer + suffix;
            }
            
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
                
                // Reset BOTH forms on tab switch
                resetCustomerForm();
                resetQaForm();
                
                // Handle mode switch
                if (isQaMode) {
                    const customerHidden = $('customer');
                    if (customerHidden) customerHidden.value = 'qatemplate';
                    // Disable Customer overwrite, enable QA overwrite
                    const customerOverwrite = $('overwrite');
                    const qaOverwrite = $('qa-overwrite');
                    if (customerOverwrite) customerOverwrite.disabled = true;
                    if (qaOverwrite) qaOverwrite.disabled = false;
                    loadQaBackups();
                } else {
                    const customerHidden = $('customer');
                    if (customerHidden) customerHidden.value = selectedCustomer;
                    // Enable Customer overwrite, disable QA overwrite
                    const customerOverwrite = $('overwrite');
                    const qaOverwrite = $('qa-overwrite');
                    if (customerOverwrite) customerOverwrite.disabled = false;
                    if (qaOverwrite) qaOverwrite.disabled = true;
                    updateSummary();
                }
            });
        });
    }
    
    function resetCustomerForm() {
        // Clear customer selection
        selectedCustomer = '';
        const customerHidden = $('customer');
        if (customerHidden) customerHidden.value = '';
        
        const searchInput = $('customer-search');
        if (searchInput) searchInput.value = '';
        
        show($('customer-search-mode'));
        hide($('customer-selected-mode'));
        updateSearchStatus('');
        hide($('customer-normalization-warning'));
        
        // Clear backup selection
        selectedBackup = null;
        const backupInput = $('backup_key');
        if (backupInput) backupInput.value = '';
        hide($('backup-selected-mode'));
        
        const backupList = $('backup-list');
        if (backupList) {
            backupList.querySelectorAll('tr.is-selected').forEach(tr => tr.classList.remove('is-selected'));
        }
        
        // Hide target callout and reset overwrite
        hide($('target-callout'));
        const overwriteCheckbox = $('overwrite');
        const overwriteWarning = $('overwrite-warning');
        if (overwriteCheckbox) overwriteCheckbox.checked = false;
        if (overwriteWarning) overwriteWarning.classList.remove('is-visible');
        
        // Reset custom target
        const customToggle = $('custom-target-toggle');
        const autoPreview = $('auto-target-preview');
        const customInput = $('custom_target');
        if (customToggle) customToggle.checked = false;
        if (autoPreview) show(autoPreview);
        if (customInput) {
            hide(customInput);
            customInput.value = '';
        }
        
        showBackupWaiting();
        updateSummary();
    }
    
    function resetQaForm() {
        // Clear QA backup selection
        const backupInput = $('backup_key');
        if (backupInput) backupInput.value = '';
        
        hide($('selected-qa-backup-display'));
        hide($('qa-target-callout'));
        show($('qa-backup-search-container'));
        
        const qaList = $('qa-backup-list');
        if (qaList) {
            qaList.querySelectorAll('tr.is-selected').forEach(tr => tr.classList.remove('is-selected'));
        }
        
        // Reset QA overwrite
        const qaOverwriteCheckbox = $('qa-overwrite');
        const qaOverwriteWarning = $('qa-overwrite-warning');
        if (qaOverwriteCheckbox) qaOverwriteCheckbox.checked = false;
        if (qaOverwriteWarning) qaOverwriteWarning.classList.remove('is-visible');
        
        updateQaSummary();
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
        const qaDateToInput = $('qa-date-to');
        const qaModeSelect = $('qa-date-mode');
        const dateValue = qaDateInput ? qaDateInput.value : '';
        const dateFrom = dateValue ? dateValue.replace(/-/g, '') : '';
        const dateMode = qaModeSelect ? qaModeSelect.value : 'on_or_after';
        
        let url = '/web/restore/search-backups?customer=qatemplate&env=prod';
        if (dateFrom) url += `&date_from=${dateFrom}`;
        url += `&date_mode=${dateMode}`;
        
        // Require date_to for "between" mode before searching
        if (dateMode === 'between') {
            if (!qaDateToInput || !qaDateToInput.value) {
                if (qaCount) qaCount.textContent = 'Select end date';
                return;
            }
            const dateTo = qaDateToInput.value.replace(/-/g, '');
            url += `&date_to=${dateTo}`;
        }
        
        htmx.ajax('GET', url, { target: '#qa-backup-list' }).then(() => {
            const rows = qaList.querySelectorAll('tbody tr');
            if (qaCount) qaCount.textContent = `${rows.length} found`;
        });
    }
    
    function initQaDatePicker() {
        const dateInput = $('qa-date-from');
        const dateToInput = $('qa-date-to');
        const resetBtn = $('qa-reset-date-btn');
        const modeSelect = $('qa-date-mode');
        
        if (!dateInput) return;
        
        dateInput.value = getDefaultDate();
        updateDateModeUI('qa-');
        
        // Mode selector change
        if (modeSelect) {
            modeSelect.addEventListener('change', () => {
                updateDateModeUI('qa-');
                if (isQaMode) {
                    clearQaBackupSelection();
                    loadQaBackups();
                }
            });
        }
        
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                dateInput.value = getDefaultDate();
                if (modeSelect) modeSelect.value = 'on_or_after';
                if (dateToInput) dateToInput.value = '';
                updateDateModeUI('qa-');
                if (isQaMode) loadQaBackups();
            });
        }
        
        dateInput.addEventListener('change', () => {
            if (!dateInput.value) dateInput.value = getDefaultDate();
            if (isQaMode) {
                clearQaBackupSelection();
                loadQaBackups();
            }
        });

        if (dateToInput) {
            dateToInput.addEventListener('change', () => {
                if (isQaMode) {
                    clearQaBackupSelection();
                    loadQaBackups();
                }
            });
        }
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
    
    function clearQaBackupSelection() {
        const backupInput = $('backup_key');
        if (backupInput) backupInput.value = '';
        
        hide($('selected-qa-backup-display'));
        hide($('qa-target-callout'));
        show($('qa-backup-search-container'));
        
        // Clear row selection
        const list = $('qa-backup-list');
        if (list) {
            list.querySelectorAll('tr.is-selected').forEach(tr => tr.classList.remove('is-selected'));
        }
        
        updateQaSummary();
    }
    
    function initQaBackupClearBtn() {
        const clearBtn = $('clear-qa-backup-btn');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                clearQaBackupSelection();
            });
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
            updateTargetCallout();
            updateTargetCallout();
            if (isQaMode) {
                updateQaSummary();
            } else {
                updateSummary();
            }
        });
    }
    
    function initOverwriteCheckbox() {
        // Customer Database overwrite
        const checkbox = $('overwrite');
        const warning = $('overwrite-warning');
        
        if (checkbox && warning) {
            checkbox.addEventListener('change', () => {
                warning.classList.toggle('is-visible', checkbox.checked);
            });
            
            if (checkbox.checked) {
                warning.classList.add('is-visible');
            }
        }
        
        // QA Template overwrite
        const qaCheckbox = $('qa-overwrite');
        const qaWarning = $('qa-overwrite-warning');
        
        if (qaCheckbox && qaWarning) {
            qaCheckbox.addEventListener('change', () => {
                qaWarning.classList.toggle('is-visible', qaCheckbox.checked);
            });
            
            if (qaCheckbox.checked) {
                qaWarning.classList.add('is-visible');
            }
            
            // Disable QA overwrite by default (Customer Database tab is active on load)
            qaCheckbox.disabled = true;
        }
    }

    // =============================================================================
    // Custom Target
    // =============================================================================
    
    let customTargetEnabled = false;
    
    function initCustomTarget() {
        const toggle = $('custom-target-toggle');
        const autoPreview = $('auto-target-preview');
        const input = $('custom_target');
        const suffixGroup = $('suffix-group');
        const suffixInput = $('suffix');
        const errorEl = $('custom-target-error');
        
        if (!toggle || !input) return;
        
        // Check if we have an initial custom target from form preservation
        if (config.initialCustomTarget) {
            toggle.checked = true;
            customTargetEnabled = true;
            show(input);
            hide(autoPreview);
            if (suffixGroup) hide(suffixGroup);
            if (suffixInput) suffixInput.value = '';
            input.value = config.initialCustomTarget;
        }
        
        // Toggle handler
        toggle.addEventListener('change', () => {
            customTargetEnabled = toggle.checked;
            
            if (customTargetEnabled) {
                show(input);
                hide(autoPreview);
                if (suffixGroup) hide(suffixGroup);
                if (suffixInput) suffixInput.value = '';  // Clear suffix
                input.focus();
            } else {
                hide(input);
                show(autoPreview);
                if (suffixGroup) show(suffixGroup);
                input.value = '';  // Clear custom target
                updateTargetCallout();  // Refresh auto-generated preview
            }
            updateSummary();
        });
        
        // Input validation and preview
        input.addEventListener('input', (e) => {
            // Force lowercase letters only
            e.target.value = e.target.value.toLowerCase().replace(/[^a-z]/g, '');
            
            validateCustomTarget();
            updateSummary();
        });
    }
    
    function validateCustomTarget() {
        const input = $('custom_target');
        const errorEl = $('custom-target-error');
        
        if (!input || !customTargetEnabled) return true;
        
        const value = input.value;
        
        if (value.length === 0) {
            hide(errorEl);
            return true;  // Empty is OK (optional field)
        }
        
        if (!/^[a-z]+$/.test(value)) {
            if (errorEl) {
                errorEl.textContent = 'Only lowercase letters (a-z) are allowed.';
                show(errorEl);
            }
            return false;
        }
        
        if (value.length > 51) {
            if (errorEl) {
                errorEl.textContent = 'Maximum 51 characters allowed.';
                show(errorEl);
            }
            return false;
        }
        
        hide(errorEl);
        return true;
    }
    
    function getCustomTarget() {
        if (!customTargetEnabled) return null;
        const input = $('custom_target');
        return input && input.value ? input.value : null;
    }

    // =============================================================================
    // User Selector
    // =============================================================================
    
    function initUserSelector() {
        const selector = $('submit_as_user');
        if (!selector) return;
        
        selector.addEventListener('change', () => {
            updateTargetCallout();
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
        
        form.addEventListener('submit', async (e) => {
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
            
            // Validate custom target if enabled
            if (customTargetEnabled) {
                const customInput = $('custom_target');
                if (customInput && customInput.value) {
                    if (!validateCustomTarget()) {
                        e.preventDefault();
                        alert('Please fix the custom target name error');
                        return;
                    }
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
        initQaBackupClearBtn();
        initTabs();
        initQaDatePicker();
        initSuffixInput();
        initOverwriteCheckbox();
        initCustomTarget();
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
    
    // Force re-initialization on back/forward navigation (bfcache)
    window.addEventListener('pageshow', (event) => {
        if (event.persisted) {
            // Page was restored from bfcache - reset dates and modes
            const dateInput = $('date-from');
            const dateToInput = $('date-to');
            const modeSelect = $('date-mode');
            const qaDateInput = $('qa-date-from');
            const qaDateToInput = $('qa-date-to');
            const qaModeSelect = $('qa-date-mode');
            const defaultDate = new Date();
            defaultDate.setDate(defaultDate.getDate() - 7);
            const defaultStr = defaultDate.toISOString().split('T')[0];
            if (dateInput) dateInput.value = defaultStr;
            if (dateToInput) dateToInput.value = '';
            if (modeSelect) modeSelect.value = 'on_or_after';
            if (qaDateInput) qaDateInput.value = defaultStr;
            if (qaDateToInput) qaDateToInput.value = '';
            if (qaModeSelect) qaModeSelect.value = 'on_or_after';
            updateDateModeUI('');
            updateDateModeUI('qa-');
        }
    });
    
    } catch (error) {
        console.error('Restore page initialization failed:', error);
        // Show user-friendly error
        const form = document.getElementById('restore-form');
        if (form) {
            const alert = document.createElement('div');
            alert.className = 'alert alert-danger';
            alert.style.margin = 'var(--space-4)';
            alert.innerHTML = '<strong>Page Error:</strong> The restore page failed to initialize. Please refresh or contact support.';
            form.parentNode.insertBefore(alert, form);
        }
    }
})();
