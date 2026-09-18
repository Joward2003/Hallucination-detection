# 当前实现与 Agentic RAG 重设计交接

> 日期：2026-09-16；文档版本：RAG redesign 1。
> 本次交付已跑通 provider-free 第一条闭环、真实检索适配器和文件版一键建库服务；异步任务、上传、SSE 与一键建库页面仍未完成。

## 1. 当前有效设计

- [架构方案](selected_architecture.md)：实体/时间感知的混合检索、独立Rerank、有界Agent补查。
- [系统骨架](system_skeleton.md)：目标目录、接口、State、配置及实施顺序。
- [一键建库](knowledge_base.md)：应用功能、后台任务、双索引一致性和原子发布。
- [研究依据](rag_research.md)：近期论文、GitHub项目及采用理由。

当前代码已接入可复现的 Dense-like/BM25/RRF/Rerank、真实 Sentence-Transformers/BM25S/Cross-Encoder 适配器、表格/结构化 Worker、MinerU Parent–Child 快照、Planning Agent 计划，以及文件版 BuildManager 的 staging/发布/版本固定检索；确定性实现用于测试模式，生产模式需显式配置并安装 `.[rag]`。异步建库生命周期仍按下列迁移项推进。

## 2. 代码现状与迁移映射

| 当前文件/模块 | 经检查的现状 | 目标改动 |
|---|---|---|
| `scripts/build_kb.py` | 保留旧 Evidence JSON，并支持 MinerU Parent–Child 快照；尚未写入持久双索引 | 变为统一BuildService的CLI入口；解析、切块、双索引、发布下沉knowledge_base |
| `services/mvp_services.py::InMemoryEvidenceRetriever` | 字符串/词项重合度、固定前5项 | 保留为测试替身；正式入口替换为HybridSearchService |
| `retrieval/service.py` + `infrastructure/{embeddings,bm25_service,rerankers}.py` | provider-free 内核、真实模型适配器、RRF/Rerank 与表格/结构化路由 | 部署时安装 `.[rag]`，把模型缓存和索引目录接入持久卷，保留端口与轨迹字段 |
| `agents/deepseek_agents.py` | 模型抽取/查询规划/核验适配 | 复用网关，补QueryContext、工具动作和缺口观察结构 |
| `graph/builder.py` | Parent–Child→Planning→按 profile 路由→grade/observation→有界 rewrite→核验/风险流程 | 增加更多工具观察、预算策略和独立 Claim 子图 |
| `domain/models.py` | 已有基础 Evidence/Locator/Query 字段；Graph State 保存 plan、requirements、trace、observation | 拆分来源Chunk、QueryContext、逐路Hit/分数、KBManifest与持久 Observation |
| `verification/` | 数值、引用、充分性和冲突基础实现 | 绑定表格操作数和来源版本，扩充金融口径及发布后引用回取 |
| `api/`、`knowledge_base/build_service.py`、`knowledge_base/repository.py` | 已有复核服务、文件版构建任务、版本仓储和检索试用路由；任务当前同步执行 | 接入上传、持久任务、队列、SSE、权限和真实 checkpointer |

当前 `pyproject.toml` 为Python 3.10+，已有graph/api/test/deepseek/rag可选依赖；`rag` extra 提供 numpy、BM25S 和 Sentence-Transformers。运行环境仍需预下载并缓存模型，不能把测试模式结果当作生产召回率。

## 3. 下一阶段的可验收交付

### 第一段：建立真实RAG主干

1. 规范原始文档和Chunk，保存页码/段落/表格定位。
2. 使用相同chunk manifest写入Dense与BM25，保存模型和分词配置。
3. 通过实体/期间解析生成查询，观测两路不同召回及RRF名次。
4. 接独立Cross-Encoder重排并恢复原文语境。
5. 固定中文金融小样本做Dense/BM25/Hybrid/Hybrid+Rerank对比。

当前已经有一条可运行主干：`KnowledgeBaseRepository` 保存不可变快照，`BuildManager` 完成同步 staging→publish，`KnowledgeBaseSearchService` 按 active/固定版本调用 `RetrievalRouter`；生产检索工厂可在同一版本目录写入 Dense/BM25S 索引。下一步是把同步建库下沉到异步 worker，而不是重新设计查询契约。

### 第二段：Agentic与金融核验

1. 将查询计划、工具输出、覆盖/缺失需求写入独立Claim State。
2. 根据缺失项调用表格或章节工具，最多预算内迭代。
3. 用跨期数值问题演示首轮缺上年值、补查、计算、引用验证。
4. 用无证据与冲突问题验证停止、证据不足和业务升级。

### 第三段：一键建库上线

1. 上传API和页面调用统一BuildService，后台持久worker执行。
2. 展示任务阶段和逐文档失败，支持重试/取消/增量。
3. 校验两路索引与原文一致后原子发布，新查询固定版本。
4. 验证失败保留旧版本、重复点击幂等、worker重启恢复、撤权即时生效。

## 4. 现有演示与历史材料

当前示例命令和外部模型行为见[examples/README.md](../examples/README.md)。provider-free 测试通过只代表契约和闭环可运行，不代表生产召回率。

重设计前的文档原样保存在：

- [历史架构](archive/2026-09-16_pre_rag_selected_architecture.md)
- [历史骨架](archive/2026-09-16_pre_rag_system_skeleton.md)
- [历史交接](archive/2026-09-16_pre_rag_handoff.md)
- [历史MVP交接](archive/2026-09-16_pre_rag_handoff_mvp.md)

这些快照顶部标明已替代；旧测试计数、依赖建议、模型名和能力描述均是历史记录，不作为当前事实保证。

## 5. 本轮验证范围

本轮已执行 Planning、混合检索/路由、真实适配器 fake-model 契约、MinerU 建库和主图回归测试；测试环境未下载真实模型，生产模型运行需在部署环境安装 `.[rag]` 并配置模型缓存。
