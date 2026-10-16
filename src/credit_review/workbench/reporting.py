"""Readable problem explanations; categories are auxiliary, source audits remain intact."""
import re


def problem_explanations(item):
    """Retain disputed findings explicitly without turning them into confirmed errors."""
    trace=item.get('labeling_trace') or {}
    candidate={r['issue_type']:r for r in trace.get('candidate',{}).get('decisions',[]) if r.get('present')}
    adjudicator={r['issue_type']:r for r in trace.get('adjudicator',{}).get('decisions',[]) if r.get('present')}
    accepted=list(item.get('issue_types') or [])
    disputed=list(trace.get('disputes') or [])
    rows=[]
    for kind in dict.fromkeys(accepted+disputed):
        decision=adjudicator.get(kind) or candidate.get(kind)
        if not decision:continue
        reason=decision.get('reason','').strip()
        follow_up=decision.get('missing_requirement','').strip()
        if reason:
            rows.append({'description':reason,'follow_up':follow_up,'needs_confirmation':kind in disputed,
                         'evidence_ids':list(dict.fromkeys((decision.get('evidence_ids') or [])+[q['evidence_id'] for q in decision.get('evidence_quotes',[]) if q.get('evidence_id')])),'auxiliary_categories':[kind]})
    for check in item.get('numeric_checks',[]):
        if check.get('passed') is False:
            description='报告数值为'+str(check.get('expected'))+'，原材料核算值为'+str(check.get('observed'))+'（'+str(check.get('unit') or '单位见底稿')+'），程序校验未通过。'
            operands=check.get('operands') or {}
            ids=list(dict.fromkeys(v['evidence_id'] for v in (operands.values() if isinstance(operands,dict) else []) if isinstance(v,dict) and v.get('evidence_id')))
            rows.append({'description':description,'follow_up':'核对单位、期间与计算口径，并修订报告数值。','needs_confirmation':False,'evidence_ids':ids,'auxiliary_categories':['fact_mismatch']})
    if not rows and item.get('reason') and (accepted or item.get('status')=='CONTRADICTED'):
        rows.append({'description':item['reason'],'follow_up':'','needs_confirmation':False,'evidence_ids':item.get('evidence_ids',[]),'auxiliary_categories':accepted})
    # The same explanation may have several labels; show its text once.
    merged={}
    for row in rows:
        key=(re.sub(r'\s+','',row['description']),row['needs_confirmation'])
        if key in merged:
            existing=merged[key]
            for field in ('auxiliary_categories','evidence_ids'):existing[field]=list(dict.fromkeys(existing[field]+row[field]))
            if row['follow_up'] and row['follow_up'] not in existing['follow_up']:existing['follow_up']='；'.join(filter(None,[existing['follow_up'],row['follow_up']]))
        else:merged[key]=row
    return list(merged.values())


def triage_metrics(cases,predictions):
    """Claim routing is measurable automatically; semantic problem coverage is not."""
    by_id={row['id']:row for row in predictions}
    positives=[c for c in cases if c['gold_issue_types']]
    clean=[c for c in cases if not c['gold_issue_types']]
    failures=[];flagged={}
    for case in cases:
        row=by_id.get(case['id'],{});v=row.get('verdict',{})
        failed=not v or bool(row.get('error')) or v.get('labeling_status') in {'failed','unresolved_extraction'}
        if failed:failures.append(case['id']);continue
        flagged[case['id']]=bool(v.get('issue_types')) or v.get('status') in {'CONTRADICTED','INSUFFICIENT_EVIDENCE'} or bool(v.get('labeling_requires_human'))
    hit=[c['id'] for c in positives if flagged.get(c['id']) is True]
    missed=[c['id'] for c in positives if flagged.get(c['id']) is not True]
    false_alarms=[c['id'] for c in clean if flagged.get(c['id']) is True]
    passed=[c['id'] for c in clean if flagged.get(c['id']) is False]
    return {'problem_claim_count':len(positives),'problem_claims_flagged':len(hit),'problem_claim_recall':len(hit)/len(positives) if positives else None,
            'missed_or_failed_problem_claims':missed,'clean_claim_count':len(clean),'clean_claims_passed':len(passed),'clean_pass_rate':len(passed)/len(clean) if clean else None,
            'false_alarm_claims':false_alarms,'execution_failure_claims':failures,
            'report_problem_coverage':{'status':'NOT_REVIEWED','reason':'结论级命中不等于其中每个具体问题均被识别；须逐项比较标准问题描述、报告解释与证据，未自动授予完整覆盖得分。'}}
