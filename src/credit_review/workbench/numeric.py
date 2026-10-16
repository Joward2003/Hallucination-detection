"""Conservative source bindings and three-state Decimal checks.

False means a completed calculation disagreed. Unresolved bindings, ambiguous
tables and undefined formulas return None and must be reviewed by a person.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal

UNITS = {'元': Decimal(1), '万元': Decimal(10000), '亿元': Decimal(100000000), '%': Decimal(1), '倍': Decimal(1)}
UNITS.update({'美元':Decimal(1),'百万美元':Decimal(1000000),'亿美元':Decimal(100000000),'十亿美元':Decimal(1000000000)})
MONEY = {'元', '万元', '亿元','美元','百万美元','亿美元','十亿美元'}
NUMBER = r'-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
QUANTITY = re.compile(r'(?<![\d.,])(?P<value>' + NUMBER + r')\s*(?P<unit>十亿美元|百万美元|亿美元|美元|亿元|万元|元|%|％|倍)')
EN_QUANTITY = re.compile(r'(?<![\d.,])(?:US\s*)?\$(?P<value>'+NUMBER+r')\s*(?P<scale>billion|million)?',re.I)
YEARS = re.compile(r'(?<!\d)(?:19|20)\d{2}(?!\d)')


def decimal(value):
    result = Decimal(str(value).replace(',', ''))
    if not result.is_finite():
        raise ValueError('数值必须有限')
    return result


def quantities(text):
    values=[(m, decimal(m['value']), m['unit'].replace('％', '%')) for m in QUANTITY.finditer(text)]
    values += [(m,decimal(m['value']),{'billion':'十亿美元','million':'百万美元',None:'美元'}[m['scale'].lower() if m['scale'] else None]) for m in EN_QUANTITY.finditer(text)]
    return sorted(values,key=lambda v:v[0].start())


def number_present(value, text):
    return any(decimal(m.group()) == value for m in re.finditer(NUMBER, text))


def _single_quantity(text, value, unit):
    values = quantities(text)
    if len(values) != 1 or values[0][1:] != (value, unit):
        raise ValueError('数值与单位未唯一绑定到同一数量短语；请提供更精确的引用')


def _claim_metric_matches(metric, fact):
    if re.fullmatch(r'(?:本|该)?(?:季度|年度|期)?营收',metric): metric='营业收入'
    if metric in fact:
        # A generic metric cannot stand in for a differently qualified metric.
        for match in re.finditer(re.escape(metric), fact):
            prefix = fact[max(0, match.start()-20):match.start()]
            if not re.search(r'(?:扣非|归母|母公司|其他|非|调整后(?:的)?|扣除非经常性损益后(?:的)?|other|adjusted|non-operating)\s*$', prefix,re.I):
                return True
        return False
    bilingual={'revenue':'营业收入','net income':'净利润','operating income':'营业利润'}
    if metric.lower() in bilingual:return _claim_metric_matches(bilingual[metric.lower()],fact)
    # Generic aliases must be standalone targets, never a substring of
    # 营业外收入/其他收入/etc. Unknown synonym mappings stay unresolved.
    return metric == '营业收入' and re.search(r'(?:^|[，。；;：:\s]|年|季度|年度|本期|公司)(?:收入|营收)', fact) is not None


def reconcile_numeric_verdict(child, verdict, checks):
    """Only a completely bound, single amount statement can be confirmed here.

    Other claims retain the semantic verdict even when some numbers agree.
    Citation and time failures cannot be erased by a numerical coincidence.
    """
    result=dict(verdict)
    if any(c.get('passed') is False for c in checks):
        result.update(status='CONTRADICTED',confidence='high',reason='程序计算与报告数字不符；详见计算工作底稿。',
                      issue_types=['fact_mismatch']+[t for t in result.get('issue_types',[]) if t!='fact_mismatch'])
    elif any(c.get('passed') is None for c in checks) and result.get('status')=='SUPPORTED':
        result.update(status='INSUFFICIENT_EVIDENCE',confidence='low',reason='数值口径或操作数尚未通过程序校验；需人工确认。',issue_types=['insufficient_evidence'])
    elif checks and all(c.get('passed') is True and c.get('kind')=='amount' for c in checks):
        simple=re.fullmatch(r'(?P<entity>[\u4e00-\u9fffA-Za-z .-]{1,30})20\d{2}(?:财年|年)(?:第[一二三四1-4]季度)?(?:营业收入|营收|营业利润|经营利润|净利润)(?:为|是|达到)'+NUMBER+r'\s*(?:十亿美元|百万美元|亿美元|美元|亿元|万元|元)[。.]?',child['fact'])
        blocked=set(result.get('issue_types',[])) & {'citation_mismatch','overstatement','reasoning_gap','risk_omission'}
        used=set(result.get('evidence_ids',[]))
        operands={b['evidence_id'] for c in checks for b in c.get('operands',{}).values()}
        times={c['evidence_id']:c for c in result.get('temporal_checks',[])}
        time_ok=operands<=set(times) and all(times[e]['eligible'] for e in operands)
        entity_ok=False
        if simple and time_ok:
            from .temporal import ENTITY_ALIASES
            target=simple['entity'].strip().lower()
            entity_ok=all(target in {str(times[e].get('source_company') or '').lower(),*(a.lower() for a in ENTITY_ALIASES.get(times[e].get('source_company'),()))} for e in operands)
        if simple and entity_ok and not blocked and not result.get('citation_checks') and operands and operands<=used and time_ok:
            result.update(status='SUPPORTED',confidence='high',reason='逐字操作数、主体、期间和币种已匹配，金额由 Decimal 换算核验一致。',issue_types=[],numeric_reconciled=True)
    return result


def _operand(binding, known):
    if not isinstance(binding, Mapping):
        raise ValueError('操作数结构无效')
    source = known[binding['evidence_id']]
    quote, metric, period, unit = (binding[k] for k in ('quote', 'metric', 'period', 'unit'))
    period = str(period)
    value = decimal(binding['value'])
    if not isinstance(quote, str) or not quote or quote not in source['content']:
        raise ValueError('操作数未匹配逐字证据')
    if re.search(r'<(?:table|tr|td|th)\b', quote, re.I):
        raise ValueError('表格操作数缺少经验证的行列绑定，需人工核对')
    if not isinstance(metric, str) or not metric or metric not in quote or not _claim_metric_matches(metric, quote):
        raise ValueError('操作数指标未匹配原文')
    if not re.fullmatch(r'(?:19|20)\d{2}', period):
        raise ValueError('操作数期间无效')
    years = set(YEARS.findall(quote))
    if years and years != {period}:
        raise ValueError('引用包含其他期间，不能唯一绑定操作数年份')
    if not years:
        source_years = set(YEARS.findall(source['content']))
        declared=str(source.get('period') or (source.get('temporal') or {}).get('data_period') or '')
        if declared not in {period,'FY'+period} and not declared.startswith('FY'+period+'Q') or source_years - {period}:
            raise ValueError('操作数期间缺少明确支持')
    if unit not in UNITS:
        raise ValueError('操作数单位无效')
    _single_quantity(quote, value, unit)
    match = quantities(quote)[0][0]
    prefix = re.split(r'[，,；;。！？!?\n]', quote[:match.start()])[-1]
    metric_end = prefix.rfind(metric) + len(metric)
    if metric not in prefix or not re.fullmatch(r'\s*(?:(?:为|约为|达到|达|合计|总计|是|约|计|人民币|金额|金额为|was|were|is|of|reached)\s*|[:：]\s*)*', prefix[metric_end:],re.I):
        raise ValueError('指标与数值不属于同一明确数量短语')
    # A short quote containing one metric/year/quantity is necessary. It is
    # intentionally insufficient for unstructured multi-year/multi-value tables.
    return value * UNITS[unit]


def compute_check(spec, fact, evidence):
    result = {**spec} if isinstance(spec, Mapping) else {'invalid_spec': type(spec).__name__}
    result.update(passed=None, observed=None, validator_version='decimal-financial-v2', tolerance='0.01')
    try:
        if not isinstance(spec, Mapping):
            raise ValueError('数值校验结构无效')
        expected = decimal(spec['expected'])
        quote, unit = spec['report_quote'], spec['unit']
        if not isinstance(quote, str) or not quote or quote not in fact or unit not in UNITS:
            raise ValueError('报告数值引用或单位无效')
        _single_quantity(quote, expected, unit)
        known = {e['evidence_id']: e for e in evidence}
        bindings = spec['operands']
        kind = spec['kind']
        required = {'amount': {'current'}, 'ratio': {'numerator', 'denominator'}, 'yoy': {'current', 'previous'}}
        if kind not in required or not isinstance(bindings, Mapping) or set(bindings) != required[kind]:
            raise ValueError('计算类型或操作数集合无效')
        operands = {name: _operand(binding, known) for name, binding in bindings.items()}
        target_years = set(YEARS.findall(quote)) or set(YEARS.findall(fact))
        if kind == 'amount':
            current = bindings['current']
            if unit not in MONEY or current['unit'] not in MONEY:
                raise ValueError('金额校验须使用金额单位')
            if ('美元' in unit)!=('美元' in current['unit']):raise ValueError('金额币种不一致，不执行汇率换算')
            if target_years and target_years != {str(current['period'])}:
                raise ValueError('操作数期间与报告目标不一致')
            if not _claim_metric_matches(current['metric'], quote):
                raise ValueError('金额指标未匹配报告目标')
            observed = operands['current'] / UNITS[unit]
            expression = 'current / report_unit_scale'
        elif kind == 'ratio':
            numerator, denominator = bindings['numerator'], bindings['denominator']
            if unit not in {'%', '倍'} or str(numerator['period']) != str(denominator['period']):
                raise ValueError('比率单位或分子分母期间不一致')
            if target_years and target_years != {str(numerator['period'])}:
                raise ValueError('比率期间与报告目标不一致')
            if numerator['unit'] not in MONEY or denominator['unit'] not in MONEY:
                raise ValueError('比率操作数量纲不一致')
            if ('美元' in numerator['unit'])!=('美元' in denominator['unit']):raise ValueError('比率币种不一致')
            formulas = {
                '资产负债率': ({'总负债', '负债总额'}, {'总资产', '资产总额'}),
                '流动比率': ({'流动资产', '流动资产合计'}, {'流动负债', '流动负债合计'}),
                '速动比率': ({'速动资产'}, {'流动负债', '流动负债合计'}),
                '净利率': ({'净利润'}, {'营业收入'}),
                '毛利率': ({'毛利润', '毛利'}, {'营业收入'}),
            }
            formula = next((v for k, v in formulas.items() if k in fact), None)
            if not formula or numerator['metric'] not in formula[0] or denominator['metric'] not in formula[1]:
                raise ValueError('比率指标不在已验证公式中或操作数指标错配')
            observed = operands['numerator'] / operands['denominator'] * (100 if unit == '%' else 1)
            expression = 'numerator / denominator * report_scale'
        else:
            current, previous = bindings['current'], bindings['previous']
            if unit != '%' or current['metric'] != previous['metric'] or current['unit'] not in MONEY or previous['unit'] not in MONEY:
                raise ValueError('同比单位、指标或量纲不一致')
            if ('美元' in current['unit'])!=('美元' in previous['unit']):raise ValueError('同比币种不一致')
            if not _claim_metric_matches(current['metric'], fact):
                raise ValueError('同比指标未匹配报告目标')
            if int(current['period']) - int(previous['period']) != 1:
                raise ValueError('同比操作数并非连续两年')
            if target_years and int(current['period']) != max(map(int, target_years)):
                raise ValueError('同比期间与报告目标不一致')
            if operands['previous'] <= 0:
                raise ValueError('同比基数非正，不能据常规增长率公式判定')
            if re.search(r'下降|减少|降低', quote):
                expected = -abs(expected)
            observed = (operands['current'] - operands['previous']) / operands['previous'] * 100
            expression = '(current - previous) / previous * 100'
        result.update(observed=str(observed), expression=expression, normalized_expected=str(expected),
                      normalized_operands={k: str(v) for k, v in operands.items()},
                      passed=abs(observed - expected) <= Decimal('0.01'))
        result['failure_reason'] = None if result['passed'] else '超出容忍误差'
    except (ArithmeticError, KeyError, ValueError, TypeError, AttributeError) as exc:
        result['failure_reason'] = f'{type(exc).__name__}: {exc}'
    return result


class NumericValidator:
    def __init__(self, verifier):
        self.verifier = verifier

    def validate(self, child, evidence):
        if child.get('review_kind') == 'extraction_gap':
            return []
        specs = self.verifier.bindings.get(child['fact_id'], [])
        if not isinstance(specs, list):
            specs = [None]
        prepared=[]
        report_quantities=quantities(child['fact'])
        for spec in specs:
            try:
                if isinstance(spec,Mapping) and spec.get('kind')=='amount' and len(report_quantities)==1:
                    _,expected,unit=report_quantities[0]
                    if unit in MONEY:
                        spec={**spec,'model_report_binding':{k:spec.get(k) for k in ('expected','unit','report_quote')},'expected':str(expected),'unit':unit,'report_quote':child['fact']}
                        operands=dict(spec.get('operands') or {})
                        current=operands.get('current')
                        if isinstance(current,Mapping):
                            quote=current.get('quote','');metric=current.get('metric','')
                            if isinstance(quote,str) and isinstance(metric,str) and metric and not re.search(r'<(?:table|td|tr|th)\b',quote,re.I) and len(set(YEARS.findall(quote)))<=1:
                                matches=[m for m,value,q_unit in quantities(quote) if str(value)==str(decimal(current.get('value',0))) and q_unit==current.get('unit')]
                                if len(matches)==1:
                                    end=matches[0].end();begin=quote.rfind(metric,0,matches[0].start())
                                    if begin>=0:operands['current']={**current,'quote':quote[begin:end]}
                        spec={**spec,'operands':operands}
            except (ValueError,TypeError,ArithmeticError,AttributeError):
                pass
            prepared.append(spec)
        checks = [compute_check(spec, child['fact'], evidence) for spec in prepared]
        if getattr(self.verifier,'temporal_policy',None):
            from .temporal import temporal_check
            by_id={e['evidence_id']:e for e in evidence}
            for check in checks:
                if not isinstance(check.get('operands'),Mapping):continue
                if any(not temporal_check(child['fact'],by_id[b['evidence_id']],self.verifier.temporal_policy)['eligible']
                       for b in check['operands'].values() if isinstance(b,Mapping) and b.get('evidence_id') in by_id):
                    check.update(passed=None,observed=None,failure_reason='操作数时间匹配未通过，不能作为事实冲突依据。')
        # One valid check cannot mask a second unbound numerical statement.
        spans = []
        for check in checks:
            if check['passed'] is not None:
                quote = check['report_quote']
                start = child['fact'].find(quote)
                spans.append((start, start + len(quote)))
        missing = [m.group() for m, _, _ in quantities(child['fact'])
                   if not any(start <= m.start() and m.end() <= end for start, end in spans)]
        if missing:
            checks.append({'passed': None, 'failure_reason': '缺少可定位且口径明确的数值操作数，未执行计算。',
                           'unbound_quantities': missing, 'validator_version': 'decimal-financial-v2'})
        return checks
