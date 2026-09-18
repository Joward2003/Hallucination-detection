# AI 金融报告智能复核工作台前端

这是当前 Python 项目的轻量浏览器界面。页面不内置复核结果样例；任务、Finding、Evidence、核验状态和检索轨迹都取自现有复核 API。前端把后端的 `completed_results` 适配为视图模型，并以 `fact_id` 和 `evidence_id` 作为稳定联动键。

## 运行

```bash
python -m pip install -e '.[api]'
credit-review-api
```

浏览器打开 `http://127.0.0.1:8000`。ASGI 入口位于 `src/credit_review/api/server.py`，同时提供静态前端和原有 `/v1/*` API，因此默认同源访问。当前 API manager 和 review record 都是内存实现；重启服务会清空任务。生产部署前应换成持久化仓储并配置鉴权。

默认运行使用项目已有的 deterministic Agent / retrieval 实现。启用 DeepSeek 时，在启动进程环境中设置 `CREDIT_REVIEW_AGENT_BACKEND=deepseek` 与 `DEEPSEEK_API_KEY`，并安装 `python -m pip install -e '.[api,deepseek]'`。是否使用真实向量检索由项目原有 `CREDIT_REVIEW_RETRIEVAL_BACKEND` 等配置决定；界面不会将 deterministic 模式标为生产模型结果。

也可从 `系统设置` 设置其他 API 地址。跨源部署需要由 API 服务自行配置 CORS；同源部署不需要额外配置。

## 现有 API 映射

| 前端行为 | 使用的后端接口 / 字段 |
| --- | --- |
| 创建复核 | `POST /v1/reviews`，提交 `report_text` 和可选 `evidence[]` |
| 复核详情 / 刷新 | `GET /v1/reviews/{review_id}` |
| 人工队列 | `GET /v1/human-tasks` |
| 人工判定 | `POST /v1/human-tasks/{review_id}/decision`，提交 `task_version`、三态 `decision`、`comment`、`selected_evidence_ids`、`decided_by` |
| 报告段落定位 | `fact_groups[].children[].source_start/source_end` |
| Finding ↔ Claim | 以现有稳定 `fact_id` 关联；当前 schema 没有独立 `finding_id` |
| Evidence ↔ 原文片段 | `evidence_id`、`content`、`source`、`page`、`section`、`document_id`、`score` |
| Evidence 关系 / 缺口 | `assessments[]`、`missing_needs[]`、`retrieval_trace[]` |

报告和参考材料文件输入目前仅解析本机 `.txt` / `.md`。参考文本按空行或换行拆成 Evidence，随请求原样提交给当前 API。浏览器本机历史只保留任务 ID、名称、状态和计数，不保存报告正文。CSV 与 JSON 导出在浏览器本机生成。

## 后端尚需补充的契约

1. **文件上传与原件读取**：当前接口只收 `report_text` 和内嵌 Evidence。建议增加授权校验的上传 / 解析接口，返回 `document_id`、版本、页数、页面文本与安全原件 URL；PDF 定位还需要页码和文本坐标（bbox 或字符区间）。
2. **持久化与异步进度**：`ReviewManager` 为进程内存，同步运行 `run_review`，没有列表、分页、取消后的持久状态或 Agent 阶段流。建议改为持久化 Review Repository + 后台任务，并增加 `GET /v1/reviews`、轮询状态或 SSE 事件。
3. **单条问题操作**：现有人工决策能提交三态判定与意见，但没有“编辑最终结论”“单条补充检索” endpoint。建议在 Finding/Claim 下增加版本化的人工修改记录与补充检索动作，并返回 `final_text`、操作人、时间及审计记录。
4. **推理步骤**：当前有 `reasoning_summary` / 规则命中说明，但没有结构化 `ReasoningStep[]`。界面只连接真实 Evidence 与 Claim，并明确标出缺少步骤字段。
5. **完整人工恢复**：`resume_review` 能保存当前挂起 Claim 的判定，但当还有后续 Claim 时不会继续运行图流程。建议通过真实 checkpoint 恢复剩余图节点，并返回新的状态 / 待办任务。
6. **来源查看与结果文档**：现有 Evidence 有页码和片段，但没有 PDF 原件流或字符坐标；当前也没有 PDF / Excel 导出与独立 audit log API。界面提供 Evidence 片段、CSV 问题表和完整 API JSON，不伪称已定位原 PDF 或生成正式审计文档。

默认 `server.py` 不注入 `BuildManager`，因此现有知识库 build/search 路由仍需在部署入口注入项目已有服务后才可调用。
