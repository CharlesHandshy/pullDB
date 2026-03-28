/**
 * LazyTable - Server-Side Lazy Loading Table Widget
 * Version: 1.0.1 (2026-01-09 - Fixed select-all checkbox updates)
 * ==================================================
 * HCA Layer: widgets (Layer 3)
 * 
 * A high-performance table component with:
 * - Server-side lazy loading with cache windowing
 * - Column sort/filter controls in headers
 * - Fixed header/footer with flex layout
 * - Optional row selection with full-dataset "Select All"
 * - Selection persistence across filter/sort changes
 * - Virtual action cell columns
 * 
 * Usage:
 *   const table = new LazyTable({
 *       container: document.getElementById('my-table-container'),
 *       columns: [
 *           { key: 'id', label: 'ID', sortable: true, width: '80px' },
 *           { key: 'name', label: 'Name', sortable: true, filterable: true },
 *           { key: 'status', label: 'Status', sortable: true, filterable: true,
 *             render: (val, row) => `<span class="badge badge-${val}">${val}</span>` },
 *           { type: 'actions', label: 'Actions', width: '120px',
 *             actions: [
 *                 { icon: 'eye', label: 'View', className: 'primary', onClick: (row) => viewRow(row) },
 *                 { icon: 'trash', label: 'Delete', className: 'danger', onClick: (row) => deleteRow(row),
 *                   visible: (row) => row.canDelete }
 *             ]
 *           }
 *       ],
 *       fetchUrl: '/api/data',
 *       rowHeight: 48,
 *       selectable: true,
 *       selectionMode: 'multiple',
 *       onSelectionChange: (state) => console.log('Selection:', state)
 *   });
 */

class LazyTable {
    /**
     * @param {Object} config - Configuration object
     * @param {HTMLElement} config.container - Container element for the table
     * @param {Array} config.columns - Column definitions
     * @param {string} config.fetchUrl - URL for fetching data (receives page, pageSize, sort, filters)
     * @param {number} [config.rowHeight=48] - Height of each row in pixels
     * @param {string} [config.rowIdKey='id'] - Key for unique row identifier
     * @param {boolean} [config.selectable=false] - Enable row selection
     * @param {string} [config.selectionMode='multiple'] - 'single' or 'multiple'
     * @param {Function} [config.canSelect] - Callback(rowData) => boolean to determine if row is selectable
     * @param {Function} [config.onSelectionChange] - Callback when selection changes
     * @param {Function} [config.onRowClick] - Callback when row is clicked (if not selectable)
     * @param {string} [config.emptyMessage='No data available'] - Message when no data
     * @param {string} [config.tableId] - ID for the table (auto-generated if not provided)
     * @param {boolean} [config.deferInitialLoad=false] - If true, don't load data until refresh() is called
     * @param {Function} [config.onLoadingChange] - Callback(isLoading) when loading state changes
     * @param {Object} [config.i18n] - Internationalization strings
     */
    constructor(config) {
        this.config = {
            rowHeight: 48,
            rowIdKey: 'id',
            selectable: false,
            selectionMode: 'multiple',
            canSelect: null,
            showSelectionBar: true,
            selectionActions: [],
            emptyMessage: 'No data available',
            tableId: `lazy-table-${Date.now()}`,
            deferInitialLoad: false,
            i18n: {
                showing: 'Showing',
                of: 'of',
                items: 'items',
                selected: 'selected',
                selectAll: 'Select all',
                selectAllFiltered: 'Select all filtered',
                clearSelection: 'Clear selection',
                loading: 'Loading...',
                noResults: 'No results found',
                sortAsc: 'Sort ascending',
                sortDesc: 'Sort descending',
                clearSort: 'Clear sort',
                filter: 'Filter',
                clearFilter: 'Clear filter',
                search: 'Search...',
                apply: 'Apply',
                clear: 'Clear',
                errorMessage: 'Failed to load data',
                retry: 'Retry'
            },
            ...config
        };

        // Validate required config
        if (!this.config.container) throw new Error('LazyTable: container is required');
        if (!this.config.columns) throw new Error('LazyTable: columns are required');
        if (!this.config.fetchUrl) throw new Error('LazyTable: fetchUrl is required');

        // Cache management
        this.cache = new Map();  // pageIndex -> { rows: [], timestamp }
        this.totalCount = 0;
        this.filteredCount = 0;
        
        // Viewport state
        this.rowHeight = this.config.rowHeight;
        this.visibleRowCount = 0;
        this.bufferMultiplier = 3;
        this.pageSize = 50;  // Will be recalculated
        this.scrollTop = 0;
        
        // Sort/filter state
        this.sortColumn = null;
        this.sortDirection = null;  // 'asc' | 'desc' | null
        this.columnFilters = {};    // { columnKey: Set<values> }
        this.filterOrder = [];      // Column keys in order of selection (for cascading)
        
        // Apply initial filters if provided (only on first load)
        if (this.config.initialFilters) {
            Object.entries(this.config.initialFilters).forEach(([key, values]) => {
                this.columnFilters[key] = new Set(Array.isArray(values) ? values : [values]);
            });
        }
        
        // Selection state (persists across cache clears)
        this.selection = {
            mode: 'partial',  // 'all' | 'partial'
            includeIds: new Set(),
            excludeIds: new Set()
        };
        
        // Loading state
        this.isLoading = false;
        this.hasError = false;
        this.pendingFetch = null;
        this._pendingRefresh = false;   // queued refresh waiting for current to finish

        // Filter popup concurrency guards
        this._filterOpenToken = 0;           // incremented on every open; stale opens bail out
        this._distinctFetchController = null; // AbortController for in-flight distinct fetch
        
        // Render optimization state
        this._lastRenderStart = -1;
        this._lastRenderEnd = -1;
        this._forceRender = false;
        this._scrollRenderTimer = null;
        
        // Column filter distinct values cache
        this.distinctValues = {};  // { columnKey: [] }

        // Responsive column hiding: keys of columns currently collapsed
        this._hiddenColumns = new Set();

        // Build and initialize
        this.buildDOM();
        this.bindEvents();
        this.calculateViewport();
        
        // Update filter indicators for initial filters (after DOM is built)
        if (this.config.initialFilters) {
            this.updateFilterIndicators();
        }
        
        // Compute initial responsive column visibility before first fetch
        this.updateResponsiveColumns(true);

        // Fetch initial data unless deferInitialLoad is true
        if (!this.config.deferInitialLoad) {
            this.fetchInitialData();
        }

        // Preload distinct values for all filterable columns in the background.
        // This fires once at init so filter dropdowns open instantly on first use.
        this._preloadDistinctValues();
    }

    // =========================================================================
    // DOM Construction
    // =========================================================================

    buildDOM() {
        const { container, tableId, columns, selectable } = this.config;
        
        container.innerHTML = '';
        container.classList.add('lazy-table-widget');

        this.elements = {};

        // Main flex container
        this.elements.wrapper = document.createElement('div');
        this.elements.wrapper.className = 'lazy-table-wrapper';
        container.appendChild(this.elements.wrapper);

        // Selection bar (shown when items selected) - only if showSelectionBar enabled
        if (selectable && this.config.showSelectionBar) {
            this.elements.selectionBar = this.createSelectionBar();
            this.elements.wrapper.appendChild(this.elements.selectionBar);
        }

        // Filter chips container (shows active filters in selection order)
        this.elements.filterChipsContainer = document.createElement('div');
        this.elements.filterChipsContainer.className = 'lazy-table-filter-chips hidden';
        this.elements.wrapper.appendChild(this.elements.filterChipsContainer);

        // Header container (fixed)
        this.elements.headerContainer = document.createElement('div');
        this.elements.headerContainer.className = 'lazy-table-header-container';
        this.elements.wrapper.appendChild(this.elements.headerContainer);

        // Header table
        this.elements.headerTable = this.createHeaderTable();
        this.elements.headerContainer.appendChild(this.elements.headerTable);

        // Body container (flex: 1, scrollable)
        this.elements.bodyContainer = document.createElement('div');
        this.elements.bodyContainer.className = 'lazy-table-body-container';
        this.elements.wrapper.appendChild(this.elements.bodyContainer);

        // Virtual scroll spacer
        this.elements.spacer = document.createElement('div');
        this.elements.spacer.className = 'lazy-table-spacer';
        this.elements.bodyContainer.appendChild(this.elements.spacer);

        // Content container (positioned via transform)
        this.elements.content = document.createElement('div');
        this.elements.content.className = 'lazy-table-content';
        this.elements.bodyContainer.appendChild(this.elements.content);

        // Body table
        this.elements.bodyTable = document.createElement('table');
        this.elements.bodyTable.className = 'lazy-table-body';
        this.elements.bodyTable.id = `${tableId}-body`;
        this.elements.content.appendChild(this.elements.bodyTable);

        // Body colgroup (syncs widths with header)
        this.elements.bodyTable.appendChild(this.createColgroup());

        // Tbody
        this.elements.tbody = document.createElement('tbody');
        this.elements.bodyTable.appendChild(this.elements.tbody);

        // Footer container (fixed)
        this.elements.footerContainer = document.createElement('div');
        this.elements.footerContainer.className = 'lazy-table-footer-container';
        this.elements.wrapper.appendChild(this.elements.footerContainer);

        // Footer content
        this.elements.footerContent = this.createFooter();
        this.elements.footerContainer.appendChild(this.elements.footerContent);

        // Loading overlay
        this.elements.loadingOverlay = document.createElement('div');
        this.elements.loadingOverlay.className = 'lazy-table-loading';
        this.elements.loadingOverlay.innerHTML = `
            <div class="lazy-table-loading-spinner"></div>
            <span>${this.config.i18n.loading}</span>
        `;
        this.elements.wrapper.appendChild(this.elements.loadingOverlay);

        // Error overlay
        this.elements.errorOverlay = document.createElement('div');
        this.elements.errorOverlay.className = 'lazy-table-error';
        this.elements.errorOverlay.innerHTML = `
            <svg class="error-icon" viewBox="0 0 24 24" width="48" height="48">
                <path fill="currentColor" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
            </svg>
            <span class="error-message">${this.config.i18n.errorMessage}</span>
            <button type="button" class="error-retry-btn">${this.config.i18n.retry}</button>
        `;
        this.elements.wrapper.appendChild(this.elements.errorOverlay);

        // Empty state overlay
        this.elements.emptyOverlay = document.createElement('div');
        this.elements.emptyOverlay.className = 'lazy-table-empty';
        this.elements.emptyOverlay.innerHTML = `
            <svg class="empty-icon" viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M22 12h-6l-2 3h-4l-2-3H2"/>
                <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>
            </svg>
            <span class="empty-message">${this.config.emptyMessage}</span>
        `;
        this.elements.wrapper.appendChild(this.elements.emptyOverlay);
    }

    createSelectionBar() {
        const bar = document.createElement('div');
        bar.className = 'lazy-table-selection-bar hidden';
        bar.innerHTML = `
            <span class="selection-count"></span>
            <button type="button" class="selection-select-all">${this.config.i18n.selectAllFiltered}</button>
            <button type="button" class="selection-clear">${this.config.i18n.clearSelection}</button>
        `;
        return bar;
    }

    createHeaderTable() {
        const { columns, selectable, selectionMode, tableId } = this.config;
        
        const table = document.createElement('table');
        table.className = 'lazy-table-header';
        table.id = `${tableId}-header`;
        
        const thead = document.createElement('thead');
        const tr = document.createElement('tr');
        
        // Selection checkbox column with optional action buttons
        if (selectable && selectionMode === 'multiple') {
            const th = document.createElement('th');
            th.className = 'lazy-table-th lazy-table-th-select';
            
            // Build action buttons HTML
            let actionsHtml = '';
            if (this.config.selectionActions && this.config.selectionActions.length > 0) {
                actionsHtml = this.config.selectionActions.map(action => {
                    const minSelected = action.minSelected || 1;
                    return `<button type="button" class="selection-action-btn" data-action="${action.id}" data-min-selected="${minSelected}" title="${action.title || ''}" disabled>
                        ${action.icon || ''}
                    </button>`;
                }).join('');
            }
            
            th.innerHTML = `
                <div class="lazy-table-select-header">
                    <label class="lazy-table-checkbox">
                        <input type="checkbox" class="select-all-checkbox">
                        <span class="checkmark"></span>
                    </label>
                    ${actionsHtml}
                </div>
            `;
            tr.appendChild(th);
        }
        
        // Data columns
        columns.forEach((col, index) => {
            const th = document.createElement('th');
            th.className = 'lazy-table-th';
            th.dataset.columnKey = col.key || `action-${index}`;
            th.dataset.columnIndex = index;
            
            if (col.type === 'actions' || (!col.sortable && !col.filterable)) {
                // Action column or non-interactive column - no sort/filter controls
                if (col.type === 'actions') th.classList.add('lazy-table-th-actions');
                // Support custom header render function
                if (col.headerRender) {
                    th.innerHTML = col.headerRender();
                } else {
                    th.innerHTML = `<span class="th-label">${col.label != null ? col.label : ''}</span>`;
                }
            } else {
                // Regular column with sort/filter controls
                th.innerHTML = this.createColumnHeaderContent(col);
                if (col.sortable) th.classList.add('sortable');
                if (col.filterable) th.classList.add('filterable');
            }
            
            tr.appendChild(th);
        });
        
        thead.appendChild(tr);
        table.appendChild(this.createColgroup());
        table.appendChild(thead);
        return table;
    }

    /**
     * Create a colgroup element for consistent column widths across header/body tables
     * @returns {HTMLElement}
     */
    createColgroup() {
        const { columns, selectable, selectionMode } = this.config;
        const colgroup = document.createElement('colgroup');
        
        // Selection checkbox column
        if (selectable && selectionMode === 'multiple') {
            const col = document.createElement('col');
            col.style.width = '48px';
            colgroup.appendChild(col);
        }
        
        // Data columns (skip hidden)
        columns.forEach(colDef => {
            const key = colDef.key || colDef.type || '';
            if (this._hiddenColumns.has(key)) return;
            const col = document.createElement('col');
            if (colDef.width) col.style.width = colDef.width;
            colgroup.appendChild(col);
        });

        return colgroup;
    }

    createColumnHeaderContent(col) {
        const sortIcon = col.sortable ? `
            <button type="button" class="sort-btn" title="${this.config.i18n.sortAsc}" data-column="${col.key}">
                <svg class="sort-icon sort-icon-asc" viewBox="0 0 24 24" width="14" height="14">
                    <path fill="currentColor" d="M7 14l5-5 5 5z"/>
                </svg>
                <svg class="sort-icon sort-icon-desc" viewBox="0 0 24 24" width="14" height="14">
                    <path fill="currentColor" d="M7 10l5 5 5-5z"/>
                </svg>
            </button>
        ` : '';
        
        const filterIcon = col.filterable ? `
            <button type="button" class="filter-btn" title="${this.config.i18n.filter}" data-column="${col.key}">
                <svg class="filter-icon" viewBox="0 0 24 24" width="14" height="14">
                    <path fill="currentColor" d="M10 18h4v-2h-4v2zM3 6v2h18V6H3zm3 7h12v-2H6v2z"/>
                </svg>
            </button>
        ` : '';
        
        // Add tooltip to label if provided
        const labelTitle = col.tooltip ? ` title="${col.tooltip}"` : '';
        
        // Order: filter icon, label, sort icons - no gaps
        return `
            <div class="th-content">
                ${filterIcon}<span class="th-label"${labelTitle}>${col.label != null ? col.label : col.key}</span>${sortIcon}
            </div>
        `;
    }

    createFooter() {
        const footer = document.createElement('div');
        footer.className = 'lazy-table-footer';
        footer.innerHTML = `
            <div class="footer-info">
                <span class="footer-showing"></span>
                <button type="button" class="footer-clear-filters-btn hidden">Clear Filters</button>
            </div>
            <div class="footer-spacer"></div>
            <div class="footer-status-indicator hidden">
                <span class="footer-status-spinner"></span>
                <span class="footer-status-text"></span>
            </div>
            <div class="footer-actions"></div>
        `;
        
        // Inject custom footer slot content if provided
        if (this.config.footerSlot) {
            const actionsContainer = footer.querySelector('.footer-actions');
            if (typeof this.config.footerSlot === 'string') {
                actionsContainer.innerHTML = this.config.footerSlot;
            } else if (this.config.footerSlot instanceof HTMLElement) {
                actionsContainer.appendChild(this.config.footerSlot);
            }
        }
        
        return footer;
    }

    // =========================================================================
    // Event Binding
    // =========================================================================

    bindEvents() {
        // Scroll handling
        this.elements.bodyContainer.addEventListener('scroll', this.handleScroll.bind(this));
        
        // Window resize (debounced)
        this._resizeHandler = this.debounce(this.handleResize.bind(this), 150);
        window.addEventListener('resize', this._resizeHandler);
        
        // Header events
        this.elements.headerTable.addEventListener('click', this.handleHeaderClick.bind(this));
        
        // Body events
        this.elements.tbody.addEventListener('click', this.handleBodyClick.bind(this));
        
        // Selection bar events (only if selection bar exists)
        if (this.config.selectable && this.elements.selectionBar) {
            const selectAllBtn = this.elements.selectionBar.querySelector('.selection-select-all');
            const clearBtn = this.elements.selectionBar.querySelector('.selection-clear');
            
            selectAllBtn?.addEventListener('click', () => this.selectAllFiltered());
            clearBtn?.addEventListener('click', () => this.clearSelection());
        }
        
        // Selection header events (checkbox and action buttons)
        if (this.config.selectable) {
            // Select all checkbox
            const selectAllCheckbox = this.elements.headerTable.querySelector('.select-all-checkbox');
            if (selectAllCheckbox) {
                selectAllCheckbox.addEventListener('change', (e) => {
                    if (e.target.checked) {
                        this.selectAllFiltered();
                    } else {
                        this.clearSelection();
                    }
                });
            }
            
            // Selection action buttons
            const actionBtns = this.elements.headerTable.querySelectorAll('.selection-action-btn');
            actionBtns.forEach(btn => {
                btn.addEventListener('click', () => {
                    const actionId = btn.dataset.action;
                    const action = this.config.selectionActions.find(a => a.id === actionId);
                    if (action && action.onClick) {
                        action.onClick(this.getSelectionState());
                    }
                });
            });
        }
        
        // Error retry button
        const retryBtn = this.elements.errorOverlay.querySelector('.error-retry-btn');
        retryBtn?.addEventListener('click', () => this.refresh());
        
        // Footer clear filters button
        const clearFiltersBtn = this.elements.footerContent.querySelector('.footer-clear-filters-btn');
        clearFiltersBtn?.addEventListener('click', () => this.clearAllFilters());
    }

    // =========================================================================
    // Viewport Management
    // =========================================================================

    calculateViewport() {
        const containerHeight = this.elements.bodyContainer.clientHeight;
        // Guard against zero height (container not yet laid out in DOM)
        this.visibleRowCount = Math.max(1, Math.ceil(containerHeight / this.rowHeight));
        this.pageSize = Math.max(50, this.visibleRowCount * this.bufferMultiplier);
    }

    handleResize() {
        this.updateResponsiveColumns();
        const prevVisibleCount = this.visibleRowCount;
        this.calculateViewport();
        if (this.visibleRowCount !== prevVisibleCount) {
            this.render();
        }
    }

    /**
     * Compute which columns should be hidden based on container width and
     * each column's `hideBelow` threshold. Rebuilds colgroups + header row
     * and forces a re-render if the visible column set changed.
     * @param {boolean} [force=false] - Skip change-detection and always rebuild
     */
    updateResponsiveColumns(force = false) {
        const containerWidth = this.elements.wrapper.offsetWidth;
        if (!containerWidth) return;

        const prevHidden = new Set(this._hiddenColumns);
        this._hiddenColumns.clear();

        this.config.columns.forEach(col => {
            const key = col.key || col.type || '';
            if (col.hideBelow && containerWidth < col.hideBelow) {
                this._hiddenColumns.add(key);
            }
        });

        // Detect change
        const changed = force ||
            prevHidden.size !== this._hiddenColumns.size ||
            [...this._hiddenColumns].some(k => !prevHidden.has(k)) ||
            [...prevHidden].some(k => !this._hiddenColumns.has(k));

        if (!changed) return;

        // Rebuild colgroups (both header and body tables)
        const replaceColgroup = (table) => {
            const old = table.querySelector('colgroup');
            if (old) old.remove();
            table.insertBefore(this.createColgroup(), table.firstChild);
        };
        replaceColgroup(this.elements.headerTable);
        replaceColgroup(this.elements.bodyTable);

        // Rebuild header thead row
        const thead = this.elements.headerTable.querySelector('thead');
        if (thead) {
            const { columns, selectable, selectionMode } = this.config;
            const tr = document.createElement('tr');

            if (selectable && selectionMode === 'multiple') {
                tr.appendChild(thead.querySelector('tr').firstElementChild.cloneNode(true));
            }

            columns.forEach((col, index) => {
                const key = col.key || col.type || '';
                if (this._hiddenColumns.has(key)) return;
                const existing = thead.querySelector(`th[data-column-key="${col.key || `action-${index}`}"]`);
                if (existing) {
                    tr.appendChild(existing.cloneNode(true));
                } else {
                    // Rebuild th from scratch
                    const th = document.createElement('th');
                    th.className = 'lazy-table-th';
                    th.dataset.columnKey = col.key || `action-${index}`;
                    th.dataset.columnIndex = index;
                    if (col.type === 'actions' || (!col.sortable && !col.filterable)) {
                        if (col.type === 'actions') th.classList.add('lazy-table-th-actions');
                        if (col.headerRender) {
                            th.innerHTML = col.headerRender();
                        } else {
                            th.innerHTML = `<span class="th-label">${col.label != null ? col.label : ''}</span>`;
                        }
                    } else {
                        th.innerHTML = this.createColumnHeaderContent(col);
                        if (col.sortable) th.classList.add('sortable');
                        if (col.filterable) th.classList.add('filterable');
                    }
                    tr.appendChild(th);
                }
            });

            thead.innerHTML = '';
            thead.appendChild(tr);
        }

        this._forceRender = true;
        this.render();
    }

    handleScroll() {
        if (this.isLoading) return;
        
        // Cancel any pending scroll render
        if (this._scrollRenderTimer) {
            cancelAnimationFrame(this._scrollRenderTimer);
        }
        
        // Use requestAnimationFrame to batch scroll renders at 60fps
        this._scrollRenderTimer = requestAnimationFrame(() => {
            this.scrollTop = this.elements.bodyContainer.scrollTop;
            this.render();
            this.checkFetchNeeded();
        });
    }

    // =========================================================================
    // Data Fetching
    // =========================================================================

    async fetchInitialData() {
        // Show skeleton rows immediately for better perceived performance
        this.renderSkeletonRows();
        
        try {
            await this.fetchPage(0);
            console.debug('LazyTable: fetchInitialData complete, cache:', this.cache, 'totalCount:', this.totalCount);
            this.render();
        } catch (error) {
            // Error already shown by fetchPage
            console.error('LazyTable: fetchInitialData error', error);
        }
    }

    async fetchPage(pageIndex) {
        if (this.cache.has(pageIndex)) return;
        
        // Build URL properly using URL API to handle existing query params
        const url = new URL(this.config.fetchUrl, window.location.origin);
        url.searchParams.set('page', pageIndex);
        url.searchParams.set('pageSize', this.pageSize);
        
        // Add sort
        if (this.sortColumn && this.sortDirection) {
            url.searchParams.set('sortColumn', this.sortColumn);
            url.searchParams.set('sortDirection', this.sortDirection);
        }
        
        // Add filters
        Object.entries(this.columnFilters).forEach(([key, values]) => {
            if (values.size > 0) {
                const valueStr = Array.from(values).join(',');
                const colDef = this.getColumnDef(key);
                
                // Handle dateRange filter type generically - split into _after/_before params
                if (colDef && colDef.filterType === 'dateRange' && valueStr.includes(',')) {
                    const parts = valueStr.split(',');
                    if (parts[0]) {
                        url.searchParams.set(`filter_${key}_after`, parts[0]);
                    }
                    if (parts[1]) {
                        url.searchParams.set(`filter_${key}_before`, parts[1]);
                    }
                    return;
                }
                
                url.searchParams.set(`filter_${key}`, valueStr);
            }
        });
        
        try {
            const response = await fetch(url.toString(), {
                headers: {
                    'HX-Request': 'true'  // Mark as AJAX request for server-side checks
                }
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            
            const data = await response.json();
            
            // Check for server-side error in response
            if (data.error) {
                console.error('LazyTable: server error', data.error);
                this.showError(data.error);
                return;
            }
            
            this.cache.set(pageIndex, {
                rows: data.rows || data.data || [],
                timestamp: Date.now()
            });
            const firstRow = (data.rows || data.data || [])[0];
            console.debug('LazyTable: cached page', pageIndex, 'rows:', (data.rows || data.data || []).length);
            console.debug('LazyTable: first row keys:', firstRow ? Object.keys(firstRow) : 'none');
            console.debug('LazyTable: first row owner_username:', firstRow?.owner_username, 'dbhost:', firstRow?.dbhost, 'total_duration_seconds:', firstRow?.total_duration_seconds);
            
            this.totalCount = data.totalCount ?? data.total ?? 0;
            this.filteredCount = data.filteredCount ?? data.totalCount ?? this.totalCount;
            console.debug('LazyTable: totalCount:', this.totalCount, 'filteredCount:', this.filteredCount);
            
            // Call onDataLoaded callback if provided
            if (this.config.onDataLoaded) {
                this.config.onDataLoaded(data);
            }
            
        } catch (error) {
            console.error('LazyTable: fetch error', error);
            this.showError();
            throw error;  // Re-throw so callers know fetch failed
        }
    }

    checkFetchNeeded() {
        const startRow = Math.floor(this.scrollTop / this.rowHeight);
        const startPage = Math.floor(startRow / this.pageSize);
        const endRow = startRow + this.visibleRowCount + (this.pageSize / 3);
        const endPage = Math.floor(endRow / this.pageSize);
        
        // Prefetch adjacent pages
        for (let p = Math.max(0, startPage - 1); p <= endPage + 1; p++) {
            if (!this.cache.has(p) && !this.isLoading) {
                this.fetchPage(p);
            }
        }
    }

    clearCache() {
        this.cache.clear();
        this.distinctValues = {};
        this._forceRender = true;  // Force render after cache clear
    }

    /**
     * Refresh table data
     * @param {Object} options - Refresh options
     * @param {boolean} options.quiet - If true, show footer spinner instead of overlay (for auto-refresh)
     */
    async refresh(options = {}) {
        const { quiet = false } = options;
        
        // Prevent concurrent refreshes; queue one retry so a filter/sort applied
        // during a load isn't silently dropped.
        if (this.isLoading) {
            this._pendingRefresh = true;
            return;
        }
        this._pendingRefresh = false;
        
        if (quiet) {
            // Quiet refresh: footer spinner, no cache clear, keep existing data visible
            this.hideFooterError();
            this.showFooterLoading();
            this.isLoading = true;
            
            // Notify loading state change
            if (this.config.onLoadingChange) {
                this.config.onLoadingChange(true);
            }
            
            try {
                // Invalidate the pages we are about to re-fetch so fetchPage
                // actually hits the server (it is a no-op for cached pages).
                // We selectively delete only what we will re-fetch to keep the
                // rest of the cache intact so the overlay is not needed.
                this.cache.delete(0);
                const visiblePage = Math.floor(
                    Math.floor(this.scrollTop / this.rowHeight) / this.pageSize
                );
                if (visiblePage !== 0) this.cache.delete(visiblePage);

                await this.fetchPage(0);
                if (visiblePage !== 0) await this.fetchPage(visiblePage);

                this.hideFooterLoading();
                // Force render so row-level data changes (status, badge, etc.) paint
                // even when the visible row range hasn't changed.
                this._forceRender = true;
                this.render();
            } catch (error) {
                this.hideFooterLoading();
                this.showFooterError('Refresh failed');
            } finally {
                this.isLoading = false;

                // Notify loading state change
                if (this.config.onLoadingChange) {
                    this.config.onLoadingChange(false);
                }

                // Fire any queued refresh (e.g. a sort/filter applied while loading)
                if (this._pendingRefresh) {
                    this._pendingRefresh = false;
                    this.refresh(options);
                }
            }
        } else {
            // Full refresh: overlay, clear cache (isLoading set by showLoading)
            this.clearCache();
            this.hideError();  // Auto-dismiss error on retry
            this.showLoading();
            try {
                await this.fetchPage(0);
                this.hideLoading();
                // Re-assert _forceRender: a concurrent clearSelection() or other
                // synchronous render() call during the await may have consumed
                // the _forceRender flag set by clearCache(), causing the post-fetch
                // render() to be skipped when renderStart/End happen to match.
                this._forceRender = true;
                this.render();
                this.checkFetchNeeded();
            } catch (error) {
                this.hideLoading();
                // Error already shown by fetchPage
            } finally {
                // Ensure isLoading is always cleared and pending refresh is honoured
                if (this.isLoading) {
                    this.hideLoading();
                }
                if (this._pendingRefresh) {
                    this._pendingRefresh = false;
                    this.refresh();
                }
            }
        }
    }

    // =========================================================================
    // Rendering
    // =========================================================================

    render() {
        const startRow = Math.floor(this.scrollTop / this.rowHeight);
        const bufferRows = Math.floor(this.visibleRowCount / 2);
        let renderStart = Math.max(0, startRow - bufferRows);
        let renderEnd = Math.min(this.filteredCount, startRow + this.visibleRowCount + bufferRows);
        
        // When near the end, ensure we always render the last complete viewport
        // This prevents bouncing when scrolling past the end of the data
        const totalRenderableRows = renderEnd - renderStart;
        const maxRenderCount = this.visibleRowCount + (bufferRows * 2);
        if (renderEnd === this.filteredCount && totalRenderableRows < maxRenderCount) {
            // Pin to the last page - show the final viewport of rows
            renderStart = Math.max(0, this.filteredCount - maxRenderCount);
        }
        
        // Skip render if range hasn't changed (reduces DOM thrashing during scroll)
        if (this._lastRenderStart === renderStart && this._lastRenderEnd === renderEnd && !this._forceRender) {
            return;
        }
        this._lastRenderStart = renderStart;
        this._lastRenderEnd = renderEnd;
        this._forceRender = false;
        
        // Handle empty state
        if (this.filteredCount === 0 && !this.hasError && !this.isLoading) {
            this.showEmpty();
        } else {
            this.hideEmpty();
        }
        
        // Update spacer height
        this.elements.spacer.style.height = `${this.filteredCount * this.rowHeight}px`;
        
        // Position content with will-change hint for smoother transforms
        this.elements.content.style.transform = `translateY(${renderStart * this.rowHeight}px)`;
        
        // Render rows
        const fragment = document.createDocumentFragment();
        
        for (let i = renderStart; i < renderEnd; i++) {
            const row = this.getRowAt(i);
            if (row) {
                fragment.appendChild(this.createRowElement(row, i));
            } else {
                fragment.appendChild(this.createPlaceholderRow(i));
            }
        }
        
        this.elements.tbody.innerHTML = '';
        this.elements.tbody.appendChild(fragment);
        
        // Update footer
        this.updateFooter();
        
        // Update selection bar
        if (this.config.selectable) {
            this.updateSelectionBar();
        }
    }
    getRowAt(index) {
        const pageIndex = Math.floor(index / this.pageSize);
        const pageOffset = index % this.pageSize;
        
        const page = this.cache.get(pageIndex);
        if (page && page.rows && page.rows[pageOffset]) {
            return page.rows[pageOffset];
        }
        return null;
    }

    createRowElement(row, index) {
        const { columns, selectable, selectionMode, rowIdKey, onRowClick } = this.config;
        
        const tr = document.createElement('tr');
        tr.className = 'lazy-table-row';
        tr.dataset.rowIndex = index;
        tr.dataset.rowId = row[rowIdKey];
        
        // Check if selected
        const isSelected = this.isRowSelected(row[rowIdKey]);
        if (isSelected) tr.classList.add('selected');
        
        // Selection checkbox
        if (selectable && selectionMode === 'multiple') {
            const td = document.createElement('td');
            td.className = 'lazy-table-td lazy-table-td-select';
            
            // Check if row can be selected (via canSelect callback)
            const canSelectRow = !this.config.canSelect || this.config.canSelect(row);
            
            if (canSelectRow) {
                td.innerHTML = `
                    <label class="lazy-table-checkbox">
                        <input type="checkbox" class="row-checkbox" ${isSelected ? 'checked' : ''}>
                        <span class="checkmark"></span>
                    </label>
                `;
            } else {
                // Non-selectable row - show empty checkbox area
                td.innerHTML = '';
            }
            tr.appendChild(td);
        }
        
        // Data columns (skip hidden)
        columns.forEach((col, colIndex) => {
            if (this._hiddenColumns.has(col.key || col.type || '')) return;
            const td = document.createElement('td');
            td.className = 'lazy-table-td';
            
            if (col.type === 'actions') {
                td.classList.add('lazy-table-td-actions');
                // Use custom render if provided, otherwise use built-in action renderer
                if (col.render) {
                    td.innerHTML = col.render(null, row, colIndex);
                } else {
                    td.innerHTML = this.renderActions(col.actions, row);
                }
            } else {
                const value = row[col.key];
                if (col.render) {
                    td.innerHTML = col.render(value, row, colIndex);
                } else {
                    td.textContent = value ?? '';
                }
                
                // Apply nowrap and maxWidth styles for truncation with tooltip
                if (col.nowrap || col.maxWidth) {
                    td.classList.add('lazy-table-td-nowrap');
                    if (col.maxWidth) {
                        td.style.maxWidth = col.maxWidth;
                    }
                    // Add tooltip with full value for truncated content
                    const displayValue = value ?? '';
                    if (displayValue && typeof displayValue === 'string') {
                        td.title = displayValue;
                    }
                }
            }
            
            tr.appendChild(td);
        });
        
        // Row click for single selection
        if (selectable && selectionMode === 'single') {
            tr.style.cursor = 'pointer';
        } else if (!selectable && onRowClick) {
            tr.style.cursor = 'pointer';
        }
        
        // Call onRowRendered callback if provided
        if (this.config.onRowRendered) {
            this.config.onRowRendered(tr, row, index);
        }
        
        return tr;
    }

    createPlaceholderRow(index) {
        const { columns, selectable, selectionMode } = this.config;
        
        const tr = document.createElement('tr');
        tr.className = 'lazy-table-row lazy-table-row-placeholder';
        tr.dataset.rowIndex = index;
        
        // Placeholder for checkbox column
        if (selectable && selectionMode === 'multiple') {
            const td = document.createElement('td');
            td.className = 'lazy-table-td lazy-table-td-select';
            tr.appendChild(td);
        }
        
        // Placeholder cells (skip hidden)
        columns.forEach(col => {
            if (this._hiddenColumns.has(col.key || col.type || '')) return;
            const td = document.createElement('td');
            td.className = 'lazy-table-td';
            td.innerHTML = '<div class="placeholder-shimmer"></div>';
            tr.appendChild(td);
        });
        
        return tr;
    }

    /**
     * Render skeleton loading rows (shown during initial data fetch)
     * Shows pageSize rows for consistent perceived loading state
     */
    renderSkeletonRows() {
        const fragment = document.createDocumentFragment();
        const rowCount = this.pageSize;
        
        for (let i = 0; i < rowCount; i++) {
            fragment.appendChild(this.createPlaceholderRow(i));
        }
        
        this.elements.tbody.innerHTML = '';
        this.elements.tbody.appendChild(fragment);
        
        // Show "Loading..." in footer during skeleton state
        const showing = this.elements.footerContent.querySelector('.footer-showing');
        if (showing) {
            showing.textContent = this.config.i18n.loading;
        }
    }

    renderActions(actions, row) {
        if (!actions || actions.length === 0) return '';
        
        return actions
            .filter(action => !action.visible || action.visible(row))
            .map(action => `
                <button type="button" 
                        class="action-btn action-btn-${action.className || 'default'}"
                        data-action="${action.label}"
                        title="${action.label}">
                    ${action.icon ? this.getActionIcon(action.icon) : ''}
                    ${action.showLabel ? `<span>${action.label}</span>` : ''}
                </button>
            `).join('');
    }

    getActionIcon(iconName) {
        const icons = {
            view: '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>',
            edit: '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>',
            delete: '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>',
            cancel: '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>',
            download: '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>',
            copy: '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>'
        };
        return icons[iconName] || '';
    }

    updateFooter() {
        const showing = this.elements.footerContent?.querySelector('.footer-showing');
        if (!showing) return;  // Guard against missing element during skeleton state
        
        const selectedCount = this.getSelectedCount();
        
        // Calculate visible row range based on scroll position
        const startRow = Math.floor(this.scrollTop / this.rowHeight);
        const visibleStart = Math.min(startRow + 1, this.filteredCount); // 1-indexed for display
        const visibleEnd = Math.min(startRow + this.visibleRowCount, this.filteredCount);
        
        let text;
        if (this.filteredCount === 0) {
            text = `${this.config.i18n.showing} 0 ${this.config.i18n.items}`;
        } else {
            // Show range of current result set (filtered or total)
            text = `${this.config.i18n.showing} ${visibleStart}-${visibleEnd} ${this.config.i18n.of} ${this.filteredCount} ${this.config.i18n.items}`;
        }
        
        if (selectedCount > 0) {
            text += ` · ${selectedCount} ${this.config.i18n.selected}`;
        }
        
        showing.textContent = text;
    }

    updateSelectionBar() {
        const count = this.getSelectedCount();
        
        // Update selection bar if it exists
        const bar = this.elements.selectionBar;
        if (bar) {
            const countSpan = bar.querySelector('.selection-count');
            if (count > 0) {
                bar.classList.remove('hidden');
                countSpan.textContent = `${count} ${this.config.i18n.selected}`;
            } else {
                bar.classList.add('hidden');
            }
        }
        
        // Update header checkbox state
        const selectAllCheckbox = this.elements.headerTable.querySelector('.select-all-checkbox');
        if (selectAllCheckbox) {
            // When in "select all" mode with no exclusions, check the checkbox
            // regardless of whether all rows are selectable (canSelect callback)
            if (this.selection.mode === 'all' && this.selection.excludeIds.size === 0) {
                selectAllCheckbox.checked = true;
                selectAllCheckbox.indeterminate = false;
            } else if (this.selection.mode === 'all' && this.selection.excludeIds.size > 0) {
                // Some exclusions in "all" mode - show indeterminate
                selectAllCheckbox.checked = false;
                selectAllCheckbox.indeterminate = true;
            } else if (count > 0) {
                // Partial selection mode with some selections
                selectAllCheckbox.checked = false;
                selectAllCheckbox.indeterminate = true;
            } else {
                // No selections
                selectAllCheckbox.checked = false;
                selectAllCheckbox.indeterminate = false;
            }
        }
        
        // Update selection action buttons enabled state
        const actionBtns = this.elements.headerTable.querySelectorAll('.selection-action-btn');
        actionBtns.forEach(btn => {
            const minSelected = parseInt(btn.dataset.minSelected, 10) || 1;
            btn.disabled = count < minSelected;
        });
    }

    showLoading() {
        this.isLoading = true;
        this.hideEmpty();
        this.elements.loadingOverlay.classList.add('visible');
        
        // Notify loading state change
        if (this.config.onLoadingChange) {
            this.config.onLoadingChange(true);
        }
    }

    hideLoading() {
        this.isLoading = false;
        this.elements.loadingOverlay.classList.remove('visible');
        
        // Notify loading state change
        if (this.config.onLoadingChange) {
            this.config.onLoadingChange(false);
        }
    }

    showError(message = null) {
        this.hasError = true;
        this.hideLoading();
        this.hideEmpty();
        
        // Update error message if provided
        const errorMsg = this.elements.errorOverlay.querySelector('.error-message');
        if (errorMsg && message) {
            errorMsg.textContent = message;
        } else if (errorMsg) {
            errorMsg.textContent = this.config.i18n.errorMessage;
        }
        
        this.elements.errorOverlay.classList.add('visible');
    }

    hideError() {
        this.hasError = false;
        this.elements.errorOverlay.classList.remove('visible');
    }

    showEmpty() {
        this.elements.emptyOverlay.classList.add('visible');
    }

    hideEmpty() {
        this.elements.emptyOverlay.classList.remove('visible');
    }

    // Footer status indicator (for quiet refresh)
    showFooterLoading() {
        const indicator = this.elements.footerContent.querySelector('.footer-status-indicator');
        const spinner = indicator?.querySelector('.footer-status-spinner');
        const text = indicator?.querySelector('.footer-status-text');
        if (indicator) {
            indicator.classList.remove('hidden', 'error');
            indicator.classList.add('loading');
            if (spinner) spinner.classList.remove('hidden');
            if (text) text.textContent = '';
        }
    }

    hideFooterLoading() {
        const indicator = this.elements.footerContent.querySelector('.footer-status-indicator');
        if (indicator) {
            indicator.classList.remove('loading');
            indicator.classList.add('hidden');
        }
    }

    showFooterError(message = 'Error') {
        const indicator = this.elements.footerContent.querySelector('.footer-status-indicator');
        const spinner = indicator?.querySelector('.footer-status-spinner');
        const text = indicator?.querySelector('.footer-status-text');
        if (indicator) {
            indicator.classList.remove('hidden', 'loading');
            indicator.classList.add('error');
            if (spinner) spinner.classList.add('hidden');
            if (text) text.textContent = message;
            // Auto-hide error after 5 seconds
            setTimeout(() => this.hideFooterError(), 5000);
        }
    }

    hideFooterError() {
        const indicator = this.elements.footerContent.querySelector('.footer-status-indicator');
        if (indicator && indicator.classList.contains('error')) {
            indicator.classList.remove('error');
            indicator.classList.add('hidden');
        }
    }

    // =========================================================================
    // Event Handlers
    // =========================================================================

    handleHeaderClick(e) {
        const sortBtn = e.target.closest('.sort-btn');
        const filterBtn = e.target.closest('.filter-btn');

        if (sortBtn) {
            // Block sort clicks while a fetch is in flight — state would change but
            // refresh() would be a no-op, leaving sort indicators out of sync.
            if (this.isLoading) return;
            const column = sortBtn.dataset.column;
            this.toggleSort(column);
        }

        if (filterBtn) {
            // Ignore click on a button that is already loading its distinct values
            if (filterBtn.classList.contains('filter-btn-loading')) return;
            const column = filterBtn.dataset.column;
            // Use .then() since this is a sync event handler calling an async method
            this.showFilterDropdown(column, filterBtn).catch(err => {
                console.error('LazyTable: error showing filter dropdown', err);
            });
        }
    }

    handleBodyClick(e) {
        const { selectable, selectionMode, onRowClick, rowIdKey } = this.config;
        
        // Action button click
        const actionBtn = e.target.closest('.action-btn');
        if (actionBtn) {
            const row = e.target.closest('.lazy-table-row');
            const rowId = row?.dataset.rowId;
            const actionLabel = actionBtn.dataset.action;
            
            if (rowId) {
                const rowData = this.getRowById(rowId);
                const column = this.config.columns.find(c => c.type === 'actions');
                const action = column?.actions.find(a => a.label === actionLabel);
                
                if (action?.onClick && rowData) {
                    action.onClick(rowData);
                }
            }
            return;
        }
        
        // Row checkbox click
        const checkbox = e.target.closest('.row-checkbox');
        if (checkbox && selectable) {
            const row = e.target.closest('.lazy-table-row');
            const rowId = row?.dataset.rowId;
            if (rowId) {
                const rowData = this.getRowById(rowId);
                // Check canSelect before allowing toggle
                if (!this.config.canSelect || this.config.canSelect(rowData)) {
                    this.toggleRowSelection(rowId, checkbox.checked);
                }
            }
            return;
        }
        
        // Row click
        const row = e.target.closest('.lazy-table-row');
        if (row) {
            const rowId = row.dataset.rowId;
            const rowData = this.getRowById(rowId);
            
            if (selectable && selectionMode === 'single') {
                this.selectSingle(rowId);
            } else if (!selectable && onRowClick && rowData) {
                onRowClick(rowData);
            }
        }
    }

    getRowById(id) {
        for (const [, page] of this.cache) {
            const row = page.rows?.find(r => String(r[this.config.rowIdKey]) === String(id));
            if (row) return row;
        }
        return null;
    }

    /**
     * Get all rows currently in the cache.
     * Useful for bulk operations when in 'all' selection mode.
     * @returns {Array} Array of all cached row objects
     */
    getAllCachedRows() {
        const rows = [];
        for (const [, page] of this.cache) {
            if (page.rows) {
                rows.push(...page.rows);
            }
        }
        return rows;
    }

    // =========================================================================
    // Sorting
    // =========================================================================

    toggleSort(column) {
        if (this.sortColumn === column) {
            // Cycle: asc -> desc -> null
            if (this.sortDirection === 'asc') {
                this.sortDirection = 'desc';
            } else if (this.sortDirection === 'desc') {
                this.sortColumn = null;
                this.sortDirection = null;
            }
        } else {
            this.sortColumn = column;
            this.sortDirection = 'asc';
        }
        
        this.updateSortIndicators();
        this.refresh();
    }

    updateSortIndicators() {
        // Remove all active states
        this.elements.headerTable.querySelectorAll('.sort-btn').forEach(btn => {
            btn.classList.remove('sort-asc', 'sort-desc');
        });
        
        // Set active state
        if (this.sortColumn && this.sortDirection) {
            const btn = this.elements.headerTable.querySelector(`.sort-btn[data-column="${this.sortColumn}"]`);
            if (btn) {
                btn.classList.add(`sort-${this.sortDirection}`);
            }
        }
    }

    // =========================================================================
    // Filtering
    // =========================================================================

    /**
     * Get column definition by key
     * @param {string} key - Column key
     * @returns {Object|undefined}
     */
    getColumnDef(key) {
        return this.config.columns.find(c => c.key === key);
    }

    async showFilterDropdown(column, anchorElement) {
        // Each open attempt gets a monotonically increasing token. If a newer
        // open supersedes this one (rapid clicks, async fetch completes late)
        // the stale path bails out before creating any DOM.
        const token = ++this._filterOpenToken;

        // Close any existing dropdown first (sync, instant)
        this.closeFilterDropdown();

        const colDef = this.getColumnDef(column);

        // Date range filter — sync, no fetch needed
        if (colDef && colDef.filterType === 'dateRange') {
            if (token !== this._filterOpenToken) return;
            this.showDateRangeFilterDropdown(column, anchorElement, token);
            return;
        }

        // Text filter — sync, no fetch needed
        if (colDef && colDef.filterType === 'text') {
            if (token !== this._filterOpenToken) return;
            this.showTextFilterDropdown(column, anchorElement, colDef.filterPlaceholder, token);
            return;
        }

        // Static options — seed the cache once so the distinct-values render
        // path below picks them up without any network fetch.
        if (colDef && colDef.filterOptions) {
            if (!this.distinctValues[column]) {
                this.distinctValues[column] = {
                    values: colDef.filterOptions,
                    filterSignature: '__static__'
                };
            }
        }

        // Distinct-values filter — may require a network fetch
        if (!this.isDistinctCacheValid(column)) {
            // Abort any previous in-flight distinct fetch (different column or stale)
            if (this._distinctFetchController) {
                this._distinctFetchController.abort();
            }
            this._distinctFetchController = new AbortController();

            // Show loading state on the button so the user knows it's working
            anchorElement.classList.add('filter-btn-loading');
            anchorElement.disabled = true;
            try {
                await this.fetchDistinctValues(column, this._distinctFetchController.signal);
            } catch (e) {
                if (e.name === 'AbortError') return; // Superseded — another open is in progress
                // Network or parse error: continue with empty values list
            } finally {
                anchorElement.classList.remove('filter-btn-loading');
                anchorElement.disabled = false;
                this._distinctFetchController = null;
            }
        }

        // Bail out if a newer open overtook us while we were fetching
        if (token !== this._filterOpenToken) return;

        const cached = this.distinctValues[column];
        const values = (cached && cached.values) ? cached.values : [];
        const selectedValues = this.columnFilters[column] || new Set();
        const valuesArray = [...values];

        // Create dropdown
        const dropdown = document.createElement('div');
        dropdown.className = 'lazy-table-filter-dropdown';
        dropdown.innerHTML = `
            <div class="filter-dropdown-search">
                <input type="text" class="filter-search-input" placeholder="${this.config.i18n.search}">
            </div>
            <div class="filter-dropdown-options">
                ${valuesArray.map((val, idx) => `
                    <label class="filter-option">
                        <input type="checkbox" data-index="${idx}" ${selectedValues.has(val) ? 'checked' : ''}>
                        <span>${this.escapeHtml(val)}</span>
                    </label>
                `).join('')}
            </div>
            <div class="filter-dropdown-actions">
                <button type="button" class="filter-clear-btn">${this.config.i18n.clear}</button>
                <button type="button" class="filter-apply-btn">${this.config.i18n.apply}</button>
            </div>
        `;

        // Position dropdown
        const rect = anchorElement.getBoundingClientRect();
        dropdown.style.position = 'fixed';
        dropdown.style.top = `${rect.bottom + 4}px`;
        dropdown.style.left = `${rect.left}px`;

        document.body.appendChild(dropdown);
        this.activeFilterDropdown = { element: dropdown, column };

        // Search: debounced so rapid keystrokes don't thrash the DOM
        const searchInput = dropdown.querySelector('.filter-search-input');
        let _searchTimer;
        searchInput.addEventListener('input', (e) => {
            clearTimeout(_searchTimer);
            _searchTimer = setTimeout(() => {
                const query = e.target.value.toLowerCase();
                dropdown.querySelectorAll('.filter-option').forEach(opt => {
                    opt.style.display = opt.textContent.toLowerCase().includes(query) ? '' : 'none';
                });
            }, 150);
        });

        dropdown.querySelector('.filter-clear-btn').addEventListener('click', () => {
            this.applyFilter(column, new Set());
            this.closeFilterDropdown();
        });

        dropdown.querySelector('.filter-apply-btn').addEventListener('click', () => {
            const selected = new Set();
            dropdown.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
                const idx = parseInt(cb.dataset.index, 10);
                if (!isNaN(idx) && valuesArray[idx] !== undefined) {
                    selected.add(valuesArray[idx]);
                }
            });
            this.applyFilter(column, selected);
            this.closeFilterDropdown();
        });

        // Outside-click: use rAF instead of setTimeout so the registration is
        // deferred past the current event cycle without creating a race window.
        // Guard with both activeFilterDropdown and token so stale rAF callbacks
        // from cancelled opens never attach a listener.
        requestAnimationFrame(() => {
            if (token !== this._filterOpenToken) return;
            if (!this.activeFilterDropdown || this.activeFilterDropdown.element !== dropdown) return;
            document.addEventListener('click', this.handleOutsideClick = (e) => {
                if (!dropdown.contains(e.target) && !anchorElement.contains(e.target)) {
                    this.closeFilterDropdown();
                }
            });
        });

        searchInput.focus();
    }

    closeFilterDropdown() {
        // Abort any in-flight distinct-values fetch so it doesn't paint a
        // stale dropdown after the user has already moved on
        if (this._distinctFetchController) {
            this._distinctFetchController.abort();
            this._distinctFetchController = null;
        }
        if (this.activeFilterDropdown) {
            this.activeFilterDropdown.element.remove();
            this.activeFilterDropdown = null;
        }
        if (this.handleOutsideClick) {
            document.removeEventListener('click', this.handleOutsideClick);
            this.handleOutsideClick = null;
        }
    }

    /**
     * Show a text-input filter dropdown for pattern-based filtering.
     * Supports wildcards: * matches any characters.
     * @param {string} column - Column key
     * @param {HTMLElement} anchorElement - Button to anchor dropdown to
     * @param {string} [placeholder] - Placeholder text for input
     */
    showTextFilterDropdown(column, anchorElement, placeholder, token) {
        // Get current filter value (stored as Set with single value for text filters)
        const currentFilter = this.columnFilters[column];
        const currentValue = currentFilter && currentFilter.size > 0 ? Array.from(currentFilter)[0] : '';
        
        // Create dropdown
        const dropdown = document.createElement('div');
        dropdown.className = 'lazy-table-filter-dropdown lazy-table-filter-text';
        dropdown.innerHTML = `
            <div class="filter-text-input-wrapper">
                <input type="text" class="filter-text-input" 
                       placeholder="${placeholder || 'Filter...'}" 
                       value="${currentValue}">
                <span class="filter-text-hint">Use * as wildcard</span>
            </div>
            <div class="filter-dropdown-actions">
                <button type="button" class="filter-clear-btn">${this.config.i18n.clear}</button>
                <button type="button" class="filter-apply-btn">${this.config.i18n.apply}</button>
            </div>
        `;
        
        // Position dropdown
        const rect = anchorElement.getBoundingClientRect();
        dropdown.style.position = 'fixed';
        dropdown.style.top = `${rect.bottom + 4}px`;
        dropdown.style.left = `${rect.left}px`;
        
        document.body.appendChild(dropdown);
        this.activeFilterDropdown = { element: dropdown, column };
        
        const textInput = dropdown.querySelector('.filter-text-input');
        
        // Clear button - clears this column's filter
        dropdown.querySelector('.filter-clear-btn').addEventListener('click', () => {
            this.applyFilter(column, new Set());
            this.closeFilterDropdown();
        });
        
        // Apply button
        dropdown.querySelector('.filter-apply-btn').addEventListener('click', () => {
            const value = textInput.value.trim();
            if (value) {
                // Store as Set with single value for consistency with checkbox filters
                this.applyFilter(column, new Set([value]));
            } else {
                this.applyFilter(column, new Set());
            }
            this.closeFilterDropdown();
        });
        
        // Apply on Enter key
        textInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                dropdown.querySelector('.filter-apply-btn').click();
            } else if (e.key === 'Escape') {
                this.closeFilterDropdown();
            }
        });
        
        // Outside-click: rAF + token guard (same pattern as showFilterDropdown)
        requestAnimationFrame(() => {
            if (token !== undefined && token !== this._filterOpenToken) return;
            if (!this.activeFilterDropdown || this.activeFilterDropdown.element !== dropdown) return;
            document.addEventListener('click', this.handleOutsideClick = (e) => {
                if (!dropdown.contains(e.target) && !anchorElement.contains(e.target)) {
                    this.closeFilterDropdown();
                }
            });
        });

        textInput.focus();
        textInput.select();
    }

    /**
     * Show a date range filter dropdown for filtering by date period.
     * Uses native HTML date inputs with From/To fields.
     * Stores value as "fromISO,toISO" in filterSet for API transmission.
     * @param {string} column - Column key
     * @param {HTMLElement} anchorElement - Button to anchor dropdown to
     */
    showDateRangeFilterDropdown(column, anchorElement, token) {
        // Get current filter value (stored as Set with single "from,to" value)
        const currentFilter = this.columnFilters[column];
        let fromValue = '', toValue = '';
        
        if (currentFilter && currentFilter.size > 0) {
            const stored = Array.from(currentFilter)[0];
            const parts = stored.split(',');
            // Convert ISO datetime back to YYYY-MM-DD for date input
            if (parts[0]) {
                try {
                    fromValue = parts[0].split('T')[0];
                } catch (e) { /* ignore */ }
            }
            if (parts[1]) {
                try {
                    toValue = parts[1].split('T')[0];
                } catch (e) { /* ignore */ }
            }
        }
        
        // Create dropdown
        const dropdown = document.createElement('div');
        dropdown.className = 'lazy-table-filter-dropdown lazy-table-filter-daterange';
        dropdown.innerHTML = `
            <div class="filter-daterange-wrapper">
                <div class="filter-daterange-row">
                    <label>From:</label>
                    <input type="date" class="filter-date-input filter-date-from" value="${fromValue}">
                </div>
                <div class="filter-daterange-row">
                    <label>To:</label>
                    <input type="date" class="filter-date-input filter-date-to" value="${toValue}">
                </div>
            </div>
            <div class="filter-dropdown-actions">
                <button type="button" class="filter-clear-btn">${this.config.i18n.clear}</button>
                <button type="button" class="filter-apply-btn">${this.config.i18n.apply}</button>
            </div>
        `;
        
        // Position dropdown
        const rect = anchorElement.getBoundingClientRect();
        dropdown.style.position = 'fixed';
        dropdown.style.top = `${rect.bottom + 4}px`;
        dropdown.style.left = `${rect.left}px`;
        
        document.body.appendChild(dropdown);
        this.activeFilterDropdown = { element: dropdown, column };
        
        const fromInput = dropdown.querySelector('.filter-date-from');
        const toInput = dropdown.querySelector('.filter-date-to');
        
        // Helper: convert YYYY-MM-DD to ISO datetime in local timezone
        const toISODateTime = (dateStr, isEndOfDay) => {
            if (!dateStr) return '';
            // Create date in local timezone
            const time = isEndOfDay ? 'T23:59:59' : 'T00:00:00';
            const localDate = new Date(dateStr + time);
            return localDate.toISOString();
        };
        
        // Clear button - clears this column's filter
        dropdown.querySelector('.filter-clear-btn').addEventListener('click', () => {
            this.applyFilter(column, new Set());
            this.closeFilterDropdown();
        });
        
        // Apply button
        dropdown.querySelector('.filter-apply-btn').addEventListener('click', () => {
            const fromDate = fromInput.value;
            const toDate = toInput.value;
            
            if (fromDate || toDate) {
                // Store as "fromISO,toISO" - empty string if not set
                const fromISO = toISODateTime(fromDate, false);
                const toISO = toISODateTime(toDate, true);
                this.applyFilter(column, new Set([`${fromISO},${toISO}`]));
            } else {
                this.applyFilter(column, new Set());
            }
            this.closeFilterDropdown();
        });
        
        // Apply on Enter key in either input
        [fromInput, toInput].forEach(input => {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    dropdown.querySelector('.filter-apply-btn').click();
                } else if (e.key === 'Escape') {
                    this.closeFilterDropdown();
                }
            });
        });
        
        // Outside-click: rAF + token guard (same pattern as showFilterDropdown)
        requestAnimationFrame(() => {
            if (token !== undefined && token !== this._filterOpenToken) return;
            if (!this.activeFilterDropdown || this.activeFilterDropdown.element !== dropdown) return;
            document.addEventListener('click', this.handleOutsideClick = (e) => {
                if (!dropdown.contains(e.target) && !anchorElement.contains(e.target)) {
                    this.closeFilterDropdown();
                }
            });
        });

        fromInput.focus();
    }

    async fetchDistinctValues(column, signal = null) {
        try {
            // Build URL for distinct values endpoint
            // If fetchUrl has query params, append /distinct before them
            // e.g., /api/jobs/paginated?view=active -> /api/jobs/paginated/distinct?view=active&column=...
            const baseUrl = new URL(this.config.fetchUrl, window.location.origin);
            const distinctUrl = new URL(baseUrl.pathname + '/distinct', window.location.origin);
            distinctUrl.search = baseUrl.search;
            distinctUrl.searchParams.set('column', column);
            
            // CASCADING FILTER LOGIC:
            // - If column is NOT in filterOrder yet: apply ALL active filters (show narrowed options)
            // - If column IS in filterOrder: only apply filters from columns BEFORE it
            // This enables hierarchical filtering where:
            //   1. Unfiltered columns show options narrowed by all active filters
            //   2. Already-filtered columns show options narrowed only by prior filters
            const columnIdx = this.filterOrder.indexOf(column);
            const isColumnInOrder = columnIdx !== -1;
            
            // Determine which filters to apply
            let applicableFilters;
            if (isColumnInOrder) {
                // Column is already in order - only apply filters from columns BEFORE it
                const priorColumns = columnIdx > 0 ? this.filterOrder.slice(0, columnIdx) : [];
                applicableFilters = priorColumns;
            } else {
                // Column not yet filtered - apply ALL active filters to narrow its options
                applicableFilters = this.filterOrder;
            }
            
            Object.entries(this.columnFilters).forEach(([filterColumn, filterValues]) => {
                // Include filters from applicable columns
                if (applicableFilters.includes(filterColumn) && filterValues && filterValues.size > 0) {
                    // Send ALL filter values (comma-separated) for proper multi-value filtering
                    const valueStr = Array.from(filterValues).join(',');
                    distinctUrl.searchParams.set(`filter_${filterColumn}`, valueStr);
                }
            });
            
            // Send filter order so backend knows the cascade sequence
            if (this.filterOrder.length > 0) {
                distinctUrl.searchParams.set('filter_order', this.filterOrder.join(','));
            }
            
            const response = await fetch(distinctUrl.toString(), signal ? { signal } : undefined);
            if (response.ok) {
                const data = await response.json();
                // Cache with filter signature based on ORDER-AWARE prior filters
                const filterSig = this.getCascadingFilterSignature(column);
                this.distinctValues[column] = {
                    values: Array.isArray(data) ? data : (data.values || []),
                    filterSignature: filterSig
                };
            }
        } catch (error) {
            if (error.name === 'AbortError') throw error;  // Let caller handle cancellation
            console.error('LazyTable: error fetching distinct values', error);
            this.distinctValues[column] = { values: [], filterSignature: '' };
        }
    }
    
    /**
     * Preload distinct values for all filterable columns that need server data.
     * Fires once at init via a single batch request so the first filter dropdown
     * open is instant.  Non-fatal — on failure, dropdowns fall back to on-demand fetch.
     */
    async _preloadDistinctValues() {
        // Collect columns that need server distinct values:
        //   - filterable but NOT text/dateRange (those are sync UI, no fetch)
        //   - NOT filterOptions (static enum, no fetch needed)
        //   - must have a key (skip action/virtual columns)
        const cols = this.config.columns
            .filter(c => c.filterable && c.key && !c.filterType && !c.filterOptions)
            .map(c => c.key);

        if (cols.length === 0) return;

        try {
            const baseUrl = new URL(this.config.fetchUrl, window.location.origin);
            const batchUrl = new URL(baseUrl.pathname + '/distinct', window.location.origin);
            batchUrl.search = baseUrl.search;
            batchUrl.searchParams.set('columns', cols.join(','));

            const response = await fetch(batchUrl.toString());
            if (!response.ok) return;

            const data = await response.json();
            if (!data || typeof data !== 'object' || Array.isArray(data)) return;

            // At init time there are no active filters, so the valid sig is 'order:'
            const initSig = this.getCascadingFilterSignature(cols[0]);
            Object.entries(data).forEach(([col, values]) => {
                if (Array.isArray(values) && !this.distinctValues[col]) {
                    this.distinctValues[col] = { values, filterSignature: initSig };
                }
            });
        } catch (e) {
            // Non-fatal — filter dropdowns will fetch on demand as before
            console.debug('LazyTable: distinct preload failed', e);
        }
    }

    /**
     * Generate a signature of filters that apply to a column.
     * Used for cascading cache invalidation - cache is valid only if applicable filters unchanged.
     * @param {string} column - Column to generate signature for
     * @returns {string}
     */
    getCascadingFilterSignature(column) {
        const parts = [];
        const columnIdx = this.filterOrder.indexOf(column);
        const isColumnInOrder = columnIdx !== -1;
        
        // Match the logic in fetchDistinctValues
        let applicableFilters;
        if (isColumnInOrder) {
            applicableFilters = columnIdx > 0 ? this.filterOrder.slice(0, columnIdx) : [];
        } else {
            // Column not in order - all active filters apply
            applicableFilters = this.filterOrder;
        }
        
        applicableFilters.forEach(col => {
            const vals = this.columnFilters[col];
            if (vals && vals.size > 0) {
                parts.push(`${col}:${Array.from(vals).sort().join(',')}`);
            }
        });
        // Include the filter order itself in the signature
        parts.push(`order:${this.filterOrder.join(',')}`);
        return parts.join('|');
    }
    
    /**
     * Generate a signature of current filters excluding a specific column.
     * Used to detect when cached distinct values are stale.
     * @param {string} excludeColumn - Column to exclude from signature
     * @returns {string}
     */
    getFilterSignature(excludeColumn) {
        const parts = [];
        Object.entries(this.columnFilters)
            .filter(([col]) => col !== excludeColumn)
            .sort(([a], [b]) => a.localeCompare(b))
            .forEach(([col, vals]) => {
                if (vals && vals.size > 0) {
                    parts.push(`${col}:${Array.from(vals).sort().join(',')}`);
                }
            });
        return parts.join('|');
    }
    
    /**
     * Check if cached distinct values are still valid for current cascading filter state.
     * @param {string} column - Column to check
     * @returns {boolean}
     */
    isDistinctCacheValid(column) {
        const cached = this.distinctValues[column];
        if (!cached || !cached.values) return false;
        if (cached.filterSignature === '__static__') return true;  // Static enum — never stale
        return cached.filterSignature === this.getCascadingFilterSignature(column);
    }

    applyFilter(column, values) {
        if (values.size === 0) {
            delete this.columnFilters[column];
            // Remove from filter order
            this.filterOrder = this.filterOrder.filter(c => c !== column);
        } else {
            this.columnFilters[column] = values;
            // Add to filter order if not already present
            if (!this.filterOrder.includes(column)) {
                this.filterOrder.push(column);
            }
        }
        
        // Invalidate distinct values cache for columns AFTER this one in order
        this.invalidateCascadingCaches(column);
        
        // Reset scroll position when filter changes
        this.scrollTop = 0;
        this.elements.bodyContainer.scrollTop = 0;
        
        this.updateFilterIndicators();
        this.renderFilterChips();
        this.refresh();
    }

    /**
     * Clear all column filters and refresh the table.
     * Resets scroll position, filter order, and updates all filter indicators.
     */
    clearAllFilters() {
        this.columnFilters = {};
        this.filterOrder = [];  // Reset filter selection order
        
        // Reset scroll position
        this.scrollTop = 0;
        this.elements.bodyContainer.scrollTop = 0;
        
        // Clear distinct values cache so filters re-fetch on next open
        this.distinctValues = {};
        
        this.updateFilterIndicators();
        this.renderFilterChips();
        this.refresh();
    }

    /**
     * Invalidate distinct values cache for columns affected by a filter change.
     * Clears caches for: columns AFTER the changed one in order, and unfiltered columns.
     * @param {string} changedColumn - The column whose filter just changed
     */
    invalidateCascadingCaches(changedColumn) {
        const idx = this.filterOrder.indexOf(changedColumn);
        
        // Clear caches for columns AFTER this one in the order
        if (idx !== -1) {
            for (let i = idx + 1; i < this.filterOrder.length; i++) {
                delete this.distinctValues[this.filterOrder[i]];
            }
        }
        
        // Also clear caches for columns NOT in filterOrder (they depend on all filters)
        Object.keys(this.distinctValues).forEach(col => {
            if (!this.filterOrder.includes(col)) {
                delete this.distinctValues[col];
            }
        });
    }

    updateFilterIndicators() {
        this.elements.headerTable.querySelectorAll('.filter-btn').forEach(btn => {
            const column = btn.dataset.column;
            const filterSet = this.columnFilters[column];
            // Must use !! to coerce to boolean - classList.toggle treats undefined as "toggle mode"
            const hasFilter = !!(filterSet && filterSet.size > 0);
            btn.classList.toggle('filter-active', hasFilter);
        });
        
        // Show/hide footer Clear Filters button based on active filters
        const hasAnyFilter = Object.keys(this.columnFilters).length > 0;
        const clearFiltersBtn = this.elements.footerContent?.querySelector('.footer-clear-filters-btn');
        if (clearFiltersBtn) {
            clearFiltersBtn.classList.toggle('hidden', !hasAnyFilter);
        }
    }

    /**
     * Render filter chips showing active filters in selection order.
     * Each chip displays: order number, column label, value count.
     * Clicking a chip opens its filter dropdown; × removes the filter.
     */
    renderFilterChips() {
        const container = this.elements.filterChipsContainer;
        if (!container) return;
        
        // Hide if no filters active
        if (this.filterOrder.length === 0) {
            container.classList.add('hidden');
            container.innerHTML = '';
            return;
        }
        
        container.classList.remove('hidden');
        
        // Build chip HTML for each filter in selection order
        const chipsHtml = this.filterOrder.map((column, index) => {
            const filterSet = this.columnFilters[column];
            if (!filterSet || filterSet.size === 0) return '';
            
            // Get column label from config
            const colDef = this.getColumnDef(column);
            const label = colDef ? (colDef.label || column) : column;
            const count = filterSet.size;
            const orderNum = index + 1;
            
            // Format values preview (show first 2, then +N more)
            const valuesArr = Array.from(filterSet);
            let valuesPreview;
            if (valuesArr.length <= 2) {
                valuesPreview = valuesArr.map(v => this.escapeHtml(v)).join(', ');
            } else {
                valuesPreview = `${this.escapeHtml(valuesArr[0])}, ${this.escapeHtml(valuesArr[1])} +${valuesArr.length - 2}`;
            }
            
            return `
                <div class="filter-chip" data-column="${column}" title="${label}: ${valuesArr.map(v => this.escapeHtml(v)).join(', ')}">
                    <span class="filter-chip-number">${orderNum}</span>
                    <span class="filter-chip-label">${this.escapeHtml(label)}</span>
                    <span class="filter-chip-values">${valuesPreview}</span>
                    <button type="button" class="filter-chip-remove" data-column="${column}" title="Remove filter">
                        <svg viewBox="0 0 24 24" width="14" height="14">
                            <path fill="currentColor" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                        </svg>
                    </button>
                </div>
            `;
        }).filter(Boolean).join('');
        
        // Add "Clear All" button at the end
        container.innerHTML = chipsHtml + `
            <button type="button" class="filter-chips-clear-all" title="Clear all filters">
                Clear All
            </button>
        `;
        
        // Bind chip click events
        container.querySelectorAll('.filter-chip').forEach(chip => {
            // Click on chip (not the remove button) opens filter dropdown
            chip.addEventListener('click', (e) => {
                if (e.target.closest('.filter-chip-remove')) return;
                const column = chip.dataset.column;
                const filterBtn = this.elements.headerTable.querySelector(`.filter-btn[data-column="${column}"]`);
                if (filterBtn) {
                    this.showFilterDropdown(column, filterBtn).catch(err => {
                        console.error('LazyTable: error showing filter dropdown from chip', err);
                    });
                }
            });
        });
        
        // Bind remove button events
        container.querySelectorAll('.filter-chip-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const column = btn.dataset.column;
                this.applyFilter(column, new Set());  // Clear this filter
            });
        });
        
        // Bind clear all button
        const clearAllBtn = container.querySelector('.filter-chips-clear-all');
        if (clearAllBtn) {
            clearAllBtn.addEventListener('click', () => this.clearAllFilters());
        }
    }

    // =========================================================================
    // Selection
    // =========================================================================

    isRowSelected(rowId) {
        const id = String(rowId);
        if (this.selection.mode === 'all') {
            return !this.selection.excludeIds.has(id);
        } else {
            return this.selection.includeIds.has(id);
        }
    }

    toggleRowSelection(rowId, isSelected) {
        const id = String(rowId);
        
        if (this.selection.mode === 'all') {
            if (isSelected) {
                this.selection.excludeIds.delete(id);
            } else {
                this.selection.excludeIds.add(id);
            }
        } else {
            if (isSelected) {
                this.selection.includeIds.add(id);
            } else {
                this.selection.includeIds.delete(id);
            }
        }
        
        this.onSelectionChange();
        this.updateSelectionBar();
    }

    selectSingle(rowId) {
        const id = String(rowId);
        this.selection = {
            mode: 'partial',
            includeIds: new Set([id]),
            excludeIds: new Set()
        };
        this.onSelectionChange();
        this.render();
    }

    updateVisibleCheckboxes() {
        // Update checkbox states for all currently visible rows
        const rows = this.elements.tbody.querySelectorAll('.lazy-table-row');
        rows.forEach(row => {
            const rowId = row.dataset.rowId;
            if (rowId) {
                const checkbox = row.querySelector('.row-checkbox');
                if (checkbox) {
                    const isSelected = this.isRowSelected(rowId);
                    checkbox.checked = isSelected;
                    if (isSelected) {
                        row.classList.add('selected');
                    } else {
                        row.classList.remove('selected');
                    }
                }
            }
        });
    }

    selectAllFiltered() {
        this.selection = {
            mode: 'all',
            includeIds: new Set(),
            excludeIds: new Set()
        };
        this.onSelectionChange();
        // Force full re-render by resetting render cache and force flag
        this._lastRenderStart = -1;
        this._lastRenderEnd = -1;
        this._forceRender = true;
        this.render();
    }

    clearSelection() {
        this.selection = {
            mode: 'partial',
            includeIds: new Set(),
            excludeIds: new Set()
        };
        this.onSelectionChange();
        // Force full re-render by resetting render cache and force flag
        this._lastRenderStart = -1;
        this._lastRenderEnd = -1;
        this._forceRender = true;
        this.render();
    }

    getSelectedCount() {
        if (this.selection.mode === 'all') {
            return this.filteredCount - this.selection.excludeIds.size;
        } else {
            return this.selection.includeIds.size;
        }
    }

    /**
     * Get selection state for server-side bulk operations.
     * Returns an object that can be sent to the server to identify selected items.
     * @returns {{ mode: 'all' | 'partial', count: number, includeIds?: string[], excludeIds?: string[], filters: Object }}
     */
    getSelectionState() {
        const state = {
            mode: this.selection.mode,
            count: this.getSelectedCount(),
            filters: { ...this.columnFilters }
        };
        
        if (this.selection.mode === 'all') {
            state.excludeIds = Array.from(this.selection.excludeIds);
        } else {
            state.includeIds = Array.from(this.selection.includeIds);
        }
        
        if (this.sortColumn) {
            state.sort = { column: this.sortColumn, direction: this.sortDirection };
        }
        
        return state;
    }

    /**
     * Get array of selected row IDs (only works reliably for partial selection mode)
     * For 'all' mode, returns excludeIds and caller must interpret accordingly.
     * @returns {string[]}
     */
    getSelectedIds() {
        if (this.selection.mode === 'partial') {
            return Array.from(this.selection.includeIds);
        } else {
            // In 'all' mode, we can't return all IDs without fetching all data
            // Return excludeIds for the caller to interpret
            console.warn('LazyTable: getSelectedIds() in "all" mode returns excludeIds. Use getSelectionState() for bulk operations.');
            return Array.from(this.selection.excludeIds);
        }
    }

    onSelectionChange() {
        if (this.config.onSelectionChange) {
            this.config.onSelectionChange(this.getSelectionState());
        }
    }

    // =========================================================================
    // Public API
    // =========================================================================

    /**
     * Set new data fetch URL
     * @param {string} url 
     */
    setFetchUrl(url) {
        this.config.fetchUrl = url;
        this.refresh();
    }

    /**
     * Get current table state for persistence (sort, filters, filter order).
     * Selection and distinctValues are NOT included - they are cleared on state restore.
     * @returns {{ sortColumn: string|null, sortDirection: string|null, columnFilters: Object, filterOrder: string[] }}
     */
    getState() {
        const filters = {};
        Object.entries(this.columnFilters).forEach(([key, values]) => {
            filters[key] = Array.from(values);
        });
        return {
            sortColumn: this.sortColumn,
            sortDirection: this.sortDirection,
            columnFilters: filters,
            filterOrder: [...this.filterOrder]
        };
    }

    /**
     * Restore table state from a saved state object.
     * Clears selection and distinctValues cache. Does NOT trigger refresh.
     * @param {Object|null} state - State object from getState(), or null to reset
     */
    setState(state) {
        if (state) {
            this.sortColumn = state.sortColumn || null;
            this.sortDirection = state.sortDirection || null;
            this.columnFilters = {};
            this.filterOrder = state.filterOrder ? [...state.filterOrder] : [];
            if (state.columnFilters) {
                Object.entries(state.columnFilters).forEach(([key, values]) => {
                    this.columnFilters[key] = new Set(values);
                });
            }
        } else {
            this.sortColumn = null;
            this.sortDirection = null;
            this.columnFilters = {};
            this.filterOrder = [];
        }
        
        // Clear selection and distinct values cache on state change
        this.selection = {
            mode: 'partial',
            includeIds: new Set(),
            excludeIds: new Set()
        };
        this.distinctValues = {};
        
        // Update visual indicators
        this.updateSortIndicators();
        this.updateFilterIndicators();
        this.renderFilterChips();
    }

    /**
     * Reset all table state (sort, filters, selection, distinctValues cache).
     * Does NOT trigger refresh - caller should call refresh() or setFetchUrl() after.
     */
    resetState() {
        this.setState(null);
    }

    /**
     * Get current sort state
     * @returns {{ column: string|null, direction: string|null }}
     */
    getSortState() {
        return { column: this.sortColumn, direction: this.sortDirection };
    }

    /**
     * Get current filter state
     * @returns {Object}
     */
    getFilterState() {
        const filters = {};
        Object.entries(this.columnFilters).forEach(([key, values]) => {
            filters[key] = Array.from(values);
        });
        return filters;
    }

    /**
     * Programmatically set filters
     * @param {Object} filters - { columnKey: [values] }
     */
    setFilters(filters) {
        this.columnFilters = {};
        Object.entries(filters).forEach(([key, values]) => {
            this.columnFilters[key] = new Set(values);
        });
        this.updateFilterIndicators();
        this.refresh();
    }

    /**
     * Programmatically set sort
     * @param {string} column 
     * @param {string} direction - 'asc' | 'desc'
     */
    setSort(column, direction) {
        this.sortColumn = column;
        this.sortDirection = direction;
        this.updateSortIndicators();
        this.refresh();
    }

    /**
     * Destroy the table and clean up
     */
    destroy() {
        window.removeEventListener('resize', this._resizeHandler);
        this.closeFilterDropdown();
        this.config.container.innerHTML = '';
    }

    // =========================================================================
    // Utilities
    // =========================================================================

    debounce(fn, delay) {
        let timeoutId;
        return (...args) => {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => fn.apply(this, args), delay);
        };
    }

    /**
     * Escape HTML special characters to prevent XSS and attribute breakage.
     * @param {string} str - String to escape
     * @returns {string} - Escaped string safe for HTML insertion
     */
    escapeHtml(str) {
        if (str == null) return '';
        const text = String(str);
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = LazyTable;
}
