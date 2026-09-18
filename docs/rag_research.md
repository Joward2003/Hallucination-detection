# Agentic RAG 论文与开源项目调研

> 查阅日期：2026-09-16。以下仅引用论文原站、官方文档和项目仓库。
> 目标：为金融报告复核选择可实施的检索架构；不将第三方自报结果直接当成本项目性能。

## 1. 近期研究与采用结论

| 资料与时间 | 核心逻辑 | 本项目采用方式与限制 |
|---|---|---|
| [Data-Centric Perspectives on Agentic RAG，ACL Findings 2026](https://aclanthology.org/2026.findings-acl.78/) | 将任务分解、探索查询、迭代证据获取及交互轨迹纳入 Agentic RAG 的数据与评估问题 | 记录每次计划、工具参数、观察与结束原因；同时评估最终结论和补查过程 |
| [Agentic RAG Survey，2025 首发](https://arxiv.org/abs/2501.09136) | 归纳规划、反思、工具使用与协作式 RAG 架构 | 采用显式计划和观察驱动决策；不因存在多个模块就宣称多智能体有效 |
| [FinGEAR，2025-09](https://arxiv.org/abs/2509.12042) · [全文](https://arxiv.org/html/2509.12042v1) | 金融词表映射披露章节，章节内 Summary/Question 层级索引，再做两阶段交叉编码器重排 | 首先采用金融词表和章节导航；双树索引/双重排另做实验。论文以美国 10-K/FinQA 场景评估，中国年报章节和指标需重新映射 |
| [FinSearchComp，2025-09](https://arxiv.org/abs/2509.13160) · [ICLR 2026 论文](https://openreview.net/pdf?id=8AJbbbe2ni) | 区分时效信息查询、历史查找和复杂历史调查的金融搜索评估 | 用于设计任务分层、截止时间与多步查询评估；开放网络搜索任务与私有知识库任务应分开报告 |
| [Multi-Reranker / FinanceRAG，2024-11](https://arxiv.org/abs/2411.16732) | 比较查询扩展、语料整理、多重排器及长上下文处理 | 首版先建单 Reranker 基线，再比较集成的质量/时延；不直接复用英文竞赛分数 |
| [Corrective RAG，2024-01](https://arxiv.org/abs/2401.15884) | 评估检索质量后采取纠正动作，包含外部检索补充思路 | 采用“证据评估→有针对性补查”；首版在授权 KB 内纠正，网页不能直接与私有证据混用 |
| [HiRAG: Retrieval-Augmented Generation with Hierarchical Knowledge，2025-03](https://arxiv.org/abs/2503.10150) | 用分层知识组织增强图式索引与检索 | 关联企业/担保链任务作为实验；关系必须回链原始出处与有效时间，不能用抽取的边代替原文 |

本文对论文的采用结论属于本项目工程判断。没有复现这些论文，也未完成本地准确率、成本或延迟测量。

## 2. 可参考的实现

| 官方项目/文档 | 具体阅读位置或能力 | 如何落到本项目 |
|---|---|---|
| [LangGraph](https://github.com/langchain-ai/langgraph) · [Agentic RAG 教程](https://docs.langchain.com/oss/python/langgraph/agentic-rag) | 检索工具调用、文档评分、查询改写与条件边 | `agentic/graph.py`、`decision.py`、`budget.py`，每个动作可观察且有上限 |
| [RAGFlow](https://github.com/infiniflow/ragflow) · [Agentic 图源文件](https://github.com/infiniflow/ragflow/blob/main/rag/advanced_rag/agentic_rag_graph.py) | 文档处理与按任务复杂度切换直接搜索、分解搜索、迭代研究路径 | 一键建库任务与简单/复杂任务预算分层；参考模块设计，不整体替换现有项目 |
| [FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding) · [Reranker 实现目录](https://github.com/FlagOpen/FlagEmbedding/tree/master/FlagEmbedding/inference/reranker) | Dense Embedding 与独立重排推理 | BGE-M3 Dense / bge-reranker-v2-m3 作为初始多语言基线；通过 adapter 可替换 |
| [BM25S](https://github.com/xhluca/bm25s) | 基于 NumPy/稀疏矩阵的可保存 BM25 索引，并支持 mmap 加载 | 使用本项目金融分词器，按 KB 版本保存词法索引；大规模服务仍可替换为 OpenSearch |
| [Chroma Query/Get](https://docs.trychroma.com/docs/querying-collections/query-and-get) | 向量相似检索与按 ID 回取 | 首版 Dense 适配器；不把文本包含过滤声称为 BM25 |
| [Qdrant Hybrid Queries](https://qdrant.tech/documentation/search/hybrid-queries/) | 多阶段候选查询与 RRF/分数融合 | 参考召回→融合→重排分层；首版 RRF 在服务层实现，后端可替换 |
| [cv-lee/FinanceRAG](https://github.com/cv-lee/FinanceRAG) | 金融比赛的查询/召回/重排/生成组织 | 消融实验与金融检索基线参考 |
| [PageIndex](https://github.com/VectifyAI/PageIndex) | 文档树索引与 Agent 导航 | 章节导航实验工具；项目自身使用无向量路径，本项目只引入导航思想，仍保留 Dense+BM25 主干 |
| [LightRAG](https://github.com/HKUDS/LightRAG) | 实体关系检索与原文 chunk 检索的组合 | 可选关系工具；其 `hybrid` 指 local/global 模式结合，不等于本项目的 Dense+BM25 |
| [hhy-huang/HiRAG](https://github.com/hhy-huang/HiRAG) | 分层知识的图检索 | 关联风险链路实验，评估索引成本、关系准确性和版本更新 |

GitHub 默认分支持续变化；接入实现时必须固定 tag/commit、依赖版本及模型 revision，在 manifest/运行轨迹中记录。本次是网页与源码调研，没有克隆、安装或执行这些项目。

## 3. 排除的资料

[Agentic Retrieval-Augmented Generation for Financial Document Question Answering / FinAgent-RAG（2605.05409）](https://arxiv.org/abs/2605.05409) 于 2026-05 提交，2026-07-05 的 v2 明确撤回，原因是实验设计存在影响结果有效性的重大方法问题。搜索摘要仍展示其准确率与成本数字；本项目不采用该论文结果作为选型或性能依据。

## 4. 取舍后的核心逻辑

```text
金融结构化建库
    ↓ 同一来源产生可追溯的 Dense/BM25/表格/章节索引
实体、期间、口径、Claim 理解
    ↓ 根据任务复杂度决定查询与工具
Dense + BM25 → RRF Top-k → Cross-Encoder Rerank
    ↓ 恢复原文、表头、脚注；按证据需求组织上下文
判断哪些需求已覆盖、哪些存在冲突
    ├─ 缺口明确 → 改写/拆分/表格/章节补查 → 重新评估
    ├─ 重复或预算耗尽 → 带缺失项退出
    └─ 证据充分 → 受约束计算 + 带引用生成 + 核验
```

首版成功标准是可复现的检索和补查闭环；章节树、关系图和多模型集成的采用必须通过相同语料与预算下的增量实验，而不能只凭“更新”或仓库热度。
