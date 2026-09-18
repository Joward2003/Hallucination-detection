# 演示数据与运行边界

本目录只包含模拟材料。示例默认运行 provider-free Dense/BM25/RRF/Rerank；生产环境可安装 `.[rag]`，通过 `create_production_hybrid_search` 接入真实 BGE-M3、BM25S 和 Cross-Encoder。

## 导出Evidence JSON

在项目根目录执行：

```bash
PYTHONPATH=src python scripts/build_kb.py
```

脚本将 `examples/data/source/` 中的TXT/Markdown按空行切片，写入 `examples/data/kb/evidence.json`。也可以用 `--mineru-json` 或 `--parent-child-output` 生成带层级、原子事实、表格定位和 metric_ids 的建库快照；真实检索索引由生产检索工厂按 KB 版本构建。

安装真实检索依赖：

```bash
python -m pip install -e '.[rag]'
```

生产检索工厂默认使用 `BAAI/bge-m3` 生成 Dense 向量、BM25S 保存词法索引，并用
`BAAI/bge-reranker-v2-m3` 对 RRF 候选做 Cross-Encoder 重排。模型首次使用时需要提前下载或设置
`CREDIT_REVIEW_RETRIEVAL_LOCAL_FILES_ONLY=1` 并提供本地模型目录。

将一键建库切到真实检索：

```python
from credit_review.config.models import RetrievalConfig
from credit_review.knowledge_base import BuildManager, KnowledgeBaseRepository

builds = BuildManager(
    KnowledgeBaseRepository("build/kb"),
    retrieval_backend="sentence_transformers",
    retrieval_config=RetrievalConfig(backend="sentence_transformers"),
)
```

构建阶段会在 `build/kb/indexes/<kb_id>/<kb_version>/` 保存 Dense 与 BM25S 索引；在线查询加载
同一版本并用 Cross-Encoder 重排。生产部署应把该目录放在持久卷，并设置
`CREDIT_REVIEW_EMBEDDING_REVISION`、`CREDIT_REVIEW_RERANKER_REVISION` 固定模型 revision。

## 可选DeepSeek演示

Python 3.10+，先安装可选依赖：

```bash
python -m pip install -e '.[deepseek,graph]'
```

在本机 `.env` 中配置 `DEEPSEEK_API_KEY`，模型名使用账号实际可用值设置 `DEEPSEEK_MODEL`；当前程序不自动读取该文件。运行：

```bash
set -a
source .env
set +a
PYTHONPATH=src python scripts/run_example_review.py

# 在终端输出 Agent loop 的结构化 trace
PYTHONPATH=src python scripts/run_example_review.py --trace
```

该命令会调用外部模型，把模拟报告与相关证据发送至配置的模型服务，并保存示例输出；模型负责抽取、Planning 和核验，检索 Worker 仍在本地运行。不要用这个演示输出证明生产RAG召回或金融核验准确率。

`--trace` 会输出各图节点的开始/结束、耗时、结构化 Planning 结果、查询参数、检索路由和候选分数、证据评估、验证结果及每次路由原因。它展示模型返回的可执行决策摘要，不记录或输出私有逐字思维链。Trace 默认关闭，避免在普通运行时输出报告内容。

目标实现将改成 `kb_id + kb_version` 查询，新增统一原文、双索引、检索轨迹等契约。旧Evidence字段只能作为迁移输入，不能认为维持JSON字段不变就完成接入。

参见[架构方案](../docs/selected_architecture.md)与[一键建库设计](../docs/knowledge_base.md)。
