# WekToDo-ai

基于 LangGraph 的 AI 任务规划与执行助手。当前已完成 FastAPI、任务领域模型、Redis 任务存储，以及带 Human-in-the-loop 的任务创建工作流。

## 目录结构

```text
WekToDo-ai/
├── docs/
│   └── PROJECT_TASK_BOOK.md
├── agent-service/
│   ├── app/
│   ├── tests/
│   └── pyproject.toml
├── frontend/
├── evaluation/
├── docker-compose.yml
├── .env.example
├── AGENTS.md
├── DEVELOPMENT_PLAN.md
├── CHANGELOG.md
└── README.md
```

## 开始之前

1. 阅读 `docs/PROJECT_TASK_BOOK.md`。
2. 阅读 `AGENTS.md` 和 `DEVELOPMENT_PLAN.md`。
3. 使用 Conda 的 `langchain` 环境进行开发。
4. 将 `.env.example` 复制为 `.env`，仅在本地填写真实配置。

## 本地启动

以下命令从仓库根目录执行：

```powershell
conda activate langchain
python -m pip install -e '.\agent-service[test]'
Copy-Item .env.example .env
docker compose up -d redis
docker compose ps
python -m uvicorn app.main:app --app-dir agent-service --reload --host 127.0.0.1 --port 8000
```

另开一个终端启动最小 Vue 客户端：

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

前端默认访问 `http://127.0.0.1:5173`，Vite 将 `/api` 请求代理至 FastAPI。若后端地址不同，请修改 `frontend/.env` 中的 `VITE_API_PROXY_TARGET`。

在 `.env` 中填写 `LLM_API_KEY`，并按需修改 `LLM_MODEL` 与 `LLM_BASE_URL`。`LLM_STRUCTURED_OUTPUT_METHOD` 默认使用兼容 DeepSeek、千问等服务的 `json_mode`；确认模型服务支持时可切换为 `function_calling` 或 `json_schema`。修改模型配置后需要重启 FastAPI。访问 `/health` 和 `/health/redis`，预期均返回 `status` 为 `ok`。Redis 8 提供 Checkpointer 所需的 RedisJSON/RediSearch；`CHECKPOINT_REDIS_URL` 必须使用 DB 0。数据保存在持久化 Volume 中。

## Agent API

`POST /api/agent/chat` 接收 `user_id`、`thread_id`、`request_id`、`message` 和 `timezone`，返回待确认草稿及 `pending_action.id`。客户端重试同一请求时应复用 `request_id`。随后将 `pending_action.id` 作为 `action_id` 调用 `POST /api/agent/confirm`。

确认操作支持 `approve`、`edit`、`reject`、`regenerate`。`edit` 需同时传 `edits`；`regenerate` 可传 `feedback`。编辑或重新生成后会返回新的 `action_id` 并再次等待确认。

同一 chat 接口也支持任务查询和状态更新。查询示例包括“查询我的任务”“今天有哪些任务”“有哪些逾期任务”和“查看论文实验详情”，查询结果直接返回 `tasks`，无需确认。状态更新示例为“把论文实验标记为进行中”；唯一匹配时返回待确认动作，同名或模糊匹配多个任务时返回 `candidates` 及任务 ID。确认后才会写入 Redis。

## 测试

```powershell
conda activate langchain
python -m pytest agent-service/tests
```

前端类型检查与生产构建：

```powershell
cd frontend
npm run typecheck
npm run build
```

## 当前状态

Milestone 7 已加入最小 Vue 对话页、任务确认卡、简单任务列表和确认式状态更新。前端直接使用现有 Agent API，未修改后端契约。任务拆解、Milvus、每日简报、动态规划和复杂仪表盘仍未实现。
