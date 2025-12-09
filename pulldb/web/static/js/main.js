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
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'fadeOut 0.3s ease-out forwards';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

window.showToast = showToast;
