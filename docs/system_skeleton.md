# Agentic RAG 系统编码骨架

> 日期：2026-09-16；状态：目标目录与接口设计；`knowledge_base/pipeline.py`、`repository.py`、`build_service.py`、`search_service.py` 和当前 retrieval/graph MVP 已落地，其余标为“新增”的文件仍是后续目标。
> [架构方案](selected_architecture.md) · [一键建库](knowledge_base.md) · [研究依据](rag_research.md) · [实现现状](handoff.md)

## 1. 目标目录

继续使用 `src/credit_review` 包名。以下是迁移后的目标结构，不代表当前磁盘上已存在这些文件。

```text
src/credit_review/
├── api/
│   ├── app.py                       # 改：装配建库/检索/复核路由
│   ├── dependencies.py              # 新：认证上下文、KB版本、服务注入
│   └── routes/                      # 新
│       ├── knowledge_bases.py       # 建库、状态、取消、重试、版本
│       ├── documents.py             # 文件上传/更正/删除/原文回取
│       ├── search.py                # 检索试用、调试信息
│       └── reviews.py               # 报告复核任务
├── knowledge_base/                  # 新：离线流水线
│   ├── build_service.py             # 已实现：同步一键构建、幂等任务、阶段状态
│   ├── repository.py                # 已实现：staging/active版本仓储与原子发布
│   ├── search_service.py            # 已实现：按active或固定版本检索
│   ├── service.py                   # 后续：异步任务编排
│   ├── pipeline.py                  # 解析→切块→索引→校验→发布
│   ├── worker.py                    # 持久化任务领取、租约、恢复
│   ├── parsers/
│   │   ├── text.py                  # TXT/Markdown
│   │   ├── pdf.py                   # 文本PDF与按页OCR路由
│   │   └── ocr_json.py              # OCR/MinerU等解析产物适配
│   ├── chunking.py                  # Document/Section/Chunk结构
│   ├── tables.py                    # 表头、行块、单元格、脚注
│   ├── enrichment.py                # 实体/期间/指标/口径元数据
│   ├── indexing.py                  # Dense和BM25索引写入
│   ├── quality.py                   # 来源/索引一致性与检索检查
│   └── manifest.py                  # staging、active版本和发布事务
├── query/                          # 新：输入理解
│   ├── entities.py                  # 公司、简称、代码候选提取
│   ├── resolver.py                  # 企业主数据消歧和别名
│   ├── financial_terms.py           # 指标、单位、口径标准化
│   ├── metric_registry.py           # 新：指标、公式变体、操作数和行业适用性
│   └── understanding.py             # QueryContext与证据需求
├── retrieval/
│   ├── service.py                   # 改：真正的混合检索编排
│   ├── dense.py                     # 新：向量召回
│   ├── bm25.py                      # 新：BM25查询与中文分词
│   ├── fusion.py                    # 新：分路去重、RRF、候选Top-k
│   ├── reranker.py                  # 新：独立Cross-Encoder重排
│   ├── context.py                   # 新：覆盖优先、去重、token预算
│   ├── tables.py                    # 新：表格定位与原文回链
│   ├── sections.py                  # 新：章节导航和邻接原文回取
│   └── filters.py                   # 改：权限/版本/截止时间与业务提示分离
├── agentic/                        # 新：在线决策循环
│   ├── graph.py                     # LangGraph节点和条件边
│   ├── state.py                     # 每个Claim独立的工作State
│   ├── planner.py                   # 概念展开、证据需求、Query Rewrite和检索参数
│   ├── decision.py                  # 根据观察选择补查/计算/结束
│   ├── tools.py                     # 结构化工具及参数校验
│   ├── grader.py                    # 证据覆盖、相关性、冲突
│   └── budget.py                    # 轮次、调用、token、时限、去重
├── review/                         # 新：金融报告业务适配层
│   ├── claims.py                    # 从现有Parent–Child抽取器迁入
│   ├── graph.py                     # 调用每个Claim的Agentic子图
│   ├── verifier.py                  # 从fact_verifier演进，带引用核验
│   └── aggregate.py                 # 汇总三态与缺失项
├── domain/
│   ├── kb.py                        # 新：Document/Chunk/BuildJob/Manifest
│   ├── query.py                     # 新：QueryContext/EvidenceNeed
│   ├── retrieval.py                 # 新：Hit/Trace/Bundle/Observation
│   ├── models.py                    # 改：保留报告与核验模型，拆分检索字段
│   ├── enums.py                     # 扩展任务/错误/停止状态
│   └── invariants.py                # 版本、来源、三态约束
├── ports/
│   ├── ingestion.py                 # 新：Parser/BuildRepository/Queue
│   ├── indexes.py                   # 新：DenseIndex/LexicalIndex/Reranker
│   ├── storage.py                   # 新：DocStore/KBRepository
│   └── llm.py                       # 保留并扩展结构化调用接口
├── infrastructure/
│   ├── embeddings.py                # 已实现：Sentence-Transformers Dense适配器
│   ├── bm25_service.py              # 已实现：BM25S持久化索引适配器
│   ├── rerankers.py                 # 已实现：Cross-Encoder重排适配器
│   ├── retrieval_stack.py           # 已实现：三类真实适配器装配
│   ├── docstore.py                  # 新：原文、表格、引用回取
│   ├── repositories.py              # 新：任务/manifest/结果持久化
│   ├── queue.py                     # 新：建库后台任务
│   ├── checkpoints.py              # 改：生产持久化checkpointer
│   └── deepseek_gateway.py          # 复用：通过LLM端口注入
├── verification/                   # 复用扩展：数值、引用、冲突
├── rules/                          # 保留：金融业务后处理
├── policies/                       # 保留：风险与人工升级
├── security/                       # 扩展：授权、数据脱敏、原文访问
├── observability/                  # 扩展：检索/建库/Agent轨迹
└── config/                         # 扩展：profiles与schema校验
configs/                            # 目标新增
├── ingestion/financial.yaml         # 解析、切块和质量阈值
├── retrieval/financial.yaml         # 两路Top-k、RRF、Rerank
├── agents/financial.yaml            # 工具白名单与预算
├── dictionaries/                    # 公司别名、金融词典、指标映射
└── metrics/financial.yaml           # 指标定义、公式变体和行业Profile
scripts/
├── build_kb.py                      # 改：CLI调用同一建库service
├── search_kb.py                     # 新：真实混合检索诊断
├── run_example_review.py            # 改：传kb_id/kb_version而非手塞Evidence
└── evaluate_rag.py                  # 新：基线/消融/轨迹评估
frontend/                           # 后续应用上线时新增，框架另定
└── knowledge-base/                  # 上传、一键建库、进度、错误、检索试用
tests/                             # 目标分层
├── unit/                           # 融合、分词、口径、预算
├── integration/                    # 双索引构建、发布、回取、恢复
├── e2e/                            # 上传→建库→混合检索→Agent补查→核验
└── evaluation/                     # 中文金融标注题、hard negatives、对比报告
```

目录中的 `graph/`、`agents/`、`services/mvp_services.py` 当前仍存在。迁移完成并验证公开入口后才迁移旧实现，不能因目标树未列出而直接删除。

## 2. 依赖方向

```text
API/CLI → Application Services → Agentic/KB/Review → Ports + Domain
                                                  ↑
                                 Infrastructure实现Ports
```

- 建库流水线和在线查询独立运行，通过已发布 `KBManifest` 衔接。
- Dense/BM25/Rerank 无 Agent 依赖；可以独立跑评估。
- Graph 节点只调用服务并返回 State patch；不能在路由函数中联网或写库。
- 基础设施客户端、模型和密钥由依赖注入提供，不放入 State。
- 现有 `run_review(..., evidence=...)` 暂时作为 demo 兼容入口；新入口以 KB 身份和版本调用真实检索。

## 3. 数据契约

下列是目标字段约定，不是已实现的 Python 类型定义。建库详细字段见[一键建库文档](knowledge_base.md)。

| 对象 | 必备字段与约束 |
|---|---|
| `QueryContext` | query_id、claim_id、original_text、entities（候选/已确认）、metrics、target_periods、comparison_periods、as_of、currency、unit、statement_scope、intent、missing_fields |
| `SourceScope` | tenant_id、kb_id、kb_version、allowed_document_ids/服务端权限谓词、as_of；由服务端生成且循环内只读 |
| `EvidenceNeed` | need_id、description、required_entities/metrics/periods、polarity、depends_on、completion_criteria |
| `MetricDefinition` | metric_id、aliases、formula_variants、operand_metrics、适用/排除行业、definition_version |
| `RetrievalPlan` | plan_id、claim_id、analysis_concept、entity_profile、requests、stop_conditions、plan_version |
| `PlannedRetrievalRequest` | need_id、profile、query_text、metric_ids、formula_id、periods、statement_scope、evidence_types、软过滤和受限Top-k |
| `SearchRequest` | query_id、need_id、dense_query、lexical_query、soft_filters、scope、top_k；工具不能覆盖scope |
| `RetrievalHit` | chunk_id、document_version、need_id、route、raw_score、rank、query_id、locator；相似度和距离语义由adapter声明 |
| `RankedCandidate` | chunk_id、document_version、route_hits[]、rrf_score、rerank_score、rerank_model、rank；各阶段分数分开存储 |
| `EvidenceBundle` | bundle_id、need_ids、source_chunks、table_cells、context_spans、locators、token_count、source_hashes |
| `Observation` | covered_needs、missing_needs、relations、conflicts、new_usable_evidence_count、tool_errors；区分无结果和服务故障 |
| `AgentDecision` | action、need_id、tool_args、reason_code、missing_fields；action必须属于白名单 |
| `Calculation` | formula_id、operand_evidence_ids、normalized_values、units、result、rounding、status |
| `ReviewVerdict` | claim_id、status（三态）、reason、evidence_ids、calculations、missing_needs、validation_status |
| `BuildJob` | build_id、kb_id、base_version、input_manifest、profile_version、status、document_progress、errors、lease、cancel_requested |

引用 locator 至少包含 doc_id、document_version、来源可访问标识与准确的页/段/表格位置。TXT 可以只有字符区间，未知页码为 null。原文 hash 与检索文本 hash 分开存储。

状态分开：流程 `COMPLETED/NEEDS_INPUT/FAILED/CANCELLED` 不等于事实三态；上游服务故障不能伪装成“库里没有证据”。

## 4. Ports 与工具

以下为接口伪代码；类型对应上一节领域对象，具体同步/异步实现需统一。

```python
class Parser:
    def parse(self, document, profile) -> ParsedDocument: ...

class DenseIndex:
    def build(self, chunks, embedding_profile, staging_ref) -> IndexReceipt: ...
    def search(self, vector, scope, soft_filters, top_k) -> list[RetrievalHit]: ...

class LexicalIndex:
    def build(self, chunks, tokenizer_profile, staging_ref) -> IndexReceipt: ...
    def search(self, query_tokens, scope, soft_filters, top_k) -> list[RetrievalHit]: ...

class Reranker:
    def rerank(self, query, candidates, top_n) -> list[RankedCandidate]: ...

class DocStore:
    def fetch(self, chunk_ids, scope) -> list[SourceChunk]: ...
    def fetch_context(self, locators, scope, token_budget) -> list[EvidenceBundle]: ...

class KBRepository:
    def resolve_active(self, kb_id, identity) -> KBManifest: ...
    def publish(self, manifest, expected_active_version) -> KBManifest: ...

class HybridSearchService:
    def search(self, request) -> SearchResult: ...  # 双召回→RRF→Rerank

class RetrievalAgent:
    def decide(self, context, needs, observation, budget) -> AgentDecision: ...
```

Agent 工具白名单：

| 工具 | 输入 | 输出与限制 |
|---|---|---|
| `hybrid_search` | query、need_id、业务提示 | RankedCandidate；内部必经双召回/融合/重排 |
| `table_lookup` | 已确认实体、指标、期间、口径 | 单元格与表头/脚注；歧义时返回候选，不能任取 |
| `section_search` | doc_id/章节主题、query | 章节原文定位和相关片段；同scope |
| `fetch_context` | chunk_ids/locators | 授权原文和邻接语境；同版本 |
| `calculate` | 公式ID、带出处操作数 | 确定性计算记录；禁止任意代码执行 |

Planning Agent 不作为普通检索工具暴露。Graph 在首次规划和 `missing_needs` 仍存在时调用同一个结构化 Agent；执行器先用配置 Schema 校验其 `RetrievalPlan`，再将每条请求交给相应 Worker。未知 `metric_id/formula_id/profile`、越界 Top-k、被锁定 Scope 字段或重复请求均在执行前拒绝。

`graph_expand` 是后续实验端口，默认关闭。网页检索如后续接入，应另设公开源工具，记录抓取时间和原文快照；不能自动向外发出内部报告内容。

## 5. 在线 State 与执行逻辑

```text
RequestState
  request_id, identity_ref, scope, kb_manifest_ref, original_input
  claims, claim_results, total_budget, workflow_status

ClaimState
  claim_id, parent_context, query_context, evidence_needs
  retrieval_plan, pending_action, round_index, tool_call_count, deadline
  query_history, tool_observations, seen_query_keys
  candidate_sets_by_need, evidence_bundles, covered_needs, missing_needs
  calculations, draft_verdict, rule_hits, risk_decision
  human_review_task, human_decision, validation_errors, stop_reason
```

Claim 之间独立 State；首版顺序处理报告中的 Claim。以后并发时用 `claim_id` 归并结果，用 `need_id` 分桶检索候选，不能共享单组 `current_evidence`。

```text
intake → claim_extract → understand → plan_and_rewrite → evidence_requirements
                                                        → retrieval_router
                                                                          ↓
                                 text_worker / table_worker / structured_data_worker
                                                                          ↓
                    dense+BM25→RRF→Rerank → collect_context → evidence_grade
                                                                  ↓        ↑
                                                     decide_next ──────────┘
                                                          ↓ 证据充分/预算退出
                                          claim_evidence_verify → business_rules
                                                                  ↓
                                                    risk_uncertainty_router
                                               ┌──────────┼──────────┐
                                            auto_pass  human_review mandatory_review
                                                           ↓
                                      approve/edit/reject/request_evidence → update_state
                                                           ↓                     ↓
                                                        finalize ───────→ plan
                                                           ↓
                                              final_result → feedback_dataset
```

`execute_tool` 根据动作分派。`hybrid_search` 固定内部阶段：

```text
validate_scope → dense_search || bm25_search
              → deduplicate_per_route → RRF → candidate_top_k
              → cross_encoder_rerank → rerank_top_n
```

Rerank 后由 `collect_context` 按需求恢复来源语境，`grade` 评估支持、部分支持、反驳或无关。直接表格/章节工具返回定位后的来源片段，同样经过 `collect_context/grade`，不能直接跳到最终结论。`claim_evidence_verify` 输出事实三态；`business_rules` 只输出规则命中；`risk_uncertainty_router` 再基于三态、规则、冲突、置信等级和业务策略决定通道。

人工任务保留 `claim_id`、`kb_version`、原证据包、规则命中、版本号和操作人。`Request Evidence` 只能新增一个明确的证据需求并恢复到 `plan`；`Approve/Edit/Reject` 写入可审计的最终人工决定。反馈数据集写入一个与线上运行隔离、去敏和版本化的仓储，只有审核完成的样本才可进入离线评估或训练候选集。

### 路由与退出

| 条件 | 路由 |
|---|---|
| 实体歧义阻止检索 | `NEEDS_INPUT`，保存候选 |
| 还有缺失需求且预算允许 | Agent 选择新的工具/查询 |
| 需求覆盖且数值操作数齐全 | calculate（若需）→ verify |
| 证据冲突 | 补查脚注/更正稿；未解决则保留冲突并走业务升级 |
| 重复查询或两轮无新增可用证据 | 停止，返回具体缺失项 |
| 预算/时间用尽 | 已充分的Claim仍可核验；不充分的返回证据不足 |
| 工具故障 | 技术重试；耗尽后FAILED或显式degraded，不冒充空结果 |
| 引用/计算不一致 | 一次答案修正；失败保留validation错误，不标成通过 |

检索预算默认每 Claim 3 轮（含首轮）、6 次检索类工具调用。混合检索一次算一个工具调用，底层两路调用分别记性能；上下文回取/计算也计入请求级总工具预算。所有重试消耗总耗时和实际tokens。

## 6. 离线任务与应用接口

建库由 `api/routes/knowledge_bases.py → knowledge_base/service.py → Queue → worker → pipeline` 执行，复核请求不触发同步建库。

一键建库 API、任务状态、取消、重试和发布流程由[knowledge_base.md](knowledge_base.md)统一定义。客户端只传 document_ids 与金融配置 profile；基础设施路径和模型对象不通过前端传入。

拟新增复核请求：`POST /reviews {kb_id, report_id|report_text, as_of, profile_id, idempotency_key}`。服务端解析 active 版本并保存；客户端指定历史版本时仍需权限校验。

拟新增检索响应：`{query_id, kb_version, candidates, evidence_bundles, trace_id, degraded, errors}`。模型故障、无候选、元数据歧义采用不同错误/状态。

## 7. 配置骨架（尚未接入运行时）

```yaml
profile_id: financial-rag-v1
embedding:
  provider: flagembedding
  model: BAAI/bge-m3
  output: dense
retrieval:
  dense_backend: chroma
  lexical_backend: rank_bm25
  dense_top_k: 50
  bm25_top_k: 50
  rrf_k: 60
  candidate_top_k: 60
  rerank_model: BAAI/bge-reranker-v2-m3
  rerank_top_n: 12
  context_top_n: 8
  context_token_budget: 6000
agent:
  max_retrieval_rounds: 3
  max_retrieval_tool_calls_per_claim: 6
  max_query_variants_per_round: 3
  max_technical_retries: 2
  max_answer_repairs: 1
  max_total_tool_calls_per_request: 60
  deadline_seconds_per_claim: 90
  deadline_seconds_per_request: 600
  max_total_model_tokens_per_request: 100000
  enable_graph_expansion: false
build:
  profile_id: financial-documents-v1
  publish_policy: all_required_documents_pass
  on_failure: keep_previous_active
```

这是初始实验配置，不是模型能力或性能承诺。启动校验需固定模型 revision、向量维度/距离、中文分词器版本和切块配置；校验 Top-k 正整数、预算上限及 KB manifest 的 embedding 兼容性。对完整报告达到请求预算的未处理 Claim，明确标记未执行，不能静默漏项。

本地 BM25 在授权子集内取 Top-k，绝不能先在全库取 Top-k 再过滤；可以对既有语料统计的分数屏蔽无权文档，并在授权集合内排序。上线多租户环境进一步采用按授权域隔离的索引或支持服务端过滤的后端。DocStore 回取和缓存命中都再次检查当前权限。

## 8. 测试与可观测性

- 单元测试：中文金融词分词一致性、RRF名次、跨路去重、同义查询不重复加权、覆盖与token截断、实体/日期口径、预算退出。
- 集成测试：真实持久化 Dense+BM25、Embedding版本错配、同名文件、增量BM25重建、双索引ID/hash一致、版本发布竞态与worker恢复。
- 端到端：上传→一键建库READY→复核→首轮缺上年值→表格补查→计算→带引用结果；另测无证据与服务中断。
- 评估：固定语料和生成模型做 Dense/BM25/Hybrid/Rerank/工具/Agent 逐层消融，指标见[架构方案](selected_architecture.md)。
- Trace：run_id、claim_id、need_id、kb_version、每路query/rank/score、RRF与Rerank、工具耗时、缺口变化、短决策理由、引用和停止原因。记录结构化决策依据，不要求暴露模型内部思维链。
- 缓存键包含scope指纹、KB版本、模型/分词器版本、查询及约束；命中后复查撤权/tombstone。

## 9. 实施顺序与完成定义

| 阶段 | 交付 | 完成定义 |
|---|---|---|
| P0 契约 | QueryContext、Chunk、Manifest、Hit、AgentDecision | 字段和样例经联调，旧demo明确隔离 |
| P1 真实建库与检索 | 解析切块、Dense、BM25、RRF、Rerank、原文回取 | 一份实际文档生成两路持久化索引，能观测不同召回结果与重排 |
| P2 Agentic循环 | 规划、工具、grade、缺口补查、预算、生成核验 | 有可重复的二轮补查成功样例及预算退出样例 |
| P3 金融增强 | 章节/表格、指标别名、期间/单位/口径、更正稿 | 中文金融标注集评估、错误归因和消融报告 |
| P4 一键建库上线 | 上传UI、持久队列、进度、重试、取消、原子发布 | 用户一次启动，后台完成；失败不破坏线上旧版本 |
| P5 实验优化 | 图扩展、文档树推理、多Reranker | 在固定测试集上证明增益与成本可接受后再默认启用 |

不得将当前字符串检索改名为 BM25，或把 JSON 导出标记为建库完成。详见[当前代码迁移映射](handoff.md)。
