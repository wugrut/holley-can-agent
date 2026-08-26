/**
 * dashboard.js — Real-time WebSocket-driven ECU dashboard
 *
 * Connects to the Holley CAN Agent WebSocket, receives decoded CAN frames,
 * and renders live gauges using Canvas 2D API with smooth interpolation.
 */

// ─── Configuration ──────────────────────────────────────────────────────────

const CONFIG = {
    wsReconnectMs: 2000,
    wsMaxReconnect: 50,
    interpolationSpeed: 0.15,   // Lerp factor (0 = no movement, 1 = instant)
    renderFps: 30,
    rpmRedline: 6200,
    rpmMax: 7000,
    watchdogTimeoutMs: 1500,    // Show connection overlay if no WS msg in 1.5s
};

// ─── State ──────────────────────────────────────────────────────────────────

const state = {
    connected: false,
    ws: null,
    reconnectAttempts: 0,
    channels: {},        // Latest values from server
    animated: {},        // Smoothly interpolated values for rendering
    stats: {},
    renderInterval: null,
    lastMessageTimestamp: 0,
    voiceEnabled: localStorage.getItem('voice_alerts') !== 'false',
    theme: localStorage.getItem('dashboard_theme') || 'dark',
    activeLayout: localStorage.getItem('dashboard_layout') || 'grid',
    logging: false,
    wakeLock: null,
};


// ─── Grid Customization State ───────────────────────────────────────────────

const CHANNEL_METADATA = {
    'rpm': { label: 'RPM', unit: 'rev/min', min: 0, max: 8000, color: '#00e5ff' },
    'map_kpa': { label: 'BOOST / VAC', unit: 'psi', min: 0, max: 300, color: '#00e5ff', isBoost: true },
    'afr_avg': { label: 'AFR', unit: 'Air-Fuel Ratio', min: 10, max: 20, color: '#00e676' },
    'afr_left': { label: 'AFR Bank 1', unit: 'Air-Fuel Ratio', min: 10, max: 20, color: '#00e676' },
    'afr_right': { label: 'AFR Bank 2', unit: 'Air-Fuel Ratio', min: 10, max: 20, color: '#00e676' },
    'target_afr': { label: 'Target AFR', unit: 'AFR', min: 10, max: 20, color: '#ffd600' },
    'ignition_timing': { label: 'TIMING', unit: '°BTDC', min: -10, max: 45, color: '#d500f9' },
    'coolant_temp': { label: 'COOLANT', unit: '°F', min: 100, max: 260, color: '#00e5ff', isBar: true, warn: 215, danger: 240 },
    'battery_voltage': { label: 'BATTERY', unit: 'Volts', min: 10, max: 16, color: '#00e5ff', isBar: true, warnLow: 13, dangerLow: 12 },
    'tps': { label: 'TPS', unit: '%', min: 0, max: 100, color: '#00e5ff' },
    'trans_gear': { label: 'GEAR', unit: '', min: 0, max: 4, color: '#00e5ff' },
    'current_learn': { label: 'FUEL LEARN', unit: '%', min: -50, max: 50, color: '#ffffff' },
    'iat': { label: 'IAT', unit: '°F', min: 0, max: 300, color: '#ffffff' },
    'oil_pressure': { label: 'OIL PRESS', unit: 'psi', min: 0, max: 100, color: '#ff6d00' },
    'fuel_pressure': { label: 'FUEL PRESS', unit: 'psi', min: 0, max: 100, color: '#00e676' },
    'vehicle_speed': { label: 'SPEED', unit: 'mph', min: 0, max: 200, color: '#00e5ff' },
};

const DEFAULT_GRID_CONFIG = [
    { type: 'arc', channel: 'rpm' },
    { type: 'radial', channel: 'map_kpa' },
    { type: 'radial', channel: 'afr_avg' },
    { type: 'radial', channel: 'ignition_timing' },
    { type: 'bar', channel: 'coolant_temp' },
    { type: 'bar', channel: 'battery_voltage' },
    { type: 'compact-ring', channel: 'tps' },
    { type: 'compact-gear', channel: 'trans_gear' },
    { type: 'compact-value', channel: 'current_learn' },
    { type: 'compact-value', channel: 'iat' },
];

let gridConfig = [];
let pressTimer = null;

// ─── WebSocket Connection ───────────────────────────────────────────────────

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    try {
        state.ws = new WebSocket(wsUrl);
    } catch (e) {
        console.error('WebSocket creation failed:', e);
        scheduleReconnect();
        return;
    }

    state.ws.onopen = () => {
        console.log('WebSocket connected');
        state.connected = true;
        state.reconnectAttempts = 0;
        updateConnectionStatus(true);
    };

    state.ws.onmessage = (event) => {
        try {
            state.lastMessageTimestamp = Date.now();
            const msg = JSON.parse(event.data);
            handleMessage(msg);
        } catch (e) {
            console.error('Message parse error:', e);
        }
    };

    state.ws.onclose = () => {
        console.log('WebSocket disconnected');
        state.connected = false;
        updateConnectionStatus(false);
        scheduleReconnect();
    };

    state.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

function scheduleReconnect() {
    if (state.reconnectAttempts >= CONFIG.wsMaxReconnect) {
        console.error('Max reconnection attempts reached');
        return;
    }
    state.reconnectAttempts++;
    const delay = Math.min(CONFIG.wsReconnectMs * state.reconnectAttempts, 10000);
    setTimeout(connectWebSocket, delay);
}

function handleMessage(msg) {
    switch (msg.type) {
        case 'init':
            // Initial snapshot — populate all channels
            if (msg.channels) {
                Object.assign(state.channels, msg.channels);
            }
            if (msg.stats) {
                state.stats = msg.stats;
            }
            break;

        case 'update':
            // Incremental channel updates
            if (msg.channels) {
                for (const [name, data] of Object.entries(msg.channels)) {
                    state.channels[name] = data;
                }
            }
            // Handle alerts
            if (msg.alerts && msg.alerts.length > 0) {
                for (const alert of msg.alerts) {
                    showAlert(alert);
                }
            }
            break;

        case 'snapshot':
            if (msg.channels) {
                Object.assign(state.channels, msg.channels);
            }
            if (msg.stats) {
                state.stats = msg.stats;
            }
            break;

        case 'pong':
            break;
    }
}

// ─── Connection Status ──────────────────────────────────────────────────────

function updateConnectionStatus(connected) {
    const el = document.getElementById('connection-status');
    const textEl = el.querySelector('.status-text');
    el.classList.toggle('connected', connected);
    el.classList.toggle('disconnected', !connected);
    textEl.textContent = connected ? 'LIVE' : 'DISCONNECTED';
}

// ─── Alert Banner ───────────────────────────────────────────────────────────

function showAlert(alert) {
    const banner = document.getElementById('alert-banner');
    const message = document.getElementById('alert-message');
    message.textContent = `[${alert.severity.toUpperCase()}] ${alert.message}`;
    banner.classList.remove('hidden');

    // Highlight the relevant gauge card
    const cardId = getCardIdForChannel(alert.channel);
    if (cardId) {
        const card = document.getElementById(cardId);
        if (card) card.classList.add('alert-active');
    }

    // Voice alarm announcement
    if (state.voiceEnabled && window.speechSynthesis) {
        window.speechSynthesis.cancel();
        let cleanMsg = alert.message.replace(/BTDC|AFR|WOT|TPS|MAP|kPa/g, (m) => {
            const mappings = {
                'BTDC': 'degrees before top dead center',
                'AFR': 'air fuel ratio',
                'WOT': 'wide open throttle',
                'TPS': 'throttle position',
                'MAP': 'manifold pressure',
                'kPa': 'kilo pascals'
            };
            return mappings[m];
        });
        const utterance = new SpeechSynthesisUtterance(cleanMsg);
        utterance.rate = 1.0;
        utterance.pitch = 1.0;
        window.speechSynthesis.speak(utterance);
    }

    // Auto-dismiss after 15 seconds
    setTimeout(() => {
        banner.classList.add('hidden');
        if (cardId) {
            const card = document.getElementById(cardId);
            if (card) card.classList.remove('alert-active');
        }
    }, 15000);
}

function getCardIdForChannel(channel) {
    const map = {
        'rpm': 'gauge-card-rpm',
        'map_kpa': 'gauge-card-map',
        'afr_avg': 'gauge-card-afr',
        'afr_left': 'gauge-card-afr',
        'afr_right': 'gauge-card-afr',
        'ignition_timing': 'gauge-card-timing',
        'coolant_temp': 'gauge-card-coolant',
        'battery_voltage': 'gauge-card-battery',
        'tps': 'gauge-card-tps',
        'trans_gear': 'gauge-card-gear',
    };
    return map[channel] || null;
}

document.getElementById('alert-dismiss').addEventListener('click', () => {
    document.getElementById('alert-banner').classList.add('hidden');
});

// ─── Utility ────────────────────────────────────────────────────────────────

function lerp(current, target, factor) {
    return current + (target - current) * factor;
}

function clamp(val, min, max) {
    return Math.max(min, Math.min(max, val));
}

function getChannelValue(name) {
    const ch = state.channels[name];
    return ch ? ch.value : 0;
}

function getAnimatedValue(name, target) {
    if (!(name in state.animated)) {
        state.animated[name] = target;
    }
    state.animated[name] = lerp(state.animated[name], target, CONFIG.interpolationSpeed);
    return state.animated[name];
}

// ─── Canvas Gauge Renderers ─────────────────────────────────────────────────

/**
 * Draw an arc/sweep gauge (used for RPM).
 */
function drawArcGauge(canvasId, value, min, max, redline, options = {}) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    const dpr = window.devicePixelRatio || 1;

    // Handle hi-DPI
    if (canvas.dataset.scaled !== 'true') {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        ctx.scale(dpr, dpr);
        canvas.dataset.scaled = 'true';
    }

    ctx.clearRect(0, 0, w, h);

    const cx = w / 2;
    const cy = h - 20;
    const radius = Math.min(cx, cy) - 20;
    const startAngle = Math.PI;          // 180°
    const endAngle = 2 * Math.PI;        // 360°
    const totalSweep = endAngle - startAngle;

    // Normalized value
    const norm = clamp((value - min) / (max - min), 0, 1);
    const redlineNorm = clamp((redline - min) / (max - min), 0, 1);
    const valueAngle = startAngle + norm * totalSweep;
    const redlineAngle = startAngle + redlineNorm * totalSweep;

    const lineWidth = 10;

    // Track background
    ctx.beginPath();
    ctx.arc(cx, cy, radius, startAngle, endAngle);
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = lineWidth;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Redline zone
    ctx.beginPath();
    ctx.arc(cx, cy, radius, redlineAngle, endAngle);
    ctx.strokeStyle = 'rgba(255, 23, 68, 0.25)';
    ctx.lineWidth = lineWidth;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Value fill
    if (norm > 0.001) {
        const gradient = ctx.createLinearGradient(cx - radius, cy, cx + radius, cy);
        gradient.addColorStop(0, '#00e5ff');
        gradient.addColorStop(0.7, '#00e676');
        if (redlineNorm < 1) {
            gradient.addColorStop(redlineNorm, '#ff6d00');
            gradient.addColorStop(1, '#ff1744');
        }

        ctx.beginPath();
        ctx.arc(cx, cy, radius, startAngle, valueAngle);
        ctx.strokeStyle = gradient;
        ctx.lineWidth = lineWidth;
        ctx.lineCap = 'round';
        ctx.stroke();

        // Glow effect
        ctx.beginPath();
        ctx.arc(cx, cy, radius, startAngle, valueAngle);
        ctx.strokeStyle = norm > redlineNorm ? 'rgba(255,23,68,0.3)' : 'rgba(0,229,255,0.2)';
        ctx.lineWidth = lineWidth + 8;
        ctx.lineCap = 'round';
        ctx.stroke();
    }

    // Tick marks
    const tickCount = 14;
    for (let i = 0; i <= tickCount; i++) {
        const tickAngle = startAngle + (i / tickCount) * totalSweep;
        const isMajor = i % 2 === 0;
        const innerR = radius - (isMajor ? 18 : 12);
        const outerR = radius - 6;

        ctx.beginPath();
        ctx.moveTo(cx + innerR * Math.cos(tickAngle), cy + innerR * Math.sin(tickAngle));
        ctx.lineTo(cx + outerR * Math.cos(tickAngle), cy + outerR * Math.sin(tickAngle));
        ctx.strokeStyle = isMajor ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.12)';
        ctx.lineWidth = isMajor ? 2 : 1;
        ctx.stroke();

        // Labels on major ticks
        if (isMajor) {
            const labelR = radius - 28;
            const labelVal = min + (i / tickCount) * (max - min);
            ctx.fillStyle = 'rgba(255,255,255,0.4)';
            ctx.font = '10px "JetBrains Mono", monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(
                Math.round(labelVal / 1000) + 'k',
                cx + labelR * Math.cos(tickAngle),
                cy + labelR * Math.sin(tickAngle)
            );
        }
    }
}

/**
 * Draw a radial gauge (used for MAP, AFR, Timing).
 */
function drawRadialGauge(canvasId, value, min, max, options = {}) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    const dpr = window.devicePixelRatio || 1;

    if (canvas.dataset.scaled !== 'true') {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        ctx.scale(dpr, dpr);
        canvas.dataset.scaled = 'true';
    }

    ctx.clearRect(0, 0, w, h);

    const cx = w / 2;
    const cy = h / 2;
    const radius = Math.min(cx, cy) - 16;
    const startAngle = 0.75 * Math.PI;    // 135°
    const endAngle = 2.25 * Math.PI;      // 405°
    const totalSweep = endAngle - startAngle;

    const norm = clamp((value - min) / (max - min), 0, 1);
    const valueAngle = startAngle + norm * totalSweep;

    const lineWidth = 8;

    // Track
    ctx.beginPath();
    ctx.arc(cx, cy, radius, startAngle, endAngle);
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = lineWidth;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Value fill
    if (norm > 0.001) {
        const color = options.color || '#00e5ff';
        const glowColor = options.glowColor || 'rgba(0,229,255,0.2)';

        ctx.beginPath();
        ctx.arc(cx, cy, radius, startAngle, valueAngle);
        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        ctx.lineCap = 'round';
        ctx.stroke();

        // Glow
        ctx.beginPath();
        ctx.arc(cx, cy, radius, startAngle, valueAngle);
        ctx.strokeStyle = glowColor;
        ctx.lineWidth = lineWidth + 6;
        ctx.lineCap = 'round';
        ctx.stroke();
    }

    // Target marker (e.g., for AFR target)
    if (options.target !== undefined) {
        const targetNorm = clamp((options.target - min) / (max - min), 0, 1);
        const targetAngle = startAngle + targetNorm * totalSweep;
        const markerR = radius + 4;

        ctx.beginPath();
        ctx.arc(cx + markerR * Math.cos(targetAngle), cy + markerR * Math.sin(targetAngle), 4, 0, 2 * Math.PI);
        ctx.fillStyle = '#ffd600';
        ctx.fill();
        ctx.strokeStyle = 'rgba(0,0,0,0.5)';
        ctx.lineWidth = 1;
        ctx.stroke();
    }

    // Tick marks
    const tickCount = 10;
    for (let i = 0; i <= tickCount; i++) {
        const tickAngle = startAngle + (i / tickCount) * totalSweep;
        const isMajor = i % 2 === 0;
        const innerR = radius - (isMajor ? 14 : 8);
        const outerR = radius - 4;

        ctx.beginPath();
        ctx.moveTo(cx + innerR * Math.cos(tickAngle), cy + innerR * Math.sin(tickAngle));
        ctx.lineTo(cx + outerR * Math.cos(tickAngle), cy + outerR * Math.sin(tickAngle));
        ctx.strokeStyle = isMajor ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.1)';
        ctx.lineWidth = isMajor ? 1.5 : 1;
        ctx.stroke();
    }
}

// ─── Render Loop ────────────────────────────────────────────────────────────

function render() {
    // Render dynamic grid
    if (state.activeLayout === 'grid') {
        renderGrid();
    }
    
    // Always calculate global vars needed for track layout
    const rpm = getAnimatedValue('rpm', getChannelValue('rpm'));
    const mapKpa = getAnimatedValue('map_kpa', getChannelValue('map_kpa'));
    const boostPsi = (mapKpa - 101.325) * 0.145038;
    const afr = getAnimatedValue('afr_avg', getChannelValue('afr_avg'));

    // Update Track Layout elements
    if (state.activeLayout === 'track') {
        const trackRpmEl = document.getElementById('track-value-rpm');
        const trackMapEl = document.getElementById('track-value-map');
        const trackAfrEl = document.getElementById('track-value-afr');
        
        if (trackRpmEl) trackRpmEl.textContent = Math.round(rpm).toLocaleString();
        if (trackMapEl) trackMapEl.textContent = boostPsi.toFixed(1) + ' psi';
        if (trackAfrEl) trackAfrEl.textContent = afr.toFixed(1);
    }

    // Update Diagnostic table (throttled)
    if (state.activeLayout === 'diag' && (!state._lastDiagRender || Date.now() - state._lastDiagRender > 500)) {
        renderDiagnostics();
        state._lastDiagRender = Date.now();
    }

    // Timing
    const timing = getAnimatedValue('ignition_timing', getChannelValue('ignition_timing'));
    drawRadialGauge('gauge-timing', timing, -10, 45, {
        color: '#d500f9',
        glowColor: 'rgba(213,0,249,0.2)',
    });
    document.getElementById('value-timing').textContent = timing.toFixed(1);

    // Coolant Temp (bar gauge)
    const coolant = getAnimatedValue('coolant_temp', getChannelValue('coolant_temp'));
    const coolantPct = clamp((coolant - 100) / (260 - 100) * 100, 0, 100);
    const coolantBar = document.getElementById('bar-coolant');
    coolantBar.style.width = coolantPct + '%';
    coolantBar.className = 'bar-gauge-fill' +
        (coolant > 240 ? ' danger' : coolant > 215 ? ' warning' : '');
    const coolantVal = document.getElementById('value-coolant');
    coolantVal.textContent = Math.round(coolant);
    coolantVal.style.color = coolant > 240 ? '#ff1744' : coolant > 215 ? '#ff6d00' : '#ffffff';

    // Battery Voltage (bar gauge)
    const battery = getAnimatedValue('battery_voltage', getChannelValue('battery_voltage'));
    const battPct = clamp((battery - 10) / (16 - 10) * 100, 0, 100);
    const battBar = document.getElementById('bar-battery');
    battBar.style.width = battPct + '%';
    battBar.className = 'bar-gauge-fill' +
        (battery < 12 ? ' danger' : battery < 13 ? ' warning' : '');
    const battVal = document.getElementById('value-battery');
    battVal.textContent = battery.toFixed(1);
    battVal.style.color = battery < 12 ? '#ff1744' : battery < 13 ? '#ff6d00' : '#ffffff';

    // TPS (progress ring)
    const tps = getAnimatedValue('tps', getChannelValue('tps'));
    const circumference = 2 * Math.PI * 42;
    const offset = circumference * (1 - clamp(tps / 100, 0, 1));
    const tpsFill = document.getElementById('ring-tps-fill');
    tpsFill.style.strokeDasharray = circumference;
    tpsFill.style.strokeDashoffset = offset;
    tpsFill.style.stroke = tps > 90 ? '#ff6d00' : '#00e5ff';
    document.getElementById('value-tps').textContent = Math.round(tps) + '%';

    // Gear
    const gear = getChannelValue('trans_gear');
    const gearNames = { 0: 'N', 1: '1', 2: '2', 3: '3', 4: '4' };
    const gearEl = document.getElementById('value-gear');
    gearEl.textContent = gearNames[Math.round(gear)] || 'N';
    gearEl.style.color = gear > 0 ? '#00e5ff' : '#5f6368';

    const tcc = getChannelValue('tcc_status');
    document.getElementById('value-tcc').textContent = tcc > 50 ? 'TCC: LOCKED' : 'TCC: OPEN';

    // Fuel Learn
    const learn = getChannelValue('current_learn');
    const learnEl = document.getElementById('value-learn');
    learnEl.textContent = learn.toFixed(1) + '%';
    learnEl.style.color = Math.abs(learn) > 10 ? '#ff6d00' : '#ffffff';

    // IAT
    const iat = getChannelValue('iat');
    document.getElementById('value-iat').textContent = iat ? Math.round(iat) + ' °F' : '— °F';

    // Footer stats
    if (state.stats) {
        document.getElementById('stat-frames').textContent = 'Frames: ' + (state.stats.frames_decoded || 0).toLocaleString();
        document.getElementById('stat-channels').textContent = 'Channels: ' + (state.stats.channels_discovered || 0);
        document.getElementById('stat-errors').textContent = 'Errors: ' + (state.stats.error_frames || 0);
        const uptime = state.stats.uptime_s || 0;
        const hrs = Math.floor(uptime / 3600);
        const mins = Math.floor((uptime % 3600) / 60);
        const secs = Math.floor(uptime % 60);
        document.getElementById('stat-uptime').textContent = 'Uptime: ' + (hrs > 0 ? hrs + 'h ' : '') + mins + 'm ' + secs + 's';
    }

    // ECU info
    if (state.stats.ecu_serial_bits) {
        document.getElementById('ecu-info').textContent = 'ECU: 0x' + state.stats.ecu_serial_bits.toString(16).toUpperCase().padStart(3, '0');
    }

    // FPS counter
    document.getElementById('fps-counter').textContent = (state.stats.fps || 0) + ' FPS';

    // Clock
    const now = new Date();
    document.getElementById('clock').textContent =
        now.getHours().toString().padStart(2, '0') + ':' +
        now.getMinutes().toString().padStart(2, '0') + ':' +
        now.getSeconds().toString().padStart(2, '0');
}

// ─── Ping keep-alive ────────────────────────────────────────────────────────

setInterval(() => {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send('ping');
        state.ws.send('snapshot');  // Also request fresh stats
    }
}, 5000);

// ─── Diagnostic View Renderer ───────────────────────────────────────────────

function renderDiagnostics() {
    const listEl = document.getElementById('diag-list');
    if (!listEl) return;
    
    const sortedChannels = Object.keys(state.channels).sort();
    
    let html = '';
    for (const name of sortedChannels) {
        const ch = state.channels[name];
        const ageSecs = (Date.now() - (ch.timestamp * 1000)) / 1000.0;
        let ageText = ageSecs < 1.0 ? 'live' : `${ageSecs.toFixed(1)}s ago`;
        
        html += `
            <tr>
                <td><strong>${name}</strong></td>
                <td>${ch.label || name}</td>
                <td>${ch.value !== undefined ? ch.value.toFixed(2) : '—'}</td>
                <td>${ch.unit || ''}</td>
                <td style="color: ${ageSecs > 2.0 ? '#ff1744' : 'inherit'}">${ageText}</td>
            </tr>
        `;
    }
    listEl.innerHTML = html || '<tr><td colspan="5" style="text-align:center;">No ECU data received yet.</td></tr>';
}

// ─── Connection Watchdog ─────────────────────────────────────────────────────

function initWatchdog() {
    state.lastMessageTimestamp = Date.now();
    setInterval(() => {
        const overlay = document.getElementById('connection-overlay');
        if (!overlay) return;
        
        if (!state.connected || (Date.now() - state.lastMessageTimestamp) > CONFIG.watchdogTimeoutMs) {
            overlay.classList.remove('hidden');
        } else {
            overlay.classList.add('hidden');
        }
    }, 200);
}

// ─── Screen Wake Lock ────────────────────────────────────────────────────────

async function requestWakeLock() {
    if (!('wakeLock' in navigator)) {
        console.warn('Wake Lock API not supported in this browser');
        return;
    }
    
    try {
        state.wakeLock = await navigator.wakeLock.request('screen');
        console.log('Screen Wake Lock acquired');
        
        state.wakeLock.addEventListener('release', () => {
            console.log('Screen Wake Lock released');
        });
    } catch (err) {
        console.error(`Failed to acquire Wake Lock: ${err.name}, ${err.message}`);
    }
}

function handleVisibilityChange() {
    if (state.wakeLock !== null && document.visibilityState === 'visible') {
        requestWakeLock();
    }
}

document.addEventListener('visibilitychange', handleVisibilityChange);

// ─── Run Logger Management ──────────────────────────────────────────────────

function initLogger() {
    const logToggleBtn = document.getElementById('btn-log-toggle');
    const logStatusText = document.getElementById('log-status-text');
    const logListBtn = document.getElementById('btn-log-list');
    const modal = document.getElementById('logs-modal');
    const modalClose = document.getElementById('modal-close');
    
    if (!logToggleBtn) return;
    
    // Check initial logging status
    fetch('/api/log/status')
        .then(res => res.json())
        .then(data => {
            updateLoggerUI(data.logging, data.session);
        })
        .catch(err => console.error('Error fetching logger status:', err));
        
    logToggleBtn.addEventListener('click', () => {
        if (!state.logging) {
            // Start logging
            const runName = prompt('Enter a name for this run session:', `Run_${new Date().toISOString().slice(11, 19).replace(/:/g, '-')}`);
            if (runName === null) return; // user cancelled
            
            fetch(`/api/log/start?name=${encodeURIComponent(runName)}`, { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'success') {
                        updateLoggerUI(true, { name: data.name });
                    }
                })
                .catch(err => console.error('Error starting logger:', err));
        } else {
            // Stop logging
            fetch('/api/log/stop', { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'success') {
                        updateLoggerUI(false, null);
                        alert('Logging session stopped successfully.');
                    }
                })
                .catch(err => console.error('Error stopping logger:', err));
        }
    });
    
    logListBtn.addEventListener('click', () => {
        fetch('/api/log/sessions')
            .then(res => res.json())
            .then(data => {
                renderSessionsList(data.sessions);
                modal.classList.remove('hidden');
            })
            .catch(err => console.error('Error fetching sessions list:', err));
    });
    
    modalClose.addEventListener('click', () => {
        modal.classList.add('hidden');
    });
    
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.add('hidden');
        }
    });
}

function updateLoggerUI(isLogging, session) {
    state.logging = isLogging;
    const logToggleBtn = document.getElementById('btn-log-toggle');
    const logStatusText = document.getElementById('log-status-text');
    
    if (isLogging) {
        logToggleBtn.textContent = 'STOP';
        logToggleBtn.classList.remove('log-start');
        logToggleBtn.classList.add('log-active');
        logStatusText.textContent = `REC: ${session ? session.name : 'ACTIVE'}`;
        logStatusText.className = 'log-status-running';
    } else {
        logToggleBtn.textContent = 'REC';
        logToggleBtn.classList.remove('log-active');
        logToggleBtn.classList.add('log-start');
        logStatusText.textContent = 'IDLE';
        logStatusText.className = 'log-status-idle';
    }
}

function renderSessionsList(sessions) {
    const listEl = document.getElementById('sessions-list');
    if (!listEl) return;
    
    let html = '';
    for (const s of sessions) {
        const start = new Date(s.start_time * 1000);
        const dateStr = start.toLocaleString();
        
        let durationText = 'running';
        if (s.end_time) {
            const diff = s.end_time - s.start_time;
            const mins = Math.floor(diff / 60);
            const secs = Math.round(diff % 60);
            durationText = `${mins}m ${secs}s`;
        }
        
        html += `
            <tr>
                <td><strong>${s.name}</strong></td>
                <td>${dateStr}</td>
                <td>${durationText}</td>
                <td>
                    <a href="/api/log/export/${s.id}" class="download-link" target="_blank">Download CSV</a>
                </td>
            </tr>
        `;
    }
    listEl.innerHTML = html || '<tr><td colspan="4" style="text-align:center;">No sessions recorded yet.</td></tr>';
}

// ─── Theme Management ────────────────────────────────────────────────────────

function initTheme() {
    const toggleBtn = document.getElementById('btn-theme-toggle');
    if (!toggleBtn) return;
    
    applyTheme(state.theme);
    
    toggleBtn.addEventListener('click', () => {
        state.theme = state.theme === 'dark' ? 'light' : 'dark';
        localStorage.setItem('dashboard_theme', state.theme);
        applyTheme(state.theme);
    });
}

function applyTheme(theme) {
    const root = document.documentElement;
    if (theme === 'light') {
        root.setAttribute('data-theme', 'light');
        document.getElementById('btn-theme-toggle').textContent = '🌙';
    } else {
        root.removeAttribute('data-theme');
        document.getElementById('btn-theme-toggle').textContent = '☀️';
    }
}

// ─── Layout Management ───────────────────────────────────────────────────────

function initLayout() {
    const btnGrid = document.getElementById('btn-layout-grid');
    const btnTrack = document.getElementById('btn-layout-track');
    const btnDiag = document.getElementById('btn-layout-diag');
    
    if (!btnGrid) return;
    
    applyLayout(state.activeLayout);
    
    btnGrid.addEventListener('click', () => setLayout('grid'));
    btnTrack.addEventListener('click', () => setLayout('track'));
    btnDiag.addEventListener('click', () => setLayout('diag'));
}

function setLayout(layout) {
    state.activeLayout = layout;
    localStorage.setItem('dashboard_layout', layout);
    applyLayout(layout);
}

function applyLayout(layout) {
    document.querySelectorAll('.layout-section').forEach(el => {
        el.classList.add('hidden');
    });
    
    document.querySelectorAll('#btn-layout-grid, #btn-layout-track, #btn-layout-diag').forEach(el => {
        el.classList.remove('active');
    });
    
    if (layout === 'grid') {
        document.getElementById('gauge-grid').classList.remove('hidden');
        document.getElementById('btn-layout-grid').classList.add('active');
    } else if (layout === 'track') {
        document.getElementById('track-grid').classList.remove('hidden');
        document.getElementById('btn-layout-track').classList.add('active');
    } else if (layout === 'diag') {
        document.getElementById('diag-grid').classList.remove('hidden');
        document.getElementById('btn-layout-diag').classList.add('active');
        renderDiagnostics();
    }
}

// ─── Voice Alarm Toggle ──────────────────────────────────────────────────────

function initVoiceToggle() {
    const toggleBtn = document.getElementById('btn-voice-toggle');
    if (!toggleBtn) return;
    
    updateVoiceToggleUI();
    
    toggleBtn.addEventListener('click', () => {
        state.voiceEnabled = !state.voiceEnabled;
        localStorage.setItem('voice_alerts', state.voiceEnabled);
        updateVoiceToggleUI();
        
        if (state.voiceEnabled && window.speechSynthesis) {
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance("Voice alarms enabled");
            window.speechSynthesis.speak(utterance);
        }
    });
}

function updateVoiceToggleUI() {
    const toggleBtn = document.getElementById('btn-voice-toggle');
    if (state.voiceEnabled) {
        toggleBtn.textContent = '🔊';
        toggleBtn.classList.add('active');
    } else {
        toggleBtn.textContent = '🔇';
        toggleBtn.classList.remove('active');
    }
}

// ─── Init ───────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();
    state.renderInterval = setInterval(render, 1000 / CONFIG.renderFps);
    

    // Init settings and tablet enhancements
    initGrid();
    initGaugeSettings();
    initWatchdog();
    requestWakeLock();
    initTheme();
    initLayout();
    initVoiceToggle();
    initLogger();
});

// ─── Dynamic Grid Generation & Rendering ────────────────────────────────────

function loadGridConfig() {
    try {
        const saved = localStorage.getItem('dashboard_grid_config');
        if (saved) {
            gridConfig = JSON.parse(saved);
        } else {
            gridConfig = JSON.parse(JSON.stringify(DEFAULT_GRID_CONFIG));
        }
    } catch (e) {
        gridConfig = JSON.parse(JSON.stringify(DEFAULT_GRID_CONFIG));
    }
}

function saveGridConfig() {
    localStorage.setItem('dashboard_grid_config', JSON.stringify(gridConfig));
}

function initGrid() {
    loadGridConfig();
    const gridEl = document.getElementById('gauge-grid');
    if (!gridEl) return;
    
    gridEl.innerHTML = ''; // Clear
    
    gridConfig.forEach((cfg, index) => {
        const meta = CHANNEL_METADATA[cfg.channel] || { label: cfg.channel, unit: '' };
        let html = '';
        
        // Gauge outer card
        const isArc = cfg.type === 'arc';
        const isCompact = cfg.type.startsWith('compact');
        const cardClass = `gauge-card ${isArc ? 'gauge-rpm' : ''} ${isCompact ? 'gauge-compact' : ''}`;
        
        html += `<div class="${cardClass}" data-index="${index}" id="dyn-card-${index}">`;
        
        // Header
        html += `<div class="gauge-header">
            <span class="gauge-label">${meta.label}</span>
            ${!isCompact && meta.unit ? `<span class="gauge-unit" id="dyn-unit-${index}">${meta.unit}</span>` : ''}
        </div>`;
        
        // Body
        if (cfg.type === 'arc') {
            html += `<div class="gauge-body">
                <canvas id="dyn-canvas-${index}" width="480" height="260"></canvas>
                <div class="gauge-value-overlay">
                    <span id="dyn-val-${index}" class="gauge-value-large">0</span>
                </div>
            </div>`;
        } else if (cfg.type === 'radial') {
            html += `<div class="gauge-body">
                <canvas id="dyn-canvas-${index}" width="240" height="240"></canvas>
                <div class="gauge-value-overlay">
                    <span id="dyn-val-${index}" class="gauge-value-medium">0.0</span>
                    <span id="dyn-val-sec-${index}" class="gauge-value-secondary"></span>
                </div>
            </div>`;
        } else if (cfg.type === 'bar') {
            html += `<div class="gauge-body gauge-body-bar">
                <div class="bar-gauge-container">
                    <div id="dyn-bar-${index}" class="bar-gauge-fill"></div>
                    <div class="bar-gauge-markers">
                        <span>${meta.min}</span><span>${Math.round(meta.min + (meta.max - meta.min)*0.33)}</span><span>${Math.round(meta.min + (meta.max - meta.min)*0.66)}</span><span>${meta.max}</span>
                    </div>
                </div>
                <span id="dyn-val-${index}" class="gauge-value-medium bar-value">0</span>
            </div>`;
        } else if (cfg.type === 'compact-ring') {
            html += `<div class="gauge-body gauge-body-compact">
                <div class="progress-ring-container">
                    <svg viewBox="0 0 100 100" class="progress-ring">
                        <circle class="progress-ring-bg" cx="50" cy="50" r="42"/>
                        <circle id="dyn-ring-${index}" class="progress-ring-fill" cx="50" cy="50" r="42"/>
                    </svg>
                    <span id="dyn-val-${index}" class="ring-value">0</span>
                </div>
            </div>`;
        } else if (cfg.type === 'compact-gear') {
            html += `<div class="gauge-body gauge-body-compact">
                <div class="gear-display">
                    <span id="dyn-val-${index}" class="gear-number">N</span>
                    <span id="dyn-val-sec-${index}" class="tcc-status">TCC: —</span>
                </div>
            </div>`;
        } else if (cfg.type === 'compact-value') {
            html += `<div class="gauge-body gauge-body-compact">
                <span id="dyn-val-${index}" class="gauge-value-medium compact-value">0</span>
            </div>`;
        }
        
        html += `</div>`;
        
        // Convert html string to node
        const template = document.createElement('template');
        template.innerHTML = html.trim();
        const node = template.content.firstChild;
        
        // Attach Long Press Event Listeners
        attachLongPressEvents(node, index);
        
        gridEl.appendChild(node);
    });
    
    // Add "Add Gauge" button
    const addCard = document.createElement('div');
    addCard.className = 'gauge-card gauge-card-add';
    addCard.innerHTML = '<span class="gauge-card-add-icon">+</span>';
    addCard.addEventListener('click', () => {
        openGaugeSettings(-1); // -1 means new gauge
    });
    gridEl.appendChild(addCard);
}

function attachLongPressEvents(node, index) {
    let pressTimer;
    
    const startPress = (e) => {
        if(e.type === 'touchstart') {
            // e.preventDefault(); // Don't prevent default, lets scrolling work if moving
        }
        node.classList.add('gauge-long-press-active');
        pressTimer = window.setTimeout(() => {
            openGaugeSettings(index);
            // haptic feedback if available
            if (navigator.vibrate) navigator.vibrate(50);
        }, 750); // 750ms long press
    };
    
    const cancelPress = () => {
        clearTimeout(pressTimer);
        node.classList.remove('gauge-long-press-active');
    };
    
    node.addEventListener('mousedown', startPress);
    node.addEventListener('touchstart', startPress, {passive: true});
    
    node.addEventListener('mouseup', cancelPress);
    node.addEventListener('mouseleave', cancelPress);
    node.addEventListener('touchend', cancelPress);
    node.addEventListener('touchcancel', cancelPress);
    node.addEventListener('touchmove', cancelPress, {passive: true}); // cancel on scroll
}

function renderGrid() {
    gridConfig.forEach((cfg, idx) => {
        const meta = CHANNEL_METADATA[cfg.channel] || { label: cfg.channel, min: 0, max: 100, color: '#00e5ff' };
        const rawVal = getChannelValue(cfg.channel);
        const val = getAnimatedValue(cfg.channel, rawVal);
        
        if (cfg.type === 'arc') {
            drawArcGauge(`dyn-canvas-${idx}`, val, meta.min, meta.max, CONFIG.rpmRedline || meta.max * 0.85);
            const el = document.getElementById(`dyn-val-${idx}`);
            if(el) {
                el.textContent = Math.round(val).toLocaleString();
                el.style.color = val > (CONFIG.rpmRedline || meta.max * 0.85) ? '#ff1744' : '#ffffff';
            }
        } 
        else if (cfg.type === 'radial') {
            let displayVal = val;
            let displayColor = meta.color;
            let secText = '';
            
            // Special handling for Boost
            if (meta.isBoost) {
                const boostPsi = (val - 101.325) * 0.145038;
                displayVal = val; // Draw raw kPa
                if (boostPsi > 0) {
                    displayColor = '#00e676'; // green for boost
                } else {
                    displayColor = '#00e5ff'; // cyan for vac
                }
                document.getElementById(`dyn-val-${idx}`).textContent = boostPsi.toFixed(1) + ' psi';
                secText = val.toFixed(0) + ' kPa';
            } else if (cfg.channel.includes('afr')) {
                const targetAfr = getChannelValue('target_afr') || 14.7;
                const dev = Math.abs(val - targetAfr);
                displayColor = dev > 1.0 ? '#ff1744' : (dev > 0.5 ? '#ff6d00' : '#00e676');
                secText = `Target: ${targetAfr.toFixed(1)}`;
                document.getElementById(`dyn-val-${idx}`).textContent = val.toFixed(1);
            } else {
                document.getElementById(`dyn-val-${idx}`).textContent = val.toFixed(1);
            }
            
            drawRadialGauge(`dyn-canvas-${idx}`, displayVal, meta.min, meta.max, { color: displayColor, glowColor: displayColor + '33' });
            
            const secEl = document.getElementById(`dyn-val-sec-${idx}`);
            if (secEl) secEl.textContent = secText;
        }
        else if (cfg.type === 'bar') {
            const pct = clamp((val - meta.min) / (meta.max - meta.min) * 100, 0, 100);
            const bar = document.getElementById(`dyn-bar-${idx}`);
            if (bar) {
                bar.style.width = pct + '%';
                let stateClass = '';
                if (meta.warn && val > meta.warn) stateClass = ' warning';
                if (meta.danger && val > meta.danger) stateClass = ' danger';
                if (meta.warnLow && val < meta.warnLow) stateClass = ' warning';
                if (meta.dangerLow && val < meta.dangerLow) stateClass = ' danger';
                bar.className = 'bar-gauge-fill' + stateClass;
            }
            const valEl = document.getElementById(`dyn-val-${idx}`);
            if (valEl) {
                valEl.textContent = val.toFixed(1);
                if (meta.danger && val > meta.danger) valEl.style.color = '#ff1744';
                else if (meta.warn && val > meta.warn) valEl.style.color = '#ff6d00';
                else if (meta.dangerLow && val < meta.dangerLow) valEl.style.color = '#ff1744';
                else if (meta.warnLow && val < meta.warnLow) valEl.style.color = '#ff6d00';
                else valEl.style.color = '#ffffff';
            }
        }
        else if (cfg.type === 'compact-ring') {
            const pct = clamp((val - meta.min) / (meta.max - meta.min) * 100, 0, 100);
            const circ = 2 * Math.PI * 42;
            const offset = circ * (1 - (pct / 100));
            const ring = document.getElementById(`dyn-ring-${idx}`);
            if (ring) {
                ring.style.strokeDasharray = circ;
                ring.style.strokeDashoffset = offset;
                ring.style.stroke = pct > 90 ? '#ff6d00' : '#00e5ff';
            }
            const valEl = document.getElementById(`dyn-val-${idx}`);
            if (valEl) valEl.textContent = Math.round(val) + (meta.unit || '');
        }
        else if (cfg.type === 'compact-gear') {
            const gearNames = { 0: 'N', 1: '1', 2: '2', 3: '3', 4: '4' };
            const gearEl = document.getElementById(`dyn-val-${idx}`);
            if (gearEl) {
                gearEl.textContent = gearNames[Math.round(val)] || 'N';
                gearEl.style.color = val > 0 ? '#00e5ff' : '#5f6368';
            }
            const tcc = getChannelValue('tcc_status');
            const secEl = document.getElementById(`dyn-val-sec-${idx}`);
            if (secEl) secEl.textContent = tcc > 50 ? 'TCC: LOCKED' : 'TCC: OPEN';
        }
        else if (cfg.type === 'compact-value') {
            const valEl = document.getElementById(`dyn-val-${idx}`);
            if (valEl) {
                valEl.textContent = val.toFixed(1) + ' ' + (meta.unit || '');
            }
        }
    });
}

// ─── Gauge Settings Modal ───────────────────────────────────────────────────

function initGaugeSettings() {
    const modal = document.getElementById('gauge-settings-modal');
    const closeBtn = document.getElementById('gauge-settings-close');
    const saveBtn = document.getElementById('btn-save-gauge');
    const deleteBtn = document.getElementById('btn-delete-gauge');
    const leftBtn = document.getElementById('btn-move-left');
    const rightBtn = document.getElementById('btn-move-right');
    const channelSelect = document.getElementById('setting-channel');
    
    // Populate select
    Object.keys(CHANNEL_METADATA).forEach(key => {
        const opt = document.createElement('option');
        opt.value = key;
        opt.textContent = CHANNEL_METADATA[key].label;
        channelSelect.appendChild(opt);
    });
    
    closeBtn.addEventListener('click', () => modal.classList.add('hidden'));
    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.classList.add('hidden');
    });
    
    saveBtn.addEventListener('click', () => {
        const idx = parseInt(document.getElementById('setting-gauge-index').value);
        const channel = document.getElementById('setting-channel').value;
        const type = document.getElementById('setting-type').value;
        
        if (idx === -1) {
            // New gauge
            gridConfig.push({ channel, type });
        } else {
            // Edit existing
            gridConfig[idx].channel = channel;
            gridConfig[idx].type = type;
        }
        
        saveGridConfig();
        initGrid();
        modal.classList.add('hidden');
    });
    
    deleteBtn.addEventListener('click', () => {
        const idx = parseInt(document.getElementById('setting-gauge-index').value);
        if (idx >= 0) {
            gridConfig.splice(idx, 1);
            saveGridConfig();
            initGrid();
            modal.classList.add('hidden');
        }
    });
    
    leftBtn.addEventListener('click', () => {
        const idx = parseInt(document.getElementById('setting-gauge-index').value);
        if (idx > 0) {
            const temp = gridConfig[idx - 1];
            gridConfig[idx - 1] = gridConfig[idx];
            gridConfig[idx] = temp;
            saveGridConfig();
            initGrid();
            document.getElementById('setting-gauge-index').value = idx - 1;
        }
    });
    
    rightBtn.addEventListener('click', () => {
        const idx = parseInt(document.getElementById('setting-gauge-index').value);
        if (idx >= 0 && idx < gridConfig.length - 1) {
            const temp = gridConfig[idx + 1];
            gridConfig[idx + 1] = gridConfig[idx];
            gridConfig[idx] = temp;
            saveGridConfig();
            initGrid();
            document.getElementById('setting-gauge-index').value = idx + 1;
        }
    });
}

function openGaugeSettings(index) {
    const modal = document.getElementById('gauge-settings-modal');
    document.getElementById('setting-gauge-index').value = index;
    
    const isNew = index === -1;
    document.getElementById('btn-delete-gauge').style.display = isNew ? 'none' : 'block';
    document.getElementById('btn-move-left').disabled = isNew || index === 0;
    document.getElementById('btn-move-right').disabled = isNew || index === gridConfig.length - 1;
    
    if (!isNew) {
        const cfg = gridConfig[index];
        document.getElementById('setting-channel').value = cfg.channel;
        document.getElementById('setting-type').value = cfg.type;
    } else {
        document.getElementById('setting-channel').value = 'oil_pressure';
        document.getElementById('setting-type').value = 'radial';
    }
    
    modal.classList.remove('hidden');
}
