"""Source registry, immutable KB versions, child retrieval and parent expansion."""
from __future__ import annotations
import hashlib
import json
import re
import threading
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree
from zipfile import ZipFile

from credit_review.knowledge_base.pipeline import KnowledgeBaseBuilder
from credit_review.retrieval.service import BM25Retriever, HybridSearchService, infer_metric_ids
from credit_review.infrastructure.embeddings import SentenceTransformerEmbedder, SentenceTransformerDenseRetriever
from credit_review.infrastructure.rerankers import SentenceTransformerCrossEncoder
from .storage import now, encode

MAX_BYTES = 50 * 1024 * 1024


def parse_file(path):
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError('加密 PDF 请先解密。')
        if len(reader.pages) > 1000:
            raise ValueError('PDF 超出 1000 页解析上限。')
        blocks = []
        for number, page in enumerate(reader.pages):
            text = (page.extract_text(extraction_mode='layout') or '') if '/Contents' in page else ''
            for part in re.split(r'\n\s*\n', text):
                if part.strip():
                    blocks.append({'type': 'table' if re.search(r'\S\s{3,}\S', part) and re.search(r'\d', part) else 'text', 'text': part.strip(), 'page_idx': number})
        if not blocks:
            raise ValueError('PDF 没有可提取文字，需要 OCR / MinerU 解析后导入；未生成虚构内容。')
        return blocks, 'pypdf-layout-v1'
    if suffix == '.html':
        from .web_sources import parse_html
        return parse_html(path.read_bytes())[0], 'web-html-v2'
    if suffix in {'.txt', '.md'}:
        text = path.read_text(encoding='utf-8-sig')
        blocks = [{'type': 'table' if p.strip().startswith('[TABLE]') or '|' in p else 'text', 'text': p.strip().removeprefix('[TABLE]').strip()} for p in re.split(r'\n\s*\n', text) if p.strip()]
        if not blocks:
            raise ValueError('文件没有正文。')
        return blocks, 'utf8-paragraph-v1'
    if suffix == '.json':
        return json.loads(path.read_text(encoding='utf-8-sig')), 'mineru-context-v3'
    if suffix == '.docx':
        with ZipFile(path) as archive:
            info = archive.getinfo('word/document.xml')
            if info.file_size > MAX_BYTES:
                raise ValueError('DOCX 解压后的正文过大。')
            xml = ElementTree.fromstring(archive.read(info))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        body = xml.find('w:body', ns)
        blocks = []
        for element in body:
            text = '\n'.join(''.join(p.itertext()) for p in element.findall('.//w:p', ns))
            if text.strip():
                blocks.append({'type': 'table' if element.tag.endswith('}tbl') else 'text', 'text': text})
        if not blocks:
            raise ValueError('DOCX 没有正文。')
        return blocks, 'docx-xml-v1'
    raise ValueError('支持 PDF / DOCX / TXT / Markdown / MinerU JSON。')


class Knowledge:
    def __init__(self, store, executor, backend='sentence_transformers', embedding_model='moka-ai/m3e-base', reranker_model='BAAI/bge-reranker-v2-m3'):
        self.store, self.executor, self.backend = store, executor, backend
        self.embedding_model, self.reranker_model = embedding_model, reranker_model
        self.embedder = self.reranker = None
        self.model_lock = threading.RLock()
        self.cache = {}

    def register(self, name, data, company='', period='', original_id=None, *, web_metadata=None):
        name = Path(name).name
        if not data or len(data) > MAX_BYTES:
            raise ValueError('单个文件大小须为 1 字节至 50 MB。')
        suffix = Path(name).suffix.lower()
        if suffix not in {'.pdf', '.txt', '.md', '.docx', '.json', '.html'}:
            raise ValueError('不支持的文件格式。')
        if original_id:
            original = self.store.get('document', original_id)
            if original['suffix'] != '.pdf':
                raise ValueError('MinerU 对应原件须为已登记的 PDF。')
        ident = 'D-' + uuid4().hex
        directory = self.store.root / 'documents' / ident
        directory.mkdir(parents=True)
        path = directory / ('original' + suffix)
        path.write_bytes(data)
        path.chmod(0o600)
        metadata = {'document_id': ident, 'name': name, 'suffix': suffix, 'size': len(data),
                    'sha256': hashlib.sha256(data).hexdigest(), 'company': company, 'period': period,
                    'created_at': now(), 'original_document_id': original_id, 'status': 'PARSING',
                    'source_type': 'pdf' if suffix=='.pdf' else 'web' if suffix=='.html' else 'file'}
        if original_id:
            metadata.update({k:original[k] for k in ('published_at','data_period_end','date_evidence') if original.get(k)})
        if web_metadata: metadata.update(web_metadata)
        self.store.save('document', ident, metadata)
        self.store.append(ident, 'source_registered', metadata)
        try:
            raw, parser = parse_file(path)
            snapshot = KnowledgeBaseBuilder(document_version=metadata['sha256'][:16], parser_version=parser).build(raw, document_id=ident, source_name=name)
            temporal_by_block = metadata.get('block_temporal', {})
            for parent in snapshot['parents']:
                segments = parent['source_locator'].get('block_id', '').split('+')
                scopes = [temporal_by_block[s] for s in segments if s in temporal_by_block]
                base = {k:metadata.get(k) for k in ('published_at','updated_at','fetched_at','effective_from','effective_to','superseded_by','date_evidence','data_period_start','data_period_end')}
                if scopes:
                    base.update(scopes[0])
                    if len({s.get('data_period') for s in scopes})>1:
                        base.update(data_period=None, ambiguous_period=True)
                elif metadata.get('period'):
                    base.update(data_period=metadata['period'], period_basis='user_asserted')
                parent['temporal'] = base
            by_parent = {p['parent_id']:p for p in snapshot['parents']}
            for child in snapshot['children']: child['temporal'] = by_parent[child['parent_id']]['temporal']
            (directory / 'parsed.json').write_text(encode(snapshot), encoding='utf-8')
            metadata.update({'parsed_sha256': hashlib.sha256((directory / 'parsed.json').read_bytes()).hexdigest(), 'parser_version': parser, 'status': 'READY', 'parent_count': len(snapshot['parents']), 'child_count': len(snapshot['children'])})
            self.store.append(ident, 'parse_and_chunk', {'manifest': snapshot['manifest'], 'parents': snapshot['parents'], 'children': snapshot['children']})
        except Exception as exc:
            metadata.update({'status': 'FAILED', 'error': str(exc)})
            self.store.append(ident, 'parse_failed', {'error': str(exc)})
        self.store.save('document', ident, metadata)
        return metadata

    def capture_url(self, url, company='', job=None, fetcher=None):
        from .web_sources import fetch_public, parse_html, canonical_url
        requested = canonical_url(url)
        result = (fetcher or fetch_public)(requested)
        raw = result['content']
        is_pdf = raw.startswith(b'%PDF') or 'pdf' in result['content_type']
        extra = {'requested_url':requested, 'final_url':result['final_url'], 'redirects':result['redirects'],
                 'fetched_at':now(), 'http_status':200, 'content_type':result['content_type'],
                 'last_modified_header':result.get('last_modified_header')}
        if is_pdf:
            title = Path(result['final_url'].split('?')[0]).name or 'web-source.pdf'
            if not title.endswith('.pdf'): title += '.pdf'
        else:
            _, parsed_meta = parse_html(raw)
            extra.update(parsed_meta)
            title = (parsed_meta['title'] or '网页来源')[:120]+'.html'
        if not company:
            from urllib.parse import urlsplit
            host=urlsplit(result['final_url']).hostname or ''
            if host.endswith('.microsoft.com') or host=='microsoft.com': company='Microsoft'
            if host.endswith('.apple.com') or host.endswith('.apple.com.cn') or host in {'apple.com','apple.com.cn'}: company='Apple'
        digest = hashlib.sha256(raw).hexdigest()
        # Deduplicate immutable captures, retain every access and redirect in audit.
        for old in self.store.list('document'):
            same_source = old.get('final_url')==result['final_url'] or is_pdf and old['suffix']=='.pdf'
            same_parser=is_pdf or old.get('parser_version')=='web-html-v2'
            if same_source and same_parser and old['sha256']==digest and old['status']=='READY':
                if job: self.store.append(job,'web_source_reused',{'document_id':old['document_id'],'access':extra})
                return old
        doc = self.register(title, raw, company=company, web_metadata=extra)
        if job: self.store.append(job,'web_source_captured',{'document_id':doc['document_id'],'metadata':extra,'sha256':digest})
        return doc

    def source_path(self, ident):
        doc = self.store.get('document', ident)
        path = self.store.root / 'documents' / ident / ('original' + doc['suffix'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc['sha256']:
            raise ValueError('来源原件哈希不一致，停止读取；请检查文件完整性。')
        return path, doc

    def parsed(self, ident):
        path = self.store.root / 'documents' / ident / 'parsed.json'
        doc = self.store.get('document', ident)
        if doc.get('parsed_sha256') and hashlib.sha256(path.read_bytes()).hexdigest() != doc['parsed_sha256']:
            raise ValueError('解析快照哈希不一致，停止读取。')
        return json.loads(path.read_text(encoding='utf-8'))

    def create(self, payload, *, synchronous=False):
        ids = list(dict.fromkeys(payload.get('document_ids') or []))
        if not ids:
            raise ValueError('请先上传并选择知识库来源文件。')
        for ident in ids:
            if self.store.get('document', ident)['status'] != 'READY':
                raise ValueError('来源文件尚未成功解析：' + ident)
        kb = str(payload.get('kb_id') or 'credit-kb')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', kb):
            raise ValueError('知识库标识只允许字母数字、连字符和下划线。')
        ident = 'B-' + uuid4().hex
        record = {'build_id': ident, 'kb_id': kb, 'name': payload.get('name') or '金融信贷资料库',
                  'version': ident, 'document_ids': ids, 'status': 'QUEUED', 'created_at': now(), 'stages': [], 'backend': self.backend}
        self.store.save('build', ident, record)
        self.store.append(ident, 'build_requested', record)
        if synchronous:
            self._build(ident)
            return self.store.get('build',ident)
        self.executor.submit(self._build, ident)
        return record

    def _stage(self, record, stage, detail):
        current = self.store.get('build', record['build_id'])
        if current['status'] == 'CANCELLED':
            raise InterruptedError('建库已取消')
        record['status'] = stage
        record['stages'].append({'stage': stage, 'at': now()})
        self.store.save('build', record['build_id'], record)
        self.store.append(record['build_id'], stage, detail)

    def _build(self, ident):
        record = self.store.get('build', ident)
        try:
            self._stage(record, 'ORGANIZING', {'document_ids': record['document_ids']})
            parents, children = [], []
            for doc_id in record['document_ids']:
                metadata = self.store.get('document', doc_id)
                parsed = self.parsed(doc_id)
                by_parent = {p['parent_id']: p for p in parsed['parents']}
                for parent in parsed['parents']:
                    parents.append({**parent, 'parent_id': doc_id + ':' + parent['parent_id']})
                for child in parsed['children']:
                    parent = by_parent[child['parent_id']]
                    if parent['parent_type'] == 'heading':
                        continue
                    locator = child['source_locator']
                    original_id = metadata.get('original_document_id') or doc_id
                    original_metadata = self.store.get('document', original_id)
                    source_url = '/v1/documents/' + original_id + '/original'
                    if metadata['suffix'] == '.json' and not metadata.get('original_document_id'):
                        source_url = '/v1/documents/' + doc_id + '/view#' + child['parent_id']
                    if metadata.get('source_type') == 'web':
                        source_url = '/v1/documents/' + doc_id + '/view#' + child['parent_id']
                    if locator.get('page'):
                        source_url += '#page=' + str(locator['page'])
                    children.append({'evidence_id': doc_id + ':' + child['child_id'], 'content': child['fact_text'],
                        'parent_content': parent['parent_text'], 'parent_id': doc_id + ':' + parent['parent_id'],
                        'document_id': doc_id, 'document_version': metadata['sha256'][:16],
                        'source': original_metadata['name'], 'parsed_source': metadata['name'], 'page': locator.get('page'), 'section': locator.get('section'),
                        'source_url': source_url, 'context_url': '/v1/documents/' + doc_id + '/view#' + child['parent_id'],
                        'content_hash': child['source_hash'], 'parent_hash': parent['source_hash'],
                        'original_sha256': original_metadata['sha256'], 'parsed_source_sha256': metadata['sha256'], 'evidence_type': 'table' if parent['parent_type'] == 'table' else 'text',
                        'company_id': metadata['company'] or None, 'period': metadata['period'] or None,
                        'metric_ids': child['metric_ids'], 'source_locator': locator})
                    children[-1].update(source_type=metadata.get('source_type','file'),
                        original_url=metadata.get('final_url'), temporal=child.get('temporal') or {},
                        snapshot_url='/v1/documents/'+doc_id+'/view#'+child['parent_id'])
            if not children:
                raise ValueError('没有可检索的事实块；请检查解析正文，纯标题资料不能发布知识库。')
            snapshot = {'parents': parents, 'children': children, 'documents': [self.store.get('document', i) for i in record['document_ids']],
                        'kb_id': record['kb_id'], 'version': ident, 'created_at': now(), 'backend': self.backend,
                        'embedding_model': self.embedding_model if self.backend == 'sentence_transformers' else None,
                        'reranker_model': self.reranker_model if self.backend == 'sentence_transformers' else None}
            directory = self.store.root / 'knowledge' / ident
            directory.mkdir(parents=True, exist_ok=False)
            (directory / 'snapshot.json').write_text(encode(snapshot), encoding='utf-8')
            self._stage(record, 'INDEXING', {'parent_count': len(parents), 'child_count': len(children), 'backend': self.backend})
            self._searcher(ident, snapshot)
            self._stage(record, 'VALIDATING', {'snapshot_sha256': hashlib.sha256(encode(snapshot).encode()).hexdigest(), 'child_count': len(children)})
            # Publish only complete, queryable versions. A failed build leaves the previous active version intact.
            record.update({'status': 'READY', 'snapshot_sha256': hashlib.sha256(encode(snapshot).encode()).hexdigest(), 'parent_count': len(parents), 'child_count': len(children), 'completed_at': now()})
            with self.store.lock:
                if self.store.get('build', ident)['status'] == 'CANCELLED':
                    raise InterruptedError('建库已取消')
                self.store.save('build', ident, record)
                self.store.save('kb', record['kb_id'], {**record, 'active_version': ident})
                self.store.append(ident, 'published', record)
        except Exception as exc:
            record.update({'status': 'CANCELLED' if isinstance(exc, InterruptedError) else 'FAILED', 'error': str(exc)})
            self.store.save('build', ident, record)
            self.store.append(ident, 'build_failed', {'error': str(exc), 'type': type(exc).__name__})

    def snapshot(self, version):
        build = self.store.get('build', version)
        if build['status'] != 'READY':
            raise ValueError('该知识库版本尚未发布。')
        path = self.store.root / 'knowledge' / version / 'snapshot.json'
        expected = build.get('snapshot_sha256')
        if not expected:
            expected = next((p['body'].get('snapshot_sha256') for p in self.store.papers(version) if p['stage'] == 'VALIDATING'), None)
        if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('知识库快照哈希不一致，停止复核。')
        return json.loads(path.read_text(encoding='utf-8'))

    def _searcher(self, version, snapshot=None):
        with self.model_lock:
            if version in self.cache:
                return self.cache[version]
            snapshot = snapshot or self.snapshot(version)
            children = snapshot['children']
            if self.backend == 'sentence_transformers':
                if self.embedder is None:
                    self.embedder = SentenceTransformerEmbedder(self.embedding_model, device='cpu', batch_size=8, local_files_only=True)
                    self.reranker = SentenceTransformerCrossEncoder(self.reranker_model, device='cpu', batch_size=4, max_length=512, local_files_only=True)
                dense = SentenceTransformerDenseRetriever(children, self.embedder, index_path=self.store.root / 'knowledge' / version / 'dense.json', persist_if_built=True)
                searcher = HybridSearchService(children, dense_retriever=dense, lexical_retriever=BM25Retriever(children), reranker=self.reranker, dense_top_k=20, bm25_top_k=30, candidate_top_k=30, rerank_top_n=8)
            elif self.backend == 'lexical':
                searcher = BM25Retriever(children)
            else:
                raise ValueError('工作台检索须为 sentence_transformers 或 lexical；不启用模拟向量。')
            self.cache[version] = searcher
            return searcher

    def retrieve(self, version, query, scope=None, job=None):
        query=dict(query)
        original_query=query.get('query_text','')
        # Search bilingual disclosures with auditable aliases, without changing
        # the claim, source content, target amount or final verification rules.
        aliases={'微软':'Microsoft','苹果':'Apple','营业收入':'revenue','营收':'revenue',
                 '营业利润':'operating income','净利润':'net income','网络安全':'cybersecurity cyberattacks',
                 '云':'cloud','风险':'risk','借款':'debt borrowings','逾期':'overdue','应收':'receivable',
                 '供应商':'supplier','汇率':'foreign currency','竞争':'competition'}
        if any(name in original_query for name in ('微软','苹果','Microsoft','Apple')):
            added=list(dict.fromkeys(en for zh,en in aliases.items() if zh in original_query))
            if added:
                query['query_text']=original_query+' '+' '.join(added)
                query.setdefault('lexical_query',query['query_text'])
                query.setdefault('dense_query',query['query_text'])
                if job:self.store.append(job,'bilingual_query_expansion',{'version':'financial-web-alias-v1','original_query':original_query,'expanded_query':query})
        with self.model_lock:
            searcher = self._searcher(version)
            actual_scope = dict(scope or {})
            if query.get('retrieval_profile') in {'financial_table', 'table_lookup', 'structured_data'}:
                actual_scope['evidence_types'] = ['table']
            if self.backend == 'lexical':
                hits = searcher.retrieve(query.get('query_text', ''), actual_scope, top_k=8)
            else:
                hits = searcher.retrieve({**query, 'dense_top_k': 20, 'lexical_top_k': 30, 'candidate_top_k': 30, 'rerank_top_n': 8}, actual_scope)
                if job:
                    self.store.append(job, 'hybrid_candidates_and_rerank', {**searcher.last_trace, 'version': version, 'note': '记录各路原始候选、融合排序及全部重排评分；重排分数不是校准后的置信度。'})
            if not hits and actual_scope.get('evidence_types') == ['table']:
                hits = searcher.retrieve(query.get('query_text', ''), scope, top_k=8) if self.backend == 'lexical' else searcher.retrieve(query, scope)
                if job:
                    self.store.append(job, 'table_text_fallback', {'query': query, 'hits': hits, 'reason': '表格没有命中，保留有界文本召回。'})
        if job:
            self.store.append(job, 'hybrid_child_retrieval', {'query': query, 'scope': scope, 'version': version, 'backend': self.backend, 'ranked_children': hits})
        parents = {}
        for hit in hits:
            metadata = self.store.get('document', hit['document_id'])
            original_id = metadata.get('original_document_id') or metadata['document_id']
            original = self.store.get('document', original_id)
            key = hit['parent_id']
            if key not in parents:
                expanded = dict(hit)
                expanded.update({'evidence_id': key, 'content': hit['parent_content'], 'child_content': hit['content'], 'matched_children': [hit['evidence_id']],
                                 'content_hash': hit['parent_hash']})
                if expanded.get('original_sha256') != original['sha256']:
                    if job:
                        self.store.append(job, 'source_locator_normalized', {'evidence_id': key, 'previous_original_sha256': expanded.get('original_sha256'), 'original_sha256': original['sha256'], 'reason': '旧快照的原件哈希字段保存了解析 JSON 哈希；原件根据登记关系校正，原快照保持不变。'})
                    expanded['original_sha256'] = original['sha256']
                    expanded['parsed_source_sha256'] = metadata['sha256']
                expanded['parsed_source'] = metadata['name']
                expanded['source'] = original['name']
                parents[key] = expanded
            else:
                parents[key]['matched_children'].append(hit['evidence_id'])
        return list(parents.values())


class BoundRetriever:
    def __init__(self, knowledge, version, scope, job):
        self.knowledge, self.version, self.scope, self.job = knowledge, version, scope, job

    def retrieve(self, query):
        if not self.version:return []
        scope=dict(self.scope)
        route=query.get('source_route')
        if route in {'html','pdf'}:
            docs=self.knowledge.snapshot(self.version)['documents']
            allowed=set(scope.get('allowed_document_ids') or [d['document_id'] for d in docs])
            subset=[d['document_id'] for d in docs if d['document_id'] in allowed and (d.get('source_type')=='web' if route=='html' else d['suffix']=='.pdf' or bool(d.get('original_document_id')))]
            if not subset:
                self.knowledge.store.append(self.job,'source_route_empty',{'route':route,'version':self.version})
                return []
            scope['allowed_document_ids']=subset
        hits = self.knowledge.retrieve(self.version, query, scope, self.job)
        required = set(query.get('citation_document_ids') or [])
        allowed = set(self.scope.get('allowed_document_ids') or [])
        if allowed: required &= allowed
        if required:
            scope = {**self.scope,'allowed_document_ids':sorted(required)}
            cited = self.knowledge.retrieve(self.version,{**query,'retrieval_profile':'hybrid'},scope,self.job)
            hits = list({e['evidence_id']:e for e in cited+hits}.values())[:12]
        return hits
