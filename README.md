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

## 可插拔意图识别

Agent 的分类链路为 `IntentRecognitionContext → IntentRecognitionService → IntentClassifier → Provider → IntentResult → LangGraph Router`。生产环境当前仅实现 `LLMIntentClassifier`，默认使用小模型 `qwen-flash`；`FakeIntentClassifier` 仅用于测试，不会读取生产配置或访问网络。分类器只判断意图、提取基础任务引用和目标状态，不查询 Redis，也不会直接执行任何写操作。创建及状态更新仍必须经过现有参数校验、任务归属校验、确认、幂等和审计流程。

意图模型配置：

```env
INTENT_CLASSIFIER_PROVIDER=llm
INTENT_MODEL_NAME=qwen-flash
INTENT_MODEL_TEMPERATURE=0
INTENT_MODEL_MAX_TOKENS=200
INTENT_MODEL_ENABLE_THINKING=false
```

API Key、Base URL 和结构化输出方式分别复用 `LLM_API_KEY`、`LLM_BASE_URL` 与 `LLM_STRUCTURED_OUTPUT_METHOD`。`rule`、`semantic`、`hybrid` 是已校验的保留 Provider 值，但尚未实现，选择后应用会明确报错而不会静默回退。未来新增 Provider 时，实现统一 `IntentClassifier` 协议并只在 `app/intent/factory.py` 增加构造分支；Graph 路由、API、领域服务和仓储无需修改。

代码导读参见 [`docs/INTENT_RECOGNITION_QUICKSTART.md`](docs/INTENT_RECOGNITION_QUICKSTART.md)。

## Agent API

`POST /api/agent/chat` 接收 `user_id`、`thread_id`、`request_id`、`message` 和 `timezone`，返回待确认草稿及 `pending_action.id`。客户端重试同一请求时应复用 `request_id`。随后将 `pending_action.id` 作为 `action_id` 调用 `POST /api/agent/confirm`。

确认操作支持 `approve`、`edit`、`reject`、`regenerate`。`edit` 需同时传 `edits`；`regenerate` 可传 `feedback`。编辑或重新生成后会返回新的 `action_id` 并再次等待确认。

同一 chat 接口也支持任务查询和状态更新。查询示例包括“查询我的任务”“今天有哪些任务”“有哪些逾期任务”和“查看论文实验详情”，查询结果直接返回 `tasks`，无需确认。状态更新示例为“把论文实验标记为进行中”；唯一匹配时返回待确认动作，同名或模糊匹配多个任务时返回 `candidates` 及任务 ID。确认后才会写入 Redis。

任务引用默认使用可解释的关键词匹配器：

```env
TASK_MATCHER_PROVIDER=keyword
```

`keyword` 按精确 ID、精确标题、规范化标题和关键词包含的顺序匹配，并始终限制当前 `user_id`。`vector`、`hybrid` 是保留配置，当前选择后会明确失败，不会静默降级。

## 测试

```powershell
conda activate langchain
python -m pytest agent-service/tests
```

默认测试全部使用 Fake、Stub 或 Mock，不调用真实模型和外部网络。若要显式执行真实模型评测，请先配置 `.env` 中的模型访问参数，再从仓库根目录运行：

```powershell
conda activate langchain
python agent-service/scripts/check_intent_model.py
```

脚本读取 `evaluation/datasets/intent_cases.json`，只输出期望值、实际结构化结果和统计；它不访问 Redis，也不修改任务。缺少 `LLM_API_KEY` 时脚本会明确退出，且不会调用模型。

前端类型检查与生产构建：

```powershell
cd frontend
npm run typecheck
npm run build
```

## 当前状态

Milestone 7 已加入最小 Vue 对话页、任务确认卡、简单任务列表和确认式状态更新。前端直接使用现有 Agent API，未修改后端契约。意图识别已迁移为可配置的结构化输出模块；属性修改和任务拆解目前会返回“功能暂未开放”。Rule/Semantic/Hybrid Provider、向量检索、多意图拆分、可靠指代消解、复杂参数提取、自动样例学习、Milvus、每日简报、动态规划和复杂仪表盘仍未实现。
