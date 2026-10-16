# 修复入口

当前实现和验证说明见 [FIXES_SUMMARY.md](FIXES_SUMMARY.md)。

不要再运行历史文档中的 `agents_fixed.py` 文件替换命令；该文件已不存在。生产代码为 `workbench/agents.py`，其数值校验实际导入 `workbench/numeric.py`。`agents_old.py` 是不参与执行的历史备份。

此前已删除与真实存储脱节的优化模块和冗余前端文件，本轮保留清理结果。
