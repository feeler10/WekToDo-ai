# WekToDo-ai

基于 LangGraph 的 AI 任务规划与执行助手。当前已初始化 FastAPI 服务骨架，任务、Agent、存储和前端能力将在后续里程碑实现。

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
python -m uvicorn app.main:app --app-dir agent-service --reload --host 127.0.0.1 --port 8000
```

访问 `http://127.0.0.1:8000/health`，预期返回 `status` 为 `ok`。

## 测试

```powershell
conda activate langchain
python -m pytest agent-service/tests
```

## 当前状态

Milestone 1 仅包含 FastAPI 入口、统一配置、统一异常处理、健康检查和 pytest 骨架。尚未接入 LangGraph、大模型、Redis、任务业务或前端。
