/**
 * dashboard.js — Streamlined EFI Calibration & Gemini Copilot Studio
 * Target: 1980 Ford Fairmont 4.8L Turbo LS (Terminator X MAX)
 */

'use strict';

const state = {
    apiKey: localStorage.getItem('gemini_api_key') || '',
    activeDatalog: null,
    includeLearn: true,
    lastMatrixData: null,
    wsConnected: false,
};

// ─── Initialization ──────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    initKeyPanel();
    initCopilot();
    initOptimizer();
    initDropzone();
    initWebSocket();
    checkCopilotStatus();
});

// ─── Gemini Key Panel ───────────────────────────────────────────────────────

function initKeyPanel() {
    const toggleBtn = document.getElementById('btn-toggle-key-panel');
    const panel = document.getElementById('gemini-key-panel');
    const input = document.getElementById('input-gemini-key');
    const saveBtn = document.getElementById('btn-save-gemini-key');
    const closeBtn = document.getElementById('btn-close-key-panel');
    const statusEl = document.getElementById('key-save-status');

    if (input && state.apiKey) {
        input.value = state.apiKey;
    }

    if (toggleBtn && panel) {
        toggleBtn.addEventListener('click', () => {
            panel.classList.toggle('hidden');
            if (!panel.classList.contains('hidden') && input) {
                input.focus();
            }
        });
    }

    if (closeBtn && panel) {
        closeBtn.addEventListener('click', () => panel.classList.add('hidden'));
    }

    if (saveBtn && input) {
        saveBtn.addEventListener('click', async () => {
            const keyVal = input.value.trim();
            state.apiKey = keyVal;
            localStorage.setItem('gemini_api_key', keyVal);
            if (statusEl) statusEl.textContent = 'Validating and saving key...';

            try {
                const res = await fetch('/api/copilot/set_key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ api_key: keyVal }),
                });
                const data = await res.json();
                if (data.gemini_active) {
                    if (statusEl) statusEl.textContent = '✓ Gemini 2.5 connected and active!';
                    setTimeout(() => panel.classList.add('hidden'), 1200);
                } else {
                    if (statusEl) statusEl.textContent = 'Key saved. (Offline fallback ready)';
                }
                checkCopilotStatus();
            } catch (err) {
                if (statusEl) statusEl.textContent = 'Error: ' + err.message;
            }
        });
    }
}

async function checkCopilotStatus() {
    const pill = document.getElementById('gemini-status-pill');
    const pillText = document.getElementById('gemini-status-text');
    const modelBadge = document.getElementById('copilot-model-badge');

    try {
        const res = await fetch('/api/copilot/status');
        const data = await res.json();
        if (data.gemini_active) {
            if (pill) {
                pill.className = 'status-pill gemini-active';
                pillText.textContent = '✨ GEMINI ACTIVE';
            }
            if (modelBadge) modelBadge.textContent = 'Gemini 2.5 Flash';
        } else if (data.has_api_key) {
            if (pill) {
                pill.className = 'status-pill watcher';
                pillText.textContent = '✨ GEMINI READY';
            }
            if (modelBadge) modelBadge.textContent = 'Gemini 2.5 Flash';
        } else {
            if (pill) {
                pill.className = 'status-pill offline';
                pillText.textContent = '🛡️ OFFLINE ENGINE';
            }
            if (modelBadge) modelBadge.textContent = 'Offline Rule Engine';
        }
    } catch (e) {
        if (pill) {
            pill.className = 'status-pill offline';
            pillText.textContent = '🛡️ OFFLINE ENGINE';
        }
    }
}

// ─── Gemini Conversational Co-Driver ───────────────────────────────────────

function initCopilot() {
    const form = document.getElementById('chat-form');
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('btn-chat-send');
    const feed = document.getElementById('chat-feed');
    const chips = document.getElementById('prompt-chips');

    if (chips) {
        chips.addEventListener('click', (e) => {
            const btn = e.target.closest('.prompt-chip');
            if (!btn) return;
            const query = btn.getAttribute('data-query');
            if (query) {
                if (input) input.value = query;
                askQuestion(query);
            }
        });
    }

    if (form) {
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const q = input.value.trim();
            if (!q) return;
            askQuestion(q);
        });
    }

    async function askQuestion(question) {
        if (!question || !feed) return;

        const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        // Append User Bubble
        const userMsg = document.createElement('div');
        userMsg.className = 'chat-msg user';
        userMsg.innerHTML = `
            <div class="msg-header">
                <span class="msg-icon">👤</span>
                <strong class="msg-author">TUNER</strong>
                <span class="msg-time">${timeStr}</span>
            </div>
            <div class="msg-body"><p>${escapeHtml(question)}</p></div>
        `;
        feed.appendChild(userMsg);

        if (input) input.value = '';
        if (sendBtn) sendBtn.disabled = true;

        // Append Thinking Bubble
        const thinkingMsg = document.createElement('div');
        thinkingMsg.className = 'chat-msg thinking';
        thinkingMsg.innerHTML = `
            <div class="msg-header">
                <span class="msg-icon">✨</span>
                <strong class="msg-author">GEMINI REASONING</strong>
                <span class="msg-time">ANALYZING...</span>
            </div>
            <div class="msg-body"><p>Synthesizing telemetry, 1:1 fuel pressure delta, and 16×16 VE cells...</p></div>
        `;
        feed.appendChild(thinkingMsg);
        feed.scrollTop = feed.scrollHeight;

        try {
            const apiKey = localStorage.getItem('gemini_api_key') || '';
            const res = await fetch('/api/copilot/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    question,
                    api_key: apiKey,
                    datalog_path: state.activeDatalog ? state.activeDatalog.path : null,
                }),
            });
            const data = await res.json();
            thinkingMsg.remove();

            const isGemini = data.engine && data.engine.includes('gemini');
            const author = isGemini ? 'GEMINI 2.5 COPILOT' : 'EFI COPILOT (OFFLINE)';
            const icon = isGemini ? '✨' : '⚡';

            const assistantMsg = document.createElement('div');
            assistantMsg.className = 'chat-msg assistant';
            assistantMsg.innerHTML = `
                <div class="msg-header">
                    <span class="msg-icon">${icon}</span>
                    <strong class="msg-author">${author}</strong>
                    <span class="msg-time">${timeStr}</span>
                </div>
                <div class="msg-body">${formatMarkdown(data.answer || data.error || 'No analysis returned.')}</div>
            `;
            feed.appendChild(assistantMsg);
            feed.scrollTop = feed.scrollHeight;
        } catch (err) {
            thinkingMsg.remove();
            const errEl = document.createElement('div');
            errEl.className = 'chat-msg assistant';
            errEl.innerHTML = `
                <div class="msg-header">
                    <span class="msg-icon">⚠️</span>
                    <strong class="msg-author">ERROR</strong>
                    <span class="msg-time">${timeStr}</span>
                </div>
                <div class="msg-body" style="color: var(--accent-red);"><p>${escapeHtml(err.message)}</p></div>
            `;
            feed.appendChild(errEl);
            feed.scrollTop = feed.scrollHeight;
        } finally {
            if (sendBtn) sendBtn.disabled = false;
        }
    }

    // Expose askQuestion globally so file drop can prompt Gemini
    window.askQuestion = askQuestion;
}

// ─── Datalog Dropzone & Upload ──────────────────────────────────────────────

function initDropzone() {
    const dropzone = document.getElementById('datalog-dropzone');
    const fileInput = document.getElementById('datalog-file-input');
    const uploadTrigger = document.getElementById('btn-upload-datalog-trigger');

    if (uploadTrigger && fileInput) {
        uploadTrigger.addEventListener('click', () => fileInput.click());
    }

    if (dropzone && fileInput) {
        dropzone.addEventListener('click', () => fileInput.click());

        ['dragenter', 'dragover'].forEach(eventName => {
            dropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.add('drag-over');
            });
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.remove('drag-over');
            });
        });

        dropzone.addEventListener('drop', (e) => {
            const files = e.dataTransfer.files;
            if (files && files.length > 0) {
                handleFileUpload(files[0]);
            }
        });

        fileInput.addEventListener('change', (e) => {
            if (fileInput.files && fileInput.files.length > 0) {
                handleFileUpload(fileInput.files[0]);
            }
        });
    }

    async function handleFileUpload(file) {
        const nameEl = document.getElementById('active-log-name');
        const metaEl = document.getElementById('active-log-meta');
        if (nameEl) nameEl.textContent = `Uploading ${file.name}...`;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch('/api/datalog/upload', {
                method: 'POST',
                body: formData,
            });
            const data = await res.json();
            if (data.status === 'success') {
                state.activeDatalog = { filename: file.name, path: data.path };
                const summary = data.summary || {};
                const wot = summary.wot || {};

                if (nameEl) nameEl.textContent = `📄 ${file.name}`;
                if (metaEl) {
                    metaEl.textContent = `${summary.total_rows || 0} rows • Peak Boost: ${summary.peak_boost_psig || 0} PSI • WOT Samples: ${wot.wot_samples || 0}`;
                }

                // Render updated VE matrix
                if (data.matrix) {
                    renderVEMatrix(data.matrix);
                }

                // Automatically trigger Gemini evaluation of the uploaded log!
                if (window.askQuestion) {
                    window.askQuestion(`I just uploaded ${file.name}. Can you summarize this run, check my 1:1 fuel pressure delta, and explain if any VE or timing changes are needed?`);
                }
            } else {
                if (nameEl) nameEl.textContent = 'Upload failed';
                if (metaEl) metaEl.textContent = data.message || 'Unknown error';
            }
        } catch (err) {
            if (nameEl) nameEl.textContent = 'Upload error';
            if (metaEl) metaEl.textContent = err.message;
        }
    }
}

// ─── 16×16 Fuel VE Optimizer ────────────────────────────────────────────────

function initOptimizer() {
    const foldLearnCheck = document.getElementById('check-fold-learn');
    const copyVeHeader = document.getElementById('btn-copy-ve-header');
    const copyVeGrid = document.getElementById('btn-copy-ve-grid');
    const copyTrimGrid = document.getElementById('btn-copy-trim-grid');
    const resetBtn = document.getElementById('btn-reset-optimizer');

    if (foldLearnCheck) {
        foldLearnCheck.addEventListener('change', (e) => {
            state.includeLearn = e.target.checked;
            loadVEMatrix();
        });
    }

    if (copyVeHeader) copyVeHeader.addEventListener('click', () => copyVEToClipboard('ve'));
    if (copyVeGrid) copyVeGrid.addEventListener('click', () => copyVEToClipboard('ve'));
    if (copyTrimGrid) copyTrimGrid.addEventListener('click', () => copyVEToClipboard('trim'));

    if (resetBtn) {
        resetBtn.addEventListener('click', async () => {
            if (confirm('Reset 16×16 VE accumulator cells for a fresh tuning pass?')) {
                try {
                    const res = await fetch('/api/optimizer/reset', { method: 'POST' });
                    const data = await res.json();
                    renderVEMatrix(data.matrix);
                } catch (e) {
                    console.error('Reset error:', e);
                }
            }
        });
    }

    loadVEMatrix();
}

async function loadVEMatrix() {
    try {
        const res = await fetch(`/api/optimizer/matrix?include_learn=${state.includeLearn}`);
        const data = await res.json();
        renderVEMatrix(data);
    } catch (e) {
        console.warn('Could not load VE matrix:', e);
    }
}

function renderVEMatrix(data) {
    if (!data) return;
    state.lastMatrixData = data;

    // 1. Update Metrics Summary
    const samplesEl = document.getElementById('metric-samples');
    const cellsEl = document.getElementById('metric-cells');
    const leanEl = document.getElementById('metric-lean');
    const richEl = document.getElementById('metric-rich');
    const sourceEl = document.getElementById('metric-source');

    if (samplesEl) samplesEl.textContent = (data.total_samples || 0).toLocaleString();
    if (cellsEl) cellsEl.textContent = `${data.cells_populated || 0} / 256`;
    if (sourceEl) sourceEl.textContent = data.last_source || 'Documents\\Holley';

    // Count lean/rich trims
    let leanCount = 0;
    let richCount = 0;

    // 2. Render Scorecard Banner
    const scorecards = data.scorecards || [];
    const verdictEl = document.getElementById('scorecard-verdict');
    const badgeEl = document.getElementById('scorecard-badge');
    const detailsEl = document.getElementById('scorecard-details');

    if (scorecards.length > 0) {
        const latest = scorecards[scorecards.length - 1];
        if (verdictEl) verdictEl.textContent = latest.verdict || 'PULL COMPLETED';
        if (badgeEl) {
            badgeEl.textContent = `${latest.peak_boost_psi.toFixed(1)} PSI @ ${Math.round(latest.peak_rpm)} RPM`;
            badgeEl.className = latest.severity === 'danger' ? 'badge danger' : 'badge';
        }
        if (detailsEl) {
            detailsEl.innerHTML = `
                Avg AFR: <strong>${latest.avg_afr.toFixed(2)}</strong> (Target: ${latest.avg_target_afr.toFixed(2)}, Err: ${latest.afr_error > 0 ? '+' : ''}${latest.afr_error.toFixed(2)}) •
                Min Fuel PSI: <strong>${latest.min_fuel_psi.toFixed(1)}</strong> (Delta: ${latest.min_delta_psi.toFixed(1)} PSI) •
                Max Injector Duty: <strong>${latest.max_duty_pct.toFixed(1)}%</strong>
            `;
        }
    }

    // 3. Render 16×16 Table
    const thead = document.getElementById('ve-thead');
    const tbody = document.getElementById('ve-tbody');
    const matrix = data.matrix || [];

    if (!matrix || matrix.length === 0) return;

    // Render Table Header (MAP columns)
    if (thead) {
        const firstRow = matrix[0];
        let thHtml = '<tr><th>RPM \\ MAP</th>';
        firstRow.cells.forEach(cell => {
            const boostPsig = (cell.map_kpa - 101.325) * 0.145038;
            const boostStr = boostPsig > 0.5 ? `<br><span style="color:#00e5ff;font-size:9px;">+${boostPsig.toFixed(1)}#</span>` : '';
            thHtml += `<th>${cell.map_kpa}k${boostStr}</th>`;
        });
        thHtml += '</tr>';
        thead.innerHTML = thHtml;
    }

    // Render Table Body (RPM rows)
    if (tbody) {
        let trHtml = '';
        matrix.forEach((row, rIdx) => {
            trHtml += `<tr><th>${row.rpm}</th>`;
            row.cells.forEach((cell, cIdx) => {
                const hits = cell.hits || 0;
                const corr = cell.correction_pct || 0;
                const sug = cell.suggested_ve !== undefined ? cell.suggested_ve : cell.base_ve;

                let cellClass = 've-cell nodata';
                let corrText = '';

                if (hits >= 2) {
                    if (corr > 0.8) {
                        cellClass = 've-cell lean';
                        corrText = `<span class="ve-corr">+${corr.toFixed(1)}%</span>`;
                        leanCount++;
                    } else if (corr < -0.8) {
                        cellClass = 've-cell rich';
                        corrText = `<span class="ve-corr">${corr.toFixed(1)}%</span>`;
                        richCount++;
                    } else {
                        cellClass = 've-cell ok';
                        corrText = `<span class="ve-corr" style="color:#a0aec0;">0.0%</span>`;
                    }
                }

                trHtml += `
                    <td class="${cellClass}"
                        data-rpm="${row.rpm}"
                        data-map="${cell.map_kpa}"
                        data-base="${cell.base_ve}"
                        data-sug="${sug}"
                        data-corr="${corr.toFixed(2)}"
                        data-hits="${hits}"
                        data-cl="${(cell.cl_comp || 0).toFixed(1)}"
                        data-learn="${(cell.learn || 0).toFixed(1)}">
                        <span class="ve-val">${Math.round(sug)}</span>
                        ${corrText}
                    </td>
                `;
            });
            trHtml += '</tr>';
        });
        tbody.innerHTML = trHtml;
        initCellTooltips();
    }

    if (leanEl) leanEl.textContent = leanCount;
    if (richEl) richEl.textContent = richCount;
}

function initCellTooltips() {
    const tooltip = document.getElementById('cell-tooltip');
    const cells = document.querySelectorAll('.ve-cell');

    cells.forEach(c => {
        c.addEventListener('mouseenter', (e) => {
            if (!tooltip) return;
            const rpm = c.getAttribute('data-rpm');
            const map = c.getAttribute('data-map');
            const base = c.getAttribute('data-base');
            const sug = c.getAttribute('data-sug');
            const corr = c.getAttribute('data-corr');
            const hits = c.getAttribute('data-hits');
            const cl = c.getAttribute('data-cl');
            const learn = c.getAttribute('data-learn');

            const boostPsig = Math.max(0, (parseFloat(map) - 101.325) * 0.145038);

            tooltip.innerHTML = `
                <div style="font-weight:700; color:#00e5ff; margin-bottom:4px;">${rpm} RPM @ ${map} kPa (${boostPsig.toFixed(1)} PSI Boost)</div>
                <div>Suggested VE: <strong style="color:#00e676;">${sug}%</strong> (Base: ${base}%)</div>
                <div>Trim Correction: <strong>${corr}%</strong></div>
                <div>Closed-Loop: <strong>${cl}%</strong> • Learn: <strong>${learn}%</strong></div>
                <div>Steady-State Samples: <strong>${hits}</strong></div>
            `;
            tooltip.classList.remove('hidden');
        });

        c.addEventListener('mousemove', (e) => {
            if (!tooltip) return;
            tooltip.style.left = (e.clientX + 14) + 'px';
            tooltip.style.top = (e.clientY + 14) + 'px';
        });

        c.addEventListener('mouseleave', () => {
            if (tooltip) tooltip.classList.add('hidden');
        });
    });
}

async function copyVEToClipboard(type = 've') {
    if (!state.lastMatrixData) {
        alert('No VE matrix data available to copy.');
        return;
    }

    const tsv = type === 've'
        ? state.lastMatrixData.tsv_clipboard
        : state.lastMatrixData.tsv_corrections_clipboard;

    if (!tsv) {
        alert('Clipboard data empty.');
        return;
    }

    try {
        await navigator.clipboard.writeText(tsv);
        showToast('✓ Copied 16×16 Table to Clipboard! (Ctrl+V into Holley software)');
    } catch (err) {
        console.error('Clipboard copy failed:', err);
        showToast('Clipboard copy failed: ' + err.message);
    }
}

function showToast(msg) {
    const existing = document.getElementById('toast-notification');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.id = 'toast-notification';
    toast.style.cssText = `
        position: fixed;
        bottom: 24px;
        right: 24px;
        background: #00e676;
        color: #050a14;
        font-family: 'JetBrains Mono', monospace;
        font-weight: 700;
        font-size: 12px;
        padding: 10px 18px;
        border-radius: 6px;
        box-shadow: 0 4px 16px rgba(0, 230, 118, 0.4);
        z-index: 9999;
        animation: fadeIn 0.2s ease-out;
    `;
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2600);
}

// ─── Passive WebSocket ──────────────────────────────────────────────────────

function initWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws`;

    let ws = null;

    function connect() {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            state.wsConnected = true;
        };

        ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                // When datalogs auto-ingest or scorecard alerts arrive, reload VE table
                if (msg.alerts && msg.alerts.some(a => a.alert_type === 'post_pull_scorecard')) {
                    loadVEMatrix();
                }
            } catch (err) {
                // Ignore parse errors on ping/pong
            }
        };

        ws.onclose = () => {
            state.wsConnected = false;
            setTimeout(connect, 3000);
        };
    }

    connect();
}

// ─── Markdown Formatter ────────────────────────────────────────────────────

function formatMarkdown(text) {
    if (!text) return '';
    let html = escapeHtml(text);

    // Headings
    html = html.replace(/^### (.*$)/gim, '<h3 style="font-family:\'Orbitron\',sans-serif;font-size:13px;color:#00e5ff;margin:8px 0 4px;">$1</h3>');
    html = html.replace(/^## (.*$)/gim, '<h2 style="font-family:\'Orbitron\',sans-serif;font-size:14px;color:#fff;margin:10px 0 6px;">$1</h2>');
    html = html.replace(/^# (.*$)/gim, '<h1 style="font-family:\'Orbitron\',sans-serif;font-size:15px;color:#fff;margin:12px 0 8px;">$1</h1>');

    // Bold & Italic
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bullet points
    html = html.replace(/^\s*-\s+(.*$)/gim, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');

    // Paragraph breaks
    html = html.replace(/\n\n/g, '</p><p>');
    html = '<p>' + html + '</p>';

    return html;
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/[&<>'"]/g, tag => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;',
    }[tag] || tag));
}
