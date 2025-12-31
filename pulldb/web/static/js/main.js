document.addEventListener('DOMContentLoaded', () => {
    // =================================================================
    // SIDEBAR - Trigger strip hover/touch to reveal
    // =================================================================
    const sidebarTrigger = document.getElementById('sidebar-trigger');
    const sidebar = document.getElementById('app-sidebar');
    const sidebarToggle = document.getElementById('sidebar-toggle');
    
    let sidebarTimeout = null;
    
    function openSidebar() {
        if (sidebar) {
            sidebar.classList.add('sidebar-open');
            if (sidebarTrigger) sidebarTrigger.classList.add('hidden');
        }
    }
    
    function closeSidebar() {
        if (sidebar) {
            sidebar.classList.remove('sidebar-open');
            if (sidebarTrigger) sidebarTrigger.classList.remove('hidden');
        }
    }
    
    if (sidebarTrigger && sidebar) {
        // Desktop: Mouse enter trigger strip
        sidebarTrigger.addEventListener('mouseenter', () => {
            clearTimeout(sidebarTimeout);
            openSidebar();
        });
        
        // Touch: Tap trigger strip
        sidebarTrigger.addEventListener('touchstart', (e) => {
            e.preventDefault();
            openSidebar();
        }, { passive: false });
        
        // Close when mouse leaves sidebar
        sidebar.addEventListener('mouseleave', () => {
            sidebarTimeout = setTimeout(closeSidebar, 300);
        });
        
        // Keep open while hovering sidebar
        sidebar.addEventListener('mouseenter', () => {
            clearTimeout(sidebarTimeout);
        });
        
        // Close when clicking outside
        document.addEventListener('click', (e) => {
            if (!sidebar.contains(e.target) && 
                !sidebarTrigger.contains(e.target) &&
                (!sidebarToggle || !sidebarToggle.contains(e.target))) {
                closeSidebar();
            }
        });
        
        // Close on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeSidebar();
            }
        });
    }
    
    // Header toggle button (alternative trigger)
    if (sidebarToggle && sidebar) {
        sidebarToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            if (sidebar.classList.contains('sidebar-open')) {
                closeSidebar();
            } else {
                openSidebar();
            }
        });
    }

    // =================================================================
    // FORM VALIDATION
    // =================================================================
    document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', (e) => {
            let valid = true;
            form.querySelectorAll('input[required], select[required]').forEach(input => {
                if (!input.value.trim()) {
                    valid = false;
                    input.style.borderColor = 'var(--danger-500)';
                } else {
                    input.style.borderColor = '';
                }
            });
            if (!valid) {
                e.preventDefault();
                showToast('Please fill in all required fields.', 'error');
            }
        });
    });
});

// =================================================================
// TOAST NOTIFICATIONS
// =================================================================

/**
 * Type-based auto-dismiss durations (milliseconds)
 * All toasts have a close button for manual dismissal
 */
const TOAST_DURATIONS = {
    success: 5000,   // 5 seconds
    info: 5000,      // 5 seconds
    warning: 30000,  // 30 seconds
    error: 60000     // 60 seconds
};

/**
 * Create a close button element for toasts
 * @returns {HTMLButtonElement}
 */
function createToastCloseButton(onClose) {
    const closeBtn = document.createElement('button');
    closeBtn.innerHTML = '&times;';
    closeBtn.className = 'toast-close';
    closeBtn.setAttribute('aria-label', 'Close');
    closeBtn.style.cssText = `
        background: none;
        border: none;
        color: inherit;
        font-size: 1.25rem;
        font-weight: bold;
        cursor: pointer;
        margin-left: 12px;
        padding: 0 4px;
        opacity: 0.7;
        line-height: 1;
        flex-shrink: 0;
    `;
    closeBtn.addEventListener('mouseenter', () => closeBtn.style.opacity = '1');
    closeBtn.addEventListener('mouseleave', () => closeBtn.style.opacity = '0.7');
    closeBtn.addEventListener('click', onClose);
    return closeBtn;
}

/**
 * Dismiss a toast element with animation
 * @param {HTMLElement} toast
 */
function dismissToast(toast) {
    toast.style.animation = 'fadeOut 0.3s ease-out forwards';
    setTimeout(() => toast.remove(), 300);
}

/**
 * Show a toast notification
 * @param {string} message - The message to display
 * @param {string} type - Toast type: 'success', 'info', 'warning', 'error'
 */
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.style.display = 'flex';
    toast.style.alignItems = 'center';
    toast.style.justifyContent = 'space-between';
    
    // Create message span
    const msgSpan = document.createElement('span');
    msgSpan.textContent = message;
    toast.appendChild(msgSpan);
    
    // Always add close button
    const closeBtn = createToastCloseButton(() => dismissToast(toast));
    toast.appendChild(closeBtn);
    
    container.appendChild(toast);
    
    // Auto-dismiss based on type
    const duration = TOAST_DURATIONS[type] || TOAST_DURATIONS.info;
    setTimeout(() => {
        if (toast.parentNode) {
            dismissToast(toast);
        }
    }, duration);
}

/**
 * Show a validation summary with multiple error messages
 * Displayed as a toast-like panel with a bullet list of errors
 * @param {string[]} errors - Array of error messages
 * @param {string} title - Optional title (default: 'Please fix the following issues:')
 */
function showValidationSummary(errors, title = 'Please fix the following issues:') {
    const container = document.getElementById('toast-container');
    if (!container || !errors || errors.length === 0) return;
    
    const toast = document.createElement('div');
    toast.className = 'toast toast-error validation-summary';
    toast.style.cssText = `
        display: flex;
        flex-direction: column;
        align-items: stretch;
        max-width: 400px;
        padding: 12px 16px;
    `;
    
    // Header with title and close button
    const header = document.createElement('div');
    header.style.cssText = `
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        margin-bottom: 8px;
    `;
    
    const titleSpan = document.createElement('strong');
    titleSpan.textContent = title;
    titleSpan.style.cssText = 'flex: 1; padding-right: 8px;';
    header.appendChild(titleSpan);
    
    const closeBtn = createToastCloseButton(() => dismissToast(toast));
    header.appendChild(closeBtn);
    toast.appendChild(header);
    
    // Error list
    const list = document.createElement('ul');
    list.style.cssText = `
        margin: 0;
        padding-left: 20px;
        font-size: 0.9em;
        line-height: 1.5;
    `;
    errors.forEach(err => {
        const li = document.createElement('li');
        li.textContent = err;
        list.appendChild(li);
    });
    toast.appendChild(list);
    
    container.appendChild(toast);
    
    // Auto-dismiss after 60 seconds (error duration)
    setTimeout(() => {
        if (toast.parentNode) {
            dismissToast(toast);
        }
    }, TOAST_DURATIONS.error);
}

window.showToast = showToast;
window.showValidationSummary = showValidationSummary;

/**
 * Show a themed confirmation modal (replacement for native confirm())
 * @param {string} message - The confirmation message
 * @param {Object} options - Optional configuration
 * @param {string} options.title - Modal title (default: 'Confirm')
 * @param {string} options.okText - OK button text (default: 'OK')
 * @param {string} options.cancelText - Cancel button text (default: 'Cancel')
 * @param {string} options.type - Modal type: 'default', 'danger', 'warning' (default: 'default')
 * @returns {Promise<boolean>} - Resolves to true if confirmed, false if cancelled
 */
function showConfirm(message, options = {}) {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirm-modal');
        const header = document.getElementById('confirm-modal-header');
        const title = document.getElementById('confirm-modal-title');
        const msg = document.getElementById('confirm-modal-message');
        const okBtn = document.getElementById('confirm-modal-ok');
        
        if (!modal || !msg || !okBtn) {
            // Fallback to native confirm if modal not available
            resolve(confirm(message));
            return;
        }
        
        // Set content
        title.textContent = options.title || 'Confirm';
        msg.innerHTML = message.replace(/\n/g, '<br>');
        okBtn.textContent = options.okText || 'OK';
        
        // Reset header classes and apply type
        header.className = 'modal-header';
        okBtn.className = 'btn btn-primary';
        
        if (options.type === 'danger') {
            header.classList.add('modal-header-danger');
            okBtn.className = 'btn btn-danger';
        } else if (options.type === 'warning') {
            header.classList.add('modal-header-warning');
            okBtn.className = 'btn btn-warning';
        }
        
        // Setup handlers
        const cleanup = () => {
            modal.classList.add('modal-hidden');
            window._confirmResolve = null;
            window._confirmReject = null;
        };
        
        window._confirmResolve = () => {
            cleanup();
            resolve(true);
        };
        
        window._confirmReject = () => {
            cleanup();
            resolve(false);
        };
        
        // Handle Escape key
        const handleKeydown = (e) => {
            if (e.key === 'Escape') {
                window._confirmReject();
                document.removeEventListener('keydown', handleKeydown);
            } else if (e.key === 'Enter') {
                window._confirmResolve();
                document.removeEventListener('keydown', handleKeydown);
            }
        };
        document.addEventListener('keydown', handleKeydown);
        
        // Show modal
        modal.classList.remove('modal-hidden');
        okBtn.focus();
    });
}

window.showConfirm = showConfirm;
