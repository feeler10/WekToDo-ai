# Changelog

本项目的重要变更将记录在此文件中。

## [Unreleased]

暂无。

## [0.2.5] - 2026-08-11

> 持久化展示用对话历史，使当前多轮会话可在浏览器刷新后恢复，并为多租户归属和 GPT 式对话列表预留数据边界。

### 版本内实际开发顺序

1. 冻结范围：只实现当前会话的消息持久化和刷新恢复，不开发租户管理、对话列表侧栏、切换/删除 UI 或长期 LLM 记忆。
2. 定义 `ConversationScope`、`ConversationRecord`、`ConversationMessage` 和历史响应，归属键从一开始包含 `tenant_id + user_id + conversation_id`。
3. 实现 Redis 对话仓储，以事务原子追加一组用户/Agent 消息，维护首条消息标题、消息总数、更新时间和用户级对话索引。
4. 使用 chat `request_id` 与 confirm `action_id + action` 作为历史操作幂等键，增加最近消息上限和七天操作键 TTL。
5. 将历史记录接入 `TaskAgentService`；任务流程成功后再写历史，历史故障只记录日志，不改变已经完成的任务结果。
6. 增加单对话恢复 API，并验证用户、租户和同名 conversation 的隔离。
7. 前端持久化当前用户/会话指针，页面启动和用户切换时从后端恢复消息、任务展示与待确认卡。
8. 增加 FakeRedis、HTTP 和真实 Redis 重建测试，同步配置、README、前端说明和版本号。

### Added

- 新增 Redis 对话仓储和 `GET /api/agent/conversations/{conversation_id}` 只读恢复接口。
- 新增 `CONVERSATION_HISTORY_MAX_MESSAGES`，默认保留每个对话最近 200 条展示消息。
- 新增用户级 Redis 有序索引，按更新时间记录 conversation ID，为后续对话列表预留查询入口。
- 新增前端启动恢复与按用户保存活动 conversation ID 的逻辑。

### Security and Reliability

- 当前租户固定为 `default`，客户端不能提交或切换 `tenant_id`；未来应由认证上下文注入租户，而不是信任请求参数。
- Redis Key 同时编码租户、用户和对话 ID；相同 conversation ID 在不同租户或用户下互不可见。
- 用户消息和 Agent 展示响应会持久化到 Redis，但不会作为完整历史重新注入 LLM，也不会替代任务真实数据或 Checkpoint。
- 每次交换的两条消息在单个 Redis 事务中写入；重复请求和重复确认不会产生重复历史。
- 历史写入属于展示副作用；失败会记录受限元数据日志，但不会让已经成功的任务写入被客户端误认为失败并重试。

### Tests

- 新增仓储幂等、消息上限、标题/计数、索引、租户隔离、用户隔离和 conversation 隔离测试。
- 新增多轮创建刷新恢复、待确认卡恢复、重复确认历史幂等和历史故障不遮蔽 Agent 成功响应测试。
- 新增真实 Redis 仓储重建后恢复同一对话历史的集成测试。
- 后端完整测试结果：`369 passed, 9 warnings`，包含真实 Redis 对话仓储重建和既有 Redis Checkpoint 集成测试。
- 前端 `npm run typecheck` 与 `npm run build` 通过；Vite 保留现有大于 500 kB 的 chunk 警告。

## [0.2.4] - 2026-08-11

> 在不扩大多轮能力边界的前提下，为 v0.2.3 增加可重复评测、HTTP 闭环回归和隐私受限的运行观测。

### 版本内实际开发顺序

1. 在开发计划中冻结 v0.2.4 范围和判定标准，明确不引入完整聊天历史、长期记忆或新的前端测试框架。
2. 定义版本化多轮评测数据模型和 `multiturn_cases.v1.json`，覆盖创建与修改任务的逐轮结构化预期。
3. 增加真实模型多轮运行器，复用生产解析器并按路由、缺失字段、标题和最小变更进行确定性判分。
4. 统一创建/修改待补充流程的事件日志，覆盖准备、恢复、取消、替换、过期、任务失效和轮数上限。
5. 增加三轮修改任务的 Agent HTTP 回归，验证同线程收参、确认前零写入和批准后单次版本化修改。
6. 首次真实模型基线得到 `9/13`，据失败结果收紧创建解析的可选字段/模糊时间规则，以及修改解析的标题指令词剥离规则，并增加提示词回归测试。
7. 真实模型复测达到 `13/13`，随后补充 Vue 联调验收步骤，更新 README、版本号并执行完整质量门禁。

### Added

- 新增 `app.evaluation.multiturn` 数据契约、数据集加载器和结构化判分函数。
- 新增 6 组多轮评测案例，包含创建任务缺标题、模糊截止时间、后轮纠正，以及修改任务字段/新值收集、模糊时间和清空字段。
- 新增 `check_multiturn_model.py`。缺少 `LLM_API_KEY` 时在调用模型前退出；配置密钥后仅运行解析评测，不访问 Redis 或写任务。
- 新增统一 `pending_operation` 事件日志，使用固定事件名、原因和下一节点标识定位多轮流程中断位置。
- 新增 `/api/agent/chat` 与 `/api/agent/confirm` 端到端回归，复现界面中的三轮修改线路。

### Changed

- 创建解析器明确禁止把未提供的描述、分类、截止时间和预计耗时当作必补字段；“月底前后”“过几天”“尽快”等多义时间必须澄清，不得擅自选定日期。
- 修改解析器明确剥离“改成”“改为”“标题叫”等指令词，只把用户指定的内容写入新标题。
- 修改评测要求实际字段集合与期望字段集合完全一致，模型额外修改任何未请求字段都会失败。

### Security and Reliability

- 多轮评测比较结构化状态而非自然语言逐字一致，避免无意义的文案波动，同时保留最小补丁和后轮纠正约束。
- 待补充日志不记录用户消息、任务标题、描述或完整草稿，只输出受限流程元数据。
- HTTP 回归在每轮 chat 后读取真实仓储状态，证明确认前任务标题和版本均未变化，批准后才从版本 1 更新为版本 2。
- Vue Store 在页面会话内复用同一 `thread_id`，每次请求使用新 `request_id`；`needs_clarification` 不会被误当作待确认写操作。

### Tests

- 新增评测数据校验、创建/修改判分和日志隐私测试。
- 新增三轮修改任务 HTTP 闭环测试，并回归创建/修改澄清节点的既有分支。
- 定向测试结果：`21 passed`。
- 后端完整测试结果：`362 passed, 9 warnings`，包含真实 Redis 与 Redis Checkpoint 集成测试。
- 真实模型多轮评测结果：首次 `9/13`，收紧规则后复测 `13/13`。
- 前端 `npm run typecheck` 与 `npm run build` 通过；Vite 保留现有大于 500 kB 的 chunk 警告。

## [0.2.3] - 2026-08-11

> 多轮对话基础能力统一版本：依次完成短期任务焦点、创建任务跨轮参数收集和修改任务跨轮参数收集。

### 版本内实际开发总顺序

1. 建立短期 `ActiveTaskContext` 与受控单数指代，为后续多轮流程提供不依赖完整聊天历史的任务焦点。
2. 增加 `TaskDraftCandidate` 与 `PendingTaskDraftClarification`，完成创建任务缺失参数的跨轮收集。
3. 抽取 `PendingOperationContextBase`，增加 `PendingTaskUpdateClarification`，完成修改任务字段和新值的跨轮收集。

### 第一阶段：短期任务焦点与单数指代

1. **确定第一阶段上下文范围**
   - 只支持“它”“这个任务”“那个任务”“这项任务”“刚才的任务”等受控单数指代。
   - 只接入任务详情查询、状态更新、普通属性修改和任务拆解，不实现复数指代、批量更新、跨线程记忆和完整聊天历史。

2. **定义短期焦点契约**
   - 新增 `ActiveTaskContext`，只保存 `user_id`、`thread_id`、`task_id`、`created_at` 和 `expires_at`。
   - 新增 `ACTIVE_TASK_CONTEXT_TTL_SECONDS`，默认 1800 秒，通过 Settings 和 Graph 依赖注入。

3. **增加受控指代识别**
   - 新增独立任务指代识别函数，只在支持焦点的意图下处理受控单数指代。
   - 显式任务名称或 ID 始终优先，不会被旧焦点覆盖。

4. **接入焦点解析节点**
   - 新增 `resolve_context_reference`，校验焦点用户/线程归属和 TTL，并将有效 `task_id` 交给现有任务匹配/定位链路。
   - 焦点过期、归属不匹配或任务已删除时清理上下文，不猜测替代任务。

5. **统一每轮焦点更新**
   - 新增 `finalize_turn`，在唯一查询结果、任务创建、任务更新或候选选择完成后更新焦点。
   - 普通列表返回多个任务、零匹配或当前任务已删除时清理焦点，防止旧上下文误引用。

6. **改造 Graph 和服务恢复**
   - 扩展 Graph State、Builder 与条件路由，在普通意图分支中先判断是否需要恢复受控指代。
   - `TaskAgentService` 在每轮从 Checkpoint 恢复 `active_task_context`，且 Checkpoint 线程键继续包含编码后的 `user_id + thread_id`。
   - 任务查询完整性与任务引用判定进行相应调整，使“它”类输入进入焦点解析，而不被误当作普通缺失引用。

7. **同步文档和版本**
   - 在 README、意图识别快速入门和开发计划中记录焦点边界、TTL、Redis 重读原则和明确延期项。
   - 包版本更新为 `0.2.3`。

#### 安全与可靠性

- 焦点上下文只保存任务 ID 和归属/过期信息；任务事实始终从 Redis 重读。
- 后续写操作继续执行现有的归属、确认、版本和幂等校验。
- 复数指代、批量状态修改、上下文删除、跨线程记忆和完整聊天历史仍明确不在本阶段范围。

#### Tests

- 新增唯一焦点、显式覆盖、多结果清理、零结果、TTL、已删除任务、用户/线程隔离和未确认零写入测试。
- 新增使用真实 Redis Checkpoint 重建 Graph 后恢复 `ActiveTaskContext` 的集成测试。
- 后端完整测试结果：`335 passed`，真实 Redis 测试通过 IPv6 `[::1]` 执行。

### 第二阶段：创建任务跨轮参数收集

1. **冻结第一阶段范围**
   - 在 `DEVELOPMENT_PLAN.md` 中定义第二阶段范围：只补齐创建任务所需参数，不引入通用聊天历史、长期记忆或自然语言确认。
   - 明确标题缺失和模型明确标记的歧义字段才进入澄清，其他可选字段不被强制补齐。

2. **分离候选草稿和最终草稿**
   - 抽取 `TaskDraftFields`，保留创建任务的公共字段与评分。
   - 新增允许标题缺失的 `TaskDraftCandidate`，包含 `missing_fields` 和 `clarification_question`。
   - 保留标题必填的严格 `TaskDraft`，确保只有完整草稿才能进入确认和写入链路。

3. **调整结构化创建解析**
   - `StructuredOutputTaskParser` 改为输出 `TaskDraftCandidate`，标题缺失不再触发解析重试失败。
   - Prompt 明确禁止编造标题或其他事实，缺失标题时返回 `title=null`，并在 `missing_fields` 中声明。
   - Prompt 加入多轮标记输入的合并和较新明确修正覆盖规则。

4. **增加创建草稿待补充上下文**
   - 新增 `PendingTaskDraftClarification`，保存用户/线程归属、有限创建输入、当前候选草稿、缺失字段、澄清问题、轮次和 TTL。
   - 增加缺失字段确定、中文澄清问题格式化、多轮输入标记与取消/新请求判定函数。

5. **改造校验节点**
   - `validate_task` 先校验宽松候选草稿；存在缺失字段时返回澄清状态，不再将缺少标题当作系统错误。
   - 字段完整后再转换为严格 `TaskDraft` 和 `TaskCreate`，原有优先级计算、创建预览和 Human-in-the-loop 确认保持不变。

6. **接入 LangGraph 跨轮路由**
   - 新增 `prepare_task_draft_clarification` 和 `resolve_task_draft_clarification`，分别负责写入待补充状态和下一轮恢复。
   - 扩展 Graph State、Builder 和条件路由；待确认动作、删除选择和任务候选选择继续高于草稿补齐。
   - 后续普通补充直接回到 `parse_task`；取消、明确新请求、TTL 过期和轮数超限均会清理草稿上下文。

7. **接入 API 状态与配置**
   - `TaskAgentService` 在每轮恢复 `pending_task_draft_clarification`，对外返回 `needs_clarification` 和当前追问。
   - 新增 `TASK_DRAFT_CLARIFICATION_MAX_ROUNDS`，默认 4，合法范围 1—8；复用 `PENDING_CONTEXT_TTL_SECONDS` 作为操作级短期 TTL。
   - 同步 `.env.example`、README、意图识别快速入门和开发计划，作为 `0.2.3` 的第二阶段内容。

#### 安全与可靠性

- 补齐过程不调用任务写工具；只有候选草稿转换为严格草稿、通过确定性校验并获得 Human-in-the-loop 批准后才写 Redis。
- 待补充状态严格绑定 `user_id + thread_id`，且受有限输入数、TTL 和最大轮数限制。
- 本阶段不引入通用聊天历史、长期记忆、自然语言确认或全局 `Pending*` 迁移。

#### Tests

- 先调整结构化解析和 Graph 旧测试，将“缺少标题报错”改为“保存草稿并追问”。
- 新增一次/多次补充、后续改口、取消、新查询替换、TTL、轮数上限、用户/线程隔离、确认前零写入与确认后单次创建测试。
- 新增真实 Redis `PendingTaskDraftClarification` Checkpoint 重建 Graph 后恢复并继续创建的集成测试。
- 后端完整测试结果：`346 passed`，真实 Redis 测试通过 IPv6 `[::1]` 执行。

### 第三阶段：通用待补充外层与修改任务跨轮参数收集

1. **确认修改链路断点**
   - 复现了“修改接水任务 → 标题”后第二轮被重新归类为普通对话的问题。
   - 确认原因是 `TaskUpdateParseResult` 只返回澄清问题，没有把已定位任务和本次修改状态写入 Checkpoint。
   - 在 `DEVELOPMENT_PLAN.md` 固化第三阶段范围：只实现单任务普通属性修改的跨轮收集，不扩展可修改字段和高风险操作。

2. **抽取通用待补充外层**
   - 新增 `PendingOperationContextBase`，统一 `user_id`、`thread_id`、有限 `user_inputs`、`clarification_round`、`created_at` 和 `expires_at`。
   - 将已有 `PendingTaskDraftClarification` 调整为继承该外层，保持创建任务的 Checkpoint 字段格式和业务行为不变。
   - 新增通用的有限输入组合、取消识别和明确新请求判定函数，创建和修改使用各自的操作语义。

3. **定义修改任务专用状态**
   - 新增 `PendingTaskUpdateClarification`，在通用外层上保存 `task_id`、`expected_version` 和已确定的 `partial_result`。
   - 扩展 `TaskAgentState` 与 `TaskAgentService` 恢复逻辑，增加 `pending_task_update_clarification`、`task_update_inputs` 和修改澄清轮次。
   - Agent API 在存在待补充修改时继续返回 `needs_clarification`，不再退化为普通对话。

4. **让修改解析器支持多轮输入**
   - `parse_task_update` 改为组合本次修改的所有受限输入，并在每轮重新生成最小结构化补丁。
   - 修改解析 Prompt 增加“各标记轮次属于同一次修改”与“较新明确值覆盖较早冲突值”规则。
   - 保留已确定且互不依赖的变更；字段、新值或时间仍不明确时继续澄清。

5. **接入 LangGraph 准备与恢复节点**
   - 新增 `prepare_task_update_clarification`，保存目标 ID、期望版本、已解析结果、输入、问题、轮次和 TTL。
   - 新增 `resolve_task_update_clarification`，处理取消、明确新请求替换、过期、任务失效和版本冲突。
   - 补充文本被识别为当前修改的续输入时，直接回到 `parse_task_update`，不再重新执行普通意图识别。

6. **补全路由优先级与结束条件**
   - 在 `route_pending_state` 中把待确认动作和候选任务选择继续作为更高优先级，其后才恢复修改参数收集。
   - 修改解析结果仍需澄清时进入准备节点；完整时进入原有 `prepare_task_update` 和 Interrupt/Resume 确认链路。
   - 达到最大轮数、用户取消或上下文失效后清理待补充状态，不留下可被误恢复的旧补丁。

7. **接入配置、版本和文档**
   - 新增 `TASK_UPDATE_CLARIFICATION_MAX_ROUNDS`，默认 4，合法范围为 1—8。
   - 配置经 `Settings` 注入 `GraphDependencies`，同步 `.env.example`、README、意图识别快速入门和开发计划，最终统一发布为 `0.2.3`。

#### 安全与可靠性

- Checkpoint 只保存目标任务 ID、期望版本和最小修改结果，不把旧任务属性当作真实状态。
- 每次恢复都按 `user_id + task_id` 从 Redis 重读任务并检查 `expected_version`；任务被删除或版本变化时立即停止旧流程。
- 参数收集和修改预览阶段零写入；批准后仍执行归属、版本、状态、确认和幂等校验。

#### Tests

- 先使用内存 Checkpoint 复现并验收“修改接水任务 → 标题 → 改成每天早上接水 → 确认”完整链路。
- 新增取消、新查询替换、TTL、轮数上限、版本冲突、用户/线程隔离和确认前零写入测试。
- 新增真实 Redis `PendingTaskUpdateClarification` Checkpoint 重建 Graph 后恢复、进入确认并完成写入的集成测试。
- 后端完整测试结果：`354 passed`，真实 Redis 测试通过 IPv6 `[::1]` 执行。

## [0.2.2] - 2026-08-11

> 自然语言批量删除、父子范围删除与已取消任务恢复。

### Added

- 新增独立结构化删除解析器，将自然语言转换为时间范围、状态、优先级、分类、多个任务引用和关键词等受控查询参数。
- 新增删除计划预览与原子批量删除，覆盖所有已取消任务、任意明确日期范围、多个指定任务和“有关论文”等包含匹配，单批安全上限为 50 条。
- 新增 `CANCELLED` 恢复门禁：修改、更新状态或拆解已取消任务前先确认恢复为 `TODO`，恢复成功后自动继续原意图并进入第二次写操作确认。
- 新增前端批量删除清单与已取消任务恢复确认卡。
- 新增父任务直接子任务删除范围，支持删除指定父任务下的单个或全部直接子任务，并隔离其他父任务下的同名子任务。
- 新增多目标逐项解析：任一引用缺失时整批停止，同名多候选通过可持久化上下文逐项选择后再生成删除预览。

- 新增 `DELETE_TASK` 对话式任务删除流程，支持真实任务唯一定位、候选消歧、Interrupt/Resume 确认、拒绝和确认后物理删除。
- 新增 `TaskDelete`、`TaskDeleteResult`、Repository `delete` 与 Tool `delete_task` 契约。
- 新增 `prepare_task_delete` 和 `execute_task_delete` LangGraph 节点，以及 API 响应中的 `deleted_task_id`。
- 新增前端永久删除危险确认卡和删除成功后的本地任务列表同步。
- 开放 `DECOMPOSE_TASK` 对话式任务拆解流程。用户可以通过自然语言指定已有父任务，系统在唯一定位或候选消歧后进入拆解流程。
- 新增独立的结构化子任务规划器，生成 3—8 个候选直接子任务，并支持方案说明、标题、描述、执行顺序、预计耗时、截止时间、前置依赖和完成权重。
- 新增确定性拆解方案校验，覆盖步骤标识和标题唯一性、连续顺序、依赖引用、循环依赖、父任务截止时间、预计总耗时及已有子任务重复检查。
- 新增 `generate_subtask_plan`、`validate_subtask_plan`、`prepare_subtask_confirmation` 和 `execute_create_subtasks_batch` LangGraph 节点。
- 新增拆解方案 Human-in-the-loop 闭环，支持确认、编辑完整方案、携带反馈重新生成和取消；编辑或重新生成后必须产生新的待确认动作。
- 新增 `SubtaskDraft`、`SubtaskPlan`、`SubtaskBatchCreate`、`SubtaskBatchResult` 和父子状态联动结果等 Pydantic 契约。
- 新增 Repository 与 Tool 层的 `create_subtasks_batch` 和 `list_children` 能力。
- 新增 Redis 父任务子节点有序索引，子任务按 `subtask_order` 保存和读取，并通过 `parent_id` 直接挂载到原任务。
- 新增子任务状态对父任务的确定性联动：按有效子任务数量计算进度，`CANCELLED` 子任务不计入有效总数；全部有效子任务完成时父任务自动完成，已完成子任务重新打开时父任务自动恢复为进行中。
- 新增前端任务拆解确认卡，展示父任务、完整子任务方案、预计耗时、依赖和截止时间，并支持编辑、重新生成、取消和确认。
- 新增前端父子层级任务列表。子任务不再作为顶层任务独立展示；点击父任务可展开或收起直接子任务，并显示完成数量和父任务进度。
- 新增对话式父子聚合查询。普通列表只逐项展示顶层任务，父任务以“父任务（含 N 个子任务）”汇总；只有明确询问某个父任务的子任务数量、列表或具体步骤时，才读取并返回真实子任务列表。
- 新增子任务查询语义 `include_subtasks`，支持父任务缺失时澄清、父任务重名时候选消歧，以及选择候选后继续原始子任务查询。

### Changed

- 删除与 `CANCELLED` 状态更新严格分离；删除确认只允许确认或拒绝，不允许编辑或重新生成。
- `PendingTaskSelection`、Graph 路由和确定性引用校验扩展到删除任务，选择候选后重新读取 Redis 并校验版本。
- 扩展任务实体，增加 `subtask_order`、`depends_on_task_ids`、`completion_weight` 和 `creation_source` 字段，并保留现有 `parent_id` 作为直接父任务归属。
- 扩展 Agent State 与 API 响应，支持拆解草稿、校验后方案、已有子任务、已创建子任务和联动后的父任务。
- 意图识别 Prompt 增加任务拆解、普通任务查询和显式子任务查询之间的边界规则，不允许普通列表默认展开全部子任务。
- `PendingTaskSelection` 支持保存拆解原始消息和子任务查询语义，候选选择后不会把“第一个”等选择文本错误地当作拆解或查询指令。
- 任务状态更新改为优先使用带父任务汇总的事务接口；普通无父任务更新保持原有状态流转行为。
- 前端任务合并逻辑同时处理父任务、单任务和批量创建的子任务，避免确认完成后丢失联动后的父任务状态。
- README、项目任务书、开发计划和意图识别快速入门文档已同步 P1a 范围及当前实现状态。

### Security and Reliability

- LLM 只产出删除查询参数；真实任务筛选、约束校验、版本检查和删除全部由确定性后端完成。
- 批量删除任务、索引、所有受影响父任务和幂等结果在单个 Redis 事务中全有或全无地提交，任何目标失效都会阻止整批写入。
- 显式任务引用不再退化为包含匹配；只接受任务 ID、精确标题或规范化标题，防止“`不存在任务`”误命中“`存在任务`”。

- 第一阶段只允许删除叶子任务；存在直接子任务或仍被兄弟任务依赖的任务拒绝删除，不执行隐式级联。
- 任务对象、用户任务索引、父任务子节点索引、父任务汇总和删除幂等结果在同一 Redis `WATCH/MULTI/EXEC` 事务中更新。
- 删除使用 `expected_version`、`user_id` 隔离和输入绑定的幂等记录；重放不会重复递增父任务版本，幂等键携带不同输入时拒绝执行。
- AI 仅生成候选拆解内容；`user_id`、`parent_id`、初始状态、版本、创建来源和审计时间由后端确定性注入，禁止模型覆盖受控字段。
- 批量创建前重新校验父任务归属、版本和状态；已取消父任务、跨用户父任务和版本冲突均拒绝写入。
- 全部子任务、用户任务索引、父任务子节点索引、父任务版本和批次幂等结果在单个 Redis `WATCH/MULTI/EXEC` 事务中全有或全无地写入。
- 批次幂等键与方案指纹绑定：相同键和相同方案返回原批次结果，相同键携带不同方案时拒绝执行。
- 子任务状态变更与父任务进度、状态、完成时间和版本更新处于同一个 Redis 事务，不产生部分联动结果，也不重复请求用户确认。
- 具有有效子任务的父任务不能在子任务未全部完成时被直接标记为完成，避免父子状态不一致。
- 所有父任务、子任务和候选查询继续执行 `user_id` 隔离，查询结果只来自 Redis 真实状态，不依赖模型记忆。

### Tests

- 新增删除意图边界、未确认零写入、拒绝、候选消歧、叶子删除、父任务与依赖阻塞、索引清理、父任务联动、幂等、版本冲突、用户隔离和 Checkpoint 恢复测试；真实 Redis/Checkpoint 验证使用 IPv6 `[::1]`。
- 新增拆解方案 Schema、结构化规划器、确定性校验、Graph 路由、Interrupt/Resume、编辑、重新生成、拒绝和候选选择测试。
- 新增 Redis 原子批量创建、事务回滚、幂等重放、幂等冲突、父任务版本冲突、用户隔离和子节点有序索引测试。
- 新增父任务进度计算、最后一个子任务完成时父任务自动完成、子任务重新打开时父任务恢复、并发状态更新和新增子任务重开父任务测试。
- 新增对话列表父子聚合、显式子任务查询、缺失父任务澄清及重名父任务选择后恢复查询语义测试。
- 新增前端拆解确认卡和父子任务列表的 TypeScript 契约，并完成真实页面展开/收起交互验收。
- 后端完整测试结果：`316 passed`，包括通过 IPv6 `[::1]` 执行的真实 Redis 批量删除、逐项消歧 Checkpoint 恢复和恢复双确认测试。
- 前端 `npm run typecheck` 与 `npm run build` 均通过；生产构建仍存在单个主 JavaScript chunk 超过 500 kB 的 Vite 警告。

### 未完成内容

- P1a 当前只支持一个父任务下的直接子任务，不支持多层任务树、跨父任务依赖、子任务再次拆解或已有执行计划覆盖。
- 尚未实现下一步任务推荐、SSE 流式响应、完整工具执行日志和基础 Trace。
- 尚未实现 Milvus、Embedding、长期记忆、历史拆解方案检索、Reranker 和 Dense/Sparse 混合检索。
- 尚未实现每日简报、动态重新规划、周期复盘和完整自动化评测平台。
- 尚未建设复杂任务看板、每日简报页、执行轨迹页、统计图表、复杂筛选、主题系统和移动端适配；当前前端仅提供基础对话、确认卡和直接父子任务列表。
- 任务属性修改的跨轮字段补全仍未接入 Checkpoint；解析器要求澄清时，用户仍需重新发送完整修改请求。
- 普通属性修改仍不支持 `actual_minutes`、手动 `progress`、父子关系、依赖关系和子任务顺序调整。
- 部分非法状态流转仍可能暴露英文内部异常，尚未全部统一为面向用户的中文错误文案。
- 拆解与子任务查询 Prompt 已覆盖结构化、Fake 和端到端测试，但尚未建立真实模型的版本化拆解评测数据集和持续回归基线。
- 多 Agent、MCP Server、邮件/日历自动操作、语音、多人协作、移动 App、复杂权限、复杂 RAG/甘特图和高风险外部操作仍明确不在当前范围。

## [0.1.4] - 2026-08-10

### Added

- 开放 `UPDATE_TASK` 对话式任务属性修改流程，支持标题、描述、分类、截止时间、预计耗时和用户优先级。
- 新增独立的任务属性结构化解析器，结合 Redis 当前任务、业务时区和当前时间生成最小字段操作列表。
- 新增 `SET`、`CLEAR` 字段操作契约，区分“未提及字段”和“主动清空字段”，支持取消截止时间及恢复 AI 推荐优先级。
- 新增 `parse_task_update`、`prepare_task_update` 和 `execute_task_update` LangGraph 节点。
- 新增属性修改前后值预览、Human-in-the-loop 确认和前端专用确认卡。
- 新增多候选任务属性修改恢复，选择候选后继续使用第一轮原始修改指令。
- 新增普通属性更新 Repository 与 Tool 接口。

### Changed

- 意图识别 Prompt 增加 `UPDATE_TASK` 与查询、取消任务、状态修改之间的边界规则。
- `PendingTaskSelection` 支持任务属性修改操作并保存原始修改消息。
- Redis 属性写入使用 `WATCH/MULTI/EXEC`、`expected_version` 和 `update_task:{request_id}` 幂等键。
- 用户修改优先级时只写入 `user_priority`，由任务实体重新计算 `effective_priority` 和 `priority_source`。
- 真实 Redis 与 Checkpoint 集成测试默认改用 IPv6 回环地址 `[::1]`；普通任务数据使用 DB 15，Checkpointer 使用 DB 0。
- 前端属性修改确认卡只提供确认和取消，不允许绕过专用解析流程进行编辑或重新生成。

### Fixed

- 修复同名任务选择后，属性解析器错误地把“第一个”等候选选择消息当作修改指令的问题。
- 修复清空任务描述时写入 `null` 与任务实体字符串约束冲突的问题，统一转换为空字符串。
- 修复点击发送后聊天输入框不清空的问题；提交顺序调整为先清空本地输入值，再触发异步发送。
- 修复属性修改待确认动作在前端被错误显示为“确认创建任务”的问题。

### Security

- 属性修改仅允许 `title`、`description`、`category`、`deadline`、`estimated_minutes` 和 `user_priority` 白名单字段。
- 禁止通过属性修改流程写入任务状态、归属、AI 优先级、有效优先级、紧急度、进度、版本和审计时间字段。
- 候选选择后按 `user_id + task_id` 重新读取 Redis，并在确认写入时再次执行归属、版本和幂等校验。
- 未确认、解析歧义、版本冲突或幂等输入不一致时不执行任务写入。

### Tests

- 新增字段操作 Schema、字段清空、属性修改确认、Redis 幂等更新、解析澄清和多候选原始消息恢复测试。
- 后端完整测试结果：`248 passed`，包括基于 IPv6 Redis 的 6 项真实 Redis/Checkpoint 集成测试。
- 前端 `npm run typecheck` 与 `npm run build` 均通过。

### 未完成内容

- 属性修改解析器能够返回澄清问题，但尚未像查询澄清一样把属性补丁与缺失字段保存到 Checkpoint；用户需要重新发送包含完整修改信息的请求。
- `CANCELLED` 当前仍是不可恢复的终止状态，尚未实现“重新启用已取消任务”的二次确认流程。
- 非法状态流转仍可能向前端暴露英文内部异常，尚未统一转换为面向用户的中文提示。
- 普通属性修改暂不支持 `actual_minutes`、`progress`、父子关系和依赖关系；任务状态继续由独立的 `UPDATE_TASK_STATUS` 流程处理。
- 属性解析 Prompt 已通过 Fake/结构化数据测试，但尚未增加真实模型的版本化回归数据集和自动评测。
- 任务拆解、批量子任务、下一步推荐、Milvus 长期记忆、每日简报和动态重新规划仍未实现。

## [0.1.3] - 2026-08-04

### Fixed

- 修复“最近/近 N 天”被模型错误解释为过去时间的问题，后端现在按业务时区确定性归一化为从今天开始、包含今天的 N 个自然日。
- 修复任务草稿编辑时需要手动输入 ISO 8601 截止时间和时区的问题，改为北京时间日期选择器与时间选择器，并在提交时自动转换为带 `+08:00` 的 aware datetime。
- 修复用户修改优先级后确认卡仍显示 AI 建议值、二次编辑无法正确回填以及任务列表不展示最终优先级的问题。

### Changed

- 任务截止时间统一按 `Asia/Shanghai` 展示；已有截止时间自动转换为北京时间，无截止时间时编辑表单默认使用当前北京时间。
- 截止时间编辑增加日期、时间必填及不得早于当前时间的前端校验。
- 任务列表增加最终 `effective_priority` 标签，区分任务优先级和任务状态。

### Tests

- 新增“最近五天”“近5天”未来自然日范围及“过去五天”不被改写的回归测试。
- 后端非 Redis 集成测试结果：`235 passed`。
- 前端 `npm run typecheck` 与 `npm run build` 均通过。

## [0.1.2] - 2026-08-03

### Added

- 新增查询条件跨轮澄清闭环，支持补充缺失的时间范围、状态等查询条件。
- 新增任务候选项选择机制，支持通过序号、候选 ID、完整标题和标准化标题选择任务。
- 新增 `PendingQueryClarification`、`PendingTaskSelection` 和 `TaskQueryIntentPatch` 数据契约。
- 新增待处理上下文过期机制，可通过 `PENDING_CONTEXT_TTL_SECONDS` 配置有效期。
- 新增确定性中文任务响应层，统一列表、详情、空结果、多候选、澄清、取消、失效和状态更新响应。
- 新增阶段三查询澄清、候选选择、Checkpoint 恢复和端到端测试。

### Changed

- 调整 LangGraph 路由，待处理状态按以下优先级恢复：
  1. 待确认写操作；
  2. 待选择任务；
  3. 待补充查询条件；
  4. 普通意图识别。
- 查询条件补充后重新执行阶段一确定性完整性校验，不直接信任 LLM 输出。
- 候选任务选中后重新从 Redis 读取任务，并校验用户归属、任务版本和当前状态。
- 查询类候选选择保持只读；状态更新类候选选择完成后仍必须进入 Human-in-the-loop 确认流程。
- 用户输入新请求或取消指令时，可终止或替换未完成的澄清上下文。
- 将关键词标准化能力公开为 `normalize_task_reference`，供确定性候选选择复用。
- 统一任务状态、优先级及操作结果的中文展示文案。
- 更新 README、开发计划、v0.1.2 设计文档、环境变量示例及阶段说明。

### Security

- 候选任务选择严格使用 `user_id + task_id` 重新读取，防止跨用户访问。
- 任务被删除、版本变化、状态变化或上下文过期时采用 fail-closed 策略。
- 所有任务写操作继续经过归属校验、状态校验及 Human-in-the-loop 确认，不允许候选选择绕过确认流程。

### Compatibility

- 保持阶段一固定时间范围及 `CUSTOM` 时间区间契约不变。
- 保持 `ALL`、`UNSPECIFIED` 和 `OVERDUE` 的既有语义。
- 保持阶段二 Redis 查询计划、任务匹配器及查询执行流程不变。
- 保持查询条件存放于 `query`，状态更新目标存放于 `target_status`。
- 保持普通查询只读，不引入 Redis 查询逻辑之外的新数据源。

### Tests

- 新增查询条件澄清测试。
- 新增候选任务选择及失效保护测试。
- 新增确定性中文响应测试。
- 新增阶段三查询交互端到端测试。
- 新增查询上下文 Redis Checkpoint 恢复测试。
- 完整测试结果：`238 passed`。

## [0.1.1] - 2026-08-02

### Added

- 增加可插拔意图识别模块。
- 增加 LLMIntentClassifier 和 FakeIntentClassifier。
- 增加 qwen-flash 结构化输出支持。
- 增加意图评测数据集和真实模型验证脚本。
- 增加意图识别代码快速入门文档。

### Changed

- LangGraph 使用 IntentRecognitionService 替换关键词分类器。
- 查询、创建、状态更新、澄清和普通对话按 IntentResult 路由。
- 模型客户端通过统一工厂创建。

### Known Limitations

- 查询节点尚未充分使用 IntentResult.task_reference。
- GENERAL_CHAT 当前只返回固定能力提示。
- UPDATE_TASK 和 DECOMPOSE_TASK 业务功能尚未开放。
