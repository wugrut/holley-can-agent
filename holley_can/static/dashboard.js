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
};

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
    // RPM
    const rpm = getAnimatedValue('rpm', getChannelValue('rpm'));
    drawArcGauge('gauge-rpm', rpm, 0, CONFIG.rpmMax, CONFIG.rpmRedline);
    const rpmEl = document.getElementById('value-rpm');
    rpmEl.textContent = Math.round(rpm).toLocaleString();
    rpmEl.style.color = rpm > CONFIG.rpmRedline ? '#ff1744' : '#ffffff';

    // MAP / Boost
    const mapKpa = getAnimatedValue('map_kpa', getChannelValue('map_kpa'));
    const boostPsi = (mapKpa - 101.325) * 0.145038;
    const mapColor = boostPsi > 0 ? '#00e676' : '#00e5ff';
    drawRadialGauge('gauge-map', mapKpa, 0, 300, { color: mapColor, glowColor: mapColor + '33' });
    document.getElementById('value-map').textContent = boostPsi > 0.5
        ? boostPsi.toFixed(1) + ' psi'
        : ((101.325 - mapKpa) * 0.295300).toFixed(1) + ' inHg';
    document.getElementById('value-map-secondary').textContent = mapKpa.toFixed(0) + ' kPa';

    // AFR
    const afr = getAnimatedValue('afr_avg', getChannelValue('afr_avg'));
    const targetAfr = getChannelValue('target_afr') || 14.7;
    const afrDeviation = Math.abs(afr - targetAfr);
    let afrColor = '#00e676';
    if (afrDeviation > 1.0) afrColor = '#ff1744';
    else if (afrDeviation > 0.5) afrColor = '#ff6d00';
    drawRadialGauge('gauge-afr', afr, 10, 20, {
        color: afrColor,
        glowColor: afrColor + '33',
        target: targetAfr,
    });
    const afrEl = document.getElementById('value-afr');
    afrEl.textContent = afr.toFixed(1);
    afrEl.style.color = afrColor;
    document.getElementById('value-afr-target').textContent = `Target: ${targetAfr.toFixed(1)}`;

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

// ─── Init ───────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();
    state.renderInterval = setInterval(render, 1000 / CONFIG.renderFps);
});
