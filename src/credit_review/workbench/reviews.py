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


class RiskCoverageExtractor:
    def __init__(self, extractor, retriever, gateway):
        self.extractor, self.retriever, self.gateway = extractor, retriever, gateway

    def extract(self, report):
        groups = self.extractor.extract(report)
        evidence = self.retriever.retrieve({'query_text': '偿债 信贷风险 逾期 担保 诉讼 现金流 债务 集中度 或有负债', 'query_id': 'REPORT-RISK', 'retrieval_profile': 'hybrid'})
        self.gateway.record('report_risk_coverage_input', {'report': report, 'evidence': evidence})
        data = ask(self.gateway, '检查整份报告是否遗漏已给出证据中的重要信贷风险，只评估当前召回范围。不能把没有检索到等同于没有风险。输出 {"omissions":[{"risk":"具体风险","evidence_id":"...","quote":"逐字证据","reason":"报告为什么未覆盖"}]}。已覆盖、无可靠证据或无法确定时返回空列表。', {'report': report, 'risk_evidence': evidence})
        known = {e['evidence_id']: e for e in evidence}
        omissions = data.get('omissions')
        if not isinstance(omissions, list):
            raise ValueError('风险遗漏检查输出无效。')
        self.gateway.record('report_risk_coverage_result', {'omissions': omissions, 'boundary': '仅覆盖本次知识库和召回证据；不能保证穷尽全部业务风险。'})
        for index, omission in enumerate(omissions[:8], 1):
            item = known.get(omission.get('evidence_id'))
            if not item or not omission.get('quote') or omission['quote'] not in item['content']:
                raise ValueError('风险遗漏引用未匹配原文。')
            pid = f'RISK{index:02d}'
            groups.append({'parent': {'parent_id': pid, 'parent_text': report, 'source_start': 0, 'source_end': len(report)},
                           'children': [{'fact_id': pid + '-F01', 'parent_id': pid, 'fact': '报告可能遗漏的信贷风险：' + omission['risk'],
                                         'source_start': 0, 'source_end': 0, 'importance': 'high', 'review_kind': 'risk_omission',
                                         'risk_reference': omission}]})
        return groups


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
        if len(request.report_text) > 100000:
            raise ValueError('报告正文超过 10 万字符，请分批提交。')
        version = payload.get('kb_version')
        kb_id = payload.get('kb_id')
        if not version:
            version = self.store.get('kb', kb_id or 'credit-kb')['active_version']
        snapshot = self.knowledge.snapshot(version)
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
            scope.update(allowed_document_ids=allowed, corpus_version=version, rule_set_version='credit-review-workbench-v1')
            record = {'review_id': ident, 'report_id': request.report_id, 'report_name': payload.get('report_name') or request.report_id,
                      'tenant_id': request.tenant_id, 'project_id': request.project_id, 'requested_by': request.requested_by,
                      'idempotency_key': request.idempotency_key, 'request_hash': fingerprint, 'kb_version': version,
                      'source_scope': scope, 'companies': request.companies, 'report_version': request.report_version, 'report_type': payload.get('report_type', '金融信贷报告'),
                      'status': 'QUEUED', 'state': {'original_input': request.report_text}, 'created_at': now(),
                      'model_config': settings.public(), 'retrieval_config': {k: snapshot.get(k) for k in ('backend', 'embedding_model', 'reranker_model')},
                      'rule_set_version': 'credit-review-workbench-v1'}
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
        return [{**r['state']['human_task'], 'review_id': r['review_id']} for r in self.store.list('review')
                if r['status'] == 'HUMAN_REVIEW_REQUIRED' and (r['state'].get('human_task') or {}).get('status') == 'PENDING']

    def _services(self, record):
        gateway = self.gateway_factory(record['review_id'])
        retriever = BoundRetriever(self.knowledge, record['kb_version'], record['source_scope'], record['review_id'])
        services = default_services(companies=record.get('companies'), retrieval_backend='deterministic')
        services.retriever = retriever
        services.extractor = RiskCoverageExtractor(Extractor(gateway), retriever, gateway)
        services.query_planner = Planner(gateway)
        services.grader = Grader(gateway)
        services.verifier = Verifier(gateway)
        services.numeric_validator = NumericValidator(services.verifier)
        services.critic_verifier = None
        services.risk_policy = WorkbenchRiskPolicy()
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
            code_root = Path(__file__).resolve().parents[1]
            source_hashes = {str(p.relative_to(code_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code_root.rglob('*.py')}
            self.store.append(ident, 'engine_version', {'source_hashes': source_hashes, 'entry_node': entry, 'provider': load_settings().public()})
            services = self._services(record)
            graph = build_review_graph(services, trace=trace, entry_node=entry)
            result = graph.invoke(state, config={'recursion_limit': 2000})
            current = self.get(ident)
            current.update(state=result, status=result['workflow_status'], updated_at=now())
            if current['status'] == 'COMPLETED': current['completed_at'] = now()
            result['corpus_version'] = record['kb_version']
            result['rule_set_version'] = record['rule_set_version']
            self.store.save('review', ident, current)
            self.store.append(ident, 'review_checkpoint', {'status': current['status'], 'completed_claims': len(result.get('completed_results', [])), 'next_child_index': result.get('child_index')})
        except Exception as exc:
            current = self.get(ident)
            if current['status'] != 'CANCELLED':
                current.update(status='FAILED', error=str(exc), updated_at=now())
                self.store.save('review', ident, current)
            self.store.append(ident, 'review_failed', {'error': str(exc), 'error_type': type(exc).__name__})

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
            if record['status'] == 'FAILED' and state.get('current_fact') and record.get('failed_node') in {'plan_query', 'retrieve', 'grade_evidence', 'rewrite_query', 'verify'}:
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

    def supplement(self, ident, payload):
        with self.lock:
            record = self.get(ident)
            if record['status'] != 'HUMAN_REVIEW_REQUIRED':
                raise ConflictError('只能为待人工复核点补充检索。')
            task = record['state']['human_task']
            if payload.get('task_version') != task['task_version']:
                raise ConflictError('人工任务版本已变更，请刷新后重试。')
            query = str(payload.get('query_text') or '').strip()
            if not query or len(query) > 2000:
                raise ValueError('补充查询须为 1 至 2000 字符。')
            hits = self.knowledge.retrieve(record['kb_version'], {'query_text': query, 'query_id': 'HUMAN-SUPPLEMENT-' + str(task['task_version']), 'retrieval_profile': 'hybrid'}, record['source_scope'], ident)
            state = record['state']
            known = {e['evidence_id'] for e in state.get('current_evidence', [])}
            additions = [h for h in hits if h['evidence_id'] not in known]
            state['current_evidence'] = state.get('current_evidence', []) + additions
            task['task_version'] += 1
            self.store.append(ident, 'human_supplementary_retrieval', {'query': query, 'added_evidence': additions, 'task_version': task['task_version'], 'note': '新增候选尚未被模型判为支持，须人工逐条确认。'}, 'local-reviewer')
            self.store.save('review', ident, record)
            return record
