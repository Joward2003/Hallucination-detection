"""Reproducible real-model development evaluation; gold labels never enter prompts.

PYTHONPATH=src HF_HUB_OFFLINE=1 .venv/bin/python scripts/evaluate_web_review.py --data-dir PATH --output PATH
The given claim boundaries isolate retrieval/verification. This is not an end-to-end or blind benchmark.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dataclasses import replace
import hashlib
import json
from credit_review.workbench.storage import Store, now
from credit_review.workbench.knowledge import Knowledge, BoundRetriever
from credit_review.workbench.gateway import Gateway, load_settings
from credit_review.workbench.agents import Grader, Verifier, NumericValidator, Extractor
from credit_review.workbench.temporal import validated_policy
from credit_review.workbench.temporal import guard_verdict
from credit_review.workbench.numeric import reconcile_numeric_verdict

TYPES=['insufficient_evidence','citation_mismatch','overstatement','reasoning_gap','risk_omission']

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--retry-errors',action='store_true')
    parser.add_argument('--model',help='Temporary evaluation model; never updates workbench settings.')
    parser.add_argument('--recheck-numeric',action='store_true',help='Replay audited bindings through the current deterministic gates; preserve original predictions.')
    args=parser.parse_args()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    source=Path(__file__).resolve().parents[1]/'examples/web_review'
    gold=json.loads((source/'gold.json').read_text())
    config=load_settings()
    if args.model:config=replace(config,model=args.model)
    config_path=output/'run-configuration.json'
    previous_config=json.loads(config_path.read_text()) if config_path.exists() else (json.loads((output/'metrics.json').read_text()).get('model_configuration') if (output/'metrics.json').exists() else None)
    if previous_config and previous_config!=config.public():raise ValueError('结果目录使用了不同模型配置，请使用新目录，避免将缓存结果误标为新模型。')
    config_path.write_text(json.dumps(config.public(),ensure_ascii=False,indent=2))
    store=Store(args.data_dir)
    code_root=source.parents[1]/'src/credit_review'
    store.append(output.name,'evaluation_engine',{'configuration':config.public(),'source_hashes':{str(p.relative_to(code_root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in code_root.rglob('*.py')},'gold_sha256':hashlib.sha256((source/'gold.json').read_bytes()).hexdigest(),'gold_labels_sent_to_model':False,'recheck_numeric':args.recheck_numeric})
    with ThreadPoolExecutor(max_workers=1) as executor:
        knowledge=Knowledge(store,executor)
        pin=output/'sources.json'
        if pin.exists(): manifest=json.loads(pin.read_text())
        else:
            docs={}
            for url in gold['sources'].values():
                doc=knowledge.capture_url(url,job='EVAL-SOURCES')
                if doc['status']!='READY':raise RuntimeError(doc.get('error'))
                docs[url]=doc['document_id']
                print('captured',doc['company'],doc['published_at'],doc['parent_count'],flush=True)
            build=knowledge.create({'kb_id':'public-web-evaluation','name':'公开披露混合错误联调样本','document_ids':list(docs.values())},synchronous=True)
            if build['status']!='READY':raise RuntimeError(build.get('error'))
            manifest={'kb_version':build['version'],'citation_map':docs,'captured_at':now(),'documents':[store.get('document',d) for d in docs.values()]}
            pin.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
            print('embedded',build['child_count'],'children',flush=True)
        results_path=output/'predictions.json'
        prior=json.loads(results_path.read_text()) if results_path.exists() else []
        by_id={r['id']:r for r in prior}
        def evaluate(case):
            job=output.name+'-'+case['id']
            gateway=Gateway(store,job,config=config)
            policy=validated_policy(case['temporal_policy'])
            child={k:case[k] for k in ('fact','source_start','source_end','citation_urls')}
            child.update(fact_id=case['id'],importance='medium',citation_document_ids=[manifest['citation_map'][u] for u in case['citation_urls']])
            parent={'parent_id':case['id'],'parent_text':case['fact']}
            retriever=BoundRetriever(knowledge,manifest['kb_version'],{'allowed_document_ids':list(manifest['citation_map'].values())},job)
            try:
                # Identical production hybrid retriever, grader, verifier, temporal/numeric gates.
                query={'query_id':case['id'],'query_text':case['fact'],'retrieval_profile':'hybrid','citation_document_ids':child['citation_document_ids']}
                evidence=retriever.retrieve(query)
                assessments,status=Grader(gateway).grade(child,evidence)
                if status!='SUFFICIENT':
                    retry={**query,'query_id':case['id']+'-retry','query_text':case['fact']+' evidence risk financial results'}
                    extra=retriever.retrieve(retry)
                    evidence=list({e['evidence_id']:e for e in evidence+extra}.values())[:16]
                    assessments,status=Grader(gateway).grade(child,evidence)
                verifier=Verifier(gateway,policy,manifest['citation_map'])
                verdict=verifier.verify(child,parent,evidence,assessments,status)
                checks=NumericValidator(verifier).validate(child,evidence)
                verdict=reconcile_numeric_verdict(child,verdict,checks)
                result={'id':case['id'],'job':job,'child':child,'verdict':verdict,'numeric_specs':verifier.bindings.get(child['fact_id'],[]),'numeric_checks':checks,'evidence':evidence,'assessments':assessments,'audit_valid':store.verify(job)['valid']}
                store.append(job,'evaluation_prediction',result)
            except Exception as exc:
                result={'id':case['id'],'job':job,'error':str(exc),'error_type':type(exc).__name__}
                store.append(job,'evaluation_error',result)
            return result
        todo=[c for c in gold['cases'] if c['id'] not in by_id or args.retry_errors and by_id[c['id']].get('error')]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures={pool.submit(evaluate,c):c for c in todo}
            for future in as_completed(futures):
                row=future.result();by_id[row['id']]=row
                results_path.write_text(json.dumps(list(by_id.values()),ensure_ascii=False,indent=2))
                print(row['id'],row.get('error') or (row['verdict']['status'],row['verdict']['issue_types']),flush=True)
        if args.recheck_numeric:
            original_path=output/'predictions-before-deterministic-replay.json'
            if not original_path.exists():original_path.write_text(json.dumps(list(by_id.values()),ensure_ascii=False,indent=2))
            for case in gold['cases']:
                row=by_id[case['id']]
                if row.get('error'):continue
                verifier=Verifier(Gateway(store,row['job'],config=config),case['temporal_policy'],manifest['citation_map'])
                verifier.bindings[row['child']['fact_id']]=row.get('numeric_specs',[c for c in row['numeric_checks'] if c.get('kind')])
                checks=NumericValidator(verifier).validate(row['child'],row['evidence'])
                verdict=guard_verdict(row['verdict'],row['child'],row['evidence'],case['temporal_policy'],manifest['citation_map'])
                updated=reconcile_numeric_verdict(row['child'],verdict,checks)
                store.append(row['job'],'deterministic_replay',{'at':now(),'old_verdict':row['verdict'],'new_verdict':updated,'checks':checks,'note':'复用已记录的同一来源与模型操作数，不输入标准答案；没有重写原底稿。'})
                row.update(verdict=updated,numeric_checks=checks,deterministic_replay=True)
            results_path.write_text(json.dumps(list(by_id.values()),ensure_ascii=False,indent=2))
        rows=[by_id[c['id']] for c in gold['cases']]
        successful=[(c,r) for c,r in zip(gold['cases'],rows) if not r.get('error')]
        errors=[r for r in rows if r.get('error')]
        binary=sum(bool(c['gold_issue_types'])==(r['verdict']['status']!='SUPPORTED' or bool(r['verdict']['issue_types'])) for c,r in successful)
        metrics={'created_at':now(),'model_configuration':config.public(),'sample_count':len(rows),'completed':len(successful),'execution_errors':len(errors),'binary_correct':binary,'binary_accuracy_including_errors':binary/len(rows),'strict_label_exact_match':sum(set(c['gold_issue_types'])==set(r['verdict']['issue_types']) for c,r in successful),'limitations':gold['limitations'],'per_type':{}}
        for t in TYPES:
            tp=sum(t in c['gold_issue_types'] and t in r['verdict']['issue_types'] for c,r in successful)
            fp=sum(t not in c['gold_issue_types'] and t in r['verdict']['issue_types'] for c,r in successful)
            fn=sum(t in c['gold_issue_types'] and (bool(by_id[c['id']].get('error')) or t not in by_id[c['id']]['verdict']['issue_types']) for c in gold['cases'])
            metrics['per_type'][t]={'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None}
        metrics['positive_controls']={'count':sum(not c['gold_issue_types'] for c in gold['cases']),'passed':sum(not c['gold_issue_types'] and r['verdict']['status']=='SUPPORTED' and not r['verdict']['issue_types'] for c,r in successful)}
        metrics['primary_category_hits']=sum(set(c['gold_issue_types'])<=set(r['verdict']['issue_types']) if c['gold_issue_types'] else r['verdict']['status']=='SUPPORTED' and not r['verdict']['issue_types'] for c,r in successful)
        (output/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2))
        (output/'audit-integrity.json').write_text(json.dumps({r['job']:store.verify(r['job']) for r in rows},ensure_ascii=False,indent=2))
        print(json.dumps(metrics,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
