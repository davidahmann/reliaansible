// Dashboard JavaScript functionality

// Auto-refresh functionality for dashboard pages
document.addEventListener('DOMContentLoaded', function() {
    // Check if auto-refresh is enabled
    const autoRefreshCheckbox = document.getElementById('auto-refresh');
    if (autoRefreshCheckbox) {
        autoRefreshCheckbox.addEventListener('change', function() {
            if (this.checked) {
                // Start auto-refresh
                startAutoRefresh();
            } else {
                // Stop auto-refresh
                stopAutoRefresh();
            }
        });
        
        // Start auto-refresh if checkbox is checked by default
        if (autoRefreshCheckbox.checked) {
            startAutoRefresh();
        }
    }
    
    // Format timestamps
    formatTimestamps();
});

// Global variable to hold auto-refresh interval
let autoRefreshInterval;

// Start auto-refresh
function startAutoRefresh() {
    // Refresh every 30 seconds
    autoRefreshInterval = setInterval(function() {
        location.reload();
    }, 30000);
}

// Stop auto-refresh
function stopAutoRefresh() {
    clearInterval(autoRefreshInterval);
}

// Format timestamps
function formatTimestamps() {
    const timestamps = document.querySelectorAll('.timestamp');
    timestamps.forEach(function(timestamp) {
        const date = new Date(timestamp.textContent);
        if (!isNaN(date)) {
            timestamp.textContent = date.toLocaleString();
        }
    });
}