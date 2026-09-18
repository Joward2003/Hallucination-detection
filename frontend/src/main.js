import { api, getApiBase, setApiBase } from './api.js';
import { adaptReview } from './adapter.js';
import { readHistory, saveHistoryEntry, updateHistoryEntry, getHistoryEntry } from './store.js';
import {
  downloadCSV, downloadJSON, esc, icon, renderDashboard, renderError, renderExport,
  renderHistory, renderModulePlaceholder, renderNewReview, renderOverview,
  renderProgress, renderReviewSettings, renderSettings, renderShell, renderWorkspace,
} from './ui.js';

const app = document.getElementById('app');
const draft = {
  reportName: '', reportType: 'AI 生成报告', reportText: '', reportFileName: '',
  sourceFiles: [], companyName: '', period: '', reportId: '',
};
const workspaceState = { typeFilter: '', riskFilter: '', selectedEvidenceId: '', evidenceTab: 'source', compareMode: false };
const recordCache = new Map();
const reviewCache = new Map();
const loadingReviews = new Set();
let health = null;
let remoteTasks = [];
let reportPending = false;
let progressError = '';

function makeId(prefix) {
  const value = globalThis.crypto?.randomUUID?.() || (Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
  return prefix + value.replace(/-/g, '').slice(0, 20).toUpperCase();
}

function navSection(path) {
  if (path.startsWith('/review/')) return '/review/new';
  if (path.startsWith('/history')) return '/history';
  if (path.startsWith('/knowledge')) return '/knowledge';
  if (path.startsWith('/rules')) return '/rules';
  if (path.startsWith('/data')) return '/data';
  if (path.startsWith('/models')) return '/models';
  if (path.startsWith('/settings')) return '/settings';
  return path === '/review/new' ? '/review/new' : '/dashboard';
}

function toast(message, isError = false) {
  const root = document.getElementById('toast-root');
  const node = document.createElement('div');
  node.className = 'toast' + (isError ? ' error' : '');
  node.innerHTML = icon(isError ? 'alert' : 'check', 15) + '<span>' + esc(message) + '</span>';
  root.appendChild(node);
  setTimeout(() => node.remove(), 4800);
}

function saveNormalizedHistory(review, meta) {
  const entry = {
    reviewId: review.reviewId,
    reportId: review.reportId,
    reportName: meta.reportName || review.reportId || '未命名报告',
    reportType: meta.reportType || '金融报告',
    status: review.workflowStatus,
    findingCount: review.findings.length,
    summaryCounts: review.summaryCounts,
  };
  if (getHistoryEntry(review.reviewId)) updateHistoryEntry(review.reviewId, entry);
  else saveHistoryEntry(entry);
}

function selectedFindingFor(review) {
  const id = new URLSearchParams(location.search).get('finding');
  if (id && review.findings.some((item) => item.id === id)) return review.findings.find((item) => item.id === id);
  return review.findings.find((item) => (!workspaceState.typeFilter || item.type === workspaceState.typeFilter) && (!workspaceState.riskFilter || String(item.risk).toLowerCase() === workspaceState.riskFilter)) || review.findings[0] || null;
}

function render() {
  const path = window.location.pathname || '/dashboard';
  if (path === '/') {
    navigate('/dashboard', true);
    return;
  }
  const active = navSection(path);
  let body = '';
  if (path === '/dashboard') {
    body = renderDashboard({ history: readHistory(), humanTasks: remoteTasks, health });
  } else if (path === '/review/new') {
    body = renderNewReview(draft);
  } else if (path === '/review/new/settings') {
    if (!draft.reportText.trim()) {
      navigate('/review/new', true);
      toast('请先填写报告正文。', true);
      return;
    }
    body = renderReviewSettings(draft);
  } else if (path === '/review/new/progress') {
    body = renderProgress(draft, null);
    if (progressError) body += '<div class="error-inline">' + esc(progressError) + '</div>';
  } else if (path === '/history') {
    body = renderHistory(readHistory());
  } else if (path === '/settings') {
    body = renderSettings(getApiBase(), health);
  } else if (path === '/knowledge') {
    body = renderModulePlaceholder('知识库', '现有后端包含建库与检索服务接口，但默认 API server 未配置 BuildManager，也没有浏览器端建库工作流。');
  } else if (path === '/rules') {
    body = renderModulePlaceholder('规则配置', '规则引擎可参与复核，但当前 API 不提供规则读取、编辑或版本发布接口。');
  } else if (path === '/data') {
    body = renderModulePlaceholder('数据管理', '当前 API 不提供来源文件上传、原件保存、权限管理或数据目录列表。');
  } else if (path === '/models') {
    body = renderModulePlaceholder('模型管理', '模型通过服务端环境与配置选择，当前 API 不提供模型列表或在线配置接口。');
  } else if (path.startsWith('/review/')) {
    const match = path.match(/^\/review\/([^/]+)\/(overview|workspace|export)$/);
    if (!match) {
      body = renderError('页面不存在', '检查复核任务链接是否正确。');
    } else {
      const reviewId = decodeURIComponent(match[1]);
      const page = match[2];
      const review = reviewCache.get(reviewId);
      if (!review) {
        body = '<div class="loading-review"><span class="large-spinner"></span><b>正在从复核 API 读取结果</b><small>' + esc(reviewId) + '</small></div>';
        loadReview(reviewId);
      } else if (page === 'overview') {
        body = renderOverview(review);
      } else if (page === 'workspace') {
        body = renderWorkspace(review, new URLSearchParams(window.location.search).get('finding'), workspaceState);
      } else {
        body = renderExport(review);
      }
    }
  } else {
    body = renderError('页面不存在', '当前路由没有对应页面。');
  }
  app.innerHTML = renderShell(active, body, health);
  bindPageInputs();
}

function navigate(path, replace = false) {
  if (replace) window.history.replaceState({}, '', path);
  else window.history.pushState({}, '', path);
  progressError = '';
  render();
  window.scrollTo({ top: 0, behavior: 'auto' });
}

async function refreshHealth() {
  try {
    await api.health();
    health = true;
    try { remoteTasks = await api.humanTasks(); }
    catch { remoteTasks = []; }
  } catch {
    health = false;
    remoteTasks = [];
  }
  render();
}

async function loadReview(reviewId) {
  if (loadingReviews.has(reviewId)) return;
  loadingReviews.add(reviewId);
  try {
    const record = await api.getReview(reviewId);
    recordCache.set(reviewId, record);
    const normalized = adaptReview(record);
    reviewCache.set(reviewId, normalized);
    const saved = getHistoryEntry(reviewId);
    saveNormalizedHistory(normalized, saved || { reportName: record.report_id, reportType: '金融报告' });
  } catch (error) {
    app.innerHTML = renderShell(navSection(location.pathname), renderError('无法读取复核结果', error.message + '。若后端为内存存储，服务重启后历史记录将不可读取。'), health);
  } finally {
    loadingReviews.delete(reviewId);
  }
  if (reviewCache.has(reviewId)) render();
}

function bindPageInputs() {
  const reportText = document.getElementById('report-text');
  if (reportText) {
    reportText.addEventListener('input', () => {
      draft.reportText = reportText.value;
      const counter = document.getElementById('report-character-count');
      if (counter) counter.textContent = draft.reportText.length + ' 字符';
    });
  }
  const reportName = document.getElementById('report-name');
  if (reportName) reportName.addEventListener('input', () => { draft.reportName = reportName.value; });
  const company = document.getElementById('scope-company');
  if (company) company.addEventListener('input', () => { draft.companyName = company.value; });
  const period = document.getElementById('scope-period');
  if (period) period.addEventListener('input', () => { draft.period = period.value; });
  const type = document.getElementById('report-type');
  if (type) type.addEventListener('change', () => { draft.reportType = type.value; });
}

function fileToText(file) {
  if (file.size > 2 * 1024 * 1024) return Promise.reject(new Error('单个文本文件不能超过 2 MB。'));
  if (!/\.(txt|md)$/i.test(file.name) && !['text/plain', 'text/markdown'].includes(file.type)) {
    return Promise.reject(new Error('当前界面只读取 .txt / .md 文本文件；PDF、Word 和 Excel 需要后端解析接口。'));
  }
  return file.text();
}

async function loadReportFile(file) {
  try {
    draft.reportText = await fileToText(file);
    draft.reportFileName = file.name;
    if (!draft.reportName.trim()) draft.reportName = file.name.replace(/\.(txt|md)$/i, '');
    render();
    toast('报告文本已载入。');
  } catch (error) { toast(error.message, true); }
}

async function addSourceFiles(files) {
  const available = Array.from(files || []);
  for (const file of available) {
    try {
      const text = await fileToText(file);
      const id = makeId('DOC-');
      draft.sourceFiles.push({ id, name: file.name, text });
    } catch (error) { toast(file.name + '：' + error.message, true); }
  }
  render();
}

function splitEvidence(source) {
  let paragraphs = source.text.split(/\n\s*\n+/).map((part) => part.trim()).filter(Boolean);
  if (paragraphs.length <= 1) paragraphs = source.text.split(/\r?\n/).map((part) => part.trim()).filter(Boolean);
  if (!paragraphs.length && source.text.trim()) paragraphs = [source.text.trim()];
  return paragraphs.map((content, index) => ({
    evidence_id: source.id + '-E' + String(index + 1).padStart(3, '0'),
    content,
    source: source.name,
    page: null,
    evidence_type: 'text',
    document_id: source.id,
    document_version: 'uploaded-text-v1',
    ...(draft.period.trim() ? { period: draft.period.trim() } : {}),
  }));
}

async function startReview() {
  if (reportPending) return;
  draft.companyName = document.getElementById('scope-company')?.value.trim() || '';
  draft.period = document.getElementById('scope-period')?.value.trim() || '';
  if (!draft.reportText.trim()) { toast('报告正文不能为空。', true); return; }
  reportPending = true;
  progressError = '';
  draft.reportId = draft.reportId || makeId('RPT-');
  navigate('/review/new/progress');
  const evidence = draft.sourceFiles.flatMap(splitEvidence);
  const sourceScope = evidence.length ? {
    allowed_document_ids: [...new Set(evidence.map((item) => item.document_id))],
    company_ids: [],
    periods: draft.period.trim() ? [draft.period.trim()] : [],
    corpus_version: 'browser-upload',
    rule_set_version: 'server-default',
    data_classification: 'unclassified',
  } : undefined;
  const payload = {
    report_id: draft.reportId,
    report_version: 'v1',
    tenant_id: 'local-tenant',
    project_id: 'default-project',
    requested_by: 'local-reviewer',
    idempotency_key: makeId('IDEM-'),
    report_text: draft.reportText,
    ...(evidence.length ? { evidence } : {}),
    ...(draft.companyName ? { companies: { [draft.companyName]: {} } } : {}),
    ...(sourceScope ? { source_scope: sourceScope } : {}),
  };
  try {
    const record = await api.createReview(payload);
    const normalized = adaptReview(record);
    recordCache.set(normalized.reviewId, record);
    reviewCache.set(normalized.reviewId, normalized);
    saveNormalizedHistory(normalized, { reportName: draft.reportName || draft.reportFileName || '未命名报告', reportType: draft.reportType });
    health = true;
    navigate('/review/' + encodeURIComponent(normalized.reviewId) + '/overview');
    try { remoteTasks = await api.humanTasks(); } catch { remoteTasks = []; }
  } catch (error) {
    reportPending = false;
    progressError = error.message;
    navigate('/review/new/settings');
    toast(error.message, true);
  } finally {
    reportPending = false;
  }
}

async function submitHumanDecision(decision) {
  const reviewId = decodeURIComponent(location.pathname.split('/')[2] || '');
  const review = reviewCache.get(reviewId);
  if (!review) return toast('当前复核结果尚未载入。', true);
  const finding = selectedFindingFor(review);
  if (!finding?.humanTask || finding.humanTask.status !== 'PENDING') return toast('当前 Finding 没有待提交的后端人工任务。', true);
  const comment = document.getElementById('human-comment')?.value.trim() || '';
  const selectedEvidence = finding.evidence.some((item) => item.evidence_id === workspaceState.selectedEvidenceId) ? [workspaceState.selectedEvidenceId] : [];
  const button = document.querySelector('[data-human-decision="' + decision + '"]');
  if (button) button.disabled = true;
  try {
    const record = await api.submitDecision(reviewId, {
      task_version: finding.humanTask.task_version,
      decision,
      selected_evidence_ids: selectedEvidence,
      comment,
      decided_by: 'local-reviewer',
    });
    recordCache.set(reviewId, record);
    const normalized = adaptReview(record);
    reviewCache.set(reviewId, normalized);
    const saved = getHistoryEntry(reviewId) || { reportName: reviewId, reportType: '金融报告' };
    saveNormalizedHistory(normalized, saved);
    render();
    toast('人工判定已通过现有 API 保存。');
    if (record.state?.workflow_status === 'CHILD_COMPLETED' && (record.state.child_index || 0) < (record.state.flat_children || []).length) {
      toast('当前 Claim 已完成；后端还没有继续执行下一 Claim 的恢复接口。', true);
    }
  } catch (error) {
    if (button) button.disabled = false;
    toast(error.message, true);
  }
}

function selectFinding(id) {
  workspaceState.selectedEvidenceId = '';
  workspaceState.evidenceTab = 'source';
  const url = new URL(location.href);
  url.searchParams.set('finding', id);
  window.history.replaceState({}, '', url.pathname + url.search);
  render();
}

function shiftFinding(direction) {
  const reviewId = decodeURIComponent(location.pathname.split('/')[2] || '');
  const review = reviewCache.get(reviewId);
  if (!review) return;
  const currentId = new URLSearchParams(location.search).get('finding');
  const index = review.findings.findIndex((item) => item.id === currentId);
  const next = Math.max(0, Math.min(review.findings.length - 1, (index < 0 ? 0 : index) + direction));
  if (review.findings[next]) selectFinding(review.findings[next].id);
}

document.addEventListener('click', async (event) => {
  const nav = event.target.closest('[data-nav]');
  if (nav) {
    event.preventDefault();
    navigate(nav.getAttribute('href'));
    return;
  }
  const navTo = event.target.closest('[data-nav-to]');
  if (navTo) { navigate(navTo.dataset.navTo); return; }
  const openReview = event.target.closest('[data-open-review]');
  if (openReview) { navigate('/review/' + encodeURIComponent(openReview.dataset.openReview) + '/overview'); return; }
  const select = event.target.closest('[data-select-finding]');
  if (select) { selectFinding(select.dataset.selectFinding); return; }
  const evidence = event.target.closest('[data-select-evidence]');
  if (evidence) { workspaceState.selectedEvidenceId = evidence.dataset.selectEvidence; workspaceState.evidenceTab = 'source'; render(); return; }
  const evidenceTab = event.target.closest('[data-evidence-tab]');
  if (evidenceTab) { workspaceState.evidenceTab = evidenceTab.dataset.evidenceTab; render(); return; }
  const humanDecision = event.target.closest('[data-human-decision]');
  if (humanDecision) { await submitHumanDecision(humanDecision.dataset.humanDecision); return; }
  const removeSource = event.target.closest('[data-remove-source]');
  if (removeSource) { draft.sourceFiles.splice(Number(removeSource.dataset.removeSource), 1); render(); return; }
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const action = button.dataset.action;
  if (action === 'choose-report') document.getElementById('report-file')?.click();
  else if (action === 'clear-report-file') { draft.reportFileName = ''; render(); }
  else if (action === 'to-settings') {
    draft.reportName = document.getElementById('report-name')?.value.trim() || '';
    draft.reportText = document.getElementById('report-text')?.value || '';
    draft.reportType = document.getElementById('report-type')?.value || draft.reportType;
    if (!draft.reportText.trim()) return toast('请填写报告正文或导入文本文件。', true);
    navigate('/review/new/settings');
  } else if (action === 'start-review') await startReview();
  else if (action === 'refresh-health') { await refreshHealth(); toast(health ? '复核服务连接正常。' : '无法连接复核服务。', !health); }
  else if (action === 'previous-finding') shiftFinding(-1);
  else if (action === 'next-finding') shiftFinding(1);
  else if (action === 'toggle-compare') { workspaceState.compareMode = !workspaceState.compareMode; render(); }
  else if (action === 'copy-evidence') {
    const reviewId = decodeURIComponent(location.pathname.split('/')[2] || '');
    const review = reviewCache.get(reviewId);
    const finding = review ? selectedFindingFor(review) : null;
    const selected = finding?.evidence.find((item) => item.evidence_id === workspaceState.selectedEvidenceId) || finding?.evidence[0];
    if (selected?.content) navigator.clipboard?.writeText(selected.content).then(() => toast('Evidence 原文已复制。')).catch(() => toast('浏览器未允许剪贴板访问。', true));
  } else if (action === 'save-api-base') {
    setApiBase(document.getElementById('api-base')?.value || '');
    await refreshHealth();
    toast(health ? 'API 地址已保存并连接成功。' : '地址已保存，但 API 连接失败。', !health);
  } else if (action === 'reset-api-base') {
    setApiBase('');
    await refreshHealth();
    toast(health ? '已恢复同源 API 并连接成功。' : '已恢复同源地址，但 API 当前不可用。', !health);
  } else if (action === 'export-csv' || action === 'export-json') {
    const reviewId = decodeURIComponent(location.pathname.split('/')[2] || '');
    const review = reviewCache.get(reviewId);
    if (review) action === 'export-csv' ? downloadCSV(review) : downloadJSON(review);
  }
});

document.addEventListener('change', (event) => {
  if (event.target.id === 'report-file' && event.target.files?.[0]) loadReportFile(event.target.files[0]);
  else if (event.target.id === 'source-files' && event.target.files?.length) addSourceFiles(event.target.files);
  else if (event.target.id === 'filter-type') { workspaceState.typeFilter = event.target.value; render(); }
  else if (event.target.id === 'filter-risk') { workspaceState.riskFilter = event.target.value; render(); }
});

document.addEventListener('dragover', (event) => {
  const zone = event.target.closest('[data-drop="report"]');
  if (zone) { event.preventDefault(); zone.classList.add('drag-over'); }
});
document.addEventListener('dragleave', (event) => {
  const zone = event.target.closest('[data-drop="report"]');
  if (zone && !zone.contains(event.relatedTarget)) zone.classList.remove('drag-over');
});
document.addEventListener('drop', (event) => {
  const zone = event.target.closest('[data-drop="report"]');
  if (zone) {
    event.preventDefault();
    zone.classList.remove('drag-over');
    const file = event.dataTransfer?.files?.[0];
    if (file) loadReportFile(file);
  }
});

document.addEventListener('keydown', (event) => {
  if (!location.pathname.includes('/workspace') || event.metaKey || event.ctrlKey || event.altKey) return;
  const target = event.target;
  if (target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) return;
  if (event.key.toLowerCase() === 'j') { event.preventDefault(); shiftFinding(1); }
  else if (event.key.toLowerCase() === 'k') { event.preventDefault(); shiftFinding(-1); }
});

window.addEventListener('popstate', render);
render();
refreshHealth();
