# Changelog

本项目的重要变更将记录在此文件中。

## [Unreleased]

### Added

- 创建初始项目目录结构。
- 添加项目任务书、开发计划、协作说明和 README。
- 添加 Docker Compose、环境变量示例及空目录跟踪文件。
- 完成 v0.1.2 查询意图、通用时间区间和确定性完整性校验。
- 完成 TaskQueryPlan、Redis 组合过滤和 KeywordTaskMatcher。
- 增加跨轮查询补全与多候选选择的 Redis Checkpoint 恢复。
- 增加候选任务按用户重新读取、版本和状态重校验。
- 增加任务列表、详情、零匹配和多候选的确定性中文响应。

### Changed

- Graph 新消息路由按 PendingAction、候选选择、查询澄清和普通意图识别排序。

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
