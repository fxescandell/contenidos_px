function getSelectedFlowId() {
    const select = document.getElementById('manual-flow-select');
    return select ? select.value : '';
}

function openManualActivityFromSelection() {
    const flowId = getSelectedFlowId();
    if (!flowId) {
        setManualResult('err', 'No hay flujos activos para este modo.');
        return;
    }
    openActivityModal(flowId);
}

function renderManualDraftState(state) {
    MANUAL_DRAFT_STATE = state;
    const incomingEl = document.getElementById('manual-incoming-list');
    const verifiedEl = document.getElementById('manual-verified-list');
    if (!incomingEl || !verifiedEl) return;

    const incoming = (state && state.incoming_files) ? state.incoming_files : [];
    incomingEl.innerHTML = incoming.length
        ? incoming.map(name => `- ${escapeHtml(name)}`).join('<br>')
        : 'Sin archivos pendientes';

    const verified = (state && state.verified_items) ? state.verified_items : [];
    verifiedEl.innerHTML = verified.length
        ? verified.map(item => `#${item.sequence} - ${escapeHtml(item.summary || 'Sin resumen')} (${(item.files || []).length} fich.)`).join('<br>')
        : 'Aun no hay previews aceptadas';

    const hasPending = Boolean(state && state.pending && state.pending.exists);
    document.getElementById('manual-accept-btn').disabled = !hasPending;
    document.getElementById('manual-discard-btn').disabled = !hasPending;
    const showPreviewBtn = document.getElementById('manual-open-preview-btn');
    if (showPreviewBtn) showPreviewBtn.disabled = !hasPending;
    document.getElementById('manual-finalize-btn').disabled = !verified.length;
}

async function loadManualDraftState() {
    const flowId = getSelectedFlowId();
    if (!flowId) {
        renderManualDraftState(null);
        return;
    }
    try {
        const res = await fetch(`/api/v1/flows/${flowId}/manual/state`);
        const data = await res.json();
        if (res.ok && data.success !== false) {
            renderManualDraftState(data);
        } else {
            renderManualDraftState(null);
        }
    } catch (_e) {
        renderManualDraftState(null);
    }
}

async function loadManualFlows() {
    const modeEl = document.getElementById('manual-mode');
    const selectEl = document.getElementById('manual-flow-select');
    if (!modeEl || !selectEl) return;
    try {
        const [flowsRes, modeRes] = await Promise.all([
            fetch('/api/v1/flows'),
            fetch('/api/v1/flows/active-mode')
        ]);

        const flowsData = flowsRes.ok ? await flowsRes.json() : [];
        const modeData = modeRes.ok ? await modeRes.json() : { mode: 'smb' };
        const activeMode = (modeData.mode || 'smb').toLowerCase();
        modeEl.className = 'manual-mode ' + (activeMode === 'local' ? 'local' : 'smb');
        modeEl.textContent = 'Modo activo: ' + (activeMode === 'local' ? 'Local' : 'SMB/FTP');

        MANUAL_FLOWS = (flowsData || [])
            .filter(flow => flow.enabled !== false)
            .filter(flow => (flow.source_mode || 'smb') === activeMode)
            .sort((a, b) => getFlowLabel(a).localeCompare(getFlowLabel(b), 'es'));

        if (!MANUAL_FLOWS.length) {
            selectEl.innerHTML = '<option value="">Sin flujos activos para este modo</option>';
            setManualButtonsDisabled(true);
            renderManualDraftState(null);
            return;
        }

        selectEl.innerHTML = MANUAL_FLOWS.map(flow => {
            const source = flow.source_folder ? ` [${flow.source_folder}]` : '';
            return `<option value="${flow.id}">${escapeHtml(getFlowLabel(flow) + source)}</option>`;
        }).join('');
        selectEl.onchange = () => { loadManualDraftState(); };
        setManualButtonsDisabled(false);
        await loadManualDraftState();
    } catch (_e) {
        modeEl.className = 'manual-mode';
        modeEl.textContent = 'Modo: error';
        selectEl.innerHTML = '<option value="">No se pudieron cargar los flujos</option>';
        setManualButtonsDisabled(true);
        setManualResult('err', 'No se pudo cargar la lista de flujos.');
        renderManualDraftState(null);
    }
}

async function uploadManualFiles() {
    const flowId = getSelectedFlowId();
    const input = document.getElementById('manual-files');
    if (!flowId) {
        setManualResult('err', 'Selecciona un flujo activo.');
        return;
    }
    if (!input.files || !input.files.length) {
        setManualResult('err', 'Selecciona uno o varios archivos para subir.');
        return;
    }

    const form = new FormData();
    for (const file of input.files) {
        form.append('files', file);
    }
    setManualResult('loading', 'Subiendo archivos al borrador manual...');

    try {
        const res = await fetch(`/api/v1/flows/${flowId}/manual/upload`, { method: 'POST', body: form });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            const rejected = (data.rejected || []).length;
            const msg = rejected
                ? `${(data.saved || []).length} archivo(s) cargado(s). ${rejected} rechazado(s) por extension.`
                : `${(data.saved || []).length} archivo(s) cargado(s).`;
            setManualResult('ok', msg);
            input.value = '';
            await loadManualDraftState();
        } else {
            setManualResult('err', data.detail || data.message || 'Error subiendo archivos.');
        }
    } catch (_e) {
        setManualResult('err', 'Error de conexion subiendo archivos.');
    }
}

async function openExistingManualPreview() {
    const flowId = getSelectedFlowId();
    if (!flowId) {
        setManualResult('err', 'Selecciona un flujo activo.');
        return;
    }

    setManualResult('loading', 'Cargando previsualizacion pendiente...');
    try {
        const res = await fetch(`/api/v1/flows/${flowId}/manual/preview-current`);
        const data = await res.json();
        if (res.ok && data.success !== false) {
            const subtitle = data.batch_id
                ? `Batch ${data.batch_id} · ${data.summary || 'Previsualizacion pendiente'}`
                : (data.summary || 'Previsualizacion pendiente');
            openPreviewModal(data.preview_json || '', subtitle);
            setManualResult('ok', 'Previsualizacion cargada.');
        } else {
            setManualResult('err', data.detail || data.message || 'No hay previsualizacion pendiente para mostrar.');
        }
    } catch (_e) {
        setManualResult('err', 'Error de conexion cargando la previsualizacion.');
    }
}

function setPreviewEditMode(enabled) {
    previewModalState.editable = Boolean(enabled);
    const pre = document.getElementById('preview-json');
    const editor = document.getElementById('preview-json-editor');
    const saveBtn = document.getElementById('preview-save-btn');
    const cancelBtn = document.getElementById('preview-cancel-btn');
    const editBtn = document.getElementById('preview-edit-btn');

    if (enabled) {
        pre.style.display = 'none';
        editor.style.display = 'block';
        saveBtn.style.display = 'inline-flex';
        cancelBtn.style.display = 'inline-flex';
        editBtn.style.display = 'none';
        editor.value = pre.textContent || '';
    } else {
        pre.style.display = 'block';
        editor.style.display = 'none';
        saveBtn.style.display = 'none';
        cancelBtn.style.display = 'none';
        editBtn.style.display = previewModalState.groupId ? 'inline-flex' : 'none';
    }
}

function setPreviewStatus(kind, message) {
    const el = document.getElementById('preview-status');
    if (!kind || !message) {
        el.className = 'preview-status';
        el.textContent = '';
        return;
    }
    el.className = 'preview-status ' + kind;
    el.textContent = message;
}

function setPreviewAiBusy(busy) {
    document.getElementById('preview-ai-btn').disabled = busy;
    document.getElementById('preview-ai-input').disabled = busy;
    document.getElementById('preview-ai-cancel-btn').style.display = busy ? 'inline-flex' : 'none';
    if (busy) {
        document.getElementById('preview-ai-btn').textContent = 'Aplicando...';
    } else {
        document.getElementById('preview-ai-btn').textContent = 'Aplicar con IA';
    }
}

function startAiProgressStatus() {
    stopAiProgressStatus();
    aiRequestState.startedAt = Date.now();
    setPreviewStatus('loading', 'Aplicando cambios con IA... 0s');
    aiRequestState.timer = setInterval(() => {
        const elapsed = Math.max(0, Math.floor((Date.now() - aiRequestState.startedAt) / 1000));
        setPreviewStatus('loading', `Aplicando cambios con IA... ${elapsed}s`);
    }, 1000);
}

function stopAiProgressStatus() {
    if (aiRequestState.timer) {
        clearInterval(aiRequestState.timer);
        aiRequestState.timer = null;
    }
}

function cancelAiPreviewChanges() {
    if (aiRequestState.controller) {
        aiRequestState.controller.abort();
    }
    stopAiProgressStatus();
    setPreviewAiBusy(false);
    setPreviewStatus('err', 'Solicitud IA cancelada por el usuario.');
}

function updatePreviewComparePanel() {
    const compareBtn = document.getElementById('preview-compare-btn');
    const hasDiff = Boolean(previewModalState.previousJson && previewModalState.previousJson !== previewModalState.originalJson);
    compareBtn.style.display = hasDiff ? 'inline-flex' : 'none';
    if (!hasDiff) {
        hidePreviewCompare();
        return;
    }
    document.getElementById('preview-compare-before').textContent = previewModalState.previousJson || '';
    document.getElementById('preview-compare-after').textContent = previewModalState.originalJson || '';
}

function togglePreviewCompare() {
    const box = document.getElementById('preview-compare');
    box.classList.toggle('open');
}

function hidePreviewCompare() {
    document.getElementById('preview-compare').classList.remove('open');
}

function openPreviewModal(jsonText, subtitle, options = {}) {
    previewModalState.groupId = options.groupId || null;
    previewModalState.originalJson = jsonText || '';
    previewModalState.previousJson = '';
    document.getElementById('preview-subtitle').textContent = subtitle || 'Resultado del ultimo preview';
    document.getElementById('preview-json').textContent = jsonText || '';
    document.getElementById('preview-json-editor').value = jsonText || '';

    const groupScoped = Boolean(previewModalState.groupId);
    document.getElementById('preview-edit-btn').style.display = groupScoped ? 'inline-flex' : 'none';
    document.getElementById('preview-recompile-btn').style.display = groupScoped ? 'inline-flex' : 'none';
    document.getElementById('preview-delete-btn').style.display = groupScoped ? 'inline-flex' : 'none';
    document.getElementById('preview-ai-btn').style.display = groupScoped ? 'inline-flex' : 'none';
    document.getElementById('preview-ai-input').style.display = groupScoped ? 'block' : 'none';
    document.getElementById('preview-ai-row').style.display = groupScoped ? 'flex' : 'none';
    document.getElementById('preview-ai-input').value = '';

    if (aiRequestState.controller) {
        aiRequestState.controller.abort();
        aiRequestState.controller = null;
    }
    stopAiProgressStatus();
    setPreviewEditMode(false);
    setPreviewStatus('', '');
    setPreviewAiBusy(false);
    updatePreviewComparePanel();
    document.getElementById('preview-modal-backdrop').classList.add('open');
}

function closePreviewModal(event) {
    if (event) event.stopPropagation();
    previewModalState.groupId = null;
    previewModalState.originalJson = '';
    previewModalState.previousJson = '';
    if (aiRequestState.controller) {
        aiRequestState.controller.abort();
        aiRequestState.controller = null;
    }
    stopAiProgressStatus();
    setPreviewEditMode(false);
    setPreviewStatus('', '');
    setPreviewAiBusy(false);
    hidePreviewCompare();
    document.getElementById('preview-modal-backdrop').classList.remove('open');
}

function enablePreviewEdit() {
    if (!previewModalState.groupId) return;
    setPreviewEditMode(true);
}

function cancelPreviewEdit() {
    document.getElementById('preview-json-editor').value = previewModalState.originalJson || '';
    setPreviewEditMode(false);
}

async function savePreviewJson() {
    const groupId = previewModalState.groupId;
    if (!groupId) return;
    const text = document.getElementById('preview-json-editor').value || '';
    try {
        const res = await fetch(`/api/v1/flows/manual/inbox/groups/${groupId}/preview-json`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ preview_json: text })
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            previewModalState.previousJson = previewModalState.originalJson || '';
            previewModalState.originalJson = data.preview_json || text;
            document.getElementById('preview-json').textContent = previewModalState.originalJson;
            setPreviewEditMode(false);
            updatePreviewComparePanel();
            setTreeResult('ok', data.message || 'Preview guardada.');
            await loadTreeGroups();
        } else {
            setTreeResult('err', data.detail || data.message || 'No se pudo guardar el JSON.');
        }
    } catch (_e) {
        setTreeResult('err', 'Error de conexion guardando el JSON.');
    }
}

async function recompilePreviewGroup() {
    const groupId = previewModalState.groupId;
    if (!groupId) return;
    try {
        const res = await fetch(`/api/v1/flows/manual/inbox/groups/${groupId}/recompile`, { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            previewModalState.previousJson = previewModalState.originalJson || '';
            previewModalState.originalJson = data.preview_json || '';
            document.getElementById('preview-json').textContent = previewModalState.originalJson;
            document.getElementById('preview-json-editor').value = previewModalState.originalJson;
            setPreviewEditMode(false);
            updatePreviewComparePanel();
            setTreeResult('ok', data.message || 'Preview recompilada.');
            await loadTreeGroups();
        } else {
            setTreeResult('err', data.detail || data.message || 'No se pudo recompilar la preview.');
        }
    } catch (_e) {
        setTreeResult('err', 'Error de conexion recompilando la preview.');
    }
}

async function applyAiPreviewChanges() {
    const groupId = previewModalState.groupId;
    if (!groupId) return;
    const instructions = (document.getElementById('preview-ai-input').value || '').trim();
    if (!instructions) {
        setPreviewStatus('err', 'Escribe una instruccion para aplicar cambios con IA.');
        return;
    }

    setPreviewStatus('loading', 'Comprobando conexion IA...');
    try {
        const healthRes = await fetch('/api/v1/flows/manual/inbox/ai-health');
        const health = await healthRes.json();
        if (!healthRes.ok || health.success === false) {
            const msg = health.detail || health.message || 'La conexion IA no esta lista para aplicar cambios.';
            setPreviewStatus('err', msg);
            setTreeResult('err', msg);
            return;
        }
    } catch (_e) {
        setPreviewStatus('err', 'No se pudo verificar la conexion IA antes de aplicar cambios.');
        return;
    }

    aiRequestState.controller = new AbortController();
    startAiProgressStatus();
    setPreviewAiBusy(true);
    try {
        const res = await fetch(`/api/v1/flows/manual/inbox/groups/${groupId}/ai-adjust`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instructions }),
            signal: aiRequestState.controller.signal,
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            const nextJson = data.preview_json || previewModalState.originalJson || '';
            previewModalState.previousJson = previewModalState.originalJson || '';
            previewModalState.originalJson = nextJson;
            document.getElementById('preview-json').textContent = previewModalState.originalJson;
            document.getElementById('preview-json-editor').value = previewModalState.originalJson;
            setPreviewEditMode(false);
            updatePreviewComparePanel();
            document.getElementById('preview-ai-input').value = '';
            setPreviewStatus('ok', data.message || 'Cambios de IA aplicados.');
            setTreeResult('ok', data.message || 'Cambios de IA aplicados.');
            await loadTreeGroups();
        } else {
            const msg = data.detail || data.message || 'No se pudieron aplicar cambios con IA.';
            setPreviewStatus('err', msg);
            setTreeResult('err', msg);
        }
    } catch (e) {
        if (e && e.name === 'AbortError') {
            setPreviewStatus('err', 'Solicitud IA cancelada por el usuario.');
            setTreeResult('err', 'Solicitud IA cancelada por el usuario.');
        } else {
            setPreviewStatus('err', 'Error de conexion aplicando cambios con IA.');
            setTreeResult('err', 'Error de conexion aplicando cambios con IA.');
        }
    } finally {
        aiRequestState.controller = null;
        stopAiProgressStatus();
        setPreviewAiBusy(false);
    }
}

async function deletePreviewGroup() {
    const groupId = previewModalState.groupId;
    if (!groupId) return;
    if (!confirm('Se borrara este grupo y sus archivos de staging manual. Esta accion no se puede deshacer.')) {
        return;
    }
    try {
        const res = await fetch('/api/v1/flows/manual/inbox/groups/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_ids: [groupId] })
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            closePreviewModal();
            setTreeResult('ok', data.message || 'Grupo eliminado.');
            await loadTreeGroups();
        } else {
            setTreeResult('err', data.detail || data.message || 'No se pudo borrar el grupo.');
        }
    } catch (_e) {
        setTreeResult('err', 'Error de conexion borrando el grupo.');
    }
}

async function runManualPreview() {
    const flowId = getSelectedFlowId();
    if (!flowId) {
        setManualResult('err', 'Selecciona un flujo activo.');
        return;
    }
    setManualResult('loading', 'Procesando preview del borrador manual...');
    openActivityModal(flowId, { startedAfter: new Date().toISOString() });
    try {
        const res = await fetch(`/api/v1/flows/${flowId}/manual/preview`, { method: 'POST' });
        const data = await res.json();
        if (data.batch_id) {
            activityState.batchId = data.batch_id;
            fetchActivityEvents();
        }
        if (res.ok && data.success !== false) {
            setManualResult('ok', data.message || 'Preview generado correctamente.', data.batch_id);
            openPreviewModal(data.preview_json || '', `Batch ${data.batch_id || '-'} · ${data.articles_count || 0} articulo(s)`);
            await loadManualDraftState();
            await refreshBatchesFromApi();
        } else {
            setManualResult('err', data.detail || data.message || 'Error creando preview.', data.batch_id);
        }
    } catch (_e) {
        setManualResult('err', 'Error de conexion ejecutando preview.');
    }
}

async function acceptManualPreview() {
    const flowId = getSelectedFlowId();
    if (!flowId) return;
    setManualResult('loading', 'Aceptando preview y anadiendo al borrador final...');
    try {
        const res = await fetch(`/api/v1/flows/${flowId}/manual/accept`, { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            setManualResult('ok', data.message || 'Preview aceptada.');
            await loadManualDraftState();
        } else {
            setManualResult('err', data.detail || data.message || 'No se pudo aceptar la preview.');
        }
    } catch (_e) {
        setManualResult('err', 'Error de conexion aceptando preview.');
    }
}

async function discardManualPreview() {
    const flowId = getSelectedFlowId();
    if (!flowId) return;
    setManualResult('loading', 'Descartando preview pendiente...');
    try {
        const res = await fetch(`/api/v1/flows/${flowId}/manual/discard`, { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            setManualResult('ok', data.message || 'Preview descartada.');
            await loadManualDraftState();
        } else {
            setManualResult('err', data.detail || data.message || 'No se pudo descartar la preview.');
        }
    } catch (_e) {
        setManualResult('err', 'Error de conexion descartando preview.');
    }
}

async function finalizeManualExport() {
    const flowId = getSelectedFlowId();
    if (!flowId) return;
    setManualResult('loading', 'Generando exportacion final de los items verificados...');
    try {
        const res = await fetch(`/api/v1/flows/${flowId}/manual/finalize-export`, { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            setManualResult('ok', data.message || 'Exportacion final completada.');
            await loadManualDraftState();
            await loadManualFlows();
        } else {
            setManualResult('err', data.detail || data.message || 'No se pudo crear la exportacion final.');
        }
    } catch (_e) {
        setManualResult('err', 'Error de conexion al crear exportacion final.');
    }
}

async function resetManualDraft() {
    const flowId = getSelectedFlowId();
    if (!flowId) return;

    if (!confirm('Se reiniciara el borrador manual del flujo seleccionado. Se eliminaran archivos pendientes y elementos verificados de esta sesion.')) {
        return;
    }

    setManualResult('loading', 'Reiniciando borrador manual...');
    try {
        const res = await fetch(`/api/v1/flows/${flowId}/manual/reset`, { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            setManualResult('ok', data.message || 'Borrador manual reiniciado.');
            document.getElementById('manual-files').value = '';
            await loadManualDraftState();
            await loadTreeGroups();
        } else {
            setManualResult('err', data.detail || data.message || 'No se pudo reiniciar el borrador manual.');
        }
    } catch (_e) {
        setManualResult('err', 'Error de conexion reiniciando el borrador manual.');
    }
}

async function runManualCleanup(dryRun, retryTargets = null) {
    const mode = (document.getElementById('manual-cleanup-mode').value || 'soft').toLowerCase();
    if (!dryRun) {
        const msg = mode === 'full'
            ? 'Se ejecutara limpieza COMPLETA de working y temp. No se eliminaran lotes historicos de base de datos. Continuar?'
            : 'Se ejecutara limpieza SUAVE (solo temporales manuales). Continuar?';
        if (!retryTargets && !confirm(msg)) {
            return;
        }
    }

    setManualResult('loading', dryRun ? 'Calculando previsualizacion de limpieza...' : 'Ejecutando limpieza de temporales y trabajos...');
    setManualButtonsDisabled(true);
    try {
        const res = await fetch('/api/v1/flows/manual/maintenance/cleanup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode, dry_run: dryRun, retry_targets: retryTargets || undefined })
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            if (dryRun) {
                setManualResult('ok', `${data.message || 'Previsualizacion lista.'} Modo: ${data.mode || mode}. Planificados: ${data.planned || 0}.`);
            } else {
                setManualResult('ok', `${data.message || 'Limpieza completada.'} Modo: ${data.mode || mode}. Eliminados: ${data.removed || 0}.`);
            }
            renderCleanupPreviewDetails(data);
        } else {
            setManualResult('err', data.detail || data.message || 'No se pudo completar la limpieza.');
            hideCleanupPreviewDetails();
        }
        if (typeof loadManualDraftState === 'function') {
            await loadManualDraftState();
        }
        if (typeof loadTreeGroups === 'function') {
            await loadTreeGroups();
        }
        if (typeof refreshBatchesFromApi === 'function') {
            await refreshBatchesFromApi();
        }
    } catch (_e) {
        setManualResult('err', 'Error de conexion durante la limpieza de temporales.');
        hideCleanupPreviewDetails();
    } finally {
        setManualButtonsDisabled(false);
    }
}

async function previewManualCleanup() {
    await runManualCleanup(true);
}

async function cleanupManualTempAndWorking() {
    await runManualCleanup(false);
}

async function runSelectedFlow(withExport) {
    const flowId = getSelectedFlowId();
    if (!flowId) {
        setManualResult('err', 'Selecciona un flujo activo.');
        return;
    }

    const actionLabel = withExport ? 'Ejecutando y exportando flujo...' : 'Ejecutando flujo...';
    setManualResult('loading', actionLabel);
    setManualButtonsDisabled(true);
    openActivityModal(flowId, { startedAfter: new Date().toISOString() });

    try {
        const endpoint = withExport ? `/api/v1/flows/${flowId}/export` : `/api/v1/flows/${flowId}/run`;
        const res = await fetch(endpoint, { method: 'POST' });
        const raw = await res.text();
        let data;
        try {
            data = JSON.parse(raw);
        } catch (_e) {
            data = { success: false, message: raw || 'Respuesta invalida del servidor' };
        }

        if (data.batch_id) {
            activityState.batchId = data.batch_id;
            fetchActivityEvents();
        }

        if (res.ok && data.success !== false) {
            const message = withExport
                ? `Flujo ejecutado y exportado. ${data.message || ''}`.trim()
                : `Flujo ejecutado. ${data.message || ''}`.trim();
            setManualResult('ok', message, data.batch_id);
        } else {
            setManualResult('err', data.detail || data.message || 'Error al ejecutar el flujo.', data.batch_id);
        }
    } catch (_e) {
        setManualResult('err', 'Error de conexion con el servidor.');
    } finally {
        setManualButtonsDisabled(false);
        await loadManualFlows();
        await refreshBatchesFromApi();
    }
}
