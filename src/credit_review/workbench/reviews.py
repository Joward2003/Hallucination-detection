"""Durable background review jobs and human continuation over pinned sources."""
from __future__ import annotations
import hashlib
import re
import threading
from pathlib import Path
from uuid import uuid4
from credit_review.graph.builder import default_services, build_review_graph, resume_review
from credit_review.domain.errors import ConflictError
from credit_review.api.schemas import ReviewRequest
from .storage import now, encode
from .gateway import Gateway, load_settings
from .agents import Extractor, Planner, Grader, Verifier, NumericValidator, WorkbenchRiskPolicy, ask
from .knowledge import BoundRetriever
from .temporal import validated_policy, claim_citations
from .web_sources import report_urls


class RiskCoverageExtractor:
    def __init__(self, extractor, retriever, gateway, citation_map=None):
        self.extractor, self.retriever, self.gateway = extractor, retriever, gateway
        self.citation_map = citation_map or {}

    def extract(self, report):
        groups = self.extractor.extract(report)
        for group in groups:
            for child in group['children']:
                child['citation_urls'] = claim_citations(child,report)
                child['citation_document_ids'] = [self.citation_map[u] for u in child['citation_urls'] if self.citation_map.get(u)]
        evidence = self.retriever.retrieve({'query_text': '偿债 信贷风险 逾期 担保 诉讼 现金流 债务 集中度 或有负债', 'query_id': 'REPORT-RISK', 'retrieval_profile': 'hybrid'})
        self.gateway.record('report_risk_coverage_input', {'report': report, 'evidence': evidence})
        if not evidence:
            self.gateway.record('report_risk_coverage_skipped',{'reason':'当前没有外部风险证据；不能声称无遗漏。'})
            return groups
        try:
            data = ask(self.gateway, '检查整份报告是否遗漏已给出证据中的重要信贷风险，只评估当前召回范围。不能把没有检索到等同于没有风险。输出 {"omissions":[{"risk":"具体风险","evidence_id":"...","quote":"逐字证据","reason":"报告为什么未覆盖"}]}。已覆盖、无可靠证据或无法确定时返回空列表。', {'report': report, 'risk_evidence': evidence})
            if not isinstance(data.get('omissions'),list):raise ValueError('风险遗漏检查输出无效。')
        except InterruptedError:
            raise
        except Exception as exc:
            self.gateway.record('report_risk_coverage_failed',{'error':str(exc),'action':'继续逐点预检，风险覆盖检查列入人工待办。'})
            return groups+[self._unresolved(report)]
        known = {e['evidence_id']: e for e in evidence}
        omissions = data.get('omissions')
        if not isinstance(omissions, list):
            raise ValueError('风险遗漏检查输出无效。')
        self.gateway.record('report_risk_coverage_result', {'omissions': omissions, 'boundary': '仅覆盖本次知识库和召回证据；不能保证穷尽全部业务风险。'})
        rejected=False
        for index, omission in enumerate(omissions[:8], 1):
            if not isinstance(omission,dict):
                rejected=True
                self.gateway.record('risk_coverage_candidate_rejected',{'candidate':omission,'reason':'候选风险结构无效。'})
                continue
            item = known.get(omission.get('evidence_id'))
            if not item or not omission.get('quote') or omission['quote'] not in item['content']:
                rejected=True
                self.gateway.record('risk_coverage_candidate_rejected',{'candidate':omission,'reason':'风险遗漏引用未逐字匹配原材料，不作为标签依据。'})
                continue
            pid = f'RISK{index:02d}'
            groups.append({'parent': {'parent_id': pid, 'parent_text': report, 'source_start': 0, 'source_end': len(report)},
                           'children': [{'fact_id': pid + '-F01', 'parent_id': pid, 'fact': '报告可能遗漏的信贷风险：' + omission['risk'],
                                         'source_start': 0, 'source_end': 0, 'importance': 'high', 'review_kind': 'risk_omission',
                                         'risk_reference': omission}]})
        if rejected:groups.append(self._unresolved(report))
        return groups

    @staticmethod
    def _unresolved(report):
        return {'parent':{'parent_id':'RISK-COVERAGE','parent_text':report,'source_start':0,'source_end':len(report)},'children':[{'fact_id':'RISK-COVERAGE-F01','parent_id':'RISK-COVERAGE','fact':'整份报告的风险覆盖检查未完成，需要人工核对。','source_start':0,'source_end':0,'importance':'high','review_kind':'extraction_gap','gap_kind':'risk_coverage','extraction_status':'unresolved'}]}


class Reviews:
    def __init__(self, store, knowledge, executor, gateway_factory=None):
        self.store, self.knowledge, self.executor = store, knowledge, executor
        self.gateway_factory = gateway_factory or (lambda job: Gateway(store, job))
        self.lock = threading.RLock()
        # Never misrepresent interrupted work as completed after process restart.
        for record in store.list('review'):
            if record['status'] in {'QUEUED', 'RUNNING'}:
                record.update(status='INTERRUPTED', error='服务重启中断，可从已保存复核点重新继续。')
                store.save('review', record['review_id'], record)
                store.append(record['review_id'], 'process_interrupted', {'last_node': record.get('last_node')})

    def create(self, payload):
        request = ReviewRequest.from_dict(payload)
        workflow_version=payload.get('workflow_version',1)
        if type(workflow_version) is not int or workflow_version not in {1,2}:raise ValueError('workflow_version 仅支持1或2。')
        if not isinstance(payload.get('web_search_enabled',False),bool):raise ValueError('web_search_enabled 必须为布尔值。')
        rule_version='credit-review-workbench-v2' if workflow_version==2 else 'credit-review-workbench-v1'
        if len(request.report_text) > 100000:
            raise ValueError('报告正文超过 10 万字符，请分批提交。')
        version = payload.get('kb_version')
        kb_id = payload.get('kb_id')
        if not version:
            try: version = self.store.get('kb', kb_id or 'credit-kb')['active_version']
            except KeyError: version = None
        urls = report_urls(request.report_text) if payload.get('fetch_references',True) else []
        if not version and not urls and not payload.get('web_search_enabled'):
            raise ValueError('请选择资料版本，或提供可读取的引用网址。')
        snapshot = self.knowledge.snapshot(version) if version else {'documents':[], 'backend':self.knowledge.backend}
        settings = load_settings()
        settings.validate()
        fingerprint = hashlib.sha256(encode(payload).encode()).hexdigest()
        with self.lock:
            for old in self.store.list('review'):
                if old['tenant_id'] == request.tenant_id and old['idempotency_key'] == request.idempotency_key:
                    if old['request_hash'] != fingerprint:
                        raise ConflictError('同一幂等键对应不同请求。')
                    return old
            ident = 'R-' + uuid4().hex
            scope = dict(payload.get('source_scope') or {})
            allowed = payload.get('document_ids') or snapshot['documents']
            allowed = [d['document_id'] if isinstance(d, dict) else d for d in allowed]
            if not set(allowed) <= {d['document_id'] for d in snapshot['documents']}:
                raise ValueError('证据范围包含知识库版本之外的文档。')
            scope.update(allowed_document_ids=allowed, corpus_version=version, rule_set_version=rule_version)
            record = {'review_id': ident, 'report_id': request.report_id, 'report_name': payload.get('report_name') or request.report_id,
                      'tenant_id': request.tenant_id, 'project_id': request.project_id, 'requested_by': request.requested_by,
                      'idempotency_key': request.idempotency_key, 'request_hash': fingerprint, 'kb_version': version,
                      'source_scope': scope, 'companies': request.companies, 'report_version': request.report_version, 'report_type': payload.get('report_type', '金融信贷报告'),
                      'status': 'QUEUED', 'state': {'original_input': request.report_text}, 'created_at': now(),
                      'model_config': settings.public(), 'retrieval_config': {k: snapshot.get(k) for k in ('backend', 'embedding_model', 'reranker_model')},
                      'rule_set_version': rule_version}
            record.update(workflow_version=int(payload.get('workflow_version',1)),web_search_enabled=bool(payload.get('web_search_enabled',False)),web_search_budget=12,reference_urls=urls, citation_map={}, web_sources_prepared=not bool(urls),
                          base_kb_version=version, temporal_policy=validated_policy(payload.get('temporal_policy')))
            if payload.get('report_document_id'):
                report_doc = self.store.get('document', payload['report_document_id'])
                if report_doc['status'] != 'READY':
                    raise ValueError('报告原件尚未成功解析。')
                parsed_text = '\n\n'.join(p['parent_text'] for p in self.knowledge.parsed(report_doc['document_id'])['parents'])
                record['report_document'] = report_doc
                record['report_text_edited_after_parse'] = parsed_text != request.report_text
            self.store.save('review', ident, record)
            self.store.append(ident, 'review_requested', {**record, 'source_documents': snapshot['documents'], 'report_sha256': hashlib.sha256(request.report_text.encode()).hexdigest()})
            self.executor.submit(self._run, ident)
            return record

    def get(self, ident):
        return self.store.get('review', ident)

    def list(self):
        return [{k: v for k, v in r.items() if k not in {'state', 'companies', 'source_scope', 'idempotency_key'}} for r in self.store.list('review')]

    def human_tasks(self):
        tasks=[]
        for r in self.store.list('review'):
            if r['status']!='HUMAN_REVIEW_REQUIRED':continue
            if r.get('workflow_version',1)>=2:
                tasks.extend({**item['human_task'],'review_id':r['review_id'],'fact':item['fact']} for item in r['state'].get('completed_results',[]) if item.get('pending_review') and (item.get('human_task') or {}).get('status')=='PENDING')
            elif (r['state'].get('human_task') or {}).get('status')=='PENDING':tasks.append({**r['state']['human_task'],'review_id':r['review_id']})
        return tasks

    def _services(self, record):
        gateway = self.gateway_factory(record['review_id'])
        retriever = BoundRetriever(self.knowledge, record['kb_version'], record['source_scope'], record['review_id'])
        services = default_services(companies=record.get('companies'), retrieval_backend='deterministic')
        services.retriever = retriever
        services.extractor = RiskCoverageExtractor(Extractor(gateway), retriever, gateway, record.get('citation_map'))
        services.query_planner = Planner(gateway)
        services.grader = Grader(gateway)
        services.verifier = Verifier(gateway,record.get('temporal_policy'),record.get('citation_map'))
        services.numeric_validator = NumericValidator(services.verifier)
        services.critic_verifier = None
        services.risk_policy = WorkbenchRiskPolicy()
        if record.get('workflow_version',1)>=2:
            from .retrieval_agents import EvidenceQueryPlanner,SourceRouter
            from .labeling import LabelingAgents
            from .browser_search import BrowserRetriever
            retriever=BrowserRetriever(self.knowledge,record)
            services.retriever=retriever
            services.extractor=RiskCoverageExtractor(Extractor(gateway),retriever,gateway,record.get('citation_map'))
            services.query_planner=EvidenceQueryPlanner(gateway)
            services.retrieval_router=SourceRouter()
            services.labeler=LabelingAgents(gateway)
            services.defer_human_review=True
        services.max_retry = 1
        return services

    def _run(self, ident, entry='extract_parent_child'):
        record = self.get(ident)
        if record['status'] == 'CANCELLED': return
        record['status'] = 'RUNNING'
        current_model = load_settings().public()
        if record.get('model_config') != current_model:
            record.setdefault('model_history', []).append(record.get('model_config'))
            record['model_config'] = current_model
        self.store.save('review', ident, record)
        state = record['state']
        def trace(event):
            current = self.get(ident)
            if current['status'] == 'CANCELLED':
                raise InterruptedError('任务已取消')
            self.store.append(ident, event.get('node') or event.get('source') or 'graph', event)
            if event['type'] == 'node_start':
                current['last_node'] = event['node']
                self.store.save('review', ident, current)
            if event['type'] == 'node_error':
                current['failed_node'] = event['node']
                self.store.save('review', ident, current)
            if event['type'] == 'node_finish':
                current['state'] = {**event['input'], **event['output']}
                current['last_node'] = event['node']
                current['updated_at'] = now()
                self.store.save('review', ident, current)
        try:
            if not record.get('web_sources_prepared',True):
                record = self._capture_references(record)
                state = record['state']
            code_root = Path(__file__).resolve().parents[1]
            source_hashes = {str(p.relative_to(code_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code_root.rglob('*.py')}
            self.store.append(ident, 'engine_version', {'source_hashes': source_hashes, 'entry_node': entry, 'provider': load_settings().public()})
            services = self._services(record)
            graph = build_review_graph(services, trace=trace, entry_node=entry)
            result = graph.invoke(state, config={'recursion_limit': 2000})
            current = self.get(ident)
            current.update(state=result, status=result['workflow_status'], updated_at=now())
            if current['status'] == 'COMPLETED': current['completed_at'] = now()
            result['corpus_version'] = current['kb_version']
            result['rule_set_version'] = record['rule_set_version']
            self.store.save('review', ident, current)
            self.store.append(ident, 'review_checkpoint', {'status': current['status'], 'completed_claims': len(result.get('completed_results', [])), 'next_child_index': result.get('child_index')})
        except Exception as exc:
            current = self.get(ident)
            if current['status'] != 'CANCELLED':
                current.update(status='FAILED', error=str(exc), updated_at=now())
                self.store.save('review', ident, current)
            self.store.append(ident, 'review_failed', {'error': str(exc), 'error_type': type(exc).__name__})

    def _capture_references(self, record):
        ident = record['review_id']
        documents = list(record['source_scope'].get('allowed_document_ids',[]))
        citation_map = dict(record.get('citation_map',{}))
        for url in record.get('reference_urls',[]):
            if self.get(ident)['status']=='CANCELLED': raise InterruptedError('任务已取消')
            try:
                doc = self.knowledge.capture_url(url,job=ident) if not citation_map.get(url) else self.store.get('document',citation_map[url])
                if doc['status']!='READY': raise ValueError(doc.get('error','网页解析失败'))
                citation_map[url]=doc['document_id']
                documents.append(doc['document_id'])
            except Exception as exc:
                citation_map[url]=None
                self.store.append(ident,'web_reference_failed',{'url':url,'error':str(exc),'error_type':type(exc).__name__})
            with self.lock:
                if self.get(ident)['status']=='CANCELLED': raise InterruptedError('任务已取消')
                record['citation_map']=citation_map
                self.store.save('review',ident,record)
        documents=list(dict.fromkeys(documents))
        if not documents:
            if record.get('web_search_enabled'):
                record.update(web_sources_prepared=True,citation_map=citation_map)
                self.store.save('review',ident,record)
                return record
            raise ValueError('没有成功读取的引用或已发布资料；请补充可读取的来源。')
        build=self.knowledge.create({'document_ids':documents,'kb_id':'sources-'+ident[2:18],
                                     'name':record['report_name']+' · 引用快照'},synchronous=True)
        if build['status']!='READY': raise ValueError('引用资料建库失败：'+str(build.get('error')))
        record.update(kb_version=build['version'],web_sources_prepared=True)
        record['source_scope'].update(allowed_document_ids=documents,corpus_version=build['version'])
        snapshot=self.knowledge.snapshot(build['version'])
        record['retrieval_config']={k:snapshot.get(k) for k in ('backend','embedding_model','reranker_model')}
        with self.lock:
            if self.get(ident)['status']=='CANCELLED': raise InterruptedError('任务已取消')
            self.store.save('review',ident,record)
        self.store.append(ident,'task_sources_pinned',{'base_kb_version':record.get('base_kb_version'),
            'kb_version':build['version'],'citation_map':citation_map,'temporal_policy':record['temporal_policy']})
        return record

    def cancel(self, ident):
        with self.lock:
            record = self.get(ident)
            if record['status'] in {'COMPLETED', 'CANCELLED'}: raise ConflictError('此状态不能取消。')
            record['status'] = 'CANCELLED'
            self.store.save('review', ident, record)
            self.store.append(ident, 'cancelled', {}, record['requested_by'])
            return record

    def continue_review(self, ident):
        with self.lock:
            record = self.get(ident)
            if record['status'] not in {'FAILED', 'INTERRUPTED'}: raise ConflictError('只能重试失败或中断的任务。')
            state = record['state']
            entry = 'prepare_child' if state.get('flat_children') and state.get('child_index', 0) < len(state['flat_children']) else 'aggregate' if state.get('flat_children') else 'extract_parent_child'
            if record['status'] == 'FAILED' and record.get('failed_node') in {'resolve_company','route_retrieval','plan_query', 'retrieve', 'grade_evidence', 'rewrite_query', 'verify','numeric_check','rule_check','classify_issues','risk_gate'}:
                entry = record['failed_node']
            record.update(status='QUEUED', error=None)
            self.store.save('review', ident, record)
            self.store.append(ident, 'continue_requested', {'entry': entry, 'model_config': load_settings().public()}, record['requested_by'])
            self.executor.submit(self._run, ident, entry)
            return record

    def submit_human_decision(self, ident, decision):
        with self.lock:
            record = self.get(ident)
            if record['status'] != 'HUMAN_REVIEW_REQUIRED': raise ConflictError('任务不是待人工确认状态。')
            state = record['state']
            if record.get('workflow_version',1)>=2:return self._decide_queued(record,decision)
            ids = decision.get('selected_evidence_ids', [])
            known = {e['evidence_id'] for e in state.get('current_evidence', [])}
            if not set(ids) <= known: raise ValueError('人工判定引用未知证据。')
            if decision.get('decision') == 'SUPPORTED' and not ids: raise ValueError('判为支持时请至少选择一条证据。')
            if not decision.get('comment') or not decision.get('decided_by'): raise ValueError('人工复核须填写理由与复核人。')
            decision = {**decision, 'decided_at': now()}
            try:
                updated = resume_review(state, decision)
            except ValueError as exc:
                raise ConflictError(str(exc)) from exc
            # Human choices are retained, not replaced by the earlier model citations.
            final = updated['completed_results'][-1]
            final['evidence_ids'] = ids
            if decision.get('issue_types'): final['issue_types'] = decision['issue_types']
            record.update(state=updated, status=updated['workflow_status'], updated_at=now())
            self.store.append(ident, 'human_decision', {'input_task': state['human_task'], 'decision': decision, 'final_result': final}, decision['decided_by'])
            if record['status'] == 'CHILD_COMPLETED':
                record['status'] = 'QUEUED'
                self.store.save('review', ident, record)
                self.executor.submit(self._run, ident, 'prepare_child')
            else:
                record['completed_at'] = now()
                self.store.save('review', ident, record)
            return record

    def _decide_queued(self,record,decision):
        state=record['state'];fact_id=decision.get('fact_id')
        item=next((i for i in state.get('completed_results',[]) if i['fact_id']==fact_id),None)
        if not item:raise ValueError('复核点不存在，请选择待办项。')
        task=item.get('human_task') or {}
        if task.get('status')!='PENDING' or decision.get('task_version')!=task.get('task_version'):raise ConflictError('人工任务已处理或版本已变更。')
        if decision.get('decision') not in {'SUPPORTED','CONTRADICTED','INSUFFICIENT_EVIDENCE'}:raise ValueError('人工判定无效。')
        ids=decision.get('selected_evidence_ids',[])
        if not set(ids)<={e['evidence_id'] for e in item.get('evidence',[])}:raise ValueError('人工判定引用未知证据。')
        if decision['decision']=='SUPPORTED' and not ids:raise ValueError('判为支持时请至少选择一条证据。')
        if not str(decision.get('comment','')).strip() or not str(decision.get('decided_by','')).strip():raise ValueError('人工复核须填写理由与复核人。')
        saved={**decision,'decided_at':now()}
        item.setdefault('automatic_verdict',{k:item.get(k) for k in ('status','reason','confidence','issue_types','primary_issue')})
        original_task=dict(task)
        item.update(status=saved['decision'],reason=saved['comment'],human_decision=saved,evidence_ids=ids,pending_review=False)
        task.update(status='RESOLVED',task_version=task['task_version']+1)
        pending=[i['human_task'] for i in state['completed_results'] if i.get('pending_review')]
        counts={}
        for result in state['completed_results']:counts[result['status']]=counts.get(result['status'],0)+1
        status='HUMAN_REVIEW_REQUIRED' if pending else 'COMPLETED'
        state.update(human_tasks=pending,workflow_status=status)
        state['review_result'].update(status=status,completed_results=state['completed_results'],summary_counts=counts)
        record.update(status=status,updated_at=now())
        if status=='COMPLETED':record['completed_at']=now()
        self.store.append(record['review_id'],'human_decision',{'input_task':original_task,'decision':saved,'final_result':item},saved['decided_by'])
        self.store.save('review',record['review_id'],record)
        return record

    def supplement(self, ident, payload):
        with self.lock:
            record = self.get(ident)
            if record['status'] != 'HUMAN_REVIEW_REQUIRED':
                raise ConflictError('只能为待人工复核点补充检索。')
            queued=record.get('workflow_version',1)>=2
            item=next((i for i in record['state'].get('completed_results',[]) if i['fact_id']==payload.get('fact_id')),None) if queued else None
            if queued and not item:raise ValueError('请选择待人工复核点。')
            task = item.get('human_task') if queued else record['state']['human_task']
            if not task or task.get('status')!='PENDING':raise ConflictError('此复核点不在待办中。')
            if payload.get('task_version') != task['task_version']:
                raise ConflictError('人工任务版本已变更，请刷新后重试。')
            query = str(payload.get('query_text') or '').strip()
            if not query or len(query) > 2000:
                raise ValueError('补充查询须为 1 至 2000 字符。')
            hits = self.knowledge.retrieve(record['kb_version'], {'query_text': query, 'query_id': 'HUMAN-SUPPLEMENT-' + str(task['task_version']), 'retrieval_profile': 'hybrid'}, record['source_scope'], ident)
            state = record['state']
            target=item if queued else state
            evidence_key='evidence' if queued else 'current_evidence'
            known = {e['evidence_id'] for e in target.get(evidence_key, [])}
            additions = [h for h in hits if h['evidence_id'] not in known]
            target[evidence_key] = target.get(evidence_key, []) + additions
            task['task_version'] += 1
            self.store.append(ident, 'human_supplementary_retrieval', {'query': query, 'added_evidence': additions, 'task_version': task['task_version'], 'note': '新增候选尚未被模型判为支持，须人工逐条确认。'}, 'local-reviewer')
            self.store.save('review', ident, record)
            return record
