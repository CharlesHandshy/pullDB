/**
 * LazyTable - Server-Side Lazy Loading Table Widget
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
     * @param {Function} [config.onSelectionChange] - Callback when selection changes
     * @param {Function} [config.onRowClick] - Callback when row is clicked (if not selectable)
     * @param {string} [config.emptyMessage='No data available'] - Message when no data
     * @param {string} [config.tableId] - ID for the table (auto-generated if not provided)
     * @param {Object} [config.i18n] - Internationalization strings
     */
    constructor(config) {
        this.config = {
            rowHeight: 48,
            rowIdKey: 'id',
            selectable: false,
            selectionMode: 'multiple',
            emptyMessage: 'No data available',
            tableId: `lazy-table-${Date.now()}`,
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
        
        // Column filter distinct values cache
        this.distinctValues = {};  // { columnKey: [] }

        // Build and initialize
        this.buildDOM();
        this.bindEvents();
        this.calculateViewport();
        
        // Update filter indicators for initial filters (after DOM is built)
        if (this.config.initialFilters) {
            this.updateFilterIndicators();
        }
        
        this.fetchInitialData();
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

        // Selection bar (shown when items selected)
        if (selectable) {
            this.elements.selectionBar = this.createSelectionBar();
            this.elements.wrapper.appendChild(this.elements.selectionBar);
        }

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
        
        // Selection checkbox column
        if (selectable && selectionMode === 'multiple') {
            const th = document.createElement('th');
            th.className = 'lazy-table-th lazy-table-th-select';
            th.innerHTML = `
                <label class="lazy-table-checkbox">
                    <input type="checkbox" class="select-all-checkbox">
                    <span class="checkmark"></span>
                </label>
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
                th.innerHTML = `<span class="th-label">${col.label != null ? col.label : ''}</span>`;
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
        
        // Data columns
        columns.forEach(colDef => {
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
        
        // Order: filter icon, label, sort icons - no gaps
        return `
            <div class="th-content">
                ${filterIcon}<span class="th-label">${col.label != null ? col.label : col.key}</span>${sortIcon}
            </div>
        `;
    }

    createFooter() {
        const footer = document.createElement('div');
        footer.className = 'lazy-table-footer';
        footer.innerHTML = `
            <div class="footer-info">
                <span class="footer-showing"></span>
            </div>
            <div class="footer-spacer"></div>
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
        
        // Selection bar events
        if (this.config.selectable) {
            const selectAllBtn = this.elements.selectionBar.querySelector('.selection-select-all');
            const clearBtn = this.elements.selectionBar.querySelector('.selection-clear');
            
            selectAllBtn?.addEventListener('click', () => this.selectAllFiltered());
            clearBtn?.addEventListener('click', () => this.clearSelection());
            
            // Select all checkbox
            const selectAllCheckbox = this.elements.headerTable.querySelector('.select-all-checkbox');
            selectAllCheckbox?.addEventListener('change', (e) => {
                if (e.target.checked) {
                    this.selectAllFiltered();
                } else {
                    this.clearSelection();
                }
            });
        }
        
        // Error retry button
        const retryBtn = this.elements.errorOverlay.querySelector('.error-retry-btn');
        retryBtn?.addEventListener('click', () => this.refresh());
    }

    // =========================================================================
    // Viewport Management
    // =========================================================================

    calculateViewport() {
        const containerHeight = this.elements.bodyContainer.clientHeight;
        this.visibleRowCount = Math.ceil(containerHeight / this.rowHeight);
        this.pageSize = Math.max(50, this.visibleRowCount * this.bufferMultiplier);
    }

    handleResize() {
        const prevVisibleCount = this.visibleRowCount;
        this.calculateViewport();
        
        if (this.visibleRowCount !== prevVisibleCount) {
            this.render();
        }
    }

    handleScroll() {
        if (this.isLoading) return;
        
        this.scrollTop = this.elements.bodyContainer.scrollTop;
        this.render();
        this.checkFetchNeeded();
    }

    // =========================================================================
    // Data Fetching
    // =========================================================================

    async fetchInitialData() {
        this.showLoading();
        try {
            await this.fetchPage(0);
            this.hideLoading();
            this.render();
        } catch (error) {
            this.hideLoading();
            // Error already shown by fetchPage
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
            const response = await fetch(url.toString());
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            
            const data = await response.json();
            
            this.cache.set(pageIndex, {
                rows: data.rows || data.data || [],
                timestamp: Date.now()
            });
            
            this.totalCount = data.totalCount ?? data.total ?? 0;
            this.filteredCount = data.filteredCount ?? data.totalCount ?? this.totalCount;
            
            // Call onDataLoaded callback if provided
            if (this.config.onDataLoaded) {
                this.config.onDataLoaded({
                    totalCount: this.totalCount,
                    filteredCount: this.filteredCount,
                    pageIndex: pageIndex,
                    rows: data.rows || data.data || []
                });
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
    }

    async refresh() {
        this.clearCache();
        this.hideError();  // Auto-dismiss error on retry
        this.showLoading();
        try {
            await this.fetchPage(0);
            this.hideLoading();
            this.render();
            this.checkFetchNeeded();
        } catch (error) {
            this.hideLoading();
            // Error already shown by fetchPage
        }
    }

    // =========================================================================
    // Rendering
    // =========================================================================

    render() {
        const startRow = Math.floor(this.scrollTop / this.rowHeight);
        const bufferRows = Math.floor(this.visibleRowCount / 2);
        const renderStart = Math.max(0, startRow - bufferRows);
        const renderEnd = Math.min(this.filteredCount, startRow + this.visibleRowCount + bufferRows);
        
        // Update spacer height
        this.elements.spacer.style.height = `${this.filteredCount * this.rowHeight}px`;
        
        // Position content
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
            td.innerHTML = `
                <label class="lazy-table-checkbox">
                    <input type="checkbox" class="row-checkbox" ${isSelected ? 'checked' : ''}>
                    <span class="checkmark"></span>
                </label>
            `;
            tr.appendChild(td);
        }
        
        // Data columns
        columns.forEach((col, colIndex) => {
            const td = document.createElement('td');
            td.className = 'lazy-table-td';
            
            if (col.type === 'actions') {
                td.classList.add('lazy-table-td-actions');
                td.innerHTML = this.renderActions(col.actions, row);
            } else {
                const value = row[col.key];
                if (col.render) {
                    td.innerHTML = col.render(value, row, colIndex);
                } else {
                    td.textContent = value ?? '';
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
        
        // Placeholder cells
        columns.forEach(col => {
            const td = document.createElement('td');
            td.className = 'lazy-table-td';
            td.innerHTML = '<div class="placeholder-shimmer"></div>';
            tr.appendChild(td);
        });
        
        return tr;
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
        const showing = this.elements.footerContent.querySelector('.footer-showing');
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
        const bar = this.elements.selectionBar;
        const countSpan = bar.querySelector('.selection-count');
        
        if (count > 0) {
            bar.classList.remove('hidden');
            countSpan.textContent = `${count} ${this.config.i18n.selected}`;
        } else {
            bar.classList.add('hidden');
        }
        
        // Update header checkbox state
        const selectAllCheckbox = this.elements.headerTable.querySelector('.select-all-checkbox');
        if (selectAllCheckbox) {
            if (this.selection.mode === 'all' && this.selection.excludeIds.size === 0) {
                selectAllCheckbox.checked = true;
                selectAllCheckbox.indeterminate = false;
            } else if (count > 0) {
                selectAllCheckbox.checked = false;
                selectAllCheckbox.indeterminate = true;
            } else {
                selectAllCheckbox.checked = false;
                selectAllCheckbox.indeterminate = false;
            }
        }
    }

    showLoading() {
        this.isLoading = true;
        this.elements.loadingOverlay.classList.add('visible');
    }

    hideLoading() {
        this.isLoading = false;
        this.elements.loadingOverlay.classList.remove('visible');
    }

    showError() {
        this.hasError = true;
        this.hideLoading();
        this.elements.errorOverlay.classList.add('visible');
    }

    hideError() {
        this.hasError = false;
        this.elements.errorOverlay.classList.remove('visible');
    }

    // =========================================================================
    // Event Handlers
    // =========================================================================

    handleHeaderClick(e) {
        const sortBtn = e.target.closest('.sort-btn');
        const filterBtn = e.target.closest('.filter-btn');
        
        if (sortBtn) {
            const column = sortBtn.dataset.column;
            this.toggleSort(column);
        }
        
        if (filterBtn) {
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
                this.toggleRowSelection(rowId, checkbox.checked);
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
        // Remove any existing dropdown
        this.closeFilterDropdown();
        
        // Check column filter type
        const colDef = this.getColumnDef(column);
        
        // Date range filter - From/To date inputs
        if (colDef && colDef.filterType === 'dateRange') {
            this.showDateRangeFilterDropdown(column, anchorElement);
            return;
        }
        
        // Text filter - single input with wildcard support
        if (colDef && colDef.filterType === 'text') {
            this.showTextFilterDropdown(column, anchorElement, colDef.filterPlaceholder);
            return;
        }
        
        // Fetch distinct values if not cached
        if (!this.distinctValues[column]) {
            await this.fetchDistinctValues(column);
        }
        
        const values = this.distinctValues[column] || [];
        const selectedValues = this.columnFilters[column] || new Set();
        
        // Create dropdown
        const dropdown = document.createElement('div');
        dropdown.className = 'lazy-table-filter-dropdown';
        dropdown.innerHTML = `
            <div class="filter-dropdown-search">
                <input type="text" class="filter-search-input" placeholder="${this.config.i18n.search}">
            </div>
            <div class="filter-dropdown-options">
                ${values.map(val => `
                    <label class="filter-option">
                        <input type="checkbox" value="${val}" ${selectedValues.has(val) ? 'checked' : ''}>
                        <span>${val}</span>
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
        
        // Bind dropdown events
        const searchInput = dropdown.querySelector('.filter-search-input');
        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();
            dropdown.querySelectorAll('.filter-option').forEach(opt => {
                const text = opt.textContent.toLowerCase();
                opt.style.display = text.includes(query) ? '' : 'none';
            });
        });
        
        dropdown.querySelector('.filter-clear-btn').addEventListener('click', () => {
            this.applyFilter(column, new Set());
            this.closeFilterDropdown();
        });
        
        dropdown.querySelector('.filter-apply-btn').addEventListener('click', () => {
            const selected = new Set();
            dropdown.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
                selected.add(cb.value);
            });
            this.applyFilter(column, selected);
            this.closeFilterDropdown();
        });
        
        // Close on outside click
        setTimeout(() => {
            document.addEventListener('click', this.handleOutsideClick = (e) => {
                if (!dropdown.contains(e.target) && !anchorElement.contains(e.target)) {
                    this.closeFilterDropdown();
                }
            });
        }, 0);
        
        searchInput.focus();
    }

    closeFilterDropdown() {
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
    showTextFilterDropdown(column, anchorElement, placeholder) {
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
        
        // Clear button - immediately clears and applies
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
        
        // Close on outside click
        setTimeout(() => {
            document.addEventListener('click', this.handleOutsideClick = (e) => {
                if (!dropdown.contains(e.target) && !anchorElement.contains(e.target)) {
                    this.closeFilterDropdown();
                }
            });
        }, 0);
        
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
    showDateRangeFilterDropdown(column, anchorElement) {
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
        
        // Clear button
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
        
        // Close on outside click
        setTimeout(() => {
            document.addEventListener('click', this.handleOutsideClick = (e) => {
                if (!dropdown.contains(e.target) && !anchorElement.contains(e.target)) {
                    this.closeFilterDropdown();
                }
            });
        }, 0);
        
        fromInput.focus();
    }

    async fetchDistinctValues(column) {
        try {
            // Build URL for distinct values endpoint
            // If fetchUrl has query params, append /distinct before them
            // e.g., /api/jobs/paginated?view=active -> /api/jobs/paginated/distinct?view=active&column=...
            const baseUrl = new URL(this.config.fetchUrl, window.location.origin);
            const distinctUrl = new URL(baseUrl.pathname + '/distinct', window.location.origin);
            distinctUrl.search = baseUrl.search;
            distinctUrl.searchParams.set('column', column);
            
            const response = await fetch(distinctUrl.toString());
            if (response.ok) {
                const data = await response.json();
                this.distinctValues[column] = Array.isArray(data) ? data : (data.values || []);
            }
        } catch (error) {
            console.error('LazyTable: error fetching distinct values', error);
            this.distinctValues[column] = [];
        }
    }

    applyFilter(column, values) {
        if (values.size === 0) {
            delete this.columnFilters[column];
        } else {
            this.columnFilters[column] = values;
        }
        
        // Reset scroll position when filter changes
        this.scrollTop = 0;
        this.elements.bodyContainer.scrollTop = 0;
        
        this.updateFilterIndicators();
        this.refresh();
    }

    updateFilterIndicators() {
        this.elements.headerTable.querySelectorAll('.filter-btn').forEach(btn => {
            const column = btn.dataset.column;
            const filterSet = this.columnFilters[column];
            // Must use !! to coerce to boolean - classList.toggle treats undefined as "toggle mode"
            const hasFilter = !!(filterSet && filterSet.size > 0);
            btn.classList.toggle('filter-active', hasFilter);
        });
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
        this.render();
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

    selectAllFiltered() {
        this.selection = {
            mode: 'all',
            includeIds: new Set(),
            excludeIds: new Set()
        };
        this.onSelectionChange();
        this.render();
    }

    clearSelection() {
        this.selection = {
            mode: 'partial',
            includeIds: new Set(),
            excludeIds: new Set()
        };
        this.onSelectionChange();
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
     * Get current table state for persistence (sort, filters).
     * Selection and distinctValues are NOT included - they are cleared on state restore.
     * @returns {{ sortColumn: string|null, sortDirection: string|null, columnFilters: Object }}
     */
    getState() {
        const filters = {};
        Object.entries(this.columnFilters).forEach(([key, values]) => {
            filters[key] = Array.from(values);
        });
        return {
            sortColumn: this.sortColumn,
            sortDirection: this.sortDirection,
            columnFilters: filters
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
            if (state.columnFilters) {
                Object.entries(state.columnFilters).forEach(([key, values]) => {
                    this.columnFilters[key] = new Set(values);
                });
            }
        } else {
            this.sortColumn = null;
            this.sortDirection = null;
            this.columnFilters = {};
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
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = LazyTable;
}
