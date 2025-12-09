/**
 * VirtualTable - Reusable Virtual Scrolling Table Widget
 * =======================================================
 * HCA Layer: widgets (Layer 3)
 * 
 * A high-performance table component with:
 * - Virtual scrolling for large datasets
 * - Multi-column sorting (click to add, shift+click for multi)
 * - Status filtering (quick filter buttons)
 * - Column filtering (dropdown with checkboxes)
 * - Filter chips with removal
 * - Keyboard navigation
 * - Paging controls
 * 
 * Usage:
 *   const table = new VirtualTable({
 *       container: document.getElementById('my-table-container'),
 *       data: myDataArray,
 *       columns: [
 *           { key: 'name', label: 'Name', sortable: true, filterable: true },
 *           { key: 'status', label: 'Status', sortable: true, filterable: true, 
 *             render: (val, row) => `<span class="badge badge-${val}">${val}</span>` },
 *           { key: 'date', label: 'Date', sortable: true, type: 'date' }
 *       ],
 *       rowHeight: 44,
 *       statusFilters: ['queued', 'running', 'complete', 'failed'],
 *       onRowClick: (row, index) => console.log('Clicked:', row),
 *       actions: (row) => `<a href="/view/${row.id}">View</a>`
 *   });
 */

class VirtualTable {
    /**
     * @param {Object} config - Configuration object
     * @param {HTMLElement} config.container - Container element for the table
     * @param {Array} config.data - Array of data objects
     * @param {Array} config.columns - Column definitions
     * @param {number} [config.rowHeight=44] - Height of each row in pixels
     * @param {Array} [config.statusFilters] - Status values for quick filter buttons
     * @param {string} [config.statusField='status'] - Field name for status filtering
     * @param {Function} [config.onRowClick] - Callback when row is clicked
     * @param {Function} [config.actions] - Function returning action buttons HTML
     * @param {Function} [config.rowClass] - Function returning additional row classes
     * @param {string} [config.emptyMessage='No data available'] - Message when no data
     * @param {string} [config.tableId] - ID for the table (auto-generated if not provided)
     * @param {Object} [config.i18n] - Internationalization strings
     */
    constructor(config) {
        this.config = {
            rowHeight: 44,
            statusField: 'status',
            emptyMessage: 'No data available',
            tableId: `virtual-table-${Date.now()}`,
            i18n: {
                showing: 'Showing',
                of: 'of',
                firstPage: 'First page',
                prevPage: 'Previous page',
                nextPage: 'Next page',
                lastPage: 'Last page',
                filter: 'Filter',
                clear: 'Clear',
                apply: 'Apply',
                selectAll: 'Select All',
                search: 'Search...'
            },
            ...config
        };

        // Validate required config
        if (!this.config.container) throw new Error('VirtualTable: container is required');
        if (!this.config.columns) throw new Error('VirtualTable: columns are required');

        // Data management
        this.originalData = [...(this.config.data || [])];
        this.filteredData = [...this.originalData];
        
        // State
        this.currentStatusFilter = '';
        this.columnFilters = {};
        this.sortColumns = [];
        this.viewportStartIndex = 0;
        this.viewportRows = 15;
        this.bufferSize = 15;
        this.isRendering = false;
        this.topIndex = 0;

        // Build and initialize
        this.buildDOM();
        this.bindEvents();
        this.render();
    }

    // =========================================================================
    // DOM Construction
    // =========================================================================

    buildDOM() {
        const { container, tableId, columns, statusFilters } = this.config;
        
        container.innerHTML = '';
        container.classList.add('virtual-table-widget');

        // Create structure
        this.elements = {};
        
        // Active filters container (chips)
        this.elements.activeFilters = this.createActiveFiltersBar();
        container.appendChild(this.elements.activeFilters);

        // Filter bar (if status filters provided)
        if (statusFilters && statusFilters.length > 0) {
            this.elements.filterBar = this.createFilterBar();
            container.appendChild(this.elements.filterBar);
        }

        // Table wrapper
        this.elements.tableWrapper = document.createElement('div');
        this.elements.tableWrapper.className = 'virtual-table-wrapper';
        container.appendChild(this.elements.tableWrapper);

        // Mobile sort bar (shown on small screens)
        this.elements.mobileSortBar = this.createMobileSortBar();
        this.elements.tableWrapper.appendChild(this.elements.mobileSortBar);

        // Fixed header table
        this.elements.headerTable = this.createHeaderTable();
        this.elements.tableWrapper.appendChild(this.elements.headerTable);

        // Scroll body
        this.elements.scrollBody = document.createElement('div');
        this.elements.scrollBody.className = 'virtual-table-scroll-body';
        this.elements.scrollBody.tabIndex = 0;
        this.elements.tableWrapper.appendChild(this.elements.scrollBody);

        // Spacer for virtual scroll height
        this.elements.spacer = document.createElement('div');
        this.elements.spacer.className = 'virtual-table-spacer';
        this.elements.scrollBody.appendChild(this.elements.spacer);

        // Content container (positioned via transform)
        this.elements.content = document.createElement('div');
        this.elements.content.className = 'virtual-table-content';
        this.elements.scrollBody.appendChild(this.elements.content);

        // Body table
        this.elements.bodyTable = document.createElement('table');
        this.elements.bodyTable.className = 'virtual-table-body';
        this.elements.bodyTable.id = `${tableId}-body`;
        this.elements.content.appendChild(this.elements.bodyTable);

        // Tbody
        this.elements.tbody = document.createElement('tbody');
        this.elements.bodyTable.appendChild(this.elements.tbody);

        // Paging controls
        this.elements.paging = this.createPagingControls();
        this.elements.tableWrapper.appendChild(this.elements.paging);

        // Calculate viewport capacity
        this.calculateViewport();
    }

    createFilterBar() {
        const { statusFilters, statusField, i18n } = this.config;
        
        const bar = document.createElement('div');
        bar.className = 'virtual-table-filter-bar';

        // Filter icon
        const icon = document.createElement('span');
        icon.className = 'filter-icon';
        icon.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" width="16" height="16">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 01-.659 1.591l-5.432 5.432a2.25 2.25 0 00-.659 1.591v2.927a2.25 2.25 0 01-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 00-.659-1.591L3.659 7.409A2.25 2.25 0 013 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0112 3z" />
        </svg>`;
        bar.appendChild(icon);

        // Status filter buttons
        const buttonsContainer = document.createElement('div');
        buttonsContainer.className = 'status-filter-buttons';
        
        statusFilters.forEach(status => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = `filter-btn filter-btn-${status}`;
            btn.dataset.status = status;
            btn.innerHTML = `<span class="filter-btn-label">${status}</span><span class="filter-btn-count" data-count="${status}">0</span>`;
            buttonsContainer.appendChild(btn);
        });
        
        bar.appendChild(buttonsContainer);
        return bar;
    }

    createActiveFiltersBar() {
        const { i18n } = this.config;
        
        const bar = document.createElement('div');
        bar.className = 'virtual-table-active-filters';
        
        // Chips container
        const chips = document.createElement('div');
        chips.className = 'filter-chips';
        bar.appendChild(chips);
        
        // Search input
        const searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.className = 'filter-search-input';
        searchInput.placeholder = i18n.search;
        bar.appendChild(searchInput);
        
        // Clear all button (hidden by default)
        const clearBtn = document.createElement('button');
        clearBtn.type = 'button';
        clearBtn.className = 'clear-all-filters hidden';
        clearBtn.textContent = i18n.clear + ' All';
        bar.appendChild(clearBtn);

        this.elements.filterChips = chips;
        this.elements.searchInput = searchInput;
        this.elements.clearAllBtn = clearBtn;

        return bar;
    }

    createMobileSortBar() {
        const { columns } = this.config;
        
        const bar = document.createElement('div');
        bar.className = 'virtual-table-mobile-sort-bar';

        // Sort label
        const label = document.createElement('span');
        label.className = 'mobile-sort-label';
        label.textContent = 'Sort/Filter:';
        bar.appendChild(label);

        // Sort buttons container
        const buttonsContainer = document.createElement('div');
        buttonsContainer.className = 'mobile-sort-buttons';
        
        // Create controls for relevant columns
        columns.forEach(col => {
            if (!col.sortable && !col.filterable) return;

            const group = document.createElement('div');
            group.className = 'mobile-control-group';
            group.dataset.column = col.key;

            // Sort button
            if (col.sortable) {
                const sortBtn = document.createElement('button');
                sortBtn.type = 'button';
                sortBtn.className = 'mobile-sort-btn';
                sortBtn.dataset.sort = col.key;
                sortBtn.innerHTML = `
                    <span>${col.label}</span>
                    <svg class="sort-icon" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5" />
                    </svg>
                `;
                group.appendChild(sortBtn);
            } else {
                // Just label if not sortable but filterable
                const labelSpan = document.createElement('span');
                labelSpan.className = 'mobile-control-label';
                labelSpan.textContent = col.label;
                group.appendChild(labelSpan);
            }

            // Filter button
            if (col.filterable) {
                const filterBtn = document.createElement('button');
                filterBtn.type = 'button';
                filterBtn.className = 'mobile-filter-btn';
                filterBtn.dataset.filterColumn = col.key;
                filterBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" width="14" height="14">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 01-.659 1.591l-5.432 5.432a2.25 2.25 0 00-.659 1.591v2.927a2.25 2.25 0 01-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 00-.659-1.591L3.659 7.409A2.25 2.25 0 013 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0112 3z" />
                </svg>`;
                
                // Create dropdown for mobile
                const dropdown = this.createColumnFilterDropdown(col);
                group.appendChild(filterBtn);
                group.appendChild(dropdown);
            }

            buttonsContainer.appendChild(group);
        });
        
        bar.appendChild(buttonsContainer);
        return bar;
    }

    createHeaderTable() {
        const { columns, tableId } = this.config;
        
        const table = document.createElement('table');
        table.className = 'virtual-table-header';
        table.id = `${tableId}-header`;

        const thead = document.createElement('thead');
        const tr = document.createElement('tr');

        columns.forEach((col, idx) => {
            const th = document.createElement('th');
            th.dataset.column = col.key;
            
            if (col.sortable) {
                th.classList.add('sortable-th');
                th.dataset.sort = col.key;
            }
            
            if (col.filterable) {
                th.dataset.filterColumn = col.key;
            }

            if (col.width) {
                th.style.width = col.width;
            }

            if (col.align) {
                th.classList.add(`text-${col.align}`);
            }

            // Header content wrapper
            const wrapper = document.createElement('div');
            wrapper.className = 'th-content';

            // Label
            const label = document.createElement('span');
            label.className = 'th-label';
            label.textContent = col.label;
            wrapper.appendChild(label);

            // Sort/filter controls
            if (col.sortable || col.filterable) {
                const controls = document.createElement('div');
                controls.className = 'th-controls';

                if (col.sortable) {
                    const sortIndicator = document.createElement('span');
                    sortIndicator.className = 'sort-indicator';
                    sortIndicator.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" width="12" height="12">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5" />
                    </svg>`;
                    controls.appendChild(sortIndicator);
                }

                if (col.filterable) {
                    const filterBtn = document.createElement('button');
                    filterBtn.type = 'button';
                    filterBtn.className = 'column-filter-btn';
                    filterBtn.title = 'Filter this column';
                    filterBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" width="14" height="14">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 01-.659 1.591l-5.432 5.432a2.25 2.25 0 00-.659 1.591v2.927a2.25 2.25 0 01-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 00-.659-1.591L3.659 7.409A2.25 2.25 0 013 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0112 3z" />
                    </svg>`;
                    controls.appendChild(filterBtn);

                    // Filter dropdown
                    const dropdown = this.createColumnFilterDropdown(col);
                    th.appendChild(dropdown);
                }

                wrapper.appendChild(controls);
            }

            th.appendChild(wrapper);
            tr.appendChild(th);
        });

        // Actions column (if actions provided)
        if (this.config.actions) {
            const th = document.createElement('th');
            th.className = 'actions-column';
            tr.appendChild(th);
        }

        thead.appendChild(tr);
        table.appendChild(thead);
        return table;
    }

    createColumnFilterDropdown(col) {
        const { i18n } = this.config;
        
        const dropdown = document.createElement('div');
        dropdown.className = 'column-filter-dropdown';
        dropdown.dataset.column = col.key;

        dropdown.innerHTML = `
            <div class="column-filter-search">
                <input type="text" placeholder="${i18n.search}" class="column-filter-search-input">
            </div>
            <div class="column-filter-options"></div>
            <div class="column-filter-actions">
                <button type="button" class="column-filter-clear">${i18n.clear}</button>
                <button type="button" class="column-filter-apply">${i18n.apply}</button>
            </div>
        `;

        return dropdown;
    }

    createPagingControls() {
        const { tableId, i18n } = this.config;
        
        const paging = document.createElement('div');
        paging.className = 'virtual-table-paging';

        paging.innerHTML = `
            <div class="paging-info">
                ${i18n.showing} <span id="${tableId}Start">0</span>-<span id="${tableId}End">0</span> ${i18n.of} <span id="${tableId}Total">0</span>
            </div>
            <div class="paging-buttons">
                <button type="button" id="${tableId}First" class="paging-btn" title="${i18n.firstPage}" disabled>
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" width="16" height="16">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M18.75 19.5l-7.5-7.5 7.5-7.5m-6 15L5.25 12l7.5-7.5" />
                    </svg>
                </button>
                <button type="button" id="${tableId}Prev" class="paging-btn" title="${i18n.prevPage}" disabled>
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" width="16" height="16">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
                    </svg>
                </button>
                <button type="button" id="${tableId}Next" class="paging-btn" title="${i18n.nextPage}" disabled>
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" width="16" height="16">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                    </svg>
                </button>
                <button type="button" id="${tableId}Last" class="paging-btn" title="${i18n.lastPage}" disabled>
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" width="16" height="16">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 4.5l7.5 7.5-7.5 7.5m6-15l7.5 7.5-7.5 7.5" />
                    </svg>
                </button>
            </div>
        `;

        return paging;
    }

    // =========================================================================
    // Event Binding
    // =========================================================================

    bindEvents() {
        // Scroll events
        this.elements.scrollBody.addEventListener('scroll', () => this.handleScroll());
        
        // Keyboard navigation
        this.elements.scrollBody.addEventListener('keydown', (e) => this.handleKeyboard(e));

        // Paging buttons
        this.bindPagingButtons();

        // Status filter buttons
        if (this.elements.filterBar) {
            this.elements.filterBar.querySelectorAll('.filter-btn').forEach(btn => {
                btn.addEventListener('click', () => this.toggleStatusFilter(btn.dataset.status));
            });
        }

        // Sortable headers
        this.elements.headerTable.querySelectorAll('.sortable-th').forEach(th => {
            th.addEventListener('click', (e) => {
                if (e.target.closest('.column-filter-btn') || e.target.closest('.column-filter-dropdown')) return;
                this.toggleSort(th.dataset.sort, e.shiftKey);
            });
        });

        // Mobile sort/filter buttons
        if (this.elements.mobileSortBar) {
            // Sort
            this.elements.mobileSortBar.querySelectorAll('.mobile-sort-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    this.toggleSort(btn.dataset.sort, false);
                    this.updateMobileSortUI();
                });
            });

            // Filter
            this.elements.mobileSortBar.querySelectorAll('.mobile-filter-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const group = btn.closest('.mobile-control-group');
                    const dropdown = group.querySelector('.column-filter-dropdown');
                    this.openColumnFilterDropdown(dropdown, btn.dataset.filterColumn);
                });
            });
        }

        // Column filter buttons
        this.elements.headerTable.querySelectorAll('.column-filter-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const th = btn.closest('th');
                const dropdown = th.querySelector('.column-filter-dropdown');
                this.openColumnFilterDropdown(dropdown, th.dataset.filterColumn);
            });
        });

        // Column filter dropdowns
        this.elements.headerTable.querySelectorAll('.column-filter-dropdown').forEach(dropdown => {
            this.bindColumnFilterDropdown(dropdown);
        });

        // Close dropdowns on outside click
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.column-filter-dropdown') && !e.target.closest('.column-filter-btn')) {
                this.elements.headerTable.querySelectorAll('.column-filter-dropdown.open').forEach(d => d.classList.remove('open'));
            }
        });

        // Search input
        if (this.elements.searchInput) {
            this.elements.searchInput.addEventListener('input', () => this.handleSearchInput());
            this.elements.searchInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') this.handleSearchInput();
            });
        }

        // Clear all button
        if (this.elements.clearAllBtn) {
            this.elements.clearAllBtn.addEventListener('click', () => this.clearAllFilters());
        }

        // Row click delegation
        if (this.config.onRowClick) {
            this.elements.tbody.addEventListener('click', (e) => {
                const row = e.target.closest('tr');
                if (row && !e.target.closest('button') && !e.target.closest('a')) {
                    const index = parseInt(row.dataset.index, 10);
                    if (!isNaN(index) && this.filteredData[index]) {
                        this.config.onRowClick(this.filteredData[index], index);
                    }
                }
            });
        }
    }

    bindPagingButtons() {
        const { tableId } = this.config;
        
        const firstBtn = document.getElementById(`${tableId}First`);
        const prevBtn = document.getElementById(`${tableId}Prev`);
        const nextBtn = document.getElementById(`${tableId}Next`);
        const lastBtn = document.getElementById(`${tableId}Last`);

        if (firstBtn) firstBtn.addEventListener('click', () => this.goToFirst());
        if (prevBtn) prevBtn.addEventListener('click', () => this.goToPrev());
        if (nextBtn) nextBtn.addEventListener('click', () => this.goToNext());
        if (lastBtn) lastBtn.addEventListener('click', () => this.goToLast());
    }

    bindColumnFilterDropdown(dropdown) {
        const column = dropdown.dataset.column;
        const searchInput = dropdown.querySelector('.column-filter-search-input');
        const clearBtn = dropdown.querySelector('.column-filter-clear');
        const applyBtn = dropdown.querySelector('.column-filter-apply');

        // Search within dropdown
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                const query = searchInput.value.toLowerCase();
                dropdown.querySelectorAll('.column-filter-option').forEach(opt => {
                    const text = opt.textContent.toLowerCase();
                    opt.style.display = text.includes(query) ? '' : 'none';
                });
            });
        }

        // Clear button
        if (clearBtn) {
            clearBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                dropdown.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
                delete this.columnFilters[column];
                this.applyFiltersAndSort();
                this.updateFilterUI();
                dropdown.classList.remove('open');
            });
        }

        // Apply button
        if (applyBtn) {
            applyBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const selected = Array.from(dropdown.querySelectorAll('input[type="checkbox"]:checked'))
                    .map(cb => cb.value);
                
                if (selected.length > 0) {
                    this.columnFilters[column] = selected;
                } else {
                    delete this.columnFilters[column];
                }
                
                this.applyFiltersAndSort();
                this.updateFilterUI();
                dropdown.classList.remove('open');
            });
        }
    }

    // =========================================================================
    // Filter & Sort Logic
    // =========================================================================

    toggleStatusFilter(status) {
        if (this.currentStatusFilter === status) {
            this.currentStatusFilter = '';
        } else {
            this.currentStatusFilter = status;
        }
        
        this.applyFiltersAndSort();
        this.updateFilterUI();
    }

    toggleSort(column, addToExisting = false) {
        const existingIdx = this.sortColumns.findIndex(s => s.column === column);

        if (existingIdx >= 0) {
            const current = this.sortColumns[existingIdx];
            if (current.direction === 'asc') {
                current.direction = 'desc';
            } else {
                this.sortColumns.splice(existingIdx, 1);
            }
        } else {
            if (!addToExisting) {
                this.sortColumns = [];
            }
            this.sortColumns.push({ column, direction: 'asc' });
        }

        this.applyFiltersAndSort();
        this.updateSortUI();
    }

    addColumnFilter(column, value) {
        if (!this.columnFilters[column]) {
            this.columnFilters[column] = [];
        }
        if (!this.columnFilters[column].includes(value)) {
            this.columnFilters[column].push(value);
            this.applyFiltersAndSort();
            this.updateFilterUI();
        }
    }

    removeColumnFilter(column, value) {
        if (this.columnFilters[column]) {
            this.columnFilters[column] = this.columnFilters[column].filter(v => v !== value);
            if (this.columnFilters[column].length === 0) {
                delete this.columnFilters[column];
            }
            this.applyFiltersAndSort();
            this.updateFilterUI();
        }
    }

    clearAllFilters() {
        this.currentStatusFilter = '';
        this.columnFilters = {};
        this.sortColumns = [];
        this.applyFiltersAndSort();
        this.updateFilterUI();
        this.updateSortUI();
    }

    applyFiltersAndSort() {
        const { statusField, columns } = this.config;
        
        // Start with original data
        let data = [...this.originalData];

        // Apply status filter
        if (this.currentStatusFilter) {
            data = data.filter(item => item[statusField] === this.currentStatusFilter);
        }

        // Apply column filters
        for (const [column, values] of Object.entries(this.columnFilters)) {
            if (values && values.length > 0) {
                data = data.filter(item => {
                    const itemValue = String(item[column] || '').toLowerCase();
                    return values.some(v => itemValue.includes(v.toLowerCase()));
                });
            }
        }

        // Apply sorting
        if (this.sortColumns.length > 0) {
            data.sort((a, b) => {
                for (const { column, direction } of this.sortColumns) {
                    const colDef = columns.find(c => c.key === column);
                    const isDate = colDef?.type === 'date';
                    const isNumber = colDef?.type === 'number';

                    let valA = a[column];
                    let valB = b[column];

                    let comparison = 0;
                    
                    if (isDate) {
                        comparison = new Date(valA || 0) - new Date(valB || 0);
                    } else if (isNumber) {
                        comparison = (parseFloat(valA) || 0) - (parseFloat(valB) || 0);
                    } else {
                        valA = String(valA || '').toLowerCase();
                        valB = String(valB || '').toLowerCase();
                        comparison = valA.localeCompare(valB);
                    }

                    if (comparison !== 0) {
                        return direction === 'asc' ? comparison : -comparison;
                    }
                }
                return 0;
            });
        }

        this.filteredData = data;
        this.viewportStartIndex = 0;
        this.elements.scrollBody.scrollTop = 0;
        this.render();
    }

    handleSearchInput() {
        const query = this.elements.searchInput.value.trim().toLowerCase();
        
        if (!query) {
            this.applyFiltersAndSort();
            return;
        }

        // Parse search query (e.g., "status:running" or free text)
        const colonIdx = query.indexOf(':');
        if (colonIdx > 0) {
            const column = query.substring(0, colonIdx);
            const value = query.substring(colonIdx + 1);
            if (column && value) {
                this.addColumnFilter(column, value);
                this.elements.searchInput.value = '';
            }
        }
    }

    // =========================================================================
    // Rendering
    // =========================================================================

    calculateViewport() {
        const height = this.elements.scrollBody.clientHeight;
        if (height > 0) {
            this.viewportRows = Math.ceil(height / this.config.rowHeight);
            this.bufferSize = this.viewportRows;
        }
    }

    render() {
        this.updateSpacerHeight();
        this.renderRows();
        this.updatePagingInfo();
        this.updateStatusCounts();
    }

    updateSpacerHeight() {
        this.elements.spacer.style.height = `${this.filteredData.length * this.config.rowHeight}px`;
    }

    renderRows() {
        if (this.isRendering) return;
        this.isRendering = true;

        const { rowHeight, columns, actions, rowClass, emptyMessage } = this.config;
        const totalCount = this.filteredData.length;

        // Calculate range to render
        const startIndex = Math.max(0, this.viewportStartIndex - this.bufferSize);
        const endIndex = Math.min(totalCount, this.viewportStartIndex + this.viewportRows + this.bufferSize);

        this.topIndex = startIndex;

        // Clear existing rows
        this.elements.tbody.innerHTML = '';

        if (totalCount === 0) {
            // Empty state
            const tr = document.createElement('tr');
            tr.className = 'empty-row';
            const td = document.createElement('td');
            td.colSpan = columns.length + (actions ? 1 : 0);
            td.className = 'empty-cell';
            td.innerHTML = `<div class="empty-state">${emptyMessage}</div>`;
            tr.appendChild(td);
            this.elements.tbody.appendChild(tr);
        } else {
            // Render visible rows
            for (let i = startIndex; i < endIndex; i++) {
                const row = this.createRow(this.filteredData[i], i);
                this.elements.tbody.appendChild(row);
            }
        }

        // Position content
        const offsetY = startIndex * rowHeight;
        this.elements.content.style.transform = `translateY(${offsetY}px)`;

        this.isRendering = false;
    }

    createRow(data, index) {
        const { columns, actions, rowClass } = this.config;
        
        const tr = document.createElement('tr');
        tr.dataset.index = index;

        // Add data attributes for each column
        columns.forEach(col => {
            if (data[col.key] !== undefined) {
                tr.dataset[col.key] = data[col.key];
            }
        });

        // Custom row class
        if (rowClass) {
            const customClass = rowClass(data, index);
            if (customClass) tr.className = customClass;
        }

        // Render columns
        columns.forEach(col => {
            const td = document.createElement('td');
            
            // Apply column width to body cells to match header
            if (col.width) {
                td.style.width = col.width;
            }
            
            if (col.align) {
                td.classList.add(`text-${col.align}`);
            }
            if (col.className) {
                td.classList.add(...col.className.split(' ').filter(c => c));
            }

            const value = data[col.key];
            
            if (col.render) {
                td.innerHTML = col.render(value, data, index);
            } else if (col.type === 'date') {
                td.textContent = this.formatDate(value);
            } else {
                td.textContent = value ?? '';
            }

            tr.appendChild(td);
        });

        // Actions column
        if (actions) {
            const td = document.createElement('td');
            td.className = 'actions-cell';
            td.innerHTML = `<div class="action-buttons">${actions(data, index)}</div>`;
            tr.appendChild(td);
        }

        return tr;
    }

    formatDate(isoString) {
        if (!isoString) return '—';
        const date = new Date(isoString);
        if (isNaN(date.getTime())) return isoString;
        // MM/DD/YY format
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const year = String(date.getFullYear()).slice(-2);
        return `${month}/${day}/${year}`;
    }

    // =========================================================================
    // Scrolling & Navigation
    // =========================================================================

    handleScroll() {
        const scrollTop = this.elements.scrollBody.scrollTop;
        const newViewportStart = Math.floor(scrollTop / this.config.rowHeight);
        const clampedStart = Math.max(0, Math.min(newViewportStart, this.filteredData.length - this.viewportRows));

        if (clampedStart === this.viewportStartIndex) return;

        this.viewportStartIndex = clampedStart;
        this.renderRows();
        this.updatePagingInfo();
    }

    handleKeyboard(e) {
        const { rowHeight } = this.config;
        
        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                this.elements.scrollBody.scrollTop += rowHeight;
                break;
            case 'ArrowUp':
                e.preventDefault();
                this.elements.scrollBody.scrollTop -= rowHeight;
                break;
            case 'PageDown':
                e.preventDefault();
                this.elements.scrollBody.scrollTop += this.viewportRows * rowHeight;
                break;
            case 'PageUp':
                e.preventDefault();
                this.elements.scrollBody.scrollTop -= this.viewportRows * rowHeight;
                break;
            case 'Home':
                e.preventDefault();
                this.goToFirst();
                break;
            case 'End':
                e.preventDefault();
                this.goToLast();
                break;
        }
    }

    goToFirst() {
        this.elements.scrollBody.scrollTop = 0;
    }

    goToLast() {
        const maxScrollTop = (this.filteredData.length - this.viewportRows) * this.config.rowHeight;
        this.elements.scrollBody.scrollTop = Math.max(0, maxScrollTop);
    }

    goToNext() {
        this.elements.scrollBody.scrollTop += this.viewportRows * this.config.rowHeight;
    }

    goToPrev() {
        this.elements.scrollBody.scrollTop -= this.viewportRows * this.config.rowHeight;
    }

    // =========================================================================
    // UI Updates
    // =========================================================================

    updatePagingInfo() {
        const { tableId } = this.config;
        const totalCount = this.filteredData.length;
        
        const startEl = document.getElementById(`${tableId}Start`);
        const endEl = document.getElementById(`${tableId}End`);
        const totalEl = document.getElementById(`${tableId}Total`);

        const visibleEnd = Math.min(this.viewportStartIndex + this.viewportRows, totalCount);

        if (startEl) startEl.textContent = totalCount > 0 ? this.viewportStartIndex + 1 : 0;
        if (endEl) endEl.textContent = visibleEnd;
        if (totalEl) totalEl.textContent = totalCount;

        // Update button states
        const firstBtn = document.getElementById(`${tableId}First`);
        const prevBtn = document.getElementById(`${tableId}Prev`);
        const nextBtn = document.getElementById(`${tableId}Next`);
        const lastBtn = document.getElementById(`${tableId}Last`);

        const canGoBack = this.viewportStartIndex > 0;
        const canGoForward = this.viewportStartIndex + this.viewportRows < totalCount;

        if (firstBtn) firstBtn.disabled = !canGoBack;
        if (prevBtn) prevBtn.disabled = !canGoBack;
        if (nextBtn) nextBtn.disabled = !canGoForward;
        if (lastBtn) lastBtn.disabled = !canGoForward;
    }

    updateStatusCounts() {
        if (!this.config.statusFilters || !this.elements.filterBar) return;

        const { statusField, statusFilters } = this.config;
        
        // Count from filtered data (respecting column filters but not status filter)
        let dataForCounts = [...this.originalData];
        
        // Apply column filters only
        for (const [column, values] of Object.entries(this.columnFilters)) {
            if (values && values.length > 0) {
                dataForCounts = dataForCounts.filter(item => {
                    const itemValue = String(item[column] || '').toLowerCase();
                    return values.some(v => itemValue.includes(v.toLowerCase()));
                });
            }
        }

        statusFilters.forEach(status => {
            const count = dataForCounts.filter(item => item[statusField] === status).length;
            const countEl = this.elements.filterBar.querySelector(`[data-count="${status}"]`);
            if (countEl) countEl.textContent = count;
        });
    }

    updateFilterUI() {
        // Update status filter button states
        if (this.elements.filterBar) {
            this.elements.filterBar.querySelectorAll('.filter-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.status === this.currentStatusFilter);
            });
        }

        // Update filter chips
        this.updateFilterChips();

        // Update clear all button visibility
        const hasFilters = this.currentStatusFilter || Object.keys(this.columnFilters).length > 0;
        if (this.elements.clearAllBtn) {
            this.elements.clearAllBtn.classList.toggle('hidden', !hasFilters);
        }

        // Update column filter button states
        this.elements.headerTable.querySelectorAll('.column-filter-btn').forEach(btn => {
            const th = btn.closest('th');
            const column = th?.dataset.filterColumn;
            btn.classList.toggle('active', column && this.columnFilters[column]?.length > 0);
        });
    }

    updateFilterChips() {
        if (!this.elements.filterChips) return;

        this.elements.filterChips.innerHTML = '';

        // Status filter chip
        if (this.currentStatusFilter) {
            const chip = this.createFilterChip('status', this.currentStatusFilter);
            this.elements.filterChips.appendChild(chip);
        }

        // Column filter chips
        for (const [column, values] of Object.entries(this.columnFilters)) {
            values.forEach(value => {
                const chip = this.createFilterChip(column, value);
                this.elements.filterChips.appendChild(chip);
            });
        }
    }

    createFilterChip(column, value) {
        const chip = document.createElement('span');
        chip.className = 'filter-chip';
        chip.innerHTML = `
            <span>${column}:${value}</span>
            <button type="button" class="filter-chip-remove" data-column="${column}" data-value="${value}">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" width="12" height="12">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
            </button>
        `;

        chip.querySelector('.filter-chip-remove').addEventListener('click', () => {
            if (column === 'status') {
                this.currentStatusFilter = '';
                this.applyFiltersAndSort();
                this.updateFilterUI();
            } else {
                this.removeColumnFilter(column, value);
            }
        });

        return chip;
    }

    updateSortUI() {
        this.elements.headerTable.querySelectorAll('.sortable-th').forEach(th => {
            const column = th.dataset.sort;
            const sortInfo = this.sortColumns.find(s => s.column === column);
            const indicator = th.querySelector('.sort-indicator');

            th.classList.toggle('sort-active', !!sortInfo);
            if (indicator) {
                indicator.classList.toggle('desc', sortInfo?.direction === 'desc');
            }
        });
        
        // Update mobile sort bar too
        this.updateMobileSortUI();
    }

    updateMobileSortUI() {
        if (!this.elements.mobileSortBar) return;
        
        this.elements.mobileSortBar.querySelectorAll('.mobile-sort-btn').forEach(btn => {
            const column = btn.dataset.sort;
            const sortInfo = this.sortColumns.find(s => s.column === column);
            
            btn.classList.toggle('active', !!sortInfo);
            btn.classList.toggle('desc', sortInfo?.direction === 'desc');
        });
    }

    openColumnFilterDropdown(dropdown, column) {
        // Close other dropdowns
        this.elements.headerTable.querySelectorAll('.column-filter-dropdown.open').forEach(d => {
            if (d !== dropdown) d.classList.remove('open');
        });

        // Populate options
        const optionsContainer = dropdown.querySelector('.column-filter-options');
        const uniqueValues = new Set();
        
        this.originalData.forEach(item => {
            const val = item[column];
            if (val) uniqueValues.add(val);
        });

        const sortedValues = Array.from(uniqueValues).sort();
        const currentFilters = this.columnFilters[column] || [];

        optionsContainer.innerHTML = sortedValues.map(value => `
            <label class="column-filter-option">
                <input type="checkbox" value="${this.escapeHtml(value)}" ${currentFilters.includes(value) ? 'checked' : ''}>
                <span>${this.escapeHtml(value)}</span>
            </label>
        `).join('');

        dropdown.classList.toggle('open');
    }

    escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // =========================================================================
    // Public API
    // =========================================================================

    /**
     * Set new data and re-render
     * @param {Array} data - New data array
     */
    setData(data) {
        this.originalData = [...data];
        this.applyFiltersAndSort();
    }

    /**
     * Get current filtered/sorted data
     * @returns {Array}
     */
    getData() {
        return this.filteredData;
    }

    /**
     * Get original unfiltered data
     * @returns {Array}
     */
    getOriginalData() {
        return this.originalData;
    }

    /**
     * Refresh display (recalculate viewport and re-render)
     */
    refresh() {
        this.calculateViewport();
        this.render();
    }

    /**
     * Destroy the widget and clean up
     */
    destroy() {
        this.config.container.innerHTML = '';
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = VirtualTable;
}
