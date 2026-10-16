"""Downloadable review reports and self-contained, auditable working-paper bundles."""
from __future__ import annotations
import csv
import hashlib
import html
import io
import json
import re
from zipfile import ZipFile, ZIP_DEFLATED
from .storage import encode
from .reporting import problem_explanations

LABELS = {'SUPPORTED': '证据支持', 'CONTRADICTED': '证据冲突', 'INSUFFICIENT_EVIDENCE': '证据不足'}
ISSUES = {'insufficient_evidence': '证据不足', 'citation_mismatch': '引用错配', 'overstatement': '表述过强', 'reasoning_gap': '推理跳跃', 'risk_omission': '风险遗漏', 'fact_mismatch': '事实不一致'}


def results(record):
    state = record['state']
    items = [{**item,'pending':bool(item.get('pending_review'))} for item in state.get('completed_results', [])]
    if (state.get('human_task') or {}).get('status') == 'PENDING':
        items.append({**(state.get('verification_result') or {}), 'fact_id': state['current_fact']['fact_id'],
                      'fact': state['current_fact']['fact'], 'parent_text': state['current_parent']['parent_text'],
                      'evidence': state.get('current_evidence', []), 'queries': state.get('current_queries', []),
                      'numeric_checks': state.get('numeric_checks', []), 'risk_decision': state.get('risk_decision'), 'pending': True})
    return items


def esc(value):
    return html.escape(str(value or ''))


def evidence_text(value):
    text = str(value or '')
    if re.search(r'<(?:table|tr|td|th)\b', text, re.I):
        text = re.sub(r'</tr>', '\n', text, flags=re.I)
        text = re.sub(r'</(?:td|th)>', ' | ', text, flags=re.I)
        text = re.sub(r'<[^>]+>', '', text)
        text = html.unescape(text)
    return text.strip()


def report_evidence(item):
    selected = set(item.get('evidence_ids', [])) | set(item.get('counter_evidence_ids', [])) | set((item.get('human_decision') or {}).get('selected_evidence_ids', []))
    selected.update(ident for row in problem_explanations(item) for ident in row['evidence_ids'])
    candidates = item.get('evidence', [])
    return [e for e in candidates if e['evidence_id'] in selected] if selected else candidates[:3]


def html_report(record, base='http://127.0.0.1:8000', offline=False, documents=None):
    documents = documents or []
    document_map = {d['document_id']: d for d in documents}
    blocks = []
    for index, item in enumerate(results(record), 1):
        evidence = []
        for source in report_evidence(item):
            url = source.get('source_url') or source.get('context_url') or ''
            if offline:
                doc = document_map.get(source.get('document_id'), {})
                original_id = doc.get('original_document_id') or source.get('document_id')
                original = document_map.get(original_id, doc)
                url = ('snapshots/' + str(original_id) + '.html#' + str(source['evidence_id']).split(':')[-1] if original.get('source_type')=='web' else
                       'sources/' + str(original_id) + original.get('suffix', '.txt') + ('#page=' + str(source['page']) if source.get('page') else ''))
            elif url.startswith('/'):
                url = base.rstrip('/') + url
            evidence.append('<details><summary>' + esc(source['source']) + ' · ' + esc(source.get('page') or '无物理页码') + '</summary><p class="pre">' + esc(evidence_text(source['content'])) + '</p><a href="' + esc(url) + '">打开原始文件</a><small>证据 ' + esc(source['evidence_id']) + ' · SHA256 ' + esc(source.get('content_hash')) + '</small></details>')
        explanations=problem_explanations(item)
        explanation_html=('<h3>'+('自动复核发现的问题（人工决定见下方）' if item.get('human_decision') else '发现的问题与复核说明')+'</h3><ul>'+''.join('<li>'+('待确认：' if r['needs_confirmation'] else '')+esc(r['description'])+('<br>后续核验：'+esc(r['follow_up']) if r['follow_up'] else '')+'</li>' for r in explanations)+'</ul>') if explanations else ''
        numeric = '<pre>' + esc(json.dumps(item.get('numeric_checks', []), ensure_ascii=False, indent=2)) + '</pre>' if item.get('numeric_checks') else ''
        if item.get('temporal_checks') or item.get('citation_checks'):
            numeric += '<details><summary>时间与引用校验底稿</summary><pre>'+esc(json.dumps({'temporal':item.get('temporal_checks',[]),'citations':item.get('citation_checks',[])},ensure_ascii=False,indent=2))+'</pre></details>'
        blocks.append('<article><h2>' + str(index) + '. ' + esc(item.get('fact')) + '</h2><b class="verdict">' + esc(LABELS.get(item.get('status'), '待判定')) + (' · 待人工确认' if item.get('pending') else '') + '</b><p>' + esc(item.get('reason')) + '</p>' + explanation_html + '<details><summary>辅助分类</summary><p>' + esc('、'.join(ISSUES.get(t, t) for t in item.get('issue_types', []))) + '</p></details><p>原始语境：' + esc(item.get('parent_text')) + '</p>' + ''.join(evidence) + numeric + ('<p>人工复核：' + esc(json.dumps(item['human_decision'], ensure_ascii=False)) + '</p>' if item.get('human_decision') else '') + '</article>')
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>金融信贷复核报告</title><style>body{font:15px/1.8 system-ui,sans-serif;max-width:980px;margin:48px auto;padding:0 24px;color:#203044}h1{color:#153d5b}h2{font-size:19px}article{border-top:1px solid #ccd4df;padding:24px 0}.verdict{background:#edf3f8;padding:6px 12px}small{display:block;overflow-wrap:anywhere;color:#697589}pre,.pre{white-space:pre-wrap;overflow-wrap:anywhere}details{border-left:3px solid #7295aa;padding:8px 16px;margin:12px 0}summary{cursor:pointer}.meta{background:#f0f4f7;padding:20px}@media print{details{display:block}details>*{display:block}}</style><h1>金融信贷分析报告复核报告</h1><div class="meta">' +
            '<b>' + esc(record.get('report_name') or record['report_id']) + '</b><br>任务：' + esc(record['review_id']) + '<br>状态：' + esc(record['status']) + '<br>知识库版本：' + esc(record['kb_version']) + '<br>规则版本：' + esc(record.get('rule_set_version')) + '<br>模型：' + esc(record.get('model_config', {}).get('model')) + '<br>已复核 / 总复核点：' + str(len(results(record))) + ' / ' + str(len(record['state'].get('flat_children', []))) + '</div><p>本报告记录结论、证据与程序校验结果。待人工、失败或中断任务导出为阶段报告；复核结果不自动修改原报告或作出授信决定。</p>' + ''.join(blocks) + '<h2>提交报告原文</h2><p class="pre">' + esc(record['state'].get('original_input')) + '</p></html>').encode('utf-8')


def pdf_report(record, base='http://127.0.0.1:8000'):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    pdfmetrics.registerFont(TTFont('WorkbenchCJK', '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'))
    styles = {
        'title': ParagraphStyle('title', fontName='WorkbenchCJK', fontSize=21, leading=30, textColor=colors.HexColor('#153d5b'), spaceAfter=20, wordWrap='CJK'),
        'heading': ParagraphStyle('heading', fontName='WorkbenchCJK', fontSize=13, leading=20, spaceBefore=16, spaceAfter=8, wordWrap='CJK'),
        'body': ParagraphStyle('body', fontName='WorkbenchCJK', fontSize=10, leading=17, spaceAfter=8, wordWrap='CJK'),
        'small': ParagraphStyle('small', fontName='WorkbenchCJK', fontSize=8, leading=12, spaceAfter=6, wordWrap='CJK', textColor=colors.HexColor('#62758a')),
    }
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=46, leftMargin=46, topMargin=44, bottomMargin=44, title='金融信贷分析报告复核报告', author='金融信贷分析报告智能复核工作台')
    flow = []
    def p(text, style='body'):
        flow.append(Paragraph(esc(text).replace('\n', '<br/>'), styles[style]))
    p('金融信贷分析报告复核报告', 'title')
    p(record.get('report_name') or record['report_id'], 'heading')
    p('任务：' + record['review_id'] + '\n状态：' + record['status'] + '\n知识库版本：' + str(record['kb_version'] or '未建立') + '\n规则版本：' + record.get('rule_set_version', '') + '\n模型：' + record.get('model_config', {}).get('model', '') + '\n信息截止日：' + str(record.get('temporal_policy',{}).get('as_of') or '未指定'), 'small')
    p('本报告保留原始结论与证据；待人工、失败或中断任务为阶段报告。自动复核不替代授信责任人的最终决定。')
    for index, item in enumerate(results(record), 1):
        p(str(index) + '. ' + item.get('fact', ''), 'heading')
        p('判定：' + LABELS.get(item.get('status'), '待判定') + (' · 待人工确认' if item.get('pending') else '') + '　置信度：' + str(item.get('confidence', '')))
        p(item.get('reason', ''))
        explanations=problem_explanations(item)
        if explanations:p('自动复核发现的问题（人工决定见下方）' if item.get('human_decision') else '发现的问题与复核说明', 'heading')
        for row in explanations:
            p(('待确认：' if row['needs_confirmation'] else '')+row['description'])
            if row['follow_up']:p('后续核验：'+row['follow_up'])
        p('辅助分类：' + '、'.join(ISSUES.get(t, t) for t in item.get('issue_types', [])), 'small')
        p('原始语境：' + item.get('parent_text', ''))
        for source in report_evidence(item):
            source_start = len(flow)
            p(source['source'] + (' · 第 ' + str(source['page']) + ' 页' if source.get('page') else ' · 无物理页码'), 'heading')
            quote = next((q.get('quote') for q in item.get('citation_quotes', []) if q.get('evidence_id') == source['evidence_id']), None)
            text = evidence_text(quote or source['content'])
            p(text[:1800])
            if len(text) > 1800: p('此处展示前 1800 字；完整父块见底稿 ZIP 与原文定位页。', 'small')
            url = source.get('source_url') or source.get('context_url')
            if url:
                if url.startswith('/'): url = base.rstrip('/') + url
                flow.append(Paragraph('<link href="' + esc(url) + '" color="#28658e">打开原始文件</link>', styles['small']))
            p('证据：' + source['evidence_id'] + '\n内容 SHA256：' + str(source.get('content_hash', '')), 'small')
            if len(text) < 800:
                flow[source_start:] = [KeepTogether(flow[source_start:])]
        for check in item.get('numeric_checks', []):
            p('程序计算：' + str(check.get('expression', check.get('kind', '未计算'))) + '\n报告值：' + str(check.get('expected', '')) + '；程序值：' + str(check.get('observed', '')) + '；通过：' + str(check.get('passed')) + '\n' + str(check.get('failure_reason', '')), 'small')
        used = set(item.get('evidence_ids',[]))
        for check in item.get('temporal_checks',[]):
            if check['evidence_id'] in used:
                p('时间校验：'+check['status']+'；截止日：'+str(check.get('as_of'))+'；数据期间：'+str(check.get('source_temporal',{}).get('data_period'))+'\n'+'；'.join(check['reasons']), 'small')
        for check in item.get('citation_checks',[]): p('引用校验：'+check['reason'],'small')
        if item.get('human_decision'):
            decision = item['human_decision']
            p('人工决定：' + str(decision.get('decision')) + '；复核人：' + str(decision.get('decided_by')) + '\n理由：' + str(decision.get('comment')), 'small')
            if decision.get('final_text'): p('人工修订结论：' + decision['final_text'])
    p('原始提交报告', 'heading')
    p(record['state'].get('original_input', ''))
    def footer(canvas, doc):
        canvas.setFont('WorkbenchCJK', 8)
        canvas.setFillColor(colors.HexColor('#62758a'))
        canvas.drawString(46, 24, '金融信贷分析报告智能复核工作台 · 可审计复核记录')
        canvas.drawRightString(A4[0] - 46, 24, str(doc.page))
    document.build(flow, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def bundle(store, knowledge, job, record=None):
    papers = store.papers(job)
    docs = []
    entries = {'audit.jsonl': '\n'.join(encode(p) for p in papers).encode(), 'integrity.json': encode(store.verify(job)).encode()}
    for paper in papers:
        entries[f'working-papers/{paper["seq"]:05d}-{paper["stage"]}.json'] = encode(paper).encode()
    for kind in ('review', 'build', 'document'):
        try:
            item = store.get(kind, job)
            entries[kind + '.json'] = encode(item).encode()
            if kind == 'review':
                record = item
                if item.get('kb_version'):
                    snapshot = knowledge.snapshot(item['kb_version'])
                    entries['knowledge/snapshot.json'] = encode(snapshot).encode()
                    docs = snapshot['documents']
                entries['report-input.txt'] = item['state']['original_input'].encode('utf-8')
                if item.get('report_document'):
                    docs = docs + [item['report_document']]
            elif kind == 'build' and item['status'] == 'READY':
                snapshot = knowledge.snapshot(job)
                entries['knowledge/snapshot.json'] = encode(snapshot).encode()
                docs = snapshot['documents']
            elif kind == 'document': docs = [item]
            else: docs = [store.get('document', i) for i in item.get('document_ids', [])]
            break
        except KeyError:
            continue
    else:
        if not papers:
            raise KeyError(job)
        for paper in papers:
            doc_id=paper['body'].get('document_id')
            if doc_id:
                try: docs.append(store.get('document',doc_id))
                except KeyError: pass
    if record:
        versions={v for v in [record.get('base_kb_version'),record.get('kb_version')] if v}
        for change in record.get('source_version_history',[]):versions.update(v for v in (change.get('previous'),change.get('version')) if v)
        for result in record.get('state',{}).get('completed_results',[]):versions.update(e['retrieved_kb_version'] for e in result.get('evidence',[]) if e.get('retrieved_kb_version'))
        for version in sorted(versions):
            pinned=knowledge.snapshot(version)
            entries['knowledge/versions/'+version+'.json']=encode(pinned).encode()
            entries['build-audits/'+version+'.jsonl']='\n'.join(encode(p) for p in store.papers(version)).encode()
            entries['build-audits/'+version+'-integrity.json']=encode(store.verify(version)).encode()
            docs+=pinned['documents']
    doc_map = {d['document_id']: d for d in docs}
    for doc in list(doc_map.values()):
        if doc.get('original_document_id'):
            original = store.get('document', doc['original_document_id'])
            doc_map[original['document_id']] = original
    for ident, metadata in doc_map.items():
        path, _ = knowledge.source_path(ident)
        entries['sources/' + ident + metadata['suffix']] = path.read_bytes()
        if metadata['status'] == 'READY':
            parsed=knowledge.parsed(ident)
            entries['knowledge/' + ident + '-parsed.json'] = encode(parsed).encode()
            entries['knowledge/'+ident+'-metadata.json']=encode(metadata).encode()
            if metadata.get('source_type')=='web':
                original_dir=path.parent/'original-view'
                if (original_dir/'manifest.json').exists():
                    from .original_web import ensure_original
                    page,view_manifest=ensure_original(knowledge,ident)
                    entries['original-views/'+ident+'/online-page.html.txt']=page.encode()
                    entries['original-views/'+ident+'/online-manifest.json']=encode(view_manifest).encode()
                    offline_manifest=json.loads(encode(view_manifest))
                    offline_manifest['online_html_sha256']=view_manifest['html_sha256']
                    prefix='/v1/documents/'+ident+'/web-assets/'
                    page=page.replace(prefix,'assets/')
                    offline_csp='<meta http-equiv="Content-Security-Policy" content="default-src &apos;none&apos;; style-src &apos;self&apos; &apos;unsafe-inline&apos;; img-src &apos;self&apos; data:; font-src &apos;self&apos; data:">'
                    page=page.replace('<head>','<head>'+offline_csp,1)
                    entries['original-views/'+ident+'/page.html']=page.encode()
                    offline_manifest['html_sha256']=hashlib.sha256(page.encode()).hexdigest()
                    offline_manifest['transform']='offline-relative-assets-v1'
                    for asset in view_manifest['assets'].values():
                        if asset.get('status')=='ready':
                            data=(original_dir/asset['name']).read_bytes()
                            if hashlib.sha256(data).hexdigest()!=asset['sha256']:raise ValueError('来源快照资源完整性不一致。')
                            if asset['mime']=='text/css':
                                entries['original-views/'+ident+'/online-assets/'+asset['name']]=data
                                data=data.decode(errors='replace').replace(prefix,'').encode()
                            for offline_asset in offline_manifest['assets'].values():
                                if offline_asset['name']==asset['name']:
                                    offline_asset.update(online_sha256=asset['sha256'],sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
                            entries['original-views/'+ident+'/assets/'+asset['name']]=data
                    entries['original-views/'+ident+'/manifest.json']=encode(offline_manifest).encode()
                from .source_views import snapshot_html
                entries['snapshots/'+ident+'.html']=snapshot_html(metadata,parsed).encode('utf-8')
    for ident in doc_map:
        entries['source-audits/'+ident+'.jsonl']='\n'.join(encode(p) for p in store.papers(ident)).encode()
        entries['source-audits/'+ident+'-integrity.json']=encode(store.verify(ident)).encode()
    if record:
        entries['review-report.html'] = html_report(record, offline=True, documents=list(doc_map.values()))
    entries['README.txt'] = ('工作底稿包：原件、解析快照、知识库版本、图节点输入输出、模型请求与结构化响应、检索评分、程序计算及人工决定。\n打开 review-report.html 查看复核报告；其证据链接指向 sources 原件。\nmanifest.json 保存每个文件的 SHA256。audit.jsonl 为本地追加式哈希链，不等同于外部签名或可信时间戳。\n模型内部思维链不在审计范围；保存的是可复核的输入、输出及判断依据。\n').encode()
    entries['manifest.json'] = encode({'job': job, 'audit': store.verify(job), 'files': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} for name, data in entries.items()}}).encode()
    buffer = io.BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        for name, data in entries.items(): archive.writestr(name, data)
    return buffer.getvalue()


def csv_report(record):
    buffer=io.StringIO(newline='')
    writer=csv.writer(buffer)
    writer.writerow(['复核点标识','原结论','判定','问题类型','判定依据','引用证据','人工修订','任务状态'])
    def cell(value):
        text=str(value or '')
        return "'"+text if text.lstrip().startswith(('=','+','-','@')) else text
    for item in results(record):
        writer.writerow([cell(value) for value in [item.get('fact_id'),item.get('fact'),LABELS.get(item.get('status')), '、'.join(ISSUES.get(t,t) for t in item.get('issue_types',[])),item.get('reason'),';'.join(e['evidence_id'] for e in report_evidence(item)),(item.get('human_decision') or {}).get('final_text'),record['status']]])
    return ('\ufeff'+buffer.getvalue()).encode('utf-8')
