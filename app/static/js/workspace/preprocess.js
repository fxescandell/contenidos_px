async function fetchActiveFlowsForWorkspace() {
    const [flowsRes, modeRes] = await Promise.all([
        fetch('/api/v1/flows'),
        fetch('/api/v1/flows/active-mode')
    ]);
    const flowsData = flowsRes.ok ? await flowsRes.json() : [];
    const modeData = modeRes.ok ? await modeRes.json() : { mode: 'smb' };
    const activeMode = (modeData.mode || 'smb').toLowerCase();
    const activeFlows = (flowsData || [])
        .filter(flow => flow.enabled !== false)
        .filter(flow => (flow.source_mode || 'smb') === activeMode)
        .sort((a, b) => getFlowLabel(a).localeCompare(getFlowLabel(b), 'es'));
    return { activeMode, flows: activeFlows };
}

function renderPreprocessAnalysis(analysis) {
    const box = document.getElementById('prep-analysis');
    if (!box) return;
    if (!analysis || !analysis.files_processed) {
        box.textContent = 'Sin analisis todavia.';
        return;
    }
    const lines = [];
    lines.push(`Archivos procesados: ${analysis.files_processed}`);
    lines.push(`Items OCR/extraccion: ${(analysis.items || []).length}`);
    if ((analysis.warnings || []).length) {
        lines.push('Warnings:');
        (analysis.warnings || []).slice(0, 8).forEach(item => lines.push(`- ${item}`));
    }
    const previews = (analysis.items || []).slice(0, 8);
    if (previews.length) {
        lines.push('');
        lines.push('Resumen por archivo:');
        previews.forEach(item => lines.push(`- ${item.file} [${item.method}] conf=${(item.confidence || 0).toFixed(2)}`));
    }
    box.textContent = lines.join('\n');
}

function applyPreprocessState(state) {
    if (!state) return;
    preprocessSessionId = state.id || preprocessSessionId;
    const sid = document.getElementById('prep-session-id');
    if (sid) sid.value = preprocessSessionId || '';
    const markdownEl = document.getElementById('prep-markdown');
    if (markdownEl) markdownEl.value = state.generated_markdown || '';
    renderPreprocessAnalysis(state.analysis || {});
}

async function loadPreprocessFlowOptions() {
    try {
        const { activeMode, flows } = await fetchActiveFlowsForWorkspace();
        const modeEl = document.getElementById('prep-active-mode');
        if (modeEl) {
            modeEl.className = 'manual-mode ' + (activeMode === 'local' ? 'local' : 'smb');
            modeEl.textContent = 'Modo activo: ' + (activeMode === 'local' ? 'Local' : 'SMB/FTP');
        }
        const select = document.getElementById('prep-flow-select');
        if (!select) return;
        if (!flows.length) {
            select.innerHTML = '<option value="">Sin flujos activos para este modo</option>';
            return;
        }
        select.innerHTML = '<option value="">Selecciona flujo destino...</option>' + flows
            .map(flow => `<option value="${flow.id}">${escapeHtml(getFlowLabel(flow))}</option>`)
            .join('');
    } catch (_e) {
        setModuleStatus('prep-status', 'err', 'No se pudieron cargar los flujos activos para preprocesado.');
    }
}

async function startPreprocessSession() {
    setModuleStatus('prep-status', 'loading', 'Creando sesion de preprocesado...');
    try {
        const res = await fetch('/api/v1/flows/workspace/preprocess/sessions', { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            applyPreprocessState(data.session || {});
            setModuleStatus('prep-status', 'ok', 'Sesion de preprocesado creada.');
        } else {
            setModuleStatus('prep-status', 'err', data.detail || data.message || 'No se pudo crear la sesion de preprocesado.');
        }
    } catch (_e) {
        setModuleStatus('prep-status', 'err', 'Error de conexion creando sesion de preprocesado.');
    }
}

async function loadPreprocessSessionState() {
    const sid = (document.getElementById('prep-session-id')?.value || '').trim();
    if (!sid) {
        setModuleStatus('prep-status', 'err', 'No hay sesion para recargar.');
        return;
    }
    try {
        const res = await fetch(`/api/v1/flows/workspace/preprocess/sessions/${sid}`);
        const data = await res.json();
        if (res.ok && data.success !== false) {
            applyPreprocessState(data.session || {});
            setModuleStatus('prep-status', 'ok', 'Sesion recargada.');
        } else {
            setModuleStatus('prep-status', 'err', data.detail || data.message || 'No se pudo recargar la sesion.');
        }
    } catch (_e) {
        setModuleStatus('prep-status', 'err', 'Error de conexion recargando sesion.');
    }
}

async function uploadPreprocessFiles() {
    const sid = (document.getElementById('prep-session-id')?.value || '').trim();
    if (!sid) {
        setModuleStatus('prep-status', 'err', 'Inicia una sesion de preprocesado antes de subir archivos.');
        return;
    }
    const input = document.getElementById('prep-files');
    const files = input && input.files ? Array.from(input.files) : [];
    if (!files.length) {
        setModuleStatus('prep-status', 'err', 'Selecciona archivos para subir al preprocesado.');
        return;
    }
    const form = new FormData();
    files.forEach(file => form.append('files', file));
    setModuleStatus('prep-status', 'loading', 'Subiendo archivos de preprocesado...');
    try {
        const res = await fetch(`/api/v1/flows/workspace/preprocess/sessions/${sid}/upload`, { method: 'POST', body: form });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            setModuleStatus('prep-status', 'ok', `${(data.saved || []).length} archivo(s) subido(s) al preprocesado.`);
            input.value = '';
        } else {
            setModuleStatus('prep-status', 'err', data.detail || data.message || 'No se pudieron subir los archivos.');
        }
    } catch (_e) {
        setModuleStatus('prep-status', 'err', 'Error de conexion subiendo archivos.');
    }
}

async function analyzePreprocessSession() {
    const sid = (document.getElementById('prep-session-id')?.value || '').trim();
    if (!sid) {
        setModuleStatus('prep-status', 'err', 'Inicia una sesion de preprocesado antes de analizar.');
        return;
    }
    setModuleStatus('prep-status', 'loading', 'Analizando fuentes (OCR/extraccion)...');
    try {
        const res = await fetch(`/api/v1/flows/workspace/preprocess/sessions/${sid}/analyze`, { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            renderPreprocessAnalysis(data.analysis || {});
            setModuleStatus('prep-status', 'ok', data.message || 'Analisis completado.');
        } else {
            setModuleStatus('prep-status', 'err', data.detail || data.message || 'No se pudo analizar la sesion.');
        }
    } catch (_e) {
        setModuleStatus('prep-status', 'err', 'Error de conexion durante el analisis.');
    }
}

async function generatePreprocessMarkdown() {
    const sid = (document.getElementById('prep-session-id')?.value || '').trim();
    const flowId = (document.getElementById('prep-flow-select')?.value || '').trim();
    const municipality = (document.getElementById('prep-municipality')?.value || '').trim();
    const category = (document.getElementById('prep-category')?.value || '').trim();
    if (!sid) {
        setModuleStatus('prep-status', 'err', 'Inicia una sesion de preprocesado antes de generar markdown.');
        return;
    }
    if (!flowId || !municipality || !category) {
        setModuleStatus('prep-status', 'err', 'Selecciona flujo, municipio y categoria para generar markdown.');
        return;
    }
    setModuleStatus('prep-status', 'loading', 'Generando markdown estructurado...');
    try {
        const payload = {
            flow_id: flowId,
            municipality,
            category,
            enable_web_enrichment: Boolean(document.getElementById('prep-enable-web')?.checked),
            web_query: document.getElementById('prep-web-query')?.value || '',
        };
        const res = await fetch(`/api/v1/flows/workspace/preprocess/sessions/${sid}/generate-md`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            const md = data.markdown || '';
            document.getElementById('prep-markdown').value = md;
            setModuleStatus('prep-status', 'ok', data.message || 'Markdown generado.');
        } else {
            setModuleStatus('prep-status', 'err', data.detail || data.message || 'No se pudo generar markdown.');
        }
    } catch (_e) {
        setModuleStatus('prep-status', 'err', 'Error de conexion generando markdown.');
    }
}

async function packagePreprocessSession() {
    const sid = (document.getElementById('prep-session-id')?.value || '').trim();
    if (!sid) {
        setModuleStatus('prep-status', 'err', 'Inicia una sesion antes de empaquetar.');
        return;
    }
    setModuleStatus('prep-status', 'loading', 'Empaquetando articulo preprocesado...');
    try {
        const res = await fetch(`/api/v1/flows/workspace/preprocess/sessions/${sid}/package`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            setModuleStatus('prep-status', 'ok', `${data.message || 'Paquete generado.'} ${data.package_path || ''}`);
        } else {
            setModuleStatus('prep-status', 'err', data.detail || data.message || 'No se pudo empaquetar el articulo.');
        }
    } catch (_e) {
        setModuleStatus('prep-status', 'err', 'Error de conexion empaquetando articulo.');
    }
}

async function publishPreprocessSession() {
    const sid = (document.getElementById('prep-session-id')?.value || '').trim();
    const flowId = (document.getElementById('prep-flow-select')?.value || '').trim();
    if (!sid || !flowId) {
        setModuleStatus('prep-status', 'err', 'Necesitas sesion y flujo destino para publicar.');
        return;
    }
    setModuleStatus('prep-status', 'loading', 'Publicando paquete en carpeta de entrada del flujo...');
    try {
        const res = await fetch(`/api/v1/flows/workspace/preprocess/sessions/${sid}/publish`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ flow_id: flowId }),
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            setModuleStatus('prep-status', 'ok', `${data.message || 'Publicado correctamente.'} ${data.published_input_path || ''}`);
        } else {
            setModuleStatus('prep-status', 'err', data.detail || data.message || 'No se pudo publicar en la carpeta de entrada.');
        }
    } catch (_e) {
        setModuleStatus('prep-status', 'err', 'Error de conexion publicando el paquete.');
    }
}
