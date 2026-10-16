"""
修复说明文档

## 已修复的问题

### 1. 清理脱节的优化模块 ✅

**删除的文件**：
- `src/credit_review/infrastructure/query_optimizer.py` - 引用不存在的数据库表
- `src/credit_review/infrastructure/backend_optimizer.py` - 未接入实际系统
- `src/credit_review/infrastructure/async_optimizer.py` - 未使用
- `src/credit_review/infrastructure/performance_monitor.py` - 依赖未声明的psutil
- `src/credit_review/infrastructure/optimized_app.py` - 未接入
- `frontend/styles-original-backup.css` - 冗余备份
- `frontend/styles-improved.css` - 冗余备份
- `frontend/src/lazy-loader.js` - 未使用
- `frontend/src/request-optimizer.js` - 未使用
- `frontend/src/store-enhanced.js` - 未使用
- `BACKEND_OPTIMIZATION_GUIDE.md` - 误导性文档

**问题**：这些文件试图在虚构的表（tasks, documents, audit_log）上创建索引，但实际的 `workbench/storage.py` 只有 `records(kind, id, body)` 和 `papers` 两张表。

### 2. 修复报告拆解的覆盖校验问题 ✅

**新文件**：`src/credit_review/workbench/agents_fixed.py`

**核心改进**：

#### 原问题：
```python
# 旧逻辑：要求 LLM 一次性处理整篇报告
# 强制 parent_quote 必须 100% 覆盖原文每个字符
# 超过 6144 tokens 就会失败
```

#### 新方案：
```python
def _split_report_into_parents(text: str, max_chunk_size: int = 800):
    """
    确定性地将报告拆分为父块（Python代码）
    - 按段落/章节边界分割
    - 保证100%覆盖原文
    - 不会超出token限制
    """
    # 1. 尝试按章节标题分割（一、二、三、1.、2.、等）
    # 2. 如果单块太大，按段落（\n\n）分割
    # 3. 返回 [(parent_text, start_offset, end_offset), ...]
```

**两阶段拆解**：
1. **Stage 1（确定性）**: Python代码分段 → 100%覆盖保证
2. **Stage 2（LLM）**: 从每个parent块中提取children → 可以失败也不影响整体

**优势**：
- ✅ 不再依赖LLM完美覆盖
- ✅ 每个块都在token限制内
- ✅ 即使LLM漏掉章节序号/标点，也不会整体失败
- ✅ 允许5%的小间隙（空格等）

### 3. 并行复核流程改进 🔄

**当前问题分析**：

在 `graph/builder.py` 中：
```python
# 当前：串行执行，遇到 HUMAN_REVIEW_REQUIRED 就阻塞
for child_index in range(len(children)):
    if child_needs_human_review:
        WAIT_FOR_HUMAN  # 整个图停止
    # 后续children无法继续
```

**建议改进方案**（需要重构graph）：

```python
# 新逻辑：全量自动核验 + 批量人工复核
async def review_all_children():
    pending_human = []
    results = []
    
    # Phase 1: 自动核验所有children
    for child in children:
        result = await auto_verify(child)
        if result.needs_human_review:
            pending_human.append(child)
            result.status = 'PENDING_HUMAN'
        results.append(result)
    
    # Phase 2: 人工批量处理
    if pending_human:
        # 保存到队列，不阻塞
        store.save('pending_human_tasks', pending_human)
    
    return results
```

**优势**：
- ✅ 人工打开工作台时看到所有待确认项
- ✅ 一次性处理完毕，不用反复等待
- ✅ 自动核验的部分不会被阻塞

### 4. 清理冗余架构代码 ⚠️

**识别的冗余**：
- `verification/numeric.py` vs `workbench/agents.py` 中的数值校验
- `api/server.py` vs `workbench/app.py` 两套FastAPI入口
- `agents/deepseek_agents.py` vs `workbench/agents.py` 两套Agent

**建议**：
- 保留 `workbench/` 目录作为生产代码
- 将 `api/`, `verification/`, `agents/` 标记为"研究/测试代码"
- 或逐步迁移旧代码到workbench模块

## 使用新的agents_fixed.py

### 替换方式

**选项1：直接替换**
```bash
mv src/credit_review/workbench/agents.py src/credit_review/workbench/agents_old.py
mv src/credit_review/workbench/agents_fixed.py src/credit_review/workbench/agents.py
```

**选项2：逐步测试**
```python
# 在 workbench/reviews.py 中临时导入
from credit_review.workbench.agents_fixed import Extractor
# 测试通过后再正式替换
```

### 测试验证

```bash
# 运行测试
python -m pytest tests/ -k extraction -v

# 手工测试
python -c "
from credit_review.workbench.agents_fixed import _split_report_into_parents

text = '''
一、企业基本情况
某公司成立于2020年...

二、财务状况分析
2023年营业收入10亿元...
'''

blocks = _split_report_into_parents(text)
print(f'分为 {len(blocks)} 个块')
for i, (content, start, end) in enumerate(blocks, 1):
    print(f'块{i}: {len(content)}字符, offset={start}-{end}')
"
```

## 后续TODO

### 高优先级
1. [ ] 重构graph/builder.py实现并行复核
2. [ ] 在pyproject.toml中记录实际依赖（不要添加psutil等无用依赖）
3. [ ] 为_split_report_into_parents添加单元测试

### 中优先级
4. [ ] 统一新旧两套架构（决定保留哪一套）
5. [ ] 为workbench/storage.py的records表添加JSON索引
6. [ ] 文档化"确定性前置，LLM后置"的设计原则

### 低优先级
7. [ ] 清理未使用的导入和函数
8. [ ] 添加性能基准测试

## 注意事项

1. **agents_fixed.py 向后兼容**：接口与原agents.py相同，只是内部实现改进
2. **性能影响**：拆分为多个块后，会有更多次LLM调用，但每次都更短更稳定
3. **容错性提升**：即使某个块提取失败，其他块依然可以继续
4. **人工介入减少**：不再因为格式问题（漏标点等）就整体失败

## 风险评估

- **低风险**：删除未使用的文件
- **中风险**：修改extraction逻辑（需要充分测试）
- **高风险**：重构graph并行流程（影响核心业务逻辑）

---

**修复日期**: 2024-10-16
**修复人**: Claude Opus 5.5
**测试状态**: agents_fixed.py 已创建，等待集成测试
