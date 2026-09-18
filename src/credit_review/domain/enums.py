"""Stable domain enums shared by graph, verification and API layers."""

from enum import Enum


class EvidenceRelation(str, Enum):
    SUPPORTS = "supports"
    PARTIALLY_SUPPORTS = "partially_supports"
    IRRELEVANT = "irrelevant"
    CONTRADICTS = "contradicts"


class EvidenceStatus(str, Enum):
    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class IssueType(str, Enum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CITATION_MISMATCH = "citation_mismatch"
    OVERSTATEMENT = "overstatement"
    REASONING_GAP = "reasoning_gap"
    RISK_OMISSION = "risk_omission"


class VerdictStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
