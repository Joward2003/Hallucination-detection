> 历史快照，已被 2026-09-16 Agentic RAG 重设计替代。不是当前开发要求。原有相对链接仅保留为历史文本。

# 金融信贷分析报告 AI 复核工作台交接文档

版本：0.2.0  
日期：2026-09-16  
状态：核心闭环可运行；DeepSeek 为显式启用的可选模型适配器

## 1. 当前交付范围

当前系统围绕 `Parent–Child Fact → Evidence → Verification` 工作，默认不调用外部模型，保证离线测试和敏感数据安全。

已完成：

- Parent–Child 保守拆分，保留联合因果、不确定性和原始区间；
- 公司名称/股票代码确定性识别；
- 文本/表格查询规划、内存证据检索和最多一次 Query Rewrite；
- 支持、部分支持、无关、反向证据评级；
- `SUPPORTED`、`CONTRADICTED`、`INSUFFICIENT_EVIDENCE` 三态核验；
- SourceScope 先过滤后检索；
- 确定性同比、期间、单位和基础规则检查；
- 低置信/反向证据 Critic 路由，冲突进入人工待办；
- 人工决策版本校验和 `resume_review` 恢复；
- `ReviewManager` 幂等创建、查询、取消和人工提交；
- 内存 checkpoint、追加式审计和敏感字段脱敏；
- DeepSeek OpenAI-compatible Gateway，以及 Parent–Child、Query Planner、Fact Verifier 的结构化适配器。

当前明确未完成：真实 Chroma/Reranker、生产数据库、真实权限中间件、正式业务规则集、前端，以及生产级异步队列和 checkpoint。

## 2. 目录和模块衔接

```text
src/credit_review/
├── config/models.py                 DeepSeekConfig，读取环境变量
├── config/settings.py               运行配置
├── infrastructure/deepseek_gateway.py  DeepSeek API 网关
├── agents/deepseek_agents.py        结构化抽取/规划/核验适配器
├── agents/                          Agent 契约和确定性默认实现
├── graph/builder.py                 主图、风险路由、人工恢复
├── retrieval/                       SourceScope 过滤和检索服务
├── verification/                    引用、数值、充分性和冲突检查
├── rules/                            版本化规则引擎
├── policies/                         重试、置信度和风险策略
├── api/                              ReviewManager 和可选 FastAPI 适配器
├── infrastructure/checkpoints.py    内存 checkpoint
├── observability/audit.py            追加式审计
└── security/redaction.py             日志/模型输入脱敏
```

调用链：

```text
run_review_with_deepseek
  → DeepSeekParentChildExtractor
  → DeepSeekQueryPlanner
  → 本地 Scope 过滤 + Evidence Retrieval
  → 本地 Evidence Grading
  → DeepSeekFactVerifier
  → 本地 Numeric/Rule/Risk Gate
  → Critic / Human / Aggregate
```

DeepSeek 只负责结构化 Agent 决策；数值计算、权限过滤、规则、重试上限和最终路由仍由本地代码控制。模型输出经过 JSON/schema 校验，失败时回退到确定性实现。

## 3. DeepSeek 配置

官方 OpenAI-compatible Base URL 为 `https://api.deepseek.com`。当前默认模型写为 `deepseek-v4-flash`，但模型名可以完全通过环境变量覆盖；不要把 Key 写入 Python、State、日志、测试夹具或文档。

配置模块：[`src/credit_review/config/models.py`](../src/credit_review/config/models.py)

### 3.1 本地配置

```bash
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，只填本机密钥：

```dotenv
DEEPSEEK_API_KEY=你的真实密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_TIMEOUT_SECONDS=60
DEEPSEEK_TEMPERATURE=0
DEEPSEEK_MAX_TOKENS=2048
```

当前实现只读取进程环境变量，不自动读取 `.env` 文件。运行前执行：

```bash
set -a
source .env
set +a
```

生产环境应使用密钥管理服务或部署平台 Secret 注入，不使用 `.env`。

### 3.2 安装和导入

```bash
pip install -e '.[deepseek,test]'
```

验证配置时只打印脱敏结果：

```bash
PYTHONPATH=src python - <<'PY'
from credit_review.config.models import DeepSeekConfig
print(DeepSeekConfig.from_env(require_key=True).safe_dict())
PY
```

### 3.3 启用 DeepSeek 复核

```python
from credit_review import run_review_with_deepseek

result = run_review_with_deepseek(
    "公司2024年营业收入同比增长20%。",
    evidence=[{
        "evidence_id": "E001",
        "content": "公司2024年营业收入同比增长20%",
        "source": "annual_report_2024",
        "page": 32,
        "evidence_type": "table",
    }],
)
```

该入口会创建 `DeepSeekGateway` 并要求 `DEEPSEEK_API_KEY`。默认的 `run_review(...)` 仍是离线确定性流程，不会因为环境中存在 Key 就自动调用外部模型。

## 4. 测试与连通性

## 4.1 本地示例：建库与复核

已提供不含真实业务数据的示例文件：

- `examples/data/report/sample_report.txt`：待复核 AI 报告；
- `examples/data/source/annual_report_2024.txt`：模拟原始材料；
- `scripts/build_kb.py`：将文本材料切成 Evidence JSON；
- `scripts/run_example_review.py`：打印建库/复核过程并保存结果；
- `examples/data/output/sample_review_result.json`：最近一次示例结果。

运行：

```bash
set -a
source .env
set +a
PYTHONPATH=src python scripts/build_kb.py
PYTHONPATH=src python scripts/run_example_review.py
```

建库脚本是后续接入 OCR、PDF、表格解析或 Chroma 的适配起点；只要保持 Evidence 字段不变，Graph 不需要改动。

离线测试：

```bash
pytest -q
python -m compileall -q src tests
```

DeepSeek 测试使用 fake gateway，不发送网络请求、不消耗额度，覆盖：

- 环境变量读取和 Key 脱敏；
- 缺少 Key 时提前失败；
- OpenAI-compatible 请求结构和 JSON 输出；
- DeepSeek Agent 与现有 Graph、数值校验的衔接。

只有在已配置 Key 后，才执行真实连通性检查：

```bash
PYTHONPATH=src python - <<'PY'
from credit_review.config.models import DeepSeekConfig
from credit_review.infrastructure.deepseek_gateway import DeepSeekGateway

config = DeepSeekConfig.from_env(require_key=True)
print(DeepSeekGateway(config).healthcheck())
PY
```

本次交接时环境没有 `DEEPSEEK_API_KEY`，所以真实调用未执行；离线测试已通过。

## 5. 风险和后续工作

- 真实模型输出不可直接视为事实；必须保留本地证据、数值、规则和风险门控；
- `DeepSeek*` Agent 当前异常时回退确定性实现，生产环境应增加结构化错误审计和告警；
- 目前内存检索和内存存储不具备生产隔离能力；
- 接入真实数据前必须完成租户/项目/文档 ACL、数据分级和外部模型白名单；
- 接入异步 API 前应将 `ReviewManager` 替换为持久化仓储和 LangGraph checkpointer；
- 正式上线前需要用业务标注集校准规则、置信等级、Critic 触发条件和人工升级比例。

## 6. 接手建议

1. 配置 Secret，但先运行脱敏配置检查，不直接提交 Key。
2. 用 fake gateway 运行 `tests/test_deepseek.py`，确认模块契约未被改动。
3. 在隔离测试数据上执行一次 `run_review_with_deepseek`，检查模型调用审计和证据链。
4. 再接入真实 Retriever/文档版本/权限过滤，不要先删除确定性回退。
5. 最后再启用生产异步任务、持久化、人工工作台和正式规则集。
