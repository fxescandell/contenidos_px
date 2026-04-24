function timeAgo(dateStr) {
    if (!dateStr) return '-';
    const now = new Date();
    const d = new Date(dateStr);
    const diffMs = now - d;
    const diffS = Math.floor(diffMs / 1000);
    if (diffS < 60) return 'ahora';
    const diffM = Math.floor(diffS / 60);
    if (diffM < 60) return diffM + ' min';
    const diffH = Math.floor(diffM / 60);
    if (diffH < 24) return diffH + 'h ' + (diffM % 60) + 'm';
    const diffD = Math.floor(diffH / 24);
    if (diffD < 30) return diffD + 'd ' + (diffH % 24) + 'h';
    return d.toLocaleDateString('es-ES', {day: '2-digit', month: '2-digit', year: '2-digit'});
}

function progressBar(status) {
    const idx = STATUS_ORDER.indexOf(status);
    if (idx < 0) return '';
    let html = '<div class="progress-bar" title="' + status + '">';
    STATUS_ORDER.forEach((s, i) => {
        let cls = '';
        if (i < idx) cls = 'done';
        else if (i === idx) {
            cls = s === 'FAILED' ? 'error' : 'current';
        }
        html += '<div class="step ' + cls + '"></div>';
    });
    html += '</div>';
    return html;
}

function matchFilter(b) {
    if (currentFilter === 'active' && !STATUSES_ACTIVE.includes(b.status)) return false;
    if (currentFilter === 'finished' && !STATUSES_FINISHED.includes(b.status)) return false;
    if (currentFilter === 'failed' && !STATUSES_FAILED.includes(b.status)) return false;
    if (currentFilter === 'review' && !STATUSES_REVIEW.includes(b.status)) return false;
    const muniEl = document.getElementById('filter-municipality');
    const searchEl = document.getElementById('search-input');
    const muni = muniEl ? muniEl.value : '';
    if (muni && b.municipality !== muni) return false;
    const q = (searchEl ? searchEl.value : '').toLowerCase();
    if (q && !(b.external_name || '').toLowerCase().includes(q)) return false;
    return true;
}

function renderBatches() {
    const tbody = document.getElementById('batches-tbody');
    const empty = document.getElementById('empty-state');
    const count = document.getElementById('showing-count');
    if (!tbody || !empty || !count) {
        return;
    }
    const filtered = BATCHES.filter(matchFilter);
    count.textContent = filtered.length + ' de ' + BATCHES.length;

    if (filtered.length === 0) {
        tbody.innerHTML = '';
        empty.style.display = 'block';
        return;
    }
    empty.style.display = 'none';

    tbody.innerHTML = filtered.map(b => {
        const statusTitle = b.error_message || b.review_reason || b.status;
        return `<tr>
            <td>
                <div style="font-weight:600;">${escapeHtml(b.external_name || 'Sin nombre')}</div>
                ${b.error_message ? '<div class="error-text" title="' + escapeHtml(b.error_message) + '">' + escapeHtml(b.error_message) + '</div>' : ''}
                ${b.review_reason ? '<div class="error-text" style="color:#856404;" title="' + escapeHtml(b.review_reason) + '">' + escapeHtml(b.review_reason) + '</div>' : ''}
            </td>
            <td>
                <span class="muni-badge ${getMuniClass(b.municipality)}">${getMuniLabel(b.municipality)}</span>
                <div style="font-size:11px;color:#888;margin-top:2px;">${escapeHtml(b.category || '')}</div>
            </td>
            <td>
                <span class="status-badge status-${b.status}" title="${escapeHtml(statusTitle)}">${b.status}</span>
                <div style="margin-top:4px;">${progressBar(b.status)}</div>
            </td>
            <td>
                <span class="count-badge">${b.n_files} fich.</span>
                <span class="count-badge">${b.n_candidates} cand.</span>
            </td>
            <td><span class="time-ago">${timeAgo(b.created_at)}</span></td>
            <td style="white-space:nowrap;">
                <a href="/batch/${b.id}" class="action-link">Ver &rarr;</a>
                <button class="btn-delete" id="del-${b.id}" title="Eliminar lote" onclick="confirmDelete(this, '${b.id}', '${escapeHtml(b.external_name || 'Sin nombre')}')">&#10005;</button>
            </td>
        </tr>`;
    }).join('');
}

function setFilter(filter, el) {
    currentFilter = filter;
    document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
    if (el) el.classList.add('active');
    applyFilters();
}

let deleteTimers = {};

function confirmDelete(btn, id, name) {
    if (deleteTimers[id]) {
        clearTimeout(deleteTimers[id]);
        delete deleteTimers[id];
        deleteBatch(id, name);
        return;
    }
    btn.classList.add('confirming');
    btn.innerHTML = 'Confirmar';
    btn.title = 'Pulsa de nuevo para confirmar el borrado';
    deleteTimers[id] = setTimeout(() => {
        btn.classList.remove('confirming');
        btn.innerHTML = '&#10005;';
        btn.title = 'Eliminar lote';
        delete deleteTimers[id];
    }, 3000);
}

async function deleteBatch(id, name) {
    try {
        const res = await fetch('/api/batches/' + id, { method: 'DELETE' });
        if (res.ok) {
            const idx = BATCHES.findIndex(b => b.id === id);
            if (idx >= 0) BATCHES.splice(idx, 1);
            renderBatches();
            const statsRes = await fetch('/api/batches');
            if (statsRes.ok) updateStats(await statsRes.json().then(d => d.stats));
        } else {
            const data = await res.json();
            alert('Error: ' + (data.message || 'No se pudo eliminar'));
        }
    } catch (e) {
        alert('Error de conexion');
    }
}

function applyFilters() { renderBatches(); }

function setBatches(nextBatches) {
    BATCHES.splice(0, BATCHES.length, ...(nextBatches || []));
}

async function refreshBatchesFromApi() {
    if (!HAS_DASHBOARD && !HAS_MANUAL_ARTICLE && !HAS_MANUAL_BATCHES) {
        return;
    }
    try {
        const res = await fetch('/api/batches');
        if (!res.ok) return;
        const data = await res.json();
        setBatches(data.batches || []);
        updateStats(data.stats || { total: 0, active: 0, finished: 0, failed: 0, review: 0 });
        renderBatches();
        if (data.has_active) {
            if (!refreshInterval) startAutoRefresh();
        } else {
            stopAutoRefresh();
        }
    } catch (_e) {}
}

let refreshInterval = null;
let refreshCountdown = 5;

function startAutoRefresh() {
    const indicator = document.getElementById('auto-refresh-indicator');
    const timer = document.getElementById('refresh-timer');
    if (!indicator || !timer) return;
    indicator.style.display = 'flex';
    refreshCountdown = 5;
    timer.textContent = refreshCountdown + 's';
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = setInterval(async () => {
        refreshCountdown--;
        timer.textContent = refreshCountdown + 's';
        if (refreshCountdown <= 0) {
            refreshCountdown = 5;
            await refreshBatchesFromApi();
        }
    }, 1000);
}

function stopAutoRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
        refreshInterval = null;
    }
    const indicator = document.getElementById('auto-refresh-indicator');
    if (indicator) indicator.style.display = 'none';
}

function updateStats(stats) {
    const cards = document.querySelectorAll('.stat-card');
    if (!cards || cards.length < 5) return;
    cards[0].querySelector('.stat-number').textContent = stats.total;
    cards[1].querySelector('.stat-number').textContent = stats.active;
    cards[2].querySelector('.stat-number').textContent = stats.finished;
    cards[3].querySelector('.stat-number').textContent = stats.failed;
    cards[4].querySelector('.stat-number').textContent = stats.review;
}

function closeActivityModal(event) {
    if (event) event.stopPropagation();
    if (activityState.timer) {
        clearInterval(activityState.timer);
        activityState.timer = null;
    }
    document.getElementById('activity-modal-backdrop').classList.remove('open');
}

function openActivityModal(flowId, options = {}) {
    activityState.flowId = flowId;
    activityState.batchId = options.batchId || null;
    activityState.startedAfter = options.startedAfter || '';

    const flow = MANUAL_FLOWS.find(f => f.id === flowId);
    document.getElementById('activity-modal-title').textContent = 'Actividad del flujo';
    document.getElementById('activity-modal-subtitle').textContent = flow ? getFlowLabel(flow) : 'Procesando...';
    document.getElementById('activity-status').textContent = 'Esperando';
    document.getElementById('activity-batch').textContent = '-';
    document.getElementById('activity-updated').textContent = '-';
    document.getElementById('activity-count').textContent = '0';
    document.getElementById('activity-log').innerHTML = '<div class="activity-log-empty">Esperando eventos del proceso...</div>';
    const batchLink = document.getElementById('activity-batch-link');
    batchLink.style.display = 'none';
    batchLink.href = '#';

    document.getElementById('activity-modal-backdrop').classList.add('open');
    startActivityPolling();
}

function startActivityPolling() {
    if (activityState.timer) clearInterval(activityState.timer);
    fetchActivityEvents();
    activityState.timer = setInterval(fetchActivityEvents, 1500);
}

async function fetchActivityEvents() {
    if (!activityState.flowId && !activityState.batchId) return;
    let url = '';
    if (activityState.batchId) {
        url = '/api/v1/flows/batches/' + activityState.batchId + '/events?limit=300';
    } else {
        url = '/api/v1/flows/' + activityState.flowId + '/activity?limit=300';
        if (activityState.startedAfter) {
            url += '&started_after=' + encodeURIComponent(activityState.startedAfter);
        }
    }

    try {
        const res = await fetch(url);
        const data = await res.json();
        if (!res.ok || data.success === false) return;
        renderActivityModal(data.batch, data.events || []);
    } catch (_e) {}
}

function renderActivityModal(batch, events) {
    const statusEl = document.getElementById('activity-status');
    const batchEl = document.getElementById('activity-batch');
    const updatedEl = document.getElementById('activity-updated');
    const countEl = document.getElementById('activity-count');
    const logEl = document.getElementById('activity-log');
    const batchLink = document.getElementById('activity-batch-link');

    if (!batch) {
        statusEl.textContent = 'Esperando lote';
        batchEl.textContent = '-';
        updatedEl.textContent = '-';
        countEl.textContent = '0';
        logEl.innerHTML = '<div class="activity-log-empty">Aun no se ha creado el lote o no hay eventos visibles.</div>';
        batchLink.style.display = 'none';
        return;
    }

    activityState.batchId = batch.id;
    statusEl.textContent = batch.status || 'UNKNOWN';
    batchEl.textContent = batch.external_name || batch.id;
    updatedEl.textContent = formatDateTime(batch.updated_at || batch.finished_at || batch.created_at);
    countEl.textContent = String(events.length || 0);
    batchLink.href = '/batch/' + batch.id;
    batchLink.style.display = 'inline-flex';

    if (!events.length) {
        logEl.innerHTML = '<div class="activity-log-empty">No hay eventos registrados todavia para este lote.</div>';
        return;
    }

    logEl.innerHTML = events.map(event => {
        const payloadText = event.payload && Object.keys(event.payload).length
            ? `<div class="activity-event-payload">${escapeHtml(JSON.stringify(event.payload, null, 2))}</div>`
            : '';
        return `<div class="activity-event"><div class="activity-event-meta"><span class="activity-event-time">${escapeHtml(formatDateTime(event.created_at))}</span><span class="activity-level ${escapeHtml(event.level || 'INFO')}">${escapeHtml(event.level || 'INFO')}</span><span class="activity-event-stage">${escapeHtml(event.stage || '-')}</span><span>${escapeHtml(event.event_type || '')}</span></div><div class="activity-event-message">${escapeHtml(event.message || '')}</div>${payloadText}</div>`;
    }).join('');
    logEl.scrollTop = logEl.scrollHeight;
}

let globalActivityTimer = null;
let globalActivitySearchTimer = null;

function moduleLabel(moduleName) {
    const value = String(moduleName || '').toLowerCase();
    if (value === 'flows') return 'Flujos';
    if (value === 'manual') return 'Manual';
    if (value === 'preprocess') return 'Preprocesado';
    if (value === 'final-review') return 'Revision final';
    if (value === 'system') return 'Sistema';
    return value || 'Desconocido';
}

function scheduleGlobalActivityFeedReload() {
    if (globalActivitySearchTimer) {
        clearTimeout(globalActivitySearchTimer);
    }
    globalActivitySearchTimer = setTimeout(loadGlobalActivityFeed, 320);
}

function setupGlobalActivityFeed() {
    const container = document.getElementById('global-activity-list');
    if (!container) return;
    loadGlobalActivityFeed();
    if (globalActivityTimer) clearInterval(globalActivityTimer);
    globalActivityTimer = setInterval(loadGlobalActivityFeed, 6000);
}

function renderGlobalActivitySummary(total, counts) {
    const el = document.getElementById('global-activity-summary');
    if (!el) return;
    const c = counts || {};
    el.textContent = `Eventos: ${total || 0} · Flujos ${c.flows || 0} · Manual ${c.manual || 0} · Preprocesado ${c.preprocess || 0} · Revision final ${c['final-review'] || 0} · Sistema ${c.system || 0}`;
}

function renderGlobalActivityFeed(events) {
    const list = document.getElementById('global-activity-list');
    if (!list) return;

    const data = events || [];
    if (!data.length) {
        list.innerHTML = '<div class="activity-feed-empty">No hay eventos para los filtros actuales.</div>';
        return;
    }

    list.innerHTML = data.map(event => {
        const payloadText = event.payload && Object.keys(event.payload).length
            ? `<div class="activity-feed-payload">${escapeHtml(JSON.stringify(event.payload, null, 2))}</div>`
            : '';
        const refs = [];
        if (event.batch_id) refs.push(`batch ${event.batch_id}`);
        if (event.candidate_id) refs.push(`candidate ${event.candidate_id}`);
        const refsText = refs.length ? `<div class="activity-feed-refs">${escapeHtml(refs.join(' · '))}</div>` : '';
        return `<div class="activity-feed-item"><div class="activity-feed-meta"><span class="activity-feed-time">${escapeHtml(formatDateTime(event.created_at))}</span><span class="activity-feed-module module-${escapeHtml(event.module || 'flows')}">${escapeHtml(moduleLabel(event.module || 'flows'))}</span><span class="activity-level ${escapeHtml(event.level || 'INFO')}">${escapeHtml(event.level || 'INFO')}</span><span class="activity-feed-type">${escapeHtml(event.event_type || '')}</span><span class="activity-feed-stage">${escapeHtml(event.stage || '-')}</span></div><div class="activity-feed-message">${escapeHtml(event.message || '')}</div>${refsText}${payloadText}</div>`;
    }).join('');
}

async function loadGlobalActivityFeed() {
    const list = document.getElementById('global-activity-list');
    if (!list) return;

    const module = document.getElementById('global-activity-module')?.value || 'all';
    const level = document.getElementById('global-activity-level')?.value || 'all';
    const query = document.getElementById('global-activity-search')?.value || '';

    const params = new URLSearchParams({
        module,
        level,
        q: query,
        limit: '250',
    });

    try {
        const res = await fetch(`/api/v1/flows/workspace/activity-feed?${params.toString()}`);
        const data = await res.json();
        if (!res.ok || data.success === false) {
            list.innerHTML = '<div class="activity-feed-empty">No se pudo cargar la actividad global.</div>';
            return;
        }
        renderGlobalActivitySummary(data.total || 0, data.module_counts || {});
        renderGlobalActivityFeed(data.events || []);
    } catch (_e) {
        list.innerHTML = '<div class="activity-feed-empty">Error de conexion cargando la actividad global.</div>';
    }
}

async function clearGlobalActivityFeed() {
    const ok = confirm('Se eliminara TODO el historial de actividad del workspace. Esta accion no se puede deshacer.');
    if (!ok) return;

    const list = document.getElementById('global-activity-list');
    const summary = document.getElementById('global-activity-summary');
    if (list) {
        list.innerHTML = '<div class="activity-feed-empty">Borrando actividad...</div>';
    }

    try {
        const res = await fetch('/api/v1/flows/workspace/activity-feed/clear', { method: 'POST' });
        const data = await res.json();
        if (!res.ok || data.success === false) {
            if (summary) summary.textContent = data.detail || data.message || 'No se pudo borrar la actividad.';
            await loadGlobalActivityFeed();
            return;
        }
        if (summary) summary.textContent = data.message || 'Actividad eliminada.';
        await loadGlobalActivityFeed();
    } catch (_e) {
        if (summary) summary.textContent = 'Error de conexion borrando actividad.';
        await loadGlobalActivityFeed();
    }
}

function exportGlobalActivityFeed() {
    const module = document.getElementById('global-activity-module')?.value || 'all';
    const level = document.getElementById('global-activity-level')?.value || 'all';
    const query = document.getElementById('global-activity-search')?.value || '';
    const format = document.getElementById('global-activity-export-format')?.value || 'json';

    const params = new URLSearchParams({
        module,
        level,
        q: query,
        limit: '500',
        format,
    });

    const summary = document.getElementById('global-activity-summary');
    if (summary) {
        summary.textContent = `Preparando export de actividad (${format.toUpperCase()})...`;
    }
    window.open(`/api/v1/flows/workspace/activity-feed/export?${params.toString()}`, '_blank');
}
