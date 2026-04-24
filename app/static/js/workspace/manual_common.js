function setManualResult(kind, message, batchId) {
    const el = document.getElementById('manual-result');
    if (!el) return;
    el.className = 'manual-result ' + kind;
    let html = escapeHtml(message || '');
    if (batchId) {
        html += ` <a href="/batch/${batchId}" style="margin-left:6px; font-weight:600;">Abrir lote</a>`;
    }
    el.innerHTML = html;
}

function hideCleanupPreviewDetails() {
    const box = document.getElementById('cleanup-preview-box');
    const errors = document.getElementById('cleanup-errors');
    if (box) box.classList.remove('open');
    if (errors) errors.style.display = 'none';
    cleanupRetryTargets = { working: [], temp: [] };
}

function extractRetryTargetsFromErrors(errors) {
    const targets = [];
    (errors || []).forEach(item => {
        const text = String(item || '');
        const idx = text.indexOf(':');
        const maybePath = idx > 0 ? text.slice(0, idx).trim() : '';
        if (maybePath.startsWith('/')) {
            targets.push(maybePath);
        }
    });
    return Array.from(new Set(targets));
}

function renderCleanupPreviewDetails(data) {
    const box = document.getElementById('cleanup-preview-box');
    if (!box || !data || !data.details) {
        if (box) box.classList.remove('open');
        return;
    }

    const working = data.details.working || {};
    const temp = data.details.temp || {};
    const mode = (data.mode || 'soft').toUpperCase();
    const dryRunLabel = data.dry_run ? ' (previsualizacion)' : '';

    document.getElementById('cleanup-preview-title').textContent = `Limpieza ${mode}${dryRunLabel}`;
    document.getElementById('cleanup-working-subtitle').textContent = `Working · planificados: ${working.planned || 0} · eliminados: ${working.removed || 0} · omitidos: ${working.skipped || 0}`;
    document.getElementById('cleanup-temp-subtitle').textContent = `Temp · planificados: ${temp.planned || 0} · eliminados: ${temp.removed || 0} · omitidos: ${temp.skipped || 0}`;

    const workingItems = (working.items || []);
    const tempItems = (temp.items || []);
    document.getElementById('cleanup-working-list').textContent = workingItems.length ? workingItems.join('\n') : (working.note || 'Sin elementos listados para working.');
    document.getElementById('cleanup-temp-list').textContent = tempItems.length ? tempItems.join('\n') : 'Sin elementos listados para temp.';

    const workingErrors = (working.errors || []);
    const tempErrors = (temp.errors || []);
    const allErrors = [...workingErrors, ...tempErrors];
    cleanupRetryTargets = {
        working: extractRetryTargetsFromErrors(workingErrors),
        temp: extractRetryTargetsFromErrors(tempErrors),
    };

    const errorsBox = document.getElementById('cleanup-errors');
    const retryBtn = document.getElementById('cleanup-retry-errors-btn');
    if (allErrors.length) {
        document.getElementById('cleanup-errors-title').textContent = `Incidencias de borrado (${allErrors.length})`;
        document.getElementById('cleanup-errors-list').textContent = allErrors.join('\n');
        errorsBox.style.display = '';
        const canRetry = cleanupRetryTargets.working.length > 0 || cleanupRetryTargets.temp.length > 0;
        retryBtn.disabled = !canRetry;
    } else {
        errorsBox.style.display = 'none';
    }

    box.classList.add('open');
}

async function retryCleanupErrors() {
    const hasRetryTargets = cleanupRetryTargets.working.length > 0 || cleanupRetryTargets.temp.length > 0;
    if (!hasRetryTargets) {
        setManualResult('err', 'No hay rutas con error para reintentar.');
        return;
    }
    await runManualCleanup(false, cleanupRetryTargets);
}

function setManualButtonsDisabled(disabled) {
    const ids = [
        'manual-run-btn', 'manual-export-btn', 'manual-activity-btn', 'manual-upload-btn',
        'manual-preview-btn', 'manual-open-preview-btn', 'manual-accept-btn', 'manual-discard-btn', 'manual-finalize-btn',
        'manual-reset-btn', 'manual-cleanup-mode', 'manual-cleanup-preview-btn', 'manual-cleanup-btn',
    ];
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = disabled;
    });
}
