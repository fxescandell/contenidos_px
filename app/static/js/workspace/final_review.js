function qaGetField(data, keys) {
    for (const key of keys) {
        if (Object.prototype.hasOwnProperty.call(data || {}, key)) return data[key] || '';
    }
    return '';
}

function renderQaArticlesList() {
    const list = document.getElementById('qa-articles-list');
    if (!list) return;
    if (!qaArticles.length) {
        list.innerHTML = '<div class="qa-item">No hay articulos cargados.</div>';
        return;
    }
    list.innerHTML = qaArticles.map(article => {
        const data = article.data || {};
        const title = qaGetField(data, ['title', 'post_title', 'final_title']) || '(Sin titulo)';
        const issues = article.issues || [];
        const badge = issues.length ? ` · ${issues.length} issue(s)` : '';
        const activeClass = qaSelectedArticleId === article.id ? 'active' : '';
        return `<div class="qa-item ${activeClass}" onclick="selectQaArticle('${article.id}')"><strong>${escapeHtml(title)}</strong><br><span style="font-size:11px; color:#64748b;">ID ${escapeHtml(article.id)}${escapeHtml(badge)}</span></div>`;
    }).join('');
}

function renderQaSelectedArticle() {
    const article = qaArticles.find(item => item.id === qaSelectedArticleId);
    const titleInput = document.getElementById('qa-article-title');
    const summaryInput = document.getElementById('qa-article-summary');
    const bodyInput = document.getElementById('qa-article-body');
    const issuesBox = document.getElementById('qa-issues');
    if (!titleInput || !summaryInput || !bodyInput || !issuesBox) return;

    if (!article) {
        titleInput.value = '';
        summaryInput.value = '';
        bodyInput.value = '';
        issuesBox.textContent = 'Selecciona un articulo para editar.';
        return;
    }

    const data = article.data || {};
    titleInput.value = qaGetField(data, ['title', 'post_title', 'final_title']);
    summaryInput.value = qaGetField(data, ['summary', 'excerpt', 'final_summary', 'post_excerpt']);
    bodyInput.value = qaGetField(data, ['body_html', 'content', 'post_content', 'final_body_html']);
    const issues = article.issues || [];
    issuesBox.textContent = issues.length
        ? issues.map(issue => `[${issue.severity || 'info'}] ${issue.code || '-'}: ${issue.message || ''}`).join('\n')
        : 'Sin incidencias detectadas.';
}

function selectQaArticle(articleId) {
    qaSelectedArticleId = articleId;
    renderQaArticlesList();
    renderQaSelectedArticle();
}

async function startQaSession() {
    setModuleStatus('qa-status', 'loading', 'Creando sesion de revision final...');
    try {
        const res = await fetch('/api/v1/flows/workspace/final-review/sessions', { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            qaSessionId = data.session.id;
            const sid = document.getElementById('qa-session-id');
            if (sid) sid.value = qaSessionId;
            qaArticles = [];
            qaSelectedArticleId = null;
            renderQaArticlesList();
            renderQaSelectedArticle();
            setModuleStatus('qa-status', 'ok', 'Sesion QA creada.');
        } else {
            setModuleStatus('qa-status', 'err', data.detail || data.message || 'No se pudo crear la sesion QA.');
        }
    } catch (_e) {
        setModuleStatus('qa-status', 'err', 'Error de conexion creando sesion QA.');
    }
}

async function loadQaSessionState() {
    const sid = (document.getElementById('qa-session-id')?.value || '').trim();
    if (!sid) {
        setModuleStatus('qa-status', 'err', 'No hay sesion QA para recargar.');
        return;
    }
    try {
        const [sessionRes, articlesRes] = await Promise.all([
            fetch(`/api/v1/flows/workspace/final-review/sessions/${sid}`),
            fetch(`/api/v1/flows/workspace/final-review/sessions/${sid}/articles`),
        ]);
        const sessionData = await sessionRes.json();
        const articlesData = await articlesRes.json();
        if (!sessionRes.ok || sessionData.success === false || !articlesRes.ok || articlesData.success === false) {
            setModuleStatus('qa-status', 'err', sessionData.detail || sessionData.message || articlesData.detail || articlesData.message || 'No se pudo recargar la sesion QA.');
            return;
        }
        qaSessionId = sid;
        qaArticles = articlesData.articles || [];
        qaSelectedArticleId = qaArticles.length ? qaArticles[0].id : null;
        renderQaArticlesList();
        renderQaSelectedArticle();
        setModuleStatus('qa-status', 'ok', 'Sesion QA recargada.');
    } catch (_e) {
        setModuleStatus('qa-status', 'err', 'Error de conexion recargando sesion QA.');
    }
}

async function uploadQaExportFile() {
    const sid = (document.getElementById('qa-session-id')?.value || '').trim();
    if (!sid) {
        setModuleStatus('qa-status', 'err', 'Inicia sesion QA antes de cargar export.');
        return;
    }
    const fileInput = document.getElementById('qa-file');
    const file = fileInput && fileInput.files ? fileInput.files[0] : null;
    if (!file) {
        setModuleStatus('qa-status', 'err', 'Selecciona un JSON o CSV para cargar en QA.');
        return;
    }
    setModuleStatus('qa-status', 'loading', 'Cargando export para revision...');
    try {
        const form = new FormData();
        form.append('file', file);
        const res = await fetch(`/api/v1/flows/workspace/final-review/sessions/${sid}/load-export`, {
            method: 'POST',
            body: form,
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            fileInput.value = '';
            await loadQaSessionState();
            setModuleStatus('qa-status', 'ok', data.message || 'Export cargado en QA.');
        } else {
            setModuleStatus('qa-status', 'err', data.detail || data.message || 'No se pudo cargar el export.');
        }
    } catch (_e) {
        setModuleStatus('qa-status', 'err', 'Error de conexion cargando export en QA.');
    }
}

async function runQaChecks() {
    const sid = (document.getElementById('qa-session-id')?.value || '').trim();
    if (!sid) {
        setModuleStatus('qa-status', 'err', 'Inicia sesion QA antes de ejecutar checks.');
        return;
    }
    setModuleStatus('qa-status', 'loading', 'Ejecutando checks de calidad...');
    try {
        const data = await runQaChecksSilently(sid);
        const checks = data.checks || {};
        const issuesTotal = checks.issues_total || 0;
        const errorsTotal = checks.errors_total || 0;
        const warningsTotal = checks.warnings || 0;
        const dupBodies = checks.duplicates || 0;
        const dupTitles = checks.title_duplicates || 0;
        const kind = errorsTotal > 0 ? 'err' : (issuesTotal > 0 ? 'loading' : 'ok');
        const statusText = issuesTotal > 0
            ? `Checks completados con incidencias. Errores: ${errorsTotal}, warnings: ${warningsTotal}, duplicados cuerpo: ${dupBodies}, duplicados titulo: ${dupTitles}.`
            : 'Checks completados sin incidencias.';
        setModuleStatus('qa-status', kind, statusText);
    } catch (_e) {
        setModuleStatus('qa-status', 'err', 'Error de conexion ejecutando checks QA.');
    }
}

async function runQaChecksSilently(sessionId) {
    const res = await fetch(`/api/v1/flows/workspace/final-review/sessions/${sessionId}/run-checks`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok || data.success === false) {
        throw new Error(data.detail || data.message || 'No se pudieron ejecutar los checks.');
    }
    qaArticles = data.articles || qaArticles;
    if (!qaSelectedArticleId && qaArticles.length) qaSelectedArticleId = qaArticles[0].id;
    renderQaArticlesList();
    renderQaSelectedArticle();
    return data;
}

function qaSyncSuffix(sync) {
    if (!sync || (!sync.json_path && !sync.csv_path)) return '';
    return ` Sync JSON: ${sync.json_path || '-'} | CSV: ${sync.csv_path || '-'}`;
}

async function saveQaArticleEdits() {
    const sid = (document.getElementById('qa-session-id')?.value || '').trim();
    if (!sid || !qaSelectedArticleId) {
        setModuleStatus('qa-status', 'err', 'Selecciona sesion y articulo para guardar cambios.');
        return;
    }
    const payload = {
        title: document.getElementById('qa-article-title')?.value || '',
        summary: document.getElementById('qa-article-summary')?.value || '',
        body_html: document.getElementById('qa-article-body')?.value || '',
    };
    setModuleStatus('qa-status', 'loading', 'Guardando cambios del articulo...');
    try {
        const res = await fetch(`/api/v1/flows/workspace/final-review/sessions/${sid}/articles/${qaSelectedArticleId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            await loadQaSessionState();
            setModuleStatus('qa-status', 'ok', `${data.message || 'Articulo actualizado.'}${qaSyncSuffix(data.sync)}`);
        } else {
            setModuleStatus('qa-status', 'err', data.detail || data.message || 'No se pudo guardar el articulo.');
        }
    } catch (_e) {
        setModuleStatus('qa-status', 'err', 'Error de conexion guardando articulo QA.');
    }
}

async function applyQaAiAdjust() {
    const sid = (document.getElementById('qa-session-id')?.value || '').trim();
    const instructions = (document.getElementById('qa-ai-instructions')?.value || '').trim();
    if (!sid || !qaSelectedArticleId || !instructions) {
        setModuleStatus('qa-status', 'err', 'Selecciona articulo e indica instrucciones para IA.');
        return;
    }
    setModuleStatus('qa-status', 'loading', 'Aplicando ajuste IA al articulo seleccionado...');
    try {
        const res = await fetch(`/api/v1/flows/workspace/final-review/sessions/${sid}/articles/${qaSelectedArticleId}/ai-adjust`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instructions }),
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            document.getElementById('qa-ai-instructions').value = '';
            await loadQaSessionState();
            setModuleStatus('qa-status', 'ok', `${data.message || 'IA aplicada correctamente.'}${qaSyncSuffix(data.sync)}`);
        } else {
            setModuleStatus('qa-status', 'err', data.detail || data.message || 'No se pudo aplicar IA en QA.');
        }
    } catch (_e) {
        setModuleStatus('qa-status', 'err', 'Error de conexion aplicando IA en QA.');
    }
}

async function autoFixQaArticleWithAi() {
    const sid = (document.getElementById('qa-session-id')?.value || '').trim();
    if (!sid || !qaSelectedArticleId) {
        setModuleStatus('qa-status', 'err', 'Selecciona sesion y articulo para usar arreglo IA.');
        return;
    }

    const article = qaArticles.find(item => item.id === qaSelectedArticleId);
    if (!article) {
        setModuleStatus('qa-status', 'err', 'Articulo no encontrado en la sesion actual.');
        return;
    }

    setModuleStatus('qa-status', 'loading', 'Aplicando arreglo IA automatico...');
    try {
        let attempts = 0;
        let lastSync = '';
        let lastIssueCount = (article.issues || []).length;

        while (attempts < 2) {
            attempts += 1;
            const current = qaArticles.find(item => item.id === qaSelectedArticleId) || article;
            const issues = current.issues || [];
            const issueLines = issues.length
                ? issues.map(item => `- [${item.severity || 'info'}] ${item.code || '-'}: ${item.message || ''}`).join('\n')
                : '- Sin incidencias concretas: aplica limpieza editorial basica (claridad, formato y coherencia).';

            const instructions = [
                `Arregla automaticamente este articulo segun incidencias QA (intento ${attempts}/2).`,
                'Prioridades: resolver errores primero, luego warnings.',
                'No inventes datos factuales ni cambies municipio/categoria.',
                'Mantener el idioma del articulo (catalan cuando aplique).',
                'Si falta resumen, generar excerpt breve (1-2 frases) en el campo de resumen existente.',
                'Si body es corto, ampliar con informacion util y concreta sin inventar hechos.',
                'Si summary duplica body, rehacer summary de forma breve y no redundante.',
                'Si hay placeholders o mensajes tecnicos, eliminarlos del contenido final.',
                '',
                'Incidencias detectadas:',
                issueLines,
            ].join('\n');

            const res = await fetch(`/api/v1/flows/workspace/final-review/sessions/${sid}/articles/${qaSelectedArticleId}/ai-adjust`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ instructions }),
            });
            const data = await res.json();
            if (!res.ok || data.success === false) {
                setModuleStatus('qa-status', 'err', data.detail || data.message || 'No se pudo aplicar arreglo IA.');
                return;
            }
            lastSync = qaSyncSuffix(data.sync);

            const checksData = await runQaChecksSilently(sid);
            const updated = (checksData.articles || []).find(item => item.id === qaSelectedArticleId);
            const pending = (updated?.issues || []).length;
            if (pending === 0) {
                setModuleStatus('qa-status', 'ok', `Arreglo IA completado en ${attempts} intento(s).${lastSync}`);
                return;
            }
            if (pending >= lastIssueCount && attempts >= 2) {
                break;
            }
            lastIssueCount = pending;
        }

        setModuleStatus('qa-status', 'loading', `Arreglo IA aplicado, pero quedan incidencias en el articulo (${lastIssueCount}). Puedes relanzar auto-fix o ajustar manualmente.${lastSync}`);
    } catch (_e) {
        setModuleStatus('qa-status', 'err', 'Error de conexion aplicando arreglo IA.');
    }
}

async function exportQaReviewed() {
    const sid = (document.getElementById('qa-session-id')?.value || '').trim();
    if (!sid) {
        setModuleStatus('qa-status', 'err', 'Inicia sesion QA para exportar version revisada.');
        return;
    }
    setModuleStatus('qa-status', 'loading', 'Generando export revisado...');
    try {
        const res = await fetch(`/api/v1/flows/workspace/final-review/sessions/${sid}/export-reviewed`, { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            setModuleStatus('qa-status', 'ok', `${data.message || 'Export revisado generado.'} JSON: ${data.json_path || '-'} | CSV: ${data.csv_path || '-'}`);
        } else {
            setModuleStatus('qa-status', 'err', data.detail || data.message || 'No se pudo exportar la version revisada.');
        }
    } catch (_e) {
        setModuleStatus('qa-status', 'err', 'Error de conexion exportando revision final.');
    }
}
