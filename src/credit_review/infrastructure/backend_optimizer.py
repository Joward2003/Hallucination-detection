"""
后端性能优化中间件集成
"""
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
import time
import logging
from typing import Optional

# 导入之前创建的优化模块
from credit_review.infrastructure.performance_monitor import (
    monitor,
    performance_middleware,
    get_performance_report
)
from credit_review.infrastructure.query_optimizer import (
    get_query_stats,
    apply_performance_indexes
)

logger = logging.getLogger(__name__)


def setup_performance_monitoring(app: FastAPI):
    """
    为 FastAPI 应用添加性能监控

    Usage:
        app = FastAPI()
        setup_performance_monitoring(app)
    """

    # 添加性能监控中间件
    app.middleware('http')(performance_middleware)

    # 性能报告端点
    @app.get('/v1/admin/performance')
    async def get_performance():
        """获取性能统计报告"""
        return get_performance_report()

    # 查询缓存统计
    @app.get('/v1/admin/query-stats')
    async def get_query_statistics():
        """获取数据库查询统计"""
        return get_query_stats()

    # 健康检查增强
    @app.get('/v1/admin/health-detailed')
    async def detailed_health():
        """详细健康检查"""
        import psutil
        process = psutil.Process()

        return {
            'status': 'healthy',
            'cpu_percent': process.cpu_percent(interval=0.1),
            'memory_mb': round(process.memory_info().rss / 1024 / 1024, 2),
            'memory_percent': process.memory_percent(),
            'threads': process.num_threads(),
            'open_files': len(process.open_files()),
            'performance': monitor.get_stats()
        }

    logger.info("Performance monitoring enabled")


def optimize_database(store):
    """
    优化数据库性能

    Args:
        store: Storage 实例
    """
    try:
        with store.connect() as conn:
            # 应用索引
            logger.info("Applying performance indexes...")
            applied = apply_performance_indexes(conn)
            logger.info(f"Applied {len(applied)} indexes")

            # 优化 SQLite 配置
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA mmap_size=268435456")  # 256MB mmap

            logger.info("Database optimization completed")
    except Exception as e:
        logger.error(f"Database optimization failed: {e}")


def add_request_logging(app: FastAPI):
    """添加请求日志记录"""

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.time()

        # 记录请求
        logger.info(f"Request: {request.method} {request.url.path}")

        response = await call_next(request)

        # 记录响应时间
        duration = time.time() - start_time
        logger.info(
            f"Response: {request.method} {request.url.path} "
            f"Status={response.status_code} Duration={duration:.3f}s"
        )

        # 慢请求警告
        if duration > 2.0:
            logger.warning(
                f"Slow request detected: {request.method} {request.url.path} "
                f"took {duration:.3f}s"
            )

        return response


def add_error_handling(app: FastAPI):
    """增强错误处理"""

    from fastapi.responses import JSONResponse

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            f"Unhandled exception: {type(exc).__name__}: {str(exc)}",
            exc_info=True
        )

        return JSONResponse(
            status_code=500,
            content={
                'detail': '服务器内部错误',
                'error_type': type(exc).__name__,
                'path': str(request.url.path)
            }
        )


def add_caching_headers(app: FastAPI):
    """为静态资源添加缓存头"""

    @app.middleware("http")
    async def cache_control(request: Request, call_next):
        response = await call_next(request)

        # 静态资源缓存
        if request.url.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'public, max-age=31536000'

        # API 响应不缓存
        elif request.url.path.startswith('/v1/'):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'

        return response


def add_compression(app: FastAPI):
    """添加响应压缩"""
    from fastapi.middleware.gzip import GZipMiddleware

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    logger.info("Response compression enabled")


def add_cors_if_needed(app: FastAPI, allowed_origins: Optional[list] = None):
    """
    添加 CORS 支持（如果需要）

    注意: 本地工作台默认不需要 CORS
    """
    if allowed_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        logger.info(f"CORS enabled for origins: {allowed_origins}")


def setup_optimizations(
    app: FastAPI,
    store=None,
    enable_performance_monitoring: bool = True,
    enable_request_logging: bool = True,
    enable_compression: bool = True,
    enable_database_optimization: bool = True
):
    """
    一键设置所有后端优化

    Usage:
        from credit_review.infrastructure.backend_optimizer import setup_optimizations

        app = create_workbench_app()
        setup_optimizations(app, store=app.state.store)
    """

    logger.info("Setting up backend optimizations...")

    # 性能监控
    if enable_performance_monitoring:
        setup_performance_monitoring(app)

    # 请求日志
    if enable_request_logging:
        add_request_logging(app)

    # 错误处理
    add_error_handling(app)

    # 缓存头
    add_caching_headers(app)

    # 响应压缩
    if enable_compression:
        add_compression(app)

    # 数据库优化
    if enable_database_optimization and store:
        optimize_database(store)

    logger.info("Backend optimizations completed ✓")


# 启动时优化任务
@asynccontextmanager
async def optimized_lifespan(app: FastAPI):
    """
    优化版应用生命周期管理

    Usage:
        app = FastAPI(lifespan=optimized_lifespan)
    """
    # 启动时
    logger.info("Application starting...")

    # 预热
    logger.info("Warming up cache...")

    yield

    # 关闭时
    logger.info("Application shutting down...")
    logger.info("Cleaning up resources...")
