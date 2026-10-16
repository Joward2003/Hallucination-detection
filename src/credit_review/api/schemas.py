from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReviewRequest:
    report_id: str
    report_version: str
    tenant_id: str
    project_id: str
    requested_by: str
    idempotency_key: str
    report_text: str
    evidence: list[dict[str, Any]] | None = None
    companies: dict[str, dict[str, str]] | None = None
    source_scope: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReviewRequest":
        required = ("report_id", "report_version", "tenant_id", "project_id", "requested_by", "idempotency_key", "report_text")
        missing = [field for field in required if not payload.get(field)]
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")
        companies=payload.get('companies')
        if companies is not None and (not isinstance(companies,dict) or any(not isinstance(name,str) or not isinstance(info,dict) for name,info in companies.items())):
            raise ValueError('companies 必须为企业名称到企业资料对象的映射。')
        return cls(**{field: payload[field] for field in required}, evidence=payload.get("evidence"), companies=payload.get("companies"), source_scope=payload.get("source_scope"))
