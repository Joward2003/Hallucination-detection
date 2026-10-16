"""Isolate taxonomy changes on frozen, audited retrieval/verifier outputs.

Gold labels are read only after all model predictions; no new claims of RAG or
end-to-end accuracy can be inferred from this labeling-only development replay.
"""
import argparse,json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import replace
from credit_review.workbench.storage import Store,now
from credit_review.workbench.gateway import Gateway,load_settings
from credit_review.workbench.labeling import LabelingAgents,TAXONOMY
from credit_review.workbench.reporting import triage_metrics,problem_explanations

p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--gold',required=True);p.add_argument('--model',required=True);p.add_argument('--rescore-only',action='store_true',help='只重算已有预测的指标，不调用模型');args=p.parse_args()
out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
store=Store(out/'working-data');config=replace(load_settings(),model=args.model)
rows=json.loads(Path(args.input).read_text());cached=out/'predictions.json';results=json.loads(cached.read_text()) if cached.exists() else []
if args.rescore_only and not cached.exists():raise ValueError('重算指标需要已有 predictions.json。')
completed={r['id'] for r in results}
def run(row):
 ident=row['id'];gateway=Gateway(store,'LABEL-V2-'+ident,config=config)
 parent={'parent_id':ident,'parent_text':row['child']['fact']}
 verdict=LabelingAgents(gateway).classify(row['child'],parent,row['verdict'],row['evidence'],row['assessments'],row.get('numeric_checks',[]),[])
 return {'id':ident,'original_verdict':row['verdict'],'verdict':verdict,'audit':store.verify('LABEL-V2-'+ident)}
with ThreadPoolExecutor(max_workers=2) as e:
 futures=[e.submit(run,row) for row in rows if not args.rescore_only and row['id'] not in completed and not row.get('error')]
 for future in as_completed(futures):
  row=future.result();results.append(row);cached.write_text(json.dumps(results,ensure_ascii=False,indent=2));print(row['id'],row['verdict']['issue_types'],row['verdict']['labeling_status'],flush=True)
gold=json.loads(Path(args.gold).read_text());byid={r['id']:r for r in results}
metrics={'created_at':now(),'model_configuration':config.public(),'boundary':'在同一开发样本及冻结证据上只评估标签；未重新验证浏览器检索、Planning或报告抽取，不是盲测。事实/数值冲突另列，不属于五类标签。','sample_count':len(gold['cases']),'completed':len(results),'labeling_failures':sum(r['verdict']['labeling_status']=='failed' for r in results),'exact_five_label_sets':0,'per_type':{}}
for case in gold['cases']:
 if case['id'] in byid:
  expected=set(case['gold_issue_types'])&set(TAXONOMY);actual=set(byid[case['id']]['verdict']['issue_types'])
  if expected==actual:metrics['exact_five_label_sets']+=1
for kind in TAXONOMY:
 tp=fp=fn=0
 for c in gold['cases']:
  actual=kind in byid.get(c['id'],{}).get('verdict',{}).get('issue_types',[]);expected=kind in c['gold_issue_types']
  tp+=expected and actual;fp+=not expected and actual;fn+=expected and not actual
 metrics['per_type'][kind]={'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None}
metrics['evaluation_mode']='rescore_only_no_model_calls' if args.rescore_only else 'live_label_evaluation'
metrics['primary_focus']='有问题的复核点召回、正常项误报，以及报告问题解释的完整性；标签完全一致仅为辅助诊断。'
metrics['claim_triage']=triage_metrics(gold['cases'],results)
coverage=[]
for case in gold['cases']:
 row=byid.get(case['id'],{});verdict=row.get('verdict',{})
 coverage.append({'id':case['id'],'claim':case['fact'],'expected_problem_description':case['gold_reason'],'report_verdict_reason':verdict.get('reason'),'report_problem_explanations':problem_explanations(verdict),'coverage_status':'NOT_REVIEWED','missing_problems':[],'unsupported_report_problems':[],'reviewer':None,'boundary':'待逐项核对真实问题和证据，不能仅因某个标签命中就认定解释完整。'})
(out/'report-coverage-review.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2))
(out/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2));print(json.dumps(metrics,ensure_ascii=False,indent=2),flush=True)
