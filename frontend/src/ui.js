import {renderEvidenceContent, evidencePdfPath, evidencePreviewPath, plainEvidenceText} from './evidence-renderer.js';
import {workbenchApi} from './api.js';
import {exportLink} from './workbench.js';
import { typeLabel } from './adapter.js';

export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

const ICONS = {
  home: '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/><path d="M9 21v-6h6v6"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h8"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 1 4 17.5z"/><path d="M4 17.5A2.5 2.5 0 0 1 6.5 15H20M8 7h8M8 10h8"/>',
  sliders: '<path d="M4 21v-7m0-4V3m8 18v-9m0-4V3m8 18v-5m0-4V3M2 14h4m4-6h4m4 8h4"/>',
  database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  cube: '<path d="m12 3 9 5-9 5-9-5z"/><path d="M3 8v9l9 5 9-5V8M12 13v9"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="m19.4 15 .1.1a1.7 1.7 0 1 1-2.4 2.4l-.1-.1a1.7 1.7 0 0 0-2.9 1.2v.2a1.7 1.7 0 1 1-3.4 0v-.2a1.7 1.7 0 0 0-2.9-1.2l-.1.1a1.7 1.7 0 1 1-2.4-2.4l.1-.1a1.7 1.7 0 0 0-1.2-2.9H4a1.7 1.7 0 1 1 0-3.4h.2A1.7 1.7 0 0 0 5.4 5.8l-.1-.1a1.7 1.7 0 1 1 2.4-2.4l.1.1a1.7 1.7 0 0 0 2.9-1.2V2a1.7 1.7 0 1 1 3.4 0v.2a1.7 1.7 0 0 0 2.9 1.2l.1-.1a1.7 1.7 0 1 1 2.4 2.4l-.1.1a1.7 1.7 0 0 0 1.2 2.9h.2a1.7 1.7 0 1 1 0 3.4h-.2a1.7 1.7 0 0 0-1.2 2.9z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  arrow: '<path d="M5 12h14m-7-7 7 7-7 7"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>',
  alert: '<path d="m10.3 3.9-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3.1l-8-14a2 2 0 0 0-3.4 0z"/><path d="M12 9v4m0 4h.01"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
  align: '<path d="M3 6h18M3 12h12M3 18h18"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.1 0l3-3a5 5 0 0 0-7.1-7.1l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.1 0l-3 3a5 5 0 0 0 7.1 7.1l1.7-1.7"/>',
  close: '<path d="m18 6-12 12M6 6l12 12"/>',
};

export function evidenceText(value) {
  return String(value || '').replace(/<\/tr>/gi,'\n').replace(/<\/(td|th)>/gi,' | ').replace(/<[^>]*>/g,'').replace(/&nbsp;/g,' ').trim();
}

export function icon(name, size = 18) {
  return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[name] || ICONS.file) + '</svg>';
}

const NAV = [
  { label: '工作概览', href: '/dashboard', icon: 'home' },
  { label: '新建复核', href: '/review/new', icon: 'file' },
  { label: '复核任务', href: '/history', icon: 'clock' },
  { label: '参考资料库', href: '/knowledge', icon: 'book' },
  { label: '复核规则', href: '/rules', icon: 'sliders' },
  { label: '资料概览', href: '/data', icon: 'database' },
  { label: '模型连接', href: '/models', icon: 'cube' },
  { label: '系统设置', href: '/settings', icon: 'settings' },
];

export function renderShell(activePath, content, apiStatus) {
  const nav = NAV.map((item) => '<a class="nav-link ' + (activePath === item.href ? 'active' : '') + '" href="' + item.href + '" data-nav '+(activePath === item.href ? 'aria-current="page" ' : '')+'aria-label="'+esc(item.label)+'" title="'+esc(item.label)+'">' + icon(item.icon) + '<span>' + item.label + '</span></a>').join('');
  const api = apiStatus === true ? '<span class="service-dot online"></span><span>复核服务正常</span>' : apiStatus === false ? '<span class="service-dot offline"></span><span>复核服务离线</span>' : '<span class="service-dot pending"></span><span>检查连接中</span>';
  if(apiStatus===false && !['/dashboard','/settings'].includes(activePath))content='<div class="error-inline" role="status">服务暂时不可用。请检查系统设置中的服务地址，再刷新连接。</div>'+content;
  return '<a class="skip-link" href="#main-content">跳转到主内容</a><div class="app-shell">' +
    '<aside class="sidebar"><a class="brand" href="/dashboard" data-nav><span class="brand-mark" aria-hidden="true"><img src="/assets/brand/review-robot.png" width="44" height="44" alt="" decoding="async" /></span><span class="brand-copy"><strong>金融报告复核</strong><small>AI Review Workspace</small></span></a>' +
    '<div class="nav-caption">工作空间</div><nav class="main-nav" aria-label="主导航">' + nav + '</nav>' +
    '<div class="sidebar-spacer"></div><div class="sidebar-assurance"><span class="assurance-icon">' + icon('link', 16) + '</span><span><b>证据可追溯</b><small>结论可解释 · 人机协同</small></span></div>' +

    '<div class="user-card"><span class="avatar">审</span><span><b>本地复核员</b><small>审核工作台</small></span></div></aside>' +
    '<main class="main-area"><header class="topbar"><div class="breadcrumbs"><span>复核工作台</span><span class="crumb-divider">/</span><b>' + esc(pageName(location.pathname)) + '</b></div><div class="topbar-right"><span class="api-indicator">' + api + '</span><button class="icon-button" aria-label="刷新服务状态" data-action="refresh-health">' + icon('clock', 16) + '</button><span class="top-avatar">审</span></div></header>' +
    '<div class="page-content" id="main-content" tabindex="-1">' + content + '</div></main></div>';
}

function pageName(path) {
  if (path.includes('/workspace')) return '逐项复核';
  if (path.includes('/overview')) return '复核总览';
  if (path.includes('/export')) return '导出结果';
  return ({'/dashboard':'工作概览','/review/new':'新建复核','/review/new/settings':'确认复核范围','/review/new/progress':'准备复核','/history':'复核任务','/knowledge':'参考资料库','/rules':'复核规则','/data':'资料概览','/models':'模型连接','/settings':'系统设置'})[path] || '流程底稿';
}
export const workflowLabel = status => ({COMPLETED:'复核完成',HUMAN_REVIEW_REQUIRED:'待人工确认',CHILD_COMPLETED:'部分完成',CANCELLED:'已取消',RUNNING:'复核中',QUEUED:'排队中',FAILED:'执行失败',INTERRUPTED:'执行中断'})[status] || '待复核';
export const relationLabel = relation => ({SUPPORTS:'支持该结论',PARTIALLY_SUPPORTS:'部分支持',CONTRADICTS:'与结论冲突',IRRELEVANT:'不相关'})[relation] || '尚未确认支持关系';

function statusPill(status) {
  const cls = status === 'COMPLETED' ? 'green' : status === 'HUMAN_REVIEW_REQUIRED' ? 'amber' : ['FAILED','INTERRUPTED'].includes(status) ? 'red' : status === 'CANCELLED' ? 'gray' : 'blue';
  const label = workflowLabel(status);
  return '<span class="status-pill ' + cls + '"><i></i>' + esc(label) + '</span>';
}

function riskPill(risk) {
  const value = String(risk || '').toLowerCase();
  const cls = value === 'critical' || value === 'high' ? 'red' : value === 'medium' ? 'amber' : value === 'low' ? 'green' : 'gray';
  const label = ({ critical: '严重', high: '高风险', medium: '中风险', low: '低风险' })[value] || '未评级';
  return '<span class="risk-pill ' + cls + '">' + label + '</span>';
}

function formatTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? esc(value) : new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date);
}

export function renderDashboard({history, humanTasks, health}) {
  const pending = humanTasks?.length || 0;
  const done = history.filter(h=>h.status==='COMPLETED').length;
  const running = history.filter(h=>['RUNNING','QUEUED'].includes(h.status)).length;
  const stats = [['全部任务',history.length],['复核中',running],['待人工确认',pending],['复核完成',done]].map(([label,value])=>`<div class="stat-item"><span>${label}</span><strong>${value}<small>项</small></strong></div>`).join('');
  const rows = history.slice(0,6).map(h=>`<tr><td><b>${esc(h.reportName || '未命名报告')}</b><small class="table-sub">${esc(h.reportType || '金融报告')}</small></td><td>${formatTime(h.savedAt)}</td><td>${statusPill(h.status)}</td><td>${h.findingCount ?? '—'}</td><td><button class="text-action" data-open-review="${esc(h.reviewId)}" aria-label="打开 ${esc(h.reportName)}">查看任务 ${icon('chevron',14)}</button></td></tr>`).join('');
  const queue = (humanTasks||[]).slice(0,5).map(t=>`<button class="pending-task" data-nav-to="/review/${encodeURIComponent(t.review_id)}/workspace?finding=${encodeURIComponent(t.fact_id || '')}"><span>${icon('alert',18)}</span><span class="pending-copy"><b>${esc(t.fact || history.find(h=>h.reviewId===t.review_id)?.reportName || '有结论需要确认')}</b><small>查看证据并提交人工判定</small></span>${icon('chevron',16)}</button>`).join('');
  return `<section class="welcome-row"><div><h1>每一条结论，都有据可查。</h1><p>核对报告事实与来源证据，优先处理需要人工确认的结论。</p></div><a class="primary-button" href="/review/new" data-nav>${icon('plus',17)}新建复核</a></section>
  ${health===false ? '<div class="error-inline" role="status">暂时无法连接复核服务。请在系统设置检查服务地址，再刷新连接。</div>' : ''}
  <section class="stats-band" aria-label="任务统计">${stats}</section>
  <section class="home-panels"><div class="panel recent-panel"><div class="panel-heading"><div><h2>最近复核任务</h2><p>从提交到判定，跟进报告复核进展</p></div><a href="/history" data-nav class="text-action">全部任务 ${icon('arrow',15)}</a></div><div class="table-scroll"><table class="data-table"><thead><tr><th>报告名称</th><th>创建时间</th><th>进度</th><th>复核项</th><th>操作</th></tr></thead><tbody>${rows || '<tr><td colspan="5"><div class="empty-state"><span class="empty-icon">'+icon('file',24)+'</span><b>从第一份报告开始</b><small>上传报告、选择参考资料，系统会逐条核对结论。</small><a class="outline-button" href="/review/new" data-nav>创建复核任务</a></div></td></tr>'}</tbody></table></div></div>
  <aside class="panel queue-panel"><div class="panel-heading"><div><h2>待我确认</h2><p>需要人工判断的结论</p></div><span class="queue-count">${pending}</span></div>${queue || '<div class="queue-empty">'+icon('check',24)+'<b>'+(health===true?'当前没有待办':'待办暂不可用')+'</b><small>'+(health===true?'需要补证或存在重要风险的结论会进入这里。':'连接恢复后可读取待确认事项。')+'</small></div>'}<a class="queue-foot" href="/history" data-nav>前往任务列表 ${icon('arrow',14)}</a></aside></section>
  <section class="workflow-guide" aria-label="复核流程"><div><b>上传报告</b><span>导入原件或粘贴正文</span></div>${icon('chevron',16)}<div><b>核对证据</b><span>使用已发布的参考资料</span></div>${icon('chevron',16)}<div><b>人工确认</b><span>保留判定理由与修订</span></div>${icon('chevron',16)}<div><b>导出报告</b><span>归档结果与完整底稿</span></div></section>`;
}

export function renderNewReview(draft, history = []) {
  const fileName = draft.reportFileName ? '<span class="selected-file">' + icon('file', 15) + '<b>' + esc(draft.reportFileName) + '</b><button type="button" data-action="clear-report-file" aria-label="移除文件">' + icon('close', 14) + '</button></span>' : '';
  const sources = draft.sourceFiles.map((item, index) => '<span class="source-chip">' + icon('file', 14) + esc(item.name) + '<button type="button" data-remove-source="' + index + '" aria-label="移除 ' + esc(item.name) + '">' + icon('close', 13) + '</button></span>').join('');
  const historyRows = '';
  return '<div class="page-heading"><div><h1>新建报告复核</h1><p>上传待核对的报告，下一步选择参考资料并确认复核范围。</p></div><a class="quiet-button" href="/dashboard" data-nav>' + icon('chevron', 15) + '返回首页</a></div>' +
    '<div class="stepper full-width"><div class="step active"><span>1</span><b>上传报告</b></div><i></i><div class="step"><span>2</span><b>复核设置</b></div><i></i><div class="step"><span>3</span><b>自动复核</b></div><i></i><div class="step"><span>4</span><b>人工复核</b></div></div>' +
    '<div class="intake-layout single-col"><section class="panel intake-main wide-card"><div class="section-title padded-head"><div><h2>报告内容</h2><p>可粘贴正文，或导入 PDF、DOCX 与文本；原件和解析结果会持久保存。</p></div></div>' +
    '<div class="form-grid intake-meta-grid"><div class="form-field"><label for="report-name">报告名称 <span class="optional-label">可选</span></label><input id="report-name" class="text-input" type="text" placeholder="例如：XX集团2023年财务分析报告" value="' + esc(draft.reportName) + '" maxlength="160" /></div><div class="form-field"><label for="report-type">报告来源</label><select id="report-type" class="text-input"><option ' + (draft.reportType === 'AI 生成报告' ? 'selected' : '') + '>AI 生成报告</option><option ' + (draft.reportType === '人工撰写报告' ? 'selected' : '') + '>人工撰写报告</option></select><small class="field-hint">用于标识报告来源，结果与任务一并保存。</small></div></div>' +
    '<div class="form-field padded-field"><div class="field-label-row"><label for="report-text">请输入报告内容</label><span class="character-count" id="report-character-count">总字符数：' + draft.reportText.length + '</span></div><textarea id="report-text" class="text-area report-input roomy-input" placeholder="粘贴 AI 生成的金融分析报告正文…" spellcheck="false">' + esc(draft.reportText) + '</textarea><div class="field-hint">文本会发送到当前配置的复核 API。请确认不包含不应提交的敏感信息。</div></div>' +
    '<div class="dropzone compact-drop" data-drop="report"><input id="report-file" type="file" accept=".pdf,.docx,.txt,.md,text/plain,text/markdown" hidden /><span class="drop-icon">' + icon('upload', 18) + '</span><div><b>从本机导入报告原件</b><small>支持 PDF、DOCX、TXT、Markdown · 保存原件与解析底稿</small></div><button type="button" class="outline-button small" data-action="choose-report">选择文件</button>' + fileName + '</div>' +
    '<div class="form-field source-field"><div class="field-label-row"><div><label>参考证据 <span class="optional-label">可选</span></label><div class="field-hint">上传可支持本次报告结论的原始资料，也可在下一步选择已有版本。</div></div><label class="outline-button small file-button" for="source-files">' + icon('plus', 14) + '添加参考资料</label><input id="source-files" type="file" accept=".pdf,.docx,.txt,.md,text/plain,text/markdown" multiple hidden /></div><div class="source-file-list">' + (sources || '<span class="no-sources">尚未添加参考来源</span>') + '</div></div>' +
    '<div class="form-actions padded-actions"><a class="quiet-button" href="/dashboard" data-nav>取消</a><button type="button" class="primary-button" data-action="to-settings">继续：复核设置 ' + icon('arrow', 16) + '</button></div></section></div>';
}

export function renderReviewSettings(draft) {
  const dimensions = [
    ['事实准确性', '核对数字、时间与来源原文是否一致。'],
    ['引用来源匹配', '检查检索证据与当前结论的相关性。'],
    ['表述合理性', '评估证据是否足以支持当前表述。'],
    ['推理完整性', '结合核验理由与证据关系检查推理断点。'],
    ['风险完整性', '检查是否存在需要人工关注的业务风险。'],
  ].map((item) => '<div class="dimension-row"><span class="checked-box">' + icon('check', 13) + '</span><span><b>' + item[0] + '</b><small>' + item[1] + '</small></span><span class="dimension-fixed">自动检查</span></div>').join('');
  const sourceNames = draft.sourceFiles.length ? draft.sourceFiles.map((item) => '<span class="source-chip readonly">' + icon('file', 14) + esc(item.name) + '</span>').join('') : '<span class="no-sources">将使用上方选定的知识库版本进行检索。</span>';
  return '<div class="page-heading"><div><h1>复核设置</h1><p>查看本次请求实际使用的复核维度和证据范围。</p></div><span class="request-mode"><span class="service-dot online"></span> 按已选资料核验</span></div>' +
    '<div class="stepper"><div class="step complete"><span>' + icon('check', 13) + '</span><b>上传报告</b></div><i class="filled"></i><div class="step active"><span>2</span><b>复核设置</b></div><i></i><div class="step"><span>3</span><b>自动复核</b></div><i></i><div class="step"><span>4</span><b>人工复核</b></div></div>' +
    '<div class="settings-layout"><section class="panel settings-panel"><div class="panel-heading"><div><h2>复核维度</h2><p>系统会自动执行以下检查，无需逐项配置。</p></div><span class="fixed-tag">5 项已启用</span></div><div class="dimension-list">' + dimensions + '</div>' +
    '<div class="settings-divider"></div><div class="panel-heading source-heading"><div><h2>本次参考资料</h2><p>来自已发布知识库，随本次任务固定版本与证据范围。</p></div><a class="text-action" href="/review/new" data-nav>返回修改</a></div><div class="selected-sources">' + sourceNames + '</div>' +
    '<div class="form-grid"><div class="form-field"><label for="scope-company">企业 / 主体名称 <span class="optional-label">可选</span></label><input id="scope-company" class="text-input" type="text" placeholder="从报告正文识别" value="' + esc(draft.companyName) + '" /></div><div class="form-field"><label for="scope-period">报告期间 <span class="optional-label">可选</span></label><input id="scope-period" class="text-input" type="text" placeholder="例如：2023" value="' + esc(draft.period) + '" /></div></div>' +
    '<div class="form-actions"><a class="quiet-button" href="/review/new" data-nav>' + icon('chevron', 14) + '返回上一步</a><button type="button" class="primary-button" data-action="start-review">开始自动复核 ' + icon('arrow', 16) + '</button></div></section>' +
    '<aside class="panel config-boundary"><span class="boundary-icon">' + icon('alert', 18) + '</span><h3>复核如何进行</h3><p>复核使用固定知识库版本异步执行，保留原件、模型调用、检索评分、程序计算与人工决定。</p><ul><li>自动保存复核进展，失败可继续</li><li>证据不足或重要风险转人工</li><li>人工提交后继续剩余复核点</li></ul><span class="boundary-foot">完成后可导出结果与全流程底稿。</span></aside></div>';
}

function findingIcon(type) {
  const cls = type === 'fact_mismatch' ? 'red' : type === 'citation_mismatch' ? 'blue' : type === 'reasoning_gap' ? 'purple' : type === 'risk_omission' ? 'green' : 'amber';
  return '<span class="finding-type ' + cls + '"><span></span>' + esc(typeLabel(type)) + '</span>';
}

export function renderProgress(draft, currentReview) {
  const title = currentReview?.reportName || draft.reportName || '正在复核报告';
  const stages = [['报告已就绪', '已收到报告正文'], ['准备参考资料', '正在固定资料版本并创建任务'], ['逐条核验', '创建任务后自动跳转进度页'], ['确认与导出', '检查待办并下载复核报告']];
  const list = stages.map((stage, index) => '<div class="progress-stage ' + (index === 0 ? 'done' : index === 1 ? 'current' : '') + '"><span class="stage-node">' + (index === 0 ? icon('check', 13) : String(index + 1).padStart(2, '0')) + '</span><div><b>' + stage[0] + '</b><small>' + stage[1] + '</small></div>' + (index === 1 ? '<span class="mini-spinner"></span>' : '') + '</div>').join('');
  return '<div class="progress-page"><a class="subtle-link" href="/dashboard" data-nav>' + icon('chevron', 14) + '返回首页</a><div class="progress-card panel"><div class="progress-symbol"><span class="large-spinner"></span></div><h1>正在等待复核结果</h1><p class="progress-report-title">' + esc(title) + '</p><div class="sync-notice">' + icon('alert', 15) + '<span>正在准备版本化知识库和提交后台任务；任务创建后将展示逐节点执行状态。</span></div><div class="progress-stages">' + list + '</div><div class="waiting-copy">请求处理中。报告较长或接入在线模型时，等待时间可能较长。</div></div></div>';
}

function metricTile(label, value, tone, note) {
  return '<article class="result-metric ' + tone + '"><span>' + label + '</span><b>' + value + '</b><small>' + note + '</small></article>';
}

export function renderOverview(review) {
  const findings = review.findings;
  const high = findings.filter((item) => ['high', 'critical'].includes(String(item.risk).toLowerCase())).length;
  const medium = findings.filter((item) => String(item.risk).toLowerCase() === 'medium').length;
  const low = findings.filter((item) => String(item.risk).toLowerCase() === 'low').length;
  const supported = findings.filter((item) => item.status === 'SUPPORTED').length;
  const contradicted = findings.filter((item) => item.status === 'CONTRADICTED').length;
  const insufficient = findings.filter((item) => item.status === 'INSUFFICIENT_EVIDENCE').length;
  const typeCounts = new Map();
  for (const item of findings) typeCounts.set(item.type, (typeCounts.get(item.type) || 0) + 1);
  const distribution = Array.from(typeCounts.entries()).map(([type, count]) => '<span class="distribution-item"><i class="type-dot ' + esc(type) + '"></i>' + esc(typeLabel(type)) + '<b>' + count + '</b></span>').join('');
  const rows = findings.map((item, index) => '<tr><td><span class="row-number">' + String(index + 1).padStart(2, '0') + '</span></td><td><b class="finding-text-cell">' + esc(item.text || '（暂无结论文本）') + '</b><small class="table-sub technical-id">复核项编号 · ' + esc(item.id) + '</small></td><td>' + findingIcon(item.type) + '</td><td>' + riskPill(item.risk) + '</td><td>' + '<span class="verdict-text ' + esc(String(item.status).toLowerCase()) + '">' + esc(item.statusLabel) + '</span></td><td>' + item.evidence.length + '</td><td><a class="text-action" href="/review/' + encodeURIComponent(review.reviewId) + '/workspace?finding=' + encodeURIComponent(item.id) + '" data-nav>查看详情 ' + icon('chevron', 13) + '</a></td></tr>').join('');
  const workflow = review.workflowStatus === 'COMPLETED' ? statusPill('COMPLETED') : statusPill(review.workflowStatus);
  return '<div class="page-heading overview-heading"><div><h1>' + esc(review.raw.report_name || review.reportId || '复核结果总览') + '</h1><p>复核 ID：<span class="mono">' + esc(review.reviewId) + '</span></p></div><div class="heading-actions">' + workflow + '<a class="outline-button" href="/review/' + encodeURIComponent(review.reviewId) + '/export" data-nav>' + icon('download', 15) + '导出结果</a><a class="primary-button" href="/review/' + encodeURIComponent(review.reviewId) + '/workspace" data-nav>进入复核工作台 ' + icon('arrow', 15) + '</a></div></div>' +
    '<div class="review-meta-strip"><span>检查项 <b>' + findings.length + '</b></span><span>返回状态 <b>' + esc(workflowLabel(review.workflowStatus)) + '</b></span><span>人工待确认 <b>' + (review.pendingTask?.status === 'PENDING' ? '1' : '0') + '</b></span><span class="meta-note">结果来自本次任务记录</span></div>' +
    '<section class="result-metric-grid">' + metricTile('复核条目', String(findings.length).padStart(2, '0'), 'tone-red', '已完成或待人工确认的复核点') + metricTile('结论冲突', String(contradicted).padStart(2, '0'), 'tone-orange', '报告表述与来源存在冲突') + metricTile('证据不足', String(insufficient).padStart(2, '0'), 'tone-blue', '当前资料尚不足以确认') + metricTile('证据支持', String(supported).padStart(2, '0'), 'tone-green', '来源证据支持该结论') + '</section>' +
    '<section class="overview-lower"><div class="panel overview-list-panel"><div class="panel-heading"><div><h2>结论核验清单</h2><p>优先查看存在冲突、证据不足或待人工确认的结论。</p></div><div class="filter-pill-row"><span>高风险 ' + high + '</span><span>中风险 ' + medium + '</span><span>低风险 ' + low + '</span></div></div><div class="table-scroll"><table class="data-table findings-table"><thead><tr><th></th><th>报告结论 / 复核点</th><th>问题类型</th><th>风险等级</th><th>核验状态</th><th>证据数</th><th></th></tr></thead><tbody>' + (rows || '<tr><td colspan="7"><div class="empty-state compact"><span class="empty-icon green-icon">' + icon('check', 20) + '</span><b>尚未生成复核结论</b><small>任务执行时会逐步保存并展示复核点；错误与重试入口见上方状态。</small></div></td></tr>') + '</tbody></table></div></div>' +
    '<aside class="panel distribution-panel"><div class="panel-heading"><div><h2>检查类型</h2><p>按复核问题类型汇总</p></div></div><div class="distribution-list">' + (distribution || '<span class="no-data">没有可统计的问题类型</span>') + '</div><div class="distribution-foot"><span class="tiny-dot green"></span>支持状态按复核点核验结果显示</div></aside></section>';
}

function renderReportText(review, selectedId) {
  const text = review.reportText || '';
  if (!text) return '<div class="report-text-empty">暂时无法显示报告原文。<br /><small>请刷新任务，或联系系统管理员检查原件保存情况。</small></div>';
  const spans = review.findings.filter((item) => Number.isInteger(item.start) && Number.isInteger(item.end) && item.start >= 0 && item.end > item.start && item.end <= text.length).sort((a, b) => a.start - b.start);
  if (!spans.length) return '<div class="report-plain-text">' + esc(text) + '</div><div class="position-note">尚无可定位的复核点。</div>';
  let cursor = 0;
  const parts = [];
  for (let i = 0; i < spans.length; i += 1) {
    const item = spans[i];
    if (item.start < cursor) continue;
    parts.push(esc(text.slice(cursor, item.start)));
    const kind = item.status === 'CONTRADICTED' || item.type === 'fact_mismatch' ? 'mark-red' : item.type === 'citation_mismatch' ? 'mark-blue' : item.type === 'reasoning_gap' ? 'mark-purple' : item.status === 'SUPPORTED' ? 'mark-green' : 'mark-amber';
    parts.push('<button class="claim-highlight ' + kind + ' ' + (item.id === selectedId ? 'selected' : '') + '" data-select-finding="' + esc(item.id) + '" title="' + esc(typeLabel(item.type)) + ' · ' + esc(item.riskLabel) + '"><span class="claim-index">' + String(i + 1).padStart(2, '0') + '</span>' + esc(text.slice(item.start, item.end)) + '</button>');
    const cited = item.evidence.filter(e => item.evidenceIds?.includes(e.evidence_id));
    const sources = cited.length ? cited : item.evidence.slice(0, 2);
    sources.slice(0,3).forEach((e,index) => {
      const url=e.source_url || e.context_url;
      if(!url)return;
      const relation=({SUPPORTS:'支持证据',PARTIALLY_SUPPORTS:'部分支持',CONTRADICTS:'反向证据',IRRELEVANT:'相关候选待核验'})[e.relation] || '检索来源';
      parts.push('<span class="inline-evidence"><a class="evidence-link" data-inline-evidence="'+esc(e.evidence_id)+'" data-inline-finding="'+esc(item.id)+'" data-inline-review="'+esc(review.reviewId)+'" href="/review/'+encodeURIComponent(review.reviewId)+'/workspace?finding='+encodeURIComponent(item.id)+'" aria-label="在证据区打开 '+esc(e.source)+' 原文件">[证据 '+(index+1)+']</a><span class="evidence-hover" role="tooltip"><b>'+esc(e.source)+(e.page?' · 第 '+esc(e.page)+' 页':'')+'</b><small>'+esc(relation)+'</small><p>'+esc(evidenceText(e.quote || e.content).slice(0,650))+'</p><small>点击在证据区查看原件 · '+esc(e.document_version)+'</small></span></span>');
    });
    cursor = item.end;
  }
  parts.push(esc(text.slice(cursor)));
  const omissions=review.findings.filter(f=>f.type==='risk_omission' && (f.end===f.start)).map(f=>'<div class="report-level-note"><b>报告整体风险覆盖提醒</b><p>'+esc(f.text)+'</p></div>').join('');
  return '<div class="report-plain-text annotated-text">' + parts.join('') + omissions + '</div><div class="position-note">高亮对应报告原文；证据链接可查看来源。</div>';
}

function emptyState(title, copy) { return `<div class="empty-state"><span class="empty-icon">${icon('search',22)}</span><b>${title}</b><small>${copy}</small></div>`; }

export function selectEvidence(finding, selectedEvidenceId) {
  const evidence=finding?.evidence || [];
  const used=finding?.evidenceIds || [];
  return evidence.find(e=>e.evidence_id===selectedEvidenceId) || evidence.find(e=>used.includes(e.evidence_id) && e.relation==='SUPPORTS') || evidence.find(e=>used.includes(e.evidence_id) && e.relation!=='IRRELEVANT') || evidence.find(e=>e.relation==='SUPPORTS') || evidence.find(e=>e.relation==='PARTIALLY_SUPPORTS') || evidence[0];
}

function renderEvidence(review, finding, selectedEvidenceId, sourceView = '', keyword = '', readerState = {}) {
  const selected=selectEvidence(finding,selectedEvidenceId);
  if(!selected)return emptyState('等待来源材料','初步检索完成后，点击左侧材料即可在此核对原件。');
  const pdfPath=evidencePdfPath(selected), isWeb=selected.source_type==='web';
  const docId=selected.document_id || '';
  const anchor=(selected.snapshot_url || selected.context_url || '').split('#')[1] || selected.evidence_id.split(':').pop();
  const showText=sourceView==='extracted';
  const temporal=selected.temporal || {};
  const page=Number(readerState.sourcePage || selected.page || 1);
  const info=readerState.sourceInfo?.[docId] || {};
  const originalId=(pdfPath?.match(/documents\/([^/]+)/) || [])[1] || docId;
  const webUrl='/v1/documents/'+encodeURIComponent(docId)+'/original-view?'+new URLSearchParams({highlight:plainEvidenceText(selected.quote || ''),keyword,parent:anchor});
  const pdfPreview='/v1/documents/'+encodeURIComponent(originalId)+'/pages/'+page+'.png?'+new URLSearchParams({highlight:[plainEvidenceText(selected.quote || ''),keyword].filter(Boolean).join('\n')});
  return `<div class="original-reader-toolbar"><div class="original-source-heading">${icon('file',18)}<div><b title="${esc(selected.source)}">${esc(selected.source || '来源原件')}</b><small>${isWeb?'原始网页离线快照':pdfPath?'PDF 原件':'原始文本材料'} · ${esc(temporal.data_period || selected.period || '期间未知')}</small></div></div><div class="original-reader-controls">${pdfPath?`<label for="original-page">第</label><input id="original-page" class="text-input page-number-input" type="number" min="1" max="${info.page_count || 1000}" value="${page}" aria-label="原件页码" /><span>页${info.page_count?' / '+info.page_count:''}</span><button class="quiet-button small" data-action="original-page-go">跳转</button>`:''}<label class="sr-only" for="web-evidence-keyword">在原件中高亮关键词</label><input id="web-evidence-keyword" class="text-input original-keyword" value="${esc(keyword)}" placeholder="在原件中查找" /><button class="outline-button small" data-action="highlight-web">高亮定位</button></div></div>
  <p class="original-reader-note">${isWeb?'保留原始网页结构及可取得的样式；原站脚本已禁用，动态内容可能缺失。':pdfPath?'展示真实 PDF 原页，高亮仅覆盖本页实际匹配的文字，不改写原件。':'按原始文本展示，不添加不存在的页码。'} <button class="text-action" data-action="evidence-${showText?(isWeb?'web':'pdf'):'extracted'}">${showText?'返回原件':'查看正文摘录'}</button></p>
  ${showText?'<article class="paper-body original-text-fallback">'+renderEvidenceContent(selected.content,selected.quote)+'</article>':isWeb?`<iframe class="web-snapshot-frame original-web-frame" title="原始网页快照，定位引用与关键词" sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer" src="${esc(workbenchApi.link(webUrl))}"></iframe>`:pdfPath?`<div class="pdf-source-view is-loading original-pdf" data-original-document="${esc(docId)}"><p class="pdf-load-status" role="status">正在读取 PDF 原页…</p><div class="pdf-page-scroll" tabindex="0" role="region" aria-label="PDF 原页，可滚动查看"><img data-pdf-page-image class="pdf-page-image" alt="${esc(selected.source)}，第 ${page} 页原件及实际文字高亮" src="${esc(workbenchApi.link(pdfPreview))}" /></div><p class="pdf-preview-error" hidden>暂时无法读取本页，可打开原件或核对页码后重试。</p></div>`:'<article class="paper-body original-text-fallback">'+renderEvidenceContent(selected.content,selected.quote)+'</article>'}
  <details class="original-source-details"><summary>来源时间与版本</summary><dl><dt>发布 / 更新</dt><dd>${esc(temporal.published_at || '未知')} / ${esc(temporal.updated_at || '未声明')}</dd><dt>抓取</dt><dd>${esc(temporal.fetched_at || '未记录')}</dd><dt>资料版本</dt><dd>${esc(selected.document_version || '未记录')}</dd><dt>来源定位</dt><dd>${esc(selected.evidence_id)}</dd></dl>${selected.original_url?'<a target="_blank" rel="noopener noreferrer" href="'+esc(selected.original_url)+'">打开当前网站原页</a>':pdfPath?'<a target="_blank" rel="noopener" href="'+esc(workbenchApi.link(pdfPath))+'">打开 PDF 原件</a>':''}</details>`;
}

export function filterFindings(review, state) {
  return review.findings.filter(f=>(!state.typeFilter || f.type===state.typeFilter) && (!state.riskFilter || (state.riskFilter==='high' ? ['high','critical'].includes(String(f.risk).toLowerCase()) : String(f.risk).toLowerCase()===state.riskFilter)) && (!state.pendingOnly || f.humanTask?.status==='PENDING'));
}

function renderHumanForm(review, selected) {
  const task=selected.humanTask;
  if (task?.status!=='PENDING') return selected.humanDecision ? `<section class="human-saved"><h3>人工判定已保存</h3>${selected.humanDecision.comment && selected.humanDecision.comment!==selected.reason ? '<p>'+esc(selected.humanDecision.comment)+'</p>':''}${selected.finalText?'<h4>修订后的结论</h4><p>'+esc(selected.finalText)+'</p>':''}<small>复核人：${esc(selected.humanDecision.decided_by || '未提供')}</small></section>` : '<p class="field-hint">此项无需人工确认。可查看来源证据或继续其他复核项。</p>';
  return `<section class="human-review" data-human-form-key="${esc(review.reviewId+':'+selected.id)}"><h3>提交人工判定</h3><p class="field-hint">先核对右侧证据，再记录你的判断。提交后保留判定与底稿，更新待办进度。</p>
    <div class="form-field"><label for="human-comment">判定理由 <em>必填</em></label><textarea id="human-comment" class="text-area comment-input" required placeholder="说明证据如何支持、反驳或不足以核验这条结论"></textarea></div>
    <div class="form-field"><label for="human-reviewer">复核人</label><input id="human-reviewer" class="text-input" value="本机复核人" /></div>
    <fieldset class="human-evidence-options"><legend>采用的证据（可多选）</legend>${selected.evidence.map(e=>`<label><input type="checkbox" name="human-evidence" value="${esc(e.evidence_id)}" /> <span>${esc(e.source || '未命名来源')}${e.page?' · 第 '+esc(e.page)+' 页':''}</span></label>`).join('') || '<p class="field-hint">暂无可选来源，请补充证据或确认证据不足。</p>'}</fieldset>
    <details class="correction-details"><summary>修订报告结论（可选）</summary><label class="field-hint" for="human-correction">修订后的结论</label><textarea class="text-area" id="human-correction" placeholder="保留原始表述，并单独记录修订内容"></textarea></details>
    <fieldset class="decision-options"><legend>最终判定</legend><label><input type="radio" name="decision" value="SUPPORTED" /><span>有证据支持</span></label><label><input type="radio" name="decision" value="CONTRADICTED" /><span>存在事实冲突</span></label><label><input type="radio" name="decision" value="INSUFFICIENT_EVIDENCE" /><span>证据不足</span></label></fieldset>
    <button class="primary-button submit-decision" data-action="submit-decision">${icon('check',16)}保存判定并继续</button><p id="decision-error" class="form-error" role="alert"></p>
    <details class="supplement-details"><summary>还需要更多证据？</summary><label class="field-hint" for="supplement-query">补充检索关键词</label><div class="search-row"><input class="text-input" id="supplement-query" placeholder="例如：2024 年营业收入" /><button class="outline-button" data-action="supplement">检索证据</button></div><p class="field-hint">在本次任务固定的资料版本内检索，新增候选仍需人工核对。</p></details></section>`;
}

export function renderWorkspace(review, findingId, state) {
  const filtered=filterFindings(review,state);
  const selected=filtered.find(f=>f.id===findingId) || filtered[0] || null;
  const base='/review/'+encodeURIComponent(review.reviewId);
  const items=filtered.map((f,i)=>{
    const chosen=f.id===selected?.id;
    const preferred=selectEvidence(f,state.selectedEvidenceId);
    const rank=e=>(e.evidence_id===preferred?.evidence_id?100:0)+(f.evidenceIds.includes(e.evidence_id)?10:0)+({SUPPORTS:4,CONTRADICTS:3,PARTIALLY_SUPPORTS:2}[e.relation] || 0);
    const byOriginal=new Map();
    for(const e of [...f.evidence].sort((a,b)=>rank(b)-rank(a))){
      const key=(e.document_id || e.source || e.evidence_id)+':'+(e.page || 'web');
      if(!byOriginal.has(key))byOriginal.set(key,e);
    }
    const materials=[...byOriginal.values()];
    const label=f.unreviewed?'待检索与判断':['failed','disputed','unresolved_extraction'].includes(f.labelingStatus)?'标签待确认':f.issueTypes.length?f.issueTypes.map(typeLabel).join(' · '):f.status==='CONTRADICTED'?'事实或数值冲突':f.status==='SUPPORTED'?'未发现问题':'类别待确认';
    return `<article class="review-queue-item ${chosen?'active':''}"><button class="queue-claim" data-select-finding="${esc(f.id)}" aria-pressed="${chosen}"><span class="queue-number">${String(i+1).padStart(2,'0')}</span><span><b>${esc(f.text)}</b><small class="queue-label">${esc(label)}${f.humanTask?.status==='PENDING'?' · 待确认':''}</small></span></button>${chosen?`<div class="queue-item-content">${f.reason?'<p class="queue-issue-reason">'+esc(f.reason.replace(/Child/g,'本条结论'))+'</p>':''}<h3>初步检索的原材料 <span>${materials.length}</span></h3><div class="queue-materials">${materials.map((e,index)=>`<button class="queue-material ${selectEvidence(f,state.selectedEvidenceId)?.evidence_id===e.evidence_id?'selected':''}" data-select-evidence="${esc(e.evidence_id)}" data-material-finding="${esc(f.id)}" title="${esc(e.source)}"><span>${icon('file',15)}<b>${esc(e.source || '未命名原件')}</b></span><small>${e.page?'第 '+esc(e.page)+' 页 · ':''}${esc(e.temporal?.data_period || e.period || e.parent_id || '期间待确认')} · ${esc(relationLabel(e.relation))}</small></button>`).join('') || '<p class="field-hint">'+(f.unreviewed?'尚未处理此项，检索到的材料将在这里出现。':'未取得可用原材料，保留待人工补充。')+'</p>'}</div><details class="queue-adjudication"><summary>${f.humanTask?.status==='PENDING'?'人工确认此项':'查看复核记录'}</summary>${renderHumanForm(review,f)}</details></div>`:''}</article>`;
  }).join('');
  return `<div class="workspace-toolbar"><div class="workspace-report-title"><a class="back-link" href="${base}/overview" data-nav>${icon('chevron',16)}返回总览</a><div><h1>${esc(review.raw.report_name || review.reportId || '报告复核')}</h1><p>${workflowLabel(review.workflowStatus)} · ${review.findings.length} 项 · ${review.findings.filter(f=>f.humanTask?.status==='PENDING').length} 项待人工确认</p></div></div><div class="heading-actions"><button class="outline-button" data-action="toggle-compare" aria-pressed="${!!state.compareMode}">${state.compareMode?'收起待核报告':'查看待核报告'}</button><a class="outline-button" href="${base}/export" data-nav>${icon('download',16)}下载</a><button class="quiet-button" data-audit-job="${esc(review.reviewId)}">工作底稿</button></div></div>
  ${state.compareMode?'<details class="report-context" open><summary>待复核报告原文</summary><div class="report-reader">'+renderReportText(review,selected?.id)+'</div></details>':''}
  <section class="review-desk"><aside class="workspace-column review-queue" aria-label="待复核列表"><div class="column-head"><h2>待复核列表</h2><span>${filtered.length} 项</span></div><div class="queue-filters"><label class="pending-filter"><input type="checkbox" id="pending-only" ${state.pendingOnly?'checked':''} />只看待人工确认</label><label class="sr-only" for="filter-type">问题类别</label><select id="filter-type" aria-label="按问题类型筛选"><option value="">全部类别</option>${[...new Set(review.findings.map(f=>f.type))].map(t=>'<option value="'+esc(t)+'" '+(state.typeFilter===t?'selected':'')+'>'+esc(typeLabel(t))+'</option>').join('')}</select><button class="text-action" data-action="clear-filters">清除筛选</button></div><div class="finding-nav-list">${items || emptyState('没有匹配的复核项','调整筛选条件，或清除筛选查看全部结论。')}</div></aside>
  <section class="workspace-column original-material-column" aria-label="原始材料"><div class="column-head"><h2>原始材料</h2><span>定位到原件核对</span></div><div class="evidence-body">${selected?renderEvidence(review,selected,state.selectedEvidenceId,state.sourceView,state.webKeyword,state):emptyState('选择一条结论','原始 PDF 或网页将显示在这里。')}</div></section></section>`;
}

export function renderHistory(history) {
  const rows = history.map((item) => '<tr><td><b>' + esc(item.reportName || '未命名报告') + '</b><small class="table-sub">' + esc(item.reportId || '') + '</small></td><td>' + esc(item.reportType || '金融报告') + '</td><td>' + formatTime(item.savedAt) + '</td><td>' + statusPill(item.status) + '</td><td>' + (item.findingCount ?? '—') + '</td><td><button class="text-action" data-open-review="' + esc(item.reviewId) + '">打开 ' + icon('chevron', 13) + '</button></td></tr>').join('');
  return '<div class="page-heading"><div><h1>复核任务</h1><p>按报告名称和状态查找任务，继续未完成的复核。</p></div><a class="primary-button" href="/review/new" data-nav>' + icon('plus', 16) + '新建任务</a></div><section class="panel history-panel"><div class="task-filters"><label for="history-search">搜索报告</label><input id="history-search" class="text-input" type="search" placeholder="输入报告名称或编号" /><label for="history-status">任务状态</label><select id="history-status" class="text-input"><option value="">全部状态</option><option value="HUMAN_REVIEW_REQUIRED">待人工确认</option><option value="RUNNING">复核中</option><option value="COMPLETED">复核完成</option><option value="FAILED">执行失败</option><option value="CANCELLED">已取消</option><option value="INTERRUPTED">执行中断</option><option value="QUEUED">排队中</option></select><span id="history-matches" role="status"></span></div><div class="panel-heading"><div><h2>复核任务</h2><p>查看任务进展，继续复核或导出结果。</p></div><span class="fixed-tag">' + history.length + ' 条</span></div><div class="table-scroll"><table class="data-table"><thead><tr><th>报告名称</th><th>类型</th><th>创建时间</th><th>状态</th><th>复核项</th><th></th></tr></thead><tbody>' + (rows || '<tr><td colspan="6"><div class="empty-state"><span class="empty-icon">' + icon('clock', 22) + '</span><b>暂无历史任务</b><small>复核完成后，任务索引会显示在这里。</small></div></td></tr>') + '</tbody></table></div></section>';
}

export function renderModulePlaceholder(title, description) {
  return '<div class="page-heading"><div><h1>' + esc(title) + '</h1><p>' + esc(description) + '</p></div></div><div class="panel module-placeholder"><span class="module-placeholder-icon">' + icon('database', 24) + '</span><h2>该功能暂不可用</h2><p>我没有添加模拟数据或虚假的配置入口。现有后端已提供的能力可以在复核工作台中查看。</p><a class="primary-button" href="/dashboard" data-nav>返回工作台 ' + icon('arrow', 15) + '</a></div>';
}

export function renderSettings(apiBase, health) {
  return '<div class="page-heading"><div><h1>系统设置</h1><p>配置浏览器连接的复核服务地址。</p></div></div><section class="panel connection-panel"><div class="panel-heading"><div><h2>API 连接</h2><p>设置本机复核服务地址，并检查连接状态。</p></div><span class="status-pill ' + (health === true ? 'green' : health === false ? 'red' : 'gray') + '"><i></i>' + (health === true ? '已连接' : health === false ? '连接失败' : '检查中') + '</span></div><div class="form-field"><label for="api-base">API 基础地址</label><input id="api-base" class="text-input" type="url" placeholder="留空使用当前网页同源 API" value="' + esc(apiBase) + '" /><small class="field-hint">例如：http://127.0.0.1:8000 · 地址仅保存在此浏览器。</small></div><div class="form-actions left-actions"><button class="outline-button" data-action="save-api-base">保存并测试连接</button><button class="quiet-button" data-action="reset-api-base">恢复同源</button></div><details class="api-endpoints"><summary>技术接口详情</summary><code>GET /health/live</code><code>POST /v1/reviews</code><code>GET /v1/reviews/{review_id}</code><code>GET /v1/human-tasks</code><code>POST /v1/human-tasks/{review_id}/decision</code></details></section>';
}

export function renderExport(review) {
  const rows = review.findings.map((item, index) => '<tr><td>' + (index + 1) + '</td><td>' + esc(item.id) + '</td><td>' + esc(item.text) + '</td><td>' + esc(item.typeLabel) + '</td><td>' + esc(item.riskLabel) + '</td><td>' + esc(item.statusLabel) + '</td><td>' + item.evidence.length + '</td></tr>').join('');
  return '<div class="page-heading"><div><h1>复核结果导出</h1><p>下载服务端生成的复核报告，或含原件、知识库快照和全流程底稿的归档包。</p></div><a class="quiet-button" href="/review/' + encodeURIComponent(review.reviewId) + '/overview" data-nav>' + icon('chevron', 14) + '返回总览</a></div><section class="panel export-panel"><div class="panel-heading"><div><h2>' + esc(review.raw.report_name || review.reportId || '复核结果') + '</h2><p>任务编号 · ' + esc(review.reviewId) + '</p></div><span class="fixed-tag">' + review.findings.length + ' 个复核项</span></div><div class="export-stats"><span>证据支持 <b>' + review.findings.filter(f=>f.status==='SUPPORTED').length + '</b></span><span>存在冲突 <b>' + review.findings.filter(f=>f.status==='CONTRADICTED').length + '</b></span><span>证据不足 <b>' + review.findings.filter(f=>f.status==='INSUFFICIENT_EVIDENCE').length + '</b></span></div><div class="table-scroll"><table class="data-table"><thead><tr><th>#</th><th>复核项编号</th><th>报告结论</th><th>问题类型</th><th>风险</th><th>核验状态</th><th>证据数</th></tr></thead><tbody>' + (rows || '<tr><td colspan="7">暂无复核结果。</td></tr>') + '</tbody></table></div><div class="form-actions">' + exportLink(review.reviewId,'pdf','下载复核报告 PDF') + exportLink(review.reviewId,'html','下载报告 HTML') + exportLink(review.reviewId,'zip','下载完整工作底稿 ZIP') + exportLink(review.reviewId,'csv','下载问题清单 CSV') + exportLink(review.reviewId,'json','下载完整记录 JSON') + '</div><div class="export-boundary">未完成或待人工任务导出为阶段报告；底稿 ZIP 保留来源原件和每一步的输入输出。</div></section>';
}

export function renderError(title, message) {
  return '<section class="panel error-panel"><span class="error-icon">' + icon('alert', 24) + '</span><h1>' + esc(title) + '</h1><p>' + esc(message) + '</p><a class="primary-button" href="/dashboard" data-nav>返回首页</a></section>';
}

export function downloadCSV(review) {
  const header = ['finding_id', 'claim', 'issue_type', 'risk_level', 'verdict', 'reason', 'evidence_ids'];
  const quote = (value) => '"' + String(value ?? '').replace(/"/g, '""') + '"';
  const lines = [header.map(quote).join(',')];
  for (const item of review.findings) lines.push([item.id, item.text, item.typeLabel, item.riskLabel, item.status, item.reason, item.evidence.map((source) => source.evidence_id).join(';')].map(quote).join(','));
  const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  downloadBlob(blob, safeFileName(review.reportId || 'review') + '-findings.csv');
}

export function downloadJSON(review) {
  const blob = new Blob([JSON.stringify(review.raw, null, 2)], { type: 'application/json;charset=utf-8' });
  downloadBlob(blob, safeFileName(review.reportId || 'review') + '-review.json');
}

function safeFileName(value) { return String(value).replace(/[\\/:*?"<>|\s]+/g, '-').slice(0, 80) || 'review'; }
function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
