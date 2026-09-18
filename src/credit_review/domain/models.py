"""Small, serializable domain models used by the MVP.

The MVP deliberately uses dataclasses rather than provider-specific model types.
The graph State stores dictionaries produced by ``asdict`` so it can be
checkpointed and tested without external services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from .enums import IssueType, RiskLevel


VerdictStatus = Literal["SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"]
EvidenceStatus = Literal["SUFFICIENT", "PARTIAL", "INSUFFICIENT"]
EvidenceRelation = Literal[
    "SUPPORTS", "PARTIALLY_SUPPORTS", "IRRELEVANT", "CONTRADICTS"
]


@dataclass(frozen=True)
class ParentContext:
    parent_id: str
    parent_text: str
    source_start: int
    source_end: int


@dataclass(frozen=True)
class ChildFact:
    fact_id: str
    parent_id: str
    fact: str
    source_start: int
    source_end: int


@dataclass(frozen=True)
class FactGroup:
    parent: ParentContext
    children: list[ChildFact]


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    content: str
    source: str
    page: int | None
    evidence_type: Literal["text", "table"]
    score: float
    table_name: str | None = None
    row: str | None = None
    column: str | None = None
    document_id: str | None = None
    document_version: str | None = None
    company_id: str | None = None
    period: str | None = None
    content_hash: str | None = None
    table_id: str | None = None
    section: str | None = None
    metric_ids: list[str] = field(default_factory=list)
    structured: bool = False


@dataclass(frozen=True)
class TextSpan:
    start: int
    end: int
    section: str | None = None


@dataclass(frozen=True)
class SourceScope:
    allowed_document_ids: list[str]
    company_ids: list[str]
    periods: list[str]
    corpus_version: str
    rule_set_version: str
    data_classification: str = "unclassified"


@dataclass(frozen=True)
class EvidenceNeed:
    need_id: str
    description: str
    evidence_type: Literal["text", "table", "hybrid"]
    polarity: Literal["support", "counter"]
    required_metrics: list[str] = field(default_factory=list)
    required_periods: list[str] = field(default_factory=list)
    sufficiency_hint: str | None = None


@dataclass(frozen=True)
class RetrievalQuery:
    query_id: str
    fact_id: str
    need_id: str
    query_text: str
    retrieval_type: Literal["text", "table"]
    attempt: int
    filters: dict[str, str | list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceLocator:
    document_id: str
    document_version: str
    file_name: str = ""
    page: int | None = None
    section: str | None = None
    table_id: str | None = None
    row: str | None = None
    column: str | None = None
    content_hash: str = ""


@dataclass(frozen=True)
class EvidenceCandidate:
    evidence_id: str
    locator: EvidenceLocator
    content: str
    retrieval_type: Literal["text", "table"]
    retrieval_score: float | None
    rerank_score: float | None
    query_id: str


@dataclass(frozen=True)
class NumericCheck:
    check_id: str
    expression: str
    operands: dict[str, Decimal]
    units: dict[str, str]
    periods: dict[str, str]
    expected: Decimal | None
    observed: Decimal | None
    tolerance: Decimal
    passed: bool | None
    failure_reason: str | None = None


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    rule_version: str
    issue_type: IssueType | str
    severity: RiskLevel | str
    triggered: bool
    facts: dict[str, Any]
    explanation: str
    required_human_review: bool = False


@dataclass(frozen=True)
class Verdict:
    status: VerdictStatus
    evidence_status: EvidenceStatus
    evidence_ids: list[str]
    counter_evidence_ids: list[str]
    issue_types: list[str]
    reasoning_summary: str
    confidence_band: Literal["low", "medium", "high"]
    confidence_basis: list[str] = field(default_factory=list)
    verifier_version: str = "mvp"


@dataclass(frozen=True)
class HumanDecision:
    task_id: str
    task_version: int
    decision: VerdictStatus
    issue_types: list[str]
    selected_evidence_ids: list[str]
    comment: str
    decided_by: str
    decided_at: datetime


@dataclass(frozen=True)
class CompanyInfo:
    company_id: str
    company_name: str
    stock_code: str | None = None
    resolution_method: Literal["deterministic", "llm_fallback", "human"] = "deterministic"
    confidence_band: Literal["low", "medium", "high"] = "high"


@dataclass(frozen=True)
class ChildReviewResult:
    fact_id: str
    fact: str
    parent_id: str
    parent_text: str
    queries: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    assessments: list[dict[str, Any]]
    initial_verdict: dict[str, Any]
    final_verdict: dict[str, Any]
    critic_verdict: dict[str, Any] | None = None
    numeric_checks: list[dict[str, Any]] = field(default_factory=list)
    rule_hits: list[dict[str, Any]] = field(default_factory=list)
    human_decision: dict[str, Any] | None = None
    trace_id: str = ""
    retrieval_plan: dict[str, Any] | None = None
    evidence_requirements: list[dict[str, Any]] = field(default_factory=list)
    retrieval_trace: list[dict[str, Any]] = field(default_factory=list)
    evidence_observation: dict[str, Any] | None = None
    missing_needs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewResult:
    review_id: str
    workflow_status: str
    completed_results: list[ChildReviewResult]
    summary_counts: dict[str, int]
    corpus_version: str = ""
    rule_set_version: str = ""
    model_versions: dict[str, str] = field(default_factory=dict)
    created_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True)
class EvidenceAssessment:
    evidence_id: str
    relation: EvidenceRelation
    rationale: str
    usable: bool


@dataclass(frozen=True)
class VerificationResult:
    status: VerdictStatus
    reason: str
    evidence_ids: list[str] = field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "low"
    counter_evidence_ids: list[str] = field(default_factory=list)
    issue_types: list[str] = field(default_factory=list)
    confidence_basis: list[str] = field(default_factory=list)
    verifier_version: str = "mvp"
