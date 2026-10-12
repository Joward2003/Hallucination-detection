import {workbenchApi as api} from './api.js';
import {esc, icon, evidenceText} from './ui.js';

export const data = {documents: [], builds: [], kbs: [], runtime: null, rules: null, search: null, audit: null};
const field = (label, id, value = '', type = 'text', placeholder = '') => `<div class="form-field"><label for="${id}">${label}</label><input class="text-input" id="${id}" type="${type}" value="${esc(value)}" placeholder="${placeholder}" /></div>`;
const tag = (status) => `<span class="status-pill ${status === 'READY' ? 'green' : ['FAILED','INTERRUPTED'].includes(status) ? 'red' : 'amber'}"><i></i>${esc(status)}</span>`;
export const exportLink = (reviewId, format, label) => `<a class="outline-button" href="${api.link('/v1/reviews/' + encodeURIComponent(reviewId) + '/export/' + format)}">${icon('download',15)}${label}</a>`;

export async function refresh() {
  const values = await Promise.all(['/v1/documents','/v1/knowledge-bases/builds','/v1/knowledge-bases','/v1/runtime','/v1/rules'].map(path => api.get(path)));
  [data.documents,data.builds,data.kbs,data.runtime,data.rules] = values;
}

export function kbOptions(selected='') {
  return '<option value="">选择已发布的知识库版本</option>' + data.builds.filter(b => b.status === 'READY').map(b => `<option value="${esc(b.version)}" ${b.version === selected ? 'selected' : ''}>${esc(b.name)} · ${esc(b.version.slice(0,12))} · ${b.document_ids.length} 个来源</option>`).join('');
}

export function reviewScope(draft) {
  return `<section class="panel workbench-scope"><h2>知识库与证据范围</h2><p>复核会固定使用选定版本；原件、父子块、索引和期间可追溯。</p><select class="text-input" id="review-kb-version">${kbOptions(draft.kbVersion)}</select><small class="field-hint">${draft.sourceFiles.length ? '随报告上传的来源会与选定资料合并建为新版本。' : '没有已发布版本时，请先到知识库上传资料并建库。'}</small><a class="text-action" href="/knowledge" data-nav>打开知识库 →</a></section>`;
}

export function renderKnowledge(activeEntity = '', expandedBuild = '') {
  const groups = new Map();
  for (const d of data.documents) {
    const key = (d.company || '未归类主体').trim() || '未归类主体';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(d);
  }
  const entities = [...groups.entries()].map(([name, docs]) => ({ name, docs, ready: docs.filter(d => d.status === 'READY').length }));
  const current = activeEntity && groups.has(activeEntity) ? activeEntity : (entities[0]?.name || '');
  const currentDocs = groups.get(current) || [];
  const currentIds = new Set(currentDocs.map(d => d.document_id));
  const currentBuilds = data.builds.filter(b => (b.document_ids || []).some(id => currentIds.has(id)) || (b.name || '').includes(current));
  const docs = currentDocs.map(d => `<tr><td><input type="checkbox" name="kb-doc" value="${esc(d.document_id)}" ${d.status !== 'READY' ? 'disabled' : ''} aria-label="选择 ${esc(d.name)}" /></td><td><b>${esc(d.name)}</b><small class="table-sub">${esc(d.period || '期间未填')} · ${(d.size/1024).toFixed(0)} KB</small><small class="table-sub mono">SHA256 ${esc(d.sha256.slice(0,20))}… · ${(d.parent_count || 0)} 父块 / ${(d.child_count || 0)} 子块</small></td><td>${tag(d.status)}<small class="table-sub">${d.error ? esc(d.error) : '解析完成'}</small></td><td><a target="_blank" rel="noopener" class="text-action" href="${api.link('/v1/documents/' + d.document_id + '/view')}">原文</a> <button class="text-action" data-audit-job="${esc(d.document_id)}">底稿</button></td></tr>`).join('');
  const builds = currentBuilds.map(b => `<details class="kb-build-merged" ${expandedBuild === b.build_id ? 'open' : ''}><summary><div><b>${esc(b.name)}</b> ${tag(b.status)}</div><small class="mono">${esc(b.version.slice(0,14))} · ${b.backend === 'sentence_transformers' ? '中文向量 + BM25 + 交叉编码' : 'BM25'} · ${esc((b.stages || []).map(s=>s.stage).join(' → '))} · ${b.document_ids.length} 个来源</small>${!['READY','FAILED','CANCELLED','INTERRUPTED'].includes(b.status) ? `<button class="quiet-button" data-cancel-build="${esc(b.build_id)}">取消</button>` : ''}</summary><div class="merged-docs">${(b.document_ids || []).map(id => { const d = data.documents.find(x => x.document_id === id); return `<span class="source-chip ${d ? '' : 'missing'}">${icon('file',13)}${esc(d ? d.name : id.slice(0,12))}</span>`; }).join('') || '<span class="no-data">无关联来源</span>'}${b.error ? '<p class="error-inline">'+esc(b.error)+'</p>' : ''}</div></details>`).join('');
  const hits = (data.search?.hits || []).map(e => `<article class="kb-hit"><div><b>${esc(e.source)}</b><span>${e.page ? '第 '+e.page+' 页' : '文本来源'} · 重排 ${e.rerank_score ?? '无'} · ${esc((e.route_hits||[]).map(r=>r.route).join(' + '))}</span></div><p>${esc(evidenceText(e.child_content))}</p><details><summary>展开父块原文</summary><p>${esc(evidenceText(e.content))}</p></details><a class="text-action" target="_blank" rel="noopener" href="${api.link(e.source_url || e.context_url)}">打开原件 ${icon('link',13)}</a><small>${esc(e.evidence_id)} · 内容哈希 ${esc(e.content_hash)}</small></article>`).join('');
  return `<div class="page-heading"><div><div class="eyebrow">KNOWLEDGE & PROVENANCE</div><h1>知识库建设</h1><p>登记原件 → 解析父子块 → 混合索引 → 验证发布。失败不覆盖已有版本。</p></div><button class="outline-button" data-wb-action="refresh">刷新</button></div>
  <section class="panel kb-upload"><div class="panel-heading"><div><h2>登记来源文件</h2><p>支持 PDF / DOCX / TXT / Markdown / MinerU JSON。扫描件须先做 OCR，系统会明确标记解析失败。</p></div></div><div class="form-grid">${field('企业 / 主体','kb-company','','text','例如：国华网安')}${field('资料期间','kb-period','','text','例如：2024')}<div class="form-field"><label>MinerU 对应 PDF 原件（导入 JSON 时可选）</label><select id="kb-original" class="text-input"><option value="">不关联 PDF</option>${data.documents.filter(d=>d.suffix==='.pdf').map(d=>`<option value="${esc(d.document_id)}">${esc(d.name)}</option>`).join('')}</select></div><div class="form-field"><label for="kb-files">选择来源文件（每个最大 50 MB）</label><input id="kb-files" type="file" accept=".pdf,.docx,.txt,.md,.json" multiple /></div></div><button class="primary-button" data-wb-action="upload">登记并解析</button><div id="kb-upload-status" role="status"></div></section>
  <section class="panel spacious"><div class="panel-heading"><div><h2>主体文件夹</h2><p>一个主体对应一个文件夹，点击进入该主体的登记表。</p></div><span class="fixed-tag">${entities.length} 个主体</span></div><div class="entity-grid">${entities.map(e => `<button class="entity-card ${e.name === current ? 'active' : ''}" data-entity="${esc(e.name)}"><span class="entity-icon">📁</span><b>${esc(e.name)}</b><small>${e.docs.length} 份来源 · ${e.ready} 份可用</small><span class="text-action">进入文件夹 →</span></button>`).join('') || '<p class="no-data">暂无主体。</p>'}</div></section>
  <section class="panel spacious folder-merged"><div class="panel-heading"><div><h2>📁 ${esc(current || '—')} · 登记与建库</h2><p>来源登记与建库版本已合并：勾选来源后直接建库，版本卡片可展开看包含哪些来源。建库不设工作底稿按钮。</p></div><span class="fixed-tag">${currentDocs.length} 份来源 · ${currentBuilds.filter(b=>b.status==='READY').length} 个版本</span></div><div class="table-scroll roomy"><table class="data-table roomy"><thead><tr><th></th><th>来源 / 版本指纹</th><th>解析状态</th><th>追溯</th></tr></thead><tbody>${docs || '<tr><td colspan="4">该文件夹暂无来源文件。</td></tr>'}</tbody></table></div><div class="merged-builds"><h3>该主体的建库版本</h3>${builds || '<p class="no-data">暂无建库版本，勾选上方来源后创建。</p>'}</div><div class="form-grid kb-build-form padded-form">${field('知识库标识','kb-id','credit-kb')}${field('资料库名称','kb-name','金融信贷资料库')}</div><div class="form-actions padded-actions"><button class="primary-button" data-wb-action="build">为所选资料创建新版本</button></div></section>
  <section class="panel"><div class="panel-heading"><div><h2>检索验证</h2><p>子块召回、重排序后回补父块上下文，并保留来源与页码。</p></div></div><div class="kb-search-row"><select class="text-input" id="search-version">${kbOptions(data.search?.kb_version)}</select><input id="kb-query" class="text-input" placeholder="例如：2024 年营业收入与现金流" value="${esc(data.search?.query_text || '')}" /><button class="primary-button" data-wb-action="search">检索</button></div>${data.search ? `<p class="field-hint">召回 ${data.search.hits.length} 个父块 <button class="text-action" data-audit-job="${esc(data.search.audit_job)}">查看本次检索底稿</button></p>` : ''}${hits}</section>`;
}

export function renderRuntime() {
  const info = data.runtime;
  if (!info) return '<section class="panel"><p>正在读取模型配置。</p></section>';
  const provider = info.provider;
  return `<div class="page-heading"><div><div class="eyebrow">MODEL & CONNECTION</div><h1>模型与中转站</h1><p>设置真实 API 地址与协议；Key 只存服务端本机配置，读取接口不返回 Key。</p></div><span class="status-pill ${provider.key_configured ? 'green' : 'amber'}">${provider.key_configured ? '已配置 Key' : '未配置 Key'}</span></div><section class="panel spacious"><div class="panel-heading padded-head"><h2>当前运行配置</h2><span class="fixed-tag">${esc(info.application_version)}</span></div><div class="form-grid padded-form">${field('API 地址','provider-base',provider.base_url,'url')}${field('模型标识','provider-model',provider.model)}<div class="form-field"><label for="provider-wire">API 协议</label><select class="text-input" id="provider-wire"><option value="responses" ${provider.wire_api==='responses'?'selected':''}>Responses</option><option value="chat_completions" ${provider.wire_api==='chat_completions'?'selected':''}>Chat Completions</option></select></div>${field('新 Key（留空保留当前 Key）','provider-key','','password','只写入本机 .env')}<div class="form-field"><label for="provider-stream">Responses 流式传输</label><select class="text-input" id="provider-stream"><option value="true" ${provider.stream?'selected':''}>启用</option><option value="false" ${!provider.stream?'selected':''}>关闭</option></select></div><div class="form-field"><label>额外请求头名称</label><small>${esc(provider.extra_header_names.join('、') || '无')}</small></div></div><div class="form-actions"><button class="outline-button" data-wb-action="save-provider">保存配置</button><button class="primary-button" data-wb-action="check-provider">测试真实 API 连通性</button></div><div id="provider-result" role="status"></div><div class="workbench-config-note"><p>检索：真实中文向量 + BM25 + 交叉编码重排序</p><div class="form-grid"><div class="form-field"><label for="retrieval-embedding">向量模型（可选）</label><select class="text-input" id="retrieval-embedding"><option ${info.embedding_model === 'moka-ai/m3e-base' ? 'selected' : ''}>moka-ai/m3e-base</option><option value="lexical-only">仅 BM25（关闭向量）</option></select></div><div class="form-field"><label for="retrieval-reranker">重排序模型（可选）</label><select class="text-input" id="retrieval-reranker"><option ${info.reranker_model === 'BAAI/bge-reranker-v2-m3' ? 'selected' : ''}>BAAI/bge-reranker-v2-m3</option><option value="none">关闭重排序</option></select></div></div></div>${info.provider_validation_error ? `<p class="error-inline">${esc(info.provider_validation_error)}</p>` : ''}</div></section>`;
}

export function renderRules() {
  const rules=data.rules;
  return `<div class="page-heading"><div><div class="eyebrow">POLICIES & CONTROL</div><h1>业务规则与人工介入</h1><p>当前执行版本：${esc(rules?.version)} · 开关实时生效（保存在本机浏览器），服务端版本不变。</p></div></div><section class="panel spacious"><div class="panel-heading"><h2>风险分层</h2><span class="fixed-tag">可交互</span></div><p>${esc(rules?.human_policy.join(' / '))}会升级人工，其余复核点自动继续。</p><p>${esc(rules?.numeric_policy)}</p><div class="table-scroll roomy"><table class="data-table roomy"><thead><tr><th>启用</th><th>规则</th><th>版本</th><th>风险</th><th>说明</th></tr></thead><tbody>${(rules?.rules||[]).map(r=>`<tr><td><label class="switch"><input type="checkbox" data-rule-toggle="${esc(r.rule_id)}" checked /><span></span></label></td><td>${esc(r.rule_id)}</td><td>${esc(r.version)}</td><td>${esc(r.severity)}</td><td>${esc(r.explanation)}</td></tr>`).join('')}</tbody></table></div><p class="field-hint">关闭后该规则在本机演示中不再触发升级人工；正式发布仍需修改服务端版本化规则。</p></section>`;
}

export function renderDataManagement(activeCompany = '') {
  const groups = new Map();
  for (const d of data.documents) {
    const key = (d.company || '未归类主体').trim() || '未归类主体';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(d);
  }
  const totalDocs = data.documents.length, readyDocs = data.documents.filter(d => d.status === 'READY').length;
  const totalParents = data.documents.reduce((s,d) => s + (d.parent_count || 0), 0), totalChildren = data.documents.reduce((s,d) => s + (d.child_count || 0), 0);
  const totalVersions = data.builds.filter(b => b.status === 'READY').length;
  const totalBytes = data.documents.reduce((s,d) => s + (d.size || 0), 0);
  const current = activeCompany && groups.has(activeCompany) ? activeCompany : '';
  const detail = current ? (groups.get(current) || []) : [];
  return `<div class="page-heading"><div><div class="eyebrow">DATA & STORAGE</div><h1>数据管理</h1><p>总—分视图：先看总体，再点公司看明细。与知识库建库操作分开。</p></div><button class="outline-button" data-wb-action="refresh">刷新</button></div>
  <section class="metric-grid"><article class="metric-card"><div class="metric-top"><span>来源总数</span></div><strong class="metric-value">${totalDocs}</strong><small>${readyDocs} 可用 · ${(totalBytes/1024/1024).toFixed(1)} MB</small></article><article class="metric-card"><div class="metric-top"><span>完整父块资料库</span></div><strong class="metric-value">${totalParents}</strong><small>父块总数，可溯源章节页码</small></article><article class="metric-card"><div class="metric-top"><span>父子分块资料库</span></div><strong class="metric-value">${totalChildren}</strong><small>子块总数，用于混合检索</small></article><article class="metric-card"><div class="metric-top"><span>已发布版本</span></div><strong class="metric-value">${totalVersions}</strong><small>不可变快照 · ${groups.size} 个主体</small></article></section>
  <section class="panel spacious"><div class="panel-heading"><div><h2>按公司查看</h2><p>点击公司卡片展开该公司的父块、哈希页码与原件。</p></div></div><div class="entity-grid">${[...groups.entries()].map(([name, docs]) => `<button class="entity-card ${name === current ? 'active' : ''}" data-company="${esc(name)}"><span class="entity-icon">🏢</span><b>${esc(name)}</b><small>${docs.length} 来源 · ${docs.reduce((s,d)=>s+(d.parent_count||0),0)} 父块 · ${docs.reduce((s,d)=>s+(d.child_count||0),0)} 子块</small><span class="text-action">${name === current ? '收起 ▲' : '查看明细 →'}</span></button>`).join('') || '<p class="no-data">暂无数据。</p>'}</div>
  ${current ? `<div class="company-detail"><h3>${esc(current)} · ${detail.length} 个来源</h3>${detail.map(d => `<details class="kb-build-merged" open><summary><div><b>${esc(d.name)}</b> ${tag(d.status)}</div><small class="mono">SHA256 ${esc((d.sha256||'').slice(0,24))}… · ${esc(d.period||'期间未填')} · ${(d.parent_count||0)} 父块 / ${(d.child_count||0)} 子块 · ${(d.size/1024).toFixed(0)} KB</small></summary><div class="merged-docs"><span>页码：${esc(d.page_count ?? d.pages ?? '见原件解析')}</span><a target="_blank" rel="noopener" class="outline-button small" href="${api.link('/v1/documents/' + d.document_id + '/view')}">打开真实原件</a><button class="outline-button small" data-audit-job="${esc(d.document_id)}">解析底稿</button></div></details>`).join('')}</div>` : '<p class="field-hint padded-hint">点击上方公司卡片查看该公司的完整父块、哈希、页码与原件。</p>'}</div></section>`;
}

export function renderAudit(job) {
  const record = data.audit?.job === job ? data.audit : null;
  const papers = record?.papers || [];
  const compact = (paper) => paper.body.type === 'node_finish' ? {summary: paper.body.summary, output: paper.body.output} : paper.body;
  return `<div class="page-heading"><div><div class="eyebrow">WORKING PAPERS</div><h1>流程底稿与审计</h1><p>${esc(job)}</p></div><a class="outline-button" href="${api.link('/v1/audit/'+encodeURIComponent(job)+'/download')}">下载完整底稿 ZIP</a></div><section class="panel"><div class="panel-heading"><div><h2>${record ? papers.length+' 份追加式工作底稿' : '正在读取工作底稿'}</h2><p>每个图节点保存输入、输出、时间、路由与错误；模型记录包含请求和结构化响应。</p></div>${record ? `<span class="status-pill ${record.integrity.valid ? 'green' : 'red'}">哈希链${record.integrity.valid ? '校验通过' : '异常'}</span>` : ''}</div><p class="field-hint">本地哈希链用于完整性检查，不等同于外部签名或可信时间戳；不记录模型内部思维链。</p><div class="paper-list">${papers.map(p=>`<details class="paper"><summary><span class="paper-index">${String(p.seq).padStart(3,'0')}</span><b>${esc(p.stage)}</b><span>${esc(p.body.type || '')}</span><time>${new Date(p.created_at).toLocaleTimeString()}</time></summary><p class="field-hint">执行人：${esc(p.actor)} · SHA256 ${esc(p.hash)}</p><pre>${esc(JSON.stringify(compact(p),null,2))}</pre><details><summary>完整输入 / 输出</summary><pre>${esc(JSON.stringify(p.body,null,2))}</pre></details></details>`).join('')}</div></section>`;
}

export function jobStatus(review) {
  const record = review.raw;
  const status = record.status;
  if (['RUNNING','QUEUED'].includes(status)) return `<section class="panel live-job"><span class="mini-spinner"></span><div><b>正在执行：${esc(record.last_node || '任务排队')}</b><p>已完成 ${review.findings.length} / ${record.state.flat_children?.length ?? '待拆解'} 个复核点。每一步结果已保存，页面会自动更新。</p></div><button class="quiet-button" data-cancel-review="${esc(review.reviewId)}">取消任务</button><button class="outline-button small" data-audit-job="${esc(review.reviewId)}">实时底稿</button></section>`;
  if (['FAILED','INTERRUPTED','CANCELLED'].includes(status)) return `<section class="panel live-job error-inline"><div><b>${esc(status)}</b><p>${esc(record.error || '任务已取消；底稿仍保留。')}</p></div>${status !== 'CANCELLED' ? `<button class="outline-button" data-continue-review="${esc(review.reviewId)}">从已保存复核点继续</button>` : ''}<button class="outline-button" data-audit-job="${esc(review.reviewId)}">检查底稿</button></section>`;
  return '';
}
