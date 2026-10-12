# v0.2 工作台交接

本次主修改目录为 `/Users/joward/Desktop/Hallucination/Hallucination_detection`，包含原有 frontend。此前 `Documents/Codex/.../outputs/Hallucination_detection` 是旧 CLI 改进副本，不是本次工作台的启动目录。

核心新增模块：

- `workbench/storage.py`：持久化记录、追加式哈希链。
- `workbench/knowledge.py`：真实原件解析、父子块版本化、真实混合召回与父块回补。
- `workbench/gateway.py` / `provider/`：真实 Responses / Chat Completions、凭据隔离、请求与响应底稿。
- `workbench/agents.py`：来源约束的模型抽取、证据评分、判定、Decimal 计算与人工路由。
- `workbench/reviews.py`：异步任务、逐节点检查点、整体风险检查、失败重试与人工继续。
- `workbench/exports.py`：PDF / HTML / ZIP 底稿。
- `workbench/app.py`：本机同源 API。
- `frontend/src/workbench.js`：知识库、模型管理、规则、工作底稿和任务进度界面；原有三栏复核界面保留。

知识库导入的国华网安 PDF 首页面明确为 2024 年年报。早期联调时的期间误填修正过程也保存在来源底稿；后续使用正确期间的发布版本。MinerU 表格文本可能包含 OCR 错字，原件链接用于核对；解析数据不等同于经过人工确认的真值。

正式推广需要由项目团队给出规则口径、风险必查清单和人工标注样本，再标定不同风险的召回覆盖与判定阈值。当前规则不会代替银行授信审批。部署到多人环境前还需接入机构身份、角色授权、数据隔离与外部审计签名；本机版本仅开放 loopback。
