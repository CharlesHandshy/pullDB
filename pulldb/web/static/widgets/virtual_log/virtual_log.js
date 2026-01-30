/**
 * VirtualLog Widget
 * =================
 * HCA Layer: widgets (Layer 3)
 *
 * Virtual scroll log viewer for job execution events.
 * Scrollbar reflects total data size; only visible rows are in DOM.
 */

class VirtualLog {
    /**
     * @param {Object} options
     * @param {HTMLElement} options.container - Container element
     * @param {string} options.jobId - Job ID for API calls
     * @param {number} options.totalEvents - Total event count from server
     * @param {boolean} options.isRunning - Whether job is still running
     * @param {Array} options.initialEvents - Pre-loaded events (newest first)
     */
    constructor(options) {
        this.container = options.container;
        this.jobId = options.jobId;
        this.totalEvents = options.totalEvents || 0;
        this.isRunning = options.isRunning || false;
        this.pollInterval = options.pollInterval || 5000;

        // Sort order: running jobs show newest first, completed jobs show oldest first
        // This is stored and doesn't change during the session
        this._newestFirst = this.isRunning;

        // Config
        this.rowHeight = 32;           // Fixed row height in pixels
        this.pageSize = 50;            // Events per API request
        this.bufferRows = 10;          // Extra rows above/below viewport
        this.maxCachedEvents = 300;    // Max events in memory
        this.debounceMs = 150;         // Wait for scroll to settle before loading

        // Position-based cache: position 0 = newest event
        // We store events by their position in the total list
        this._cache = new Map();       // position -> event data
        this._cacheStartPos = 0;       // Lowest position in cache
        this._cacheEndPos = 0;         // Highest position + 1 in cache

        // Loading state - simplified with debounce
        this._loadDebounceTimer = null;
        this._abortController = null;  // Cancel in-flight requests
        this._isLoading = false;
        this._pollTimer = null;
        this._isDestroyed = false;

        // DOM refs
        this._scrollEl = null;
        this._spacerEl = null;
        this._contentEl = null;
        this._countEl = document.getElementById('event-count-badge');

        // Render state
        this._renderedStart = -1;
        this._renderedEnd = -1;

        this._onScroll = this._onScroll.bind(this);

        this._build();
        this._initCache(options.initialEvents || []);
        this._render();

        if (this.isRunning) {
            this._startPolling();
        }
    }

    // =========================================================================
    // DOM Construction
    // =========================================================================

    _build() {
        this.container.classList.add('virtual-log-widget');

        // Scroll container
        this._scrollEl = document.createElement('div');
        this._scrollEl.className = 'virtual-log-scroll';

        // Spacer sets total scrollable height based on totalEvents
        this._spacerEl = document.createElement('div');
        this._spacerEl.className = 'virtual-log-spacer';
        this._updateSpacerHeight();

        // Content container - positioned absolutely within scroll
        this._contentEl = document.createElement('div');
        this._contentEl.className = 'virtual-log-content';

        this._scrollEl.appendChild(this._spacerEl);
        this._scrollEl.appendChild(this._contentEl);
        this.container.appendChild(this._scrollEl);

        this._scrollEl.addEventListener('scroll', this._onScroll, { passive: true });

        // Hide initial loading indicator
        const loadingEl = document.getElementById('virtual-log-loading');
        if (loadingEl) loadingEl.style.display = 'none';
    }

    _updateSpacerHeight() {
        const height = this.totalEvents * this.rowHeight;
        this._spacerEl.style.height = `${height}px`;
    }

    // =========================================================================
    // Cache Management
    // =========================================================================

    _initCache(events) {
        if (!events || events.length === 0) return;

        // Server now sends events in the correct order:
        // - Running jobs: newest-first (for live updates at top)
        // - Completed jobs: oldest-first (for chronological reading)
        // No reversal needed - use events as-is
        for (let i = 0; i < events.length; i++) {
            this._cache.set(i, events[i]);
        }
        this._cacheStartPos = 0;
        this._cacheEndPos = events.length;

        this._updateCount();
    }

    _addEventsAtPosition(events, startPos) {
        for (let i = 0; i < events.length; i++) {
            this._cache.set(startPos + i, events[i]);
        }
        
        // Update cache bounds
        this._cacheStartPos = Math.min(this._cacheStartPos, startPos);
        this._cacheEndPos = Math.max(this._cacheEndPos, startPos + events.length);

        // Trim cache if too large
        this._trimCache();
        this._updateCount();
    }

    _trimCache() {
        if (this._cache.size <= this.maxCachedEvents) return;

        // Find center of current view
        const { start, end } = this._getVisibleRange();
        const viewCenter = Math.floor((start + end) / 2);
        
        // Keep a window around current view
        const keepHalf = Math.floor(this.maxCachedEvents / 2);
        const keepStart = Math.max(0, viewCenter - keepHalf);
        const keepEnd = Math.min(this.totalEvents, viewCenter + keepHalf);

        // Remove entries outside keep range
        for (const pos of this._cache.keys()) {
            if (pos < keepStart || pos >= keepEnd) {
                this._cache.delete(pos);
            }
        }

        // Update bounds to reflect ACTUAL cached entries, not the keep window
        // This prevents _canExtendCache from thinking we have data we don't
        if (this._cache.size === 0) {
            this._cacheStartPos = 0;
            this._cacheEndPos = 0;
        } else {
            let minPos = Infinity;
            let maxPos = -1;
            for (const pos of this._cache.keys()) {
                minPos = Math.min(minPos, pos);
                maxPos = Math.max(maxPos, pos);
            }
            this._cacheStartPos = minPos;
            this._cacheEndPos = maxPos + 1;  // End is exclusive
        }
    }

    // =========================================================================
    // Scroll Handling & Visible Range
    // =========================================================================

    _onScroll() {
        if (this._isDestroyed) return;

        // IMMEDIATE: Render placeholders for visible range (no delay)
        // This gives instant visual feedback during scroll
        this._render();

        // DEBOUNCED: Wait for scroll to settle before loading data
        // This prevents hundreds of requests during rapid scroll wheel or drag
        clearTimeout(this._loadDebounceTimer);
        
        // Cancel any in-flight request - position is changing
        if (this._abortController) {
            this._abortController.abort();
            this._abortController = null;
        }

        // After scroll settles, load the data
        this._loadDebounceTimer = setTimeout(() => {
            this._loadVisibleRange();
        }, this.debounceMs);
    }

    _getVisibleRange() {
        const scrollTop = this._scrollEl.scrollTop;
        const viewportHeight = this._scrollEl.clientHeight;

        // Calculate visible row range with buffer
        const startRow = Math.max(0, Math.floor(scrollTop / this.rowHeight) - this.bufferRows);
        const visibleRows = Math.ceil(viewportHeight / this.rowHeight);
        const endRow = Math.min(this.totalEvents, startRow + visibleRows + this.bufferRows * 2);

        return { start: startRow, end: endRow };
    }

    /**
     * Check if we have sufficient cached data for a range
     */
    _hasCachedRange(start, end) {
        // Check if at least 80% of the range is cached
        let cached = 0;
        for (let i = start; i < end; i++) {
            if (this._cache.has(i)) cached++;
        }
        return cached >= (end - start) * 0.8;
    }

    /**
     * Check if we can extend the current cache to cover the range
     * (vs needing a fresh offset-based load)
     * 
     * Returns true only if ONE page fetch would cover the gap.
     * Otherwise, offset-based load is more efficient.
     */
    _canExtendCache(start, end) {
        // If cache is empty, can't extend
        if (this._cache.size === 0) return false;
        
        // Calculate gap between cache and visible range
        const gapBelow = Math.max(0, end - this._cacheEndPos);  // scrolling down
        const gapAbove = Math.max(0, this._cacheStartPos - start);  // scrolling up
        
        // If either gap is larger than one page, use offset load instead
        // (more efficient to jump directly than fetch multiple pages)
        const maxGap = this.pageSize;
        
        const canExtend = gapBelow <= maxGap && gapAbove <= maxGap;
        return canExtend;
    }

    // =========================================================================
    // Data Loading - Unified with Debounce
    // =========================================================================

    async _loadVisibleRange() {
        if (this._isDestroyed) return;

        const { start, end } = this._getVisibleRange();

        // Already have this data? Skip
        if (this._hasCachedRange(start, end)) {
            this._render();
            return;
        }

        // Decide strategy: extend cache or fresh offset load
        const shouldUseOffset = !this._canExtendCache(start, end);

        // Create abort controller for this request
        // Store locally AND on instance - local copy prevents race condition
        const controller = new AbortController();
        this._abortController = controller;
        this._isLoading = true;
        this._loadId = (this._loadId || 0) + 1;
        const myLoadId = this._loadId;

        try {
            if (shouldUseOffset) {
                await this._fetchByOffset(start, end - start, controller.signal);
            } else {
                await this._fetchToExtendCache(start, end, controller.signal);
            }
            
            // Only re-render if this is still the active load
            if (this._loadId === myLoadId && !this._isDestroyed) {
                // Force re-render by invalidating cached render state
                // Use -999 to ensure any comparison fails (including 0)
                this._renderedStart = -999;
                this._renderedEnd = -999;
                // Synchronously render to prevent scroll event from intervening
                this._render();
            }
        } catch (err) {
            if (err.name === 'AbortError') {
                // Request cancelled during scroll - expected behavior
            } else {
                console.error(`[VirtualLog] Load #${myLoadId} error:`, err);
            }
        } finally {
            // Only clear state if this is still the active load
            if (this._loadId === myLoadId) {
                this._isLoading = false;
                this._abortController = null;
            }
        }
    }

    /**
     * Fetch events by offset (for jumps/scrollbar drags)
     * Clears cache and loads fresh at the target position
     */
    async _fetchByOffset(offset, limit, signal) {
        // DON'T clear cache here - only clear after successful fetch
        // This prevents empty cache if request is aborted

        const params = new URLSearchParams({
            offset: offset.toString(),
            limit: limit.toString(),
            order: this._newestFirst ? 'desc' : 'asc',
        });

        const response = await fetch(`/web/jobs/${this.jobId}/events?${params}`, { signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();

        // NOW clear and repopulate cache (request succeeded)
        this._cache.clear();
        
        if (data.events && data.events.length > 0) {
            for (let i = 0; i < data.events.length; i++) {
                this._cache.set(offset + i, data.events[i]);
            }
            this._cacheStartPos = offset;
            this._cacheEndPos = offset + data.events.length;
        } else {
            this._cacheStartPos = offset;
            this._cacheEndPos = offset;
        }

        this._updateTotalIfChanged(data.total_count);
    }

    /**
     * Fetch events to extend the current cache (for sequential scrolling)
     * Uses cursor-based pagination for efficiency
     */
    async _fetchToExtendCache(start, end, signal) {
        // Determine which direction to load
        if (end > this._cacheEndPos && this._cacheEndPos < this.totalEvents) {
            // Need older events (scrolling down)
            await this._fetchOlder(signal);
        }
        
        if (start < this._cacheStartPos && this._cacheStartPos > 0) {
            // Need newer events (scrolling up)
            await this._fetchNewer(signal);
        }
    }

    async _fetchOlder(signal) {
        // Fetch events after current cache end (scrolling toward older events)
        const offset = this._cacheEndPos;
        const params = new URLSearchParams({
            offset: offset.toString(),
            limit: this.pageSize.toString(),
            order: this._newestFirst ? 'desc' : 'asc',
        });

        const response = await fetch(`/web/jobs/${this.jobId}/events?${params}`, { signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();

        if (data.events && data.events.length > 0) {
            this._addEventsAtPosition(data.events, this._cacheEndPos);
        }

        this._updateTotalIfChanged(data.total_count);
    }

    async _fetchNewer(signal) {
        // Fetch events before current cache start (scrolling toward newer events)
        const fetchCount = Math.min(this.pageSize, this._cacheStartPos);
        if (fetchCount <= 0) return;
        
        const offset = this._cacheStartPos - fetchCount;
        const params = new URLSearchParams({
            offset: offset.toString(),
            limit: fetchCount.toString(),
            order: this._newestFirst ? 'desc' : 'asc',
        });

        const response = await fetch(`/web/jobs/${this.jobId}/events?${params}`, { signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();

        if (data.events && data.events.length > 0) {
            this._addEventsAtPosition(data.events, offset);
        }
    }

    _updateTotalIfChanged(newTotal) {
        if (newTotal && newTotal !== this.totalEvents) {
            this.totalEvents = newTotal;
            this._updateSpacerHeight();
        }
    }

    // =========================================================================
    // Rendering
    // =========================================================================

    _render() {
        const { start, end } = this._getVisibleRange();

        // Clamp to actual data boundaries FIRST
        // This ensures we never render placeholders outside valid positions
        const renderStart = Math.max(0, start);
        const renderEnd = Math.min(this.totalEvents, end);

        // Skip if clamped range hasn't changed
        // Note: After data load, _renderedStart/End are reset to -999 to force re-render
        if (renderStart === this._renderedStart && 
            renderEnd === this._renderedEnd) {
            return;
        }

        // Position content at the clamped start row (not buffered start)
        // This prevents empty space before first row or after last row
        const offsetY = renderStart * this.rowHeight;
        this._contentEl.style.transform = `translateY(${offsetY}px)`;

        // Clear and rebuild
        this._contentEl.innerHTML = '';

        if (this.totalEvents === 0) {
            this._showEmpty();
            return;
        }

        const fragment = document.createDocumentFragment();

        for (let pos = renderStart; pos < renderEnd; pos++) {
            const event = this._cache.get(pos);
            if (event) {
                try {
                    fragment.appendChild(this._createEntry(event));
                } catch (err) {
                    console.error(`[VirtualLog] Error creating entry at pos ${pos}:`, event, err);
                    fragment.appendChild(this._createPlaceholder(pos));
                }
            } else {
                // Placeholder for not-yet-loaded position (within valid range)
                fragment.appendChild(this._createPlaceholder(pos));
            }
        }
        this._contentEl.appendChild(fragment);

        // Store the CLAMPED range we actually rendered
        // This ensures optimization check matches what's on screen
        this._renderedStart = renderStart;
        this._renderedEnd = renderEnd;
    }

    _createEntry(event) {
        const el = document.createElement('div');
        el.className = `virtual-log-entry ${this._getVariant(event.event_type)}`;
        el.style.height = `${this.rowHeight}px`;

        const time = this._formatTime(event.logged_at);
        let details;
        try {
            details = this._formatDetails(event);
        } catch (err) {
            console.error('[VirtualLog] Error formatting event:', event, err);
            details = `[Format error: ${err.message}]`;
        }

        el.innerHTML = `
            <span class="virtual-log-entry__time">${time}</span>
            <span class="virtual-log-entry__type" title="${event.event_type}">${event.event_type}</span>
            <span class="virtual-log-entry__msg">${details}</span>
        `;

        return el;
    }

    _createPlaceholder(pos) {
        const el = document.createElement('div');
        el.className = 'virtual-log-entry virtual-log-entry--loading';
        el.style.height = `${this.rowHeight}px`;
        el.innerHTML = `<span class="virtual-log-entry__msg">Loading row ${pos + 1}...</span>`;
        return el;
    }

    _showEmpty() {
        this._contentEl.innerHTML = `
            <div class="virtual-log-empty">
                <div class="virtual-log-empty__icon">📋</div>
                <p class="virtual-log-empty__msg">No execution events yet</p>
            </div>
        `;
    }

    // =========================================================================
    // Formatting
    // =========================================================================

    _getVariant(type) {
        if (!type) return '';
        if (type.includes('complete') || type.includes('created') || type === 'restore_profile') {
            return 'virtual-log-entry--success';
        }
        if (type === 'failed' || type === 'error' || type.includes('error')) {
            return 'virtual-log-entry--error';
        }
        if (type.includes('warning') || type.includes('skip')) {
            return 'virtual-log-entry--warning';
        }
        if (type.includes('progress') || type.includes('started')) {
            return 'virtual-log-entry--info';
        }
        return '';
    }

    _formatTime(isoString) {
        if (!isoString) return '--:--:--';
        try {
            const d = new Date(isoString);
            return d.toLocaleTimeString('en-US', {
                hour12: false,
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        } catch {
            return '--:--:--';
        }
    }

    _formatDetails(event) {
        const d = event.detail || {};
        const t = event.event_type;

        switch (t) {
            // === Job lifecycle ===
            case 'queued':
            case 'running':
            case 'complete':
            case 'deployed':
                return d.message || '';
            case 'failed':
                return d.error || d.message || 'Unknown error';
            case 'heartbeat':
                return d.status || d.message || 'Worker alive';

            // === Download phase ===
            case 'backup_selected': {
                const key = d.key || d.backup_key || 'unknown';
                const filename = key.split('/').pop() || key;
                const size = this._formatBytes(d.size_bytes);
                return `${filename} (${size})`;
            }
            case 'download_started': {
                const key = d.key || d.backup_key || '';
                const filename = key.split('/').pop() || key || 'backup';
                return `Downloading: ${filename}`;
            }
            case 'download_progress': {
                const pct = d.percent ?? d.percent_complete ?? 0;
                return `Download: ${pct.toFixed(1)}% (${this._formatBytes(d.downloaded_bytes)} / ${this._formatBytes(d.total_bytes)})`;
            }
            case 'download_complete': {
                const size = d.size_bytes || d.total_bytes;
                const dur = d.duration_seconds ?? d.elapsed_seconds;
                if (size && dur != null) {
                    return `Downloaded ${this._formatBytes(size)} in ${dur.toFixed(1)}s`;
                }
                // Fallback: just show completion (detail may only have path)
                return `Download complete`;
            }
            case 'download_failed':
                return `Download failed: ${d.error || d.message || 'unknown'}`;

            // === Extraction phase ===
            case 'extraction_started':
                return `Extracting backup...`;
            case 'extraction_progress': {
                const pct = d.percent ?? d.percent_complete ?? 0;
                return `Extraction: ${pct.toFixed(1)}%`;
            }
            case 'extraction_complete':
                return `Extracted ${d.total_files || '?'} files (${this._formatBytes(d.total_bytes)})`;
            case 'extraction_failed':
                return `Extraction failed: ${d.error || d.message || 'unknown'}`;
            case 'format_detected':
                return `Format: ${d.detected_version || d.format_tag || 'unknown'}`;

            // === Staging cleanup ===
            case 'staging_cleanup_started':
                return `Cleaning orphaned staging for ${d.target || '?'}`;
            case 'staging_cleanup_complete':
                return `Staging cleanup: ${d.orphans_count || 0} orphans dropped (${(d.duration_seconds || 0).toFixed(2)}s)`;
            case 'staging_drop_started':
                return `Dropping staging database ${d.staging_db || '?'}`;
            case 'staging_drop_complete':
                return `Staging database dropped (${(d.duration_seconds || 0).toFixed(2)}s)`;

            // === Pre-create metadata ===
            case 'pre_create_metadata_started':
                return `Creating metadata in ${d.staging_db || '?'}`;
            case 'pre_create_metadata_complete':
                return `Metadata created (${(d.duration_seconds || 0).toFixed(2)}s)`;

            // === Restore/myloader phase ===
            case 'restore_started':
                return `Starting restore to ${d.staging_db || 'staging'}`;
            case 'myloader_started':
                return `myloader started with ${d.threads || '?'} threads`;
            case 'restore_progress':
                return this._formatProgress(d);
            case 'schema_creating':
                return `Creating schema: ${d.table || '?'}`;
            case 'schema_created':
                return `Schema created: ${d.table || ''} (${d.tables_created || '?'}/${d.tables_total || '?'})`;
            
            // === Indexing phase events ===
            case 'indexing_started':
                return `Building indexes: ${d.table || '?'} (${(d.rows || 0).toLocaleString()} rows)`;
            case 'indexing_progress': {
                const count = d.count || (d.tables ? d.tables.length : 0);
                if (count === 0) return 'Indexing in progress...';
                const names = (d.tables || []).slice(0, 3).map(t => t.table).join(', ');
                const more = count > 3 ? ` +${count - 3} more` : '';
                return `Indexing ${count} table(s): ${names}${more}`;
            }
            
            case 'table_data_progress':
                return `Loading data: ${d.table || '?'} (${(d.percent || 0).toFixed(1)}%)`;
            case 'table_data_complete':
                return `Data loaded: ${d.table || '?'}`;
            case 'table_index_rebuild_started':
                return `Rebuilding indexes: ${d.table || '?'}`;
            case 'table_index_rebuild_progress':
                return `Index rebuild: ${d.table || '?'} (${(d.percent || 0).toFixed(1)}%)`;
            case 'table_index_complete':
                return `Indexes complete: ${d.table || '?'}`;
            case 'table_restore_complete':
                return `Table ${d.table_name || d.table || '?'}: ${(d.row_count || 0).toLocaleString()} rows`;
            case 'restore_table_ready':
                return `Table ready: ${d.table || '?'}`;
            case 'restore_complete': {
                const dur = d.duration_seconds ?? d.elapsed_seconds;
                if (dur != null) {
                    return `Restore complete in ${dur.toFixed(1)}s`;
                }
                const tables = d.table_count || d.tables_count;
                return tables ? `Restore complete: ${tables} tables` : `Restore complete`;
            }
            case 'restore_failed':
                return `Restore failed: ${d.error || d.message || 'unknown'}`;

            // === Early analyze (during myloader) ===
            case 'early_analyze_started':
                return `Starting early analysis`;
            case 'table_analyze_started':
                return `Analyzing: ${d.table || '?'}`;
            case 'table_analyze_complete':
                return `Analyzed: ${d.table || '?'} (${(d.duration_seconds || 0).toFixed(2)}s)`;
            case 'early_analyze_batch_complete':
                return `Early analyze: ${d.tables_analyzed || '?'} tables (${(d.total_duration_seconds || 0).toFixed(1)}s)`;
            case 'early_analyze_myloader_complete':
                return `Early analyze finished with myloader`;

            // === Post-restore analyze ===
            case 'analyzing_started':
                return `Starting table analysis (${d.table_count || '?'} tables)`;
            case 'analyzing_complete':
                return `Analysis complete: ${d.tables_analyzed || '?'} tables`;

            // === Post-SQL scripts ===
            case 'post_sql_started':
                return `Starting post-SQL scripts on ${d.staging_db || 'staging'}`;
            case 'post_sql_script_complete':
                return `Script ${d.script_index || '?'}/${d.total_scripts || '?'}: ${d.script_name || '?'} (${d.rows_affected || 0} rows)`;
            case 'post_sql_complete':
                return `Post-SQL: ${d.statements_executed || d.scripts_executed || d.total_scripts || 0} scripts`;

            // === Metadata update ===
            case 'metadata_update_started':
                return `Updating metadata in ${d.staging_db || '?'}`;
            case 'metadata_update_complete':
                return `Metadata updated (${(d.duration_seconds || 0).toFixed(2)}s)`;
            case 'metadata_synthesis_started':
                return `Synthesizing metadata`;
            case 'metadata_synthesis_complete':
                return `Metadata synthesis complete`;

            // === Atomic rename phase ===
            case 'atomic_rename_validating': {
                if (d.staging_db && d.target_db) {
                    return `Validating rename: ${d.staging_db} → ${d.target_db}`;
                }
                if (d.expected_tables) {
                    return `Validating: ${d.expected_tables} tables (${d.phase || 'validation'})`;
                }
                return `Validating rename`;
            }
            case 'atomic_rename_validation_pass':
                return `Validation passed: ${d.table_count || '?'} tables`;
            case 'atomic_rename_checking_procedure':
                return `Checking stored procedure`;
            case 'atomic_rename_procedure_ready':
                return `Stored procedure ready`;
            case 'atomic_rename_started':
                return `Atomic rename: swapping ${d.total_tables || d.tables_total || '?'} tables`;
            case 'atomic_rename_executing':
                return `Executing atomic rename`;
            case 'atomic_rename_target_dropped':
                return `Dropped existing target: ${d.target_db || '?'}`;
            case 'atomic_rename_progress': {
                const tableName = d.message || d.table || d.table_name || '';
                const renamed = d.tables_renamed || '?';
                const total = d.total_tables || d.tables_total || '?';
                return tableName ? `Renamed: ${tableName} (${renamed}/${total})` : `Renamed ${renamed}/${total} tables`;
            }
            case 'atomic_rename_complete': {
                const tables = d.tables_renamed || d.total_tables || d.table_count;
                const dur = d.duration_seconds ?? d.elapsed_seconds;
                if (tables && dur != null) {
                    return `Atomic rename complete: ${tables} tables in ${dur.toFixed(1)}s`;
                }
                if (dur != null) {
                    return `Atomic rename complete in ${dur.toFixed(1)}s`;
                }
                if (tables) {
                    return `Atomic rename complete: ${tables} tables`;
                }
                return `Atomic rename complete`;
            }

            // === Workflow/profile ===
            case 'workflow_complete':
                return `Workflow complete in ${(d.duration_seconds || 0).toFixed(1)}s`;
            case 'restore_profile':
                return `Profile recorded`;

            // === Delete operations ===
            case 'delete_started':
            case 'job_delete_started':
                return `Starting database deletion`;
            case 'database_dropped':
                return `Dropped: ${d.database || d.db || '?'}`;
            case 'delete_complete':
            case 'job_delete_complete':
                return `Deletion complete`;
            case 'delete_failed':
            case 'job_delete_failed':
                return `Delete failed: ${d.error || d.message || 'unknown'}`;
            case 'force_delete_started':
                return `Force deleting databases`;
            case 'force_delete_failed':
                return `Force delete failed: ${d.error || d.message || 'unknown'}`;

            // === Admin/bulk operations ===
            case 'admin_task_started':
                return `Admin task: ${d.task || '?'}`;
            case 'admin_task_failed':
                return `Admin task failed: ${d.error || d.message || 'unknown'}`;
            case 'bulk_delete_started':
                return `Bulk delete: ${d.count || '?'} databases`;
            case 'bulk_delete_failed':
                return `Bulk delete failed: ${d.error || d.message || 'unknown'}`;
            case 'retention_cleanup_started':
                return `Starting retention cleanup`;
            case 'retention_cleanup_failed':
                return `Retention cleanup failed: ${d.error || d.message || 'unknown'}`;

            // === Default fallback ===
            default:
                if (d.message) return d.message;
                if (d.error) return d.error;
                if (Object.keys(d).length > 0) {
                    return JSON.stringify(d).slice(0, 200);
                }
                return '';
        }
    }

    _formatProgress(d) {
        const pct = d.percent != null ? `${d.percent.toFixed(1)}%` : '';
        const tables = d.tables_complete != null ? `${d.tables_complete}/${d.tables_total || '?'} tables` : '';
        const rows = d.rows_complete != null ? `${d.rows_complete.toLocaleString()} rows` : '';
        return [pct, tables, rows].filter(Boolean).join(' • ');
    }

    _formatBytes(bytes) {
        if (bytes == null) return '?';
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
        return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
    }

    _updateCount() {
        if (this._countEl) {
            this._countEl.textContent = `${this.totalEvents} events`;
        }
    }

    // =========================================================================
    // Polling (for running jobs)
    // =========================================================================

    _startPolling() {
        if (this._pollTimer || this._isDestroyed) return;
        console.log(`[VirtualLog] Starting poll for job ${this.jobId} (interval: ${this.pollInterval}ms)`);
        this._pollTimer = setInterval(() => this._poll(), this.pollInterval);
        // Also poll immediately to get latest state
        this._poll();
    }

    _stopPolling() {
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
    }

    async _poll() {
        if (this._isDestroyed) return;

        try {
            const params = new URLSearchParams({
                limit: '50',
                direction: 'newer',
            });

            // Get newest event from position 0
            const newestEvent = this._cache.get(0);
            if (newestEvent) {
                params.set('cursor', newestEvent.id.toString());
            }

            const response = await fetch(`/web/jobs/${this.jobId}/events?${params}`);
            if (!response.ok) return;

            const data = await response.json();

            // Check if job is still active - stop polling if complete
            if (data.is_active === false) {
                console.log(`[VirtualLog] Job ${this.jobId} completed (status: ${data.job_status}), stopping poll`);
                this.isRunning = false;
                this._stopPolling();
                // One final update with any remaining events
            }

            // Check for restore_profile event - triggers page refresh to show complete state
            if (data.events && data.events.length > 0) {
                const hasProfileEvent = data.events.some(e => e.event_type === 'restore_profile');
                if (hasProfileEvent) {
                    console.log(`[VirtualLog] restore_profile detected - refreshing page to show complete state`);
                    this._stopPolling();
                    // Small delay to let user see the event before refresh
                    setTimeout(() => window.location.reload(), 500);
                    return;
                }
            }

            // Always update total_count from server (authoritative)
            if (data.total_count != null && data.total_count !== this.totalEvents) {
                const oldTotal = this.totalEvents;
                this.totalEvents = data.total_count;
                this._updateSpacerHeight();
                this._updateCount();
                console.log(`[VirtualLog] Total events updated: ${oldTotal} → ${this.totalEvents}`);
            }

            if (data.events && data.events.length > 0) {
                // New events go at position 0, shift existing positions
                const shift = data.events.length;
                
                // Shift all existing cache entries
                const newCache = new Map();
                for (const [pos, event] of this._cache.entries()) {
                    newCache.set(pos + shift, event);
                }
                
                // Add new events at positions 0 to shift-1
                for (let i = 0; i < data.events.length; i++) {
                    newCache.set(i, data.events[i]);
                }
                
                this._cache = newCache;
                this._cacheStartPos = 0;
                this._cacheEndPos += shift;
                
                // Force re-render to show new events at top
                // Use -999 to ensure comparison fails even when range starts at 0
                this._renderedStart = -999;
                this._renderedEnd = -999;
                this._render();
                
                console.log(`[VirtualLog] Poll: +${shift} events, total now ${this.totalEvents}`);
            }
        } catch (err) {
            console.error('VirtualLog poll error:', err);
        }
    }

    // =========================================================================
    // Cleanup
    // =========================================================================

    destroy() {
        this._isDestroyed = true;
        this._stopPolling();
        
        // Cancel pending debounce timer
        clearTimeout(this._loadDebounceTimer);
        
        // Cancel in-flight requests
        if (this._abortController) {
            this._abortController.abort();
            this._abortController = null;
        }
        
        this._scrollEl.removeEventListener('scroll', this._onScroll);
        this.container.innerHTML = '';
        this.container.classList.remove('virtual-log-widget');
        this._cache.clear();
    }
}

// Export for use
window.VirtualLog = VirtualLog;
