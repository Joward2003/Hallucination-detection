"""Run a small end-to-end build and search through the production adapters.

Usage (inside the production Conda environment):
    conda activate credit-review-rag-prod
    export CREDIT_REVIEW_RETRIEVAL_BACKEND=sentence_transformers
    export HF_HUB_DISABLE_XET=1  # use the regular Hub download path on first run
    python scripts/smoke_test_production_rag.py

The sample KB and indexes are temporary. Model weights remain in the normal
Hugging Face cache and are not copied into the repository.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from credit_review.config.models import RetrievalConfig
from credit_review.knowledge_base import BuildManager, KnowledgeBaseRepository


def main() -> None:
    print("[1/5] Loading production retrieval configuration", flush=True)
    config = RetrievalConfig.from_env()
    if config.backend != "sentence_transformers":
        raise SystemExit("Set CREDIT_REVIEW_RETRIEVAL_BACKEND=sentence_transformers first")
    print(
        "      backend={}; embedding={}; reranker={}; lexical={}".format(
            config.backend, config.embedding_model, config.reranker_model, config.bm25_backend
        ),
        flush=True,
    )

    source = {
        "content_list": [
            {
                "type": "text",
                "text": "甲公司2024年流动比率为1.62，速动比率为1.21。公司流动资产覆盖流动负债，短期偿债能力较强。",
                "page_idx": 4,
            },
            {
                "type": "text",
                "text": "甲公司2024年经营活动现金流净额为18.6亿元，利息保障倍数为4.3倍。",
                "page_idx": 5,
            },
            {
                "type": "text",
                "text": "报告期内公司营业收入增长12.4%，经营现金流与净利润匹配度提升。",
                "page_idx": 6,
            },
            {
                "type": "text",
                "text": "公司债务期限结构较为均衡，一年内到期有息负债占比下降。",
                "page_idx": 7,
            },
            {
                "type": "text",
                "text": "主要客户回款周期缩短，应收账款周转率同比改善。",
                "page_idx": 8,
            },
        ]
    }

    with TemporaryDirectory(prefix="credit-review-prod-smoke-") as temporary:
        root = Path(temporary)
        repository = KnowledgeBaseRepository(root / "kb")
        manager = BuildManager(
            repository,
            retrieval_backend="sentence_transformers",
            retrieval_config=config,
            index_root=root / "indexes",
        )

        print("[2/5] Building temporary KB with real embeddings and BM25S", flush=True)
        started = perf_counter()
        build = manager.create(
            {
                "kb_id": "smoke-finance",
                "tenant_id": "local-smoke",
                "requested_by": "local-user",
                "idempotency_key": "smoke-001",
                "kb_version": "smoke-v1",
                "source": source,
                "source_name": "financial-smoke.json",
            }
        )
        if build["status"] != "READY":
            raise RuntimeError("Build failed: {}".format(build["errors"]))
        manifest = build["manifest"]
        print(
            "      READY in {:.1f}s; evidence={}".format(perf_counter() - started, manifest["evidence_count"]),
            flush=True,
        )
        print("      dense_index={}".format(manifest["dense_index_ref"]), flush=True)
        print("      bm25_index={}".format(manifest["bm25_index_ref"]), flush=True)

        print('[3/5] Searching: "甲公司短期偿债能力和流动性如何"', flush=True)
        started = perf_counter()
        hits = manager.search(
            "smoke-finance",
            {
                "query_id": "Q-SMOKE-1",
                "query_text": "甲公司短期偿债能力和流动性如何",
                "dense_top_k": 5,
                "lexical_top_k": 5,
                "candidate_top_k": 8,
                "rerank_top_n": 3,
            },
            version="smoke-v1",
        )
        elapsed = perf_counter() - started
        if not hits:
            raise RuntimeError("Production search returned no hits")
        print("      got {} hits in {:.1f}s".format(len(hits), elapsed), flush=True)

        print("[4/5] Checking Dense/BM25 fusion and Cross-Encoder metadata", flush=True)
        for rank, hit in enumerate(hits, 1):
            routes = ",".join(route["route"] for route in hit.get("route_hits", []))
            print(
                "      #{} {} routes=[{}] rerank={} model={}".format(
                    rank,
                    hit["evidence_id"],
                    routes,
                    hit.get("rerank_score"),
                    hit.get("reranker_model"),
                ),
                flush=True,
            )
            print("         {}".format(hit["content"]), flush=True)
        has_hybrid_hit = any(
            {"dense", "bm25"} <= {route["route"] for route in hit.get("route_hits", [])} for hit in hits
        )
        if not has_hybrid_hit:
            raise RuntimeError("No result preserved both Dense and BM25 route provenance")
        if not all(hit.get("reranker_model") == config.reranker_model for hit in hits):
            raise RuntimeError("Cross-Encoder reranker metadata is missing from one or more hits")

        print("[5/5] Production RAG smoke test passed; temporary KB/indexes will be removed", flush=True)


if __name__ == "__main__":
    main()
