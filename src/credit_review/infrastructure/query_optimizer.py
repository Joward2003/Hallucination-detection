"""
数据库查询优化器 - 提升查询性能
"""
from functools import wraps
from typing import Any, Callable, Optional
import hashlib
import json
import time
from collections import OrderedDict


class LRUCache:
    """LRU缓存实现"""
    def __init__(self, capacity: int = 1000):
        self.cache = OrderedDict()
        self.capacity = capacity

    def get(self, key: str) -> Optional[Any]:
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key: str, value: Any) -> None:
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

    def clear(self):
        self.cache.clear()


# 全局查询缓存
query_cache = LRUCache(capacity=500)
query_stats = {
    'hits': 0,
    'misses': 0,
    'total_queries': 0,
    'slow_queries': []
}


def cache_key(*args, **kwargs) -> str:
    """生成缓存键"""
    key_data = {
        'args': str(args),
        'kwargs': json.dumps(kwargs, sort_keys=True, default=str)
    }
    return hashlib.md5(json.dumps(key_data).encode()).hexdigest()


def query_cache_decorator(ttl: int = 300):
    """
    查询缓存装饰器

    Args:
        ttl: 缓存过期时间（秒）
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 生成缓存键
            key = f"{func.__name__}:{cache_key(*args, **kwargs)}"

            # 检查缓存
            cached = query_cache.get(key)
            if cached is not None:
                timestamp, result = cached
                if time.time() - timestamp < ttl:
                    query_stats['hits'] += 1
                    return result

            # 执行查询
            query_stats['misses'] += 1
            query_stats['total_queries'] += 1

            start_time = time.time()
            result = func(*args, **kwargs)
            duration = time.time() - start_time

            # 记录慢查询
            if duration > 1.0:  # 超过1秒
                query_stats['slow_queries'].append({
                    'function': func.__name__,
                    'duration': duration,
                    'timestamp': time.time()
                })
                # 只保留最近50条慢查询
                if len(query_stats['slow_queries']) > 50:
                    query_stats['slow_queries'] = query_stats['slow_queries'][-50:]

            # 存入缓存
            query_cache.put(key, (time.time(), result))

            return result
        return wrapper
    return decorator


class QueryBatcher:
    """查询批处理器 - 减少数据库往返次数"""

    def __init__(self, batch_size: int = 100):
        self.batch_size = batch_size
        self.pending = []

    def add(self, query_func: Callable, *args, **kwargs):
        """添加查询到批次"""
        self.pending.append((query_func, args, kwargs))

        if len(self.pending) >= self.batch_size:
            return self.execute()
        return None

    def execute(self):
        """执行批量查询"""
        if not self.pending:
            return []

        results = []
        for query_func, args, kwargs in self.pending:
            try:
                result = query_func(*args, **kwargs)
                results.append(result)
            except Exception as e:
                results.append({'error': str(e)})

        self.pending.clear()
        return results


class ConnectionPool:
    """简单的连接池管理"""

    def __init__(self, max_connections: int = 10):
        self.max_connections = max_connections
        self.active_connections = 0
        self.waiting = []

    def acquire(self):
        """获取连接"""
        if self.active_connections < self.max_connections:
            self.active_connections += 1
            return True
        return False

    def release(self):
        """释放连接"""
        if self.active_connections > 0:
            self.active_connections -= 1


def get_query_stats():
    """获取查询统计信息"""
    total = query_stats['total_queries']
    hits = query_stats['hits']
    misses = query_stats['misses']

    hit_rate = (hits / (hits + misses) * 100) if (hits + misses) > 0 else 0

    return {
        'total_queries': total,
        'cache_hits': hits,
        'cache_misses': misses,
        'hit_rate': f"{hit_rate:.2f}%",
        'slow_queries_count': len(query_stats['slow_queries']),
        'recent_slow_queries': query_stats['slow_queries'][-10:]
    }


def clear_query_cache():
    """清空查询缓存"""
    query_cache.clear()
    query_stats['hits'] = 0
    query_stats['misses'] = 0


# 索引建议
SUGGESTED_INDEXES = {
    'tasks': [
        'CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)',
        'CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC)',
        'CREATE INDEX IF NOT EXISTS idx_tasks_company_period ON tasks(company_name, period)',
    ],
    'documents': [
        'CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(sha256_hash)',
        'CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(document_type)',
    ],
    'audit_log': [
        'CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp DESC)',
        'CREATE INDEX IF NOT EXISTS idx_audit_task_id ON audit_log(task_id)',
    ],
    'knowledge_versions': [
        'CREATE INDEX IF NOT EXISTS idx_kb_status ON knowledge_versions(status)',
        'CREATE INDEX IF NOT EXISTS idx_kb_company ON knowledge_versions(company_name)',
    ]
}


def apply_performance_indexes(connection):
    """应用性能优化索引"""
    applied = []
    for table, indexes in SUGGESTED_INDEXES.items():
        for index_sql in indexes:
            try:
                connection.execute(index_sql)
                applied.append(index_sql)
            except Exception as e:
                print(f"Failed to create index: {e}")

    return applied


# 查询优化建议
def analyze_query_plan(connection, query: str):
    """分析查询计划"""
    try:
        cursor = connection.execute(f"EXPLAIN QUERY PLAN {query}")
        plan = cursor.fetchall()
        return {
            'query': query,
            'plan': plan,
            'recommendations': _generate_recommendations(plan)
        }
    except Exception as e:
        return {'error': str(e)}


def _generate_recommendations(plan):
    """根据查询计划生成优化建议"""
    recommendations = []

    for row in plan:
        detail = str(row).lower()

        if 'scan' in detail and 'index' not in detail:
            recommendations.append("考虑为查询字段添加索引以避免全表扫描")

        if 'temp b-tree' in detail:
            recommendations.append("查询使用了临时B树，考虑创建覆盖索引")

    return recommendations if recommendations else ["查询计划看起来不错"]
