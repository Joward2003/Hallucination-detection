"""Regression cases from the 4d268fe production code review. No real API calls."""
import json
import random
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from credit_review.workbench.agents import (
    Extractor, NumericValidator, WorkbenchRiskPolicy, Verifier,
    _split_report_into_parents, compute_check,
)
from credit_review.workbench.app import create_workbench_app
from credit_review.workbench.storage import Store
from credit_review.graph.builder import build_review_graph, default_services


@pytest.mark.parametrize('text', [
    '经营情况正常。' * 800,
    '   营业收入100万元。   ',
    '一、' + '甲'*900 + '\n二、' + '乙'*900,
    '前言'*8 + '\n一、' + '甲'*19 + '\n二、' + '乙'*15,
    '相同结论。\n\n相同结论。\r\n（三）🙂风险说明。'*100,
    '\n'*900 + '正文。' + ' '*900,
])
@pytest.mark.parametrize('limit', [1, 20, 800])
def test_parent_slices_are_bounded_contiguous_and_exact(text, limit):
    blocks = _split_report_into_parents(text, limit)
    assert ''.join(block for block, _, _ in blocks) == text
    offset = 0
    for block, start, end in blocks:
        assert start == offset and 0 < end-start <= limit
        assert text[start:end] == block
        offset = end
    assert offset == len(text)


def test_random_section_lengths_do_not_drift_offsets():
    rng = random.Random(42)
    for _ in range(50):
        text = '\n'.join(f'{i}、'+rng.choice(['甲', '🙂', ' '])*rng.randint(1,1500) for i in range(6))
        blocks = _split_report_into_parents(text)
        assert ''.join(b for b, _, _ in blocks) == text
        assert all(text[s:e] == b and 0 < len(b) <= 800 for b,s,e in blocks)


@pytest.mark.parametrize('limit', [0, -1, True, 1.5])
def test_invalid_chunk_limits_are_rejected(limit):
    with pytest.raises(ValueError):
        _split_report_into_parents('正文。', limit)


class Gateway:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.events = []

    def complete_json(self, messages):
        result = next(self.replies)
        if isinstance(result, Exception):
            raise result
        return result

    def record(self, stage, body):
        self.events.append((stage, body))


def test_rejected_risk_is_audited_and_preserved_for_human():
    gateway = Gateway([{'children': [
        {'fact': '收入增长。', 'source_quote': '收入增长。'},
        {'fact': '存在逾期贷款。', 'source_quote': '引用不存在'},
    ]}])
    report = '   收入增长。存在逾期贷款。'
    groups = Extractor(gateway).extract(report)
    children = groups[0]['children']
    assert any(stage == 'extraction_child_rejected' for stage, _ in gateway.events)
    gap = children[-1]
    assert '逾期贷款' in gap['fact'] and gap['review_kind'] == 'extraction_gap'
    assert all(report[c['source_start']:c['source_end']] == c['source_quote'] for c in children)
    verifier = Verifier(Gateway([]))
    verdict = verifier.verify(gap, groups[0]['parent'], [], [], 'INSUFFICIENT')
    assert verdict['status'] == 'INSUFFICIENT_EVIDENCE'
    assert WorkbenchRiskPolicy().decide(child=gap, initial_verdict=verdict, rule_hits=[], has_counter_evidence=False)['next_step'] == 'human'


@pytest.mark.parametrize('reply', [{'children': []}, {}, None, {'children': [None]}, {'children': [42]}])
def test_empty_or_malformed_children_preserve_original(reply):
    result = Extractor(Gateway([reply])).extract('营业收入100万元。')
    assert result[0]['children'][0]['fact'] == '营业收入100万元。'
    assert result[0]['children'][0]['review_kind'] == 'extraction_gap'


def test_failed_segment_continues_next_segment_with_durable_workpapers(tmp_path):
    store = Store(tmp_path)
    report = '甲' * 800 + '收入增长。'
    gateway = Gateway([RuntimeError('upstream unavailable'), {'children': [{'fact': '收入增长。', 'source_quote': '收入增长。'}]}])
    gateway.record = lambda stage, body: store.append('R-test', stage, body)
    groups = Extractor(gateway).extract(report)
    assert groups[0]['children'][0]['review_kind'] == 'extraction_gap'
    assert groups[1]['children'][0]['fact'] == '收入增长。'
    assert store.verify('R-test')['valid']
    assert any(p['stage'] == 'extraction_segment_failed' for p in store.papers('R-test'))


def test_numbers_must_be_from_the_child_quote_not_another_sentence():
    gateway = Gateway([{'children': [{'fact': '收入200万元', 'source_quote': '收入100万元。'}]}])
    children = Extractor(gateway).extract('收入100万元。负债200万元。')[0]['children']
    assert all(c.get('review_kind') == 'extraction_gap' for c in children)


def operand(value='100', period='2024', unit='万元', metric='营业收入', eid='E1', quote=None):
    return {'value': value, 'period': period, 'unit': unit, 'metric': metric, 'evidence_id': eid,
            'quote': quote or f'{period}年{metric}{value}{unit}。'}


def amount(binding=None, fact='2024年营业收入100万元'):
    binding = binding or operand()
    return {'kind': 'amount', 'expected': '100', 'unit': '万元', 'report_quote': fact,
            'operands': {'current': binding}}, fact, [{'evidence_id': 'E1', 'content': binding['quote']}]


def test_numeric_states_and_bad_schema_are_not_factual_conflicts():
    spec, fact, evidence = amount()
    assert compute_check(spec, fact, evidence)['passed'] is True
    spec['expected'] = '200'; spec['report_quote'] = fact = '2024年营业收入200万元'
    assert compute_check(spec, fact, evidence)['passed'] is False
    spec['operands']['current']['period'] = '2022'
    result = compute_check(spec, fact, evidence)
    assert result['passed'] is None and result['observed'] is None
    for invalid in (None, [], {'operands': None}, {**spec, 'expected': 'NaN'}, {**spec, 'expected': 'Infinity'}):
        assert compute_check(invalid, fact, evidence)['passed'] is None


def test_unit_suffix_is_not_a_unit_match():
    source = operand(unit='元', quote='2024年营业收入100万元')
    spec, fact, evidence = amount(source)
    spec.update(unit='元')
    assert compute_check(spec, fact, evidence)['passed'] is None
    spec['report_quote'] = fact = '2024年营业收入100元'
    assert compute_check(spec, fact, evidence)['passed'] is None


def test_multi_year_and_multi_metric_quotes_cannot_swap_values():
    for quote in ('2024年营业收入100万元，2023年营业收入200万元', '2024年营业收入100万元，净利润200万元'):
        source = operand('200', quote=quote)
        spec, fact, evidence = amount(source, '2024年营业收入200万元')
        spec['expected'] = '200'
        assert compute_check(spec, fact, evidence)['passed'] is None
    source = operand('200', '2023')
    spec, fact, evidence = amount(source, '2024年营业收入200万元')
    spec['expected'] = '200'
    assert compute_check(spec, fact, evidence)['passed'] is None


def test_html_cells_need_verified_coordinates_instead_of_substring_binding():
    source = operand(quote='<tr><td>2024年营业收入</td><td>100万元</td></tr>')
    spec, fact, evidence = amount(source)
    assert compute_check(spec, fact, evidence)['passed'] is None


@pytest.mark.parametrize('quote', ['2024年营业收入100万元，净利润较低', '2024年净利润较低，营业收入100万元', '2024年净利润低于营业收入100万元'])
def test_single_quantity_cannot_be_bound_to_a_different_metric(quote):
    source = operand(metric='净利润', quote=quote)
    spec, fact, evidence = amount(source, '2024年净利润100万元')
    assert compute_check(spec, fact, evidence)['passed'] is None


def test_income_alias_does_not_match_nonoperating_income():
    spec, fact, evidence = amount(fact='2024年营业外收入100万元')
    assert compute_check(spec, fact, evidence)['passed'] is None


@pytest.mark.parametrize('qualified', ['扣非净利润', '归母净利润', '调整后净利润', '扣除非经常性损益后的净利润'])
def test_generic_profit_cannot_validate_a_differently_qualified_metric(qualified):
    source = operand(metric='净利润')
    spec, fact, evidence = amount(source, f'2024年{qualified}100万元')
    assert compute_check(spec, fact, evidence)['passed'] is None
    source = operand(metric='净利润', quote=f'2024年{qualified}100万元')
    spec, fact, evidence = amount(source, '2024年净利润100万元')
    assert compute_check(spec, fact, evidence)['passed'] is None


@pytest.mark.parametrize('previous,word,expected,passed', [('200','下降','50',True), ('200','减少','50',True), ('50','增长','100',True), ('200','增长','50',False), ('0','增长','50',None), ('-200','增长','50',None)])
def test_yoy_direction_and_nonpositive_base(previous, word, expected, passed):
    current, old = operand('100'), operand(previous, '2023', eid='E2')
    fact = f'2024年营业收入同比{word}{expected}%'
    spec = {'kind':'yoy','expected':expected,'unit':'%','report_quote':fact,'operands':{'current':current,'previous':old}}
    evidence = [{'evidence_id':'E1','content':current['quote']}, {'evidence_id':'E2','content':old['quote']}]
    assert compute_check(spec, fact, evidence)['passed'] is passed


def test_one_check_does_not_hide_another_unbound_amount():
    spec, fact, evidence = amount()
    child = {'fact_id':'F1','fact':fact+'，净利润20万元。'}
    validator = NumericValidator(SimpleNamespace(bindings={'F1':[spec]}))
    checks = validator.validate(child, evidence)
    assert checks[0]['passed'] is True
    assert checks[-1]['passed'] is None and checks[-1]['unbound_quantities'] == ['20万元']


def test_graph_routes_unresolved_numeric_bindings_to_human_not_conflict():
    services = default_services()
    class Numeric:
        def validate(self, *args): return [{'passed': None, 'observed': None, 'failure_reason': '期间错配'}]
    services.numeric_validator = Numeric()
    services.risk_policy = WorkbenchRiskPolicy()
    checkpoint = {'original_input':'营业收入100万元。','current_parent':{'parent_id':'P1','parent_text':'营业收入100万元。'},
        'current_fact':{'fact_id':'F1','parent_id':'P1','fact':'营业收入100万元。','importance':'medium'},
        'verification_result':{'status':'SUPPORTED','confidence':'high','evidence_ids':[]},
        'initial_verdict':{'status':'SUPPORTED','confidence':'high'}, 'current_assessments':[],
        'current_evidence':[], 'current_queries':[], 'evidence_status':'SUFFICIENT'}
    # Start from verification with a controlled verifier to exercise the real numeric node.
    class Verify:
        def verify(self, *args): return {'status':'SUPPORTED','confidence':'high','evidence_ids':[]}
    services.verifier = Verify()
    result = build_review_graph(services, entry_node='verify').invoke(checkpoint, config={'recursion_limit':100})
    assert result['verification_result']['status'] == 'INSUFFICIENT_EVIDENCE'
    assert result['workflow_status'] == 'HUMAN_REVIEW_REQUIRED'


def test_real_app_factory_import_and_health_without_model_calls(tmp_path):
    with TestClient(create_workbench_app(tmp_path, backend='lexical')) as client:
        assert client.get('/health/live').status_code == 200
        assert client.get('/v1/reviews').json() == []


def test_unresolved_extraction_reaches_human_without_another_model_call():
    gateway = Gateway([RuntimeError('model unavailable')])
    services = default_services()
    services.extractor = Extractor(gateway)
    services.risk_policy = WorkbenchRiskPolicy()
    class MustNotCall:
        def __getattr__(self, name):
            def fail(*args, **kwargs): raise AssertionError('unresolved extraction must not call '+name)
            return fail
    services.query_planner = services.grader = services.retriever = services.verifier = MustNotCall()
    services.numeric_validator = NumericValidator(SimpleNamespace(bindings={}))
    result = build_review_graph(services).invoke({'original_input':'存在逾期贷款。'}, config={'recursion_limit':100})
    assert result['workflow_status'] == 'HUMAN_REVIEW_REQUIRED'
    assert 'extraction_incomplete' in result['risk_decision']['reason_codes']
    assert result['verification_result']['status'] == 'INSUFFICIENT_EVIDENCE'


def test_workbench_api_upload_build_review_and_human_completion(tmp_path, monkeypatch):
    """Exercise the production service assembly; only the external model is replaced."""
    from credit_review.workbench import reviews as review_module
    from credit_review.workbench.provider.config import Settings
    monkeypatch.setattr(review_module, 'load_settings', lambda: Settings(api_key='test-only-key'))
    holder = {}
    class Model:
        def __init__(self, job): self.job = job
        def record(self, stage, body): holder['app'].state.store.append(self.job, stage, body)
        def complete_json(self, messages):
            try: data = json.loads(messages[-1]['content'])
            except json.JSONDecodeError: raise ValueError('exercise audited planning fallback')
            if 'parent_segment' in data:
                return {'children':[{'fact':data['parent_segment'], 'source_quote':data['parent_segment'], 'importance':'high'}]}
            if 'risk_evidence' in data: return {'omissions':[]}
            if 'parent_context' in data:
                evidence = data['evidence'][0]
                return {'status':'SUPPORTED','confidence_band':'high','reason':'引用及程序计算匹配',
                        'evidence_ids':[evidence['evidence_id']], 'issue_types':[],
                        'citation_quotes':[{'evidence_id':evidence['evidence_id'],'quote':evidence['content']}],
                        'numeric_checks':[{'kind':'amount','expected':'100','unit':'万元','report_quote':data['claim'],
                            'operands':{'current':operand(eid=evidence['evidence_id'],quote=evidence['content'])}}]}
            return {'assessments':[{'evidence_id':e['evidence_id'],'relation':'SUPPORTS','quote':e['content'],'rationale':'原文直接支持'} for e in data['evidence']]}
    app = create_workbench_app(tmp_path, backend='lexical', gateway_factory=Model)
    holder['app'] = app
    def await_record(client, path, statuses):
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            response = client.get(path); assert response.status_code == 200
            record = response.json()
            if record['status'] in statuses: return record
            time.sleep(.01)
        raise AssertionError('background job did not reach expected status')
    with TestClient(app) as client:
        doc = client.post('/v1/documents', files={'file':('annual.txt','2024年营业收入100万元。'.encode())}, data={'period':'2024'}).json()
        assert doc['status'] == 'READY'
        build = client.post('/v1/knowledge-bases/builds', json={'document_ids':[doc['document_id']]}).json()
        build = await_record(client, '/v1/knowledge-bases/builds/'+build['build_id'], {'READY','FAILED'})
        assert build['status'] == 'READY'
        response = client.post('/v1/reviews', json={
            'report_id':'test-report','report_version':'v1','tenant_id':'local','project_id':'local',
            'requested_by':'test-reviewer','idempotency_key':'test-once','report_text':'2024年营业收入100万元。',
            'kb_version':build['version']})
        assert response.status_code == 202
        rid = response.json()['review_id']
        record = await_record(client, '/v1/reviews/'+rid, {'HUMAN_REVIEW_REQUIRED','FAILED'})
        assert record['status'] == 'HUMAN_REVIEW_REQUIRED', record.get('error')
        assert record['state']['numeric_checks'][0]['passed'] is True
        task = record['state']['human_task']
        result = client.post('/v1/human-tasks/'+rid+'/decision', json={
            'task_version':task['task_version'],'decision':'SUPPORTED','selected_evidence_ids':record['state']['verification_result']['evidence_ids'],
            'comment':'仅验证测试链路','decided_by':'test-reviewer'})
        assert result.status_code == 200 and result.json()['status'] == 'COMPLETED'
        assert client.get('/v1/audit/'+rid).json()['integrity']['valid']
