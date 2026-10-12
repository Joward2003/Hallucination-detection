const TYPE_LABELS = {
  insufficient_evidence: '证据不足',
  citation_mismatch: '引用错配',
  overstatement: '表述过强',
  reasoning_gap: '推理跳跃',
  risk_omission: '风险遗漏',
  fact_mismatch: '事实不一致',
  unclassified: '待分类',
  supported: '核验通过',
};

const STATUS_LABELS = {
  SUPPORTED: '已支持',
  CONTRADICTED: '存在冲突',
  INSUFFICIENT_EVIDENCE: '证据不足',
};

function asArray(value) { return Array.isArray(value) ? value : []; }

function spanKind(result,context){return context.childById.get(result.fact_id)?.review_kind;}
function toFinding(result, context) {
  const factId = result.fact_id || result.child_id || 'unknown-fact';
  const evidence = asArray(result.evidence);
  const assessments = asArray(result.assessments);
  const risk = result.risk_decision || {};
  const issueTypes = asArray(result.issue_types);
  const type = (issueTypes.includes('fact_mismatch') ? 'fact_mismatch' : issueTypes[0]) || (spanKind(result,context) === 'risk_omission' ? 'risk_omission' : result.status === 'SUPPORTED' ? 'supported' : 'unclassified');
  const assessmentById = new Map(assessments.map((item) => [item.evidence_id, item]));
  const span = context.childById.get(factId) || {};
  return {
    id: factId,
    factId,
    parentId: result.parent_id || span.parent_id || '',
    text: result.fact || span.fact || '',
    parentText: result.parent_text || '',
    start: Number.isInteger(span.source_start) ? [...context.reportText].slice(0,span.source_start).join('').length : null,
    end: Number.isInteger(span.source_end) ? [...context.reportText].slice(0,span.source_end).join('').length : null,
    status: result.status || 'INSUFFICIENT_EVIDENCE',
    statusLabel: STATUS_LABELS[result.status] || '待复核',
    reason: result.reason || result.reasoning_summary || '',
    confidence: result.confidence || '',
    issueTypes,
    evidenceIds:asArray(result.evidence_ids),
    type,
    typeLabel: TYPE_LABELS[type] || (type === 'unclassified' ? '待分类' : type),
    risk: risk.risk_level || span.importance || '',
    riskLabel: ({ critical: '严重', high: '高风险', medium: '中风险', low: '低风险' })[String(risk.risk_level || span.importance || '').toLowerCase()] || '未评级',
    riskReasonCodes: asArray(risk.reason_codes),
    evidence: evidence.map((item) => ({
      ...item,
      relation: assessmentById.get(item.evidence_id)?.relation || '',
      quote: assessmentById.get(item.evidence_id)?.quote || '',
      rationale: assessmentById.get(item.evidence_id)?.rationale || assessmentById.get(item.evidence_id)?.reason || '',
    })),
    queries: asArray(result.queries),
    trace: asArray(result.retrieval_trace),
    missingNeeds: asArray(result.missing_needs),
    numericChecks: asArray(result.numeric_checks),
    ruleHits: asArray(result.rule_hits),
    humanDecision: result.human_decision || null,
    humanTask: context.pendingTask?.fact_id === factId ? context.pendingTask : null,
    finalText: result.human_decision?.final_text || null,
  };
}

function currentPendingFinding(state, context) {
  const task = state.human_task;
  if (!task || task.status !== 'PENDING') return null;
  const current = state.current_fact || {};
  const verification = state.verification_result || state.initial_verdict || {};
  const result = {
    ...verification,
    fact_id: current.fact_id || task.fact_id,
    fact: current.fact || '',
    parent_id: (state.current_parent || {}).parent_id || '',
    parent_text: (state.current_parent || {}).parent_text || '',
    evidence: asArray(state.current_evidence),
    assessments: asArray(state.current_assessments),
    queries: asArray(state.current_queries),
    retrieval_trace: asArray(state.retrieval_trace),
    missing_needs: asArray(state.missing_needs),
    numeric_checks: asArray(state.numeric_checks),
    rule_hits: asArray(state.rule_hits),
    risk_decision: state.risk_decision || {},
  };
  return toFinding(result, context);
}

export function adaptReview(record) {
  const state = record?.state || record || {};
  const result = state.review_result || {};
  const groups = asArray(state.fact_groups).length ? state.fact_groups : asArray(result.fact_groups);
  const childById = new Map();
  for (const group of groups) {
    const parent = group.parent || {};
    for (const child of asArray(group.children)) {
      childById.set(child.fact_id, { ...child, parent_id: parent.parent_id, parent_text: parent.parent_text });
    }
  }
  const context = { childById, pendingTask: state.human_task || null,reportText:state.original_input || '' };
  const completed = asArray(state.completed_results).length ? state.completed_results : asArray(result.completed_results);
  const findings = completed.map((item) => toFinding(item, context));
  const pending = currentPendingFinding(state, context);
  if (pending && !findings.some((item) => item.id === pending.id)) findings.push(pending);
  return {
    reviewId: record.review_id || result.review_id || state.review_id || '',
    reportId: record.report_id || '',
    status: record.status || state.workflow_status || result.status || 'UNKNOWN',
    workflowStatus: record.status || state.workflow_status || result.status || 'UNKNOWN',
    reportText: state.original_input || '',
    company: (result.company_info || state.company_info || {}).company_name || '',
    findings,
    groups,
    pendingTask: context.pendingTask,
    summaryCounts: result.summary_counts || {},
    corpusVersion: result.corpus_version || state.corpus_version || '',
    ruleSetVersion: result.rule_set_version || state.rule_set_version || '',
    currentStep: state.workflow_status || record.status || 'UNKNOWN',
    raw: record,
  };
}

export function typeLabel(type) { return TYPE_LABELS[type] || type || '待分类'; }
export function statusLabel(status) { return STATUS_LABELS[status] || status || '未知'; }
