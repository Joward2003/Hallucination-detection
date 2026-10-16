from credit_review.workbench.reporting import problem_explanations,triage_metrics
from credit_review.workbench.exports import html_report,report_evidence


def test_report_preserves_all_problem_explanations_and_disputes_with_own_evidence():
    item={'fact_id':'F1','fact':'收入增长，因此保证全部偿还。','status':'INSUFFICIENT_EVIDENCE','reason':'需结合证据复核。','issue_types':['overstatement'],'evidence_ids':['E1'],
          'evidence':[{'evidence_id':'E1','source':'公告','content':'存在不确定性','source_url':'/v1/documents/D1/original'},{'evidence_id':'E2','source':'财务资料','content':'未披露现金流','source_url':'/v1/documents/D2/original'}],
          'labeling_trace':{'candidate':{'decisions':[{'issue_type':'overstatement','present':True,'reason':'偿还保证超出披露的确定程度。','evidence_ids':['E1']},{'issue_type':'reasoning_gap','present':True,'reason':'收入增长不能直接证明偿债能力。','missing_requirement':'补充现金流及到期债务资料。','evidence_ids':['E2']}]},'adjudicator':{'decisions':[{'issue_type':'overstatement','present':True,'reason':'偿还保证超出披露的确定程度。','evidence_ids':['E1']}]},'disputes':['reasoning_gap']}}
    problems=problem_explanations(item)
    assert len(problems)==2 and problems[1]['needs_confirmation']
    assert {e['evidence_id'] for e in report_evidence(item)}=={'E1','E2'}
    record={'review_id':'R1','report_id':'report','status':'HUMAN_REVIEW_REQUIRED','kb_version':None,'state':{'original_input':item['fact'],'completed_results':[item]}}
    report=html_report(record).decode()
    assert '收入增长不能直接证明偿债能力。' in report and '补充现金流及到期债务资料。' in report
    assert '待确认：' in report and '<summary>辅助分类</summary>' in report
    assert item['issue_types']==['overstatement']


def test_identical_problem_explanations_are_not_repeated_for_each_label():
    decisions=[{'issue_type':kind,'present':True,'reason':'同一个业务问题','evidence_ids':['E1']} for kind in ['overstatement','reasoning_gap']]
    item={'issue_types':['overstatement','reasoning_gap'],'labeling_trace':{'adjudicator':{'decisions':decisions}}}
    rows=problem_explanations(item)
    assert len(rows)==1 and rows[0]['auxiliary_categories']==['overstatement','reasoning_gap']


def test_claim_recall_never_claims_complete_semantic_coverage_or_passes_model_failure():
    cases=[{'id':'error','gold_issue_types':['overstatement','reasoning_gap']},{'id':'clean','gold_issue_types':[]},{'id':'failed','gold_issue_types':[]}]
    rows=[{'id':'error','verdict':{'status':'SUPPORTED','issue_types':['overstatement']}},{'id':'clean','verdict':{'status':'SUPPORTED','issue_types':[]}},{'id':'failed','verdict':{'status':'SUPPORTED','issue_types':[],'labeling_status':'failed'}}]
    m=triage_metrics(cases,rows)
    assert m['problem_claim_recall']==1 and m['clean_pass_rate']==0.5
    assert m['execution_failure_claims']==['failed']
    assert m['report_problem_coverage']['status']=='NOT_REVIEWED'
