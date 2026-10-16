"""
RAG检索优化 - 提升向量检索和混合检索性能
"""
from typing import List, Dict, Tuple
import numpy as np
from functools import lru_cache
import hashlib


class RetrievalOptimizer:
    """检索优化器"""

    def __init__(self):
        self.query_cache = {}
        self.embedding_cache = {}

    @lru_cache(maxsize=1000)
    def get_query_hash(self, query: str) -> str:
        """生成查询哈希用于缓存"""
        return hashlib.md5(query.encode()).hexdigest()

    def cache_embeddings(self, text: str, embedding: np.ndarray):
        """缓存文本的向量表示"""
        key = self.get_query_hash(text)
        self.embedding_cache[key] = embedding

    def get_cached_embedding(self, text: str) -> np.ndarray | None:
        """获取缓存的向量"""
        key = self.get_query_hash(text)
        return self.embedding_cache.get(key)

    def optimize_query(self, query: str) -> str:
        """优化查询文本"""
        # 移除多余空格
        query = ' '.join(query.split())

        # 移除特殊字符（保留中文、英文、数字）
        # 可根据业务需求调整

        return query.strip()

    def rerank_results(
        self,
        results: List[Dict],
        query: str,
        weights: Dict[str, float] = None
    ) -> List[Dict]:
        """
        重新排序检索结果

        Args:
            results: 检索结果列表
            query: 查询文本
            weights: 评分权重 {'relevance': 0.5, 'recency': 0.3, 'authority': 0.2}
        """
        if not weights:
            weights = {'relevance': 0.7, 'recency': 0.2, 'quality': 0.1}

        scored_results = []
        for result in results:
            score = 0.0

            # 相关性得分（基于原始检索分数）
            relevance_score = result.get('score', 0.0)
            score += relevance_score * weights.get('relevance', 0.7)

            # 新近度得分（如果有时间信息）
            if 'timestamp' in result:
                recency_score = self._calculate_recency_score(result['timestamp'])
                score += recency_score * weights.get('recency', 0.2)

            # 质量得分（文档长度、结构等）
            quality_score = self._calculate_quality_score(result)
            score += quality_score * weights.get('quality', 0.1)

            scored_results.append((score, result))

        # 按得分排序
        scored_results.sort(key=lambda x: x[0], reverse=True)
        return [result for _, result in scored_results]

    def _calculate_recency_score(self, timestamp: str) -> float:
        """计算新近度得分"""
        from datetime import datetime
        try:
            doc_time = datetime.fromisoformat(timestamp)
            now = datetime.now()
            days_old = (now - doc_time).days

            # 越新得分越高，衰减函数
            return max(0.0, 1.0 - days_old / 365.0)
        except:
            return 0.5  # 默认中等得分

    def _calculate_quality_score(self, result: Dict) -> float:
        """计算文档质量得分"""
        score = 0.5  # 基础分

        # 文档长度合理性
        content = result.get('content', '')
        if 100 < len(content) < 5000:
            score += 0.2

        # 有明确来源
        if result.get('source'):
            score += 0.2

        # 有页码信息
        if result.get('page_number'):
            score += 0.1

        return min(1.0, score)

    def deduplicate_results(
        self,
        results: List[Dict],
        similarity_threshold: float = 0.95
    ) -> List[Dict]:
        """
        去除重复结果

        Args:
            results: 检索结果
            similarity_threshold: 相似度阈值
        """
        if not results:
            return []

        unique_results = [results[0]]

        for result in results[1:]:
            is_duplicate = False
            for unique in unique_results:
                if self._is_similar(result, unique, similarity_threshold):
                    is_duplicate = True
                    break

            if not is_duplicate:
                unique_results.append(result)

        return unique_results

    def _is_similar(self, doc1: Dict, doc2: Dict, threshold: float) -> bool:
        """判断两个文档是否相似"""
        content1 = doc1.get('content', '')
        content2 = doc2.get('content', '')

        # 简单的文本重叠率计算
        if not content1 or not content2:
            return False

        # 计算共同字符比例
        set1 = set(content1)
        set2 = set(content2)

        if not set1 or not set2:
            return False

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        jaccard_sim = intersection / union if union > 0 else 0
        return jaccard_sim > threshold

    def expand_query(self, query: str, synonyms: Dict[str, List[str]] = None) -> List[str]:
        """
        查询扩展 - 生成同义词查询

        Args:
            query: 原始查询
            synonyms: 同义词字典
        """
        expanded = [query]

        if not synonyms:
            # 金融领域常见同义词
            synonyms = {
                '营业收入': ['营收', '收入', '销售收入'],
                '净利润': ['利润', '盈利', '净收益'],
                '资产': ['总资产'],
                '负债': ['债务', '欠款'],
                '现金流': ['资金流', '现金'],
            }

        for term, syns in synonyms.items():
            if term in query:
                for syn in syns:
                    expanded.append(query.replace(term, syn))

        return list(set(expanded))  # 去重

    def get_cache_stats(self) -> Dict:
        """获取缓存统计"""
        return {
            'query_cache_size': len(self.query_cache),
            'embedding_cache_size': len(self.embedding_cache),
        }

    def clear_cache(self):
        """清空缓存"""
        self.query_cache.clear()
        self.embedding_cache.clear()


class HybridSearchOptimizer:
    """混合检索优化器 - BM25 + 向量检索"""

    def __init__(self, alpha: float = 0.5):
        """
        Args:
            alpha: BM25和向量检索的权重平衡 (0-1)
                  0.5 表示各占50%
        """
        self.alpha = alpha

    def fuse_scores(
        self,
        bm25_results: List[Tuple[str, float]],
        vector_results: List[Tuple[str, float]],
        method: str = 'rrf'
    ) -> List[Tuple[str, float]]:
        """
        融合BM25和向量检索结果

        Args:
            bm25_results: [(doc_id, score), ...]
            vector_results: [(doc_id, score), ...]
            method: 'rrf' (Reciprocal Rank Fusion) 或 'weighted'
        """
        if method == 'rrf':
            return self._reciprocal_rank_fusion(bm25_results, vector_results)
        elif method == 'weighted':
            return self._weighted_fusion(bm25_results, vector_results)
        else:
            raise ValueError(f"Unknown fusion method: {method}")

    def _reciprocal_rank_fusion(
        self,
        bm25_results: List[Tuple[str, float]],
        vector_results: List[Tuple[str, float]],
        k: int = 60
    ) -> List[Tuple[str, float]]:
        """
        RRF融合算法

        score = 1/(k + rank_bm25) + 1/(k + rank_vector)
        """
        scores = {}

        # BM25排名得分
        for rank, (doc_id, _) in enumerate(bm25_results, 1):
            scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank)

        # 向量检索排名得分
        for rank, (doc_id, _) in enumerate(vector_results, 1):
            scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank)

        # 排序
        sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_results

    def _weighted_fusion(
        self,
        bm25_results: List[Tuple[str, float]],
        vector_results: List[Tuple[str, float]]
    ) -> List[Tuple[str, float]]:
        """
        加权融合

        score = alpha * norm_bm25_score + (1-alpha) * norm_vector_score
        """
        # 归一化分数
        bm25_scores = self._normalize_scores(dict(bm25_results))
        vector_scores = self._normalize_scores(dict(vector_results))

        # 合并所有文档ID
        all_doc_ids = set(bm25_scores.keys()) | set(vector_scores.keys())

        # 计算加权得分
        fused = {}
        for doc_id in all_doc_ids:
            bm25_score = bm25_scores.get(doc_id, 0.0)
            vector_score = vector_scores.get(doc_id, 0.0)
            fused[doc_id] = self.alpha * bm25_score + (1 - self.alpha) * vector_score

        # 排序
        sorted_results = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        return sorted_results

    def _normalize_scores(self, scores: Dict[str, float]) -> Dict[str, float]:
        """Min-Max归一化"""
        if not scores:
            return {}

        values = list(scores.values())
        min_val = min(values)
        max_val = max(values)

        if max_val == min_val:
            return {k: 1.0 for k in scores.keys()}

        return {
            k: (v - min_val) / (max_val - min_val)
            for k, v in scores.items()
        }


# 单例
retrieval_optimizer = RetrievalOptimizer()
hybrid_optimizer = HybridSearchOptimizer(alpha=0.5)
