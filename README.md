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

任务属性修改同样通过 chat 接口发起，例如“把论文任务改名为最终实验，截止到周五，优先级设为紧急”。当前支持标题、描述、分类、截止时间、预计耗时和用户优先级；唯一匹配后由专用结构化解析器生成最小补丁，经确认后使用 Redis 版本校验和幂等键写入。取消截止时间或恢复 AI 推荐优先级会清空相应用户设置，状态修改仍走独立的 `UPDATE_TASK_STATUS` 流程。

任务删除同样通过 chat 接口发起。独立的结构化删除解析器只把自然语言转换为受控查询参数，支持任意明确日期区间、状态、优先级、分类、多个任务引用、关键词包含匹配，以及“某父任务下的某个/全部直接子任务”。例如“删除所有被取消的代办”“删除八月一日到十日的任务”“删除所有有关论文的代办”“删除论文实验下的结果分析任务”。后端随后从 Redis 确定性查询并完整预览匹配项，用户确认后才在单个事务中全有或全无地物理删除，单批上限为 50 条。

删除与取消任务严格分离：取消写入 `CANCELLED` 状态，删除则不可恢复。当前只允许删除没有直接子任务的叶子任务；存在子任务或外部依赖时整批拒绝。多个显式任务引用会逐项解析：任一引用缺失则整批停止，任一引用存在多个候选则保存上下文并要求逐项选择，不会静默部分删除或把全部同名任务加入批次。删除子任务时，索引清理和父任务联动与批次幂等记录处于同一个 Redis 事务。对已取消任务执行属性修改、状态更新或拆解时，系统先提示恢复；确认恢复为 `TODO` 后自动继续原意图并再次展示相应写操作确认。查询已取消任务会提示恢复规则，而删除已取消任务不要求先恢复。

任务引用默认使用可解释的关键词匹配器：

```env
TASK_MATCHER_PROVIDER=keyword
PENDING_CONTEXT_TTL_SECONDS=900
ACTIVE_TASK_CONTEXT_TTL_SECONDS=1800
TASK_DRAFT_CLARIFICATION_MAX_ROUNDS=4
TASK_UPDATE_CLARIFICATION_MAX_ROUNDS=4
CONVERSATION_HISTORY_MAX_MESSAGES=200
```

`keyword` 按精确 ID、精确标题、规范化标题和关键词包含的顺序匹配，并始终限制当前 `user_id`。`vector`、`hybrid` 是保留配置，当前选择后会明确失败，不会静默降级。


## v0.1.2 查询上下文闭环

不完整列表查询和多候选任务会作为短期流程状态写入现有 LangGraph Checkpoint，并严格绑定 `user_id` 与 `thread_id`。处理优先级为待确认写操作、候选选择、查询澄清、普通意图识别。用户可以在下一轮补充时间范围，或使用序号、候选任务 ID、精确标题选择任务；完成、取消、替换或过期后会清理对应状态。

查询补丁由确定性代码按字段合并，并重新运行阶段一完整性校验；执行仍使用阶段二 `TaskQueryPlan`。候选恢复只信任 Checkpoint 中的候选 ID 和最小上下文，选择后必须按当前用户重新读取 Redis，并校验任务版本与状态。查询选择保持只读；状态更新选择后仍需经过原有确认流程。

任务列表、详情、零匹配、多候选和状态更新结果由确定性中文格式化层生成。任务事实只来自 Repository 返回的真实 `Task`，截止时间按请求业务时区显示，不使用 LLM 自由总结。短期状态默认 15 分钟过期，可通过 `PENDING_CONTEXT_TTL_SECONDS` 调整。

## v0.2.3 多轮对话基础能力

### 第一阶段：短期任务焦点与单数指代

同一 `user_id + thread_id` 在唯一定位、创建、更新或选择任务后，会把该任务 ID 作为短期 `ActiveTaskContext` 写入现有 LangGraph Checkpoint。后续可以使用“它”“这个任务”“那个任务”“刚才的任务”等受控单数指代继续查询详情、更新状态、修改普通属性或拆解任务。焦点默认 30 分钟过期，可通过 `ACTIVE_TASK_CONTEXT_TTL_SECONDS` 调整。

焦点上下文只保存任务 ID、用户/线程归属和过期时间，不保存任务属性，也不向 LLM 注入原始聊天历史。每次使用焦点后仍通过现有 Matcher 按精确 ID 定位，并从 Redis 重新读取真实任务；写操作继续执行归属、版本、状态、确认和幂等校验。显式名称或 ID 会覆盖旧焦点；普通列表返回多个任务、零匹配、焦点过期或任务已删除时不会猜测。当前不支持复数指代、批量状态修改、上下文删除、跨线程记忆或自然语言确认。

### 第二阶段：创建任务跨轮参数收集

创建任务时，结构化解析先产生可缺字段的 `TaskDraftCandidate`。如果缺少标题，或模型明确标记截止时间、分类等字段存在歧义，Graph 会把当前候选草稿、本次创建输入、缺失字段、轮次和过期时间写入 Checkpoint，在同一 `user_id + thread_id` 的下一轮继续补齐。后续明确修正优先于较早输入。

收集过程默认最多 4 轮，使用 `PENDING_CONTEXT_TTL_SECONDS` 的短期 TTL；可通过 `TASK_DRAFT_CLARIFICATION_MAX_ROUNDS` 调整轮数。“取消”“算了”等可终止本次创建，明确的查询、状态更新、拆解或删除请求可替换当前草稿。补齐期间不写 Redis；只有形成严格 `TaskDraft`、进入原有确认链路并获得用户批准后，才会执行一次幂等创建。这是操作级短期上下文，不等于完整聊天历史或长期记忆。

### 第三阶段：修改任务跨轮参数收集

任务唯一定位后，如果用户尚未指定要修改的字段、只说了“标题”但没有新值，或截止时间等表达存在歧义，Graph 会保存 `PendingTaskUpdateClarification`。例如“修改接水任务 → 标题 → 改成每天早上接水”会在同一修改流程中逐轮补齐，后面的明确修正覆盖较早冲突内容。

待补充上下文只保存目标任务 ID、期望版本、已确定的最小修改结果、有限输入和过期信息。每次恢复都会按当前用户从 Redis 重读任务并校验版本；任务被删除或已发生变化时停止旧修改。支持取消、明确新请求替换、TTL、用户/线程隔离和最大轮数，轮数默认为 4，可通过 `TASK_UPDATE_CLARIFICATION_MAX_ROUNDS` 调整。补齐后只进入修改预览，用户确认前不写 Redis。

## v0.2.4 多轮对话稳定性基线

`evaluation/datasets/multiturn_cases.v1.json` 固化了创建与修改任务的版本化多轮用例。评测按每轮结构化结果检查澄清/就绪路由、缺失字段、标题和最小修改补丁，不要求模型生成完全相同的自然语言追问。真实模型脚本只调用创建与修改解析器，不访问 Redis，也不会执行任何任务写入。

创建和修改任务的待补充节点会记录统一的 `pending_operation` 事件，包括 `prepared`、`resumed`、`cancelled`、`replaced`、`expired`、`stale` 和 `max_rounds`。事件只包含请求、用户、线程、轮次、任务 ID/版本、缺失字段、固定原因、下一节点和过期时间等受限元数据，不记录用户原话、任务标题或草稿正文。

API 回归用例覆盖“修改接水任务 → 标题 → 改成每天早上接水 → 确认”的真实 HTTP 契约：三次 chat 必须复用同一 `thread_id`，前两轮返回 `needs_clarification`，第三轮返回 `awaiting_confirmation`，确认前任务保持原值和原版本，批准后才执行一次版本化修改。Vue Store 已符合该契约：线程 ID 在页面会话内保持不变，只有 `awaiting_confirmation` 才锁定为待确认动作，`needs_clarification` 时输入框继续可用。

## v0.2.5 对话历史持久化与刷新恢复

Agent chat 和 confirm 成功返回后，会把用户展示文本与完整 `AgentResponse` 作为一组对话交换写入 Redis。Vue 页面只在 `localStorage` 保存当前用户和 `conversation_id` 指针；页面启动或刷新时调用以下只读接口恢复消息、任务展示、澄清状态和当前待确认卡：

```http
GET /api/agent/conversations/{conversation_id}?user_id={user_id}
```

现阶段 `conversation_id` 与原有 `thread_id` 是同一个值。重复 `request_id` 和重复确认使用历史操作键去重；单个对话默认保留最近 200 条展示消息，可通过 `CONVERSATION_HISTORY_MAX_MESSAGES` 调整。历史写入失败会记录错误，但不会把已经成功的任务写操作伪装成失败或重复执行任务。

存储契约已按 `tenant_id + user_id + conversation_id` 分层，当前服务内部固定使用 `tenant_id=default`。Redis 还会更新用户级对话时间索引，为后续左侧对话列表、切换、重命名和归档预留入口；本版本没有开放租户参数、对话列表 API 或侧栏 UI。完整对话历史不会重新注入 LLM，也不替代 LangGraph Checkpoint；任务事实仍从任务 Repository 读取。

## 测试

```powershell
conda activate langchain
python -m pytest agent-service/tests -m 'not integration'
```

上述测试使用 Fake、Stub、Mock 或内存实现，不调用真实模型和外部服务。

本机 Redis 通过 IPv6 回环地址提供服务时，可运行真实 Redis 与 Checkpoint 集成测试：

```powershell
$env:TEST_REDIS_URL='redis://[::1]:6379/15'
$env:TEST_CHECKPOINT_REDIS_URL='redis://[::1]:6379/0'
python -m pytest agent-service/tests/integration
```

真实任务数据测试使用 Redis DB 15，Checkpointer 按约束使用 DB 0。

若要显式执行真实模型评测，请先配置 `.env` 中的模型访问参数，再从仓库根目录运行：

```powershell
conda activate langchain
python agent-service/scripts/check_intent_model.py
python agent-service/scripts/check_multiturn_model.py
```

两个脚本分别读取 `evaluation/datasets/intent_cases.json` 和 `evaluation/datasets/multiturn_cases.v1.json`，只输出期望值、实际结构化结果和统计；它们不访问 Redis，也不修改任务。缺少 `LLM_API_KEY` 时脚本会明确退出，且不会调用模型。

前端类型检查与生产构建：

```powershell
cd frontend
npm run typecheck
npm run build
```

## 当前状态

Milestone 7 已加入最小 Vue 对话页、任务确认卡、父子层级任务列表、确认式状态更新和确认式属性修改。P1a 后端已支持 AI 任务拆解、完整方案确认与编辑、Redis 原子批量创建直接子任务，以及子任务状态对父任务进度和完成状态的自动联动；v0.2.2 进一步支持自然语言删除计划、预览后原子批量删除，以及 `CANCELLED` 任务先恢复再继续原意图；v0.2.3 统一收录了同线程唯一任务焦点、受控单数指代、创建任务跨轮缺失参数收集，以及修改任务跨轮字段/新值收集、版本冲突防护与 Checkpoint 恢复；v0.2.4 增加版本化多轮评测、HTTP 零写入回归和隐私受限的待补充事件日志；v0.2.5 将展示用对话历史持久化到 Redis，并支持页面刷新后恢复当前会话。前端可展示批量删除清单与恢复确认，并在删除成功后同步移除本地任务。完整多租户认证、GPT 式对话侧栏、更复杂的多级任务树页面仍未建设。Rule/Semantic/Hybrid Provider、向量检索、多意图拆分、复数及列表序号上下文引用、自动样例学习、Milvus、每日简报、动态规划和复杂仪表盘仍未实现。
