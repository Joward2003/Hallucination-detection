> 历史快照，已被 2026-09-16 Agentic RAG 重设计替代。不是当前开发要求。原有相对链接仅保留为历史文本。

# 金融信贷分析报告 AI 复核工作台

## MVP 交接文档

版本：MVP-0.1  
状态：已实现并通过测试（扩展核心闭环）  
适用范围：单次、同步、内存证据集的 Parent–Child 事实核验闭环

## 1. 项目定位

系统用于帮助业务人员复核 AI 生成的金融信贷分析报告，不替代银行人员作出授信或信贷审批判断。

MVP 的最小闭环是：

```text
报告文本
  → Parent–Child 拆分
  → 公司识别
  → Child 查询规划
  → 外部证据检索
  → 证据分级
  → 证据不足时最多重写查询一次
  → Child 核验
  → 多 Child 结果汇总
```

单个 Child 的最终状态只有：

```text
SUPPORTED
CONTRADICTED
INSUFFICIENT_EVIDENCE
```

其中 `INSUFFICIENT_EVIDENCE` 表示当前证据不足，不能直接等同于事实错误或模型幻觉。

## 2. 已实现内容

已实现：

- Parent 保留原始句子及位置；Child 作为检索和核验单位。
- 对联合驱动、联合因果和“预计/可能”等不确定表达进行保守处理。
- 未识别模式回退为“一个 Parent 对应一个 Child”，避免不安全拆分。
- 确定性公司识别接口，支持公司名称和股票代码映射。
- 基于 Child 的文本/表格查询类型规划。
- 内存版证据检索器，支持传入 `Evidence` 对象或 JSON 字典。
- 证据关系分级：支持、部分支持、无关、反向证据。
- 证据不足时只允许一次 Query Rewrite。
- 基于证据关系的三态核验。
- LangGraph 顺序处理多个 Child。
- 每个 Child 完成后清理当前工作状态，避免跨 Child 污染。
- 测试覆盖 Parent–Child 约束、证据不足、反向证据、JSON 输入和多 Child 顺序执行。

本轮在上述 MVP 之上已落地并通过测试的可运行能力：

- 领域枚举、Parent–Child/结论不变量和严格入口校验；
- 确定性同比、期间和单位校验，以及证据引用 hash/定位检查；
- SourceScope 先过滤后检索，避免越权证据进入排序和核验；
- 版本化规则注册/执行、置信等级和风险门控；
- 低置信/反向证据触发 Critic，Critic 冲突进入人工待办；
- 人工任务乐观锁版本校验与 `resume_review` 恢复入口；
- 框架无关的 `ReviewManager`：租户幂等创建、查询、取消、人工提交；
- 内存 checkpoint、追加式审计和敏感字段脱敏基础实现；
- LangGraph 为可选依赖：未安装时使用同一 StateGraph 契约的本地同步 runner，保证测试环境可运行。

暂未实现：

- 真实 LLM 抽取、查询改写和核验。
- Chroma 或其他生产级向量/关键词检索。
- Reranker、结构化表格检索和文档版本管理。
- 生产级数值/单位/期间规则覆盖、20 多条正式业务规则及真实模型校准。
- 真实 LLM、Chroma/Reranker、生产持久化、权限中间件和前端工作台。

说明：本轮提供的是无框架的 API 应用服务与内存实现；FastAPI、生产持久化、真实权限中间件和外部审计系统仍需按部署环境接入，不能把当前内存实现当作生产隔离边界。

## 3. 代码目录

```text
src/credit_review/
├── __init__.py
├── domain/
│   ├── __init__.py
│   └── models.py              # Parent、Child、Evidence、核验结果数据模型
├── graph/
│   ├── __init__.py
│   ├── state.py               # LangGraph ReviewState
│   └── builder.py             # MVP 图构建、节点、路由和公开入口
├── services/
│   ├── __init__.py
│   └── mvp_services.py        # 当前可替换的确定性服务实现
└── adapters/
    └── __init__.py            # 预留外部适配器目录，当前未接入实现

tests/
├── __init__.py
└── test_mvp.py                # MVP 单元测试和图链路测试
```

旧目录 `Build_kb/`、`tool/`、`atomic_fact/` 和 `OpenFActScore/` 已移除；不提供旧实现兼容层。

## 4. 公开入口和使用方式

公开入口位于 `src/credit_review/__init__.py`：

```python
from credit_review import build_review_graph, run_review
```

### 4.1 `run_review`

```python
run_review(
    original_input: str,
    evidence: list[Evidence | dict] | None = None,
    companies: dict[str, dict[str, str]] | None = None,
) -> dict
```

参数说明：

- `original_input`：待复核的报告文本。
- `evidence`：外部证据列表。可以传 `Evidence`，也可以传等价字典。
- `companies`：可选公司映射，例如：

```python
{
    "某某公司": {"stock_code": "600000"}
}
```

Evidence 字典的最小字段：

```python
{
    "evidence_id": "E001",
    "content": "公司2024年营业收入同比增长20%",
    "source": "annual_report_2024",
    "page": 32,
    "evidence_type": "table",
}
```

`page` 可以为 `None`；`score` 不传时默认为 `0.0`，检索阶段会重新计算当前 MVP 分数。字段缺失或类型错误会在入口处抛出异常，不应静默补全关键字段。

### 4.2 `build_review_graph`

```python
services = MvpServices(...)
graph = build_review_graph(services)
state = graph.invoke({"original_input": text})
```

该入口用于后续替换服务实现和测试节点行为。服务依赖通过 `MvpServices` 注入，避免把 LLM、检索器或数据库写死在图节点中。

## 5. LangGraph 主链路

当前节点顺序和路由如下：

```text
START
  ↓
extract_parent_child
  ↓
resolve_company
  ↓
prepare_child
  ↓
plan_query
  ↓
retrieve
  ↓
grade_evidence
  ├─ evidence_status == INSUFFICIENT 且 retry_count < 1
  │    ↓
  │  rewrite_query → retrieve
  │
  └─ 其他情况 → verify
                    ↓
              finalize_child
              ├─ 还有 Child → prepare_child
              └─ 已完成全部 Child → aggregate → END
```

当前为顺序执行。并行 Fan-out 暂不启用，因为当前 `ReviewState` 使用单组 `current_*` 工作字段，并行会引入状态归并和隔离问题。

## 6. State 说明

`ReviewState` 位于 `src/credit_review/graph/state.py`，分为三类字段。

### 6.1 任务级字段

| 字段 | 作用 |
|---|---|
| `original_input` | 原始报告文本 |
| `fact_groups` | Parent 及其 Child 分组 |
| `flat_children` | 用于顺序处理的 Parent–Child 工作队列 |
| `company_info` | 公司识别结果，可能为 `None` |
| `completed_results` | 已完成 Child 的结果 |
| `workflow_status` | 当前流程状态 |

### 6.2 当前 Child 工作字段

| 字段 | 作用 |
|---|---|
| `child_index` | 当前 Child 在工作队列中的下标 |
| `current_parent` | 当前 Child 对应的 Parent 语境 |
| `current_fact` | 当前 Child |
| `current_queries` | 当前 Child 的查询记录 |
| `current_evidence` | 当前 Child 检索到的证据 |
| `evidence_status` | `SUFFICIENT`、`PARTIAL` 或 `INSUFFICIENT` |
| `retry_count` | 当前 Child 的查询改写次数，MVP 最大为 1 |
| `current_assessments` | 证据关系判断 |
| `verification_result` | 当前 Child 的三态核验结果 |

### 6.3 最终字段

`review_result` 包含：

- `status`：流程状态 `COMPLETED`，不是单个 Child 的核验状态；
- `company_info`；
- `fact_groups`；
- `completed_results`；
- `summary_counts`。

## 7. 数据结构约定

### 7.1 Parent

```python
{
    "parent_id": "P001",
    "parent_text": "原始句子或段落",
    "source_start": 0,
    "source_end": 20,
}
```

Parent 是语境，不是外部证据，不能用于支持自身结论。

### 7.2 Child

```python
{
    "fact_id": "F00101",
    "parent_id": "P001",
    "fact": "可独立检索和核验的事实",
    "source_start": 0,
    "source_end": 12,
}
```

Child 应保留主体、期间、数字、单位、比较关系、限定词、联合关系、因果和否定/不确定表达。当前确定性抽取器只覆盖少量模式，未知模式会保守回退。

### 7.3 Evidence

```python
{
    "evidence_id": "E001",
    "content": "外部原始证据片段",
    "source": "文档或数据源",
    "page": 32,
    "evidence_type": "text" | "table",
    "score": 0.92,
    "table_name": None,
    "row": None,
    "column": None,
}
```

生产实现必须继续补充文档版本、章节/表格定位、内容 hash、检索方式和排序信息。当前 MVP 尚未实现这些字段。

### 7.4 Child 核验结果

```python
{
    "status": "SUPPORTED" | "CONTRADICTED" | "INSUFFICIENT_EVIDENCE",
    "reason": "简短理由",
    "evidence_ids": ["E001"],
    "confidence": "low" | "medium" | "high",
    "fact_id": "F00101",
    "fact": "Child 文本",
    "parent_id": "P001",
    "parent_text": "Parent 原文",
    "queries": [],
    "evidence": [],
    "assessments": [],
    "retry_count": 0,
}
```

`parent_text` 出现在结果中是为了追溯和恢复语境，不代表 Parent 被当成证据使用。

## 8. 当前服务实现和替换点

服务均位于 `mvp_services.py`，后续应保持方法输入/输出基本稳定，再替换内部实现。

| 服务 | 当前实现 | 后续替换方向 |
|---|---|---|
| `DeterministicParentChildExtractor` | 正则和保守回退 | LLM 结构化抽取 + Schema 校验 |
| `SimpleCompanyResolver` | 名称/股票代码包含匹配 | 企业主数据、别名、租户范围校验 |
| `SimpleQueryPlanner` | 根据关键词选择 text/table | Agentic Query Planner、多路查询 |
| `InMemoryEvidenceRetriever` | 字符串和二元组重合度 | 文本/表格混合检索 + reranker |
| `MvpEvidenceGrader` | 指标、方向和数字启发式判断 | 证据级模型 + 业务规则联合判断 |
| `MvpFactVerifier` | 基于证据关系的确定性三态输出 | LLM 结构化核验 + 确定性校验器 |

注意：当前 `MvpEvidenceGrader` 的分数和语义判断只适合测试闭环，不可直接作为生产金融核验结论。

## 9. 测试与验证

测试文件：

```text
tests/test_mvp.py
```

覆盖内容：

- 联合驱动没有被拆成两个单因素结论；
- 联合原因不会分别分配完整结果数值；
- “预计/可能”等不确定性没有被强化；
- 支持结果同时保留 Parent、Child 和外部证据；
- 无证据时会改写查询一次，最终输出证据不足；
- 同一指标方向相反时输出 `CONTRADICTED`；
- JSON 字典 Evidence 能在公开入口被标准化；
- 多 Child 按顺序处理，当前状态在 Child 间被清理。

已执行命令：

```bash
/private/tmp/credit-review-venv/bin/python -m unittest discover -s tests -v
```

最近结果：

```text
Ran 8 tests
OK
```

测试环境使用 Python 3.11 和 LangGraph 1.2.11 临时环境。仓库默认 Python 3.9.6 不满足当前代码的 Python 3.10+ 语法要求。

## 10. 规格决定和已发现问题

### 已确认的设计决定

- Parent 只做语境恢复，不做证据。
- 核验输入逻辑上是 `Child + Parent + 外部 Evidence`。
- 证据不足不直接判定为错误。
- Query Rewrite 在 MVP 中最多一次。
- 多 Child 暂时顺序执行，不做并行。
- 通过服务注入保留后续接入真实模型和检索器的替换点。

### 当前必须注意的问题

1. `langgraph` 和 `fastapi` 通过可选依赖安装；未安装 LangGraph 时使用本地兼容 runner。
2. 已提供最小 `pyproject.toml`；本地开发可执行 `pip install -e .`，LangGraph/FastAPI 通过可选依赖安装。
3. 当前证据检索是内存检索，不能代表真实召回率、证据相关性或金融场景准确率。
4. 当前没有租户、用户、企业和文档权限隔离，禁止直接接入真实生产数据。
5. 当前仅有内存 checkpoint/审计/人工任务实现，不能替代生产持久化和审计系统。
6. 当前已具备基础数值、单位、期间和规则校验，不能据此宣称已达到原项目约 90% 的业务准确率。
7. 当前 `review_result.status = COMPLETED` 表示流程完成；单个 Child 的业务结论必须读取 `completed_results[*].status`。

## 11. 后续开发顺序

建议按以下顺序推进：

1. 将当前输入/输出 Schema、配置和内存实现替换为生产契约。
2. 建立业务标注集，先覆盖支持、部分支持、无关、反向证据四类标签。
3. 接入真实文本和表格检索，保持 `Evidence` 统一输出格式。
4. 扩充确定性数值、单位、期间和同比校验的业务覆盖。
5. 接入 LLM 结构化抽取、Query Rewrite 和核验，并保留当前确定性回退。
6. 将当前规则引擎和风险分层扩展为正式版本化规则集。
7. 将当前确定性 Critic 替换为独立模型/检索策略，并保留冲突路由。
8. 将内存人工复核、checkpoint、权限隔离和审计替换为生产实现。
9. 最后再接入 API、前端和生产部署。

每一步都应至少增加一类针对性测试，并继续保留本文件中的 8 个 MVP 回归测试。

## 12. 交接建议

接手人员首先阅读：

1. `docs/selected_architecture.md`
2. `docs/system_skeleton.md`
3. 本文档
4. `src/credit_review/graph/builder.py`
5. `src/credit_review/services/mvp_services.py`
6. `tests/test_mvp.py`

第一项后续开发建议是补齐 `Evidence` 的真实检索适配器和业务标注样本，不建议先增加更多 Agent。当前架构的首要目标仍是保证证据可追溯、状态可控和测试可复现。
