"""Meaningful persistence, graph continuation, source and audit boundary tests."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
import hashlib
import io
import json
import time
import zipfile
import pytest
from fastapi.testclient import TestClient
from credit_review.workbench.storage import Store, encode
from credit_review.workbench.knowledge import Knowledge, BoundRetriever
from credit_review.workbench.agents import compute_check, Grader, Extractor, WorkbenchRiskPolicy
from credit_review.workbench.exports import bundle
from credit_review.workbench.app import create_workbench_app
from credit_review.graph.builder import build_review_graph, default_services, resume_review


class ImmediateExecutor:
    def submit(self, fn, *args):
        fn(*args)


def source(store, text):
    knowledge=Knowledge(store,ImmediateExecutor(),backend='lexical')
    doc=knowledge.register('proof.txt',text.encode(),company='甲公司',period='2024')
    build=knowledge.create({'document_ids':[doc['document_id']],'kb_id':'credit-kb'})
    return knowledge,doc,knowledge.store.get('build',build['build_id'])


def test_durable_hash_chain_detects_tampering(tmp_path):
    store=Store(tmp_path)
    store.append('R1','extract',{'report':'测试'})
    store.append('R1','decision',{'status':'SUPPORTED'},'张三')
    assert Store(tmp_path).verify('R1')['valid']
    with store.connect() as db:
        with pytest.raises(Exception): db.execute("UPDATE papers SET body='{}'")
        db.execute('DROP TRIGGER immutable_papers_update')
        db.execute("UPDATE papers SET body='{}' WHERE seq=1")
    assert not store.verify('R1')['valid']


def test_child_retrieval_returns_parent_and_original_hash(tmp_path):
    store=Store(tmp_path)
    knowledge,doc,build=source(store,'2024 年营业收入为 100 万元。经营现金流不足，不能只看收入。\n\n诉讼未结。')
    hits=knowledge.retrieve(build['version'],{'query_text':'营业收入'},job='SEARCH1')
    assert hits
    assert '经营现金流不足' in hits[0]['content']
    assert hits[0]['source_url'].endswith('/original')
    assert hits[0]['original_sha256']==doc['sha256']
    assert hits[0]['content_hash']==hashlib.sha256(hits[0]['content'].encode()).hexdigest()
    assert store.verify('SEARCH1')['valid']
    reopened=Knowledge(Store(tmp_path),ImmediateExecutor(),backend='lexical')
    assert reopened.snapshot(build['version'])['children']


def test_failed_build_never_overwrites_active_version(tmp_path):
    store=Store(tmp_path)
    knowledge,doc,first=source(store,'营业收入为 100 万元。')
    class Broken:
        def retrieve(self,*args,**kwargs): raise RuntimeError('index unavailable')
    knowledge._searcher=lambda *args: (_ for _ in ()).throw(RuntimeError('index unavailable'))
    second=knowledge.create({'document_ids':[doc['document_id']],'kb_id':'credit-kb'})
    assert store.get('build',second['build_id'])['status']=='FAILED'
    assert store.get('kb','credit-kb')['active_version']==first['version']


def test_empty_scan_is_failed_source(tmp_path):
    from pypdf import PdfWriter
    writer=PdfWriter();writer.add_blank_page(width=100,height=100)
    buffer=io.BytesIO();writer.write(buffer)
    knowledge=Knowledge(Store(tmp_path),ImmediateExecutor(),backend='lexical')
    doc=knowledge.register('scan.pdf',buffer.getvalue())
    assert doc['status']=='FAILED' and 'OCR' in doc['error']


def binding(metric,value,unit='万元',period='2024',eid='E1'):
    return {'metric':metric,'value':value,'unit':unit,'period':period,'evidence_id':eid,'quote':period+' 年'+metric+'为 '+value+' '+unit+'。'}


def test_decimal_unit_ratio_and_yoy_do_not_use_model_math():
    current=binding('营业收入','120')
    previous=binding('营业收入','100',period='2023',eid='E2')
    evidence=[{'evidence_id':'E1','content':current['quote']},{'evidence_id':'E2','content':previous['quote']}]
    spec={'kind':'yoy','expected':'20','unit':'%','report_quote':'同比增长 20%','operands':{'current':current,'previous':previous}}
    check=compute_check(spec,'公司营业收入同比增长 20%。',evidence)
    assert check['passed'] and Decimal(check['observed'])==20
    spec.update(kind='amount',expected='0.012',unit='亿元',report_quote='收入 0.012 亿元',operands={'current':current})
    assert compute_check(spec,'收入 0.012 亿元',evidence)['passed']
    numerator=binding('总负债','40');denominator=binding('总资产','100',eid='E2')
    spec.update(kind='ratio',expected='40',unit='%',report_quote='资产负债率 40%',operands={'numerator':numerator,'denominator':denominator})
    evidence=[{'evidence_id':'E1','content':numerator['quote']},{'evidence_id':'E2','content':denominator['quote']}]
    assert compute_check(spec,'资产负债率 40%',evidence)['passed']
    spec['expected']='50';spec['report_quote']='资产负债率 50%'
    assert compute_check(spec,'资产负债率 50%',evidence)['passed'] is False
    spec['operands']['numerator']['period']='2022'
    assert compute_check(spec,'资产负债率 50%',evidence)['passed'] is None


def test_unknown_or_fabricated_citations_never_become_evidence():
    class Gateway:
        def complete_json(self,messages): return {'assessments':[{'evidence_id':'E1','relation':'SUPPORTS','quote':'假造原文'}]}
    assessments,status = Grader(Gateway()).grade({'fact':'测试'},[{'evidence_id':'E1','content':'真实原文'}])
    assert status == 'INSUFFICIENT'
    assert assessments[0]['usable'] is False and assessments[0]['quote'] == ''


def test_extractor_preserves_offsets_and_rejects_missing_coverage():
    class Gateway:
        def complete_json(self,messages): return {'children':[{'fact':'收入增长','source_quote':'收入增长'}]}
    assert Extractor(Gateway()).extract('收入增长。')[0]['children'][0]['source_end']==4
    children = Extractor(Gateway()).extract('收入增长。风险加大。')[0]['children']
    assert children[-1]['review_kind'] == 'extraction_gap'
    assert '风险加大' in children[-1]['fact']


def test_real_graph_human_resume_runs_remaining_children():
    services=default_services(evidence=[{'evidence_id':'E1','source':'年报','content':'营业收入增长。净利润下降。','page':1,'evidence_type':'text'}])
    services.risk_policy=WorkbenchRiskPolicy()
    class Verifier:
        def verify(self,*args): return {'status':'INSUFFICIENT_EVIDENCE','confidence':'low','reason':'需确认','evidence_ids':[]}
    services.verifier=Verifier()
    state=build_review_graph(services).invoke({'original_input':'营业收入增长。净利润下降。'},config={'recursion_limit':200})
    assert state['workflow_status']=='HUMAN_REVIEW_REQUIRED' and state['child_index']==0
    next_state=resume_review(state,{'task_version':1,'decision':'INSUFFICIENT_EVIDENCE','comment':'确认','decided_by':'甲'})
    assert next_state['child_index']==1
    next_state=build_review_graph(services,entry_node='prepare_child').invoke(next_state,config={'recursion_limit':200})
    assert next_state['human_task']['fact_id']!=state['human_task']['fact_id']
    assert len(next_state['completed_results'])==1


def test_bundle_contains_real_original_and_manifest_hashes(tmp_path):
    store=Store(tmp_path);knowledge,doc,build=source(store,'真实来源。')
    data=bundle(store,knowledge,build['build_id'])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        for name,detail in manifest['files'].items(): assert hashlib.sha256(archive.read(name)).hexdigest()==detail['sha256']
        assert archive.read('sources/'+doc['document_id']+'.txt')=='真实来源。'.encode()


def test_api_source_scope_origin_errors_and_redacted_config(tmp_path):
    app=create_workbench_app(tmp_path,backend='lexical')
    with TestClient(app) as client:
        assert 'api_key' not in client.get('/v1/runtime').json()['provider']
        assert client.get('/v1/documents',headers={'Origin':'https://attacker.example'}).status_code==403
        assert client.get('/v1/documents',headers={'Host':'attacker.example'}).status_code==403
        assert client.get('/v1/reviews/missing').status_code==404
        assert client.get('/v1/missing').status_code==404
        doc=client.post('/v1/documents',files={'file':('proof.txt','<script>alert(1)</script>。'.encode())}).json()
        response=client.get('/v1/documents/'+doc['document_id']+'/view')
        assert '&lt;script&gt;' in response.text
        assert '<script>alert' not in response.text


def test_source_and_snapshot_integrity_prevent_modified_evidence(tmp_path):
    store=Store(tmp_path);knowledge,doc,build=source(store,'真实财务数据。')
    path,_=knowledge.source_path(doc['document_id'])
    path.write_text('被修改的数据。')
    with pytest.raises(ValueError):knowledge.source_path(doc['document_id'])
    snapshot=store.root/'knowledge'/build['version']/'snapshot.json'
    snapshot.write_text('{}')
    with pytest.raises(ValueError):knowledge.snapshot(build['version'])


def test_human_reasons_selected_sources_and_optimistic_lock(tmp_path):
    from credit_review.workbench.reviews import Reviews
    store=Store(tmp_path);knowledge,doc,build=source(store,'收入为 100 万元。')
    services=default_services(evidence=[{'evidence_id':'E1','content':'收入为100万元。','source':'年报','page':1,'evidence_type':'text'}])
    services.risk_policy=WorkbenchRiskPolicy()
    class Low:
        def verify(self,*args):return {'status':'INSUFFICIENT_EVIDENCE','confidence':'low','evidence_ids':[]}
    services.verifier=Low()
    state=build_review_graph(services).invoke({'original_input':'收入为100万元。'},config={'recursion_limit':200})
    record={'review_id':'R1','report_id':'测试','status':'HUMAN_REVIEW_REQUIRED','state':state,'kb_version':build['version'],'source_scope':{},'requested_by':'甲'}
    store.save('review','R1',record)
    manager=Reviews(store,knowledge,ImmediateExecutor())
    with pytest.raises(ValueError):manager.submit_human_decision('R1',{'task_version':1,'decision':'SUPPORTED','comment':'测试','decided_by':'甲','selected_evidence_ids':['FAKE']})
    with pytest.raises(Exception):manager.submit_human_decision('R1',{'task_version':99,'decision':'INSUFFICIENT_EVIDENCE','comment':'测试','decided_by':'甲'})
    result=manager.submit_human_decision('R1',{'task_version':1,'decision':'INSUFFICIENT_EVIDENCE','comment':'证据缺少期间','decided_by':'甲','selected_evidence_ids':[],'final_text':'金额需补证'})
    assert result['status']=='COMPLETED'
    assert result['state']['completed_results'][0]['human_decision']['final_text']=='金额需补证'
    assert Store(tmp_path).get('review','R1')['status']=='COMPLETED'
    with pytest.raises(Exception):manager.submit_human_decision('R1',{'task_version':1,'decision':'SUPPORTED','comment':'再次','decided_by':'甲','selected_evidence_ids':[]})
    assert store.verify('R1')['valid']


def test_interrupted_jobs_persist_restart_status(tmp_path):
    from credit_review.workbench.reviews import Reviews
    store=Store(tmp_path)
    store.save('review','R1',{'review_id':'R1','status':'RUNNING','state':{'original_input':'未完成报告'},'last_node':'verify'})
    manager=Reviews(store,Knowledge(store,ImmediateExecutor(),backend='lexical'),ImmediateExecutor())
    assert manager.get('R1')['status']=='INTERRUPTED'
    assert store.verify('R1')['valid']


def test_responses_requires_terminal_completion():
    from credit_review.workbench.provider.api import read_sse,APIError
    partial=io.BytesIO(b'data: {"type":"response.output_text.delta","delta":"OK"}\n\n')
    with pytest.raises(APIError):read_sse(partial)
    full=io.BytesIO(b'data: {"type":"response.completed","response":{"status":"completed","output":[]}}\n\n')
    assert read_sse(full)['status']=='completed'


def test_failure_retry_starts_at_verification_without_losing_evidence():
    services=default_services(evidence=[{'evidence_id':'E1','source':'年报','content':'营业收入增长。','page':1,'evidence_type':'text'}])
    state=build_review_graph(services).invoke({'original_input':'营业收入增长。'},config={'recursion_limit':200})
    group=state['fact_groups'][0]
    checkpoint={'original_input':'营业收入增长。','fact_groups':state['fact_groups'],'flat_children':state['flat_children'],
                'child_index':0,'completed_results':[],'current_parent':group['parent'],'current_fact':group['children'][0],
                'current_queries':[{'query_text':'已保存查询'}],'current_evidence':[{'evidence_id':'E1','source':'年报','content':'营业收入增长。','page':1,'evidence_type':'text'}],
                'current_assessments':[{'evidence_id':'E1','relation':'SUPPORTS','usable':True}], 'evidence_status':'SUFFICIENT','retry_count':0}
    seen=[]
    result=build_review_graph(services,entry_node='verify',trace=lambda event:seen.append(event.get('node'))).invoke(checkpoint,config={'recursion_limit':200})
    assert result['workflow_status']=='COMPLETED'
    assert result['completed_results'][0]['queries']==[{'query_text':'已保存查询'}]
    assert 'extract_parent_child' not in seen and 'plan_query' not in seen


def test_mineru_parent_keeps_unfinished_context_and_table_caption():
    from credit_review.knowledge_base.pipeline import KnowledgeBaseBuilder
    snapshot=KnowledgeBaseBuilder(parser_version='mineru-context-v2').build([
        {'type':'text','text':'由于客户回款','page_idx':1},
        {'type':'text','text':'延迟，公司现金流承压。','page_idx':1},
        {'type':'table','table_caption':['2024 年财务数据，单位：万元'],'table_body':'<table><tr><td>收入</td><td>100</td></tr></table>','table_footnote':['不含内部交易'],'page_idx':1},
    ])
    assert len(snapshot['parents'])==2
    assert '延迟' in snapshot['parents'][0]['parent_text']
    assert '单位：万元' in snapshot['parents'][1]['parent_text'] and '不含内部交易' in snapshot['parents'][1]['parent_text']


def test_cross_page_parent_preserves_each_original_locator():
    from credit_review.knowledge_base.pipeline import KnowledgeBaseBuilder
    result=KnowledgeBaseBuilder().build([
        {'type':'text','text':'本年营业收入100万元。由于其','page_idx':71},
        {'type':'text','text':'收入确认影响重大，因此列为关键审计事项。','page_idx':72},
        {'type':'text','text':'审计应对','text_level':1,'page_idx':72},
        {'type':'text','text':'核对合同。','page_idx':72},
    ])
    parent=result['parents'][0]
    assert '收入确认影响重大' in parent['parent_text']
    assert parent['source_locator']['page']==72
    assert parent['source_locator']['page_end']==73
    assert [s['page'] for s in parent['source_locator']['source_segments']]==[72,73]
    assert len(result['parents'])==3


def test_downloads_keep_human_selected_evidence_and_escape_csv_formulas():
    import csv
    from credit_review.workbench.exports import report_evidence,csv_report,evidence_text
    item={'fact_id':'F1','fact':'=伪造表格公式','status':'INSUFFICIENT_EVIDENCE','evidence_ids':['AI'],
          'evidence':[{'evidence_id':'AI'},{'evidence_id':'HUMAN'}],
          'human_decision':{'selected_evidence_ids':['HUMAN'],'final_text':'保留审查意见'}}
    assert {e['evidence_id'] for e in report_evidence(item)}=={'AI','HUMAN'}
    rows=list(csv.reader(io.StringIO(csv_report({'state':{'completed_results':[item]},'status':'COMPLETED'}).decode('utf-8-sig'))))
    assert rows[1][1].startswith("'=伪造") and 'HUMAN' in rows[1][5]
    assert evidence_text('<tr><td>营业收入</td><td>100</td></tr>')=='营业收入 | 100 |'
