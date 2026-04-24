const __BOOT = window.__WORKSPACE_BOOTSTRAP__ || {};

const BATCHES = Array.isArray(__BOOT.batches) ? __BOOT.batches : [];
let MANUAL_FLOWS = [];
let MANUAL_DRAFT_STATE = null;
const STATUSES_ACTIVE = ['DETECTED', 'COPYING', 'COPIED', 'SCANNED', 'GROUPED', 'PROCESSING'];
const STATUSES_FINISHED = ['FINISHED'];
const STATUSES_FAILED = ['FAILED'];
const STATUSES_REVIEW = ['REVIEW_REQUIRED'];
const STATUS_ORDER = ['DETECTED', 'COPYING', 'COPIED', 'SCANNED', 'GROUPED', 'PROCESSING', 'FINISHED', 'REVIEW_REQUIRED', 'FAILED'];
const activityState = { flowId: null, batchId: null, startedAfter: '', timer: null };
let TREE_GROUPS = [];
let TREE_FLOW_OPTIONS = [];
let TREE_STATUS_FILTER = 'all';
let TREE_TEXT_FILTER = '';
let TREE_SORT_MODE = 'status';
const previewModalState = { groupId: null, editable: false, originalJson: '', previousJson: '' };
const aiRequestState = { controller: null, timer: null, startedAt: 0 };
let cleanupRetryTargets = { working: [], temp: [] };
const WORKSPACE_PAGE = (__BOOT.workspacePage || 'dashboard');
const HAS_DASHBOARD = WORKSPACE_PAGE === 'dashboard' || WORKSPACE_PAGE === 'activity';
const HAS_MANUAL_ARTICLE = WORKSPACE_PAGE === 'manual-article';
const HAS_MANUAL_BATCHES = WORKSPACE_PAGE === 'manual-batches';
const HAS_PREPROCESS = WORKSPACE_PAGE === 'preprocess';
const HAS_FINAL_REVIEW = WORKSPACE_PAGE === 'final-review';

const MUNI_LABELS = {
    BERGUEDA: 'Bergueda',
    CERDANYA: 'Cerdanya',
    MARESME: 'Maresme',
    GENERAL: 'General'
};

let currentFilter = 'all';
let preprocessSessionId = null;
let qaSessionId = null;
let qaSelectedArticleId = null;
let qaArticles = [];
