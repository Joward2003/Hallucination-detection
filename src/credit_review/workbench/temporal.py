"""Auditable time compatibility, separate from semantic support and fetch time."""
from __future__ import annotations
import re
from datetime import date
from .web_sources import period_labels, dates_in, canonical_url, report_urls

POLICY_VERSION = 'temporal-v1'
ENTITY_ALIASES = {'Microsoft': ('微软','Microsoft','MSFT'), 'Apple': ('苹果','Apple','AAPL')}


def validated_policy(payload=None):
    result = dict(payload or {})
    for field in ('as_of', 'data_period_start', 'data_period_end'):
        if result.get(field): date.fromisoformat(result[field])
    mode = result.setdefault('mode', 'historical')
    if mode not in {'historical','current'}: raise ValueError('时间策略须为 historical 或 current。')
    days = result.get('max_age_days')
    if days is not None and (not isinstance(days,int) or not 1 <= days <= 3660):
        raise ValueError('资料有效天数须为1至3660；历史数据不按抓取时间失效。')
    result['version'] = POLICY_VERSION
    return result


def target_period(claim, policy):
    labels = period_labels(claim)
    if len(labels)==1: return labels[0]
    years = re.findall(r'(20\d{2})\s*(?:财年|年度|年)', claim)
    if len(set(years))==1: return 'FY'+years[0] if '财年' in claim else years[0]
    return policy.get('data_period')


def claim_citations(child, report):
    definitions = {m[1]:canonical_url(m[2]) for m in re.finditer(r'\[([A-Za-z0-9_-]{1,20})\]\s*[:：]?\s*(https://[^\s<>]+)', report)}
    start, end = child.get('source_start',0), child.get('source_end',0)
    # Citation markers following this sentence belong to its own line. A
    # report need not contain blank lines; borrowing the next claim's URLs
    # would silently turn a wrong citation into the right company's evidence.
    paragraph_start = report.rfind('\n',0,start)+1
    paragraph_end = report.find('\n',end)
    paragraph = report[paragraph_start:paragraph_end if paragraph_end>=0 else len(report)]
    urls = report_urls(child.get('source_quote') or child['fact']) + report_urls(paragraph)
    for label in re.findall(r'\[([A-Za-z0-9_-]{1,20})\]', paragraph):
        if label in definitions: urls.append(definitions[label])
    return list(dict.fromkeys(urls))


def temporal_check(claim, evidence, policy=None):
    policy = validated_policy(policy)
    explicit_cutoff=re.search(r'以\s*(20\d{2}-\d{2}-\d{2})\s*为信息截止日',claim)
    if explicit_cutoff:
        date.fromisoformat(explicit_cutoff[1])
        policy['as_of']=min(policy.get('as_of') or explicit_cutoff[1],explicit_cutoff[1])
    meta = evidence.get('temporal') or {}
    target = target_period(claim, policy)
    result = {'evidence_id':evidence['evidence_id'], 'policy_version':POLICY_VERSION,
              'source_company':evidence.get('company_id'),
              'target_period':target, 'as_of':policy.get('as_of'), 'source_temporal':meta,
              'status':'compatible', 'reasons':[], 'eligible':True}
    def flag(status, reason):
        result.update(status=status, eligible=False)
        result['reasons'].append(reason)
    as_of = policy.get('as_of')
    published = meta.get('published_at')
    if as_of:
        if not published: flag('unknown', '发布时间未知，无法确认信息截止日前可知。')
        elif published[:10] > as_of: flag('after_cutoff', '资料发布于报告信息截止日之后。')
        if meta.get('updated_at') and meta['updated_at'][:10] > as_of:
            flag('after_cutoff', '当前快照在截止日之后更新，缺少当时历史版本。')
    if meta.get('superseded_by'): flag('superseded', '资料已被更正版本替代。')
    if as_of and meta.get('effective_from') and meta['effective_from'][:10] > as_of:
        flag('not_effective', '事项在报告截止日尚未生效。')
    if as_of and meta.get('effective_to') and meta['effective_to'][:10] < as_of:
        flag('expired', '事项有效期已结束。')
    source_period = meta.get('data_period')
    for boundary in ('data_period_start','data_period_end'):
        if policy.get(boundary):
            if not meta.get(boundary): flag('unknown', '证据缺少所需的数据期间边界：'+boundary)
            elif meta[boundary][:10] != policy[boundary]: flag('period_mismatch', '证据数据期间边界与待核区间不一致：'+boundary)
    if target:
        if meta.get('ambiguous_period'): flag('ambiguous', '证据包含多个期间，未取得单值行列绑定。')
        elif not source_period: flag('unknown', '数据所属期间未知。')
        elif str(target) != str(source_period):
            flag('period_mismatch', '证据数据期间与待核期间不匹配。')
    if policy['mode']=='current' or re.search(r'目前|当前|截至目前|现时',claim):
        valid_date = meta.get('effective_from') or meta.get('data_period_end')
        if not as_of or not valid_date or policy.get('max_age_days') is None:
            flag('unknown', '当前状态判断缺少截止日、数据时点或适用的有效期规则。')
        elif (date.fromisoformat(as_of)-date.fromisoformat(valid_date[:10])).days > policy['max_age_days']:
            flag('stale', '证据数据时点超过本次当前状态有效期规则。')
    if not target and not as_of and not meta:
        result.update(status='not_requested')
    return result


def guard_verdict(verdict, child, evidence, policy=None, citation_map=None, record=None):
    """Record all candidates, then gate the evidence actually used by the model.

    Rejected evidence remains visible for contradiction and human audit. Time
    mismatch never becomes a high-confidence factual contradiction by itself.
    """
    result = dict(verdict)
    checks = [temporal_check(child['fact'], e, policy) for e in evidence]
    used = set(result.get('evidence_ids', []))
    used_checks = [c for c in checks if c['evidence_id'] in used]
    issues = list(result.get('issue_types', []))
    cited = child.get('citation_urls') or report_urls(child.get('source_quote') or child['fact'])
    citation_map = citation_map or {}
    citation_docs = {citation_map[u] for u in cited if citation_map.get(u)}
    selected = [e for e in evidence if e['evidence_id'] in used]
    failures = []
    for url in cited:
        if not citation_map.get(url): failures.append({'url':url,'reason':'本次网址未读取成功或未进入固定资料版本。'})
    if cited and result.get('status')=='SUPPORTED' and not any(e.get('document_id') in citation_docs for e in selected):
        failures.append({'reason':'模型依据其他来源判为支持，未验证报告所引网址。'})
    mentioned=[company for company,aliases in ENTITY_ALIASES.items() if any(a.lower() in child['fact'].lower() for a in aliases)]
    expected={a.lower() for company in mentioned for a in (company,*ENTITY_ALIASES[company])}
    if expected:
        entity_sources={e['evidence_id']:e for e in selected+[e for e in evidence if e.get('document_id') in citation_docs]}
        for e in entity_sources.values():
            entity=e.get('company_id') or ''
            if entity and entity.lower() not in expected:
                failures.append({'evidence_id':e['evidence_id'],'reason':'引用企业与待核企业不一致。'})
    for document in citation_docs:
        candidates={e['evidence_id'] for e in evidence if e.get('document_id')==document}
        candidate_checks=[c for c in checks if c['evidence_id'] in candidates]
        if candidate_checks and not any(c['eligible'] for c in candidate_checks):
            failures.append({'document_id':document,'reason':'所引资料的本次召回候选均未通过时间匹配。'})
    bad = [c for c in used_checks if not c['eligible']]
    # An empty support set is not a temporal pass.
    if bad or failures:
        if 'citation_mismatch' not in issues: issues.append('citation_mismatch')
        result.update(status='INSUFFICIENT_EVIDENCE', confidence='low',
                      reason='引用或时间匹配未通过：'+'；'.join(dict.fromkeys([r for c in bad for r in c['reasons']]+[f['reason'] for f in failures])))
    if result.get('status')=='INSUFFICIENT_EVIDENCE' and 'insufficient_evidence' not in issues:
        issues.append('insufficient_evidence')
    result.update(issue_types=issues, temporal_checks=checks, citation_checks=failures)
    if record: record('temporal_and_citation_gate', {'claim':child, 'policy':validated_policy(policy), 'checks':checks, 'citation_failures':failures,'verdict':result})
    return result
