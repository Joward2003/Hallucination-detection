import {workbenchApi} from './api.js';
import {data as wb, refresh as refreshWorkbench, reviewScope, renderKnowledge, renderDataManagement, renderRuntime, renderRules, renderAudit, jobStatus} from './workbench.js';
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
  sourceFiles: [], companyName: '', period: '', reportId: '', kbVersion: '', reportDocumentId: '',
};
const workspaceState = { typeFilter: '', riskFilter: '', selectedEvidenceId: '', evidenceTab: 'source', compareMode: false };
const recordCache = new Map();
const reviewCache = new Map();
const loadingReviews = new Set();
const humanDrafts = new Map();
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
  const oldForm = document.querySelector('[data-human-form-key]');
  if (oldForm) humanDrafts.set(oldForm.dataset.humanFormKey, {
    values: Object.fromEntries([...oldForm.querySelectorAll('input[id],textarea[id]')].map(e => [e.id,e.value])),
    evidence: [...oldForm.querySelectorAll('[name="human-evidence"]:checked')].map(e=>e.value)
  });
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
    body = renderNewReview(draft, readHistory());
  } else if (path === '/review/new/settings') {
    if (!draft.reportText.trim()) {
      navigate('/review/new', true);
      toast('请先填写报告正文。', true);
      return;
    }
    body = reviewScope(draft) + renderReviewSettings(draft);
  } else if (path === '/review/new/progress') {
    body = renderProgress(draft, null);
    if (progressError) body += '<div class="error-inline">' + esc(progressError) + '</div>';
  } else if (path === '/history') {
    body = renderHistory(readHistory());
  } else if (path === '/settings') {
    body = renderSettings(getApiBase(), health);
  } else if (path === '/knowledge') {
    body = renderKnowledge();
  } else if (path === '/rules') {
    body = renderRules();
  } else if (path === '/data') {
    body = renderDataManagement();
  } else if (path === '/models') {
    body = renderRuntime();
  } else if (path.startsWith('/audit/')) {
    const job = decodeURIComponent(path.slice(7));
    body = renderAudit(job);
    if (wb.audit?.job !== job) loadAudit(job);
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
        body = jobStatus(review) + renderOverview(review);
      } else if (page === 'workspace') {
        body = jobStatus(review) + renderWorkspace(review, new URLSearchParams(window.location.search).get('finding'), workspaceState);
      } else {
        body = jobStatus(review) + renderExport(review);
      }
    }
  } else {
    body = renderError('页面不存在', '当前路由没有对应页面。');
  }
  app.innerHTML = renderShell(active, body, health);
  bindPageInputs();
  const newForm = document.querySelector('[data-human-form-key]');
  const savedForm = newForm && humanDrafts.get(newForm.dataset.humanFormKey);
  if(savedForm) {
    newForm.querySelectorAll('input[id],textarea[id]').forEach(e=>{if(e.id in savedForm.values)e.value=savedForm.values[e.id];});
    newForm.querySelectorAll('[name="human-evidence"]').forEach(e=>e.checked=savedForm.evidence.includes(e.value));
  }
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
    await refreshWorkbench();
    const records = await workbenchApi.get("/v1/reviews");
    records.reverse().forEach(record => saveHistoryEntry({reviewId:record.review_id,reportId:record.report_id,reportName:record.report_name,status:record.status,savedAt:record.created_at,reportType:"金融信贷报告"}));
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
    app.innerHTML = renderShell(navSection(location.pathname), renderError('无法读取复核结果', error.message), health);
  } finally {
    loadingReviews.delete(reviewId);
  }
  if (reviewCache.has(reviewId)) render();
  const record = recordCache.get(reviewId);
  if (record && ['QUEUED','RUNNING'].includes(record.status)) setTimeout(() => loadReview(reviewId), 1800);
}

function bindPageInputs() {
  const kbVersion = document.getElementById('review-kb-version');
  if (kbVersion) kbVersion.addEventListener('change', () => { draft.kbVersion = kbVersion.value; });
  const reportText = document.getElementById('report-text');
  if (reportText) {
    reportText.addEventListener('input', () => {
      draft.reportText = reportText.value;
      const counter = document.getElementById('report-character-count');
      if (counter) counter.textContent = '总字符数：' + draft.reportText.length;
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
    const doc = await workbenchApi.upload(file);
    if (doc.status !== 'READY') throw new Error(doc.error || '报告解析失败');
    const response = await fetch(workbenchApi.link('/v1/documents/' + doc.document_id + '/view'));
    const html = new DOMParser().parseFromString(await response.text(), 'text/html');
    draft.reportText = [...html.querySelectorAll('section pre')].map(p=>p.textContent).join('\n\n');
    draft.reportFileName = file.name;
    draft.reportDocumentId = doc.document_id;
    if (!draft.reportName.trim()) draft.reportName = file.name.replace(/\.[^.]+$/, '');
    await refreshWorkbench(); render(); toast('报告原件已保存并解析。');
  } catch (error) { toast(error.message, true); }
}

async function addSourceFiles(files) {
  for (const file of Array.from(files || [])) {
    try {
      const doc = await workbenchApi.upload(file, {company:draft.companyName,period:draft.period});
      if (doc.status !== 'READY') throw new Error(doc.error || '解析失败');
      draft.sourceFiles.push({id:doc.document_id,name:doc.name});
    } catch (error) { toast(file.name + '：' + error.message,true); }
  }
  await refreshWorkbench(); render();
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
  let version = draft.kbVersion;
  try {
    if (draft.sourceFiles.length) {
      const selected = wb.builds.find(b=>b.version===version);
      const documentIds = [...new Set([...(selected?.document_ids || []),...draft.sourceFiles.map(s=>s.id)])];
      const build = await workbenchApi.post('/v1/knowledge-bases/builds', {kb_id:'credit-kb',name:draft.reportName || '本次复核资料',document_ids:documentIds});
      let result = build;
      while (!['READY','FAILED','CANCELLED','INTERRUPTED'].includes(result.status)) {
        await new Promise(resolve=>setTimeout(resolve,1500));
        result=await workbenchApi.get('/v1/knowledge-bases/builds/'+build.build_id);
      }
      if (result.status !== 'READY') throw new Error(result.error || '建库失败');
      version=result.version;
    }
    if (!version) throw new Error('请先选择已发布的知识库版本，或上传本次参考资料。');
  } catch(error) {
    reportPending=false; navigate('/review/new/settings'); toast(error.message,true); return;
  }
  const payload = {
    report_id: draft.reportId,
    report_version: 'v1',
    tenant_id: 'local-tenant',
    project_id: 'default-project',
    requested_by: 'local-reviewer',
    idempotency_key: makeId('IDEM-'),
    report_text: draft.reportText,
    report_name: draft.reportName,
    report_type: draft.reportType,
    report_document_id: draft.reportDocumentId || undefined,
    kb_version: version,
    ...(draft.companyName ? { companies: { [draft.companyName]: {} } } : {}),
    source_scope: {company_ids: [], periods:draft.period ? [draft.period] : [], data_classification:'local'},
  };
  try {
    const record = await api.createReview(payload);
    const normalized = adaptReview(record);
    recordCache.set(normalized.reviewId, record);
    reviewCache.set(normalized.reviewId, normalized);
    saveNormalizedHistory(normalized, { reportName: draft.reportName || draft.reportFileName || '未命名报告', reportType: draft.reportType });
    health = true;
    navigate('/review/' + encodeURIComponent(normalized.reviewId) + '/overview');
    loadReview(normalized.reviewId);
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
  if (!comment) return toast('请填写人工复核理由，作为审计底稿。',true);
  const selectedEvidence = [...document.querySelectorAll('[name="human-evidence"]:checked')].map(e=>e.value);
  const finalText = document.getElementById('human-correction')?.value.trim() || '';
  const button = document.querySelector('[data-human-decision="' + decision + '"]');
  if (button) button.disabled = true;
  try {
    const record = await api.submitDecision(reviewId, {
      task_version: finding.humanTask.task_version,
      decision,
      selected_evidence_ids: selectedEvidence,
      final_text: finalText,
      comment,
      decided_by: document.getElementById('human-reviewer')?.value.trim() || '本机复核人',
    });
    recordCache.set(reviewId, record);
    const normalized = adaptReview(record);
    reviewCache.set(reviewId, normalized);
    const saved = getHistoryEntry(reviewId) || { reportName: reviewId, reportType: '金融报告' };
    saveNormalizedHistory(normalized, saved);
    render();
    toast('人工判定已保存，流程将继续剩余复核点。');
    loadReview(reviewId);

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
  if (await handleWorkbenchClick(event)) return;
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
  const entity = event.target.closest('[data-entity]');
  if (entity) { app.innerHTML = renderShell('/knowledge', renderKnowledge(entity.dataset.entity), health); return; }
  const company = event.target.closest('[data-company]');
  if (company) { const { renderDataManagement: rdm } = await import('./workbench.js'); const active = company.dataset.company; const cur = document.querySelector('.entity-card.active[data-company]'); app.innerHTML = renderShell('/data', rdm(cur && cur.dataset.company === active ? '' : active), health); return; }
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
  else if (action === 'supplement') {
    const reviewId=decodeURIComponent(location.pathname.split('/')[2] || '');
    const review=reviewCache.get(reviewId);
    const finding=review ? selectedFindingFor(review) : null;
    const query=document.getElementById('supplement-query')?.value.trim() || '';
    if(!finding?.humanTask || !query) return toast('请在人工复核区填写补充检索关键词。',true);
    try{await workbenchApi.post('/v1/reviews/'+reviewId+'/supplement',{task_version:finding.humanTask.task_version,query_text:query});await loadReview(reviewId);toast('补充候选已保存，请逐条确认其支持关系。');}catch(error){toast(error.message,true);}
  }
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


async function loadAudit(job) {
  if (wb.auditLoading === job) return;
  wb.auditLoading = job;
  try { wb.audit = await workbenchApi.get('/v1/audit/' + encodeURIComponent(job)); render(); }
  catch(error) {toast(error.message,true);}
  finally {wb.auditLoading = null;}
}

async function handleWorkbenchClick(event) {
  const audit=event.target.closest('[data-audit-job]');
  if(audit){navigate('/audit/'+encodeURIComponent(audit.dataset.auditJob)); return true;}
  const cancelBuild=event.target.closest('[data-cancel-build]');
  const cancelReview=event.target.closest('[data-cancel-review]');
  const continueReview=event.target.closest('[data-continue-review]');
  const button=event.target.closest('[data-wb-action]');
  if(!button&&!cancelBuild&&!cancelReview&&!continueReview)return false;
  const trigger=button||cancelBuild||cancelReview||continueReview;
  trigger.disabled=true;
  try{
    if(cancelBuild){await workbenchApi.post('/v1/knowledge-bases/builds/'+cancelBuild.dataset.cancelBuild+'/cancel');await refreshWorkbench();render();return true;}
    if(cancelReview){await workbenchApi.post('/v1/reviews/'+cancelReview.dataset.cancelReview+'/cancel');loadReview(cancelReview.dataset.cancelReview);return true;}
    if(continueReview){await workbenchApi.post('/v1/reviews/'+continueReview.dataset.continueReview+'/continue');loadReview(continueReview.dataset.continueReview);return true;}
    const action=button.dataset.wbAction;
    if(action==='refresh'){await refreshWorkbench();render();}
    if(action==='upload'){
      const files=[...document.getElementById('kb-files').files];
      if(!files.length)throw new Error('请先选择文件。');
      const metadata={company:document.getElementById('kb-company').value,period:document.getElementById('kb-period').value,original_document_id:document.getElementById('kb-original').value};
      for(const file of files){
        document.getElementById('kb-upload-status').textContent='正在解析：'+file.name;
        const doc=await workbenchApi.upload(file,{...metadata,original_document_id:file.name.endsWith('.json')?metadata.original_document_id:''});
        if(doc.status!=='READY')toast(doc.name+'：'+doc.error,true);
      }
      await refreshWorkbench();render();toast('来源原件与解析底稿已保存。');
    }
    if(action==='build'){
      const ids=[...document.querySelectorAll('[name="kb-doc"]:checked')].map(e=>e.value);
      const payload={document_ids:ids,kb_id:document.getElementById('kb-id').value,name:document.getElementById('kb-name').value};
      const build=await workbenchApi.post('/v1/knowledge-bases/builds',payload);await refreshWorkbench();render();toast('建库已开始，工作底稿会逐步保存。');pollBuild(build.build_id);
    }
    if(action==='search'){
      const version=document.getElementById('search-version').value;
      const build=wb.builds.find(b=>b.version===version);if(!build)throw new Error('请选择已发布版本。');
      const query=document.getElementById('kb-query').value.trim();if(!query)throw new Error('请输入检索内容。');
      wb.search={...await workbenchApi.post('/v1/knowledge-bases/'+build.kb_id+'/search',{kb_version:version,query:{query_text:query,retrieval_profile:'hybrid'}}),query_text:query};render();
    }
    if(action==='save-provider'){
      await workbenchApi.put('/v1/provider',{base_url:document.getElementById('provider-base').value,model:document.getElementById('provider-model').value,wire_api:document.getElementById('provider-wire').value,api_key:document.getElementById('provider-key').value,stream:document.getElementById('provider-stream').value==='true'});
      await refreshWorkbench();render();toast('本机 API 配置已保存；Key 不进入浏览器存储。');
    }
    if(action==='check-provider'){
      const target=document.getElementById('provider-result');target.textContent='正在请求真实 API…';
      const result=await workbenchApi.post('/v1/provider/check');target.textContent=result.ok?'API 已连通：'+result.reply:'连接失败：'+result.error;toast(result.ok?'本次真实 API 请求成功。':result.error,!result.ok);
    }
  }catch(error){toast(error.message,true);}
  finally{trigger.disabled=false;}
  return true;
}

async function pollBuild(ident){
  let previous='';
  while(true){
    await new Promise(resolve=>setTimeout(resolve,2000));
    let build;try{build=await workbenchApi.get('/v1/knowledge-bases/builds/'+ident);}catch(error){toast(error.message,true);return;}
    if(build.status!==previous){previous=build.status;await refreshWorkbench();if(['/knowledge','/data'].includes(location.pathname))render();}
    if(['READY','FAILED','CANCELLED','INTERRUPTED'].includes(build.status)){toast(build.status==='READY'?'知识库已发布，原件与索引版本已固定。':build.error||build.status,build.status!=='READY');return;}
  }
}

function positionEvidenceCard(event) {
  const source = event.target.closest?.('.inline-evidence');
  if (!source) return;
  const card=source.querySelector('.evidence-hover');
  const rect=source.getBoundingClientRect();
  if(card){card.style.left=Math.max(12,Math.min(rect.left,window.innerWidth-350))+'px';card.style.top=Math.max(12,Math.min(rect.bottom+8,window.innerHeight-280))+'px';}
}
document.addEventListener('mouseover',positionEvidenceCard);
document.addEventListener('focusin',positionEvidenceCard);
