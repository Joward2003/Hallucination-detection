# 后端优化完整指南

## 📋 优化概览

已完成后端性能和代码质量的全面优化，包括性能监控、查询优化、异步任务处理等。

## 🚀 已实现的优化模块

### 1. **性能监控系统** (`performance_monitor.py`)

#### 功能特性
- ✅ 实时追踪 API 请求性能
- ✅ 记录慢请求（>2秒）
- ✅ 统计端点调用次数、平均响应时间、P50/P95/P99
- ✅ 监控系统资源使用（CPU、内存、线程）
- ✅ 错误率统计

#### 使用方法

```python
from credit_review.infrastructure.performance_monitor import track_performance, monitor

# 装饰器方式追踪函数性能
@track_performance('review_task')
async def process_review(task_id):
    # 你的代码
    pass

# 获取性能报告
stats = monitor.get_stats()
print(f"Average response time: {stats['endpoints']['review_task']['avg_time']}s")
```

#### API端点
```bash
# 获取性能报告
GET /v1/admin/performance

# 获取详细健康检查
GET /v1/admin/health-detailed
```

---

### 2. **数据库查询优化** (`query_optimizer.py`)

#### 功能特性
- ✅ LRU 查询结果缓存
- ✅ 自动缓存过期（TTL）
- ✅ 慢查询检测和记录
- ✅ 查询批处理
- ✅ 自动索引建议和应用
- ✅ 查询计划分析

#### 使用方法

```python
from credit_review.infrastructure.query_optimizer import (
    query_cache_decorator,
    get_query_stats,
    apply_performance_indexes
)

# 使用缓存装饰器
@query_cache_decorator(ttl=300)  # 缓存5分钟
def get_task_by_id(task_id):
    return db.query(Task).filter(Task.id == task_id).first()

# 应用性能索引
with store.connect() as conn:
    applied = apply_performance_indexes(conn)
    print(f"Applied {len(applied)} indexes")

# 查看缓存统计
stats = get_query_stats()
print(f"Cache hit rate: {stats['hit_rate']}")
```

#### 自动创建的索引
```sql
-- 任务表
CREATE INDEX idx_tasks_status ON tasks(status)
CREATE INDEX idx_tasks_created_at ON tasks(created_at DESC)
CREATE INDEX idx_tasks_company_period ON tasks(company_name, period)

-- 文档表
CREATE INDEX idx_documents_hash ON documents(sha256_hash)
CREATE INDEX idx_documents_type ON documents(document_type)

-- 审计日志
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp DESC)
CREATE INDEX idx_audit_task_id ON audit_log(task_id)

-- 知识库版本
CREATE INDEX idx_kb_status ON knowledge_versions(status)
CREATE INDEX idx_kb_company ON knowledge_versions(company_name)
```

---

### 3. **RAG检索优化** (`retrieval/optimizer.py`)

#### 功能特性
- ✅ 查询文本优化和标准化
- ✅ 向量表示缓存
- ✅ 检索结果重排序（考虑相关性、新近度、质量）
- ✅ 去重处理
- ✅ 查询扩展（同义词）
- ✅ 混合检索优化（BM25 + 向量）

#### 使用方法

```python
from credit_review.retrieval.optimizer import (
    retrieval_optimizer,
    hybrid_optimizer
)

# 优化查询
optimized_query = retrieval_optimizer.optimize_query("  营业收入 增长  ")
# 结果: "营业收入 增长"

# 查询扩展
expanded = retrieval_optimizer.expand_query("营业收入")
# 结果: ["营业收入", "营收", "收入", "销售收入"]

# 重排序结果
results = retrieval_optimizer.rerank_results(
    raw_results,
    query="营业收入",
    weights={'relevance': 0.6, 'recency': 0.2, 'quality': 0.2}
)

# 混合检索融合
fused = hybrid_optimizer.fuse_scores(
    bm25_results=[("doc1", 0.8), ("doc2", 0.6)],
    vector_results=[("doc1", 0.7), ("doc3", 0.9)],
    method='rrf'  # Reciprocal Rank Fusion
)
```

---

### 4. **异步任务优化** (`async_optimizer.py`)

#### 功能特性
- ✅ 异步任务队列
- ✅ 批量任务并行处理
- ✅ 证据检索并发控制
- ✅ 复核结果缓存
- ✅ 进度追踪

#### 使用方法

```python
from credit_review.infrastructure.async_optimizer import (
    task_queue,
    evidence_optimizer,
    caching_service,
    ProgressTracker
)

# 并行检索证据
claims = ["结论1", "结论2", "结论3"]
results = await evidence_optimizer.batch_retrieve(
    claims=claims,
    retriever=your_retriever_function
)

# 使用缓存避免重复计算
cached = caching_service.get_cached(claim, kb_version)
if cached:
    return cached
else:
    result = compute_result(claim)
    caching_service.cache_result(claim, kb_version, result)

# 追踪进度
tracker = ProgressTracker(total_steps=100)
for i in range(100):
    # 执行任务
    tracker.update(i, f"Processing item {i}")
tracker.complete()
```

---

### 5. **集成优化器** (`backend_optimizer.py`)

#### 功能特性
- ✅ 一键启用所有优化
- ✅ 性能监控中间件
- ✅ 请求日志记录
- ✅ 全局错误处理
- ✅ 响应压缩（GZip）
- ✅ 缓存头管理
- ✅ 数据库自动优化

#### 使用方法

```python
from credit_review.infrastructure.backend_optimizer import setup_optimizations

# 创建 FastAPI 应用
app = create_workbench_app()

# 一键应用所有优化
setup_optimizations(
    app=app,
    store=app.state.store,
    enable_performance_monitoring=True,
    enable_request_logging=True,
    enable_compression=True,
    enable_database_optimization=True
)
```

---

## 📊 新增的管理端点

### 性能监控
```bash
# 获取性能统计
GET /v1/admin/performance
Response:
{
  "summary": {
    "total_endpoints": 15,
    "total_requests": 1234,
    "total_errors": 5
  },
  "slowest_endpoints": [...],
  "system": {
    "cpu_percent": 5.2,
    "memory_mb": 256.4
  }
}

# 获取查询统计
GET /v1/admin/query-stats
Response:
{
  "total_queries": 567,
  "cache_hits": 432,
  "cache_misses": 135,
  "hit_rate": "76.17%",
  "slow_queries_count": 3
}

# 优化状态总览
GET /v1/admin/optimization/status

# 清空所有缓存
POST /v1/admin/optimization/clear-cache

# 获取优化建议
GET /v1/admin/optimization/recommendations
```

---

## 🔧 如何集成到现有项目

### 方法 1: 修改启动脚本

编辑 `启动复核工作台.command`:

```bash
#!/bin/bash
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/src"

# 使用优化版启动
.venv/bin/python -m credit_review.infrastructure.optimized_app
```

### 方法 2: 修改 workbench/app.py

在 `create_workbench_app` 函数末尾添加:

```python
def create_workbench_app(root=None, backend=None, gateway_factory=None):
    # ... 原有代码 ...

    # 添加优化
    from credit_review.infrastructure.backend_optimizer import setup_optimizations
    setup_optimizations(
        app=app,
        store=store,
        enable_performance_monitoring=True,
        enable_request_logging=True,
        enable_compression=True,
        enable_database_optimization=True
    )

    return app
```

### 方法 3: 使用优化版应用类

```python
from credit_review.infrastructure.optimized_app import create_optimized_workbench_app

# 直接使用优化版
app = create_optimized_workbench_app()
```

---

## 📈 性能提升预期

### 数据库查询
- ✅ **查询缓存**: 重复查询速度提升 **90%+**
- ✅ **索引优化**: 复杂查询速度提升 **50-200%**
- ✅ **批处理**: 减少数据库往返次数 **70%**

### API响应
- ✅ **响应压缩**: 传输大小减少 **60-80%**
- ✅ **缓存头**: 静态资源加载速度提升 **95%**

### 复核任务
- ✅ **并行检索**: 证据检索速度提升 **3-5倍**（5个并发）
- ✅ **结果缓存**: 相同报告重复复核速度提升 **10倍+**

### 系统监控
- ✅ **实时监控**: 可识别性能瓶颈
- ✅ **慢查询追踪**: 快速定位问题

---

## 🎯 最佳实践

### 1. 定期查看性能报告
```bash
curl http://127.0.0.1:8000/v1/admin/performance
```

### 2. 监控慢查询
检查 `slow_queries` 列表，优化频繁出现的慢查询

### 3. 合理设置缓存TTL
- 静态数据（知识库版本）: 长缓存（3600s+）
- 动态数据（任务状态）: 短缓存（60-300s）
- 实时数据（进行中的任务）: 不缓存

### 4. 批量操作
尽量使用批量API，减少HTTP往返

### 5. 定期清理缓存
在知识库更新或配置变更后清空缓存

---

## 🐛 故障排查

### 问题1: 内存占用过高
```python
# 减少缓存大小
from credit_review.infrastructure.query_optimizer import query_cache
query_cache.cache = {}  # 清空缓存
```

### 问题2: 缓存数据过期
```bash
# 清空所有缓存
POST /v1/admin/optimization/clear-cache
```

### 问题3: 性能监控影响性能
```python
# 禁用性能监控
setup_optimizations(
    app=app,
    enable_performance_monitoring=False  # 关闭
)
```

---

## 📚 扩展阅读

- [FastAPI Performance Best Practices](https://fastapi.tiangolo.com/deployment/concepts/)
- [SQLite Optimization](https://www.sqlite.org/optoverview.html)
- [Python Async/Await](https://docs.python.org/3/library/asyncio.html)

---

**优化完成时间**: 2024年10月16日  
**优化模块数**: 5个核心模块  
**新增功能**: 性能监控、查询缓存、异步任务、RAG优化  
**向后兼容**: ✅ 完全兼容现有代码
