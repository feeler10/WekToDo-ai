# Repository Guidelines

## 项目范围与技术栈

本项目是基于 LangGraph 的个人任务规划 Agent。P0 后端采用 Python 3.11+、LangGraph、LangChain、FastAPI、Uvicorn、Pydantic、HTTPX 与 Redis；Redis 保存任务真实状态、待确认动作、Checkpoint、幂等键和锁。P0 最后仅提供 Vue 3 + TypeScript 的基础对话页。Milvus、Embedding、每日简报、动态重新规划和复杂前端均不在当前范围。开始工作前先阅读 `docs/PROJECT_TASK_BOOK.md` 与 `DEVELOPMENT_PLAN.md`。

## 目录规范

- `agent-service/app/api/`：HTTP 路由；`graph/`：State、节点、路由和 Graph 构建；`tools/`：查询/写入工具；`storage/`：Redis 适配；`schemas/`：Pydantic 输入输出；`services/`：确定性领域逻辑；`core/`：配置与日志。
- `agent-service/tests/`：后端测试，结构尽量与 `app/` 对应。
- `frontend/src/`：仅在后端闭环验收后创建；按 `pages/`、`components/`、`stores/`、`api/`、`types/` 组织。
- `evaluation/`：版本化数据集与评测脚本；`docs/`：架构、API、数据模型和部署文档。

## 开发命令

后端统一使用 Conda 的 `langchain` 环境。以下命令从仓库根目录执行：

```powershell
conda activate langchain
python -m pip install -e '.\agent-service[test]'
Copy-Item .env.example .env
python -m uvicorn app.main:app --app-dir agent-service --reload
python -m pytest agent-service/tests
```

新增或修改命令时必须同步更新 `README.md`，并保证可从干净检出复现。前端尚未初始化，不得虚构 Node 命令。

## 编码与命名

Python 使用四空格、类型注解、`snake_case` 模块/函数/变量和 `PascalCase` 类/Pydantic 模型；节点保持单一职责，确定性计算不得交给 LLM。Vue/TypeScript 使用两空格、`PascalCase.vue` 组件和 `camelCase` 函数。配置、模型名称和端点通过环境配置注入，不在业务代码中写死。

## 测试要求

使用 `test_*.py` 命名。单元测试覆盖时间解析、优先级、状态流转、参数校验、幂等和 `user_id` 隔离；节点测试覆盖 State 输入输出、缺失字段和异常分支；Graph 测试覆盖条件路由、Interrupt、Resume、Checkpoint、拒绝、编辑后恢复及重复请求。每个开发阶段必须携带可独立验收的测试，不以固定覆盖率数字替代关键分支验证。

## 安全、提交与禁止事项

任何写操作必须经过确认、归属校验、幂等校验、版本/状态校验并记录最小审计日志；查询任务状态必须读取 Redis，不得依赖模型记忆。严禁提交 `.env`、密钥或用户数据，严禁绕过 Human-in-the-loop，严禁未经批准扩展 P1/P2、多 Agent、MCP、邮件/日历自动操作或高风险外部操作。提交使用 Conventional Commits，例如 `feat: add task confirmation node`；PR 需说明范围、验证命令、配置变化及 UI 截图（如适用）。
