/**
 * DashPi Display Shell
 *
 * Runs in the Raspberry Pi browser (fullscreen kiosk mode) and orchestrates
 * the rotating dashboard. Every second it polls /api/current_state to learn
 * which plugin should be active; when the active plugin changes it fetches
 * that plugin's dashboard.html fragment, injects it into the container, and
 * re-executes the fragment's <script> tags. The fragment's own script then
 * listens for lifecycle events to render itself.
 *
 * Plugin contract — events dispatched on window:
 *   - 'plugin-dashboard-loaded' : { pluginId, state }
 *       DOM is ready and injected scripts have executed.
 *   - 'plugin-data'             : { pluginId, data, settings }
 *       Fresh data fetched from /api/plugin/<id>/data.
 *   - 'plugin-data-error'       : { pluginId, error }
 *       Data fetch failed (network error or server-reported error).
 *
 * Plugin contract — global helpers exposed on window:
 *   - window.setDataRefreshInterval(ms)  Customize the data poll cadence.
 *   - window.refreshPluginData()         Trigger an immediate data fetch.
 */

// ===========================================================================
// State
// ===========================================================================

/** Plugin id currently rendered in the container, or null. */
let currentPluginId = null;

/** How often (ms) to poll /api/current_state. */
const pollIntervalMs = 1000;

/** setInterval handle for the per-plugin data refresh, or null. */
let dataRefreshTimer = null;

/** Consecutive poll failure count; reset to 0 on a successful poll. */
let consecutivePollFailures = 0;

/** setTimeout handle for auto-hiding the error overlay, or null. */
let errorHideTimer = null;

/** Consecutive failures required to enter the "Reconnecting..." state. */
const RECONNECT_THRESHOLD = 3;

/** Auto-hide delay (ms) for non-persistent error messages. */
const ERROR_AUTOHIDE_MS = 10000;

/** Default data refresh cadence (ms) for a freshly loaded plugin. */
const DEFAULT_DATA_REFRESH_MS = 60000;

// ===========================================================================
// Polling
// ===========================================================================

/**
 * Poll /api/current_state and react to plugin changes.
 *
 * On a plugin change, loads the new plugin's dashboard.html fragment. If no
 * plugin is active, shows a placeholder. Transient poll errors are surfaced
 * via the error overlay; after RECONNECT_THRESHOLD consecutive failures a
 * persistent "Reconnecting..." state is shown until the next success.
 */
async function pollCurrentState() {
    try {
        const response = await fetch('/api/current_state');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const state = await response.json();

        // Successful poll — reset failure tracking and clear any error UI.
        consecutivePollFailures = 0;
        hideError();

        if (state.plugin_id && state.plugin_id !== currentPluginId) {
            await loadPlugin(state.plugin_id, state);
        } else if (!state.plugin_id && currentPluginId !== null) {
            // No active plugin — show placeholder.
            showPlaceholder();
        }

        // Remaining-time / status display could be updated here if desired.
    } catch (err) {
        // Transient fetch failures (e.g. Flask dev-server restart, brief network
        // blip) are expected — log as a warning, not an error, to avoid noise.
        // The handlePollFailure() escalation logic still surfaces persistent
        // outages via the error overlay.
        console.warn('Poll failed (will retry):', err.message);
        handlePollFailure();
    }
}

/**
 * Track consecutive poll failures and escalate the UI message.
 *
 * Below RECONNECT_THRESHOLD the overlay auto-hides after ERROR_AUTOHIDE_MS;
 * at or above the threshold a persistent "Reconnecting..." state takes over
 * until the next successful poll clears it.
 */
function handlePollFailure() {
    consecutivePollFailures++;
    if (consecutivePollFailures >= RECONNECT_THRESHOLD) {
        showError('Reconnecting...', /* persistent */ true);
    } else {
        showError('Connection lost. Retrying...');
    }
}

// ===========================================================================
// Plugin loading
// ===========================================================================

/**
 * Fetch a plugin's dashboard.html fragment, inject it into the container,
 * re-execute any inline scripts, and kick off data refresh polling.
 *
 * @param {string} pluginId - The plugin to load.
 * @param {object} state - The latest current_state snapshot from the server.
 */
async function loadPlugin(pluginId, state) {
    showLoading(true);
    hideError();

    try {
        const response = await fetch(`/plugin/${pluginId}/dashboard.html`);
        if (!response.ok) {
            throw new Error(`Failed to load plugin view: HTTP ${response.status}`);
        }
        const html = await response.text();

        // Inject into container.
        const container = document.getElementById('dashboard-container');
        container.innerHTML = html;

        // innerHTML does not execute <script> tags, so re-inject them.
        executeInjectedScripts(container);

        currentPluginId = pluginId;
        showLoading(false);

        // Notify the plugin's script that its DOM is in place.
        window.dispatchEvent(new CustomEvent('plugin-dashboard-loaded', {
            detail: { pluginId, state }
        }));

        // Start periodic data fetching for this plugin.
        startDataRefresh(pluginId);
    } catch (err) {
        console.error('Failed to load plugin:', err);
        showError(`Failed to load dashboard: ${err.message}`);
        showLoading(false);
    }
}

/**
 * Re-create each <script> node inside a container so the browser executes it.
 *
 * Replacing the node (rather than copying textContent) is required because
 * scripts inserted via innerHTML are intentionally not run by the HTML spec.
 *
 * @param {HTMLElement} container - The element holding the injected fragment.
 */
function executeInjectedScripts(container) {
    const scripts = container.querySelectorAll('script');
    scripts.forEach(oldScript => {
        const newScript = document.createElement('script');
        if (oldScript.src) {
            newScript.src = oldScript.src;
        } else {
            newScript.textContent = oldScript.textContent;
        }
        oldScript.parentNode.replaceChild(newScript, oldScript);
    });
}

// ===========================================================================
// Data refresh
// ===========================================================================

/**
 * Start periodic data fetching for the current plugin.
 *
 * Fetches immediately, then on a fixed interval. The interval is initially
 * DEFAULT_DATA_REFRESH_MS (60s) but will be updated when the first data
 * response carries a ``refresh_interval_seconds`` from the server.
 *
 * @param {string} pluginId - The plugin whose data to refresh.
 */
function startDataRefresh(pluginId) {
    clearDataRefreshTimer();
    fetchPluginData(pluginId);
    dataRefreshTimer = setInterval(
        () => fetchPluginData(pluginId),
        DEFAULT_DATA_REFRESH_MS
    );
}

/**
 * Clear the active data refresh timer, if any.
 */
function clearDataRefreshTimer() {
    if (dataRefreshTimer) {
        clearInterval(dataRefreshTimer);
        dataRefreshTimer = null;
    }
}

/**
 * Fetch the current plugin's data and dispatch a plugin-data (or
 * plugin-data-error) event that the plugin's dashboard.html script consumes.
 *
 * @param {string} pluginId - The plugin whose data to fetch.
 */
async function fetchPluginData(pluginId) {
    try {
        const response = await fetch(`/api/plugin/${pluginId}/data`);
        const result = await response.json();

        if (!response.ok || result.error) {
            const errorMsg = result.error || `HTTP ${response.status}`;
            window.dispatchEvent(new CustomEvent('plugin-data-error', {
                detail: { pluginId, error: errorMsg }
            }));
            return;
        }

        // Dispatch event with the data — plugin's dashboard.html script
        // listens for this.
        window.dispatchEvent(new CustomEvent('plugin-data', {
            detail: { pluginId, data: result.data, settings: result.settings }
        }));

        // If the server returned a per-plugin refresh interval, adjust our
        // polling cadence so we don't hammer the backend unnecessarily.
        if (result.refresh_interval_seconds) {
            const serverIntervalMs = result.refresh_interval_seconds * 1000;
            // Only adjust if the timer is still running (plugin hasn't
            // overridden it via setDataRefreshInterval).
            if (dataRefreshTimer && serverIntervalMs !== DEFAULT_DATA_REFRESH_MS) {
                clearDataRefreshTimer();
                dataRefreshTimer = setInterval(
                    () => fetchPluginData(currentPluginId),
                    serverIntervalMs
                );
            }
        }
    } catch (err) {
        console.error('Data fetch error:', err);
        window.dispatchEvent(new CustomEvent('plugin-data-error', {
            detail: { pluginId, error: err.message }
        }));
    }
}

/**
 * Allow a plugin to customize its data refresh cadence.
 *
 * @param {number} ms - Refresh interval in milliseconds.
 */
window.setDataRefreshInterval = function (ms) {
    clearDataRefreshTimer();
    if (currentPluginId) {
        dataRefreshTimer = setInterval(
            () => fetchPluginData(currentPluginId),
            ms
        );
    }
};

/**
 * Allow a plugin to trigger an immediate data fetch on demand.
 */
window.refreshPluginData = function () {
    if (currentPluginId) {
        fetchPluginData(currentPluginId);
    }
};

// ===========================================================================
// UI helpers
// ===========================================================================

/**
 * Show or hide the loading indicator.
 *
 * @param {boolean} show - True to display the indicator, false to hide it.
 */
function showLoading(show) {
    const el = document.getElementById('loading-indicator');
    if (el) el.style.display = show ? 'flex' : 'none';
}

/**
 * Display a message in the error overlay.
 *
 * By default the overlay auto-hides after ERROR_AUTOHIDE_MS. Pass
 * `persistent = true` for states (e.g. "Reconnecting...") that should remain
 * until the next successful poll clears them via hideError().
 *
 * @param {string} message - The message to display.
 * @param {boolean} [persistent=false] - When true, do not auto-hide.
 */
function showError(message, persistent = false) {
    const el = document.getElementById('error-overlay');
    if (!el) return;
    el.textContent = message;
    el.style.display = 'flex';

    // Cancel any pending auto-hide from a previous message.
    if (errorHideTimer) {
        clearTimeout(errorHideTimer);
        errorHideTimer = null;
    }
    if (!persistent) {
        errorHideTimer = setTimeout(() => {
            el.style.display = 'none';
            errorHideTimer = null;
        }, ERROR_AUTOHIDE_MS);
    }
}

/**
 * Hide the error overlay and cancel any pending auto-hide timer.
 */
function hideError() {
    const el = document.getElementById('error-overlay');
    if (el) el.style.display = 'none';
    if (errorHideTimer) {
        clearTimeout(errorHideTimer);
        errorHideTimer = null;
    }
}

/**
 * Replace the dashboard container with a "no active dashboard" placeholder
 * and tear down data refresh for the previous plugin.
 */
function showPlaceholder() {
    const container = document.getElementById('dashboard-container');
    container.innerHTML =
        '<div style="display:flex;align-items:center;justify-content:center;' +
        'width:100%;height:100%;color:#888;font-family:sans-serif;' +
        'font-size:2rem;">No active dashboard</div>';
    currentPluginId = null;
    clearDataRefreshTimer();
}

// ===========================================================================
// Initialization
// ===========================================================================

document.addEventListener('DOMContentLoaded', () => {
    showLoading(false);
    pollCurrentState();
    setInterval(pollCurrentState, pollIntervalMs);
});

// Re-poll immediately when the tab becomes visible again (e.g. after the Pi
// wakes from sleep) so the displayed plugin is fresh without waiting for the
// next scheduled tick.
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        pollCurrentState();
    }
});
