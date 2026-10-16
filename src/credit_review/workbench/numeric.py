"""Conservative source bindings and three-state Decimal checks.

False means a completed calculation disagreed. Unresolved bindings, ambiguous
tables and undefined formulas return None and must be reviewed by a person.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal

UNITS = {'元': Decimal(1), '万元': Decimal(10000), '亿元': Decimal(100000000), '%': Decimal(1), '倍': Decimal(1)}
MONEY = {'元', '万元', '亿元'}
NUMBER = r'-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
QUANTITY = re.compile(r'(?<![\d.,])(?P<value>' + NUMBER + r')\s*(?P<unit>亿元|万元|元|%|％|倍)')
YEARS = re.compile(r'(?<!\d)(?:19|20)\d{2}(?!\d)')


def decimal(value):
    result = Decimal(str(value).replace(',', ''))
    if not result.is_finite():
        raise ValueError('数值必须有限')
    return result


def quantities(text):
    return [(m, decimal(m['value']), m['unit'].replace('％', '%')) for m in QUANTITY.finditer(text)]


def number_present(value, text):
    return any(decimal(m.group()) == value for m in re.finditer(NUMBER, text))


def _single_quantity(text, value, unit):
    values = quantities(text)
    if len(values) != 1 or values[0][1:] != (value, unit):
        raise ValueError('数值与单位未唯一绑定到同一数量短语；请提供更精确的引用')


def _claim_metric_matches(metric, fact):
    if metric in fact:
        # A generic metric cannot stand in for a differently qualified metric.
        for match in re.finditer(re.escape(metric), fact):
            prefix = fact[max(0, match.start()-20):match.start()]
            if not re.search(r'(?:扣非|归母|母公司|其他|非|调整后(?:的)?|扣除非经常性损益后(?:的)?)\s*$', prefix):
                return True
        return False
    # Generic aliases must be standalone targets, never a substring of
    # 营业外收入/其他收入/etc. Unknown synonym mappings stay unresolved.
    return metric == '营业收入' and re.search(r'(?:^|[，。；;：:\s]|年|公司)(?:收入|营收)', fact) is not None


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
        if str(source.get('period') or '') != period or source_years - {period}:
            raise ValueError('操作数期间缺少明确支持')
    if unit not in UNITS:
        raise ValueError('操作数单位无效')
    _single_quantity(quote, value, unit)
    match = quantities(quote)[0][0]
    prefix = re.split(r'[，,；;。！？!?\n]', quote[:match.start()])[-1]
    metric_end = prefix.rfind(metric) + len(metric)
    if metric not in prefix or not re.fullmatch(r'\s*(?:(?:为|约为|达到|达|合计|总计|是|约|计|人民币|金额|金额为)\s*|[:：]\s*)*', prefix[metric_end:]):
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
        checks = [compute_check(spec, child['fact'], evidence) for spec in specs]
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
