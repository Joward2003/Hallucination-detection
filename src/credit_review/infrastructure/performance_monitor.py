"""
性能监控中间件 - 追踪API性能、慢请求、资源使用
"""
import time
import psutil
import functools
from typing import Callable, Dict, List
from datetime import datetime
from collections import defaultdict, deque


class PerformanceMonitor:
    """性能监控器"""

    def __init__(self, max_records: int = 1000):
        self.max_records = max_records
        self.metrics = defaultdict(lambda: {
            'count': 0,
            'total_time': 0.0,
            'min_time': float('inf'),
            'max_time': 0.0,
            'errors': 0,
            'recent_times': deque(maxlen=100)
        })
        self.slow_requests = deque(maxlen=100)
        self.error_log = deque(maxlen=100)

    def record(self, endpoint: str, duration: float, status: str = 'success'):
        """记录请求性能"""
        metric = self.metrics[endpoint]
        metric['count'] += 1
        metric['total_time'] += duration
        metric['min_time'] = min(metric['min_time'], duration)
        metric['max_time'] = max(metric['max_time'], duration)
        metric['recent_times'].append(duration)

        if status == 'error':
            metric['errors'] += 1
            self.error_log.append({
                'endpoint': endpoint,
                'timestamp': datetime.now().isoformat(),
                'duration': duration
            })

        # 记录慢请求（超过2秒）
        if duration > 2.0:
            self.slow_requests.append({
                'endpoint': endpoint,
                'duration': duration,
                'timestamp': datetime.now().isoformat()
            })

    def get_stats(self, endpoint: str = None) -> Dict:
        """获取统计数据"""
        if endpoint:
            return self._endpoint_stats(endpoint)

        # 返回所有端点统计
        return {
            'endpoints': {
                ep: self._endpoint_stats(ep)
                for ep in self.metrics.keys()
            },
            'slow_requests': list(self.slow_requests)[-20:],
            'recent_errors': list(self.error_log)[-20:],
            'system': self._system_stats()
        }

    def _endpoint_stats(self, endpoint: str) -> Dict:
        """计算单个端点的统计"""
        metric = self.metrics[endpoint]
        if metric['count'] == 0:
            return {'count': 0}

        avg_time = metric['total_time'] / metric['count']
        recent = list(metric['recent_times'])
        recent.sort()

        return {
            'count': metric['count'],
            'avg_time': round(avg_time, 3),
            'min_time': round(metric['min_time'], 3),
            'max_time': round(metric['max_time'], 3),
            'p50': round(recent[len(recent) // 2], 3) if recent else 0,
            'p95': round(recent[int(len(recent) * 0.95)], 3) if recent else 0,
            'p99': round(recent[int(len(recent) * 0.99)], 3) if recent else 0,
            'error_rate': round(metric['errors'] / metric['count'] * 100, 2),
            'errors': metric['errors']
        }

    def _system_stats(self) -> Dict:
        """获取系统资源使用情况"""
        try:
            process = psutil.Process()
            return {
                'cpu_percent': process.cpu_percent(interval=0.1),
                'memory_mb': round(process.memory_info().rss / 1024 / 1024, 2),
                'threads': process.num_threads(),
                'open_files': len(process.open_files()),
            }
        except Exception:
            return {}

    def reset(self):
        """重置所有统计"""
        self.metrics.clear()
        self.slow_requests.clear()
        self.error_log.clear()


# 全局监控实例
monitor = PerformanceMonitor()


def track_performance(endpoint_name: str = None):
    """
    性能追踪装饰器

    Usage:
        @track_performance('review_task')
        async def process_review(task_id):
            ...
    """
    def decorator(func: Callable) -> Callable:
        name = endpoint_name or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            status = 'success'
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = 'error'
                raise
            finally:
                duration = time.time() - start
                monitor.record(name, duration, status)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            status = 'success'
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                status = 'error'
                raise
            finally:
                duration = time.time() - start
                monitor.record(name, duration, status)

        # 检测是否为异步函数
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# FastAPI 中间件
async def performance_middleware(request, call_next):
    """FastAPI性能监控中间件"""
    start = time.time()
    status = 'success'

    try:
        response = await call_next(request)
        if response.status_code >= 400:
            status = 'error'
        return response
    except Exception as e:
        status = 'error'
        raise
    finally:
        duration = time.time() - start
        endpoint = f"{request.method} {request.url.path}"
        monitor.record(endpoint, duration, status)


class RequestLogger:
    """请求日志记录器 - 结构化日志"""

    def __init__(self):
        self.requests = deque(maxlen=1000)

    def log(self, request_data: Dict):
        """记录请求"""
        self.requests.append({
            **request_data,
            'timestamp': datetime.now().isoformat()
        })

    def get_recent(self, limit: int = 50) -> List[Dict]:
        """获取最近的请求"""
        return list(self.requests)[-limit:]

    def filter_by_endpoint(self, endpoint: str) -> List[Dict]:
        """按端点过滤"""
        return [r for r in self.requests if endpoint in r.get('endpoint', '')]

    def filter_by_status(self, status_code: int) -> List[Dict]:
        """按状态码过滤"""
        return [r for r in self.requests if r.get('status_code') == status_code]


request_logger = RequestLogger()


def get_performance_report() -> Dict:
    """生成性能报告"""
    stats = monitor.get_stats()

    # 找出最慢的端点
    endpoints = stats.get('endpoints', {})
    slowest = sorted(
        [(ep, data.get('avg_time', 0)) for ep, data in endpoints.items()],
        key=lambda x: x[1],
        reverse=True
    )[:10]

    # 找出错误率最高的端点
    highest_error_rate = sorted(
        [(ep, data.get('error_rate', 0)) for ep, data in endpoints.items()],
        key=lambda x: x[1],
        reverse=True
    )[:10]

    return {
        'summary': {
            'total_endpoints': len(endpoints),
            'total_requests': sum(data.get('count', 0) for data in endpoints.values()),
            'total_errors': sum(data.get('errors', 0) for data in endpoints.values()),
        },
        'slowest_endpoints': [
            {'endpoint': ep, 'avg_time': time}
            for ep, time in slowest if time > 0
        ],
        'highest_error_rate': [
            {'endpoint': ep, 'error_rate': rate}
            for ep, rate in highest_error_rate if rate > 0
        ],
        'recent_slow_requests': stats.get('slow_requests', []),
        'system': stats.get('system', {})
    }


# 内存缓存监控
class CacheMonitor:
    """缓存性能监控"""

    def __init__(self):
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'deletes': 0,
            'size': 0
        }

    def record_hit(self):
        self.stats['hits'] += 1

    def record_miss(self):
        self.stats['misses'] += 1

    def record_set(self):
        self.stats['sets'] += 1

    def record_delete(self):
        self.stats['deletes'] += 1

    def update_size(self, size: int):
        self.stats['size'] = size

    def get_stats(self) -> Dict:
        total = self.stats['hits'] + self.stats['misses']
        hit_rate = (self.stats['hits'] / total * 100) if total > 0 else 0

        return {
            **self.stats,
            'hit_rate': round(hit_rate, 2),
            'total_requests': total
        }

    def reset(self):
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'deletes': 0,
            'size': 0
        }


cache_monitor = CacheMonitor()
