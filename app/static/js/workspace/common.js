function getFlowLabel(flow) {
    const name = (flow.name || '').trim();
    if (name) return name;
    const muni = getMuniLabel(flow.municipality || 'GENERAL');
    return `${muni} · ${flow.category || 'SIN_CATEGORIA'}`;
}

function getMuniClass(m) { return 'muni-' + (m || 'GENERAL'); }
function getMuniLabel(m) { return MUNI_LABELS[m] || m || '?'; }

function formatDateTime(value) {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
}

function escapeHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function setModuleStatus(elementId, kind, message) {
    const el = document.getElementById(elementId);
    if (!el) return;
    if (!kind || !message) {
        el.className = 'module-status';
        el.textContent = '';
        return;
    }
    el.className = 'module-status ' + kind;
    el.textContent = message;
}

async function switchWorkspaceMode(mode) {
    const normalized = (mode || '').toLowerCase();
    if (!['local', 'smb'].includes(normalized)) return;
    const currentMode = ((window.__WORKSPACE_BOOTSTRAP__ || {}).activeMode || '').toLowerCase();
    if (currentMode && currentMode === normalized) return;

    const buttons = Array.from(document.querySelectorAll('.mode-switch-btn'));
    buttons.forEach(btn => { btn.disabled = true; });
    try {
        const res = await fetch(`/api/v1/flows/switch-mode?mode=${encodeURIComponent(normalized)}`, { method: 'POST' });
        const raw = await res.text();
        let data;
        try {
            data = JSON.parse(raw);
        } catch (_e) {
            data = { success: false, detail: raw || 'Respuesta invalida del servidor' };
        }
        if (!res.ok || data.success === false) {
            alert(data.detail || data.message || 'No se pudo cambiar el modo activo.');
            return;
        }
        window.location.reload();
    } catch (_e) {
        alert('Error de conexion cambiando el modo activo.');
    } finally {
        buttons.forEach(btn => { btn.disabled = false; });
    }
}

function initWorkspaceModeSwitch() {
    const localBtn = document.getElementById('workspace-mode-local');
    const smbBtn = document.getElementById('workspace-mode-smb');
    if (!localBtn || !smbBtn) return;
    localBtn.addEventListener('click', () => switchWorkspaceMode('local'));
    smbBtn.addEventListener('click', () => switchWorkspaceMode('smb'));
}
