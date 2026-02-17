/**
 * Admin Overlord Company Detail Page
 * HCA Layer: pages (Layer 4)
 * 
 * Handles:
 * - Save (update) managed company fields
 * - Claim company for a deployed job
 * - Release company management
 * - Delete company row
 */
(function() {
    'use strict';

    // Extract companyID from URL: /web/admin/overlord/companies/{id}
    const pathParts = window.location.pathname.split('/');
    const companyId = pathParts[pathParts.length - 1];

    // ==========================================================================
    // Helpers
    // ==========================================================================

    function getFieldValue(id) {
        const el = document.getElementById(id);
        if (!el) return undefined;
        return el.value;
    }

    async function apiCall(url, body) {
        const resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {}),
        });
        return await resp.json();
    }

    // ==========================================================================
    // Save (Update)
    // ==========================================================================

    window.saveCompany = async function() {
        const btn = document.getElementById('save-btn');
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Saving...';
        }

        const body = {};
        const fields = [
            'company', 'name', 'owner', 'subdomain',
            'dbHost', 'dbHostRead', 'dbServer', 'visible',
            'brandingPrefix', 'brandingLogo',
            'adminContact', 'adminPhone', 'adminEmail',
            'billingName', 'billingEmail',
        ];

        for (const field of fields) {
            const val = getFieldValue('field-' + field);
            if (val !== undefined) {
                body[field] = field === 'visible' ? parseInt(val, 10) : val;
            }
        }

        try {
            const data = await apiCall(
                `/web/admin/api/overlord/companies/${companyId}/update`,
                body
            );

            if (data.success) {
                showToast(data.message, 'success');
                // Reload to reflect changes (flash via query param)
                setTimeout(() => {
                    window.location.href = window.location.pathname + '?updated=1';
                }, 400);
            } else {
                showToast(data.message || 'Update failed', 'error');
            }
        } catch (e) {
            showToast('Error: ' + e.message, 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Save Changes';
            }
        }
    };

    // ==========================================================================
    // Claim
    // ==========================================================================

    window.claimCompany = async function() {
        const select = document.getElementById('claim-job-select');
        if (!select) return;

        const jobId = select.value;
        if (!jobId) {
            showToast('Select a deployed job first', 'error');
            return;
        }

        if (!confirm(`Claim this company for job ${jobId}? This will enable editing.`)) return;

        try {
            const data = await apiCall(
                `/web/admin/api/overlord/companies/${companyId}/claim`,
                { job_id: parseInt(jobId, 10) }
            );

            if (data.success) {
                showToast(data.message, 'success');
                setTimeout(() => window.location.reload(), 600);
            } else {
                showToast(data.message || 'Claim failed', 'error');
            }
        } catch (e) {
            showToast('Error: ' + e.message, 'error');
        }
    };

    // ==========================================================================
    // Release
    // ==========================================================================

    window.releaseCompany = async function() {
        const select = document.getElementById('release-action-select');
        const action = select ? select.value : 'RESTORE';

        const actionLabels = {
            'RESTORE': 'restore original values',
            'CLEAR': 'clear routing fields',
            'DELETE': 'delete the row if it was created by pullDB',
        };

        const msg = `Release management of this company? Action: ${actionLabels[action] || action}`;
        if (!confirm(msg)) return;

        try {
            const data = await apiCall(
                `/web/admin/api/overlord/companies/${companyId}/release`,
                { action: action }
            );

            if (data.success) {
                showToast(data.message, 'success');
                setTimeout(() => window.location.reload(), 600);
            } else {
                showToast(data.message || 'Release failed', 'error');
            }
        } catch (e) {
            showToast('Error: ' + e.message, 'error');
        }
    };

    // ==========================================================================
    // Delete
    // ==========================================================================

    window.deleteCompany = async function() {
        const dbName = document.querySelector('.form-static.monospace')?.textContent?.trim() || companyId;

        if (!confirm(`DELETE company "${dbName}" from the overlord table?\n\nThis is permanent and cannot be undone.`)) return;
        if (!confirm(`Are you absolutely sure? Type YES to confirm.\n\n(This is the second confirmation for safety.)`)) return;

        try {
            const data = await apiCall(
                `/web/admin/api/overlord/companies/${companyId}/delete`,
                {}
            );

            if (data.success) {
                showToast(data.message, 'success');
                setTimeout(() => {
                    window.location.href = '/web/admin/overlord/companies';
                }, 600);
            } else {
                showToast(data.message || 'Delete failed', 'error');
            }
        } catch (e) {
            showToast('Error: ' + e.message, 'error');
        }
    };

})();
