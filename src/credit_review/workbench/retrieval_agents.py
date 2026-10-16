"""Explicit format routing followed by an evidence-aware LLM query planner."""
import re
from urllib.parse import urlsplit
from .agents import Planner, ask
from .temporal import ENTITY_ALIASES
from credit_review.agents.planning_agent import validate_retrieval_plan,KNOWN_METRIC_IDS


class SourceRouter:
    def route(self,child,parent,company,evidence):
        mentioned=[name for name,aliases in ENTITY_ALIASES.items() if any(a.lower() in child['fact'].lower() for a in aliases)]
        subjects=mentioned or ([child['entity_name']] if child.get('entity_name') else [])
        if not subjects and company and company.get('company_name') and company['company_name'] in child['fact']:subjects=[company['company_name']]
        numeric=bool(re.search(r'\d.*(?:元|%|倍)|收入|利润|债务|资产|负债|现金流',child['fact']))
        routes=['table','text'] if numeric else ['text']
        formats=list(dict.fromkeys('pdf' if urlsplit(u).path.lower().endswith('.pdf') else 'html' for u in child.get('citation_urls',[])))
        routes=formats+routes
        return {'entities':subjects,'routes':routes,'preferred_domains':list(dict.fromkeys(urlsplit(u).hostname for u in child.get('citation_urls',[]) if urlsplit(u).hostname)),'claim_period':'按当前结论，不能继承整份报告中其他企业或期间','version':'credit-source-router-v2'}


class EvidenceQueryPlanner(Planner):
    accepts_context=True
    def build_plan(self,child,parent,company,*,attempt=0,missing_needs=None,entity_profile=None,context=None):
        context=context or {};routing=context.get('routing_decision') or {}
        prior=[{'evidence_id':e['evidence_id'],'source':e['source'],'company':e.get('company_id'),'period':e.get('temporal',{}).get('data_period'),'content_excerpt':e['content'][:600]} for e in context.get('evidence',[])[:8]]
        payload={'claim':child,'parent_context':parent['parent_text'],'extracted_entities':routing.get('entities',[]),'source_routes':routing.get('routes',['text','table','html']),'known_candidates':prior,'assessment_feedback':context.get('assessments',[]),'missing_needs':missing_needs or [],'attempt':attempt,'preferred_domains':routing.get('preferred_domains',[]),'boundary':'候选摘录仅为规划上下文，不作为最终核验依据。只发送短检索词给公开搜索。'}
        fallback=self._fallback_plan(child,parent,company,attempt=attempt,missing_needs=missing_needs,entity_profile=entity_profile)
        payload['allowed_values']={'source_route':['text','table','html','pdf'],'retrieval_type':['text','table'],'retrieval_profile':['atomic_text','financial_table'],'metric_ids':sorted(KNOWN_METRIC_IDS)}
        try:
            data=ask(self.gateway,'你是证据检索规划智能体。基于当前主体、待核结论、材料类型和上一轮证据缺口生成最多2组检索词；可用中英文同义词。不要把报告中的结论当成检索前提，避免只搜相同数字。输出 {"entity":"主体","requests":[{"query_text":"本地知识库查询","web_query":"企业 年份 指标 原始公告等短公开检索词","source_route":"html","retrieval_type":"text","retrieval_profile":"atomic_text","metric_ids":[],"periods":[],"preferred_domains":[]}]}。每个枚举字段只能填写allowed_values中的一个值，禁止用竖线拼接多个值。metric_ids不确定时留空，不得创造注册表之外的标识。有引用时优先核查原引用，也寻找独立材料；第二轮必须针对已知缺口或冲突调整。',payload)
            for repair_attempt in range(2):
                try:
                    requests=self._normalize_requests(data.get('requests') or [],child,company,attempt)[:2]
                    if not requests:raise ValueError('LLM未生成检索请求。')
                    for request in requests:
                        route=request.get('source_route','text')
                        if route not in {'text','table','html','pdf'}:raise ValueError('未知来源路由。')
                        web=request.get('web_query','')
                        if not isinstance(web,str) or len(web)>400:raise ValueError('公开检索词超出预算。')
                        domains=request.get('preferred_domains') or []
                        request['preferred_domains']=[d for d in domains if isinstance(d,str) and re.fullmatch(r'[a-zA-Z0-9.-]{3,150}',d)]
                        request['citation_document_ids']=child.get('citation_document_ids',[])
                    plan={**fallback,'requests':requests,'attempt':attempt,'entity':data.get('entity'),'routing_decision':routing,'planner_version':'evidence-aware-llm-v2'}
                    validate_retrieval_plan(plan)
                    break
                except (ValueError,TypeError,KeyError,AttributeError) as exc:
                    if repair_attempt:raise
                    self.gateway.record('llm_search_plan_schema_retry',{'error':str(exc),'attempt_limit':1})
                    data=ask(self.gateway,'修复检索规划 JSON。每个枚举必须取 allowed_values 中一个值，不能含竖线。最多2条请求，只用已注册指标，不确定时metric_ids为空。输出entity与requests；每条有query_text、web_query、source_route、retrieval_type、retrieval_profile、metric_ids、periods。上次失败：'+str(exc),{**payload,'rejected_output':data})
            self.gateway.record('llm_search_plan',{'input':payload,'plan':plan})
            return plan
        except Exception as exc:
            # A fallback query is allowed; a synthetic source or verdict is not.
            fallback['requests']=fallback['requests'][:2]
            for request in fallback['requests']:
                request['source_route']='table' if request.get('retrieval_type')=='table' else 'text'
                request['citation_document_ids']=child.get('citation_document_ids',[])
                subjects=routing.get('entities') or []
                if subjects:
                    years=' '.join(dict.fromkeys(re.findall(r'20\d{2}',child['fact'])))
                    request['web_query']=' '.join(subjects)+' '+years+' financial results risk disclosure'
            self.gateway.record('llm_search_plan_failed',{'error':str(exc),'fallback_plan':fallback})
            return fallback
