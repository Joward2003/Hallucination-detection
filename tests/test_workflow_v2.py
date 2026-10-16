"""Actual workflow boundaries: queue, contextual planning, independent labels, originals."""
import json
from types import SimpleNamespace
import pytest
from credit_review.workbench.storage import Store
from credit_review.workbench.knowledge import Knowledge
from credit_review.workbench.reviews import Reviews
from credit_review.workbench.labeling import LabelingAgents,TAXONOMY
from credit_review.workbench.retrieval_agents import SourceRouter,EvidenceQueryPlanner
from credit_review.workbench.numeric import NumericValidator
from credit_review.workbench.agents import WorkbenchRiskPolicy
from credit_review.workbench.original_web import ensure_original,original_html,SCRIPT,CSP,asset_path
from credit_review.workbench.browser_search import public_search
from credit_review.graph.builder import default_services,build_review_graph
from credit_review.domain.errors import ConflictError
from bs4 import BeautifulSoup

class Immediate:
 def submit(self,fn,*args):return fn(*args)
class Gateway:
 def __init__(self,replies):self.replies=iter(replies);self.events=[];self.messages=[]
 def complete_json(self,messages):self.messages.append(messages);return next(self.replies)
 def record(self,stage,body):self.events.append((stage,body))

def decisions(present=()):
 return {'decisions':[{'issue_type':kind,'present':kind in present,'claim_quote':'保证全部回收' if kind in present else '', 'reason':'有独立依据' if kind in present else '不满足必要条件','evidence_ids':['E1'] if kind in present else [],'evidence_quotes':[{'evidence_id':'E1','quote':'可能损失'}] if kind in present else [],'missing_requirement':'未说明约束条件' if kind in present else ''} for kind in TAXONOMY],'primary_issue':next(iter(present),None)}

def test_status_does_not_force_insufficient_or_risk_labels():
 g=Gateway([decisions(['overstatement']),decisions(['overstatement'])])
 child={'fact':'保证全部回收','fact_id':'F1'}
 result=LabelingAgents(g).classify(child,{'parent_text':child['fact']},{'status':'INSUFFICIENT_EVIDENCE','issue_types':['insufficient_evidence','risk_omission'],'confidence':'low'},[{'evidence_id':'E1','content':'可能损失'}],[],[],[])
 assert result['issue_types']==['overstatement'] and result['primary_issue']=='overstatement'
 payload=json.loads(g.messages[0][1]['content']);assert 'issue_types' not in payload['verdict']
 assert [stage for stage,_ in g.events]==['label_candidates','label_adjudication']


def test_agent_disagreement_routes_human_without_inventing_label():
 result=LabelingAgents(Gateway([decisions(['risk_omission']),decisions([])])).classify({'fact':'保证全部回收','review_kind':'risk_omission'},{'parent_text':'保证全部回收'},{'status':'INSUFFICIENT_EVIDENCE'},[{'evidence_id':'E1','content':'可能损失'}],[],[],[])
 assert result['issue_types']==[] and result['labeling_requires_human']
 assert result['labeling_trace']['disputes']==['risk_omission']


def test_fabricated_label_quote_is_not_accepted():
 data=decisions(['risk_omission']);data['decisions'][-1]['evidence_quotes'][0]['quote']='来源不存在的风险'
 r=LabelingAgents(Gateway([data])).classify({'fact':'保证全部回收','review_kind':'risk_omission'},{'parent_text':'保证全部回收'},{'status':'INSUFFICIENT_EVIDENCE'},[{'evidence_id':'E1','content':'可能损失'}],[],[],[])
 assert r['labeling_status']=='failed' and r['issue_types']==[] and r['labeling_requires_human']


def test_routing_and_planner_receive_current_entity_and_previous_evidence():
 child={'fact_id':'F1','fact':'微软2025财年第四季度营业收入764亿美元。','citation_urls':['https://www.microsoft.com/results'],'citation_document_ids':['D1']}
 parent={'parent_id':'P1','parent_text':'苹果与微软均需复核。'}
 route=SourceRouter().route(child,parent,{'company_name':'Apple'},[])
 assert route['entities']==['Microsoft']
 g=Gateway([{'entity':'Microsoft','requests':[{'query_text':'Microsoft FY2025 revenue','web_query':'Microsoft FY2025 earnings official','source_route':'html','retrieval_type':'text','retrieval_profile':'atomic_text','metric_ids':[],'periods':[]}]}])
 plan=EvidenceQueryPlanner(g).build_plan(child,parent,{},attempt=1,missing_needs=['cash-flow'],context={'routing_decision':route,'evidence':[{'evidence_id':'E1','source':'2024年报','content':'过去期间数据'}],'assessments':[{'evidence_id':'E1','relation':'IRRELEVANT'}]})
 payload=json.loads(g.messages[0][1]['content'])
 assert payload['extracted_entities']==['Microsoft'] and payload['known_candidates'][0]['evidence_id']=='E1'
 assert payload['missing_needs']==['cash-flow'] and plan['requests'][0]['source_route']=='html'
 assert plan['requests'][0]['citation_document_ids']==['D1']


def test_all_points_are_prechecked_before_queued_human_decisions(tmp_path):
 evidence=[{'evidence_id':'E1','content':'资料无法证明两个结论。','source':'原材料','page':1,'evidence_type':'text'}]
 services=default_services(evidence=evidence,retrieval_backend='deterministic')
 class Extractor:
  def extract(self,text):return [{'parent':{'parent_id':'P1','parent_text':text,'source_start':0,'source_end':len(text)},'children':[{'fact_id':'F1','parent_id':'P1','fact':'结论甲。','source_start':0,'source_end':4,'importance':'high'},{'fact_id':'F2','parent_id':'P1','fact':'结论乙。','source_start':4,'source_end':8,'importance':'high'}]}]
 class Verifier:
  def verify(self,*args):return {'status':'INSUFFICIENT_EVIDENCE','confidence':'low','reason':'缺少原材料','evidence_ids':[],'issue_types':[]}
 services.extractor=Extractor();services.verifier=Verifier();services.max_retry=0;services.defer_human_review=True;services.risk_policy=WorkbenchRiskPolicy()
 state=build_review_graph(services).invoke({'original_input':'结论甲。结论乙。'})
 assert len(state['completed_results'])==2 and len(state['human_tasks'])==2
 assert state['workflow_status']=='HUMAN_REVIEW_REQUIRED' and state.get('human_task') is None
 store=Store(tmp_path);knowledge=Knowledge(store,Immediate(),backend='lexical');reviews=Reviews(store,knowledge,Immediate())
 store.save('review','R1',{'review_id':'R1','workflow_version':2,'status':state['workflow_status'],'state':state})
 d={'fact_id':'F2','task_version':1,'decision':'INSUFFICIENT_EVIDENCE','comment':'复核第二项材料不足','decided_by':'测试复核人','selected_evidence_ids':[]}
 record=reviews.submit_human_decision('R1',d)
 assert record['status']=='HUMAN_REVIEW_REQUIRED' and len(reviews.human_tasks())==1
 with pytest.raises(ConflictError):reviews.submit_human_decision('R1',d)
 record=reviews.submit_human_decision('R1',{**d,'fact_id':'F1'})
 assert record['status']=='COMPLETED' and not reviews.human_tasks()
 assert store.verify('R1')['valid']


def test_original_dom_preserves_layout_and_blocks_source_scripts(tmp_path):
 raw=b'''<html><head><title>FY2025Q4</title><link rel="stylesheet" href="/site.css"><script>steal()</script></head><body><header>Website masthead</header><main id="original-main" class="original-layout"><h1 id="original-heading">FY2025Q4</h1><p>Revenue was $76.4 billion. This paragraph has the original page content and financial statement.</p><p onmouseover="steal()">Risk disclosure may lead to losses and financial uncertainty.</p></main></body></html>'''
 k=Knowledge(Store(tmp_path),Immediate(),backend='lexical')
 doc=k.capture_url('https://example.com/results',fetcher=lambda u:{'final_url':u,'content':raw,'content_type':'text/html','redirects':[]})
 calls=[]
 def css(url,**kwargs):calls.append(url);return {'content':b'.original-layout{max-width:900px;color:navy}','content_type':'text/css'}
 page,manifest=ensure_original(k,doc['document_id'],fetcher=css)
 assert BeautifulSoup(page,'html.parser').find(id='original-heading') is not None
 assert 'Website masthead' in page and 'original-layout' in page and 'steal()' not in page
 assert calls==['https://example.com/site.css'] and len(manifest['targets'])>=2
 rendered=original_html(k,doc['document_id'],quote='Revenue was $76.4 billion.',keyword='</script><script>bad()</script>',parent='P0002')
 soup=BeautifulSoup(rendered,'html.parser');scripts=soup.find_all('script')
 assert len(scripts)==2 and scripts[-1].string==SCRIPT
 assert "script-src 'sha256-" in CSP and "connect-src 'none'" in CSP
 assert 'bad()' not in str(soup.find_all('script')[-1])
 asset=next(iter(manifest['assets'].values()));path,mime=asset_path(k,doc['document_id'],asset['name']);assert mime=='text/css'
 path.write_bytes(b'changed')
 with pytest.raises(ValueError):asset_path(k,doc['document_id'],asset['name'])


def test_search_snippets_are_discovery_only_and_bad_results_fall_back():
 def fetch(url,**kwargs):
  if 'format=rss' in url:return {'content':b'<rss><channel><item><title>Microsoft account login</title><link>https://account.microsoft.com/</link></item></channel></rss>','content_type':'application/xml'}
  return {'content':b'<html><li class="b_algo"><h2><a href="https://example.com/results">FY2025 Revenue results</a></h2></li></html>','content_type':'text/html'}
 r=public_search('Microsoft FY2025 revenue',fetcher=fetch)
 assert r['provider']=='bing_html' and r['results'][0]['url']=='https://example.com/results'
 assert r['failures'] and '证据' in r['failures'][0]['error']


def test_program_uses_actual_report_amount_and_preserves_model_error():
 fact='微软2025财年第四季度营业利润为343亿美元。'
 spec={'kind':'amount','expected':'34.3','unit':'十亿美元','report_quote':'343亿美元','operands':{'current':{'value':'34.3','unit':'十亿美元','metric':'Operating income','period':'2025','evidence_id':'E1','quote':'Operating income was $34.3 billion and increased 23%'}}}
 source={'evidence_id':'E1','content':'Operating income was $34.3 billion and increased 23%','temporal':{'data_period':'FY2025Q4','published_at':'2025-07-30'}}
 v=SimpleNamespace(bindings={'F1':[spec]},temporal_policy={'as_of':'2026-10-16'})
 checks=NumericValidator(v).validate({'fact_id':'F1','fact':fact},[source])
 assert checks[0]['passed'] is True and checks[0]['expected']=='343' and checks[0]['unit']=='亿美元'
 assert checks[0]['model_report_binding']['expected']=='34.3'
 v.bindings['F1'][0]['operands']['current']['value']='invalid'
 assert NumericValidator(v).validate({'fact_id':'F1','fact':fact},[source])[0]['passed'] is None


def test_risk_coverage_quote_failure_preserves_report_precheck_and_manual_gap():
 from credit_review.workbench.reviews import RiskCoverageExtractor
 extractor=SimpleNamespace(extract=lambda text:[{'parent':{'parent_id':'P1','parent_text':text},'children':[{'fact_id':'F1','fact':text,'source_start':0,'source_end':len(text)}]}])
 retriever=SimpleNamespace(retrieve=lambda query:[{'evidence_id':'E1','content':'Actual source risk disclosure.'}])
 gateway=Gateway([{'omissions':[{'risk':'invented','quote':'not in source','evidence_id':'E1'}]}])
 groups=RiskCoverageExtractor(extractor,retriever,gateway).extract('营业收入增长。')
 assert groups[0]['children'][0]['fact_id']=='F1'
 assert groups[-1]['children'][0]['gap_kind']=='risk_coverage'
 assert groups[-1]['children'][0]['review_kind']=='extraction_gap'
 assert not any(c.get('review_kind')=='risk_omission' for group in groups for c in group['children'])
 assert any(stage=='risk_coverage_candidate_rejected' for stage,_ in gateway.events)


def test_ordinary_fact_does_not_inherit_report_level_risk_omission():
 g=Gateway([decisions(['risk_omission']),decisions(['risk_omission'])])
 result=LabelingAgents(g).classify({'fact':'保证全部回收'},{'parent_text':'保证全部回收'},{'status':'INSUFFICIENT_EVIDENCE'},[{'evidence_id':'E1','content':'可能损失'}],[],[],[])
 assert result['issue_types']==[]
 assert result['labeling_trace']['candidate']['decisions'][-1]['scope_exclusion']


def test_numbered_references_and_list_markers_do_not_create_false_review_items():
 from credit_review.workbench.agents import Extractor
 g=Gateway([{'children':[{'fact':'收入为100万元。','source_quote':'收入为100万元。','importance':'low'},{'fact':'利润为10万元。','source_quote':'利润为10万元。','importance':'low'}]}])
 text='一、收入为100万元。[1]\n二、利润为10万元。[1]\n参考资料：[1] https://example.com/results'
 children=[c for group in Extractor(g).extract(text) for c in group['children']]
 assert len(children)==2 and all(c.get('review_kind')!='extraction_gap' for c in children)
 assert all(text[c['source_start']:c['source_end']]==c['source_quote'] for c in children)


def test_citations_never_borrow_next_companys_link_without_blank_lines():
 from credit_review.workbench.temporal import claim_citations
 report='微软收入764亿美元。[1]\n苹果收入940亿美元。[2]\n[1]: https://example.com/msft\n[2]: https://example.com/apple'
 first={'fact':'微软收入764亿美元','source_start':0,'source_end':10}
 second_start=report.index('苹果')
 second={'fact':'苹果收入940亿美元','source_start':second_start,'source_end':second_start+10}
 assert claim_citations(first,report)==['https://example.com/msft']
 assert claim_citations(second,report)==['https://example.com/apple']


def test_planner_repairs_model_enum_lists_before_executing_queries():
 bad={'entity':'Microsoft','requests':[{'query_text':'revenue','retrieval_type':'text|table','source_route':'html|pdf','retrieval_profile':'atomic_text|financial_table'}]}
 good={'entity':'Microsoft','requests':[{'query_text':'Microsoft revenue','web_query':'Microsoft FY2025 earnings','source_route':'html','retrieval_type':'text','retrieval_profile':'atomic_text','metric_ids':['revenue']}]}
 g=Gateway([bad,good]);child={'fact_id':'F1','fact':'微软2025财年营业收入需复核。'}
 plan=EvidenceQueryPlanner(g).build_plan(child,{'parent_text':child['fact']},{},context={'routing_decision':{'entities':['Microsoft']}})
 assert plan['requests'][0]['source_route']=='html'
 assert [stage for stage,_ in g.events]==['llm_search_plan_schema_retry','llm_search_plan']
 assert len(g.messages)==2
