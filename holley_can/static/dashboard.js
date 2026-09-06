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
    isEditingLayout: false,
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

const DEFAULT_LAYOUTS = [
    {
        id: 'layout_grid',
        name: 'GRID',
        gauges: [
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
        ]
    },
    {
        id: 'layout_track',
        name: 'TRACK',
        gauges: [
            { type: 'track-large', channel: 'rpm' },
            { type: 'track-large', channel: 'map_kpa' },
            { type: 'track-large', channel: 'afr_avg' }
        ]
    }
];

let layouts = [];
let activeLayoutId = 'layout_grid';
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
                updateLiveHardwareStats(msg.stats);
            }
            break;

        case 'update':
            // Incremental channel updates
            if (msg.channels) {
                for (const [name, data] of Object.entries(msg.channels)) {
                    state.channels[name] = data;
                }
            }
            if (msg.stats) {
                state.stats = msg.stats;
                updateLiveHardwareStats(msg.stats);
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
                updateLiveHardwareStats(msg.stats);
            }
            break;

        case 'pong':
            break;
    }
}

// ─── Connection Status ──────────────────────────────────────────────────────

function updateConnectionStatus(connected) {
    const el = document.getElementById('connection-status');
    if (!el) return;
    const textEl = el.querySelector('.status-text');
    el.classList.toggle('connected', connected);
    el.classList.toggle('disconnected', !connected);
    if (connected) {
        if (textEl) textEl.textContent = 'LIVE';
        el.setAttribute('data-tooltip-title', 'ECU LINK: LIVE');
        el.setAttribute('data-tooltip-desc', 'CAN bus streaming active. Click to view live transceiver diagnostics, frame stats, and adapter details.');
    } else {
        if (textEl) textEl.textContent = 'CONNECT';
        el.setAttribute('data-tooltip-title', 'CONNECT TO ECU');
        el.setAttribute('data-tooltip-desc', 'Transceiver offline or no CAN traffic. Click to probe adapters, attempt connection, and open diagnostics.');
    }
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

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/[&<>'"]/g, tag => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;'
    }[tag] || tag));
}

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
        
        const hwModal = document.getElementById('hardware-modal');
        const modalOpen = hwModal && !hwModal.classList.contains('hidden');

        if ((!state.connected || (Date.now() - state.lastMessageTimestamp) > CONFIG.watchdogTimeoutMs) && !modalOpen) {
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

function showToast(message, type = 'info', durationMs = 3500) {
    let toast = document.getElementById('dashboard-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'dashboard-toast';
        toast.className = 'dashboard-toast';
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.className = `dashboard-toast ${type} show`;
    clearTimeout(toast._timeout);
    toast._timeout = setTimeout(() => {
        toast.className = 'dashboard-toast';
    }, durationMs);
}

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
            // Instant 1-Click Recording: generate timestamped run name
            const now = new Date();
            const timeStr = `${String(now.getHours()).padStart(2, '0')}-${String(now.getMinutes()).padStart(2, '0')}-${String(now.getSeconds()).padStart(2, '0')}`;
            const runName = `Run_${timeStr}`;
            
            // Immediate optimistic UI update
            updateLoggerUI(true, { name: runName });
            showToast(`🔴 Telemetry recording started: ${runName}`, 'success');

            if (state.voiceEnabled && window.speechSynthesis) {
                window.speechSynthesis.cancel();
                window.speechSynthesis.speak(new SpeechSynthesisUtterance("Telemetry recording started"));
            }

            fetch(`/api/log/start?name=${encodeURIComponent(runName)}`, { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'success') {
                        updateLoggerUI(true, { name: data.name });
                    } else {
                        updateLoggerUI(false, null);
                        showToast(`Failed to start recording: ${data.message || 'Error'}`, 'error');
                    }
                })
                .catch(err => {
                    console.error('Error starting logger:', err);
                    updateLoggerUI(false, null);
                    showToast('Error starting logger', 'error');
                });
        } else {
            // Stop logging immediately
            updateLoggerUI(false, null);
            showToast(`💾 Telemetry session saved. Click 'LOGS' to export CSV.`, 'success');

            if (state.voiceEnabled && window.speechSynthesis) {
                window.speechSynthesis.cancel();
                window.speechSynthesis.speak(new SpeechSynthesisUtterance("Recording stopped and saved"));
            }

            fetch('/api/log/stop', { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if (data.status !== 'success') {
                        console.warn('Stop logging response:', data);
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
        logToggleBtn.setAttribute('data-tooltip-title', 'STOP RECORDER');
        logToggleBtn.setAttribute('data-tooltip-desc', 'Click to stop the active recording session and flush telemetry frames to disk.');
        logStatusText.textContent = `REC: ${session ? session.name : 'ACTIVE'}`;
        logStatusText.className = 'log-status-running';
    } else {
        logToggleBtn.textContent = 'REC';
        logToggleBtn.classList.remove('log-active');
        logToggleBtn.classList.add('log-start');
        logToggleBtn.setAttribute('data-tooltip-title', 'RECORD TELEMETRY (REC)');
        logToggleBtn.setAttribute('data-tooltip-desc', 'Start recording high-resolution time-series data to the local SQLite database.');
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
                    <a href="/api/log/export/${s.id}" class="download-link" target="_blank"
                       data-tooltip-title="EXPORT TELEMETRY CSV"
                       data-tooltip-desc="Download full 50Hz high-speed CAN telemetry log as a CSV spreadsheet for MegaLogViewer or Excel.">Download CSV</a>
                </td>
            </tr>
        `;
    }
    listEl.innerHTML = html || '<tr><td colspan="4" style="text-align:center;">No sessions recorded yet.</td></tr>';
}

// ─── AI Copilot Drawer ("Ask Your Engine") ──────────────────────────────────

function formatMarkdown(text) {
    if (!text) return '';
    let html = text
        // Headers
        .replace(/^#### (.*$)/gim, '<h4>$1</h4>')
        .replace(/^### (.*$)/gim, '<h3>$1</h3>')
        .replace(/^## (.*$)/gim, '<h2>$1</h2>')
        // Bold
        .replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>')
        // Inline code
        .replace(/`([^`]+)`/gim, '<code>$1</code>');

    // Tables
    const tableRegex = /((?:\|[^\n]+\|\r?\n)+)/g;
    html = html.replace(tableRegex, (match) => {
        const rows = match.trim().split(/\r?\n/).filter(r => r.includes('|'));
        if (rows.length < 2) return match;
        let tableHtml = '<table>';
        rows.forEach((row, idx) => {
            if (row.includes('---')) return; // separator row
            const cells = row.split('|').slice(1, -1).map(c => c.trim());
            const tag = idx === 0 ? 'th' : 'td';
            tableHtml += '<tr>' + cells.map(c => `<${tag}>${c}</${tag}>`).join('') + '</tr>';
        });
        tableHtml += '</table>';
        return tableHtml;
    });

    // Lists
    html = html.replace(/^\s*-\s+(.*$)/gim, '<li>$1</li>');
    html = html.replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>');

    // Paragraphs
    const lines = html.split(/\n\n+/);
    html = lines.map(p => {
        p = p.trim();
        if (!p) return '';
        if (p.startsWith('<h') || p.startsWith('<table') || p.startsWith('<ul')) return p;
        return `<p>${p}</p>`;
    }).join('');

    return html;
}

function initCopilot() {
    const toggleBtn = document.getElementById('btn-copilot-toggle');
    const drawer = document.getElementById('copilot-drawer');
    const backdrop = document.getElementById('copilot-backdrop');
    const closeBtn = document.getElementById('copilot-close');
    const form = document.getElementById('copilot-form');
    const input = document.getElementById('copilot-input');
    const submitBtn = document.getElementById('copilot-submit');
    const messagesEl = document.getElementById('copilot-messages');
    const chipsEl = document.getElementById('copilot-chips');

    if (!toggleBtn || !drawer) return;

    function openDrawer() {
        drawer.classList.remove('hidden');
        if (backdrop) backdrop.classList.remove('hidden');
        toggleBtn.classList.add('active');
        updateContextStrip();
        if (input) input.focus();
    }

    function closeDrawer() {
        drawer.classList.add('hidden');
        if (backdrop) backdrop.classList.add('hidden');
        toggleBtn.classList.remove('active');
    }

    toggleBtn.addEventListener('click', () => {
        if (drawer.classList.contains('hidden')) {
            openDrawer();
        } else {
            closeDrawer();
        }
    });

    if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
    if (backdrop) backdrop.addEventListener('click', closeDrawer);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !drawer.classList.contains('hidden')) {
            closeDrawer();
        }
    });

    // Update Context Strip with live numbers
    function updateContextStrip() {
        const rpm = getChannelValue('rpm');
        const afr = getChannelValue('afr_avg');
        const mapKpa = getChannelValue('map_kpa');
        const learn = getChannelValue('current_learn');
        const clt = getChannelValue('coolant_temp');

        const rpmEl = document.getElementById('copilot-ctx-rpm');
        const afrEl = document.getElementById('copilot-ctx-afr');
        const mapEl = document.getElementById('copilot-ctx-map');
        const learnEl = document.getElementById('copilot-ctx-learn');
        const cltEl = document.getElementById('copilot-ctx-clt');

        if (rpmEl) rpmEl.textContent = rpm ? Math.round(rpm) : '—';
        if (afrEl) afrEl.textContent = afr ? afr.toFixed(2) : '—';
        if (mapEl) mapEl.textContent = mapKpa ? mapKpa.toFixed(1) + ' kPa' : '—';
        if (learnEl) learnEl.textContent = learn !== undefined ? `${learn > 0 ? '+' : ''}${learn.toFixed(1)}%` : '—';
        if (cltEl) cltEl.textContent = clt ? Math.round(clt) + '°F' : '—';
    }

    // Refresh context strip every second while drawer is open
    setInterval(() => {
        if (drawer && !drawer.classList.contains('hidden')) {
            updateContextStrip();
        }
    }, 1000);

    // Quick Chips click handler
    if (chipsEl) {
        chipsEl.addEventListener('click', (e) => {
            const chip = e.target.closest('.copilot-chip');
            if (!chip) return;
            const query = chip.getAttribute('data-query');
            if (query) {
                if (input) input.value = query;
                askQuestion(query);
            }
        });
    }

    // Form submit handler
    if (form) {
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const q = input.value.trim();
            if (!q) return;
            askQuestion(q);
        });
    }

    async function askQuestion(question) {
        if (!question || !messagesEl) return;

        // 1. Add User Message
        const now = new Date();
        const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        const userMsg = document.createElement('div');
        userMsg.className = 'copilot-msg user';
        userMsg.innerHTML = `
            <div class="msg-author">
                <span class="author-name">YOU</span>
                <span class="author-time">${timeStr}</span>
            </div>
            <div class="msg-content">${escapeHtml(question)}</div>
        `;
        messagesEl.appendChild(userMsg);

        // 2. Clear input & disable button
        if (input) input.value = '';
        if (submitBtn) submitBtn.disabled = true;

        // 3. Add Thinking Message
        const thinkingMsg = document.createElement('div');
        thinkingMsg.className = 'copilot-msg assistant thinking-msg';
        thinkingMsg.innerHTML = `
            <div class="msg-author">
                <span class="author-icon">⚡</span>
                <span class="author-name">EFI INTELLIGENCE COPILOT</span>
                <span class="author-time">ANALYZING...</span>
            </div>
            <div class="msg-content" style="color: var(--accent-cyan); font-style: italic;">
                Analyzing live CAN broadcast channels and diagnostic baselines...
            </div>
        `;
        messagesEl.appendChild(thinkingMsg);
        messagesEl.scrollTop = messagesEl.scrollHeight;

        // 4. Fetch Response from API
        try {
            const res = await fetch('/api/copilot/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question }),
            });
            const data = await res.json();
            thinkingMsg.remove();

            const answerMsg = document.createElement('div');
            answerMsg.className = 'copilot-msg assistant';
            answerMsg.innerHTML = `
                <div class="msg-author">
                    <span class="author-icon">⚡</span>
                    <span class="author-name">EFI INTELLIGENCE COPILOT</span>
                    <span class="author-time">${timeStr}</span>
                </div>
                <div class="msg-content">${formatMarkdown(data.answer || data.error || 'No telemetry analysis available.')}</div>
            `;
            messagesEl.appendChild(answerMsg);
            messagesEl.scrollTop = messagesEl.scrollHeight;

            // Optional Voice synthesis if voice alerts enabled
            if (state.voiceEnabled && window.speechSynthesis && data.telemetry) {
                const verbalText = `Engine at ${data.telemetry.rpm} RPM. AFR is ${data.telemetry.afr}. ${data.telemetry.active_alerts > 0 ? data.telemetry.active_alerts + ' active alarms' : 'All systems normal'}.`;
                const utterance = new SpeechSynthesisUtterance(verbalText);
                utterance.rate = 1.05;
                window.speechSynthesis.speak(utterance);
            }
        } catch (err) {
            thinkingMsg.remove();
            const errorMsg = document.createElement('div');
            errorMsg.className = 'copilot-msg assistant';
            errorMsg.innerHTML = `
                <div class="msg-author">
                    <span class="author-icon">⚠</span>
                    <span class="author-name">COPILOT ERROR</span>
                    <span class="author-time">${timeStr}</span>
                </div>
                <div class="msg-content" style="color: var(--accent-red);">
                    Failed to reach Copilot diagnostic service: ${escapeHtml(err.message)}
                </div>
            `;
            messagesEl.appendChild(errorMsg);
            messagesEl.scrollTop = messagesEl.scrollHeight;
        } finally {
            if (submitBtn) submitBtn.disabled = false;
        }
    }

}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/[&<>'"]/g, tag => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;'
    }[tag] || tag));
}

// ─── Hardware Link & Bus Diagnostics Modal ──────────────────────────────────

function updateLiveHardwareStats(stats) {
    if (!stats) return;
    const hwModal = document.getElementById('hardware-modal');
    if (hwModal && !hwModal.classList.contains('hidden')) {
        const framesEl = document.getElementById('hw-stat-frames');
        const errorsEl = document.getElementById('hw-stat-errors');
        if (framesEl && stats.frames_decoded !== undefined) {
            framesEl.textContent = Number(stats.frames_decoded).toLocaleString();
        }
        if (errorsEl && stats.error_frames !== undefined) {
            errorsEl.textContent = Number(stats.error_frames).toLocaleString();
        }
    }
}

async function refreshHardwareDiagnostics() {
    const statusEl = document.getElementById('hw-probe-status');
    const ifaceEl = document.getElementById('hw-stat-interface');
    const bitrateEl = document.getElementById('hw-stat-bitrate');
    const stateEl = document.getElementById('hw-stat-state');
    const ecuEl = document.getElementById('hw-stat-ecu');
    const framesEl = document.getElementById('hw-stat-frames');
    const errorsEl = document.getElementById('hw-stat-errors');
    const adaptersContainer = document.getElementById('hw-adapters-container');

    // 1. Fetch live transceiver status from API
    try {
        const statusRes = await fetch('/api/hardware/status');
        if (statusRes.ok) {
            const data = await statusRes.json();
            if (ifaceEl) ifaceEl.textContent = `${data.interface || '—'} (${data.channel || 'default'})`;
            if (bitrateEl) bitrateEl.textContent = `${(data.bitrate || 1000000).toLocaleString()} baud (1 Mbps)`;
            if (stateEl) {
                const isLive = data.is_running && state.connected;
                stateEl.textContent = isLive ? 'STREAMING' : (data.is_running ? 'LISTENING (WAITING FOR FRAMES)' : 'STANDBY');
                stateEl.style.color = isLive ? 'var(--accent-green)' : (data.is_running ? 'var(--accent-amber)' : 'var(--accent-red)');
            }
            if (ecuEl) {
                ecuEl.textContent = data.ecu_serial 
                    ? `0x${Number(data.ecu_serial).toString(16).toUpperCase()} (Terminator X)`
                    : (state.connected ? '0x1A5 (Terminator X)' : 'Not detected (Key OFF)');
            }
            if (data.stats) {
                if (framesEl && data.stats.frames_decoded !== undefined) {
                    framesEl.textContent = Number(data.stats.frames_decoded).toLocaleString();
                }
                if (errorsEl && data.stats.error_frames !== undefined) {
                    errorsEl.textContent = Number(data.stats.error_frames).toLocaleString();
                }
            }
        }
    } catch (e) {
        console.warn('Failed to fetch hardware status:', e);
    }

    // 2. Fetch discovered physical/virtual adapters
    try {
        const adaptersRes = await fetch('/api/hardware/adapters');
        if (adaptersRes.ok) {
            const data = await adaptersRes.json();
            if (adaptersContainer && data.adapters) {
                if (!Array.isArray(data.adapters) || data.adapters.length === 0) {
                    adaptersContainer.innerHTML = '<div class="hw-loading">No physical USB-CAN adapters detected on host system. Check USB cable and drivers.</div>';
                } else {
                    let html = '';
                    for (const ad of data.adapters) {
                        const isCurrent = (ad.channel === data.current_channel || ad.name === data.current_interface);
                        const badgeClass = isCurrent ? 'hw-badge-active' : (ad.available ? 'hw-badge-avail' : 'hw-badge-unavail');
                        const badgeText = isCurrent ? 'ACTIVE BUS' : (ad.available ? 'AVAILABLE' : 'OFFLINE');
                        const icon = (ad.adapter_type === 'pcan' || String(ad.name).includes('PCAN')) ? '🔌' : 
                                     (ad.adapter_type === 'slcan' || String(ad.name).includes('COM')) ? '📟' : 
                                     (ad.adapter_type === 'socketcan') ? '🐧' : '💻';
                        html += `
                            <div class="hw-adapter-item">
                                <div class="hw-adapter-left">
                                    <span style="font-size: 16px;">${icon}</span>
                                    <div>
                                        <strong>${escapeHtml(ad.name || ad.channel || 'CAN Interface')}</strong>
                                        <div style="font-size: 10px; color: var(--text-dim);">${escapeHtml(ad.adapter_type ? ad.adapter_type.toUpperCase() : 'DRIVER')} &bull; ${escapeHtml(ad.description || ad.channel || 'Host Interface')}</div>
                                    </div>
                                </div>
                                <span class="hw-adapter-badge ${badgeClass}">${badgeText}</span>
                            </div>
                        `;
                    }
                    adaptersContainer.innerHTML = html;
                }
            }
        }
    } catch (e) {
        console.warn('Failed to fetch adapters:', e);
        if (adaptersContainer) {
            adaptersContainer.innerHTML = '<div class="hw-loading" style="color: var(--accent-red);">Host adapter scan error</div>';
        }
    }
}

async function reconnectHardware(btnEl) {
    const statusEl = document.getElementById('hw-probe-status');
    const reconnectLabel = document.getElementById('hw-reconnect-label');
    if (statusEl) statusEl.textContent = 'Probing CAN hardware adapters...';
    if (reconnectLabel) reconnectLabel.textContent = 'Probing...';
    if (btnEl) btnEl.disabled = true;

    showToast('⚡ Probing CAN hardware transceivers...', 'info');

    // Reset WebSocket reconnect state and retry immediate connection
    state.reconnectAttempts = 0;
    if (!state.connected || !state.ws || state.ws.readyState !== WebSocket.OPEN) {
        connectWebSocket();
    }

    try {
        const res = await fetch('/api/hardware/reconnect', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') {
            showToast('✅ Hardware transceiver active', 'success');
            if (statusEl) statusEl.textContent = 'Transceiver probed and active';
        } else {
            showToast(`Hardware probe: ${data.message || 'Check adapters'}`, 'error');
            if (statusEl) statusEl.textContent = `Probe: ${data.message || 'Error'}`;
        }
    } catch (e) {
        console.warn('Hardware reconnect request failed:', e);
        if (statusEl) statusEl.textContent = 'Hardware probe request failed';
    } finally {
        if (reconnectLabel) reconnectLabel.textContent = 'Re-probe Bus & Connect';
        if (btnEl) btnEl.disabled = false;
        refreshHardwareDiagnostics();
    }
}

function initHardwareModal() {
    const connBtn = document.getElementById('connection-status');
    const modal = document.getElementById('hardware-modal');
    const closeBtn = document.getElementById('hardware-modal-close');
    const reconnectBtn = document.getElementById('btn-hardware-reconnect');
    const refreshBtn = document.getElementById('btn-hardware-refresh');
    const overlayReconnectBtn = document.getElementById('btn-overlay-reconnect');
    const overlayDiagBtn = document.getElementById('btn-overlay-diag');

    if (!modal) return;

    function openModal() {
        modal.classList.remove('hidden');
        refreshHardwareDiagnostics();
    }

    function closeModal() {
        modal.classList.add('hidden');
    }

    if (connBtn) {
        connBtn.addEventListener('click', () => {
            if (!state.connected) {
                // If disconnected, trigger immediate connection probe
                reconnectHardware(reconnectBtn);
            }
            openModal();
        });
    }

    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
            closeModal();
        }
    });

    if (reconnectBtn) {
        reconnectBtn.addEventListener('click', () => reconnectHardware(reconnectBtn));
    }

    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            const statusEl = document.getElementById('hw-probe-status');
            if (statusEl) statusEl.textContent = 'Scanning host interfaces...';
            refreshHardwareDiagnostics().then(() => {
                if (statusEl) statusEl.textContent = 'Scan complete';
            });
        });
    }

    if (overlayReconnectBtn) {
        overlayReconnectBtn.addEventListener('click', () => {
            reconnectHardware(reconnectBtn);
            openModal();
        });
    }

    if (overlayDiagBtn) {
        overlayDiagBtn.addEventListener('click', () => {
            openModal();
        });
    }
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
    const themeBtn = document.getElementById('btn-theme-toggle');
    if (theme === 'light') {
        root.setAttribute('data-theme', 'light');
        if (themeBtn) {
            themeBtn.textContent = '🌙';
            themeBtn.setAttribute('data-tooltip-title', 'SWITCH TO NIGHT THEME');
            themeBtn.setAttribute('data-tooltip-desc', 'Activate cyberpunk dark mode optimized for low-light dyno room and night track driving.');
        }
    } else {
        root.removeAttribute('data-theme');
        if (themeBtn) {
            themeBtn.textContent = '☀️';
            themeBtn.setAttribute('data-tooltip-title', 'SWITCH TO DAY THEME');
            themeBtn.setAttribute('data-tooltip-desc', 'Activate high-contrast bright theme optimized for direct sunlight in the paddock.');
        }
    }
}

// ─── Layout Management ───────────────────────────────────────────────────────

function populateLayoutSelector() {
    const sel = document.getElementById('layout-selector');
    if (!sel) return;
    
    sel.innerHTML = '';
    layouts.forEach(l => {
        const opt = document.createElement('option');
        opt.value = l.id;
        opt.textContent = l.name;
        sel.appendChild(opt);
    });
    
    const optNew = document.createElement('option');
    optNew.value = 'add_new';
    optNew.textContent = '+ New Layout...';
    sel.appendChild(optNew);
    
    sel.value = activeLayoutId;
}

function initLayout() {
    const sel = document.getElementById('layout-selector');
    const btnDiag = document.getElementById('btn-layout-diag');
    const btnEdit = document.getElementById('btn-edit-layout');
    
    if (!sel) return;
    
    const savedLayout = localStorage.getItem('dashboard_active_layout');
    if (savedLayout && layouts.find(l => l.id === savedLayout)) {
        activeLayoutId = savedLayout;
    }
    
    populateLayoutSelector();
    applyLayout(state.activeLayout);
    
    if (btnEdit) {
        btnEdit.addEventListener('click', () => {
            toggleEditMode();
        });
    }
    
    sel.addEventListener('change', (e) => {
        if (state.isEditingLayout) {
            toggleEditMode(false);
        }
        if (e.target.value === 'add_new') {
            const name = prompt("Enter name for new layout:");
            if (name && name.trim().length > 0) {
                const newId = 'layout_' + Date.now();
                layouts.push({ id: newId, name: name.trim(), gauges: [] });
                saveGridConfig();
                activeLayoutId = newId;
                localStorage.setItem('dashboard_active_layout', activeLayoutId);
                populateLayoutSelector();
                setLayout('grid'); // switch to grid rendering view
                initGrid();
            } else {
                e.target.value = activeLayoutId; // revert
            }
        } else {
            activeLayoutId = e.target.value;
            localStorage.setItem('dashboard_active_layout', activeLayoutId);
            setLayout('grid'); // always grid renderer for custom layouts
            initGrid();
        }
    });
    
    btnDiag.addEventListener('click', () => {
        if (state.isEditingLayout) {
            toggleEditMode(false);
        }
        setLayout('diag');
    });
}

function toggleEditMode(forceState) {
    state.isEditingLayout = (typeof forceState === 'boolean') ? forceState : !state.isEditingLayout;
    const btnEdit = document.getElementById('btn-edit-layout');
    const gridEl = document.getElementById('gauge-grid');
    
    if (btnEdit) {
        if (state.isEditingLayout) {
            btnEdit.textContent = '✓ DONE';
            btnEdit.classList.add('active', 'editing-active');
            btnEdit.setAttribute('data-tooltip-title', 'LOCK LAYOUT (DONE)');
            btnEdit.setAttribute('data-tooltip-desc', 'Exit layout customization mode and lock current gauge positions.');
        } else {
            btnEdit.textContent = 'EDIT';
            btnEdit.classList.remove('active', 'editing-active');
            btnEdit.setAttribute('data-tooltip-title', 'EDIT CLUSTER LAYOUT');
            btnEdit.setAttribute('data-tooltip-desc', 'Enable drag-and-drop mode to reposition, reconfigure, or add new telemetry tiles.');
        }
    }
    
    if (gridEl) {
        if (state.isEditingLayout) {
            gridEl.classList.add('edit-mode');
        } else {
            gridEl.classList.remove('edit-mode');
        }
    }
}

function setLayout(layoutType) {
    state.activeLayout = layoutType;
    applyLayout(layoutType);
}

function applyLayout(layoutType) {
    document.querySelectorAll('.layout-section').forEach(el => {
        el.classList.add('hidden');
    });
    const btnDiag = document.getElementById('btn-layout-diag');
    if (btnDiag) btnDiag.classList.remove('active');
    
    if (layoutType === 'grid') {
        document.getElementById('gauge-grid').classList.remove('hidden');
        if (btnDiag) {
            btnDiag.setAttribute('data-tooltip-title', 'DIAGNOSTIC VIEW');
            btnDiag.setAttribute('data-tooltip-desc', 'Toggle full high-density tabular view of all raw ECU CAN broadcast channels.');
        }
    } else if (layoutType === 'diag') {
        document.getElementById('diag-grid').classList.remove('hidden');
        if (btnDiag) {
            btnDiag.classList.add('active');
            btnDiag.setAttribute('data-tooltip-title', 'EXIT DIAGNOSTICS VIEW');
            btnDiag.setAttribute('data-tooltip-desc', 'Return to visual gauge dashboard.');
        }
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
    if (!toggleBtn) return;
    if (state.voiceEnabled) {
        toggleBtn.textContent = '🔊';
        toggleBtn.classList.add('active');
        toggleBtn.setAttribute('data-tooltip-title', 'VOICE ALERTS (ON)');
        toggleBtn.setAttribute('data-tooltip-desc', 'Click to mute synthesized speech warnings for engine alarms and critical faults.');
    } else {
        toggleBtn.textContent = '🔇';
        toggleBtn.classList.remove('active');
        toggleBtn.setAttribute('data-tooltip-title', 'VOICE ALERTS (MUTED)');
        toggleBtn.setAttribute('data-tooltip-desc', 'Click to enable spoken voice announcements when critical engine thresholds are breached.');
    }
}

// ─── Futuristic On-Hover Tooltip Manager ─────────────────────────────────────

function initTooltips() {
    let activeTarget = null;
    const tooltipEl = document.getElementById('custom-tooltip');
    if (!tooltipEl) return;

    const titleEl = tooltipEl.querySelector('.tooltip-title');
    const descEl = tooltipEl.querySelector('.tooltip-desc');
    const hintEl = tooltipEl.querySelector('.tooltip-hint');

    function showTooltip(target) {
        if (!target) return;
        const title = target.getAttribute('data-tooltip-title') || target.title || '';
        const desc = target.getAttribute('data-tooltip-desc') || '';
        const hint = target.getAttribute('data-tooltip-hint') || '';

        if (!title && !desc) return;

        // Suppress native browser tooltip by temporarily saving title
        if (target.title) {
            target.dataset.originalTitle = target.title;
            target.removeAttribute('title');
        }

        activeTarget = target;
        if (titleEl) titleEl.textContent = title;
        if (descEl) descEl.textContent = desc;
        if (hintEl) {
            hintEl.textContent = hint;
            hintEl.style.display = hint ? 'block' : 'none';
        }

        // Make visible and set display before calculating bounding box
        tooltipEl.style.display = 'block';
        tooltipEl.classList.add('visible');
        tooltipEl.setAttribute('aria-hidden', 'false');

        positionTooltip(target);
    }

    function positionTooltip(target) {
        if (!tooltipEl || !target) return;
        const rect = target.getBoundingClientRect();
        const tooltipRect = tooltipEl.getBoundingClientRect();
        const padding = 12;

        // Center horizontally above or below element
        let left = rect.left + (rect.width / 2) - (tooltipRect.width / 2);
        let top = rect.bottom + 8; // Default below target

        // If placed too close to bottom of viewport, flip to above
        if (top + tooltipRect.height > window.innerHeight - padding) {
            top = rect.top - tooltipRect.height - 8;
        }

        // If top is still negative, clamp to padding
        if (top < padding) top = padding;

        // Clamp horizontally so it never clips off screen edges
        if (left < padding) left = padding;
        if (left + tooltipRect.width > window.innerWidth - padding) {
            left = window.innerWidth - tooltipRect.width - padding;
        }

        tooltipEl.style.left = `${Math.round(left)}px`;
        tooltipEl.style.top = `${Math.round(top)}px`;
    }

    function hideTooltip() {
        if (activeTarget && activeTarget.dataset.originalTitle) {
            activeTarget.title = activeTarget.dataset.originalTitle;
            delete activeTarget.dataset.originalTitle;
        }
        activeTarget = null;
        if (tooltipEl) {
            tooltipEl.classList.remove('visible');
            tooltipEl.style.display = 'none';
            tooltipEl.setAttribute('aria-hidden', 'true');
        }
    }

    function handleEnter(e) {
        const target = e.target.closest('[data-tooltip-title], [data-tooltip-desc]');
        if (!target) return;
        if (activeTarget === target) return;
        showTooltip(target);
    }

    function handleLeave(e) {
        const target = e.target.closest('[data-tooltip-title], [data-tooltip-desc]');
        if (!target) return;
        if (!e.relatedTarget || !target.contains(e.relatedTarget)) {
            hideTooltip();
        }
    }

    // Event delegation for mouse & pointer hover
    document.addEventListener('mouseover', handleEnter, { passive: true });
    document.addEventListener('mouseout', handleLeave, { passive: true });
    document.addEventListener('pointerover', handleEnter, { passive: true });
    document.addEventListener('pointerout', handleLeave, { passive: true });

    // Keyboard accessibility
    document.addEventListener('focusin', handleEnter);
    document.addEventListener('focusout', handleLeave);

    // Dismiss on click, touch, or scroll
    document.addEventListener('click', () => hideTooltip());
    document.addEventListener('touchstart', () => hideTooltip(), { passive: true });
    window.addEventListener('scroll', () => hideTooltip(), true);
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
    initCopilot();
    initTooltips();
    initHardwareModal();
});

// ─── Dynamic Grid Generation & Rendering ────────────────────────────────────

function loadGridConfig() {
    try {
        const saved = localStorage.getItem('dashboard_layouts_v2');
        if (saved) {
            layouts = JSON.parse(saved);
        } else {
            layouts = JSON.parse(JSON.stringify(DEFAULT_LAYOUTS));
        }
    } catch (e) {
        layouts = JSON.parse(JSON.stringify(DEFAULT_LAYOUTS));
    }
}

function saveGridConfig() {
    localStorage.setItem('dashboard_layouts_v2', JSON.stringify(layouts));
}

function getActiveLayout() {
    return layouts.find(l => l.id === activeLayoutId) || layouts[0];
}

function initGrid() {
    loadGridConfig();
    const gridEl = document.getElementById('gauge-grid');
    if (!gridEl) return;
    
    gridEl.innerHTML = ''; // Clear
    
    if (state.isEditingLayout) {
        gridEl.classList.add('edit-mode');
    } else {
        gridEl.classList.remove('edit-mode');
    }
    
    const layout = getActiveLayout();
    
    layout.gauges.forEach((cfg, index) => {
        const meta = CHANNEL_METADATA[cfg.channel] || { label: cfg.channel, unit: '' };
        let html = '';
        
        // Gauge outer card
        const isArc = cfg.type === 'arc';
        const isCompact = cfg.type.startsWith('compact');
        const isTrack = cfg.type === 'track-large';
        const cardClass = `gauge-card ${isArc ? 'gauge-rpm' : ''} ${isCompact ? 'gauge-compact' : ''} ${isTrack ? 'track-card' : ''}`;
        
        html += `<div class="${cardClass}" data-index="${index}" id="dyn-card-${index}">`;
        
        // Header
        html += `<div class="gauge-header">
            <span class="gauge-label">${meta.label}</span>
            ${!isCompact && meta.unit ? `<span class="gauge-unit" id="dyn-unit-${index}">${meta.unit}</span>` : ''}
            <span class="gauge-drag-handle" data-tooltip-title="DRAG TO REPOSITION" data-tooltip-desc="Click and drag or touch to reorder this gauge tile on your telemetry cluster.">⠿</span>
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
        } else if (cfg.type === 'track-large') {
            html += `<div class="gauge-body">
                <span id="dyn-val-${index}" class="track-value-large" style="color: ${meta.color}">0</span>
            </div>`;
        }
        
        html += `</div>`;
        
        // Convert html string to node
        const template = document.createElement('template');
        template.innerHTML = html.trim();
        const node = template.content.firstChild;
        
        // Attach Event Listeners
        attachLongPressEvents(node, index);
        attachDragAndDropEvents(node, index);
        
        gridEl.appendChild(node);
    });
    
    // Add "Add Gauge" button
    const addCard = document.createElement('div');
    addCard.className = 'gauge-card gauge-card-add';
    addCard.setAttribute('data-tooltip-title', 'ADD CUSTOM GAUGE');
    addCard.setAttribute('data-tooltip-desc', 'Add a new telemetry tile (e.g. Oil Pressure, Fuel Pressure, Boost, Target AFR) to this dashboard layout.');
    addCard.innerHTML = '<span class="gauge-card-add-icon">+</span>';
    addCard.addEventListener('click', () => {
        openGaugeSettings(-1); // -1 means new gauge
    });
    gridEl.appendChild(addCard);
}

function attachLongPressEvents(node, index) {
    let pressTimer = null;
    
    const startPress = (e) => {
        // Never trigger long press if touching the drag handle or if in edit mode
        if (state.isEditingLayout || (e.target && e.target.closest('.gauge-drag-handle'))) return;
        node.classList.add('gauge-long-press-active');
        pressTimer = window.setTimeout(() => {
            openGaugeSettings(index);
            if (navigator.vibrate) navigator.vibrate(50);
        }, 750);
    };
    
    const cancelPress = () => {
        if (pressTimer) {
            clearTimeout(pressTimer);
            pressTimer = null;
        }
        node.classList.remove('gauge-long-press-active');
    };
    
    node._cancelLongPress = cancelPress;
    
    node.addEventListener('mousedown', startPress);
    node.addEventListener('touchstart', startPress, {passive: true});
    
    node.addEventListener('mouseup', cancelPress);
    node.addEventListener('mouseleave', cancelPress);
    node.addEventListener('touchend', cancelPress);
    node.addEventListener('touchcancel', cancelPress);
    node.addEventListener('touchmove', cancelPress, {passive: true});
}

function attachDragAndDropEvents(card, index) {
    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let offsetX = 0;
    let offsetY = 0;
    let startRect = null;
    let placeholder = null;
    let pointerId = null;
    let fromHandle = false;

    const onPointerDown = (e) => {
        fromHandle = !!(e.target && e.target.closest('.gauge-drag-handle'));

        // Allow drag if in edit mode OR if user grabbed the dedicated drag handle
        if (!state.isEditingLayout && !fromHandle) return;
        if (e.button !== 0 && e.pointerType === 'mouse') return;

        // Cancel any pending long press immediately
        if (card._cancelLongPress) card._cancelLongPress();

        pointerId = e.pointerId;
        startX = e.clientX;
        startY = e.clientY;
        startRect = card.getBoundingClientRect();
        offsetX = e.clientX - startRect.left;
        offsetY = e.clientY - startRect.top;

        // Lower movement threshold if grabbed directly by the handle for instant response
        const threshold = fromHandle ? 2 : 8;

        const onPointerMove = (moveEv) => {
            if (moveEv.pointerId !== pointerId) return;

            const dx = moveEv.clientX - startX;
            const dy = moveEv.clientY - startY;

            if (!isDragging && Math.hypot(dx, dy) > threshold) {
                isDragging = true;
                if (card._cancelLongPress) card._cancelLongPress();

                try {
                    card.setPointerCapture(pointerId);
                } catch (_) {}

                const gridEl = document.getElementById('gauge-grid');

                // Create placeholder
                placeholder = document.createElement('div');
                const isArc = card.classList.contains('gauge-rpm');
                const isCompact = card.classList.contains('gauge-compact');
                const isTrack = card.classList.contains('track-card');
                placeholder.className = `gauge-card gauge-drop-placeholder ${isArc ? 'gauge-rpm' : ''} ${isCompact ? 'gauge-compact' : ''} ${isTrack ? 'track-card' : ''}`;
                placeholder.style.height = `${startRect.height}px`;

                gridEl.insertBefore(placeholder, card.nextSibling);

                // Lift the card
                card.classList.add('is-dragging');
                card.style.width = `${startRect.width}px`;
                card.style.height = `${startRect.height}px`;
                card.style.left = `${moveEv.clientX - offsetX}px`;
                card.style.top = `${moveEv.clientY - offsetY}px`;

                if (navigator.vibrate) navigator.vibrate(30);
            }

            if (isDragging) {
                moveEv.preventDefault();
                card.style.left = `${moveEv.clientX - offsetX}px`;
                card.style.top = `${moveEv.clientY - offsetY}px`;

                // Find drop target card in grid
                const gridEl = document.getElementById('gauge-grid');
                const cards = Array.from(gridEl.querySelectorAll('.gauge-card:not(.is-dragging):not(.gauge-drop-placeholder):not(.gauge-card-add)'));

                for (const otherCard of cards) {
                    const rect = otherCard.getBoundingClientRect();
                    if (
                        moveEv.clientX >= rect.left &&
                        moveEv.clientX <= rect.right &&
                        moveEv.clientY >= rect.top &&
                        moveEv.clientY <= rect.bottom
                    ) {
                        const midX = rect.left + rect.width / 2;
                        const isAfter = moveEv.clientX > midX;

                        if (isAfter) {
                            if (otherCard.nextSibling !== placeholder) {
                                gridEl.insertBefore(placeholder, otherCard.nextSibling);
                            }
                        } else {
                            if (otherCard !== placeholder) {
                                gridEl.insertBefore(placeholder, otherCard);
                            }
                        }
                        break;
                    }
                }
            }
        };

        const onPointerUp = (upEv) => {
            if (upEv.pointerId !== pointerId) return;

            window.removeEventListener('pointermove', onPointerMove);
            window.removeEventListener('pointerup', onPointerUp);
            window.removeEventListener('pointercancel', onPointerUp);

            if (isDragging) {
                isDragging = false;
                try {
                    card.releasePointerCapture(pointerId);
                } catch (_) {}

                card.classList.remove('is-dragging');
                card.style.width = '';
                card.style.height = '';
                card.style.left = '';
                card.style.top = '';

                const gridEl = document.getElementById('gauge-grid');
                if (placeholder && placeholder.parentNode) {
                    gridEl.insertBefore(card, placeholder);
                    placeholder.remove();
                }

                // Read new order from DOM
                const currentCards = Array.from(gridEl.querySelectorAll('.gauge-card[data-index]'));
                const newIndices = currentCards.map(c => parseInt(c.getAttribute('data-index'), 10));

                const layout = getActiveLayout();
                const originalGauges = [...layout.gauges];
                layout.gauges = newIndices.map(idx => originalGauges[idx]);

                saveGridConfig();
                if (navigator.vibrate) navigator.vibrate([20, 30]);

                initGrid();
            } else {
                // If it was a quick tap in edit mode on the card body (NOT the handle), open settings
                if (state.isEditingLayout && !fromHandle) {
                    openGaugeSettings(index);
                }
            }
        };

        window.addEventListener('pointermove', onPointerMove, { passive: false });
        window.addEventListener('pointerup', onPointerUp);
        window.addEventListener('pointercancel', onPointerUp);
    };

    card.addEventListener('pointerdown', onPointerDown);
}

function renderGrid() {
    const layout = getActiveLayout();
    layout.gauges.forEach((cfg, idx) => {
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
            
            if (meta.isBoost) {
                const boostPsi = (val - 101.325) * 0.145038;
                displayVal = val;
                if (boostPsi > 0) displayColor = '#00e676';
                else displayColor = '#00e5ff';
                const el = document.getElementById(`dyn-val-${idx}`);
                if (el) el.textContent = boostPsi.toFixed(1) + ' psi';
                secText = val.toFixed(0) + ' kPa';
            } else if (cfg.channel.includes('afr')) {
                const targetAfr = getChannelValue('target_afr') || 14.7;
                const dev = Math.abs(val - targetAfr);
                displayColor = dev > 1.0 ? '#ff1744' : (dev > 0.5 ? '#ff6d00' : '#00e676');
                secText = `Target: ${targetAfr.toFixed(1)}`;
                const el = document.getElementById(`dyn-val-${idx}`);
                if(el) el.textContent = val.toFixed(1);
            } else {
                const el = document.getElementById(`dyn-val-${idx}`);
                if (el) el.textContent = val.toFixed(1);
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
        else if (cfg.type === 'track-large') {
            let displayVal = val.toFixed(1);
            let displayColor = meta.color;
            if (meta.isBoost) {
                const boostPsi = (val - 101.325) * 0.145038;
                displayVal = boostPsi.toFixed(1);
                if (boostPsi > 0) displayColor = '#00e676';
            } else if (cfg.channel === 'rpm') {
                displayVal = Math.round(val).toLocaleString();
            } else if (cfg.channel.includes('afr')) {
                const targetAfr = getChannelValue('target_afr') || 14.7;
                const dev = Math.abs(val - targetAfr);
                displayColor = dev > 1.0 ? '#ff1744' : (dev > 0.5 ? '#ff6d00' : '#00e676');
            }
            
            const valEl = document.getElementById(`dyn-val-${idx}`);
            if (valEl) {
                valEl.textContent = displayVal;
                valEl.style.color = displayColor;
            }
            // Update the unit for boost if needed
            if (meta.isBoost) {
                const unitEl = document.getElementById(`dyn-unit-${idx}`);
                if (unitEl) unitEl.textContent = 'psi';
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
    
    // Add delete layout button functionality
    const deleteLayoutBtn = document.createElement('button');
    deleteLayoutBtn.className = 'action-btn danger-btn';
    deleteLayoutBtn.textContent = 'Delete Layout';
    deleteLayoutBtn.style.marginTop = '12px';
    deleteLayoutBtn.addEventListener('click', () => {
        if (layouts.length <= 1) {
            alert("Cannot delete the last layout.");
            return;
        }
        if (confirm("Are you sure you want to delete this entire layout?")) {
            layouts = layouts.filter(l => l.id !== activeLayoutId);
            activeLayoutId = layouts[0].id;
            saveGridConfig();
            populateLayoutSelector();
            setLayout('grid');
            initGrid();
            modal.classList.add('hidden');
        }
    });
    document.querySelector('#gauge-settings-modal .form-body').appendChild(deleteLayoutBtn);
    
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
        const layout = getActiveLayout();
        const idx = parseInt(document.getElementById('setting-gauge-index').value);
        const channel = document.getElementById('setting-channel').value;
        const type = document.getElementById('setting-type').value;
        
        if (idx === -1) {
            layout.gauges.push({ channel, type });
        } else {
            layout.gauges[idx].channel = channel;
            layout.gauges[idx].type = type;
        }
        
        saveGridConfig();
        initGrid();
        modal.classList.add('hidden');
    });
    
    deleteBtn.addEventListener('click', () => {
        const layout = getActiveLayout();
        const idx = parseInt(document.getElementById('setting-gauge-index').value);
        if (idx >= 0) {
            layout.gauges.splice(idx, 1);
            saveGridConfig();
            initGrid();
            modal.classList.add('hidden');
        }
    });
    
    leftBtn.addEventListener('click', () => {
        const layout = getActiveLayout();
        const idx = parseInt(document.getElementById('setting-gauge-index').value);
        if (idx > 0) {
            const temp = layout.gauges[idx - 1];
            layout.gauges[idx - 1] = layout.gauges[idx];
            layout.gauges[idx] = temp;
            saveGridConfig();
            initGrid();
            document.getElementById('setting-gauge-index').value = idx - 1;
        }
    });
    
    rightBtn.addEventListener('click', () => {
        const layout = getActiveLayout();
        const idx = parseInt(document.getElementById('setting-gauge-index').value);
        if (idx >= 0 && idx < layout.gauges.length - 1) {
            const temp = layout.gauges[idx + 1];
            layout.gauges[idx + 1] = layout.gauges[idx];
            layout.gauges[idx] = temp;
            saveGridConfig();
            initGrid();
            document.getElementById('setting-gauge-index').value = idx + 1;
        }
    });
}

function openGaugeSettings(index) {
    const layout = getActiveLayout();
    const modal = document.getElementById('gauge-settings-modal');
    document.getElementById('setting-gauge-index').value = index;
    
    const isNew = index === -1;
    document.getElementById('btn-delete-gauge').style.display = isNew ? 'none' : 'block';
    document.getElementById('btn-move-left').disabled = isNew || index === 0;
    document.getElementById('btn-move-right').disabled = isNew || index === layout.gauges.length - 1;
    
    if (!isNew) {
        const cfg = layout.gauges[index];
        document.getElementById('setting-channel').value = cfg.channel;
        document.getElementById('setting-type').value = cfg.type;
    } else {
        document.getElementById('setting-channel').value = 'oil_pressure';
        document.getElementById('setting-type').value = 'radial';
    }
    
    modal.classList.remove('hidden');
}
