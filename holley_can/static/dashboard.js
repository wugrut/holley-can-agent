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

    let leanCount = 0;
    let richCount = 0;

    // 2. Safety banner + scorecard (scorecards are newest-first)
    const scorecards = data.scorecards || [];
    const latest = scorecards.length > 0 ? scorecards[0] : null;
    renderSafetyBanner(data.safety_alerts || [], data.safety_level, latest ? latest.log_name : '');
    renderComparison(data);

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
