"""
后端优化集成示例 - 应用到现有工作台
"""
from pathlib import Path
import os
import sys

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from credit_review.workbench.app import create_workbench_app
from credit_review.infrastructure.backend_optimizer import (
    setup_optimizations,
    optimize_database
)


def create_optimized_workbench_app(root=None, backend=None, gateway_factory=None):
    """
    创建优化版工作台应用

    这是对原有 create_workbench_app 的增强版本
    """
    # 创建原始应用
    app = create_workbench_app(root=root, backend=backend, gateway_factory=gateway_factory)

    # 应用所有优化
    setup_optimizations(
        app=app,
        store=app.state.store,
        enable_performance_monitoring=True,
        enable_request_logging=True,
        enable_compression=True,
        enable_database_optimization=True
    )

    # 添加优化相关的API端点
    add_optimization_endpoints(app)

    return app


def add_optimization_endpoints(app):
    """添加优化管理端点"""
    from fastapi.responses import JSONResponse
    from credit_review.infrastructure.query_optimizer import (
        get_query_stats,
        clear_query_cache
    )
    from credit_review.infrastructure.performance_monitor import (
        get_performance_report,
        monitor
    )

    @app.get('/v1/admin/optimization/status')
    async def optimization_status():
        """获取优化状态总览"""
        return {
            'optimization_enabled': True,
            'features': {
                'performance_monitoring': True,
                'query_caching': True,
                'request_logging': True,
                'response_compression': True,
                'database_optimization': True
            },
            'stats': {
                'query': get_query_stats(),
                'performance': get_performance_report()
            }
        }

    @app.post('/v1/admin/optimization/clear-cache')
    async def clear_all_caches():
        """清空所有缓存"""
        clear_query_cache()
        monitor.reset()

        from credit_review.infrastructure.async_optimizer import caching_service
        caching_service.clear_cache()

        return {'status': 'success', 'message': '所有缓存已清空'}

    @app.get('/v1/admin/optimization/recommendations')
    async def get_recommendations():
        """获取优化建议"""
        recommendations = []

        # 检查慢查询
        stats = get_query_stats()
        if stats.get('slow_queries_count', 0) > 10:
            recommendations.append({
                'type': 'warning',
                'category': 'database',
                'message': f"检测到 {stats['slow_queries_count']} 个慢查询，建议优化数据库索引"
            })

        # 检查缓存命中率
        if 'hit_rate' in stats:
            hit_rate = float(stats['hit_rate'].rstrip('%'))
            if hit_rate < 50:
                recommendations.append({
                    'type': 'info',
                    'category': 'cache',
                    'message': f"缓存命中率较低 ({stats['hit_rate']})，建议增加缓存时间"
                })

        # 检查性能
        perf = get_performance_report()
        system = perf.get('system', {})
        if system.get('memory_mb', 0) > 1000:
            recommendations.append({
                'type': 'warning',
                'category': 'memory',
                'message': f"内存使用较高 ({system['memory_mb']}MB)，建议监控内存泄漏"
            })

        if not recommendations:
            recommendations.append({
                'type': 'success',
                'category': 'general',
                'message': '系统运行正常，暂无优化建议'
            })

        return {'recommendations': recommendations}


# 使用示例
if __name__ == '__main__':
    """
    启动优化版工作台

    用法：
        python -m credit_review.infrastructure.optimized_app
    """
    import uvicorn

    # 创建优化版应用
    app = create_optimized_workbench_app()

    # 启动服务
    uvicorn.run(
        app,
        host='127.0.0.1',
        port=8000,
        log_level='info',
        access_log=True
    )
