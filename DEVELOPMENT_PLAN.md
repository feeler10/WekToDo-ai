# 第一版 P0 开发计划

## 1. 范围判定

本计划以 `docs/PROJECT_TASK_BOOK.md` 第 23 章 P0 清单和第 29.1 节第一版验收标准为准。第一版目标是形成以下最小闭环：

```text
自然语言输入 → 结构化解析 → 时间/优先级计算 → 用户确认
→ Redis 保存 → 对话查询 → 状态更新 → Checkpoint 恢复
```

P0 包含 FastAPI 服务、单一 LangGraph 主流程、Agent State、意图识别、任务结构化解析、时间解析、优先级计算、Human-in-the-loop、Redis Checkpoint、创建/查询/状态更新工具、幂等控制和基础对话页。第 29.1 节要求的用户隔离、真实数据查询和最小工具执行日志属于闭环验收约束；这不等同于提前实现 P1 的完整 Trace。

## 2. 分阶段实施与独立验收

### 阶段 0：范围与契约冻结（当前）

明确 P0、目录边界、数据字段、状态流转、确认规则和延期项。验收：`DEVELOPMENT_PLAN.md` 与 `AGENTS.md` 内容一致，未产生业务代码或依赖变更。

### 阶段 1：FastAPI 基础骨架

初始化 Python 3.11+ / FastAPI 工程、统一配置、统一异常处理和健康检查，建立 pytest 测试骨架并补充启动文档。验收：服务可启动；`GET /health` 返回 `status=ok`；health 测试可从干净检出重复运行。此阶段不接入 Redis、LangGraph、大模型、任务业务或前端。

### 阶段 2：确定性领域与 Redis 存储

接入 Redis 连接与健康检查；定义 Task、PendingAction、工具参数等 Pydantic Schema；实现时区时间解析、优先级公式、合法状态流转、任务存储、`user_id` 隔离、版本校验和幂等键。验收：单元测试覆盖正常、边界、歧义、非法流转、跨用户访问与重复请求，任务读写不依赖 LLM。

### 阶段 3：只读 Agent 与任务草稿

定义可序列化 Agent State，完成 `load_context`、`classify_intent`、`parse_task`、`validate_task`、`calculate_priority`、`query_tasks` 和错误处理节点。验收：自然语言可生成结构化待确认草稿；信息不足时不写入；查询从 Redis 返回真实数据；节点和条件路由可独立测试。

### 阶段 4：确认式任务创建

实现 PendingAction、`prepare_tool_call`、Interrupt/Resume、确认/编辑/重生成/取消分支、Redis Checkpoint 与 `create_task`。验收：未确认不写入；恢复从 Checkpoint 继续而非重跑；相同幂等键只创建一次；重启会话后可查询已创建任务。

### 阶段 5：状态更新与 API 闭环

实现任务引用解析、候选消歧、确认式状态更新、线程状态查询及最小工具审计日志，完成 chat/confirm/resume 和必要任务查询接口。验收：创建、查询、状态更新、拒绝、异常恢复和用户隔离通过端到端测试；非法状态流转、版本冲突和 Redis 故障不会继续写入。

### 阶段 6：P0 基础对话页与交付

后端闭环稳定后再创建最小 Vue 3 + TypeScript 页面，仅支持对话输入、草稿展示、确认操作和结果查看；不建设复杂任务面板。验收：用户可从页面完成 P0 端到端闭环；部署与使用文档包含可复现命令。注意：本次文档任务不创建任何前端文件。

## 3. 阶段 1 预计文件清单

阶段 1 实施时预计创建：

```text
agent-service/
├── pyproject.toml
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── router.py
│   │   └── health.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── exceptions.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    └── test_health.py
```

同时创建 `.gitignore`，更新现有 `.env.example` 和 `README.md`。阶段 1 不创建 `frontend/` 内容，也不创建 Redis、Graph、任务工具或领域服务实现。


## 3.1 v0.1.2 查询上下文闭环

阶段三复用现有 Redis Checkpointer 保存短期 `PendingQueryClarification` 与 `PendingTaskSelection`。查询补丁按字段确定性合并并重新执行阶段一完整性校验；多候选只保存候选 ID、版本和最小操作上下文，选择后按 `user_id + task_id` 重读 Redis。查询选择只读，状态更新选择后继续进入现有 PendingAction 确认链路。所有待处理状态绑定用户和线程、统一过期，并在完成、取消、新请求替换或不可恢复错误时清理。中文响应只格式化真实结构化数据，不查询仓储或调用 LLM。

## 3.2 v0.1.3 对话式任务属性修改

在现有 `UPDATE_TASK` 意图、关键词任务匹配、PendingAction 与 Redis 乐观并发控制基础上，增加对话式普通属性修改闭环。第一阶段仅允许修改 `title`、`description`、`category`、`deadline`、`estimated_minutes` 和 `user_priority`；状态继续由 `UPDATE_TASK_STATUS` 独立处理，禁止修改 ID、归属、AI 优先级、有效优先级、紧急度、进度、版本和审计时间字段。

属性修改采用独立结构化解析器：意图识别只确定 `UPDATE_TASK` 和任务引用，从 Redis 唯一定位任务后，解析器结合当前任务、业务时区和当前时间生成最小字段操作列表。多候选状态保留原始修改语句，用户选择后重新按 `user_id + task_id` 读取并校验版本。所有补丁经过 Pydantic 白名单校验、前后值预览和 Interrupt 确认，再使用 `WATCH/MULTI/EXEC`、`expected_version` 与 `update_task:{request_id}` 幂等键写入 Redis。

验收覆盖标题、截止时间、优先级、多字段修改、字段清空、解析澄清、多候选恢复、拒绝、重复请求、版本冲突和用户隔离；基础 Vue 确认卡只允许确认或取消属性修改。

## 4. 当前明确不实现

- **P1**：任务拆解、批量子任务、父子进度、下一步推荐、SSE、完整工具日志和基础 Trace。
- **P2**：Milvus、Embedding 与长期记忆、Reranker、混合检索、每日简报、动态重新规划、周期复盘、完整评测平台、复杂任务面板。
- **复杂前端**：任务看板、每日简报页、执行轨迹页、统计图表、复杂筛选、主题系统、移动端适配；P0 只保留基础对话和确认交互。
- **任务书明确延期项**：多 Agent、MCP Server、邮件/日历自动操作、语音、多人协作、移动 App、复杂权限、复杂 RAG/甘特图、自动长期日程、团队/社交功能及高风险外部操作。

任何延期项进入实施前，必须先更新范围、验收标准和本计划；不得以“预留”为由提前引入依赖或业务代码。
