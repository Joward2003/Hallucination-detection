"""Web evidence, immutable snapshots, temporal and citation boundaries."""
import json
from unittest.mock import patch
from zipfile import ZipFile
from io import BytesIO
import pytest
from fastapi.testclient import TestClient
from credit_review.workbench.web_sources import canonical_url, report_urls, parse_html, fetch_public, period_labels
from credit_review.workbench.temporal import temporal_check, guard_verdict, claim_citations, validated_policy
from credit_review.workbench.source_views import snapshot_html
from credit_review.workbench.storage import Store
from credit_review.workbench.knowledge import Knowledge
from credit_review.workbench.exports import bundle
from credit_review.workbench.app import create_workbench_app

class Immediate:
    def submit(self,fn,*args): return fn(*args)

URL='https://example.com/results'
RAW=b'''<html><head><title>FY2025Q4 results</title><meta property="article:published_time" content="2025-07-30T12:00:00Z"><script>bad()</script></head><body><main><h1>FY2025Q4 results</h1><p>The quarter ended June 30, 2025.</p><p>Revenue was $76.4 billion. Our business faces competition and cybersecurity risks.</p><table onclick="bad()"><tr><th>Metric</th><th>2025</th><th>2024</th></tr><tr><td>Revenue</td><td>76.4</td><td>64.7</td></tr></table><img src="http://127.0.0.1/secret"><iframe src="https://evil.com"></iframe></main></body></html>'''

def fetched(raw=RAW):return {'final_url':URL,'content':raw,'content_type':'text/html','redirects':[]}

def evidence(**meta):
    return {'evidence_id':'E1','document_id':'D1','company_id':'Microsoft','temporal':{'published_at':'2025-07-30','data_period':'FY2025Q4','data_period_end':'2025-06-30',**meta}}


def test_parser_preserves_table_and_provenance_without_executable_html():
    blocks,meta=parse_html(RAW)
    assert meta['published_at']=='2025-07-30'
    assert meta['date_evidence']['published_at']['method']=='html_meta'
    assert meta['updated_at'] is None
    table=next(b for b in blocks if b['type']=='table')
    assert '<th>2024</th>' in table['text'] and 'onclick' not in table['text']
    assert meta['block_temporal'][table['id']]['ambiguous_period']
    paragraph=next(b for b in blocks if b['text'].startswith('Revenue was'))
    assert meta['block_temporal'][paragraph['id']]['data_period_end']=='2025-06-30'
    assert all('bad()' not in b['text'] and 'iframe' not in b['text'] for b in blocks)
    assert period_labels('2025财年第三季度 FY25Q4')==['FY2025Q3','FY2025Q4']


def test_fetch_time_and_last_modified_are_not_publication_dates(tmp_path):
    knowledge=Knowledge(Store(tmp_path),Immediate(),backend='lexical')
    raw=RAW.replace(b'<meta property="article:published_time" content="2025-07-30T12:00:00Z">',b'')
    doc=knowledge.capture_url(URL,fetcher=lambda _:dict(fetched(raw),last_modified_header='Wed, 30 Jul 2025 12:00:00 GMT'))
    assert doc['published_at'] is None and doc['fetched_at']
    assert doc['last_modified_header']
    result=temporal_check('FY2025Q4 Revenue',evidence(published_at=None,fetched_at='2026-10-16'),{'as_of':'2026-10-16'})
    assert not result['eligible'] and result['status']=='unknown'


def test_web_capture_versions_retrieval_and_offline_bundle(tmp_path):
    store=Store(tmp_path);knowledge=Knowledge(store,Immediate(),backend='lexical')
    first=knowledge.capture_url(URL,fetcher=lambda _:fetched(),job='WEB-1')
    same=knowledge.capture_url(URL,fetcher=lambda _:fetched(),job='WEB-2')
    assert first['document_id']==same['document_id']
    build=knowledge.create({'document_ids':[first['document_id']],'kb_id':'web'})
    version=build['version'];old_hash=store.get('build',version)['snapshot_sha256']
    updated=knowledge.capture_url(URL,fetcher=lambda _:fetched(RAW.replace(b'76.4',b'77.4')),job='WEB-3')
    assert updated['document_id']!=first['document_id']
    hits=knowledge.retrieve(version,{'query_text':'Revenue billion'})
    assert hits and all(h['source_type']=='web' for h in hits)
    hit=next(h for h in hits if '76.4 billion' in h['content'])
    assert hit['temporal']['data_period']=='FY2025Q4'
    assert hit['original_url']==URL and '/view#' in hit['source_url']
    assert store.get('build',version)['snapshot_sha256']==old_hash
    assert any('76.4' in h['content'] for h in knowledge.retrieve(version,{'query_text':'Revenue'}))
    rendered=snapshot_html(first,knowledge.parsed(first['document_id']),quote='Revenue was $76.4 billion.',keyword='competition')
    assert '<mark class="citation">Revenue was $76.4 billion.</mark>' in rendered
    assert '<mark class="keyword">competition</mark>' in rendered
    assert 'onclick' not in rendered and '<iframe' not in rendered and '<script' not in rendered
    archive=ZipFile(BytesIO(bundle(store,knowledge,'WEB-1')))
    assert 'snapshots/'+first['document_id']+'.html' in archive.namelist()
    assert archive.read('sources/'+first['document_id']+'.html')==RAW
    manifest=json.loads(archive.read('manifest.json'));assert manifest['audit']['valid']


@pytest.mark.parametrize('url',['https://user:secret@example.com/','file:///etc/passwd','http://example.com/','https://example.com:8000/'])
def test_invalid_source_urls(url):
    with pytest.raises(ValueError):canonical_url(url)


def test_ssrf_private_dns_is_rejected_before_request():
    with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
        with pytest.raises(ValueError,match='非公网'):fetch_public(URL)


def test_redirect_to_private_host_is_validated_again():
    class Response:
        status=302
        def getheader(self,name,*args):return 'https://localhost/secret' if name=='Location' else None
    class Connection:
        def __init__(self,*args,**kwargs):pass
        def request(self,*args,**kwargs):pass
        def getresponse(self):return Response()
        def close(self):pass
    public=[(2,1,6,'',('93.184.216.34',443))]
    private=[(2,1,6,'',('127.0.0.1',443))]
    with patch('http.client.HTTPSConnection',Connection),patch('socket.getaddrinfo',side_effect=[public,private]):
        with pytest.raises(ValueError,match='非公网'):fetch_public(URL)


def test_reference_mapping_uses_paragraph_footnote_and_strips_tracking():
    report='收入增加。[S1]\n\n另一段没有引用。\n\n[S1]: https://example.com/results?utm_source=ad#fragment'
    child={'fact':'收入增加','source_start':0,'source_end':5}
    assert claim_citations(child,report)==[URL]
    start=report.index('另一段')
    assert claim_citations({'fact':'另一段没有引用','source_start':start,'source_end':start+8},report)==[]
    assert report_urls('[来源](https://example.com/results)')==[URL]


@pytest.mark.parametrize('claim,meta,policy,status',[
    ('微软2025财年第四季度营业收入',{}, {'as_of':'2026-10-16'},'compatible'),
    ('微软2024财年第四季度营业收入',{}, {'as_of':'2026-10-16'},'period_mismatch'),
    ('微软2025财年第四季度营业收入',{}, {'as_of':'2025-07-29'},'after_cutoff'),
    ('微软2025财年第四季度营业收入',{'updated_at':'2026-08-19'}, {'as_of':'2025-08-01'},'after_cutoff'),
    ('微软2025财年第四季度营业收入',{'data_period':None}, {'as_of':'2026-10-16'},'unknown'),
    ('微软2025财年第四季度营业收入',{'ambiguous_period':True}, {'as_of':'2026-10-16'},'ambiguous'),
    ('微软营收',{'superseded_by':'D2'}, {'as_of':'2026-10-16'},'superseded'),
    ('微软目前经营情况',{}, {'as_of':'2026-10-16','mode':'current','max_age_days':90},'stale'),
    ('微软2025财年第四季度营业收入',{}, {'as_of':'2026-10-16','mode':'historical'},'compatible'),
    ('微软目前经营情况',{}, {'as_of':'2026-10-16','mode':'current'},'unknown'),
    ('生效担保',{'effective_from':'2026-11-01'}, {'as_of':'2026-10-16'},'not_effective'),
])
def test_time_policy_is_independent_of_retrieval_score(claim,meta,policy,status):
    result=temporal_check(claim,{**evidence(**meta),'score':999},policy)
    assert result['status']==status
    assert result['eligible']==(status=='compatible')


def test_citation_and_time_mismatch_do_not_invent_numeric_contradiction():
    verdict={'status':'SUPPORTED','confidence':'high','evidence_ids':['E1'],'issue_types':[],'reason':'same number'}
    child={'fact':'苹果2025财年第三季度营收940亿美元。','citation_urls':[URL]}
    checked=guard_verdict(verdict,child,[evidence()],{'as_of':'2026-10-16'},{URL:'D1'})
    assert checked['status']=='INSUFFICIENT_EVIDENCE'
    assert 'citation_mismatch' in checked['issue_types']
    assert checked['citation_checks'] and checked['temporal_checks']
    assert verdict['status']=='SUPPORTED'


def test_snapshot_api_csp_and_literal_keyword_highlight(tmp_path):
    app=create_workbench_app(tmp_path,backend='lexical')
    doc=app.state.knowledge.capture_url(URL,fetcher=lambda _:fetched())
    with TestClient(app) as client:
        response=client.get('/v1/documents/'+doc['document_id']+'/view',params={'keyword':'Revenue'})
        assert response.status_code==200
        assert "default-src 'none'" in response.headers['content-security-policy']
        assert '<mark class="keyword">Revenue</mark>' in response.text
        assert '<script' not in response.text
        original=client.get('/v1/documents/'+doc['document_id']+'/original')
        assert 'attachment' in original.headers['content-disposition']


def test_current_policy_rejects_invalid_window():
    with pytest.raises(ValueError):validated_policy({'as_of':'2026-10-16','max_age_days':0})


def test_bounded_json_retry_records_invalid_response_without_guessing(tmp_path):
    from credit_review.workbench.gateway import Gateway
    class Client:
        usage={'input_tokens':0,'output_tokens':0,'total_tokens':0}
        calls=[]
        def complete(self,system,user):
            self.calls.append((system,user))
            return 'not valid JSON' if len(self.calls)==1 else '{"ok":true}'
    gateway=Gateway(Store(tmp_path),'JSON-RETRY')
    gateway.client=Client()
    assert gateway.complete_json([{'role':'system','content':'JSON'},{'role':'user','content':'原始数据'}])=={'ok':True}
    assert len(gateway.client.calls)==2
    assert gateway.client.calls[0][1]==gateway.client.calls[1][1]=='原始数据'
    papers=gateway.store.papers('JSON-RETRY')
    assert any(p['stage']=='model_json_retry' for p in papers)
    assert len([p for p in papers if p['stage']=='model_response'])==2


def test_usd_binding_requires_same_currency_and_normalizes_bilingual_revenue():
    from credit_review.workbench.numeric import compute_check
    source={'evidence_id':'E1','content':'公司公布本季度营收达到 940 亿美元，同比增长 10%。', 'temporal':{'data_period':'FY2025Q3'}}
    fact='苹果2025财年第三季度营业收入为940亿美元。'
    spec={'kind':'amount','report_quote':fact,'expected':'940','unit':'亿美元','operands':{'current':{'value':'940','unit':'亿美元','metric':'本季度营收','period':'2025','evidence_id':'E1','quote':'本季度营收达到 940 亿美元'}}}
    assert compute_check(spec,fact,[source])['passed'] is True
    spec['unit']='亿元';spec['report_quote']='营业收入为940亿元。'
    assert compute_check(spec,spec['report_quote'],[source])['passed'] is None


def test_wrong_company_citation_is_flagged_even_without_model_support_ids():
    verdict={'status':'INSUFFICIENT_EVIDENCE','confidence':'low','evidence_ids':[],'issue_types':['insufficient_evidence']}
    child={'fact':'苹果2025财年第三季度营业收入为940亿美元。','citation_urls':[URL]}
    checked=guard_verdict(verdict,child,[evidence()],{'as_of':'2026-10-16'},{URL:'D1'})
    assert 'citation_mismatch' in checked['issue_types']
    assert checked['citation_checks']


def test_program_can_confirm_only_simple_fully_bound_amounts():
    from credit_review.workbench.numeric import reconcile_numeric_verdict
    child={'fact':'微软2025财年第四季度营业利润为343亿美元。'}
    verdict={'status':'CONTRADICTED','confidence':'high','issue_types':[],'evidence_ids':['E1'],'temporal_checks':[{'evidence_id':'E1','eligible':True,'source_company':'Microsoft'}]}
    checks=[{'kind':'amount','passed':True,'operands':{'current':{'evidence_id':'E1'}}}]
    assert reconcile_numeric_verdict(child,verdict,checks)['status']=='SUPPORTED'
    for change in [{'issue_types':['reasoning_gap']},{'citation_checks':[{'reason':'引用错配'}]},{'temporal_checks':[{'evidence_id':'E1','eligible':False,'source_company':'Microsoft'}]},{'temporal_checks':[{'evidence_id':'E1','eligible':True,'source_company':'Apple'}]}]:
        assert reconcile_numeric_verdict(child,{**verdict,**change},checks)['status']=='CONTRADICTED'
    assert reconcile_numeric_verdict({'fact':child['fact']+'因此不存在信贷风险。'},verdict,checks)['status']=='CONTRADICTED'


def test_publication_date_before_period_end_clause_never_becomes_data_date():
    raw=RAW.replace(b'The quarter ended June 30, 2025.',b'REDMOND, Wash. - July 30, 2025 - Results for the quarter ended June 30, 2025.')
    blocks,meta=parse_html(raw)
    revenue=next(b for b in blocks if b['text'].startswith('Revenue was'))
    t=meta['block_temporal'][revenue['id']]
    assert t['data_period_end']=='2025-06-30'
    assert 'quarter ended June 30' in t['data_period_end_evidence']


def test_uploaded_dates_remain_user_asserted_and_are_retrievable(tmp_path):
    app=create_workbench_app(tmp_path,backend='lexical')
    with TestClient(app) as client:
        response=client.post('/v1/documents',files={'file':('disclosure.txt','2024年营业收入为100万元。'.encode(),'text/plain')},data={'company':'甲公司','period':'2024','published_at':'2025-03-31','data_period_end':'2024-12-31'})
        assert response.status_code==200
        doc=response.json();assert doc['published_at']=='2025-03-31'
        assert doc['date_evidence']['published_at']['method']=='user_asserted_upload_metadata'
        parent=app.state.knowledge.parsed(doc['document_id'])['parents'][0]
        assert parent['temporal']['data_period_end']=='2024-12-31'
        assert parent['temporal']['data_period']=='2024'
        bad=client.post('/v1/documents',files={'file':('x.txt',b'a','text/plain')},data={'published_at':'2025-02-30'})
        assert bad.status_code==400


def test_reference_annotations_do_not_become_false_extraction_gaps():
    class Gateway:
        def complete_json(self,messages):return {'children':[{'fact':'收入为100万元。','source_quote':'收入为100万元。','importance':'low'}]}
        def record(self,*args):pass
    from credit_review.workbench.agents import Extractor
    report='[C01] 收入为100万元。 [S1]\n\n[S1]: https://example.com/results'
    groups=Extractor(Gateway()).extract(report)
    children=[c for g in groups for c in g['children']]
    assert len(children)==1 and children[0].get('review_kind')!='extraction_gap'
    assert report[children[0]['source_start']:children[0]['source_end']]=='收入为100万元。'


def test_url_only_review_pins_sources_without_executor_deadlock(tmp_path):
    from credit_review.workbench.reviews import Reviews
    class Queue:
        def submit(self,*args):pass
    store=Store(tmp_path);knowledge=Knowledge(store,Queue(),backend='lexical');reviews=Reviews(store,knowledge,Queue())
    original=knowledge.capture_url
    knowledge.capture_url=lambda url,**kwargs:original(url,fetcher=lambda _:fetched(),**kwargs)
    payload={'report_id':'web-only','report_version':'v1','tenant_id':'local','project_id':'test','requested_by':'tester','idempotency_key':'web-only','report_text':'FY2025Q4 Revenue was $76.4 billion. '+URL,'temporal_policy':{'as_of':'2026-10-16'}}
    record=reviews.create(payload)
    assert record['kb_version'] is None and not record['web_sources_prepared']
    prepared=reviews._capture_references(record)
    assert prepared['web_sources_prepared'] and prepared['kb_version']
    assert prepared['citation_map'][URL] in prepared['source_scope']['allowed_document_ids']
    assert knowledge.snapshot(prepared['kb_version'])['children']
    assert store.verify(record['review_id'])['valid']


def test_focused_snapshot_keeps_parent_context_and_full_snapshot_link(tmp_path):
    knowledge=Knowledge(Store(tmp_path),Immediate(),backend='lexical')
    doc=knowledge.capture_url(URL,fetcher=lambda _:fetched())
    snapshot=knowledge.parsed(doc['document_id']);parent=snapshot['parents'][2]
    rendered=snapshot_html(doc,snapshot,focus=parent['parent_id'],keyword='Revenue')
    assert parent['parent_text'] in rendered or 'class="keyword"' in rendered
    assert '查看完整保存快照' in rendered
    assert rendered.count('<section id=')<=3
    with pytest.raises(ValueError):snapshot_html(doc,snapshot,focus='missing')
