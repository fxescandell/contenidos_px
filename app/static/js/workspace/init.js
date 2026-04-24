if (typeof initWorkspaceModeSwitch === 'function') {
    initWorkspaceModeSwitch();
}

if (HAS_DASHBOARD) {
    const activeTab = document.querySelector('.filter-tab.active');
    currentFilter = activeTab ? (activeTab.getAttribute('data-filter') || 'all') : 'all';
    applyFilters();
    refreshBatchesFromApi();
    if ((window.__WORKSPACE_BOOTSTRAP__ || {}).hasActiveDashboard) {
        startAutoRefresh();
    }
}

if (HAS_MANUAL_ARTICLE) {
    loadManualFlows();
}

if (HAS_MANUAL_BATCHES) {
    loadTreeGroups();
}

if (HAS_PREPROCESS) {
    loadPreprocessFlowOptions();
    renderPreprocessAnalysis(null);
}

if (HAS_FINAL_REVIEW) {
    renderQaArticlesList();
    renderQaSelectedArticle();
}

if (HAS_ACTIVITY && typeof setupGlobalActivityFeed === 'function') {
    setupGlobalActivityFeed();
}
