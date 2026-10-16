"""Five explicit issue decisions, proposed and independently adjudicated.

Verdict status, numerical conflicts and manual-routing diagnostics are separate
from the taxonomy. Low confidence never manufactures a risk-omission label.
"""
import re
from .agents import ask
from .reporting import problem_explanations

TAXONOMY={
 'insufficient_evidence':'缺少核验该结论所必需的外部材料。不能仅因系统转人工、低置信度或某个候选无关就打此标签。若唯一问题是已确认的引用/时间错配，不重复追加证据不足；必须另有独立资料缺口。',
 'citation_mismatch':'报告明确引用的来源与企业、期间或所引内容不对应。有证明错配的依据；网页打不开或日期未知本身不证明引错。',
 'overstatement':'原文将有限、有条件或不确定的依据表述为必然、保证或无风险，需指出过强的原文及合理限定。单纯陈述一个错误金额、引错来源或缺少推理依据不属于表述过强，不能将所有肯定陈述都当作绝对化。',
 'reasoning_gap':'报告从前提推出结论时缺少必要中间依据或因果关系，需明确缺少哪一步。单纯数值错误不算推理跳跃。',
 'risk_omission':'报告或当前风险清单遗漏外部证据中明确披露的重要风险，必须提供风险原文。不能由反向证据或重要程度直接推定。'}


class LabelingAgents:
    def __init__(self,gateway):self.gateway=gateway

    def classify(self,child,parent,verdict,evidence,assessments,numeric_checks,rule_hits):
        if child.get('review_kind')=='extraction_gap':
            return {**verdict,'issue_types':[],'primary_issue':None,'labeling_status':'unresolved_extraction','diagnostics':list(dict.fromkeys(verdict.get('diagnostics',[])+['extraction_gap']))}
        if verdict.get('numeric_reconciled') and verdict['status']=='SUPPORTED':
            return {**verdict,'issue_types':[],'primary_issue':None,'labeling_status':'verified_amount','labeling_trace':{'skip_reason':'单一金额的主体、时间、引用与全部操作数由程序核验一致。'}}
        known={e['evidence_id']:e for e in evidence}
        semantic={k:v for k,v in verdict.items() if k not in {'issue_types','primary_issue','labeling_trace','semantic_issue_proposals'}}
        risk_scope=child.get('review_kind')=='risk_omission' or bool(re.search(r'风险清单|风险识别|仅(?:识别|列)|风险监测',child['fact']))
        payload={'label_scope':{'risk_omission':risk_scope},'scope_boundary':('本点属于风险覆盖检查或显式风险清单，必须在当前节点评估遗漏，不得推迟给别的节点。报告只列X而证据明确披露重要风险Y时，可以判断遗漏；不要求来源提供完整的授信风险清单。前瞻性风险声明也可以是风险证据，其相关性和重要性须独立评估。' if risk_scope else '本点是普通业务结论，不打报告整体风险遗漏标签；风险扫描节点单独检查报告整体覆盖。'),'claim':child,'parent_context':parent['parent_text'],'verdict':semantic,'evidence':evidence,'assessments':assessments,'numeric_checks':numeric_checks,'business_rules':rule_hits,'taxonomy':TAXONOMY}
        schema='{"decisions":[{"issue_type":"分类标识","present":true,"claim_quote":"报告连续原文","reason":"满足或不满足哪个必要条件","evidence_ids":[],"evidence_quotes":[{"evidence_id":"...","quote":"连续逐字原文"}],"missing_requirement":"缺少的依据或风险"}],"primary_issue":null}'
        try:
            proposed=self._decision('你是问题复核智能体。优先找全有证据依据的实际问题，并用reason清楚说明问题与依据、missing_requirement说明还需核实什么；分类仅为辅助，不要求词句级问题定位，也不要为凑类别重复描述同一问题。对taxonomy五类逐一作出present布尔判断，恰好覆盖五类。可同时存在多类，但每类须独立满足定义，不能从verdict.status直接复制标签。只输出'+schema,payload)
            first=self._validate(proposed,child,parent,known,risk_scope=risk_scope)
            self.gateway.record('label_candidates',first)
            reviewed=self._decision('你是独立问题复核智能体。首先检查候选是否遗漏实际问题、是否误报，并确保reason可直接写入业务复核报告。分类仅为辅助。逐类重新核对taxonomy和证据，删除没有独立依据的标签，也可提出被遗漏的类别。候选智能体的意见不是事实。恰好覆盖五类，只输出'+schema,{**payload,'candidate_decisions':first})
            second=self._validate(reviewed,child,parent,known,risk_scope=risk_scope)
            accepted=[];disputes=[]
            for kind in TAXONOMY:
                a=next(d for d in first['decisions'] if d['issue_type']==kind);b=next(d for d in second['decisions'] if d['issue_type']==kind)
                if a['present'] and b['present']:
                    if kind=='risk_omission' and not b['evidence_quotes']:
                        disputes.append(kind);continue
                    accepted.append(kind)
                elif a['present']!=b['present']:disputes.append(kind)
            primary=second.get('primary_issue') if second.get('primary_issue') in accepted else first.get('primary_issue') if first.get('primary_issue') in accepted else (accepted[0] if accepted else None)
            result={**verdict,'issue_types':accepted,'primary_issue':primary,'labeling_status':'disputed' if disputes else 'adjudicated','labeling_trace':{'taxonomy_version':'credit-five-v2.1','candidate':first,'adjudicator':second,'disputes':disputes},'labeling_requires_human':bool(disputes)}
            if accepted and result['status']=='SUPPORTED':
                result.update(status='INSUFFICIENT_EVIDENCE',confidence='low',labeling_requires_human=True,reason='支持关系与标签复核存在分歧，须结合原材料人工确认。')
            result['problem_explanations']=problem_explanations(result)
            self.gateway.record('label_adjudication',result)
            return result
        except Exception as exc:
            self.gateway.record('labeling_failed',{'error':str(exc),'action':'保留支持关系和来源，不猜测错误类别，升级人工。'})
            return {**verdict,'issue_types':[],'primary_issue':None,'labeling_status':'failed','labeling_requires_human':True,'labeling_error':str(exc)}

    def _decision(self,task,payload):
        data=ask(self.gateway,task,payload)
        known={e['evidence_id']:e for e in payload['evidence']}
        try:self._validate(data,payload['claim'],{'parent_text':payload['parent_context']},known,risk_scope=payload['label_scope']['risk_omission'])
        except (ValueError,TypeError,AttributeError,KeyError) as exc:
            self.gateway.record('label_schema_retry',{'error':str(exc),'attempt_limit':1})
            data=ask(self.gateway,task+' 上次结构或引用未通过校验：'+str(exc)+'。仅使用已给出的证据标识和连续原文；每类都填写理由。修正后仍须满足原定义。',{**payload,'rejected_output':data})
        return data

    @staticmethod
    def _validate(data,child,parent,known,*,risk_scope=True):
        rows=data.get('decisions')
        if not isinstance(rows,list) or len(rows)!=len(TAXONOMY) or {d.get('issue_type') for d in rows}!=set(TAXONOMY):raise ValueError('标签智能体未逐类覆盖五类。')
        for row in rows:
            if row.get('issue_type')=='risk_omission' and row.get('present') and not risk_scope:
                row.update(present=False,scope_exclusion='当前是逐点结论；报告整体风险覆盖另行检查。')
            if row.get('present') is False:
                row.update(evidence_ids=[],evidence_quotes=[])
            if not isinstance(row.get('present'),bool):raise ValueError('标签present须为布尔值。')
            if not isinstance(row.get('reason'),str) or not row['reason'].strip():raise ValueError('标签缺少必要条件判断理由。')
            if not isinstance(row.get('evidence_ids'),list) or not set(row['evidence_ids'])<=set(known):raise ValueError('标签引用未知证据。')
            quotes=row.get('evidence_quotes') or []
            if not isinstance(quotes,list):raise ValueError('标签引用结构无效。')
            for quote in quotes:
                if quote.get('evidence_id') not in known or not quote.get('quote') or quote['quote'] not in known[quote['evidence_id']]['content']:raise ValueError('标签依据未逐字匹配原材料。')
            row['evidence_quotes']=quotes
            if row['present']:
                if row.get('claim_quote') and row['claim_quote'] not in child['fact'] and row['claim_quote'] not in parent['parent_text']:raise ValueError('标签没有报告原文定位。')
                if row['issue_type'] in {'overstatement','reasoning_gap'} and not row.get('claim_quote'):raise ValueError('推理/表述标签缺少原文。')
                if row['issue_type'] in {'insufficient_evidence','reasoning_gap','risk_omission'} and not row.get('missing_requirement'):raise ValueError('缺少证据、推理环节或遗漏风险说明。')
        return data
