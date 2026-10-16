"""
异步任务优化 - 提升复核任务执行效率
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Callable, Any, Optional
import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """任务结果"""
    task_id: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    duration: float = 0.0


class AsyncTaskQueue:
    """
    异步任务队列 - 批量处理复核任务
    """

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix='review-worker'
        )
        self.pending_tasks = []
        self.completed_tasks = []

    async def submit(self, task_id: str, func: Callable, *args, **kwargs) -> TaskResult:
        """
        提交异步任务

        Args:
            task_id: 任务ID
            func: 要执行的函数
            *args, **kwargs: 函数参数

        Returns:
            TaskResult: 任务结果
        """
        start_time = datetime.now()

        try:
            # 在线程池中执行
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.executor,
                func,
                *args
            )

            duration = (datetime.now() - start_time).total_seconds()

            return TaskResult(
                task_id=task_id,
                success=True,
                result=result,
                duration=duration
            )

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"Task {task_id} failed: {e}", exc_info=True)

            return TaskResult(
                task_id=task_id,
                success=False,
                error=str(e),
                duration=duration
            )

    async def batch_submit(
        self,
        tasks: List[tuple[str, Callable, tuple, dict]]
    ) -> List[TaskResult]:
        """
        批量提交任务并等待完成

        Args:
            tasks: [(task_id, func, args, kwargs), ...]

        Returns:
            List[TaskResult]: 所有任务结果
        """
        results = []

        # 创建所有任务
        task_futures = [
            self.submit(task_id, func, *args, **kwargs)
            for task_id, func, args, kwargs in tasks
        ]

        # 等待所有任务完成
        results = await asyncio.gather(*task_futures, return_exceptions=True)

        # 统计
        success_count = sum(1 for r in results if isinstance(r, TaskResult) and r.success)
        logger.info(f"Batch completed: {success_count}/{len(tasks)} successful")

        return results

    def shutdown(self, wait: bool = True):
        """关闭执行器"""
        self.executor.shutdown(wait=wait)


class EvidenceRetrievalOptimizer:
    """
    证据检索优化器 - 并行检索提升速度
    """

    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def retrieve_evidence(
        self,
        claim: str,
        retriever: Callable,
        **kwargs
    ) -> dict:
        """
        单个证据检索（带并发控制）

        Args:
            claim: 待验证的结论
            retriever: 检索函数
            **kwargs: 检索参数

        Returns:
            dict: 检索结果
        """
        async with self.semaphore:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                retriever,
                claim,
                **kwargs
            )

    async def batch_retrieve(
        self,
        claims: List[str],
        retriever: Callable,
        **kwargs
    ) -> List[dict]:
        """
        批量并行检索证据

        Args:
            claims: 待验证的结论列表
            retriever: 检索函数
            **kwargs: 检索参数

        Returns:
            List[dict]: 检索结果列表
        """
        logger.info(f"Starting batch retrieval for {len(claims)} claims")
        start_time = datetime.now()

        # 创建所有检索任务
        tasks = [
            self.retrieve_evidence(claim, retriever, **kwargs)
            for claim in claims
        ]

        # 并行执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Batch retrieval completed in {duration:.2f}s")

        return results


class CachingReviewService:
    """
    带缓存的复核服务 - 避免重复计算
    """

    def __init__(self, ttl: int = 3600):
        self.cache = {}
        self.ttl = ttl  # 缓存过期时间（秒）

    def _cache_key(self, claim: str, kb_version: str) -> str:
        """生成缓存键"""
        import hashlib
        data = f"{claim}:{kb_version}"
        return hashlib.md5(data.encode()).hexdigest()

    def get_cached(self, claim: str, kb_version: str) -> Optional[dict]:
        """获取缓存的复核结果"""
        key = self._cache_key(claim, kb_version)

        if key in self.cache:
            cached_time, result = self.cache[key]

            # 检查是否过期
            if (datetime.now() - cached_time).total_seconds() < self.ttl:
                logger.debug(f"Cache hit for claim: {claim[:50]}...")
                return result
            else:
                # 过期，删除
                del self.cache[key]

        return None

    def cache_result(self, claim: str, kb_version: str, result: dict):
        """缓存复核结果"""
        key = self._cache_key(claim, kb_version)
        self.cache[key] = (datetime.now(), result)

        # 限制缓存大小
        if len(self.cache) > 1000:
            # 删除最旧的项
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][0])
            del self.cache[oldest_key]

    def clear_cache(self):
        """清空缓存"""
        self.cache.clear()
        logger.info("Review cache cleared")


class ProgressTracker:
    """
    进度追踪器 - 实时追踪复核进度
    """

    def __init__(self, total_steps: int):
        self.total_steps = total_steps
        self.current_step = 0
        self.start_time = datetime.now()
        self.step_times = []

    def update(self, step: int, message: str = ""):
        """更新进度"""
        self.current_step = step
        self.step_times.append(datetime.now())

        elapsed = (datetime.now() - self.start_time).total_seconds()
        progress = (step / self.total_steps) * 100

        # 估算剩余时间
        if step > 0:
            avg_time_per_step = elapsed / step
            remaining_steps = self.total_steps - step
            eta_seconds = avg_time_per_step * remaining_steps
            eta_minutes = eta_seconds / 60
        else:
            eta_minutes = 0

        logger.info(
            f"Progress: {progress:.1f}% ({step}/{self.total_steps}) "
            f"ETA: {eta_minutes:.1f}min {message}"
        )

    def complete(self):
        """标记完成"""
        duration = (datetime.now() - self.start_time).total_seconds()
        logger.info(f"Task completed in {duration:.2f}s")

        return {
            'total_duration': duration,
            'steps': self.total_steps,
            'avg_step_time': duration / self.total_steps if self.total_steps > 0 else 0
        }


# 全局任务队列实例
task_queue = AsyncTaskQueue(max_workers=4)
evidence_optimizer = EvidenceRetrievalOptimizer(max_concurrent=5)
caching_service = CachingReviewService(ttl=3600)


def optimize_review_pipeline(review_func: Callable) -> Callable:
    """
    复核流程优化装饰器

    Usage:
        @optimize_review_pipeline
        def run_review(task_id, report_text):
            ...
    """
    async def wrapper(*args, **kwargs):
        task_id = kwargs.get('task_id', 'unknown')

        logger.info(f"Starting optimized review: {task_id}")
        start_time = datetime.now()

        try:
            result = await review_func(*args, **kwargs)
            duration = (datetime.now() - start_time).total_seconds()

            logger.info(f"Review completed: {task_id} in {duration:.2f}s")
            return result

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"Review failed: {task_id} after {duration:.2f}s - {e}")
            raise

    return wrapper
