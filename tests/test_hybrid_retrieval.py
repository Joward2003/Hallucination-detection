from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_review.retrieval.service import (
    BM25Retriever,
    HybridSearchService,
    RetrievalRouter,
    RRFFusion,
    financial_tokens,
)


class HybridRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = [
            {"evidence_id": "exact", "content": "甲公司2024年流动资产合计120亿元，流动负债合计80亿元。", "document_id": "D1"},
            {"evidence_id": "narrative", "content": "公司短期流动性良好，偿债能力持续增强。", "document_id": "D1"},
            {"evidence_id": "wrong-period", "content": "甲公司2023年流动资产合计90亿元。", "document_id": "D1"},
            {"evidence_id": "forbidden", "content": "甲公司2024年流动资产合计120亿元。", "document_id": "D2"},
        ]

    def test_tokenizer_keeps_financial_numbers_and_chinese_bigrams(self) -> None:
        tokens = financial_tokens("2024年收入20.5亿元")
        self.assertIn("2024", tokens)
        self.assertIn("20.5", tokens)
        self.assertIn("收入", tokens)

    def test_dense_adapter_is_stable_across_instances(self) -> None:
        first = HybridSearchService(self.candidates, dense_top_k=10, bm25_top_k=10).dense.retrieve("甲公司2024年流动资产")
        second = HybridSearchService(self.candidates, dense_top_k=10, bm25_top_k=10).dense.retrieve("甲公司2024年流动资产")
        self.assertEqual([item["evidence_id"] for item in first], [item["evidence_id"] for item in second])

    def test_bm25_ranks_exact_financial_terms_and_applies_scope_first(self) -> None:
        retriever = BM25Retriever(self.candidates, top_k=10)
        results = retriever.retrieve("甲公司 2024 流动资产 120亿元", {"allowed_document_ids": ["D1"]})
        self.assertEqual(results[0]["evidence_id"], "exact")
        self.assertNotIn("forbidden", [item["evidence_id"] for item in results])

    def test_rrf_merges_routes_once_and_preserves_route_provenance(self) -> None:
        fusion = RRFFusion(rrf_k=60)
        results = fusion.fuse(
            {
                "dense": [{"evidence_id": "same", "content": "a", "retrieval_score": 0.8}, {"evidence_id": "dense-only", "content": "b", "retrieval_score": 0.7}],
                "bm25": [{"evidence_id": "same", "content": "a", "retrieval_score": 4.0}, {"evidence_id": "bm25-only", "content": "c", "retrieval_score": 3.0}],
            },
            top_k=10,
        )
        same = next(item for item in results if item["evidence_id"] == "same")
        self.assertEqual(len([item for item in results if item["evidence_id"] == "same"]), 1)
        self.assertEqual({item["route"] for item in same["route_hits"]}, {"dense", "bm25"})
        self.assertGreater(same["rrf_score"], results[-1]["rrf_score"])

    def test_hybrid_service_returns_reranked_candidates_with_trace(self) -> None:
        service = HybridSearchService(self.candidates, dense_top_k=10, bm25_top_k=10, candidate_top_k=10, rerank_top_n=3)
        results = service.retrieve(
            {
                "query_id": "Q1",
                "query_text": "甲公司2024年流动资产合计120亿元",
                "retrieval_profile": "financial_table",
                "dense_top_k": 10,
                "lexical_top_k": 10,
                "rerank_top_n": 3,
            },
            {"allowed_document_ids": ["D1"]},
        )
        self.assertEqual(results[0]["evidence_id"], "exact")
        self.assertEqual(results[0]["query_id"], "Q1")
        self.assertIn("route_hits", results[0])
        self.assertIn("rerank_score", results[0])
        self.assertNotIn("forbidden", [item["evidence_id"] for item in results])

    def test_text_worker_does_not_use_table_rows_as_narrative_evidence(self) -> None:
        service = HybridSearchService(self.candidates, dense_top_k=10, bm25_top_k=10)
        results = service.retrieve({"query_text": "流动性良好", "evidence_type": "text"})
        self.assertTrue(results)
        self.assertTrue(all(item.get("evidence_type", "text") == "text" for item in results))

    def test_router_uses_table_worker_for_metric_requests(self) -> None:
        router = RetrievalRouter(
            [
                {"evidence_id": "table", "content": "甲公司2024年流动资产120亿元", "evidence_type": "table", "document_id": "D1"},
                {"evidence_id": "text", "content": "公司流动性良好", "evidence_type": "text", "document_id": "D1"},
            ]
        )
        results = router.retrieve({
            "query_id": "Q-table",
            "query_text": "甲公司 2024 流动资产",
            "retrieval_profile": "financial_table",
            "metric_ids": ["current_assets"],
            "periods": ["2024"],
        })
        self.assertEqual([item["evidence_id"] for item in results], ["table"])
        self.assertEqual(results[0]["route"], "table")
        self.assertEqual(results[0]["matched_metric_ids"], ["current_assets"])

    def test_router_uses_structured_worker_and_applies_scope(self) -> None:
        router = RetrievalRouter(
            [
                {"evidence_id": "ratio", "content": "流动比率=1.5", "evidence_type": "table", "metric_ids": ["current_ratio"], "period": "2024", "document_id": "D1", "structured": True},
                {"evidence_id": "outside", "content": "流动比率=2.0", "evidence_type": "table", "metric_ids": ["current_ratio"], "period": "2024", "document_id": "D2", "structured": True},
                {"evidence_id": "singular", "content": "1.7", "evidence_type": "table", "metric_id": "current_ratio", "period": "2024", "document_id": "D1", "structured": True},
            ]
        )
        results = router.retrieve(
            {"query_id": "Q-structured", "retrieval_profile": "structured_data", "metric_ids": ["current_ratio"], "periods": ["2024"]},
            {"allowed_document_ids": ["D1"]},
        )
        self.assertEqual(results[0]["evidence_id"], "ratio")
        self.assertIn("singular", [item["evidence_id"] for item in results])
        self.assertEqual(results[0]["route"], "structured")

    def test_runtime_top_k_is_bounded_at_retrieval_boundary(self) -> None:
        service = HybridSearchService(self.candidates)
        with self.assertRaises(ValueError):
            service.retrieve({"query_text": "流动资产", "dense_top_k": 1000})


if __name__ == "__main__":
    unittest.main()
