# 金融报告复核：Agentic RAG 与一键建库

本项目面向金融信贷分析报告复核，目标是让系统从财报、公告和业务材料中主动检索、补齐证据，再输出带原文引用的核验意见。

**当前状态：2026-09-16 已完成第一条可运行闭环和文件版一键建库服务。** 代码同时提供基于 `BAAI/bge-m3`、`bm25s` 和 `BAAI/bge-reranker-v2-m3` 的真实检索适配器；默认测试模式仍使用确定性实现，生产模式通过配置显式启用。

## 核心逻辑

```text
离线建库
上传材料 → 解析/OCR → 章节与表格切块 → 金融实体/期间/口径元数据
        → Dense向量索引 + BM25词法索引 + 原文/表格存储
        → 质量检查 → 发布可检索的知识库版本

在线 Agentic RAG
报告 → 提取主体/指标/期间与待核验结论
     → 单一Planning Agent展开金融概念并直接生成Query Rewrite和检索参数
     → 向量检索 Top-50 + BM25检索 Top-50
     → RRF融合/去重，候选 Top-60 → Cross-Encoder Rerank Top-12
     → 恢复原文、表头和脚注 → 按证据需求组织上下文
     → 评估证据是否充分
          ├─ 有缺口：改写/拆分查询，调用表格/章节工具补查
          ├─ 证据充分：计算与带引用核验
          └─ 达到预算：说明证据不足及缺失项
     → 引用与数值校验 → 汇总复核结果
```

Top-k 为初始实验参数。每个 Claim 默认最多 3 轮检索；Agent 根据已有证据决定下一步工具、查询和结束时机，执行器约束权限与预算。金融适配重点是主体消歧、财务期间与披露日期分离、指标/单位/合并口径、表格脚注、更正稿和反向证据。

报告 Parent–Child 提取是业务入口；来源文档 Document–Section–Chunk 是建库结构。报告语境不能作为外部证据自证。结果使用 `SUPPORTED / CONTRADICTED / INSUFFICIENT_EVIDENCE`，证据不足不直接等于事实错误。

## 应用一键建库（当前为文件版 API）

当前 `BuildManager` 已把“一键建库”的服务契约跑通：提交一次请求后依次执行解析、整理、索引、校验和发布，并返回阶段记录、失败原因和发布版本。`KnowledgeBaseRepository` 以不可变 JSON 快照保存版本，`KnowledgeBaseSearchService` 在一次检索/补查中固定版本；新版本构建失败时旧版本继续可用。

页面上传、异步队列、SSE 进度和持久化双索引仍是上线工作，产品流程和迁移约束见[一键建库设计](docs/knowledge_base.md)。

## 设计文档

| 文档 | 内容 |
|---|---|
| [架构方案](docs/selected_architecture.md) | 全链路设计、金融适配、Agent决策、Top-k与验收 |
| [系统骨架](docs/system_skeleton.md) | 目标目录、数据契约、Ports、State、工具与迁移顺序 |
| [一键建库](docs/knowledge_base.md) | 上传、解析、双索引、增量更新、任务恢复与发布 |
| [研究与项目参考](docs/rag_research.md) | 2025–2026近期研究、开源实现、采用/实验/排除理由 |
| [当前实现与交接](docs/handoff.md) | 已有代码的真实能力、差距及下一步工作 |

方案参考 [ACL Findings 2026 Agentic RAG 综述](https://aclanthology.org/2026.findings-acl.78/)、[FinGEAR](https://arxiv.org/abs/2509.12042)、[RAGFlow](https://github.com/infiniflow/ragflow) 和 [LangGraph Agentic RAG](https://docs.langchain.com/oss/python/langgraph/agentic-rag)。章节导航、图扩展与多重排器分别评估，论文和项目的自报成绩不当作本项目实测成绩。

## 当前能运行什么

| 能力 | 当前状态 |
|---|---|
| Parent–Child提取、三态核验、规则与人工路由 | 已有可运行演示；每个 Child 保留 Parent、检索计划和证据轨迹 |
| MinerU Parent–Child 建库 | 已实现 JSON 适配、层级上下文、原子事实、表格定位和版本 manifest |
| Dense + BM25 + RRF + Rerank | 已实现 provider-free 内核和真实 Sentence-Transformers/BM25S/Cross-Encoder 适配器 |
| 表格/结构化数据路由 | 已实现 `RetrievalRouter`，按 Planning Agent 的 `retrieval_profile` 选择 Worker |
| Planning Agent按定性概念生成指标需求和 Query Rewrite | 已实现通用概念模板、结构化 `RetrievalPlan`、缺口重写和参数校验；DeepSeek 可选实现为 LLM-first |
| 文件版建库任务、版本发布、检索试用 API | 已实现最小闭环；支持幂等、失败可查询、取消状态和版本固定检索 |
| 持久化建库任务、版本发布、上传与一键建库页面 | 文件版发布契约已实现；上传、队列、SSE、持久双索引和页面待产品化 |

### 演示环境

需要 Python 3.10+；以 `pyproject.toml` 为当前安装入口：

```bash
python -m pip install -e '.[graph,test]'
python -m pytest -q
```

导出演示 Evidence JSON：

```bash
PYTHONPATH=src python scripts/build_kb.py

# MinerU content_list → Parent–Child + Evidence snapshot
PYTHONPATH=src python scripts/build_kb.py --mineru-json report.json --parent-child-output build/kb.json
```

可选 DeepSeek 演示见[示例说明](examples/README.md)。报告复核示例仍使用内存检索，不能用于验证生产召回率；知识库最小 API 需要在应用层注入 `BuildManager`（详见[一键建库设计](docs/knowledge_base.md)）。

需要观察完整 Agent 执行轨迹时，在示例命令后加 `--trace`。终端会逐节点打印 Parent–Child、Planning Agent 的结构化计划与检索参数、检索候选/路由分数、证据分级、核验、数值/规则检查和风险路由；这是一份可审计的决策摘要，不会输出模型私有逐字思维链。具体命令见[示例说明](examples/README.md)。

启用真实检索后，建库和报告复核都会读取同一组配置：

```bash
pip install -e '.[rag]'
export CREDIT_REVIEW_RETRIEVAL_BACKEND=sentence_transformers
export CREDIT_REVIEW_EMBEDDING_MODEL=BAAI/bge-m3
export CREDIT_REVIEW_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
```

## 实施顺序

1. 在部署环境安装 `.[rag]` 并启用真实 Dense/BM25S/Cross-Encoder，记录模型、分词器和索引 profile。
2. 把 `BuildManager._run` 下沉到持久任务仓库和队列 worker，补齐重启恢复、SSE 进度和失败重试。
3. 接入上传/文档登记/权限中间件，页面调用同一 Build API；保留 active 版本原子切换和请求级版本固定。
4. 用中文金融标注集验证期间、单位、表格、口径与复杂问题，校准 Evidence Requirement 和预算退出。

历史设计已存入 `docs/archive/`，不再作为当前开发要求。
