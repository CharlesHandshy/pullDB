"""
VirtualLog Widget
=================
HCA Layer: widgets (Layer 3)

A virtualized log viewer for job execution events.
Only renders visible rows for performance with large event counts.

Features:
- Virtual scrolling with fixed row height
- Viewport-constrained (flex-based, no overflow)
- Auto-resize with parent container
- Light/dark theme support via CSS custom properties
- Cursor-based pagination for large datasets
- Live streaming for running jobs

Usage:
    Include in template:
    <div id="virtual-log-container" 
         data-job-id="{{ job.id }}"
         data-total-events="{{ total_event_count }}"
         data-is-running="{{ 'true' if job.status.value in ['running', 'queued'] else 'false' }}">
    </div>
    
    Initialize in JS:
    const log = new VirtualLog({
        container: document.getElementById('virtual-log-container'),
        jobId: '...',
        totalEvents: 1234,
        isRunning: true,
        initialEvents: [...],
    });
"""
