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
  shield: '<path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11"/><path d="m9 12 2 2 4-4"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
  align: '<path d="M3 6h18M3 12h12M3 18h18"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.1 0l3-3a5 5 0 0 0-7.1-7.1l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.1 0l-3 3a5 5 0 0 0 7.1 7.1l1.7-1.7"/>',
  close: '<path d="m18 6-12 12M6 6l12 12"/>',
};

export function icon(name, size = 18) {
  return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[name] || ICONS.file) + '</svg>';
}

const NAV = [
  { label: '首页', href: '/dashboard', icon: 'home' },
  { label: '报告复核', href: '/review/new', icon: 'file' },
  { label: '历史记录', href: '/history', icon: 'clock' },
  { label: '知识库', href: '/knowledge', icon: 'book' },
  { label: '规则配置', href: '/rules', icon: 'sliders' },
  { label: '数据管理', href: '/data', icon: 'database' },
  { label: '模型管理', href: '/models', icon: 'cube' },
];

export function renderShell(activePath, content, apiStatus) {
  const nav = NAV.map((item) => '<a class="nav-link ' + (activePath === item.href ? 'active' : '') + '" href="' + item.href + '" data-nav>' + icon(item.icon) + '<span>' + item.label + '</span></a>').join('');
  const api = apiStatus === true ? '<span class="service-dot online"></span><span>复核服务正常</span>' : apiStatus === false ? '<span class="service-dot offline"></span><span>复核服务离线</span>' : '<span class="service-dot pending"></span><span>检查连接中</span>';
  return '<div class="app-shell">' +
    '<aside class="sidebar"><a class="brand" href="/dashboard" data-nav><span class="brand-mark">' + icon('shield', 21) + '</span><span class="brand-copy"><strong>金融报告复核</strong><small>AI Review Workspace</small></span></a>' +
    '<div class="nav-caption">工作空间</div><nav class="main-nav">' + nav + '</nav>' +
    '<div class="sidebar-spacer"></div><div class="sidebar-assurance"><span class="assurance-icon">' + icon('link', 16) + '</span><span><b>证据可追溯</b><small>结论可解释 · 人机协同</small></span></div>' +
    '<button class="nav-link settings-link ' + (activePath === '/settings' ? 'active' : '') + '" data-nav-to="/settings">' + icon('settings') + '<span>系统设置</span></button>' +
    '<div class="user-card"><span class="avatar">审</span><span><b>本地复核员</b><small>审核工作台</small></span><span class="user-menu">···</span></div></aside>' +
    '<main class="main-area"><header class="topbar"><div class="breadcrumbs"><span>复核工作台</span><span class="crumb-divider">/</span><b>' + esc(pageName(activePath)) + '</b></div><div class="topbar-right"><span class="api-indicator">' + api + '</span><button class="icon-button" aria-label="刷新服务状态" data-action="refresh-health">' + icon('clock', 16) + '</button><span class="top-avatar">审</span></div></header>' +
    '<div class="page-content">' + content + '</div></main></div>';
}

function pageName(path) {
  if (path === '/dashboard') return '首页';
  if (path === '/review/new') return '新建复核';
  if (path === '/review/new/settings') return '复核设置';
  if (path.includes('/workspace')) return '报告复核';
  if (path.includes('/overview')) return '复核结果';
  if (path.includes('/export')) return '导出结果';
  if (path === '/history') return '历史记录';
  if (path === '/settings') return '系统设置';
  return '工作空间';
}

function statusPill(status) {
  const cls = status === 'COMPLETED' ? 'green' : status === 'HUMAN_REVIEW_REQUIRED' ? 'amber' : status === 'CANCELLED' ? 'gray' : 'blue';
  const label = ({ COMPLETED: '复核完成', HUMAN_REVIEW_REQUIRED: '待人工确认', CHILD_COMPLETED: '部分完成', CANCELLED: '已取消' })[status] || status || '未知';
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

export function renderDashboard({ history, humanTasks, health }) {
  const pending = Array.isArray(humanTasks) ? humanTasks.length : 0;
  const done = history.filter((item) => item.status === 'COMPLETED').length;
  const totalFindings = history.reduce((sum, item) => sum + Number(item.findingCount || 0), 0);
  const summary = [
    ['本机任务索引', String(history.length).padStart(2, '0'), '记录仅保存在此浏览器', 'file', 'navy'],
    ['待人工确认', String(pending).padStart(2, '0'), health === true ? '来自当前复核 API' : 'API 连接后可读取', 'alert', 'amber'],
    ['已完成复核', String(done).padStart(2, '0'), '按本机历史记录统计', 'check', 'teal'],
    ['累计复核项', String(totalFindings).padStart(2, '0'), '来源：已保存的复核结果', 'align', 'purple'],
  ].map((item) => '<article class="metric-card"><div class="metric-top"><span>' + item[0] + '</span><span class="metric-icon ' + item[4] + '">' + icon(item[3], 17) + '</span></div><strong class="metric-value">' + item[1] + '</strong><small>' + item[2] + '</small></article>').join('');

  const rows = history.slice(0, 7).map((item) => '<tr><td><span class="report-file-icon">' + icon('file', 16) + '</span></td><td><b>' + esc(item.reportName || '未命名报告') + '</b><small class="table-sub">' + esc(item.reportId || '') + '</small></td><td><span class="type-tag">' + esc(item.reportType || '金融报告') + '</span></td><td>' + formatTime(item.savedAt) + '</td><td>' + statusPill(item.status) + '</td><td class="numeric-cell">' + (item.findingCount ?? '—') + '</td><td><button class="text-action" data-open-review="' + esc(item.reviewId) + '">打开 ' + icon('chevron', 14) + '</button></td></tr>').join('');
  const pendingRows = (Array.isArray(humanTasks) ? humanTasks : []).slice(0, 3).map((task) => '<button class="pending-task" data-open-review="' + esc(task.review_id) + '"><span class="pending-number">' + icon('alert', 15) + '</span><span class="pending-copy"><b>' + esc(task.fact || task.fact_id || '待确认结论') + '</b><small>任务 ' + esc(task.task_id || '') + '</small></span>' + riskPill('') + icon('chevron', 15) + '</button>').join('');
  return '<section class="welcome-row"><div><div class="eyebrow"><span class="eyebrow-line"></span> REVIEW OPERATIONS</div><h1>报告复核中心</h1><p>以证据为基础，让 AI 生成的金融分析更可靠。</p></div><a class="primary-button" href="/review/new" data-nav>' + icon('plus', 17) + '新建复核任务</a></section>' +
    '<section class="metric-grid">' + summary + '</section>' +
    '<section class="home-panels"><div class="panel recent-panel"><div class="panel-heading"><div><h2>最近任务</h2><p>仅显示当前浏览器保存的任务索引</p></div><a class="subtle-link" href="/history" data-nav>查看历史 ' + icon('arrow', 14) + '</a></div>' +
    '<div class="table-scroll"><table class="data-table"><thead><tr><th></th><th>报告名称</th><th>报告类型</th><th>提交时间</th><th>当前状态</th><th>问题数</th><th></th></tr></thead><tbody>' + (rows || '<tr><td colspan="7"><div class="empty-state compact"><span class="empty-icon">' + icon('file', 21) + '</span><b>还没有复核任务</b><small>新建任务后，结果会显示在这里。</small></div></td></tr>') + '</tbody></table></div></div>' +
    '<aside class="panel queue-panel"><div class="panel-heading"><div><h2>人工复核队列</h2><p>后端当前待处理任务</p></div><span class="queue-count">' + pending + '</span></div><div class="pending-list">' + (pendingRows || '<div class="queue-empty">' + icon('check', 20) + '<b>暂无待确认事项</b><small>连接后端并运行复核后，待人工任务会出现在这里。</small></div>') + '</div><div class="queue-foot"><span class="service-dot ' + (health === true ? 'online' : health === false ? 'offline' : 'pending') + '"></span>' + (health === true ? '实时 API 已连接' : health === false ? 'API 当前不可用' : '正在检查 API') + '</div></aside></section>' +
    '<section class="trust-strip"><span class="trust-mark">' + icon('shield', 17) + '</span><b>审慎复核</b><span>每条结论关联证据与核验状态</span><i></i><b>人工把关</b><span>由复核员提交明确判定与意见</span><i></i><b>过程可查</b><span>保留 API 返回的检索轨迹</span></section>';
}

export function renderNewReview(draft) {
  const fileName = draft.reportFileName ? '<span class="selected-file">' + icon('file', 15) + '<b>' + esc(draft.reportFileName) + '</b><button type="button" data-action="clear-report-file" aria-label="移除文件">' + icon('close', 14) + '</button></span>' : '';
  const sources = draft.sourceFiles.map((item, index) => '<span class="source-chip">' + icon('file', 14) + esc(item.name) + '<button type="button" data-remove-source="' + index + '" aria-label="移除 ' + esc(item.name) + '">' + icon('close', 13) + '</button></span>').join('');
  return '<div class="page-heading"><div><div class="eyebrow"><span class="eyebrow-line"></span> NEW REVIEW</div><h1>新建报告复核</h1><p>提交报告正文和可选参考材料。复核结果由现有 API 实际生成。</p></div><a class="quiet-button" href="/dashboard" data-nav>' + icon('chevron', 15) + '返回首页</a></div>' +
    '<div class="stepper"><div class="step active"><span>1</span><b>上传报告</b></div><i></i><div class="step"><span>2</span><b>复核设置</b></div><i></i><div class="step"><span>3</span><b>自动复核</b></div><i></i><div class="step"><span>4</span><b>人工复核</b></div></div>' +
    '<div class="intake-layout"><section class="panel intake-main"><div class="section-title"><span class="section-index">01</span><div><h2>报告内容</h2><p>当前 API 接收已解析的文本，不接收原始 PDF / Word 文件。</p></div></div>' +
    '<div class="form-grid intake-meta-grid"><div class="form-field"><label for="report-name">报告名称 <em>*</em></label><input id="report-name" class="text-input" type="text" placeholder="例如：XX集团2023年财务分析报告" value="' + esc(draft.reportName) + '" maxlength="160" /></div><div class="form-field"><label for="report-type">报告来源</label><select id="report-type" class="text-input"><option ' + (draft.reportType === 'AI 生成报告' ? 'selected' : '') + '>AI 生成报告</option><option ' + (draft.reportType === '人工撰写报告' ? 'selected' : '') + '>人工撰写报告</option></select><small class="field-hint">该标记仅用于本机任务索引，现有 API 不保存报告类型。</small></div></div>' +
    '<div class="form-field"><div class="field-label-row"><label for="report-text">报告正文 <em>*</em></label><span class="character-count" id="report-character-count">' + draft.reportText.length + ' 字符</span></div><textarea id="report-text" class="text-area report-input" placeholder="粘贴 AI 生成的金融分析报告正文…" spellcheck="false">' + esc(draft.reportText) + '</textarea><div class="field-hint">文本会发送到当前配置的复核 API。请确认不包含不应提交的敏感信息。</div></div>' +
    '<div class="dropzone compact-drop" data-drop="report"><input id="report-file" type="file" accept=".txt,.md,text/plain,text/markdown" hidden /><span class="drop-icon">' + icon('upload', 18) + '</span><div><b>从本机导入文本文件</b><small>支持 .txt、.md · 原始 PDF/Word 暂无解析接口</small></div><button type="button" class="outline-button small" data-action="choose-report">选择文件</button>' + fileName + '</div>' +
    '<div class="form-field source-field"><div class="field-label-row"><div><label>参考证据 <span class="optional-label">可选</span></label><div class="field-hint">将文本按段落拆分为 Evidence，并随复核请求提交。</div></div><label class="outline-button small file-button" for="source-files">' + icon('plus', 14) + '添加文本来源</label><input id="source-files" type="file" accept=".txt,.md,text/plain,text/markdown" multiple hidden /></div><div class="source-file-list">' + (sources || '<span class="no-sources">尚未添加参考来源</span>') + '</div></div>' +
    '<div class="form-actions"><a class="quiet-button" href="/dashboard" data-nav>取消</a><button type="button" class="primary-button" data-action="to-settings">继续：复核设置 ' + icon('arrow', 16) + '</button></div></section>' +
    '<aside class="intake-side"><div class="panel side-note"><div class="note-icon blue-note">' + icon('link', 19) + '</div><h3>证据链随请求传递</h3><p>提供参考材料后，复核结果会保留来源名称、页码（如果有）和原文片段。</p><div class="note-divider"></div><div class="note-check">' + icon('check', 15) + '<span>稳定的 claim / evidence ID</span></div><div class="note-check">' + icon('check', 15) + '<span>支持关系与检索分数</span></div><div class="note-check muted-check">' + icon('alert', 15) + '<span>PDF 原件定位需后端文件接口</span></div></div><div class="privacy-note">' + icon('shield', 16) + '<span>报告正文只在提交时发送给 API。任务索引保存在当前浏览器，不在本机历史中保存正文。</span></div></aside></div>';
}

export function renderReviewSettings(draft) {
  const dimensions = [
    ['事实准确性', '核对数字、时间与来源原文是否一致。'],
    ['引用来源匹配', '检查检索证据与当前结论的相关性。'],
    ['表述合理性', '评估证据是否足以支持当前表述。'],
    ['推理完整性', '结合核验理由与证据关系检查推理断点。'],
    ['风险完整性', '显示后端规则命中与风险路由结果。'],
  ].map((item) => '<div class="dimension-row"><span class="checked-box">' + icon('check', 13) + '</span><span><b>' + item[0] + '</b><small>' + item[1] + '</small></span><span class="dimension-fixed">后端流程</span></div>').join('');
  const sourceNames = draft.sourceFiles.length ? draft.sourceFiles.map((item) => '<span class="source-chip readonly">' + icon('file', 14) + esc(item.name) + '</span>').join('') : '<span class="no-sources">未随请求提供参考证据；检索结果取决于后端检索配置。</span>';
  return '<div class="page-heading"><div><div class="eyebrow"><span class="eyebrow-line"></span> REVIEW CONFIGURATION</div><h1>复核设置</h1><p>查看本次请求实际使用的复核维度和证据范围。</p></div><span class="request-mode"><span class="service-dot online"></span> API 直连模式</span></div>' +
    '<div class="stepper"><div class="step complete"><span>' + icon('check', 13) + '</span><b>上传报告</b></div><i class="filled"></i><div class="step active"><span>2</span><b>复核设置</b></div><i></i><div class="step"><span>3</span><b>自动复核</b></div><i></i><div class="step"><span>4</span><b>人工复核</b></div></div>' +
    '<div class="settings-layout"><section class="panel settings-panel"><div class="panel-heading"><div><h2>复核维度</h2><p>这些检查由后端图流程固定执行，目前 API 不提供单项开关。</p></div><span class="fixed-tag">5 项已启用</span></div><div class="dimension-list">' + dimensions + '</div>' +
    '<div class="settings-divider"></div><div class="panel-heading source-heading"><div><h2>本次参考资料</h2><p>来自上传页，随请求作为 evidence 参数提交。</p></div><a class="text-action" href="/review/new" data-nav>返回修改</a></div><div class="selected-sources">' + sourceNames + '</div>' +
    '<div class="form-grid"><div class="form-field"><label for="scope-company">企业 / 主体名称 <span class="optional-label">可选</span></label><input id="scope-company" class="text-input" type="text" placeholder="从报告正文识别" value="' + esc(draft.companyName) + '" /></div><div class="form-field"><label for="scope-period">报告期间 <span class="optional-label">可选</span></label><input id="scope-period" class="text-input" type="text" placeholder="例如：2023" value="' + esc(draft.period) + '" /></div></div>' +
    '<div class="form-actions"><a class="quiet-button" href="/review/new" data-nav>' + icon('chevron', 14) + '返回上一步</a><button type="button" class="primary-button" data-action="start-review">开始自动复核 ' + icon('arrow', 16) + '</button></div></section>' +
    '<aside class="panel config-boundary"><span class="boundary-icon">' + icon('alert', 18) + '</span><h3>当前 API 能力边界</h3><p>复核 API 同步接收报告文本和内嵌 Evidence，返回 finding、evidence、assessment 与检索轨迹。</p><ul><li>报告类别不会写入后端</li><li>没有实时 Agent 阶段进度</li><li>模型及规则参数由服务端配置</li></ul><span class="boundary-foot">结果完成后会显示实际返回字段。</span></aside></div>';
}

function findingIcon(type) {
  const cls = type === 'fact_mismatch' ? 'red' : type === 'citation_mismatch' ? 'blue' : type === 'reasoning_gap' ? 'purple' : type === 'risk_omission' ? 'green' : 'amber';
  return '<span class="finding-type ' + cls + '"><span></span>' + esc(typeLabel(type)) + '</span>';
}

export function renderProgress(draft, currentReview) {
  const title = currentReview?.reportName || draft.reportName || '正在复核报告';
  const stages = [['客户端校验', '报告正文已在浏览器检查'], ['提交复核请求', 'POST /v1/reviews · 等待 API 响应'], ['后端复核图', '服务端未提供逐阶段状态'], ['复核结果', '等待 Finding 与 Evidence 返回']];
  const list = stages.map((stage, index) => '<div class="progress-stage ' + (index === 0 ? 'done' : index === 1 ? 'current' : '') + '"><span class="stage-node">' + (index === 0 ? icon('check', 13) : String(index + 1).padStart(2, '0')) + '</span><div><b>' + stage[0] + '</b><small>' + stage[1] + '</small></div>' + (index === 1 ? '<span class="mini-spinner"></span>' : '') + '</div>').join('');
  return '<div class="progress-page"><a class="subtle-link" href="/dashboard" data-nav>' + icon('chevron', 14) + '返回首页</a><div class="progress-card panel"><div class="progress-symbol"><span class="large-spinner"></span></div><div class="eyebrow centered">REVIEW IN PROGRESS</div><h1>正在等待复核结果</h1><p class="progress-report-title">' + esc(title) + '</p><div class="sync-notice">' + icon('alert', 15) + '<span>后端当前为同步 API。不会返回实时 Agent 阶段或百分比；收到响应后将直接展示实际复核结果。</span></div><div class="progress-stages">' + list + '</div><div class="waiting-copy">请求处理中。报告较长或接入在线模型时，等待时间可能较长。</div></div></div>';
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
  const rows = findings.map((item, index) => '<tr><td><span class="row-number">' + String(index + 1).padStart(2, '0') + '</span></td><td><b class="finding-text-cell">' + esc(item.text || '（后端未返回 claim 文本）') + '</b><small class="table-sub">Claim ID · ' + esc(item.id) + '</small></td><td>' + findingIcon(item.type) + '</td><td>' + riskPill(item.risk) + '</td><td>' + '<span class="verdict-text ' + esc(String(item.status).toLowerCase()) + '">' + esc(item.statusLabel) + '</span></td><td>' + item.evidence.length + '</td><td><a class="text-action" href="/review/' + encodeURIComponent(review.reviewId) + '/workspace?finding=' + encodeURIComponent(item.id) + '" data-nav>查看详情 ' + icon('chevron', 13) + '</a></td></tr>').join('');
  const workflow = review.workflowStatus === 'COMPLETED' ? statusPill('COMPLETED') : statusPill(review.workflowStatus);
  return '<div class="page-heading overview-heading"><div><div class="eyebrow"><span class="eyebrow-line"></span> REVIEW SUMMARY</div><h1>' + esc(review.reportId || '复核结果总览') + '</h1><p>复核 ID：<span class="mono">' + esc(review.reviewId) + '</span></p></div><div class="heading-actions">' + workflow + '<a class="outline-button" href="/review/' + encodeURIComponent(review.reviewId) + '/export" data-nav>' + icon('download', 15) + '导出结果</a><a class="primary-button" href="/review/' + encodeURIComponent(review.reviewId) + '/workspace" data-nav>进入复核工作台 ' + icon('arrow', 15) + '</a></div></div>' +
    '<div class="review-meta-strip"><span>检查项 <b>' + findings.length + '</b></span><span>返回状态 <b>' + esc(review.workflowStatus) + '</b></span><span>人工待确认 <b>' + (review.pendingTask?.status === 'PENDING' ? '1' : '0') + '</b></span><span class="meta-note">数据均来自当前 API 响应</span></div>' +
    '<section class="result-metric-grid">' + metricTile('复核条目', String(findings.length).padStart(2, '0'), 'tone-red', '按 API 返回的 Claim 数量计数') + metricTile('结论冲突', String(contradicted).padStart(2, '0'), 'tone-orange', 'CONTRADICTED') + metricTile('证据不足', String(insufficient).padStart(2, '0'), 'tone-blue', 'INSUFFICIENT_EVIDENCE') + metricTile('证据支持', String(supported).padStart(2, '0'), 'tone-green', 'SUPPORTED') + '</section>' +
    '<section class="overview-lower"><div class="panel overview-list-panel"><div class="panel-heading"><div><h2>复核问题</h2><p>优先查看存在冲突、证据不足或待人工确认的结论。</p></div><div class="filter-pill-row"><span>高风险 ' + high + '</span><span>中风险 ' + medium + '</span><span>低风险 ' + low + '</span></div></div><div class="table-scroll"><table class="data-table findings-table"><thead><tr><th></th><th>报告结论 / Claim</th><th>问题类型</th><th>风险等级</th><th>核验状态</th><th>Evidence</th><th></th></tr></thead><tbody>' + (rows || '<tr><td colspan="7"><div class="empty-state compact"><span class="empty-icon green-icon">' + icon('check', 20) + '</span><b>后端没有返回 Claim 结果</b><small>请检查报告输入和后端复核运行状态。</small></div></td></tr>') + '</tbody></table></div></div>' +
    '<aside class="panel distribution-panel"><div class="panel-heading"><div><h2>问题类型</h2><p>按 API 返回的 issue_types 汇总</p></div></div><div class="distribution-list">' + (distribution || '<span class="no-data">没有可统计的问题类型</span>') + '</div><div class="distribution-foot"><span class="tiny-dot green"></span>支持状态按 Finding 核验结果显示</div></aside></section>';
}

function renderReportText(review, selectedId) {
  const text = review.reportText || '';
  if (!text) return '<div class="report-text-empty">后端响应没有包含原始报告正文。<br /><small>需要后端持久保存原文或提供报告读取接口。</small></div>';
  const spans = review.findings.filter((item) => Number.isInteger(item.start) && Number.isInteger(item.end) && item.start >= 0 && item.end > item.start && item.end <= text.length).sort((a, b) => a.start - b.start);
  if (!spans.length) return '<div class="report-plain-text">' + esc(text) + '</div><div class="position-note">API 未返回 claim 字符偏移，暂不能在原文精确标注。</div>';
  let cursor = 0;
  const parts = [];
  for (let i = 0; i < spans.length; i += 1) {
    const item = spans[i];
    if (item.start < cursor) continue;
    parts.push(esc(text.slice(cursor, item.start)));
    const kind = item.type === 'fact_mismatch' ? 'mark-red' : item.type === 'citation_mismatch' ? 'mark-blue' : item.type === 'reasoning_gap' ? 'mark-purple' : item.status === 'SUPPORTED' ? 'mark-green' : 'mark-amber';
    parts.push('<button class="claim-highlight ' + kind + ' ' + (item.id === selectedId ? 'selected' : '') + '" data-select-finding="' + esc(item.id) + '" title="' + esc(typeLabel(item.type)) + ' · ' + esc(item.riskLabel) + '"><span class="claim-index">' + String(i + 1).padStart(2, '0') + '</span>' + esc(text.slice(item.start, item.end)) + '</button>');
    cursor = item.end;
  }
  parts.push(esc(text.slice(cursor)));
  return '<div class="report-plain-text annotated-text">' + parts.join('') + '</div><div class="position-note">高亮位置采用后端返回的 source_start / source_end。</div>';
}

function renderReasoning(finding) {
  const evidence = finding.evidence;
  const nodes = evidence.slice(0, 3).map((item) => {
    const relation = String(item.relation || '').toLowerCase();
    const positive = relation === 'supports';
    const partial = relation === 'partially_supports';
    const cls = positive ? 'supported' : partial ? 'partial' : relation === 'contradicts' ? 'contradicted' : 'unknown';
    const label = positive ? '已支持' : partial ? '部分支持' : relation === 'contradicts' ? '存在冲突' : '未判定';
    return '<div class="chain-node"><span class="chain-state ' + cls + '">' + (positive ? icon('check', 12) : partial ? '△' : relation === 'contradicts' ? '×' : '·') + '</span><div class="chain-copy"><b>' + esc(item.content || 'Evidence 原文片段') + '</b><small>' + esc(item.source || item.document_id || '来源未命名') + (item.page ? ' · 第 ' + esc(item.page) + ' 页' : '') + '</small></div><span class="chain-label ' + cls + '">' + label + '</span></div><div class="chain-arrow">↓</div>';
  }).join('');
  const finalStatus = finding.status === 'SUPPORTED' ? 'supported' : finding.status === 'CONTRADICTED' ? 'contradicted' : 'partial';
  return '<div class="reasoning-card"><div class="reasoning-card-head"><span class="reasoning-mark">' + icon('align', 15) + '</span><b>证据与结论</b><span class="chain-source-note">仅展示 API 返回内容</span></div><div class="chain-list">' + (nodes || '<div class="missing-evidence-note">' + icon('alert', 15) + '<span>当前 Finding 没有 Evidence；无法构造数据支持的推理链。</span></div>') + '<div class="chain-node conclusion-node"><span class="chain-state ' + finalStatus + '">' + (finding.status === 'SUPPORTED' ? icon('check', 12) : finding.status === 'CONTRADICTED' ? '×' : '△') + '</span><div class="chain-copy"><b>报告结论：' + esc(finding.text) + '</b><small>' + esc(finding.reason || '后端未返回单独的推理步骤。') + '</small></div><span class="chain-label ' + finalStatus + '">' + esc(finding.statusLabel) + '</span></div></div>' + (!finding.evidence.length ? '' : '<div class="chain-boundary">后端当前没有提供 ReasoningStep[]；此处以真实 Evidence 关系连接 Claim，不补造中间推理节点。</div>') + '</div>';
}

function renderEvidence(review, finding, selectedEvidenceId, evidenceTab) {
  const evidence = finding.evidence;
  const selected = evidence.find((item) => item.evidence_id === selectedEvidenceId) || evidence[0];
  const tabs = evidence.length > 1 ? '<div class="evidence-tabs"><button class="' + (evidenceTab === 'source' ? 'active' : '') + '" data-evidence-tab="source">原文摘录 <span>' + evidence.length + '</span></button><button class="' + (evidenceTab === 'all' ? 'active' : '') + '" data-evidence-tab="all">多源证据 <span>' + evidence.length + '</span></button></div>' : '<div class="single-evidence-tab">来源原文</div>';
  const quote = selected ? '<div class="document-paper"><div class="paper-toolbar"><span class="paper-dot"></span><span class="paper-dot"></span><span class="paper-dot"></span><span class="paper-name">' + esc(selected.source || selected.document_id || '未命名来源') + '</span><span class="paper-page">' + (selected.page ? '第 ' + esc(selected.page) + ' 页' : '页码未提供') + '</span></div><div class="paper-body"><div class="paper-kicker">' + esc(selected.section || '原文片段') + '</div><div class="paper-rule"></div><div class="paper-paragraph"><span class="quote-highlight">' + esc(selected.content || 'Evidence 未返回原文内容。') + '</span></div><div class="paper-meta-line">Evidence ID <span>' + esc(selected.evidence_id || '—') + '</span></div><div class="paper-meta-line">数据期间 <span>' + esc(selected.period || '未提供') + '</span></div><div class="paper-meta-line">检索分数 <span>' + (Number.isFinite(Number(selected.score)) ? Number(selected.score).toFixed(3) : '未提供') + '</span></div></div></div><div class="source-relation"><span class="relation-label ' + esc(String(selected.relation || 'unknown').toLowerCase()) + '">' + esc(selected.relation || '关系未标注') + '</span><span>' + esc(selected.rationale || '后端未返回此 Evidence 的独立评估理由。') + '</span></div>' : '<div class="no-evidence-card"><span class="empty-icon">' + icon('search', 20) + '</span><b>没有检索到 Evidence</b><small>' + (finding.missingNeeds.length ? '缺失需求：' + esc(finding.missingNeeds.join('、')) : '后端响应未包含可展示的 Evidence。') + '</small><small>当前 API 没有单独的补充检索 endpoint。</small></div>';
  const allEvidence = evidence.map((item, index) => '<button class="evidence-source-row ' + (item.evidence_id === selected?.evidence_id ? 'selected' : '') + '" data-select-evidence="' + esc(item.evidence_id) + '"><span class="evidence-source-index">' + String(index + 1).padStart(2, '0') + '</span><span class="evidence-source-copy"><b>' + esc(item.source || item.document_id || '未命名来源') + '</b><small>' + esc(item.section || item.document_version || item.evidence_type || '文本') + (item.page ? ' · p.' + esc(item.page) : '') + '</small><em>' + esc(item.content || '') + '</em></span><span class="relation-dot ' + esc(String(item.relation || '').toLowerCase()) + '"></span></button>').join('');
  const isAll = evidenceTab === 'all' && evidence.length > 1;
  return '<div class="evidence-panel-head"><div><div class="eyebrow small-eyebrow">EVIDENCE SOURCE</div><h3>' + esc(selected?.source || '证据来源') + '</h3><p>' + esc(selected?.section || '来源章节未提供') + (selected?.page ? ' · 第 ' + esc(selected.page) + ' 页' : '') + '</p></div><button class="icon-button" title="证据可追溯" aria-label="Evidence 详情">' + icon('link', 15) + '</button></div>' + tabs +
    (isAll ? '<div class="evidence-source-list">' + allEvidence + '</div>' : '<div class="source-viewer">' + quote + '</div>') +
    '<div class="source-capability-note">' + icon('alert', 14) + '<span>' + (selected?.page ? '后端提供页码，但没有原始 PDF URL / 文件流，暂不支持定位到 PDF 页面。' : '后端尚未提供 PDF 原件与文本坐标；当前展示可追溯的 Evidence 原文。') + '</span></div>' +
    '<div class="evidence-actions"><button class="outline-button small" data-action="copy-evidence" ' + (selected ? '' : 'disabled') + '>' + icon('file', 14) + '复制原文</button><button class="outline-button small" data-evidence-tab="all" ' + (evidence.length > 1 ? '' : 'disabled') + '>' + icon('align', 14) + '多源证据</button></div>';
}

export function renderWorkspace(review, findingId, workspaceState) {
  const filtered = review.findings.filter((item) => {
    if (workspaceState.typeFilter && item.type !== workspaceState.typeFilter) return false;
    if (workspaceState.riskFilter && String(item.risk).toLowerCase() !== workspaceState.riskFilter) return false;
    return true;
  });
  const selected = review.findings.find((item) => item.id === findingId) || filtered[0] || review.findings[0] || null;
  const issues = filtered.map((item, index) => '<button class="finding-nav-item ' + (selected?.id === item.id ? 'active' : '') + '" data-select-finding="' + esc(item.id) + '"><span class="finding-nav-num">' + String(index + 1).padStart(2, '0') + '</span><span class="finding-nav-copy"><b>' + esc(item.text || item.id) + '</b><small>' + findingIcon(item.type) + '</small></span><span class="finding-nav-risk ' + String(item.risk).toLowerCase() + '"></span></button>').join('');
  const activeIndex = selected ? review.findings.findIndex((item) => item.id === selected.id) : -1;
  const task = selected?.humanTask;
  const selectedEvidenceId = selected && selected.evidence.some((item) => item.evidence_id === workspaceState.selectedEvidenceId) ? workspaceState.selectedEvidenceId : (selected?.evidence[0]?.evidence_id || '');
  const center = selected ? '<div class="detail-head"><div class="detail-number">問題 ' + String(activeIndex + 1).padStart(2, '0') + '<span> / ' + String(review.findings.length).padStart(2, '0') + '</span></div><div class="detail-tag-row">' + findingIcon(selected.type) + riskPill(selected.risk) + '<span class="status-pill ' + (task?.status === 'PENDING' ? 'amber' : selected.humanDecision ? 'green' : 'gray') + '"><i></i>' + (task?.status === 'PENDING' ? '待人工确认' : selected.humanDecision ? '已人工判定' : '未进入人工队列') + '</span></div><h2>' + esc(selected.typeLabel) + '</h2></div>' +
    '<div class="detail-scroll"><section class="detail-section"><div class="detail-section-title"><span class="section-dot navy-dot"></span>AI 原结论</div><div class="claim-quote">' + esc(selected.text || '后端未返回 Claim 文本。') + '</div></section><section class="detail-section"><div class="detail-section-title"><span class="section-dot amber-dot"></span>核验说明</div><p class="body-copy">' + esc(selected.reason || '后端没有返回单独的问题描述。请结合 Evidence 关系与核验状态判断。') + '</p></section>' +
    (selected.type === 'reasoning_gap' ? '<section class="detail-section">' + renderReasoning(selected) + '</section>' : '') +
    '<section class="detail-section"><div class="detail-section-title"><span class="section-dot blue-dot"></span>证据缺口</div><div class="missing-need-list">' + (selected.missingNeeds.length ? selected.missingNeeds.map((need) => '<span class="missing-need"><i></i>' + esc(need) + '</span>').join('') : '<span class="no-data inline-no-data">后端未返回缺失需求</span>') + '</div><button class="text-action disabled-action" type="button" disabled title="后端尚未提供补充检索接口">' + icon('search', 14) + '补充检索 <small>接口待补</small></button></section>' +
    '<section class="detail-section"><div class="ai-conclusion"><div class="conclusion-label">' + icon('shield', 15) + 'AI 复核结论</div><p>' + esc(selected.reason || selected.statusLabel + '。具体判断依据见上方 Evidence 与核验状态。') + '</p><span>置信度：' + esc(selected.confidence || '后端未提供') + '</span></div></section>' +
    '<section class="detail-section review-action-section"><div class="detail-section-title"><span class="section-dot teal-dot"></span>人工复核</div>' + (task?.status === 'PENDING' ? '<label class="sr-only" for="human-comment">人工复核意见</label><textarea class="text-area comment-input" id="human-comment" placeholder="填写人工复核意见（可选）"></textarea><div class="decision-buttons"><button class="outline-button" data-human-decision="SUPPORTED">结论有证据支持</button><button class="outline-button danger-outline" data-human-decision="CONTRADICTED">存在事实冲突</button><button class="primary-button" data-human-decision="INSUFFICIENT_EVIDENCE">确认证据不足</button></div><small class="field-hint">将以 task_version 乐观锁提交至现有人工决策 API。</small>' : selected.humanDecision ? '<div class="human-saved"><span class="status-pill green"><i></i>人工判定已提交</span><p>' + esc(selected.humanDecision.comment || selected.humanDecision.decision || '') + '</p></div>' : '<div class="no-human-task">此 Claim 当前没有后端生成的待处理任务。只有后端 risk gate 返回 human task 时，人工决策才可提交。</div>') +
    '<div class="unsupported-actions"><button type="button" disabled title="现有 HumanDecision schema 不支持修改 Claim 文本">修改结论 <small>接口待补</small></button><button type="button" disabled title="现有 API 没有补充检索接口">补充证据 <small>接口待补</small></button></div></section></div>' : '<div class="detail-empty"><span class="empty-icon">' + icon('search', 21) + '</span><b>没有匹配的问题</b><small>调整筛选条件，或查看复核总览。</small></div>';
  const evidenceHtml = selected ? renderEvidence(review, selected, selectedEvidenceId, workspaceState.evidenceTab) : '<div class="detail-empty">尚无 Evidence</div>';
  return '<div class="workspace-toolbar"><div class="workspace-report-title"><a class="back-link" href="/review/' + encodeURIComponent(review.reviewId) + '/overview" data-nav>' + icon('chevron', 15) + '总览</a><span class="toolbar-divider"></span><div><b>' + esc(review.reportId || '金融分析报告') + '</b><small>Review ID · ' + esc(review.reviewId) + '</small></div></div><div class="workspace-toolbar-actions"><button class="outline-button small" data-action="toggle-compare">' + icon('align', 14) + (workspaceState.compareMode ? '退出对照' : '证据对照') + '</button><button class="icon-button" title="复核结果" data-nav-to="/review/' + encodeURIComponent(review.reviewId) + '/export">' + icon('download', 15) + '</button></div></div>' +
    '<div class="workspace-meta-line"><span class="workspace-status"><i></i>' + esc(review.workflowStatus) + '</span><span>' + review.findings.length + ' 个 Claim / 复核项</span><span>' + (review.pendingTask?.status === 'PENDING' ? '1 项待人工确认' : '无待处理人工任务') + '</span><span class="keyboard-hint"><kbd>J</kbd><kbd>K</kbd> 切换问题</span></div>' +
    '<section class="workspace-grid ' + (workspaceState.compareMode ? 'compare-mode' : '') + '"><div class="workspace-column report-column"><div class="column-head"><div><span class="column-kicker">01 / REPORT</span><h2>AI 生成报告</h2></div><span class="column-count">原文</span></div><div class="report-filters"><select id="filter-type" aria-label="按问题类型筛选"><option value="">所有类型</option>' + Array.from(new Set(review.findings.map((item) => item.type))).map((type) => '<option value="' + esc(type) + '" ' + (workspaceState.typeFilter === type ? 'selected' : '') + '>' + esc(typeLabel(type)) + '</option>').join('') + '</select><select id="filter-risk" aria-label="按风险筛选"><option value="">所有风险</option><option value="high" ' + (workspaceState.riskFilter === 'high' ? 'selected' : '') + '>高风险</option><option value="medium" ' + (workspaceState.riskFilter === 'medium' ? 'selected' : '') + '>中风险</option><option value="low" ' + (workspaceState.riskFilter === 'low' ? 'selected' : '') + '>低风险</option></select></div><div class="report-reader">' + renderReportText(review, selected?.id) + '</div><div class="legend-row"><span><i class="legend red"></i>事实冲突</span><span><i class="legend amber"></i>证据不足 / 表述</span><span><i class="legend blue"></i>引用</span><span><i class="legend purple"></i>推理</span></div></div>' +
    '<div class="workspace-column issue-column"><div class="column-head"><div><span class="column-kicker">02 / REVIEW</span><h2>问题详情</h2></div><span class="column-count">' + (selected ? String(activeIndex + 1).padStart(2, '0') : '—') + ' / ' + String(review.findings.length).padStart(2, '0') + '</span></div><div class="finding-nav-list">' + (issues || '<div class="filter-empty">当前筛选下没有问题。</div>') + '</div><div class="finding-detail-body">' + center + '</div><div class="finding-pagination"><button class="quiet-button small-quiet" data-action="previous-finding" ' + (activeIndex <= 0 ? 'disabled' : '') + '>← 上一个</button><span>' + (activeIndex < 0 ? '0' : activeIndex + 1) + ' / ' + review.findings.length + '</span><button class="quiet-button small-quiet" data-action="next-finding" ' + (activeIndex < 0 || activeIndex >= review.findings.length - 1 ? 'disabled' : '') + '>下一个 →</button></div></div>' +
    '<div class="workspace-column evidence-column"><div class="column-head"><div><span class="column-kicker">03 / EVIDENCE</span><h2>证据来源</h2></div><span class="column-count">' + (selected?.evidence.length || 0) + ' 条</span></div><div class="evidence-body">' + evidenceHtml + '</div></div></section>';
}

export function renderHistory(history) {
  const rows = history.map((item) => '<tr><td><b>' + esc(item.reportName || '未命名报告') + '</b><small class="table-sub">' + esc(item.reportId || '') + '</small></td><td>' + esc(item.reportType || '金融报告') + '</td><td>' + formatTime(item.savedAt) + '</td><td>' + statusPill(item.status) + '</td><td>' + (item.findingCount ?? '—') + '</td><td><button class="text-action" data-open-review="' + esc(item.reviewId) + '">打开 ' + icon('chevron', 13) + '</button></td></tr>').join('');
  return '<div class="page-heading"><div><div class="eyebrow"><span class="eyebrow-line"></span> LOCAL HISTORY</div><h1>历史记录</h1><p>本页面只索引当前浏览器创建的任务；服务端没有列表 / 搜索接口。</p></div><a class="primary-button" href="/review/new" data-nav>' + icon('plus', 16) + '新建任务</a></div><section class="panel history-panel"><div class="panel-heading"><div><h2>本机任务索引</h2><p>浏览器本地元数据，不含报告正文。</p></div><span class="fixed-tag">' + history.length + ' 条</span></div><div class="table-scroll"><table class="data-table"><thead><tr><th>报告名称</th><th>类型</th><th>创建时间</th><th>状态</th><th>问题数</th><th></th></tr></thead><tbody>' + (rows || '<tr><td colspan="6"><div class="empty-state"><span class="empty-icon">' + icon('clock', 22) + '</span><b>暂无历史任务</b><small>复核完成后，任务索引会显示在这里。</small></div></td></tr>') + '</tbody></table></div></section>';
}

export function renderModulePlaceholder(title, description) {
  return '<div class="page-heading"><div><div class="eyebrow"><span class="eyebrow-line"></span> PRODUCT MODULE</div><h1>' + esc(title) + '</h1><p>' + esc(description) + '</p></div></div><div class="panel module-placeholder"><span class="module-placeholder-icon">' + icon('database', 24) + '</span><h2>当前项目尚无此模块 API</h2><p>我没有添加模拟数据或虚假的配置入口。现有后端已提供的能力可以在复核工作台中查看。</p><a class="primary-button" href="/dashboard" data-nav>返回工作台 ' + icon('arrow', 15) + '</a></div>';
}

export function renderSettings(apiBase, health) {
  return '<div class="page-heading"><div><div class="eyebrow"><span class="eyebrow-line"></span> CONNECTION</div><h1>系统设置</h1><p>配置浏览器连接的复核服务地址。</p></div></div><section class="panel connection-panel"><div class="panel-heading"><div><h2>API 连接</h2><p>与现有 FastAPI endpoint 对接。</p></div><span class="status-pill ' + (health === true ? 'green' : health === false ? 'red' : 'gray') + '"><i></i>' + (health === true ? '已连接' : health === false ? '连接失败' : '检查中') + '</span></div><div class="form-field"><label for="api-base">API 基础地址</label><input id="api-base" class="text-input" type="url" placeholder="留空使用当前网页同源 API" value="' + esc(apiBase) + '" /><small class="field-hint">例如：http://127.0.0.1:8000 · 地址仅保存在此浏览器。</small></div><div class="form-actions left-actions"><button class="outline-button" data-action="save-api-base">保存并测试连接</button><button class="quiet-button" data-action="reset-api-base">恢复同源</button></div><div class="api-endpoints"><b>前端使用的接口</b><code>GET /health/live</code><code>POST /v1/reviews</code><code>GET /v1/reviews/{review_id}</code><code>GET /v1/human-tasks</code><code>POST /v1/human-tasks/{review_id}/decision</code></div></section>';
}

export function renderExport(review) {
  const rows = review.findings.map((item, index) => '<tr><td>' + (index + 1) + '</td><td>' + esc(item.id) + '</td><td>' + esc(item.text) + '</td><td>' + esc(item.typeLabel) + '</td><td>' + esc(item.riskLabel) + '</td><td>' + esc(item.statusLabel) + '</td><td>' + item.evidence.length + '</td></tr>').join('');
  return '<div class="page-heading"><div><div class="eyebrow"><span class="eyebrow-line"></span> EXPORT REVIEW</div><h1>复核结果导出</h1><p>从当前 API 响应生成本地文件，不调用后端导出服务。</p></div><a class="quiet-button" href="/review/' + encodeURIComponent(review.reviewId) + '/overview" data-nav>' + icon('chevron', 14) + '返回总览</a></div><section class="panel export-panel"><div class="panel-heading"><div><h2>' + esc(review.reportId || '复核结果') + '</h2><p>Review ID · ' + esc(review.reviewId) + '</p></div><span class="fixed-tag">' + review.findings.length + ' 个 Claim</span></div><div class="export-stats"><span>SUPPORTED <b>' + (review.summaryCounts.SUPPORTED || 0) + '</b></span><span>CONTRADICTED <b>' + (review.summaryCounts.CONTRADICTED || 0) + '</b></span><span>INSUFFICIENT <b>' + (review.summaryCounts.INSUFFICIENT_EVIDENCE || 0) + '</b></span></div><div class="table-scroll"><table class="data-table"><thead><tr><th>#</th><th>Claim ID</th><th>报告结论</th><th>问题类型</th><th>风险</th><th>核验状态</th><th>证据数</th></tr></thead><tbody>' + (rows || '<tr><td colspan="7">没有 Finding 条目。</td></tr>') + '</tbody></table></div><div class="form-actions"><button class="outline-button" data-action="export-csv">' + icon('download', 15) + '下载问题清单 CSV</button><button class="primary-button" data-action="export-json">' + icon('download', 15) + '下载完整 API 响应 JSON</button></div><div class="export-boundary">当前没有 PDF / Excel 生成 API。JSON 导出包含当前 API 响应中的报告文本与证据，请妥善保管。</div></section>';
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
