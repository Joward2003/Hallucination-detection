from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_review.infrastructure.bm25_service import BM25SService
from credit_review.infrastructure.embeddings import SentenceTransformerDenseRetriever, SentenceTransformerEmbedder
from credit_review.infrastructure.index_builder import ProductionIndexBuilder
from credit_review.infrastructure.rerankers import SentenceTransformerCrossEncoder
from credit_review.infrastructure.retrieval_stack import create_production_hybrid_search
from credit_review.config.models import RetrievalConfig


class FakeEmbeddingModel:
    def encode(self, texts, **kwargs):
        return [[1.0, 0.0] if "流动" in text or "甲" in text else [0.0, 1.0] for text in texts]


class FakeTokenizer:
    def tokenize(self, texts, **kwargs):
        return texts

    def save_vocab(self, save_dir):
        Path(save_dir, "vocab.json").write_text("{}", encoding="utf-8")

    def load_vocab(self, save_dir):
        return None


class FakeBM25:
    def __init__(self):
        self.indexed = None

    def index(self, tokenized):
        self.indexed = tokenized

    def retrieve(self, query_tokens, k):
        return [[1, 0]][:1], [[4.0, 2.0]][:1]

    def save(self, path):
        Path(path, "params.index.json").write_text("{}", encoding="utf-8")


class FakeCrossEncoder:
    def predict(self, pairs, **kwargs):
        return [0.2 if "流动" in document else 2.0 for _, document in pairs]


class RealRetrievalAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = [
            {"evidence_id": "E1", "content": "甲公司流动资产120亿元", "document_id": "D1"},
            {"evidence_id": "E2", "content": "乙公司市场竞争力较强", "document_id": "D2"},
        ]

    def test_sentence_transformer_dense_retriever_uses_model_and_scope(self) -> None:
        embedder = SentenceTransformerEmbedder(model=FakeEmbeddingModel())
        retriever = SentenceTransformerDenseRetriever(self.candidates, embedder, top_k=2)
        hits = retriever.retrieve("甲公司流动资产", {"allowed_document_ids": ["D1"]})
        self.assertEqual([item["evidence_id"] for item in hits], ["E1"])
        self.assertEqual(hits[0]["embedding_model"], "BAAI/bge-m3")

    def test_dense_index_can_be_saved_and_loaded_only_with_same_model_and_ids(self) -> None:
        embedder = SentenceTransformerEmbedder(model=FakeEmbeddingModel())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dense.json"
            SentenceTransformerDenseRetriever(self.candidates, embedder, index_path=path, persist_if_built=True)
            loaded = SentenceTransformerDenseRetriever(self.candidates, embedder, index_path=path)
            self.assertEqual(loaded.retrieve("甲公司")[0]["evidence_id"], "E1")

    def test_bm25s_service_uses_persistent_index_contract_and_scope(self) -> None:
        service = BM25SService(self.candidates, index=FakeBM25(), tokenizer=FakeTokenizer(), top_k=2)
        hits = service.retrieve("甲公司", {"allowed_document_ids": ["D1"]})
        self.assertEqual([item["evidence_id"] for item in hits], ["E1"])
        self.assertEqual(hits[0]["route"], "bm25")

    def test_cross_encoder_reranker_scores_query_document_pairs(self) -> None:
        reranker = SentenceTransformerCrossEncoder(model=FakeCrossEncoder())
        ranked = reranker.rank("市场", self.candidates, top_n=2)
        self.assertEqual(ranked[0]["evidence_id"], "E2")
        self.assertEqual(ranked[0]["reranker_model"], "BAAI/bge-reranker-v2-m3")

    def test_production_factory_wires_all_three_real_adapter_ports(self) -> None:
        dense = SentenceTransformerDenseRetriever(
            self.candidates,
            SentenceTransformerEmbedder(model=FakeEmbeddingModel()),
            top_k=2,
        )
        lexical = BM25SService(self.candidates, index=FakeBM25(), tokenizer=FakeTokenizer(), top_k=2)
        reranker = SentenceTransformerCrossEncoder(model=FakeCrossEncoder())
        service = create_production_hybrid_search(
            self.candidates,
            dense_retriever=dense,
            lexical_retriever=lexical,
            reranker=reranker,
        )
        hits = service.retrieve({"query_text": "甲公司流动资产", "rerank_top_n": 2})
        self.assertTrue(hits)
        self.assertEqual(hits[0]["reranker_model"], "BAAI/bge-reranker-v2-m3")

    def test_production_index_builder_persists_dense_and_lexical_refs(self) -> None:
        calls = []

        def fake_bm25_factory(candidates, **kwargs):
            path = Path(kwargs["index_path"])
            path.mkdir(parents=True)
            (path / "manifest.json").write_text("{}", encoding="utf-8")
            calls.append(len(candidates))

        with tempfile.TemporaryDirectory() as directory:
            builder = ProductionIndexBuilder(
                directory,
                config=RetrievalConfig(backend="sentence_transformers"),
                embedder=SentenceTransformerEmbedder(model=FakeEmbeddingModel()),
                bm25_service_factory=fake_bm25_factory,
            )
            snapshot = {"evidence": self.candidates, "manifest": {"status": "READY"}}
            refs = builder.build("kb", "v1", snapshot)
            self.assertTrue(Path(refs["dense_index_ref"]).exists())
            self.assertTrue(Path(refs["bm25_index_ref"]).exists())
            self.assertEqual(calls, [2])

    def test_production_factory_requires_explicit_production_backend(self) -> None:
        with self.assertRaises(ValueError):
            create_production_hybrid_search(
                self.candidates,
                config=RetrievalConfig(backend="deterministic"),
                dense_retriever=object(),
                lexical_retriever=object(),
                reranker=object(),
            )


if __name__ == "__main__":
    unittest.main()
