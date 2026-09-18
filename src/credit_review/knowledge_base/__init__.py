"""Knowledge-base ingestion and MinerU-compatible document normalization."""

from .pipeline import KnowledgeBaseBuilder, build_knowledge_base, evidence_from_snapshot, parse_mineru_export
from .repository import KnowledgeBaseRepository
from .build_service import BuildManager
from .search_service import KnowledgeBaseSearchService

__all__ = ["BuildManager", "KnowledgeBaseBuilder", "KnowledgeBaseRepository", "KnowledgeBaseSearchService", "build_knowledge_base", "evidence_from_snapshot", "parse_mineru_export"]
