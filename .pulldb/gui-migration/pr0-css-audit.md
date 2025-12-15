# Inline CSS Audit Report

**Total `<style>` blocks**: 36
**Blocks ≥10 lines**: 36
**Total inline CSS lines**: 10193

## Files by Priority (Most CSS First)

| Priority | File | CSS Lines | Blocks | Action |
|----------|------|-----------|--------|--------|
| 🔴 Critical | `hosts.html` | 1109 | 1 | Extract to components.css |
| 🔴 Critical | `dashboard.html` | 590 | 1 | Extract to components.css |
| 🔴 Critical | `settings.html` | 573 | 1 | Extract to components.css |
| 🟠 High | `logo.html` | 570 | 1 | Extract to components.css |
| 🟠 High | `maintenance.html` | 512 | 1 | Extract to components.css |
| 🟠 High | `restore.html` | 453 | 1 | Extract to components.css |
| 🟡 Medium | `users.html` | 434 | 1 | Extract to components.css |
| 🟡 Medium | `restore.html` | 416 | 1 | Extract to components.css |
| 🟡 Medium | `job_search.html` | 387 | 1 | Extract to components.css |
| 🟢 Low | `host_detail.html` | 376 | 1 | Extract to components.css |
| 🟢 Low | `my_jobs.html` | 365 | 1 | Extract to components.css |
| 🟢 Low | `login.html` | 364 | 1 | Extract to components.css |
| 🟢 Low | `searchable_dropdown.html` | 280 | 1 | Extract to components.css |
| 🟢 Low | `history.html` | 279 | 1 | Extract to components.css |
| 🟢 Low | `profile.html` | 279 | 1 | Extract to components.css |
| 🟢 Low | `submit_for_user.html` | 259 | 1 | Extract to components.css |
| 🟢 Low | `user_detail.html` | 240 | 1 | Extract to components.css |
| 🟢 Low | `cleanup.html` | 237 | 1 | Extract to components.css |
| 🟢 Low | `jobs.html` | 234 | 1 | Extract to components.css |
| 🟢 Low | `job_profile.html` | 221 | 1 | Extract to components.css |
| 🟢 Low | `search.html` | 204 | 1 | Extract to components.css |
| 🟢 Low | `filter_bar.html` | 197 | 1 | Extract to components.css |
| 🟢 Low | `admin.html` | 197 | 1 | Extract to components.css |
| 🟢 Low | `index.html` | 169 | 1 | Extract to components.css |
| 🟢 Low | `change_password.html` | 166 | 1 | Extract to components.css |
| 🟢 Low | `user_detail.html` | 150 | 1 | Extract to components.css |
| 🟢 Low | `index.html` | 126 | 1 | Extract to components.css |
| 🟢 Low | `my_team.html` | 120 | 1 | Extract to components.css |
| 🟢 Low | `create_user.html` | 116 | 1 | Extract to components.css |
| 🟢 Low | `error.html` | 101 | 1 | Extract to components.css |
| 🟢 Low | `users.html` | 99 | 1 | Extract to feature CSS |
| 🟢 Low | `jobs.html` | 80 | 1 | Extract to feature CSS |
| 🟢 Low | `job_events.html` | 76 | 1 | Extract to feature CSS |
| 🟢 Low | `cleanup_preview.html` | 75 | 1 | Extract to feature CSS |
| 🟢 Low | `orphan_preview.html` | 71 | 1 | Extract to feature CSS |
| 🟢 Low | `prune_preview.html` | 68 | 1 | Extract to feature CSS |

## Selector Categories (Extraction Candidates)

### Alerts (7 selectors)

- `background: var(--danger-50);
    border: 1px solid var(--danger-200);
    color: var(--danger-800);
}

.alert-danger svg`
- `background: var(--warning-50);
    border: 1px solid var(--warning-200);
    color: var(--warning-800);
}

.alert-warning svg`
- `color: var(--danger-500);
}

.alert-danger a`
- `color: var(--warning-500);
}

.alert-danger`
- `display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    padding: var(--space-4);
    border-radius: var(--radius-md);
    margin-bottom: var(--space-4);
}

.alert svg`
- `display: flex;
    flex-direction: column;
    gap: var(--space-5);
}

/* Alert Styles */
.alert`
- `width: 20px;
    height: 20px;
    flex-shrink: 0;
    margin-top: 2px;
}

.alert-warning`

### Badges (11 selectors)

- `.role-badge.manager`
- `.role-badge.user`
- `background: var(--warning-100);
    color: var(--warning-700);
}

.env-badge.env-prod`
- `background: var(--warning-100);
    color: var(--warning-700);
}

.role-badge.developer`
- `display: flex;
    align-items: center;
    gap: var(--space-3);
}

.user-code-badge`
- `display: flex;
    flex-direction: column;
    gap: var(--space-5);
}

.count-badge`
- `display: flex;
    justify-content: space-between;
    align-items: center;
}

.step-badge`
- `display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-family: var(--font-mono);
    font-size: 0.8125rem;
    color: var(--gray-600);
}

.user-code-badge svg`
- `font-family: var(--font-mono);
    font-size: 0.8125rem;
    padding: 0.125rem 0.375rem;
    background: var(--gray-100);
    border-radius: var(--radius-sm);
}

.role-badge`
- `font-size: 0.875rem;
    color: var(--gray-500);
}

.env-badge`
- ... and 1 more

### Buttons (56 selectors)

- `.exclude-btn`
- `background: rgba(0, 0, 0, 0.03);
}

.filter-bar-table .filter-btn .filter-count`
- `background: rgba(255, 255, 255, 0.5);
}

.filter-bar-table .filter-cell.active .filter-btn .filter-label`
- `background: var(--danger-100);
    color: var(--danger-600);
}
.exclude-btn.excluded`
- `background: var(--danger-50);
    color: var(--danger-600);
}

.action-btn.success:hover`
- `background: var(--danger-600);
    color: white;
}
.btn-cancel-all:hover`
- `background: var(--danger-700);
}
.btn-cancel-all:disabled`
- `background: var(--gray-100);
        color: var(--gray-600);
    }

    .action-btns`
- `background: var(--gray-100);
    color: var(--gray-700);
    border-color: var(--gray-400);
}
.reset-exclusions-btn.visible`
- `background: var(--gray-100);
    color: var(--gray-700);
}

.action-btn.danger:hover`
- ... and 46 more

### Cards (42 selectors)

- `.filter-card`
- `.form-card`
- `.search-card`
- `.team-card`
- `.user-profile-card`
- `background: var(--gray-50);
            overflow-y: auto;
        }

        .login-card`
- `background: var(--gray-50);
        border-color: var(--gray-400);
    }

    /* Last Job Card */
    .last-job-card`
- `background: var(--gray-50);
}

.card-title`
- `background: white;
        border: 1px solid var(--gray-200);
        border-radius: var(--radius-xl);
        overflow: hidden;
        max-width: 560px;
        margin: 0 auto;
    }

    .form-card-header`
- `background: white;
        border: 1px solid var(--gray-200);
        border-radius: var(--radius-xl);
        overflow: hidden;
        max-width: 640px;
        margin: 0 auto;
    }

    .form-card-header`
- ... and 32 more

### Dropdowns (8 selectors)

- `.filter-group-searchable .searchable-dropdown-list`
- `.filter-group-searchable .searchable-dropdown.has-value .icon-clear`
- `.filter-group-searchable .searchable-dropdown.has-value .icon-search`
- `.filter-group-searchable .searchable-dropdown.is-loading .icon-loading`
- `display: block;
}

.filter-group-searchable .searchable-dropdown.is-loading .icon-search`
- `position: relative;
}

.filter-group-searchable .searchable-dropdown-filter`
- `width: 100%;
    padding-right: 32px;
}

.filter-group-searchable .searchable-dropdown-icon`
- `width: 14px;
    height: 14px;
    color: var(--gray-400);
    display: none;
}

.filter-group-searchable .searchable-dropdown-icon .icon-search`

### Forms (106 selectors)

- `SEARCHABLE DROPDOWN COMPONENT
   Standard type-ahead search/select for pullDB
   ================================================================= */

.searchable-dropdown`
- `background: var(--gray-100);
    color: var(--gray-500);
    cursor: not-allowed;
}

.form-input[readonly]`
- `background: white;
            border-radius: 1rem;
            box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1);
        }

        .form-control`
- `background: white;
        border: 1px solid var(--gray-200);
        border-radius: var(--radius-xl);
        padding: var(--space-6);
        margin-bottom: var(--space-6);
    }

    .search-form`
- `background: white;
    color: var(--primary-600);
    box-shadow: var(--shadow-sm);
}

.form-tab svg`
- `block or CSS file:
        searchable_dropdown_styles()
        
        In your form:
        searchable_dropdown(
            id="customer",
            name="customer",
            label="Customer Name",
            placeholder="Type at least 5 characters...",
            min_chars=5,
            api_endpoint="/api/customers/search",
            hint="Type 5+ characters to search customers"
        )
        
        Before </body>:
        searchable_dropdown_scripts()
#}`
- `border-color: var(--primary-300);
        background: var(--primary-50);
    }
    
    .env-option.is-selected`
- `border-color: var(--primary-300);
        box-shadow: var(--shadow-md);
        transform: translateY(-2px);
    }

    .section-icon`
- `border-color: var(--primary-300);
    background: var(--primary-50);
    transform: translateX(4px);
}

.action-icon`
- `border-color: var(--primary-300);
    box-shadow: var(--shadow-md);
    transform: translateY(-2px);
}

.section-icon`
- ... and 96 more

### Layout (75 selectors)

- `.admin-grid`
- `.admin-page`
- `.admin-sections-grid`
- `.error-container`
- `.header-search`
- `.logo-manager-grid`
- `.manager-sections-grid`
- `.profile-container`
- `.profile-header`
- `.restore-container`
- ... and 65 more

### Modals (6 selectors)

- `background: white;
    border-radius: 8px;
    padding: 1.5rem;
    max-width: 450px;
    width: 90%;
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
}
.modal-title`
- `color: var(--primary-600);
    border-bottom-color: var(--primary-600);
}
/* Bulk cancel modal */
.modal-overlay`
- `margin-bottom: 1.5rem;
}
.modal-body p`
- `margin: 0 0 1rem 0;
    font-size: 1.25rem;
    color: var(--danger-700);
}
.modal-body`
- `outline: none;
    border-color: var(--danger-500);
}
.modal-footer`
- `position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
}
.modal-content`

### Navigation (5 selectors)

- `.breadcrumb-nav`
- `color: var(--primary-600);
}

.breadcrumb-link svg`
- `display: flex;
    flex-direction: column;
    gap: var(--space-5);
}

.host-detail-sidebar`
- `display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-size: 0.875rem;
    color: var(--gray-600);
    text-decoration: none;
}

.breadcrumb-link:hover`
- `margin-bottom: var(--space-4);
}

.breadcrumb-link`

### Other (184 selectors)

- `#admin-jobs .content-body`
- `.brand-content`
- `.cleanup-layout`
- `.event-timeline`
- `.host-detail-layout`
- `.live-indicator`
- `.maintenance-layout`
- `.phase-bar.phase-download`
- `.phase-bar.phase-extraction`
- `.phase-bar.phase-metadata`
- ... and 174 more

### Stat-Cards (69 selectors)

- `.stat-content`
- `.stat-icon-gray`
- `.stat-icon-info`
- `.stat-icon-success`
- `.stat-icon-warning`
- `.stat-icon.hosts`
- `.stat-icon.jobs`
- `.stats-grid`
- `.status-badge`
- `.status-badge svg`
- ... and 59 more

### Tables (17 selectors)

- `.filter-bar-table`
- `FIXED LAYOUT - FULL HEIGHT TABLE WITH SCROLLING BODY
       ===================================================== */
    
    /* Main content container fills available space - OVERRIDE base.html scroll */
    /* Use higher specificity to override base.html's .content-body`
- `background: var(--surface, white);
}

.filter-bar-table .filter-cell`
- `background: white;
        border: 1px solid var(--gray-200);
        border-radius: var(--radius-xl);
        overflow: hidden;
    }

    .history-table`
- `background: white;
        border: 1px solid var(--gray-200);
        border-radius: var(--radius-xl);
        overflow: hidden;
    }

    .team-table`
- `border-bottom: none;
    }

    .team-table tr:hover`
- `border-color: var(--primary, #3b82f6);
    border-width: 2px;
    z-index: 1;
}

.filter-bar-table .filter-cell.active::after`
- `border-left: 1px solid var(--border, #e5e7eb);
    border-radius: 0.75rem 0 0 0.75rem;
}

.filter-bar-table .filter-cell:last-child`
- `color: var(--gray-900);
    }

    /* History Table */
    .history-table-wrapper`
- `flex: 1;
    min-height: 0;
    overflow: hidden;
}

#admin-jobs .table-container`
- ... and 7 more

### Tabs (17 selectors)

- `.tabs`
- `.tabs-container`
- `background: var(--gray-100);
    color: var(--gray-900);
}

.tab.active`
- `background: var(--primary-100);
        color: var(--primary-700);
    }

    /* Tab Content - Flex grows to fill space */
    .tab-content`
- `background: var(--primary-500);
    color: white;
}

.tab svg`
- `color: var(--gray-900);
}
.tab-active`
- `display: flex !important;
        flex-direction: column !important;
        height: 100% !important;
        min-height: 0 !important;
        overflow: hidden !important;  /* Override base.html's overflow-y: auto */
        overflow-x: hidden !important;
        overflow-y: hidden !important;  /* Critical: prevent scroll context that breaks flex constraints */
    }

    /* Tab Panel - Full height flex container */
    .tab-panel`
- `display: flex;
        flex-direction: column;
        flex: 1;
        min-height: 0;
        background: white;
        border: 1px solid var(--gray-200);
        border-radius: var(--radius-xl);
        overflow: hidden;
    }

    /* Tab Header - Fixed at top */
    .tab-header`
- `display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-5);
    background: transparent;
    border: none;
    border-radius: var(--radius-md);
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--gray-600);
    cursor: pointer;
    transition: all var(--transition-fast);
}

.tab:hover`
- `display: flex;
    border-bottom: 1px solid var(--gray-200);
}
.tab`
- ... and 7 more

### Widgets (30 selectors)

- `background: var(--success-100);
    color: var(--success-700);
}

.customer-name`
- `color: var(--gray-400);
}

.search-filters`
- `color: var(--gray-800);
    }

    .filters-toggle svg`
- `color: var(--primary-700);
    }
    
    /* Customer search widget */
    .customer-search-widget`
- `display: flex;
        align-items: center;
        gap: var(--space-2);
        font-size: 0.8125rem;
        font-weight: 500;
        color: var(--gray-600);
        cursor: pointer;
        background: none;
        border: none;
        padding: 0;
    }

    .filters-toggle:hover`
- `display: flex;
        align-items: center;
        gap: var(--space-2);
        padding: var(--space-4);
        border-bottom: 1px solid var(--gray-100);
        flex-wrap: wrap;
    }

    .filter-bar-label`
- `display: flex;
        flex-direction: column;
        gap: var(--space-2);
    }

    .filter-label`
- `display: flex;
        gap: var(--space-2);
        margin-bottom: var(--space-5);
    }
    
    .env-option`
- `display: flex;
    align-items: flex-end;
    gap: var(--space-4);
    flex-wrap: wrap;
}

.filter-group`
- `display: flex;
    flex-direction: column;
    gap: var(--space-1);
}

.filter-group-searchable`
- ... and 20 more

## Detailed Breakdown

### admin/hosts.html

**Lines 262-1555** (1109 lines)
- Key selectors: `.stats-grid, display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--space-4);
    margin-bottom: var(--space-6);
}

.stat-card, display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-4);
    background: white;
    border-radius: var(--radius-lg);
    border: 1px solid var(--gray-200);
}

.stat-icon, width: 48px;
    height: 48px;
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}

.stat-icon svg, width: 24px;
    height: 24px;
}

.stat-icon-primary`

### dashboard.html

**Lines 16-702** (590 lines)
- Key selectors: `.live-indicator, display: flex;
        align-items: center;
        gap: 6px;
        font-size: 0.8125rem;
        color: var(--gray-600);
    }
    
    .live-dot, width: 8px;
        height: 8px;
        background: var(--success-500);
        border-radius: 50%;
        animation: pulse-dot 2s infinite;
    }
    
    @keyframes pulse-dot, 0%, 100%, 50%`

### admin/settings.html

**Lines 323-988** (573 lines)
- Key selectors: `Admin Settings Page Styles
   Modernized for better readability and UX
   ================================================================= */

/* --- Info Banner --- */
.info-banner, display: flex;
    gap: var(--space-4);
    padding: var(--space-4);
    background: var(--info-50);
    border: 1px solid var(--info-200);
    border-radius: var(--radius-md);
    margin-bottom: var(--space-6);
    align-items: flex-start;
}

.info-icon, flex-shrink: 0;
    padding-top: 2px;
}

.info-icon svg, width: 20px;
    height: 20px;
    color: var(--info-600);
}

.info-content p, margin: 0;
    font-size: 0.875rem;
    color: var(--info-800);
    line-height: 1.5;
}

.info-subtext`

### admin/logo.html

**Lines 273-938** (570 lines)
- Key selectors: `.logo-manager-grid, display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-6);
    margin-bottom: var(--space-6);
}

@media (max-width: 1024px), grid-template-columns: 1fr;
    }
}

/* Upload Zone */
.upload-zone, border: 2px dashed var(--gray-300);
    border-radius: var(--radius-lg);
    padding: var(--space-8);
    text-align: center;
    cursor: pointer;
    transition: all var(--transition-fast);
    margin-bottom: var(--space-4);
}

.upload-zone:hover,
.upload-zone.dragover, border-color: var(--primary-400);
    background: var(--primary-50);
}

.upload-icon svg`

### admin/maintenance.html

**Lines 332-939** (512 lines)
- Key selectors: `.tabs-container, margin-bottom: var(--space-6);
}

.tabs, display: flex;
    gap: var(--space-1);
    background: white;
    padding: var(--space-1);
    border-radius: var(--radius-lg);
    border: 1px solid var(--gray-200);
}

.tab, display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-5);
    background: transparent;
    border: none;
    border-radius: var(--radius-md);
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--gray-600);
    cursor: pointer;
    transition: all var(--transition-fast);
}

.tab:hover, background: var(--gray-100);
    color: var(--gray-900);
}

.tab.active`

### features/restore/restore.html

**Lines 6-535** (453 lines)
- Key selectors: `.restore-page, max-width: 800px;
        margin: 0 auto;
    }
    
    /* Section cards */
    .restore-section, background: white;
        border: 1px solid var(--gray-200);
        border-radius: var(--radius-lg);
        margin-bottom: var(--space-5);
    }
    
    .restore-section-header, padding: var(--space-4) var(--space-5);
        border-bottom: 1px solid var(--gray-200);
        display: flex;
        align-items: center;
        gap: var(--space-3);
    }
    
    .restore-section-number, width: 28px;
        height: 28px;
        background: var(--primary-500);
        color: white;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 600;
        font-size: 0.875rem;
        flex-shrink: 0;
    }
    
    .restore-section-title`

### features/admin/users.html

**Lines 7-515** (434 lines)
- Key selectors: `.users-page, max-width: 1200px;
    margin: 0 auto;
    padding: var(--space-6);
    height: 100%;
    display: flex;
    flex-direction: column;
    box-sizing: border-box;
}

/* Card fills remaining space */
.users-page .card, flex: 1;
    min-height: 0; /* Critical: allows flex shrinking */
    display: flex;
    flex-direction: column;
}

/* Table container fills the card */
.users-page #users-table-container, flex: 1;
    min-height: 0;
}

/* Stats Row */
.stats-row, display: flex;
    gap: var(--space-3);
    margin-bottom: var(--space-5);
}

.stat-pill`

### restore.html

**Lines 312-805** (416 lines)
- Key selectors: `.restore-container, display: grid;
    grid-template-columns: 1fr 320px;
    gap: var(--space-6);
    align-items: start;
}

.restore-form, display: flex;
    flex-direction: column;
    gap: var(--space-6);
}

.form-card, background: white;
}

.form-card .card-header, display: flex;
    justify-content: space-between;
    align-items: center;
}

.step-badge`

### job_search.html

**Lines 11-465** (387 lines)
- Key selectors: `.search-card, background: white;
        border: 1px solid var(--gray-200);
        border-radius: var(--radius-xl);
        padding: var(--space-6);
        margin-bottom: var(--space-6);
    }

    .search-form, display: flex;
        gap: var(--space-3);
        align-items: flex-end;
    }

    .search-input-group, flex: 1;
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
    }

    .search-label, font-size: 0.75rem;
        font-weight: 500;
        color: var(--gray-600);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .search-input-wrapper`

### admin/host_detail.html

**Lines 244-694** (376 lines)
- Key selectors: `.host-detail-layout, display: grid;
    grid-template-columns: 1fr 320px;
    gap: var(--space-6);
    max-width: 1200px;
    margin: 0 auto;
}

@media (max-width: 900px), grid-template-columns: 1fr;
    }
}

.host-detail-main, display: flex;
    flex-direction: column;
    gap: var(--space-5);
}

.host-detail-sidebar, display: flex;
    flex-direction: column;
    gap: var(--space-5);
}

/* Alert Styles */
.alert`

