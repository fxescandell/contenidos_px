function setTreeResult(kind, message) {
    const el = document.getElementById('tree-result');
    if (!el) return;
    el.className = 'tree-result ' + kind;
    el.textContent = message || '';
}

function setTreeSectionResult(elementId, kind, message) {
    const el = document.getElementById(elementId);
    if (!el) return;
    if (!kind || !message) {
        el.className = 'tree-result';
        el.textContent = '';
        return;
    }
    el.className = 'tree-result ' + kind;
    el.textContent = message || '';
}

function renderTreeValidationLists(groups) {
    const previewReadyEl = document.getElementById('tree-preview-ready-list');
    const verifiedEl = document.getElementById('tree-verified-list');
    if (!previewReadyEl || !verifiedEl) return;

    const list = groups || [];
    const previewReady = list.filter(item => (item.status || 'UNASSIGNED') === 'PREVIEW_READY');
    const verified = list.filter(item => (item.status || 'UNASSIGNED') === 'VERIFIED');

    const toHtml = (items) => {
        if (!items.length) {
            return '<div class="tree-validation-empty">-</div>';
        }
        return items
            .slice(0, 12)
            .map(item => {
                const category = escapeHtml(item.category_name || '-');
                const article = escapeHtml(item.article_name || '-');
                return `<div class="tree-validation-item"><span class="tree-validation-category">${category}</span><span class="tree-validation-sep">/</span><span class="tree-validation-article">${article}</span></div>`;
            })
            .join('');
    };

    previewReadyEl.innerHTML = toHtml(previewReady);
    verifiedEl.innerHTML = toHtml(verified);
}

function selectedTreeGroupIds() {
    return [...document.querySelectorAll('.tree-group-check:checked')].map(item => item.value);
}

function clearTreeSelection() {
    document.querySelectorAll('.tree-group-check').forEach(item => { item.checked = false; });
    const all = document.getElementById('tree-select-all');
    if (all) all.checked = false;
}

function toggleAllTreeGroups(source) {
    document.querySelectorAll('.tree-group-check').forEach(item => {
        item.checked = Boolean(source && source.checked);
    });
}

function setTreeFilter(filter, el) {
    TREE_STATUS_FILTER = filter || 'all';
    document.querySelectorAll('.tree-filter-tab').forEach(item => item.classList.remove('active'));
    if (el) el.classList.add('active');
    renderTreeGroups(TREE_GROUPS);
    clearTreeSelection();
}

function setTreeSearch(value) {
    TREE_TEXT_FILTER = (value || '').trim().toLowerCase();
    renderTreeGroups(TREE_GROUPS);
    clearTreeSelection();
}

function setTreeSort(value) {
    TREE_SORT_MODE = value || 'status';
    renderTreeGroups(TREE_GROUPS);
    clearTreeSelection();
}

function filteredTreeGroups(groups) {
    const list = groups || [];
    return list.filter(group => {
        const statusMatch = !TREE_STATUS_FILTER || TREE_STATUS_FILTER === 'all'
            ? true
            : (group.status || 'UNASSIGNED') === TREE_STATUS_FILTER;
        if (!statusMatch) return false;

        if (!TREE_TEXT_FILTER) return true;
        const category = (group.category_name || '').toLowerCase();
        const article = (group.article_name || '').toLowerCase();
        return category.includes(TREE_TEXT_FILTER) || article.includes(TREE_TEXT_FILTER);
    });
}

function sortTreeGroups(groups) {
    const list = [...(groups || [])];
    const statusRank = {
        ERROR: 0,
        UNASSIGNED: 1,
        ASSIGNED: 2,
        PREVIEW_READY: 3,
        VERIFIED: 4,
        EXPORTED: 5,
    };

    if (TREE_SORT_MODE === 'category') {
        return list.sort((a, b) => (a.category_name || '').localeCompare(b.category_name || '', 'es'));
    }
    if (TREE_SORT_MODE === 'article') {
        return list.sort((a, b) => (a.article_name || '').localeCompare(b.article_name || '', 'es'));
    }
    if (TREE_SORT_MODE === 'files_desc') {
        return list.sort((a, b) => (b.files_count || 0) - (a.files_count || 0));
    }

    return list.sort((a, b) => {
        const aStatus = statusRank[a.status || 'UNASSIGNED'] ?? 99;
        const bStatus = statusRank[b.status || 'UNASSIGNED'] ?? 99;
        if (aStatus !== bStatus) return aStatus - bStatus;
        const catCmp = (a.category_name || '').localeCompare(b.category_name || '', 'es');
        if (catCmp !== 0) return catCmp;
        return (a.article_name || '').localeCompare(b.article_name || '', 'es');
    });
}

function selectVisibleTreeGroups() {
    document.querySelectorAll('.tree-group-check').forEach(item => { item.checked = true; });
    const all = document.getElementById('tree-select-all');
    if (all) all.checked = true;
}

function selectTreeGroupsByStatus(statuses) {
    const acceptedStatuses = new Set(statuses || []);
    const visibleRows = [...document.querySelectorAll('#tree-groups-body tr')];
    let checkedAny = false;
    visibleRows.forEach(row => {
        const check = row.querySelector('.tree-group-check');
        const badge = row.querySelector('.tree-status');
        if (!check || !badge) return;
        const rowStatus = (badge.textContent || '').trim();
        const shouldCheck = acceptedStatuses.has(rowStatus);
        check.checked = shouldCheck;
        if (shouldCheck) checkedAny = true;
    });
    const all = document.getElementById('tree-select-all');
    if (all) all.checked = checkedAny;
}

function updateTreeStats(stats) {
    const totalEl = document.getElementById('tree-stat-total');
    const assignedEl = document.getElementById('tree-stat-assigned');
    const unassignedEl = document.getElementById('tree-stat-unassigned');
    const errorsEl = document.getElementById('tree-stat-errors');
    const previewEl = document.getElementById('tree-stat-preview');
    const verifiedEl = document.getElementById('tree-stat-verified');
    const exportedEl = document.getElementById('tree-stat-exported');
    if (!totalEl || !assignedEl || !unassignedEl || !errorsEl || !previewEl || !verifiedEl || !exportedEl) return;
    const safe = stats || { total: 0, assigned: 0, unassigned: 0, error: 0, preview_ready: 0, verified: 0, exported: 0 };
    totalEl.textContent = 'Total: ' + (safe.total || 0);
    assignedEl.textContent = 'Asignados: ' + (safe.assigned || 0);
    unassignedEl.textContent = 'Sin asignar: ' + (safe.unassigned || 0);
    errorsEl.textContent = 'Errores: ' + (safe.error || 0);
    previewEl.textContent = 'Preview lista: ' + (safe.preview_ready || 0);
    verifiedEl.textContent = 'Verificados: ' + (safe.verified || 0);
    exportedEl.textContent = 'Exportados: ' + (safe.exported || 0);
}

function renderTreeGroups(groups) {
    TREE_GROUPS = groups || [];
    const tbody = document.getElementById('tree-groups-body');
    if (!tbody) return;
    const allCheck = document.getElementById('tree-select-all');
    if (allCheck) allCheck.checked = false;
    const filtered = sortTreeGroups(filteredTreeGroups(TREE_GROUPS));
    const countEl = document.getElementById('tree-showing-count');
    if (countEl) countEl.textContent = `Mostrando ${filtered.length} de ${TREE_GROUPS.length}`;

    if (!filtered.length) {
        tbody.innerHTML = '<tr><td colspan="9" style="color:#64748b;">Todavia no hay grupos cargados.</td></tr>';
        return;
    }

    tbody.innerHTML = filtered.map(group => {
        const errors = (group.validation_errors || []);
        const fileList = (group.files || []).slice(0, 4).map(name => `- ${escapeHtml(name)}`).join('<br>');
        const canPreview = group.status === 'ASSIGNED' || group.status === 'PREVIEW_READY';
        const canViewPreview = Boolean(group.preview && group.preview.exists);
        return `<tr>
            <td><input class="tree-group-check" type="checkbox" value="${group.id}"></td>
            <td>${escapeHtml(group.category_name || '')}</td>
            <td>${escapeHtml(group.article_name || '')}</td>
            <td><span class="tree-status ${escapeHtml(group.status || 'UNASSIGNED')}">${escapeHtml(group.status || 'UNASSIGNED')}</span></td>
            <td><div>${group.files_count || 0} fichero(s)</div><div class="tree-file-list">${fileList || '-'}</div></td>
            <td>${escapeHtml(group.suggested_flow_label || '-')}</td>
            <td>${escapeHtml(group.assigned_flow_label || '-')}</td>
            <td>${errors.length ? escapeHtml(errors.join(' | ')) : '-'}</td>
            <td>
                <button class="btn btn-settings" style="padding:4px 8px; font-size:11px;" ${canPreview ? '' : 'disabled'} onclick="previewOneTreeGroup('${group.id}')">Generar JSON</button>
                <button class="btn" style="padding:4px 8px; font-size:11px;" ${canViewPreview ? '' : 'disabled'} onclick="openTreeGroupPreview('${group.id}')">Ver JSON</button>
                <button class="btn btn-settings" style="padding:4px 8px; font-size:11px;" onclick="deleteOneTreeGroup('${group.id}')">Borrar</button>
            </td>
        </tr>`;
    }).join('');
}

function renderTreeFlowOptions(options) {
    TREE_FLOW_OPTIONS = options || [];
    const select = document.getElementById('tree-flow-select');
    if (!select) return;
    if (!TREE_FLOW_OPTIONS.length) {
        select.innerHTML = '<option value="">No hay flujos activos para el modo</option>';
        document.getElementById('tree-assign-btn').disabled = true;
        document.getElementById('tree-preview-btn').disabled = true;
        document.getElementById('tree-accept-btn').disabled = true;
        document.getElementById('tree-finalize-btn').disabled = true;
        return;
    }
    select.innerHTML = '<option value="">Selecciona flow para asignar...</option>' + TREE_FLOW_OPTIONS
        .map(item => `<option value="${item.id}">${escapeHtml(item.label)}</option>`)
        .join('');
    document.getElementById('tree-assign-btn').disabled = false;
    document.getElementById('tree-preview-btn').disabled = false;
    document.getElementById('tree-accept-btn').disabled = false;
    document.getElementById('tree-finalize-btn').disabled = false;
}

async function loadTreeGroups() {
    if (!document.getElementById('tree-groups-body')) {
        return;
    }
    try {
        const res = await fetch('/api/v1/flows/manual/inbox/groups');
        const data = await res.json();
        if (res.ok && data.success !== false) {
            updateTreeStats(data.stats);
            renderTreeFlowOptions(data.flow_options || []);
            renderTreeGroups(data.groups || []);
            renderTreeValidationLists(data.groups || []);
            return;
        }
        setTreeResult('err', data.detail || data.message || 'No se pudieron cargar los grupos.');
    } catch (_e) {
        setTreeResult('err', 'Error de conexion cargando grupos manuales.');
    }
}

async function uploadTreeFolders() {
    const input = document.getElementById('tree-folder-input');
    const files = input.files ? Array.from(input.files) : [];
    if (!files.length) {
        setTreeResult('err', 'Selecciona una carpeta con estructura categoria/articulo/archivo.');
        return;
    }

    const formData = new FormData();
    files.forEach(file => {
        formData.append('files', file);
        formData.append('relative_paths', file.webkitRelativePath || file.name || '');
    });

    setTreeResult('loading', 'Subiendo estructura de carpetas...');
    try {
        const res = await fetch('/api/v1/flows/manual/inbox/upload-tree', { method: 'POST', body: formData });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            const msg = `${data.saved || 0} archivo(s) cargado(s), ${data.rejected || 0} rechazado(s), ${data.invalid_structure || 0} con estructura invalida.`;
            setTreeResult('ok', msg);
            input.value = '';
            await loadTreeGroups();
        } else {
            setTreeResult('err', data.detail || data.message || 'Error al subir estructura.');
        }
    } catch (_e) {
        setTreeResult('err', 'Error de conexion subiendo la estructura.');
    }
}

async function assignSelectedTreeGroups() {
    const flowId = document.getElementById('tree-flow-select').value;
    if (!flowId) {
        setTreeResult('err', 'Selecciona un flujo para asignar.');
        return;
    }
    const groupIds = selectedTreeGroupIds();
    if (!groupIds.length) {
        setTreeResult('err', 'Selecciona al menos un grupo.');
        return;
    }

    setTreeResult('loading', 'Asignando grupos seleccionados...');
    try {
        const res = await fetch('/api/v1/flows/manual/inbox/groups/assign', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ flow_id: flowId, group_ids: groupIds })
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            setTreeResult('ok', data.message || 'Grupos asignados.');
            await loadTreeGroups();
        } else {
            setTreeResult('err', data.detail || data.message || 'No se pudieron asignar los grupos.');
        }
    } catch (_e) {
        setTreeResult('err', 'Error de conexion asignando grupos.');
    }
}

async function autoAssignTreeGroups() {
    setTreeResult('loading', 'Autoasignando grupos por categoria...');
    try {
        const res = await fetch('/api/v1/flows/manual/inbox/groups/auto-assign?only_unassigned=true', { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            setTreeResult('ok', data.message || 'Autoasignacion completada.');
            await loadTreeGroups();
        } else {
            setTreeResult('err', data.detail || data.message || 'No se pudo autoasignar.');
        }
    } catch (_e) {
        setTreeResult('err', 'Error de conexion en autoasignacion.');
    }
}

async function previewSelectedTreeGroups() {
    const groupIds = selectedTreeGroupIds();
    if (!groupIds.length) {
        setTreeResult('err', 'Selecciona al menos un grupo para previsualizar.');
        return;
    }
    setTreeResult('loading', 'Generando JSON de los grupos seleccionados...');
    try {
        const res = await fetch('/api/v1/flows/manual/inbox/groups/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_ids: groupIds })
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            const errCount = (data.errors || []).length;
            const msg = `${data.previewed || 0} grupo(s) con JSON generado.${errCount ? ' ' + errCount + ' con error.' : ''}`;
            setTreeResult('ok', msg);
        } else {
            setTreeResult('err', data.detail || data.message || 'No se pudieron generar los JSON.');
        }
        await loadTreeGroups();
    } catch (_e) {
        setTreeResult('err', 'Error de conexion generando previews.');
    }
}

async function previewOneTreeGroup(groupId) {
    if (!groupId) return;
    setTreeResult('loading', 'Generando JSON del grupo...');
    try {
        const res = await fetch('/api/v1/flows/manual/inbox/groups/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_ids: [groupId] })
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            setTreeResult('ok', data.message || 'JSON generado.');
            await openTreeGroupPreview(groupId);
        } else {
            setTreeResult('err', data.detail || data.message || 'No se pudo generar JSON.');
        }
        await loadTreeGroups();
    } catch (_e) {
        setTreeResult('err', 'Error de conexion generando preview.');
    }
}

async function acceptSelectedTreeGroups() {
    const groupIds = selectedTreeGroupIds();
    if (!groupIds.length) {
        setTreeSectionResult('tree-validation-result', 'err', 'Selecciona al menos un grupo para marcar como verificado.');
        return;
    }
    setTreeSectionResult('tree-validation-result', 'loading', 'Marcando grupos seleccionados como verificados...');
    try {
        const res = await fetch('/api/v1/flows/manual/inbox/groups/accept', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_ids: groupIds })
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            const errCount = (data.errors || []).length;
            const msg = `${data.accepted || 0} grupo(s) anadido(s) al borrador verificado.${errCount ? ' ' + errCount + ' con error.' : ''}`;
            setTreeSectionResult('tree-validation-result', 'ok', msg);
        } else {
            setTreeSectionResult('tree-validation-result', 'err', data.detail || data.message || 'No se pudieron marcar los grupos como verificados.');
        }
        await loadTreeGroups();
        await loadManualDraftState();
    } catch (_e) {
        setTreeSectionResult('tree-validation-result', 'err', 'Error de conexion marcando grupos verificados.');
    }
}

async function finalizeSelectedTreeGroupsExport() {
    const groupIds = selectedTreeGroupIds();
    if (!groupIds.length) {
        setTreeSectionResult('tree-export-result', 'err', 'Selecciona grupos verificados para exportar.');
        return;
    }
    setTreeSectionResult('tree-export-result', 'loading', 'Generando exportacion final para la seleccion...');
    try {
        const res = await fetch('/api/v1/flows/manual/inbox/groups/finalize-export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_ids: groupIds })
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            const failed = (data.exports || []).filter(item => !item.success).length;
            const msg = `${(data.exports || []).length} exportacion(es) intentada(s). ${failed ? failed + ' con fallo.' : 'Todo correcto.'}`;
            setTreeSectionResult('tree-export-result', 'ok', msg);
        } else {
            setTreeSectionResult('tree-export-result', 'err', data.detail || data.message || 'No se pudo completar la exportacion seleccionada.');
        }
        await loadTreeGroups();
        await loadManualFlows();
    } catch (_e) {
        setTreeSectionResult('tree-export-result', 'err', 'Error de conexion exportando la seleccion.');
    }
}

async function openTreeGroupPreview(groupId) {
    try {
        const res = await fetch(`/api/v1/flows/manual/inbox/groups/${groupId}/preview`);
        const data = await res.json();
        if (res.ok && data.success !== false) {
            openPreviewModal(data.preview_json || '', `Grupo ${groupId} · ${data.summary || 'Preview manual'}`, { groupId });
        } else {
            setTreeResult('err', data.detail || data.message || 'No hay preview disponible para este grupo.');
        }
    } catch (_e) {
        setTreeResult('err', 'Error de conexion cargando la preview del grupo.');
    }
}

async function deleteSelectedTreeGroups() {
    const groupIds = selectedTreeGroupIds();
    if (!groupIds.length) {
        setTreeResult('err', 'Selecciona al menos un grupo para borrar.');
        return;
    }
    if (!confirm(`Se borraran ${groupIds.length} grupo(s) y sus archivos del staging manual. Esta accion no se puede deshacer.`)) {
        return;
    }
    setTreeResult('loading', 'Borrando grupos seleccionados...');
    try {
        const res = await fetch('/api/v1/flows/manual/inbox/groups/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_ids: groupIds })
        });
        const data = await res.json();
        if (res.ok && data.success !== false) {
            setTreeResult('ok', data.message || 'Grupos eliminados.');
        } else {
            setTreeResult('err', data.detail || data.message || 'No se pudieron borrar los grupos.');
        }
        await loadTreeGroups();
    } catch (_e) {
        setTreeResult('err', 'Error de conexion borrando grupos.');
    }
}

async function deleteOneTreeGroup(groupId) {
    if (!groupId) return;
    clearTreeSelection();
    const check = document.querySelector(`.tree-group-check[value="${groupId}"]`);
    if (check) check.checked = true;
    await deleteSelectedTreeGroups();
}
