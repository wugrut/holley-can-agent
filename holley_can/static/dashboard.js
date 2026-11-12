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
    selectedCell: null,
    wsConnected: false,
    activeView: 'tuning',
    dashPreset: localStorage.getItem('holley_dash_active_preset') || 'drag',
    dashLayout: [],
    dashEditMode: false,
    channelCatalog: [],
    liveValues: {},
    gaugePeaks: {},
    historyBuffers: {},
    canPktCount: 0,
    canLastFpsTime: Date.now(),
    canFps: 0,
};

// ─── Initialization ──────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    initKeyPanel();
    initCopilot();
    initOptimizer();
    initHistory();
    initCellModal();
    initDropzone();
    initWebSocket();
    initLiveDashboard();
    checkCopilotStatus();
    updateWatcherStatus();
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

async function updateWatcherStatus() {
    const textEl = document.getElementById('log-status-text');
    const pill = document.getElementById('log-status-pill');
    try {
        const res = await fetch('/api/datalogs/discover');
        const data = await res.json();
        const dlCount = (data.datalogs || []).length;
        const tuneCount = (data.tunes || []).length;
        const roots = data.watched_roots || [];

        if (textEl) {
            textEl.textContent = `Auto-Watching (${dlCount} logs, ${tuneCount} tunes)`;
        }
        if (pill) {
            pill.title = `Actively watching on this machine:\n${roots.join('\n')}`;
        }
    } catch (e) {
        if (textEl) textEl.textContent = 'Auto-Watch Active';
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

    initTerxControls();
    loadVEMatrix();
}

function initTerxControls() {
    const toggleBtn = document.getElementById('btn-toggle-terx');
    const dropdown = document.getElementById('terx-dropdown');
    const browseBtn = document.getElementById('btn-browse-terx');
    const uploadInput = document.getElementById('input-upload-terx');
    const saveDirectBtn = document.getElementById('btn-save-terx-direct');

    if (toggleBtn && dropdown) {
        toggleBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const willOpen = dropdown.classList.contains('hidden');
            dropdown.classList.toggle('hidden');
            if (willOpen) loadTerxList();
        });

        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target) && e.target !== toggleBtn) {
                dropdown.classList.add('hidden');
            }
        });
    }

    if (browseBtn && uploadInput) {
        browseBtn.addEventListener('click', () => uploadInput.click());
        uploadInput.addEventListener('change', async () => {
            if (!uploadInput.files || uploadInput.files.length === 0) return;
            const file = uploadInput.files[0];
            const formData = new FormData();
            formData.append('file', file);
            try {
                showToast(`Uploading and validating ${file.name}...`);
                const res = await fetch('/api/terx/upload', {
                    method: 'POST',
                    body: formData,
                });
                const data = await res.json();
                if (data.status === 'success') {
                    renderVEMatrix(data.matrix);
                    showToast(`✓ Loaded calibration: ${data.filename} (CRC: ${data.calibration.stored_crc})`);
                    if (dropdown) dropdown.classList.add('hidden');
                } else {
                    alert('Failed to load .terx: ' + data.message);
                }
            } catch (err) {
                console.error('Upload error:', err);
                alert('Upload error: ' + err.message);
            }
        });
    }

    if (saveDirectBtn) {
        saveDirectBtn.addEventListener('click', async () => {
            try {
                saveDirectBtn.disabled = true;
                saveDirectBtn.textContent = '⏳ Saving .terx...';
                const res = await fetch('/api/terx/export', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ include_learn: state.includeLearn }),
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast(`✓ Exported verified tune: ${data.output_filename} (CRC: ${data.crc})!`);
                    // Trigger browser download
                    const dlLink = document.createElement('a');
                    dlLink.href = data.download_url;
                    dlLink.download = data.output_filename;
                    document.body.appendChild(dlLink);
                    dlLink.click();
                    document.body.removeChild(dlLink);
                } else {
                    alert('Export failed: ' + data.message);
                }
            } catch (err) {
                console.error('Save error:', err);
                alert('Save error: ' + err.message);
            } finally {
                saveDirectBtn.disabled = false;
                saveDirectBtn.textContent = '💾 Save Directly to .terx Tune';
            }
        });
    }
}

async function loadTerxList() {
    const listEl = document.getElementById('terx-list');
    if (!listEl) return;
    listEl.innerHTML = '<div style="padding:10px; color:#90caf9; font-size:11px;">Scanning system for .terx files...</div>';

    try {
        const res = await fetch('/api/terx/discover');
        const data = await res.json();
        const cals = data.calibrations || [];

        if (cals.length === 0) {
            listEl.innerHTML = '<div style="padding:10px; color:#888; font-size:11px;">No .terx files found on Desktop or Documents.</div>';
            return;
        }

        listEl.innerHTML = cals.map(c => {
            const isVerified = c.checksum_verified;
            const badge = isVerified 
                ? `<span style="color:#00e676; font-size:10px; font-weight:700;">✓ CRC ${c.crc || 'OK'}</span>`
                : `<span style="color:#ff5252; font-size:10px; font-weight:700;">⚠️ Checksum Mismatch</span>`;
            const comment = c.tune_comment ? `<div style="font-size:10px; color:#8899aa; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(c.tune_comment)}</div>` : '';

            return `
                <div class="history-item" style="cursor:default;">
                    <div class="history-item-info" style="flex:1; min-width:0;">
                        <span class="history-source" title="${escapeHtml(c.path)}" style="display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(c.filename)}</span>
                        ${comment}
                        <div style="font-size:10px; color:#607d8b;">${(c.filesize_bytes/1024).toFixed(0)} KB • ${badge}</div>
                    </div>
                    <button type="button" class="history-revert-btn btn-load-terx" data-path="${escapeHtml(c.path)}" style="align-self:center;">Load</button>
                </div>
            `;
        }).join('');

        listEl.querySelectorAll('.btn-load-terx').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const path = btn.getAttribute('data-path');
                try {
                    showToast(`Loading calibration: ${path}...`);
                    const res = await fetch('/api/terx/load', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ path: path }),
                    });
                    const loadData = await res.json();
                    if (loadData.status === 'success') {
                        renderVEMatrix(loadData.matrix);
                        showToast(`✓ Loaded ${loadData.calibration.filename} (CRC: ${loadData.calibration.stored_crc})`);
                        const dropdown = document.getElementById('terx-dropdown');
                        if (dropdown) dropdown.classList.add('hidden');
                    } else {
                        alert('Failed to load .terx: ' + loadData.message);
                    }
                } catch (err) {
                    console.error('Load error:', err);
                    alert('Load error: ' + err.message);
                }
            });
        });
    } catch (err) {
        console.error('Discover error:', err);
        listEl.innerHTML = `<div style="padding:10px; color:#ff5252; font-size:11px;">Scan error: ${err.message}</div>`;
    }
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

function renderSafetyBanner(alerts, level, source) {
    const banner = document.getElementById('safety-banner');
    if (!banner) return;
    const list = document.getElementById('safety-banner-list');
    const title = document.getElementById('safety-banner-title');
    const icon = document.getElementById('safety-banner-icon');
    const src = document.getElementById('safety-banner-source');

    if (!alerts || alerts.length === 0) {
        banner.classList.add('hidden');
        banner.classList.remove('critical');
        return;
    }
    const critical = level === 'critical';
    banner.classList.remove('hidden');
    banner.classList.toggle('critical', critical);
    if (icon) icon.textContent = critical ? '🛑' : '⚠️';
    if (title) title.textContent = critical ? 'CRITICAL SAFETY ALERT - DO NOT ADD BOOST OR TIMING' : 'SAFETY WARNING';
    if (src) src.textContent = source ? `from ${source}` : '';
    if (list) {
        list.innerHTML = alerts
            .map(a => `<li class="${a.level}">${escapeHtml(a.message)}</li>`)
            .join('');
    }
}

function renderComparison(data) {
    const box = document.getElementById('compare-box');
    if (!box) return;
    const parts = [];

    const pc = data.pull_comparison;
    if (pc) {
        const fmt = (v, unit, goodWhenNegative) => {
            if (v === null || v === undefined) return null;
            const cls = Math.abs(v) < 0.05 ? 'cmp-flat' : ((v < 0) === goodWhenNegative ? 'cmp-good' : 'cmp-bad');
            return `<span class="${cls}">${v > 0 ? '+' : ''}${v.toFixed(unit === 'rpm' ? 0 : 1)}${unit === 'rpm' ? '' : ' ' + unit}</span>`;
        };
        const bits = [];
        const boost = fmt(pc.peak_boost_psig, 'psi', false);
        if (boost) bits.push(`Peak boost ${boost}`);
        if (pc.afr_error !== null && pc.afr_error !== undefined) {
            const cls = pc.afr_error_improved === true ? 'cmp-good' : (pc.afr_error_improved === false ? 'cmp-bad' : 'cmp-flat');
            const label = pc.afr_error_improved === true ? 'closer to target' : (pc.afr_error_improved === false ? 'further from target' : 'about the same');
            bits.push(`AFR error <span class="${cls}">${pc.afr_error > 0 ? '+' : ''}${pc.afr_error.toFixed(2)}</span> (${label})`);
        }
        const diff = fmt(pc.min_differential_fuel_psi, 'psi', false);
        if (diff) bits.push(`Min fuel differential ${diff}`);
        const knock = fmt(pc.max_knock_retard_deg, 'deg', true);
        if (knock) bits.push(`Knock ${knock}`);
        parts.push(`<strong>vs previous pull</strong> (${escapeHtml(pc.previous_log || 'previous')} → ${escapeHtml(pc.current_log || 'this')}): ${bits.join(' • ')}`);
    }

    const tc = data.comparison;
    if (tc && tc.cells_compared > 0) {
        const cls = tc.trend === 'improving' ? 'cmp-good' : (tc.trend === 'worse' ? 'cmp-bad' : 'cmp-flat');
        const label = tc.trend === 'improving' ? 'TABLE IMPROVING' : (tc.trend === 'worse' ? 'TABLE GOT WORSE' : 'NO CHANGE');
        parts.push(`<span class="${cls}">${label}</span> ${escapeHtml(tc.summary)}`);
    }

    if (parts.length === 0) {
        box.classList.add('hidden');
        box.innerHTML = '';
        return;
    }
    box.innerHTML = parts.join('<br>');
    box.classList.remove('hidden');
}

function renderVEMatrix(data) {
    if (!data) return;
    state.lastMatrixData = data;

    // 1. Update Metrics Summary
    const samplesEl = document.getElementById('metric-samples');
    const cellsEl = document.getElementById('metric-cells');
    const leanEl = document.getElementById('metric-lean');
    const richEl = document.getElementById('metric-rich');
    const lowEl = document.getElementById('metric-lowconf');
    const sourceEl = document.getElementById('metric-source');
    const stepEl = document.getElementById('legend-step');

    if (samplesEl) samplesEl.textContent = (data.total_samples || 0).toLocaleString();
    if (cellsEl) cellsEl.textContent = `${data.cells_populated || 0} / 256`;
    if (lowEl) lowEl.textContent = data.low_confidence_cells || 0;
    if (stepEl && data.max_step_pct !== undefined) stepEl.textContent = data.max_step_pct;
    if (sourceEl) sourceEl.textContent = data.last_source || 'Documents\\Holley';

    // Update active tune button label
    const tuneLabel = document.getElementById('lbl-active-tune');
    if (tuneLabel) {
        if (data.loaded_terx_comment) {
            tuneLabel.textContent = `Tune: ${data.loaded_terx_comment}`;
        } else if (data.loaded_terx_path) {
            const parts = data.loaded_terx_path.split(/[\\/]/);
            tuneLabel.textContent = `Tune: ${parts[parts.length - 1]}`;
        }
    }

    let leanCount = 0;
    let richCount = 0;

    // 1b. Render History dropdown
    renderHistory(data.tune_history || []);

    // 2. Safety banner + scorecard (scorecards are newest-first)
    const scorecards = data.scorecards || [];
    const latest = scorecards.length > 0 ? scorecards[0] : null;
    renderSafetyBanner(data.safety_alerts || [], data.safety_level, latest ? latest.log_name : '');
    renderComparison(data);
    renderPullChart(latest ? latest.trace : null);

    const verdictEl = document.getElementById('scorecard-verdict');
    const badgeEl = document.getElementById('scorecard-badge');
    const detailsEl = document.getElementById('scorecard-details');

    if (latest) {
        if (verdictEl) verdictEl.textContent = latest.verdict || 'PULL COMPLETED';
        if (badgeEl) {
            badgeEl.textContent = `${latest.peak_boost_psig.toFixed(1)} PSI @ ${Math.round(latest.peak_rpm)} RPM`;
            badgeEl.className = latest.severity === 'critical' ? 'badge danger' : 'badge';
        }
        if (detailsEl) {
            detailsEl.innerHTML = `
                Avg AFR: <strong>${latest.avg_afr.toFixed(2)}</strong> (Target: ${latest.target_afr.toFixed(2)}, Err: ${latest.afr_error > 0 ? '+' : ''}${latest.afr_error.toFixed(2)}) •
                Min Fuel PSI: <strong>${latest.min_fuel_pressure_psi.toFixed(1)}</strong> (Differential: ${latest.min_differential_fuel_psi.toFixed(1)} PSI) •
                Max Injector Duty: <strong>${latest.max_injector_duty_pct.toFixed(1)}%</strong>
            `;
        }
    }

    // 3. Render 16×16 table: RPM across the top, MAP down the side (highest MAP first, as in Holley's table)
    const thead = document.getElementById('ve-thead');
    const tbody = document.getElementById('ve-tbody');
    const rows = data.rows || [];
    if (rows.length === 0) return;

    if (thead) {
        let thHtml = '<tr><th>MAP \\ RPM</th>';
        rows[0].cells.forEach(cell => {
            thHtml += `<th>${cell.rpm}</th>`;
        });
        thHtml += '</tr>';
        thead.innerHTML = thHtml;
    }

    if (tbody) {
        let trHtml = '';
        rows.forEach(row => {
            const boost = row.boost_psig > 0.4 ? `<br><span style="color:#00e5ff;font-size:9px;">+${row.boost_psig.toFixed(1)}#</span>` : '';
            trHtml += `<tr><th>${row.map_kpa}k${boost}</th>`;
            row.cells.forEach(cell => {
                const hits = cell.hits || 0;
                const corr = cell.correction_pct || 0;
                const raw = cell.raw_correction_pct !== undefined ? cell.raw_correction_pct : corr;
                const rec = cell.recommended_ve;
                const conf = cell.confidence || 'none';

                let cellClass = 've-cell nodata';
                let corrText = '';

                if (hits > 0 && conf === 'low') {
                    cellClass = 've-cell nodata lowconf';
                    corrText = `<span class="ve-corr" style="color:#a0aec0;">n=${hits}</span>`;
                } else if (hits > 0) {
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
                    if (cell.limited) cellClass += ' capped';
                }

                trHtml += `
                    <td class="${cellClass}"
                        data-rpm="${cell.rpm}"
                        data-map="${cell.map_kpa}"
                        data-base="${cell.base_ve}"
                        data-sug="${rec}"
                        data-corr="${corr.toFixed(2)}"
                        data-raw="${raw.toFixed(2)}"
                        data-limited="${cell.limited ? 1 : 0}"
                        data-conf="${conf}"
                        data-hits="${hits}"
                        data-afr="${cell.afr_avg === null || cell.afr_avg === undefined ? '' : cell.afr_avg}"
                        data-tafr="${cell.target_afr === null || cell.target_afr === undefined ? '' : cell.target_afr}"
                        data-fp="${cell.diff_fuel_psi === undefined ? '' : cell.diff_fuel_psi}"
                        data-knock="${cell.knock_deg || 0}"
                        data-cl="${(cell.cl_comp_pct || 0).toFixed(1)}"
                        data-learn="${(cell.learn_pct || 0).toFixed(1)}">
                        <span class="ve-val">${Math.round(rec)}</span>
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
        // Open interactive Cell Detail Modal on click
        c.addEventListener('click', () => openCellModal(c));

        c.addEventListener('mouseenter', () => {
            if (!tooltip) return;
            const g = (k) => c.getAttribute(k);
            const hits = parseInt(g('data-hits'), 10) || 0;
            const conf = g('data-conf');
            const boostPsig = Math.max(0, (parseFloat(g('data-map')) - 101.325) * 0.145038);
            const confLabel = { none: 'no data', low: 'LOW - held at 0%', medium: 'medium', high: 'high' }[conf] || conf;

            let html = `<div style="font-weight:700; color:#00e5ff; margin-bottom:4px;">${g('data-rpm')} RPM @ ${g('data-map')} kPa (${boostPsig.toFixed(1)} PSI Boost)</div>`;
            if (hits === 0) {
                html += `<div>No steady-state samples in this cell.</div>`;
            } else {
                html += `<div>Recommended VE: <strong style="color:#00e676;">${g('data-sug')}%</strong> (Base: ${g('data-base')}%)</div>`;
                html += `<div>Applied change: <strong>${g('data-corr')}%</strong>`;
                if (g('data-limited') === '1') {
                    html += ` <span style="color:#ffb300;">(capped; measured error is ${g('data-raw')}% - do another pass)</span>`;
                }
                html += `</div>`;
                if (g('data-afr')) html += `<div>AFR: <strong>${g('data-afr')}</strong> vs target ${g('data-tafr')}</div>`;
                html += `<div>Closed-Loop: <strong>${g('data-cl')}%</strong> • Learn: <strong>${g('data-learn')}%</strong></div>`;
                if (g('data-fp') !== '') html += `<div>Fuel differential: <strong>${g('data-fp')} PSI</strong> (target 58)</div>`;
                if (parseFloat(g('data-knock')) > 0) html += `<div style="color:#ff8a80;">Knock retard: <strong>${g('data-knock')}°</strong></div>`;
                html += `<div>Samples: <strong>${hits}</strong> • Confidence: <strong>${confLabel}</strong></div>`;
            }
            tooltip.innerHTML = html;
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
        ? state.lastMatrixData.holley_tsv_ve
        : state.lastMatrixData.holley_tsv_correction_pct;

    if (!tsv) {
        alert('Clipboard data empty.');
        return;
    }

    if (type === 've' && state.lastMatrixData.safety_level === 'critical') {
        const proceed = confirm(
            'CRITICAL SAFETY ALERT on the latest pull (see red banner).\n\n' +
            'Fix the safety issue first - for example, never add VE while fuel pressure is sagging.\n\n' +
            'Copy the VE table anyway?'
        );
        if (!proceed) return;
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

// ─── History & Revision Undo Manager ────────────────────────────────────────

function initHistory() {
    const btn = document.getElementById('btn-toggle-history');
    const dropdown = document.getElementById('history-dropdown');

    if (btn && dropdown) {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('hidden');
        });

        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target) && e.target !== btn) {
                dropdown.classList.add('hidden');
            }
        });
    }
}

function renderHistory(historyList) {
    const countEl = document.getElementById('history-count');
    const listEl = document.getElementById('history-list');
    if (!listEl) return;

    const list = historyList || [];
    if (countEl) countEl.textContent = list.length;

    if (list.length === 0) {
        listEl.innerHTML = '<div style="padding: 12px; color: var(--text-muted); font-size: 11px; text-align: center;">No revisions saved yet.</div>';
        return;
    }

    listEl.innerHTML = list.map((rev, idx) => {
        const timeAgo = Math.max(0, Math.round((Date.now() / 1000) - rev.timestamp));
        const timeStr = timeAgo < 60 ? `${timeAgo}s ago` : `${Math.round(timeAgo / 60)}m ago`;
        const isLatest = idx === 0;

        return `
            <div class="history-item">
                <div class="history-item-info">
                    <span class="history-source">${escapeHtml(rev.source)}</span>
                    <span class="history-meta">${rev.cells_populated} cells • ${rev.total_samples.toLocaleString()} samples • ${timeStr}</span>
                </div>
                ${!isLatest ? `<button type="button" class="history-revert-btn" data-id="${rev.id}">↺ Revert</button>` : '<span style="font-size:10px; color:#00e676; font-weight:700;">ACTIVE</span>'}
            </div>
        `;
    }).join('');

    // Attach Revert button click handlers
    listEl.querySelectorAll('.history-revert-btn').forEach(b => {
        b.addEventListener('click', async (e) => {
            e.stopPropagation();
            const revId = b.getAttribute('data-id');
            if (confirm('Revert 16×16 VE recommendations back to this revision?')) {
                try {
                    const res = await fetch('/api/optimizer/revert', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ id: revId }),
                    });
                    const data = await res.json();
                    if (data.status === 'success') {
                        renderVEMatrix(data.matrix);
                        showToast('✓ Successfully Reverted to Previous Revision!');
                        const dropdown = document.getElementById('history-dropdown');
                        if (dropdown) dropdown.classList.add('hidden');
                    } else {
                        alert(data.message || 'Revert failed.');
                    }
                } catch (err) {
                    console.error('Revert error:', err);
                    alert('Revert failed: ' + err.message);
                }
            }
        });
    });
}

// ─── WOT Pull Telemetry Chart Renderer ──────────────────────────────────────

function renderPullChart(trace) {
    const wrapper = document.getElementById('pull-chart-wrapper');
    const canvas = document.getElementById('wot-pull-canvas');
    if (!wrapper || !canvas) return;

    if (!trace || trace.length < 2) {
        wrapper.classList.add('hidden');
        return;
    }

    wrapper.classList.remove('hidden');

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;

    // Clear background
    ctx.fillStyle = '#050a14';
    ctx.fillRect(0, 0, w, h);

    // Draw horizontal grid lines
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    for (let y = 0.25; y < 1.0; y += 0.25) {
        ctx.beginPath();
        ctx.moveTo(0, h * y);
        ctx.lineTo(w, h * y);
        ctx.stroke();
    }

    const n = trace.length;
    const xStep = w / (n - 1);

    // Helper to plot a normalized curve
    function drawLine(getValue, minVal, maxVal, color, lineWidth = 2, isDashed = false) {
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        if (isDashed) {
            ctx.setLineDash([4, 4]);
        } else {
            ctx.setLineDash([]);
        }

        trace.forEach((pt, i) => {
            const val = getValue(pt);
            const norm = Math.max(0, Math.min(1, (val - minVal) / (maxVal - minVal)));
            const px = i * xStep;
            const py = h - (norm * (h - 16)) - 8;
            if (i === 0) ctx.moveTo(px, py);
            else ctx.lineTo(px, py);
        });
        ctx.stroke();
        ctx.setLineDash([]);
    }

    // 1. Plot RPM (White) [scaled 2000 to 7000 RPM]
    drawLine(d => d.rpm, 2000, 7000, 'rgba(248, 250, 252, 0.7)', 1.5);

    // 2. Plot Boost (Cyan) [scaled 0 to 22 PSI]
    drawLine(d => d.boost, 0, 22, '#00e5ff', 2.5);

    // 3. Plot Target AFR (Dashed Amber) [scaled 10.0 to 15.0 AFR]
    drawLine(d => d.target_afr, 10.0, 15.0, '#ffe082', 1.5, true);

    // 4. Plot Measured AFR (Green) [scaled 10.0 to 15.0 AFR]
    drawLine(d => d.afr, 10.0, 15.0, '#00e676', 2.0);

    // 5. Plot Differential Fuel Pressure (Purple / Red if sagging below 55 PSI)
    drawLine(d => d.diff_fp, 45, 65, '#e040fb', 1.5);
}

// ─── Interactive Cell Inspector Modal ──────────────────────────────────────

function initCellModal() {
    const modal = document.getElementById('cell-detail-modal');
    const closeBtn = document.getElementById('btn-close-cell-modal');
    const modalCloseBtn = document.getElementById('btn-modal-close');
    const backdrop = document.getElementById('cell-modal-backdrop');
    const askBtn = document.getElementById('btn-modal-ask-gemini');

    function closeModal() {
        if (modal) modal.classList.add('hidden');
    }

    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (modalCloseBtn) modalCloseBtn.addEventListener('click', closeModal);
    if (backdrop) backdrop.addEventListener('click', closeModal);

    if (askBtn) {
        askBtn.addEventListener('click', () => {
            if (!state.selectedCell) return;
            closeModal();
            const c = state.selectedCell;
            const boostPsig = Math.max(0, (parseFloat(c.map) - 101.325) * 0.145038);
            const prompt = `Can you audit the VE cell at ${c.rpm} RPM @ ${c.map} kPa (${boostPsig.toFixed(1)} PSI Boost)? Base VE is ${c.base}%, recommended is ${c.sug}% (${c.corr}% trim applied, measured error was ${c.raw}%). Measured AFR was ${c.afr || 'N/A'} vs Target ${c.tafr || 'N/A'}. Steady samples: ${c.hits}. Does this look safe for our 4.8L Turbo Fairmont?`;
            if (window.askQuestion) {
                window.askQuestion(prompt);
            }
        });
    }
}

function openCellModal(cellElement) {
    const modal = document.getElementById('cell-detail-modal');
    if (!modal) return;

    const g = (k) => cellElement.getAttribute(k);
    const rpm = g('data-rpm');
    const map = g('data-map');
    const base = g('data-base');
    const sug = g('data-sug');
    const corr = parseFloat(g('data-corr') || 0);
    const raw = parseFloat(g('data-raw') || corr);
    const hits = parseInt(g('data-hits') || 0, 10);
    const conf = g('data-conf') || 'none';
    const afr = g('data-afr');
    const tafr = g('data-tafr');
    const fp = g('data-fp');
    const knock = parseFloat(g('data-knock') || 0);
    const limited = g('data-limited') === '1';

    const boostPsig = Math.max(0, (parseFloat(map) - 101.325) * 0.145038);

    state.selectedCell = { rpm, map, base, sug, corr, raw, hits, conf, afr, tafr, fp, knock, limited };

    // Fill Title
    const titleEl = document.getElementById('modal-cell-title');
    if (titleEl) {
        titleEl.textContent = `${map} kPa @ ${rpm} RPM (${boostPsig > 0.4 ? '+' + boostPsig.toFixed(1) + ' PSI Boost' : 'Vacuum'})`;
    }

    // Fill Metric Cards
    const setVal = (id, text, color = null) => {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = text;
            if (color) el.style.color = color;
            else el.style.color = '';
        }
    };

    setVal('modal-base-ve', `${base}%`);
    setVal('modal-rec-ve', `${sug}%`, corr > 0 ? '#00e676' : (corr < 0 ? '#ff9100' : ''));
    setVal('modal-trim', `${corr > 0 ? '+' : ''}${corr.toFixed(1)}%`, corr > 0 ? '#00e676' : (corr < 0 ? '#ff9100' : ''));
    setVal('modal-raw-err', `${raw > 0 ? '+' : ''}${raw.toFixed(1)}%`);
    setVal('modal-hits', `${hits}`);
    setVal('modal-conf', conf.toUpperCase(), conf === 'high' ? '#00e676' : (conf === 'medium' ? '#00e5ff' : '#a0aec0'));
    setVal('modal-afr', afr ? `${afr} / ${tafr}` : '--');
    setVal('modal-diff-fp', fp ? `${parseFloat(fp).toFixed(1)} PSI` : '58.0 PSI', fp && parseFloat(fp) < 55 ? '#ff1744' : '#00e676');

    // Contextual Advice
    const adviceEl = document.getElementById('modal-advice-box');
    if (adviceEl) {
        let adviceHtml = '';
        if (hits === 0) {
            adviceHtml = '<p style="margin:0; color:#a0aec0;">No steady-state datalog samples recorded in this cell yet. The default 4.8L Sloppy Stage 2 base curve is maintained.</p>';
        } else if (fp && parseFloat(fp) < 55.0) {
            adviceHtml = '<p style="margin:0; color:#ff8a80;"><strong>⚠️ FUEL PRESSURE WARNING:</strong> Injector differential pressure dropped below 55 PSI in this cell. <strong>Do NOT add VE fuel</strong> until you verify fuel pump voltage, filter, or regulator reference line!</p>';
        } else if (knock >= 1.5) {
            adviceHtml = `<p style="margin:0; color:#ff8a80;"><strong>⚠️ KNOCK RETARD DETECTED (${knock.toFixed(1)}°):</strong> Engine knocked in this cell. Pull 1-2° timing in the Holley ignition table before increasing boost or fuel.</p>`;
        } else if (limited) {
            adviceHtml = `<p style="margin:0; color:#ffe082;"><strong>▲ TRIM STEP CAPPED:</strong> Measured AFR error was ${raw > 0 ? '+' : ''}${raw.toFixed(1)}%, but single-pass correction was safely capped at ${corr > 0 ? '+' : ''}${corr.toFixed(1)}%. After flashing, make another pass to allow the cell to fully converge.</p>`;
        } else if (conf === 'low') {
            adviceHtml = `<p style="margin:0; color:#a0aec0;"><strong>LOW SAMPLE CONFIDENCE:</strong> This cell only has ${hits} sample(s) (minimum is 5). The correction is held at 0.0% to prevent transient spikes from distorting your table.</p>`;
        } else {
            adviceHtml = `<p style="margin:0; color:#cbd5e1;">Steady-state AFR tracking is within safe tolerance. Recommended VE is calculated from ${hits} steady-state samples with Wideband O2 transport delay lookback.</p>`;
        }
        adviceEl.innerHTML = adviceHtml;
    }

    modal.classList.remove('hidden');
}

// ─── Passive WebSocket & Auto-Watch Coordinator ─────────────────────────────

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

                // 1. Zero-Touch Auto-Pull Analyzed Event
                if (msg.type === 'auto_pull_analyzed') {
                    if (msg.matrix) {
                        renderVEMatrix(msg.matrix);
                    }
                    const nameEl = document.getElementById('active-log-name');
                    const metaEl = document.getElementById('active-log-meta');
                    if (nameEl) nameEl.textContent = `📄 ${msg.log_name}`;
                    if (metaEl && msg.scorecard) {
                        metaEl.textContent = `Auto-Ingested • Peak Boost: ${msg.scorecard.peak_boost_psig.toFixed(1)} PSI @ ${Math.round(msg.scorecard.peak_rpm)} RPM`;
                    }
                    showToast(`🏁 New Pass Auto-Ingested: ${msg.log_name} (VE Table Ready!)`);

                    // Append Gemini Auto-Pilot message to chat
                    if (msg.gemini_answer) {
                        appendAutoPilotMessage(msg.log_name, msg.gemini_answer, msg.scorecard);
                    }

                    // Audible announcement - driven by the actual safety alerts, never assumed safe
                    if (window.speechSynthesis) {
                        try {
                            const sc = msg.scorecard;
                            const alerts = msg.safety_alerts || [];
                            let text;
                            if (alerts.length > 0) {
                                const first = alerts[0].message.split('. ')[0];
                                text = `${msg.safety_level === 'critical' ? 'Critical safety alert' : 'Warning'}. ${first}.`;
                            } else if (sc) {
                                text = `New pass ingested. ${sc.peak_boost_psig.toFixed(1)} PSI boost. No safety alerts. Updated VE table ready to paste.`;
                            } else {
                                text = 'New pass ingested. Updated VE table ready to paste.';
                            }
                            const utter = new SpeechSynthesisUtterance(text);
                            utter.rate = 1.05;
                            window.speechSynthesis.cancel();
                            window.speechSynthesis.speak(utter);
                        } catch (sErr) {}
                    }
                }

                // 2. Zero-Touch Auto-Tune Detected Event
                else if (msg.type === 'auto_tune_detected') {
                    showToast(`📋 Holley Calibration Detected: ${msg.tune_name}`);
                    if (msg.gemini_answer) {
                        appendCalibrationAuditMessage(msg.tune_name, msg.gemini_answer);
                    }
                }

                // 3. Fallback scorecard alerts from live CAN stream
                else if (msg.alerts && msg.alerts.some(a => a.alert_type === 'post_pull_scorecard')) {
                    loadVEMatrix();
                }

                // 4. Live CAN Telemetry Stream (Updates customizable gauges & circuit health)
                else if (msg.type === 'update' && msg.channels) {
                    handleLiveCANUpdate(msg);
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

function appendAutoPilotMessage(logName, answerText, scorecard) {
    const feed = document.getElementById('chat-feed');
    if (!feed) return;

    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const msg = document.createElement('div');
    msg.className = 'chat-msg assistant';

    let headerBadge = '';
    if (scorecard) {
        headerBadge = `<span class="badge" style="margin-left:8px;background:rgba(0,230,118,0.15);color:#00e676;">Peak ${scorecard.peak_boost_psig.toFixed(1)} PSI</span>`;
    }

    msg.innerHTML = `
        <div class="msg-header">
            <span class="msg-icon">✨</span>
            <strong class="msg-author">GEMINI AUTO-PILOT</strong>
            ${headerBadge}
            <span class="msg-time">${timeStr}</span>
        </div>
        <div class="msg-body" style="border-left: 2px solid #00e676; padding-left: 8px;">
            <div style="font-size: 11px; color: #a0aec0; margin-bottom: 6px; font-family: 'JetBrains Mono', monospace;">
                ⚡ Auto-Ingested Run: <strong>${escapeHtml(logName)}</strong>
            </div>
            ${formatMarkdown(answerText)}
        </div>
    `;
    feed.appendChild(msg);
    feed.scrollTop = feed.scrollHeight;
}

function appendCalibrationAuditMessage(tuneName, answerText) {
    const feed = document.getElementById('chat-feed');
    if (!feed) return;

    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const msg = document.createElement('div');
    msg.className = 'chat-msg assistant';
    msg.innerHTML = `
        <div class="msg-header">
            <span class="msg-icon">🛡️</span>
            <strong class="msg-author">CALIBRATION SAFETY AUDIT</strong>
            <span class="msg-time">${timeStr}</span>
        </div>
        <div class="msg-body" style="border-left: 2px solid #00e5ff; padding-left: 8px;">
            <div style="font-size: 11px; color: #a0aec0; margin-bottom: 6px; font-family: 'JetBrains Mono', monospace;">
                📁 Loaded Holley Tune: <strong>${escapeHtml(tuneName)}</strong>
            </div>
            ${formatMarkdown(answerText)}
        </div>
    `;
    feed.appendChild(msg);
    feed.scrollTop = feed.scrollHeight;
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

// =============================================================================
// Customizable Live Digital HUD & CAN Telemetry Engine
// Target: 1980 Ford Fairmont 4.8L Turbo LS (Terminator X MAX)
// =============================================================================

const DASHBOARD_PRESETS = {
    drag: [
        { id: 'rpm', channel: 'rpm', type: 'dial', size: 'large', label: 'ENGINE RPM', min: 0, max: 8000, warn: 6200, danger: 6600, unit: 'RPM' },
        { id: 'boost_psig', channel: 'boost_psig', type: 'dial', size: 'large', label: 'BOOST PRESSURE', min: 0, max: 30, warn: 20, danger: 25, unit: 'PSIG' },
        { id: 'fuel_pressure', channel: 'fuel_pressure', type: 'bar', size: 'wide', label: 'FUEL RAIL PRESSURE', min: 0, max: 100, target: 58, warn: 45, danger: 40, unit: 'PSI' },
        { id: 'afr_avg', channel: 'afr_avg', type: 'bar', size: 'wide', label: 'WIDEBAND AFR (AVG)', min: 9.0, max: 18.0, target: 11.8, warn: 12.8, danger: 13.5, unit: 'AFR' },
        { id: 'staging_input_1', channel: 'staging_input_1', type: 'stat', size: 'normal', label: 'TRANSBRAKE / STAGING', unit: 'STATUS' },
        { id: 'input_speed', channel: 'input_speed', type: 'stat', size: 'normal', label: '4L80E INPUT RPM', unit: 'RPM' },
        { id: 'knock_retard', channel: 'knock_retard', type: 'chart', size: 'wide', label: 'KNOCK RETARD TRACE', min: 0, max: 10, warn: 2, danger: 4, unit: '°' },
        { id: 'oil_pressure', channel: 'oil_pressure', type: 'stat', size: 'normal', label: 'OIL PRESSURE', min: 0, max: 100, warn: 30, danger: 20, unit: 'PSI' },
        { id: 'coolant_temp', channel: 'coolant_temp', type: 'stat', size: 'normal', label: 'COOLANT TEMP', min: 100, max: 250, warn: 215, danger: 230, unit: '°F' },
        { id: 'trans_temp', channel: 'trans_temp', type: 'stat', size: 'normal', label: '4L80E TRANS TEMP', min: 100, max: 260, warn: 210, danger: 235, unit: '°F' }
    ],
    street: [
        { id: 'rpm', channel: 'rpm', type: 'dial', size: 'large', label: 'ENGINE RPM', min: 0, max: 7000, warn: 6000, danger: 6500, unit: 'RPM' },
        { id: 'vehicle_speed', channel: 'vehicle_speed', type: 'dial', size: 'large', label: 'VEHICLE SPEED', min: 0, max: 140, warn: 80, danger: 120, unit: 'MPH' },
        { id: 'coolant_temp', channel: 'coolant_temp', type: 'dial', size: 'normal', label: 'COOLANT TEMP', min: 100, max: 250, warn: 215, danger: 230, unit: '°F' },
        { id: 'oil_pressure', channel: 'oil_pressure', type: 'dial', size: 'normal', label: 'OIL PRESSURE', min: 0, max: 100, warn: 30, danger: 20, unit: 'PSI' },
        { id: 'afr_avg', channel: 'afr_avg', type: 'bar', size: 'wide', label: 'WIDEBAND AFR', min: 10, max: 18, target: 14.7, warn: 16.0, danger: 17.0, unit: 'AFR' },
        { id: 'trans_gear', channel: 'trans_gear', type: 'stat', size: 'normal', label: '4L80E CURRENT GEAR', unit: 'GEAR' },
        { id: 'battery_volt', channel: 'battery_volt', type: 'stat', size: 'normal', label: 'BATTERY VOLTAGE', min: 10, max: 16, warn: 12.0, danger: 11.5, unit: 'V' },
        { id: 'trans_temp', channel: 'trans_temp', type: 'stat', size: 'normal', label: 'TRANS FLUID TEMP', min: 100, max: 260, warn: 210, danger: 235, unit: '°F' },
        { id: 'mat', channel: 'mat', type: 'stat', size: 'normal', label: 'MANIFOLD AIR TEMP', min: 50, max: 200, warn: 140, danger: 160, unit: '°F' }
    ],
    dyno: [
        { id: 'map_kpa', channel: 'map_kpa', type: 'dial', size: 'large', label: 'MAP PRESSURE', min: 0, max: 300, target: 101, warn: 200, danger: 250, unit: 'kPa' },
        { id: 'rpm', channel: 'rpm', type: 'dial', size: 'large', label: 'ENGINE RPM', min: 0, max: 8000, warn: 6200, danger: 6600, unit: 'RPM' },
        { id: 'afr_left', channel: 'afr_left', type: 'bar', size: 'wide', label: 'AFR BANK 1', min: 9.0, max: 18.0, target: 11.8, warn: 12.8, danger: 13.5, unit: 'AFR' },
        { id: 'afr_right', channel: 'afr_right', type: 'bar', size: 'wide', label: 'AFR BANK 2', min: 9.0, max: 18.0, target: 11.8, warn: 12.8, danger: 13.5, unit: 'AFR' },
        { id: 'closed_loop_comp', channel: 'closed_loop_comp', type: 'bar', size: 'wide', label: 'CLOSED LOOP COMP %', min: -30, max: 30, target: 0, warn: 15, danger: 25, unit: '%' },
        { id: 'current_learn', channel: 'current_learn', type: 'bar', size: 'wide', label: 'FUEL LEARN %', min: -30, max: 30, target: 0, warn: 15, danger: 25, unit: '%' },
        { id: 'injector_duty', channel: 'injector_duty', type: 'chart', size: 'wide', label: 'INJECTOR DUTY CYCLE', min: 0, max: 100, warn: 80, danger: 90, unit: '%' },
        { id: 'timing', channel: 'timing', type: 'stat', size: 'normal', label: 'TOTAL IGNITION TIMING', unit: '°BTDC' },
        { id: 'knock_retard', channel: 'knock_retard', type: 'stat', size: 'normal', label: 'KNOCK RETARD', min: 0, max: 12, warn: 2, danger: 4, unit: '°' }
    ],
    diagnostics: [
        { id: 'diag_tps', channel: 'tps', type: 'bar', size: 'wide', label: 'THROTTLE POSITION (TPS)', min: 0, max: 100, unit: '%' },
        { id: 'diag_map', channel: 'map_kpa', type: 'bar', size: 'wide', label: 'MANIFOLD PRESSURE (MAP)', min: 0, max: 300, unit: 'kPa' },
        { id: 'diag_clt', channel: 'coolant_temp', type: 'bar', size: 'wide', label: 'COOLANT TEMP SENSOR', min: -40, max: 260, unit: '°F' },
        { id: 'diag_mat', channel: 'mat', type: 'bar', size: 'wide', label: 'MANIFOLD AIR TEMP (MAT)', min: -40, max: 260, unit: '°F' },
        { id: 'diag_oil', channel: 'oil_pressure', type: 'bar', size: 'wide', label: 'OIL PRESSURE TRANSDUCER', min: 0, max: 150, unit: 'PSI' },
        { id: 'diag_fuel', channel: 'fuel_pressure', type: 'bar', size: 'wide', label: 'FUEL PRESSURE TRANSDUCER', min: 0, max: 150, unit: 'PSI' },
        { id: 'diag_batt', channel: 'battery_volt', type: 'bar', size: 'wide', label: 'SYSTEM BATTERY VOLTAGE', min: 8, max: 18, unit: 'V' },
        { id: 'diag_afr', channel: 'afr_avg', type: 'bar', size: 'wide', label: 'WIDEBAND O2 HEATER & SENSOR', min: 8, max: 22, unit: 'AFR' }
    ]
};

// Fallback catalog of reverse-engineered channels
const FALLBACK_CHANNELS = [
    { index: 1, name: 'rpm', label: 'RPM', unit: 'rpm', category: 'ENGINE', min_val: 0, max_val: 10000 },
    { index: 28, name: 'map_kpa', label: 'MAP', unit: 'kPa', category: 'ENGINE', min_val: 0, max_val: 500 },
    { index: 29, name: 'tps', label: 'Throttle Position', unit: '%', category: 'ENGINE', min_val: 0, max_val: 100 },
    { index: 32, name: 'baro_kpa', label: 'Barometric Pressure', unit: 'kPa', category: 'ENGINE', min_val: 50, max_val: 120 },
    { index: 34, name: 'oil_pressure', label: 'Oil Pressure', unit: 'psi', category: 'ENGINE', min_val: 0, max_val: 150 },
    { index: 26, name: 'iac_position', label: 'IAC Position', unit: '%', category: 'ENGINE', min_val: 0, max_val: 100 },
    { index: 2, name: 'fuel_pw', label: 'Fuel Pulse Width', unit: 'ms', category: 'FUELING', min_val: 0, max_val: 30 },
    { index: 3, name: 'injector_duty', label: 'Injector Duty Cycle', unit: '%', category: 'FUELING', min_val: 0, max_val: 100 },
    { index: 4, name: 'closed_loop_comp', label: 'Closed Loop Comp', unit: '%', category: 'FUELING', min_val: -50, max_val: 50 },
    { index: 5, name: 'target_afr', label: 'Target AFR', unit: 'AFR', category: 'FUELING', min_val: 8, max_val: 22 },
    { index: 6, name: 'afr_left', label: 'AFR Bank 1', unit: 'AFR', category: 'FUELING', min_val: 8, max_val: 22 },
    { index: 7, name: 'afr_right', label: 'AFR Bank 2', unit: 'AFR', category: 'FUELING', min_val: 8, max_val: 22 },
    { index: 8, name: 'afr_avg', label: 'AFR Average', unit: 'AFR', category: 'FUELING', min_val: 8, max_val: 22 },
    { index: 13, name: 'current_learn', label: 'Fuel Learn', unit: '%', category: 'FUELING', min_val: -50, max_val: 50 },
    { index: 17, name: 'fuel_flow', label: 'Fuel Flow', unit: 'lb/hr', category: 'FUELING', min_val: 0, max_val: 2000 },
    { index: 35, name: 'fuel_pressure', label: 'Fuel Pressure', unit: 'psi', category: 'FUELING', min_val: 0, max_val: 150 },
    { index: 21, name: 'estimated_ve', label: 'Estimated VE', unit: '%', category: 'FUELING', min_val: 0, max_val: 200 },
    { index: 126, name: 'system_boost_psig', label: 'System Boost', unit: 'psig', category: 'BOOST', min_val: 0, max_val: 60 },
    { index: 132, name: 'boost_psig', label: 'Boost Pressure', unit: 'psig', category: 'BOOST', min_val: 0, max_val: 60 },
    { index: 135, name: 'target_boost', label: 'Target Boost', unit: 'psig', category: 'BOOST', min_val: 0, max_val: 60 },
    { index: 142, name: 'boost_solenoid_duty', label: 'Boost Solenoid Duty', unit: '%', category: 'BOOST', min_val: 0, max_val: 100 },
    { index: 475, name: 'staging_input_1', label: 'Staging / Transbrake Input #1', unit: '', category: 'BOOST', min_val: 0, max_val: 1 },
    { index: 22, name: 'timing', label: 'Ignition Timing', unit: '°BTDC', category: 'SPARK', min_val: -10, max_val: 60 },
    { index: 24, name: 'knock_retard', label: 'Knock Retard', unit: '°', category: 'SPARK', min_val: 0, max_val: 20 },
    { index: 30, name: 'coolant_temp', label: 'Coolant Temp', unit: '°F', category: 'TEMPERATURE', min_val: -40, max_val: 300 },
    { index: 31, name: 'mat', label: 'Manifold Air Temp', unit: '°F', category: 'TEMPERATURE', min_val: -40, max_val: 300 },
    { index: 33, name: 'battery_volt', label: 'Battery Voltage', unit: 'V', category: 'SYSTEM', min_val: 0, max_val: 20 },
    { index: 219, name: 'trans_gear', label: 'Current Gear', unit: '', category: 'TRANSMISSION', min_val: 0, max_val: 6 },
    { index: 220, name: 'vehicle_speed', label: 'Vehicle Speed', unit: 'mph', category: 'TRANSMISSION', min_val: 0, max_val: 250 },
    { index: 221, name: 'line_pressure', label: 'Line Pressure PWM', unit: '%', category: 'TRANSMISSION', min_val: 0, max_val: 100 },
    { index: 222, name: 'input_speed', label: 'Input Shaft Speed', unit: 'rpm', category: 'TRANSMISSION', min_val: 0, max_val: 10000 },
    { index: 224, name: 'tcc_status', label: 'TCC Duty Cycle', unit: '%', category: 'TRANSMISSION', min_val: 0, max_val: 100 },
    { index: 225, name: 'trans_temp', label: 'Trans Temp', unit: '°F', category: 'TRANSMISSION', min_val: -40, max_val: 350 },
    { index: 498, name: 'line_pressure_psi', label: 'Actual Line Pressure', unit: 'psi', category: 'TRANSMISSION', min_val: 0, max_val: 300 }
];

function initLiveDashboard() {
    // 1. View Mode Switcher
    const btnTuning = document.getElementById('tab-btn-tuning');
    const btnLiveDash = document.getElementById('tab-btn-live-dash');
    if (btnTuning && btnLiveDash) {
        btnTuning.addEventListener('click', () => switchViewMode('tuning'));
        btnLiveDash.addEventListener('click', () => switchViewMode('live'));
    }

    // 2. Preset Selector Pills
    const presetPills = document.querySelectorAll('#dash-preset-selector .preset-pill');
    presetPills.forEach(pill => {
        pill.addEventListener('click', () => {
            const preset = pill.dataset.preset;
            if (preset) loadDashPreset(preset);
        });
    });

    // 3. Toolbar Action Buttons
    const btnAdd = document.getElementById('btn-add-gauge');
    if (btnAdd) btnAdd.addEventListener('click', () => openGaugeModal(-1));

    const btnEdit = document.getElementById('btn-toggle-edit-mode');
    if (btnEdit) {
        btnEdit.addEventListener('click', () => {
            state.dashEditMode = !state.dashEditMode;
            const container = document.getElementById('live-dashboard-view');
            const lbl = document.getElementById('lbl-edit-mode');
            if (container) container.classList.toggle('edit-mode-active', state.dashEditMode);
            if (lbl) lbl.textContent = state.dashEditMode ? 'Done Editing' : 'Edit Layout';
            btnEdit.classList.toggle('active', state.dashEditMode);
        });
    }

    const btnSave = document.getElementById('btn-save-dash-layout');
    if (btnSave) btnSave.addEventListener('click', saveCustomPreset);

    const btnReset = document.getElementById('btn-reset-dash-layout');
    if (btnReset) btnReset.addEventListener('click', resetDashPreset);

    const btnFullscreen = document.getElementById('btn-dash-fullscreen');
    if (btnFullscreen) {
        btnFullscreen.addEventListener('click', () => {
            if (!document.fullscreenElement) {
                document.documentElement.requestFullscreen().catch(() => {});
            } else {
                document.exitFullscreen().catch(() => {});
            }
        });
    }

    // 4. Gauge Modal Controls
    const modalClose = document.getElementById('btn-close-gauge-modal');
    const modalBackdrop = document.getElementById('gauge-modal-backdrop');
    const modalCancel = document.getElementById('btn-cancel-gauge-cfg');
    const gaugeForm = document.getElementById('gauge-config-form');

    if (modalClose) modalClose.addEventListener('click', closeGaugeModal);
    if (modalBackdrop) modalBackdrop.addEventListener('click', closeGaugeModal);
    if (modalCancel) modalCancel.addEventListener('click', closeGaugeModal);
    if (gaugeForm) gaugeForm.addEventListener('submit', saveGaugeConfig);

    // 5. Fetch Full Channel Catalog from API
    fetchChannelCatalog();

    // 6. Load Initial Preset
    loadDashPreset(state.dashPreset || 'drag');
}

function switchViewMode(mode) {
    state.activeView = mode;
    const btnTuning = document.getElementById('tab-btn-tuning');
    const btnLiveDash = document.getElementById('tab-btn-live-dash');
    const tuningWorkspace = document.getElementById('tuning-workspace');
    const liveDashView = document.getElementById('live-dashboard-view');

    if (mode === 'live') {
        if (btnTuning) btnTuning.classList.remove('active');
        if (btnLiveDash) btnLiveDash.classList.add('active');
        if (tuningWorkspace) tuningWorkspace.classList.add('hidden');
        if (liveDashView) liveDashView.classList.remove('hidden');
        // Render gauges to measure canvas sizes correctly
        setTimeout(renderGaugeGrid, 50);
    } else {
        if (btnLiveDash) btnLiveDash.classList.remove('active');
        if (btnTuning) btnTuning.classList.add('active');
        if (liveDashView) liveDashView.classList.add('hidden');
        if (tuningWorkspace) tuningWorkspace.classList.remove('hidden');
    }
}

async function fetchChannelCatalog() {
    try {
        const res = await fetch('/api/channels/catalog');
        if (res.ok) {
            const data = await res.json();
            if (data.channels && data.channels.length > 0) {
                state.channelCatalog = data.channels;
                populateChannelSelect();
                return;
            }
        }
    } catch (e) {
        // Fallback to static catalog if API call fails
    }
    state.channelCatalog = FALLBACK_CHANNELS;
    populateChannelSelect();
}

function populateChannelSelect() {
    const select = document.getElementById('cfg-gauge-channel');
    if (!select) return;

    select.innerHTML = '';
    const cats = {};
    (state.channelCatalog || FALLBACK_CHANNELS).forEach(ch => {
        const cat = ch.category || 'GENERAL';
        cats[cat] = cats[cat] || [];
        cats[cat].push(ch);
    });

    Object.keys(cats).sort().forEach(cat => {
        const optgroup = document.createElement('optgroup');
        optgroup.label = `─── ${cat} ───`;
        cats[cat].forEach(ch => {
            const opt = document.createElement('option');
            opt.value = ch.name;
            opt.textContent = `${ch.label} (${ch.name}) [${ch.unit || ''}]`;
            opt.dataset.unit = ch.unit || '';
            opt.dataset.min = ch.min_val ?? '';
            opt.dataset.max = ch.max_val ?? '';
            optgroup.appendChild(opt);
        });
        select.appendChild(optgroup);
    });

    select.addEventListener('change', () => {
        const opt = select.selectedOptions[0];
        if (!opt) return;
        const unitInp = document.getElementById('cfg-gauge-unit');
        const minInp = document.getElementById('cfg-gauge-min');
        const maxInp = document.getElementById('cfg-gauge-max');
        const labelInp = document.getElementById('cfg-gauge-label');
        if (unitInp && opt.dataset.unit) unitInp.value = opt.dataset.unit;
        if (minInp && opt.dataset.min) minInp.value = opt.dataset.min;
        if (maxInp && opt.dataset.max) maxInp.value = opt.dataset.max;
        if (labelInp && !labelInp.value) labelInp.value = opt.textContent.split(' (')[0];
    });
}

function loadDashPreset(presetName) {
    state.dashPreset = presetName;
    localStorage.setItem('holley_dash_active_preset', presetName);

    const pills = document.querySelectorAll('#dash-preset-selector .preset-pill');
    pills.forEach(p => p.classList.toggle('active', p.dataset.preset === presetName));

    if (presetName === 'custom') {
        const saved = localStorage.getItem('holley_dash_custom_preset');
        if (saved) {
            try {
                state.dashLayout = JSON.parse(saved);
            } catch (e) {
                state.dashLayout = JSON.parse(JSON.stringify(DASHBOARD_PRESETS.drag));
            }
        } else {
            state.dashLayout = JSON.parse(JSON.stringify(DASHBOARD_PRESETS.drag));
        }
    } else {
        const preset = DASHBOARD_PRESETS[presetName] || DASHBOARD_PRESETS.drag;
        state.dashLayout = JSON.parse(JSON.stringify(preset));
    }

    renderGaugeGrid();
}

function saveCustomPreset() {
    localStorage.setItem('holley_dash_custom_preset', JSON.stringify(state.dashLayout));
    state.dashPreset = 'custom';
    localStorage.setItem('holley_dash_active_preset', 'custom');

    const pills = document.querySelectorAll('#dash-preset-selector .preset-pill');
    pills.forEach(p => p.classList.toggle('active', p.dataset.preset === 'custom'));

    showToast('💾 Custom Dashboard Layout Saved!');
}

function resetDashPreset() {
    if (confirm(`Reset dashboard layout to default "${state.dashPreset}" preset?`)) {
        if (state.dashPreset === 'custom') {
            state.dashLayout = JSON.parse(JSON.stringify(DASHBOARD_PRESETS.drag));
            localStorage.setItem('holley_dash_custom_preset', JSON.stringify(state.dashLayout));
        } else {
            state.dashLayout = JSON.parse(JSON.stringify(DASHBOARD_PRESETS[state.dashPreset] || DASHBOARD_PRESETS.drag));
        }
        renderGaugeGrid();
        showToast('🔄 Layout Reset to Default');
    }
}

function renderGaugeGrid() {
    const grid = document.getElementById('gauge-grid');
    if (!grid) return;

    grid.innerHTML = '';
    const badge = document.getElementById('active-layout-badge');
    if (badge) badge.textContent = `${state.dashLayout.length} Gauges Loaded`;

    state.dashLayout.forEach((gauge, idx) => {
        const card = document.createElement('div');
        const sizeClass = gauge.size === 'large' ? 'gauge-large' : gauge.size === 'wide' ? 'gauge-wide' : 'gauge-normal';
        card.className = `dash-gauge-card ${sizeClass}`;
        card.id = `card-gauge-${idx}`;
        card.dataset.channel = gauge.channel;
        card.dataset.index = idx;

        const valObj = state.liveValues[gauge.channel] || { value: gauge.min || 0 };
        const currentVal = valObj.value ?? 0;

        let bodyHtml = '';
        if (gauge.type === 'dial') {
            bodyHtml = `
                <div class="gauge-card-body">
                    <canvas class="gauge-dial-canvas" id="canvas-dial-${idx}"></canvas>
                </div>
            `;
        } else if (gauge.type === 'bar') {
            const min = gauge.min ?? 0;
            const max = gauge.max ?? 100;
            const pct = Math.max(0, Math.min(100, ((currentVal - min) / (max - min)) * 100));
            const targetLine = gauge.target !== undefined ? `<div class="gauge-bar-target-line" style="left:${Math.max(0, Math.min(100, ((gauge.target - min) / (max - min)) * 100))}%;" title="Target: ${gauge.target}"></div>` : '';
            bodyHtml = `
                <div class="gauge-card-body">
                    <div class="gauge-bar-wrapper">
                        <div class="gauge-bar-numeric">
                            <span class="gauge-bar-val" id="bar-val-${idx}">${Number(currentVal).toFixed(1)}</span>
                            <span class="gauge-bar-unit">${escapeHtml(gauge.unit || '')}</span>
                        </div>
                        <div class="gauge-bar-track">
                            <div class="gauge-bar-fill" id="bar-fill-${idx}" style="width: ${pct}%;"></div>
                            ${targetLine}
                        </div>
                        <div class="gauge-bar-scale-labels">
                            <span>${min}</span>
                            ${gauge.target !== undefined ? `<span>🎯 ${gauge.target}</span>` : ''}
                            <span>${max}</span>
                        </div>
                    </div>
                </div>
            `;
        } else if (gauge.type === 'stat') {
            bodyHtml = `
                <div class="gauge-card-body">
                    <div class="gauge-stat-box">
                        <div class="stat-big-val" id="stat-val-${idx}">${Number(currentVal).toFixed(gauge.unit === 'STATUS' || gauge.unit === 'GEAR' ? 0 : 1)}</div>
                        <div class="stat-unit-line">${escapeHtml(gauge.unit || '')}</div>
                        <div class="stat-subline">
                            <span id="stat-min-${idx}">MIN: ${Number(currentVal).toFixed(1)}</span>
                            <span>•</span>
                            <span id="stat-max-${idx}">MAX: ${Number(currentVal).toFixed(1)}</span>
                        </div>
                    </div>
                </div>
            `;
        } else if (gauge.type === 'chart') {
            bodyHtml = `
                <div class="gauge-card-body">
                    <canvas class="gauge-chart-canvas" id="canvas-chart-${idx}"></canvas>
                    <div class="gauge-chart-stat-overlay" id="chart-val-${idx}">${Number(currentVal).toFixed(1)} ${escapeHtml(gauge.unit || '')}</div>
                </div>
            `;
        }

        card.innerHTML = `
            <div class="gauge-card-header">
                <div class="gauge-title-group">
                    <span class="gauge-title" title="${escapeHtml(gauge.label)}">${escapeHtml(gauge.label)}</span>
                    <span class="gauge-fault-badge healthy" id="fault-badge-${idx}">HEALTHY</span>
                </div>
                <div class="gauge-actions">
                    <button type="button" class="gauge-action-btn" onclick="moveGauge(${idx}, -1)" title="Move Left">⬅️</button>
                    <button type="button" class="gauge-action-btn" onclick="moveGauge(${idx}, 1)" title="Move Right">➡️</button>
                    <button type="button" class="gauge-action-btn" onclick="openGaugeModal(${idx})" title="Edit Gauge">⚙️</button>
                    <button type="button" class="gauge-action-btn btn-del" onclick="deleteGauge(${idx})" title="Remove Gauge">🗑️</button>
                </div>
            </div>
            ${bodyHtml}
        `;

        grid.appendChild(card);

        // Pre-render canvases
        if (gauge.type === 'dial') {
            setTimeout(() => {
                const cv = document.getElementById(`canvas-dial-${idx}`);
                if (cv) drawDialGauge(cv, currentVal, gauge);
            }, 20);
        } else if (gauge.type === 'chart') {
            setTimeout(() => {
                const cv = document.getElementById(`canvas-chart-${idx}`);
                state.historyBuffers[gauge.id] = state.historyBuffers[gauge.id] || [currentVal];
                if (cv) drawSparklineChart(cv, state.historyBuffers[gauge.id], gauge);
            }, 20);
        }
    });
}

function handleLiveCANUpdate(msg) {
    // 1. Telemetry Frame Rate (fps) calculation
    state.canPktCount++;
    const now = Date.now();
    if (now - state.canLastFpsTime >= 1000) {
        state.canFps = state.canPktCount;
        state.canPktCount = 0;
        state.canLastFpsTime = now;
        const rateEl = document.getElementById('can-rate-text');
        if (rateEl) rateEl.textContent = `CAN ${state.canFps} fps`;
    }

    if (!msg.channels) return;

    // 2. Cache latest channel values & update buffer
    Object.keys(msg.channels).forEach(name => {
        const chData = msg.channels[name];
        state.liveValues[name] = chData;
    });

    // 3. Update rendered gauges
    state.dashLayout.forEach((gauge, idx) => {
        const chData = state.liveValues[gauge.channel];
        if (!chData) return;

        const val = Number(chData.value);
        const card = document.getElementById(`card-gauge-${idx}`);
        if (!card) return;

        // Peak tracking
        state.gaugePeaks[gauge.id] = Math.max(state.gaugePeaks[gauge.id] ?? val, val);

        // Hardware circuit fault badging
        const faultBadge = document.getElementById(`fault-badge-${idx}`);
        if (faultBadge) {
            const fault = chData.circuit_fault;
            if (fault && !fault.healthy) {
                faultBadge.className = 'gauge-fault-badge fault';
                const codeStr = (fault.fault_codes && fault.fault_codes.length) ? fault.fault_codes[0] : 'FAULT';
                faultBadge.textContent = `⚠️ ${codeStr}`;
                faultBadge.title = fault.fault_codes ? fault.fault_codes.join(', ') : 'Sensor Circuit Fault';
            } else {
                faultBadge.className = 'gauge-fault-badge healthy';
            }
        }

        // Danger / Shift Light pulse
        if (gauge.danger !== undefined && val >= gauge.danger) {
            card.classList.add('danger-pulse');
        } else {
            card.classList.remove('danger-pulse');
        }

        // Render type update
        if (gauge.type === 'dial') {
            const cv = document.getElementById(`canvas-dial-${idx}`);
            if (cv) drawDialGauge(cv, val, gauge);
        } else if (gauge.type === 'bar') {
            const min = gauge.min ?? 0;
            const max = gauge.max ?? 100;
            const pct = Math.max(0, Math.min(100, ((val - min) / (max - min)) * 100));
            const fill = document.getElementById(`bar-fill-${idx}`);
            const valEl = document.getElementById(`bar-val-${idx}`);
            if (fill) {
                fill.style.width = `${pct}%`;
                if (gauge.danger !== undefined && val >= gauge.danger) {
                    fill.style.background = '#ff1744';
                } else if (gauge.warn !== undefined && val >= gauge.warn) {
                    fill.style.background = '#ff9100';
                } else {
                    fill.style.background = 'linear-gradient(90deg, #00e5ff 0%, #00e676 100%)';
                }
            }
            if (valEl) valEl.textContent = val.toFixed(1);
        } else if (gauge.type === 'stat') {
            const valEl = document.getElementById(`stat-val-${idx}`);
            const maxEl = document.getElementById(`stat-max-${idx}`);
            if (valEl) valEl.textContent = val.toFixed(gauge.unit === 'STATUS' || gauge.unit === 'GEAR' ? 0 : 1);
            if (maxEl) maxEl.textContent = `MAX: ${state.gaugePeaks[gauge.id].toFixed(1)}`;
        } else if (gauge.type === 'chart') {
            state.historyBuffers[gauge.id] = state.historyBuffers[gauge.id] || [];
            const buf = state.historyBuffers[gauge.id];
            buf.push(val);
            if (buf.length > 30) buf.shift();

            const cv = document.getElementById(`canvas-chart-${idx}`);
            const overlay = document.getElementById(`chart-val-${idx}`);
            if (cv) drawSparklineChart(cv, buf, gauge);
            if (overlay) overlay.textContent = `${val.toFixed(1)} ${gauge.unit || ''}`;
        }
    });
}

function drawDialGauge(canvas, value, gauge) {
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const cx = w / 2;
    const cy = h * 0.52;
    const r = Math.min(w, h) * 0.42;

    const min = gauge.min ?? 0;
    const max = gauge.max ?? 100;
    const clampedVal = Math.max(min, Math.min(max, value));

    const startAngle = 135 * Math.PI / 180;
    const endAngle = 405 * Math.PI / 180;
    const sweep = endAngle - startAngle;

    ctx.clearRect(0, 0, w, h);

    // 1. Background Track Arc
    ctx.beginPath();
    ctx.arc(cx, cy, r, startAngle, endAngle);
    ctx.lineWidth = Math.max(6, r * 0.08);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.lineCap = 'round';
    ctx.stroke();

    // 2. Warning Arc
    if (gauge.warn !== undefined && gauge.danger !== undefined && gauge.warn < max) {
        const warnAngle = startAngle + ((Math.max(min, gauge.warn) - min) / (max - min)) * sweep;
        const dangerAngle = startAngle + ((Math.min(max, gauge.danger) - min) / (max - min)) * sweep;
        ctx.beginPath();
        ctx.arc(cx, cy, r, warnAngle, dangerAngle);
        ctx.lineWidth = Math.max(6, r * 0.08);
        ctx.strokeStyle = 'rgba(255, 145, 0, 0.5)';
        ctx.stroke();
    }

    // 3. Danger / Redline Arc
    if (gauge.danger !== undefined && gauge.danger < max) {
        const dangerAngle = startAngle + ((Math.max(min, gauge.danger) - min) / (max - min)) * sweep;
        ctx.beginPath();
        ctx.arc(cx, cy, r, dangerAngle, endAngle);
        ctx.lineWidth = Math.max(6, r * 0.08);
        ctx.strokeStyle = 'rgba(255, 23, 68, 0.85)';
        ctx.stroke();
    }

    // 4. Value Progress Arc
    const valAngle = startAngle + ((clampedVal - min) / (max - min)) * sweep;
    ctx.beginPath();
    ctx.arc(cx, cy, r, startAngle, valAngle);
    ctx.lineWidth = Math.max(6, r * 0.08);
    ctx.strokeStyle = (gauge.danger !== undefined && value >= gauge.danger) ? '#ff1744' : '#00e5ff';
    ctx.shadowBlur = 10;
    ctx.shadowColor = (gauge.danger !== undefined && value >= gauge.danger) ? 'rgba(255, 23, 68, 0.6)' : 'rgba(0, 229, 255, 0.6)';
    ctx.stroke();
    ctx.shadowBlur = 0;

    // 5. Major Tick Marks & Numbers
    const numTicks = 6;
    for (let i = 0; i <= numTicks; i++) {
        const tickVal = min + (i / numTicks) * (max - min);
        const tickAngle = startAngle + (i / numTicks) * sweep;
        const isDanger = gauge.danger !== undefined && tickVal >= gauge.danger;

        const x1 = cx + (r - 12) * Math.cos(tickAngle);
        const y1 = cy + (r - 12) * Math.sin(tickAngle);
        const x2 = cx + (r - 2) * Math.cos(tickAngle);
        const y2 = cy + (r - 2) * Math.sin(tickAngle);

        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.lineWidth = 2;
        ctx.strokeStyle = isDanger ? '#ff1744' : 'rgba(255, 255, 255, 0.35)';
        ctx.stroke();

        // Tick Label
        const xt = cx + (r - 22) * Math.cos(tickAngle);
        const yt = cy + (r - 22) * Math.sin(tickAngle);
        ctx.font = `600 ${Math.max(9, r * 0.12)}px 'JetBrains Mono', monospace`;
        ctx.fillStyle = isDanger ? '#ff5252' : '#94a3b8';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(Math.round(tickVal), xt, yt);
    }

    // 6. Swept Needle
    const needleLen = r * 0.85;
    const nx = cx + needleLen * Math.cos(valAngle);
    const ny = cy + needleLen * Math.sin(valAngle);

    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(nx, ny);
    ctx.lineWidth = 3.5;
    ctx.strokeStyle = (gauge.danger !== undefined && value >= gauge.danger) ? '#ff1744' : '#00e5ff';
    ctx.shadowBlur = 12;
    ctx.shadowColor = (gauge.danger !== undefined && value >= gauge.danger) ? '#ff1744' : '#00e5ff';
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Needle Boss Cap
    ctx.beginPath();
    ctx.arc(cx, cy, Math.max(6, r * 0.1), 0, Math.PI * 2);
    ctx.fillStyle = '#0f172a';
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#00e5ff';
    ctx.stroke();

    // 7. Center Digital Value & Unit
    ctx.font = `900 ${Math.max(16, r * 0.28)}px 'Orbitron', monospace`;
    ctx.fillStyle = '#ffffff';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(Number(value).toFixed(max > 200 ? 0 : 1), cx, cy + r * 0.45);

    ctx.font = `700 ${Math.max(9, r * 0.12)}px 'JetBrains Mono', monospace`;
    ctx.fillStyle = '#00e5ff';
    ctx.fillText(gauge.unit || '', cx, cy + r * 0.65);
}

function drawSparklineChart(canvas, historyArr, gauge) {
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;

    ctx.clearRect(0, 0, w, h);

    if (!historyArr || historyArr.length < 2) return;

    const min = gauge.min ?? Math.min(...historyArr);
    const max = Math.max(gauge.max ?? Math.max(...historyArr), min + 0.001);

    // Area Gradient Fill
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, 'rgba(0, 229, 255, 0.3)');
    grad.addColorStop(1, 'rgba(0, 229, 255, 0.0)');

    ctx.beginPath();
    historyArr.forEach((val, i) => {
        const x = (i / (historyArr.length - 1)) * w;
        const norm = (val - min) / (max - min);
        const y = h - Math.max(0, Math.min(1, norm)) * (h - 10) - 5;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });

    ctx.strokeStyle = '#00e5ff';
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.lineTo(w, h);
    ctx.lineTo(0, h);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();
}

function openGaugeModal(gaugeIdx) {
    const modal = document.getElementById('gauge-modal');
    const idxInput = document.getElementById('cfg-gauge-edit-idx');
    const titleEl = document.getElementById('gauge-modal-title');
    const channelSelect = document.getElementById('cfg-gauge-channel');
    const typeSelect = document.getElementById('cfg-gauge-type');
    const sizeSelect = document.getElementById('cfg-gauge-size');
    const labelInput = document.getElementById('cfg-gauge-label');
    const minInput = document.getElementById('cfg-gauge-min');
    const maxInput = document.getElementById('cfg-gauge-max');
    const warnInput = document.getElementById('cfg-gauge-warn');
    const dangerInput = document.getElementById('cfg-gauge-danger');
    const targetInput = document.getElementById('cfg-gauge-target');
    const unitInput = document.getElementById('cfg-gauge-unit');

    if (!modal) return;
    idxInput.value = gaugeIdx;

    if (gaugeIdx >= 0 && state.dashLayout[gaugeIdx]) {
        const g = state.dashLayout[gaugeIdx];
        if (titleEl) titleEl.textContent = `Edit Gauge: ${g.label}`;
        if (channelSelect) channelSelect.value = g.channel;
        if (typeSelect) typeSelect.value = g.type || 'dial';
        if (sizeSelect) sizeSelect.value = g.size || 'normal';
        if (labelInput) labelInput.value = g.label || '';
        if (minInput) minInput.value = g.min ?? '';
        if (maxInput) maxInput.value = g.max ?? '';
        if (warnInput) warnInput.value = g.warn ?? '';
        if (dangerInput) dangerInput.value = g.danger ?? '';
        if (targetInput) targetInput.value = g.target ?? '';
        if (unitInput) unitInput.value = g.unit ?? '';
    } else {
        if (titleEl) titleEl.textContent = 'Add New Live Gauge';
        if (labelInput) labelInput.value = '';
        if (minInput) minInput.value = '0';
        if (maxInput) maxInput.value = '100';
        if (warnInput) warnInput.value = '';
        if (dangerInput) dangerInput.value = '';
        if (targetInput) targetInput.value = '';
        if (unitInput) unitInput.value = '';
    }

    modal.classList.remove('hidden');
}

function closeGaugeModal() {
    const modal = document.getElementById('gauge-modal');
    if (modal) modal.classList.add('hidden');
}

function saveGaugeConfig(e) {
    e.preventDefault();
    const idx = parseInt(document.getElementById('cfg-gauge-edit-idx').value, 10);
    const channel = document.getElementById('cfg-gauge-channel').value;
    const type = document.getElementById('cfg-gauge-type').value;
    const size = document.getElementById('cfg-gauge-size').value;
    const label = document.getElementById('cfg-gauge-label').value.trim() || channel.toUpperCase();
    const min = document.getElementById('cfg-gauge-min').value !== '' ? parseFloat(document.getElementById('cfg-gauge-min').value) : 0;
    const max = document.getElementById('cfg-gauge-max').value !== '' ? parseFloat(document.getElementById('cfg-gauge-max').value) : 100;
    const warn = document.getElementById('cfg-gauge-warn').value !== '' ? parseFloat(document.getElementById('cfg-gauge-warn').value) : undefined;
    const danger = document.getElementById('cfg-gauge-danger').value !== '' ? parseFloat(document.getElementById('cfg-gauge-danger').value) : undefined;
    const target = document.getElementById('cfg-gauge-target').value !== '' ? parseFloat(document.getElementById('cfg-gauge-target').value) : undefined;
    const unit = document.getElementById('cfg-gauge-unit').value.trim();

    const gaugeObj = {
        id: `gauge_${channel}_${Date.now()}`,
        channel,
        type,
        size,
        label,
        min,
        max,
        unit,
    };
    if (warn !== undefined) gaugeObj.warn = warn;
    if (danger !== undefined) gaugeObj.danger = danger;
    if (target !== undefined) gaugeObj.target = target;

    if (idx >= 0 && idx < state.dashLayout.length) {
        state.dashLayout[idx] = gaugeObj;
        showToast(`Updated Gauge: ${label}`);
    } else {
        state.dashLayout.push(gaugeObj);
        showToast(`Added Gauge: ${label}`);
    }

    closeGaugeModal();
    renderGaugeGrid();
}

function moveGauge(idx, direction) {
    const targetIdx = idx + direction;
    if (targetIdx < 0 || targetIdx >= state.dashLayout.length) return;
    const temp = state.dashLayout[idx];
    state.dashLayout[idx] = state.dashLayout[targetIdx];
    state.dashLayout[targetIdx] = temp;
    renderGaugeGrid();
}

function deleteGauge(idx) {
    if (confirm(`Remove gauge "${state.dashLayout[idx]?.label}" from dashboard?`)) {
        state.dashLayout.splice(idx, 1);
        renderGaugeGrid();
        showToast('Gauge Removed');
    }
}

