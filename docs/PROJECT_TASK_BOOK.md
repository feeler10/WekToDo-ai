# 基于 LangGraph 的 AI 任务规划与执行助手——项目启动任务书

## 1. 项目基本信息

### 1.1 项目名称

**基于 LangGraph 的 AI 任务规划与执行助手**

英文名称：

**LangGraph-Based AI Task Planning and Execution Assistant**

### 1.2 项目性质

个人 AI 应用研发项目 / 智能任务管理系统 / Agent 工程实践项目

### 1.3 项目定位

本项目旨在构建一个以 **LangGraph 状态化 AI Agent** 为核心的个人任务规划与执行助手。

系统不以传统待办软件中的表单填写、任务列表和 CRUD 操作为主要交互方式，而是以自然语言对话作为核心入口。用户可以直接描述目标、时间要求、任务背景和当前进度，由 AI 助手完成任务理解、结构化分析、优先级判断、步骤拆解、进度跟踪和动态调整。

系统中的任务列表、任务树、进度面板和每日简报主要用于展示 Agent 的执行结果，并为用户提供必要的手动修正能力，而不是替代 Agent 成为系统的主要操作入口。

---

## 2. 项目背景

传统待办系统通常要求用户手动填写：

- 任务名称；
- 任务描述；
- 截止时间；
- 优先级；
- 分类；
- 执行步骤；
- 完成状态。

这类系统可以保存任务，却无法真正理解用户想要完成的目标，也无法根据任务内容、剩余时间、工作量和依赖关系主动帮助用户规划。

例如，用户输入：

> 下周五之前完成论文实验部分修改，需要重新跑实验、更新表格、修改实验分析，这件事比较重要。

传统待办系统通常仍然需要用户分别填写标题、截止时间、优先级和具体步骤。

本项目中的 AI 助手应能够自动完成：

1. 判断用户是在创建任务；
2. 提取任务标题、描述和截止时间；
3. 识别任务的重要性和潜在影响；
4. 结合时间规则计算紧急程度；
5. 估算任务工作量；
6. 生成结构化任务草稿；
7. 在用户确认后保存任务；
8. 根据需要将复杂任务拆解为可执行步骤；
9. 在后续对话中查询、更新和重新规划任务。

---

## 3. 项目愿景

构建一个能够长期协助个人进行目标管理、任务规划和执行推进的 AI 助手。

它不仅记录“需要做什么”，还应逐步具备以下能力：

- 理解用户真正想完成的目标；
- 将模糊目标转化为清晰任务；
- 识别任务的重要性和紧迫性；
- 将复杂任务拆解为可执行步骤；
- 根据用户可用时间推荐下一步行动；
- 根据任务进度动态调整计划；
- 记住用户稳定的规划偏好；
- 从历史任务中复用有效经验；
- 在关键操作前让用户确认；
- 通过持续反馈逐步提高规划质量。

项目最终应形成一个可持续迭代的个人 AI 执行系统，而不仅是一个接入大模型的待办列表。

---

## 4. 项目建设目标

### 4.1 总体目标

构建一个以 LangGraph 为流程控制核心的状态化 AI 任务助手，使用户能够主要通过自然语言完成：

- 任务创建；
- 任务拆解；
- 任务查询；
- 状态更新；
- 优先级调整；
- 进度跟踪；
- 每日规划；
- 下一步推荐；
- 动态重新规划；
- 历史经验复用。

系统应形成完整的 Agent 工作闭环：

```text
自然语言输入
    ↓
意图识别
    ↓
上下文加载
    ↓
真实任务数据查询
    ↓
任务分析或规划
    ↓
用户确认
    ↓
工具执行
    ↓
状态持久化
    ↓
结果反馈
    ↓
历史经验沉淀
```

### 4.2 产品目标

系统需要解决以下实际问题：

1. 减少创建和整理任务时的手动输入；
2. 帮助用户将模糊目标转化为可执行任务；
3. 避免只记录任务但不知道下一步做什么；
4. 根据截止时间和任务影响合理安排优先级；
5. 在任务执行过程中持续维护真实进度；
6. 当时间、进度或目标变化时重新规划；
7. 让历史任务经验能够被后续任务复用；
8. 保证关键写操作始终由用户最终决定。

### 4.3 技术建设目标

项目需要建立以下完整能力：

- LangGraph 状态图设计；
- Agent State 管理；
- 条件路由；
- Tool Calling；
- Human-in-the-loop；
- Interrupt 与 Resume；
- Checkpoint 状态持久化；
- 结构化输出；
- 任务数据精确查询；
- 短期上下文管理；
- 长期语义记忆；
- 向量检索与 Metadata Filter；
- 幂等控制与重复调用防护；
- 服务化 API；
- 流式响应；
- 可观测性；
- 自动化评测；
- 容器化部署。

### 4.4 第一版目标

第一版重点完成最小可用 Agent 闭环：

```text
用户自然语言输入
→ Agent 判断意图
→ 解析任务
→ 计算优先级
→ 生成待确认草稿
→ 用户确认
→ 保存任务
→ 对话查询任务
→ 更新任务状态
→ 查询当前进度
```

第一版不追求复杂界面和大量扩展功能，优先保证核心流程真实可用、可恢复、可追踪。

---

## 5. 项目边界

### 5.1 项目核心

本项目的核心是：

- 状态化 Agent；
- 自然语言任务理解；
- 任务规划；
- 工具调用；
- 用户确认；
- 状态持久化；
- 任务进度维护；
- 长期经验复用。

### 5.2 辅助模块

以下模块服务于 Agent，但不是第一阶段重点：

- 任务列表；
- 看板页面；
- 日历视图；
- 数据统计；
- 任务筛选；
- 复杂后台管理；
- 多主题界面；
- 移动端适配。

### 5.3 系统不应退化为

- 只增加聊天框的传统待办系统；
- 由大模型直接生成但不保存真实状态的对话工具；
- 只做任务拆解、无法跟踪执行进度的演示项目；
- 依赖模型记忆回答任务状态的非可靠系统；
- 所有操作都由模型自动执行、缺少确认机制的黑盒 Agent。

---

## 6. 项目建设原则

### 6.1 Agent 优先

优先完成 LangGraph 工作流、状态持久化、工具调用和确认恢复机制，再逐步完善界面。

### 6.2 真实数据优先

涉及任务状态、截止时间、完成进度和优先级时，必须查询真实存储数据，不允许依赖模型上下文猜测。

### 6.3 AI 建议，用户决策

AI 可以分析、建议和规划，但关键写操作由用户最终确认。

需要确认的操作包括：

- 创建任务；
- 批量创建子任务；
- 修改截止时间；
- 修改最终优先级；
- 删除任务；
- 批量更新任务；
- 调整子任务顺序；
- 重新规划任务；
- 覆盖已有执行计划。

任务拆解方案及批量创建子任务仍然属于需要确认的写操作。用户确认创建子任务后，子任务状态变化引起的父任务进度和完成状态更新属于确定性领域规则，不是新的 AI 决策，因此不重复请求确认。

### 6.4 结构化数据与语义记忆分离

精确业务数据和语义经验采用不同存储方式。

结构化任务数据包括：

- 标题；
- 描述；
- 截止时间；
- 状态；
- 优先级；
- 父子关系；
- 完成进度；
- 依赖关系。

语义记忆包括：

- 历史任务经验；
- 用户稳定偏好；
- 已采纳的拆解模板；
- 失败原因；
- 执行反馈。

### 6.5 规则与大模型结合

大模型负责语义理解，程序负责确定性计算。

例如：

- LLM 判断语义重要性；
- 程序计算距离截止时间；
- 程序检查预计工作量是否超过剩余时间；
- 程序判断任务是否逾期；
- 程序计算父任务进度；
- 用户决定最终优先级。

### 6.6 所有工具调用可追踪

每次工具调用至少记录：

- 用户 ID；
- 线程 ID；
- Trace ID；
- Tool Call ID；
- 工具名称；
- 输入参数；
- 执行结果；
- 执行耗时；
- 是否成功；
- 是否经过确认；
- 幂等键；
- 错误信息。

### 6.7 渐进式开发

每个阶段必须形成完整可运行闭环，避免同时开发过多功能，导致系统模块很多但主流程无法运行。

---

## 7. 核心用户场景

### 7.1 创建任务

用户输入：

> 下周五前完成论文实验修改，需要重新跑实验、更新表格和修改结果分析。

系统输出任务草稿，并等待用户确认。

### 7.2 拆解任务

用户输入：

> 帮我把论文实验修改拆成具体步骤。

系统查询原任务和相似历史经验，生成子任务方案，并等待确认。

### 7.3 查询任务

用户输入：

> 我今天还有什么没做？

系统查询真实任务数据并返回今日未完成任务。

### 7.4 更新状态

用户输入：

> 重新跑实验已经完成了。

系统识别对应任务，生成状态更新确认，并在确认后更新。

### 7.5 推荐下一步

用户输入：

> 我今天只剩两个小时，应该先做什么？

系统结合优先级、截止时间、预计耗时、依赖关系和当前进度，返回可执行建议。

### 7.6 动态重新规划

用户输入：

> 今天临时有事，只能再工作一个小时，重新帮我安排。

系统根据最新可用时间调整计划，但不直接覆盖原计划，必须经过确认。

---

## 8. 第一版核心功能

### 8.1 对话式任务创建

用户可以通过自然语言创建任务。

Agent 应提取：

- 任务标题；
- 任务描述；
- 截止时间；
- 任务分类；
- 预计耗时；
- 语义重要程度；
- 影响程度；
- 建议优先级；
- 判断理由；
- 信息完整度。

结构化输出示例：

```json
{
  "title": "完成论文实验部分修改",
  "description": "重新运行实验、更新实验表格并修改结果分析",
  "deadline": "2026-08-07T23:59:59+08:00",
  "category": "paper",
  "estimated_minutes": 480,
  "semantic_importance": 85,
  "impact_score": 80,
  "ai_priority": "HIGH",
  "priority_reason": "任务具有明确截止时间，并会影响论文整体修改进度",
  "missing_fields": []
}
```

模型生成的结构化结果不能直接写入任务存储，必须先进入确认节点。

---

### 8.2 时间表达解析

系统需要识别常见自然语言时间表达，例如：

- 今天；
- 明天；
- 后天；
- 本周五；
- 下周一；
- 这周末；
- 月底之前；
- 三天之内；
- 两小时后；
- 下个月第一周。

处理要求：

1. 所有相对时间必须根据用户时区解析；
2. 保存时统一转为标准时间格式；
3. 展示时转回用户本地时间；
4. 表达存在歧义时，不直接写入；
5. 对“月底前”“尽快”等模糊表达生成解释和确认。

---

### 8.3 任务紧急程度判断

紧急程度采用大模型语义分析与后端规则计算相结合的方式。

#### LLM 负责分析

- 用户语义中的紧急表达；
- 任务的重要性；
- 不完成任务的影响；
- 是否会阻塞后续任务；
- 工作量大小；
- 任务场景；
- 用户明确表达的重要程度。

#### 后端负责计算

- 是否已经逾期；
- 距离截止时间还有多久；
- 剩余工作时间；
- 预计工作量是否超过剩余时间；
- 是否存在前置依赖；
- 是否阻塞其他任务；
- 用户是否手动标记重要。

建议计算模型：

```text
urgency_score
=
deadline_score × 0.40
+ semantic_importance × 0.25
+ impact_score × 0.20
+ workload_risk_score × 0.10
+ dependency_score × 0.05
```

优先级映射：

| 分数范围 | 优先级 |
|---|---|
| 80—100 | URGENT |
| 60—79 | HIGH |
| 30—59 | MEDIUM |
| 0—29 | LOW |

系统需要分别保存：

- `ai_priority`
- `user_priority`
- `effective_priority`
- `priority_source`
- `urgency_score`
- `priority_reason`

其中：

```text
effective_priority =
用户手动设置优先级
或
AI 计算优先级
```

---

### 8.4 Human-in-the-loop 确认

Agent 在准备执行关键写操作时，通过 LangGraph Interrupt 暂停。

用户可以选择：

- 确认；
- 编辑后确认；
- 重新生成；
- 取消。

示例：

```text
任务：完成论文实验部分修改
截止时间：2026-08-07 23:59
AI 建议优先级：HIGH
预计耗时：8 小时
判断原因：截止时间明确，且会影响后续论文修改

可执行操作：
[确认创建] [编辑后创建] [重新生成] [取消]
```

确认信息必须保存到 Checkpoint，Graph 恢复后继续执行，不应重新开始整个流程。

---

### 8.5 AI 任务拆解

用户可以要求 Agent 将复杂任务拆解为多个可执行步骤。

拆解产生的任务必须作为原任务的直接子任务保存，每个子任务都必须携带原任务的 `parent_id`，不得以无归属的普通任务形式写入。AI 只生成候选拆解方案，`user_id`、`parent_id`、初始状态和创建来源等受控字段由后端确定性注入。

标准流程：

1. 查询原任务；
2. 获取任务上下文；
3. 检索相似历史任务；
4. 读取用户拆解偏好；
5. 生成 3—8 个可执行子任务；
6. 检查步骤是否重复；
7. 检查顺序和依赖；
8. 检查预计耗时；
9. 等待用户确认；
10. 校验父任务归属、版本和当前状态；
11. 使用同一个 Redis 事务原子批量保存全部子任务、父子索引和批次幂等结果；
12. 初始化或重新计算父任务进度。

批量创建必须满足全有或全无语义，不得通过循环调用单任务创建工具产生部分成功。相同幂等键和相同方案重复执行时返回原批次结果；相同幂等键携带不同方案时拒绝执行。

子任务示例：

```text
1. 整理当前实验结果
2. 确认需要补充的实验组
3. 配置并重新运行实验
4. 汇总实验指标
5. 更新论文表格和图片
6. 修改实验结果分析
7. 检查正文与附录数据一致性
```

每个子任务应包含：

- 标题；
- 描述；
- 执行顺序；
- 预计耗时；
- 前置依赖；
- 截止时间；
- 当前状态；
- 是否由 AI 生成；
- 创建来源；
- 完成权重。

---

### 8.6 对话式任务查询

系统需要支持：

- 今天还有什么任务；
- 哪些任务已经逾期；
- 当前有哪些高优先级任务；
- 某个任务完成到哪一步；
- 某类任务还有哪些没完成；
- 最近完成了哪些任务；
- 哪些任务长时间没有更新；
- 哪些任务正在阻塞其他任务。

普通列表查询只在对话中逐项展示顶层任务。若顶层任务拥有直接子任务，则以“父任务（含 N 个子任务）”汇总展示，不将这些子任务重复展开为同级列表项。只有用户明确询问某个父任务的子任务数量、子任务列表或具体步骤时，系统才从真实存储读取该父任务的直接子任务，并返回数量及按执行顺序排列的列表。父任务引用不明确时必须先进行候选消歧。

查询结果必须来自真实任务存储。

---

### 8.7 对话式状态更新

用户输入：

> 论文实验已经跑完了。

Agent 应执行：

1. 查询可能匹配的任务；
2. 判断候选任务数量；
3. 候选不唯一时请求用户选择；
4. 候选唯一时生成更新草稿；
5. 等待用户确认；
6. 调用状态更新工具；
7. 重新计算父任务进度；
8. 返回最新状态。

任务状态包括：

- `TODO`
- `DOING`
- `DONE`
- `BLOCKED`
- `CANCELLED`

---

### 8.8 父子任务与进度计算

任务采用树形结构：

```text
父任务
├── 子任务 1
├── 子任务 2
└── 子任务 3
```

第一版使用简单数量计算：

```text
父任务进度
=
已完成子任务数量
÷
有效子任务总数量
```

其中，`CANCELLED` 子任务不计入有效子任务；当有效子任务数量为零时，父任务不能因此自动完成。

后续版本支持按预计耗时或权重计算：

```text
父任务进度
=
已完成子任务权重之和
÷
全部有效子任务权重之和
```

父任务拥有至少一个有效子任务时，完成状态由子任务闭环确定性维护：

```text
parent.status == DONE
当且仅当
全部有效子任务 status == DONE
```

最后一个有效子任务变为 `DONE` 时，系统必须在同一个 Redis 事务中将父任务的 `progress` 更新为 `100`、将 `status` 更新为 `DONE`、写入 `completed_at` 并递增父任务版本。已完成子任务被重新打开，或者已完成父任务下新增有效子任务时，系统必须在同一个事务中重新计算进度，将父任务恢复为 `DOING` 并清空 `completed_at`。

父任务联动更新是已确认子任务写操作的确定性副作用，不需要再次请求用户确认。父任务的 `TODO`、`DOING` 和 `BLOCKED` 暂不全部由子任务推导，但必须始终满足上述 `DONE` 一致性约束。

---

### 8.9 下一步任务推荐

用户输入：

> 我今天只剩两个小时，接下来应该先做什么？

系统综合考虑：

- 有效优先级；
- 截止时间；
- 预计耗时；
- 当前进度；
- 前置依赖；
- 是否阻塞其他任务；
- 用户可用时间；
- 用户历史执行偏好。

推荐结果应具体说明：

- 建议先做哪个任务；
- 为什么优先做；
- 两小时内可以完成到什么程度；
- 完成后下一步是什么；
- 哪些任务暂时不建议开始。

---

## 9. 第二阶段扩展功能

### 9.1 每日任务简报

系统根据真实任务数据生成每日简报。

筛选范围：

- 已逾期任务；
- 今日到期任务；
- 即将到期任务；
- 高优先级任务；
- 正在执行任务；
- 长时间未更新任务；
- 被阻塞任务；
- 当日可完成任务。

LLM 负责组织语言，不负责决定任务真实状态。

### 9.2 动态重新规划

当用户修改以下信息时，Agent 可以重新规划：

- 可用时间；
- 截止时间；
- 完成进度；
- 任务优先级；
- 新增紧急任务；
- 任务被阻塞；
- 原计划未按时完成。

重新规划结果必须保留修改原因，并经过用户确认。

### 9.3 长期用户偏好

系统可以从用户明确反馈中提取：

- 喜欢的任务拆解粒度；
- 常用工作时间；
- 常见任务类别；
- 对优先级的修正习惯；
- 常用执行顺序；
- 对预计耗时的调整习惯；
- 明确表达的规划偏好。

只有稳定、明确且可复用的信息才能写入长期记忆。

### 9.4 历史经验复用

任务完成后生成经验摘要，例如：

```text
任务类型：论文修改

有效拆解方式：
1. 阅读修改要求
2. 整理待修改问题
3. 修改方法部分
4. 补充实验
5. 更新图表
6. 检查正文与附录
7. 完成最终排版
```

后续遇到相似任务时，通过向量检索召回相关经验，作为规划参考，而不是直接照搬。

### 9.5 周期性复盘

后续可支持：

- 每日完成情况；
- 每周任务总结；
- 计划与实际耗时差异；
- 经常延期的任务类型；
- 常见阻塞原因；
- 用户优先级修正趋势；
- 任务拆解采纳率。

---

## 10. 总体技术架构

```text
Vue 3 + TypeScript
        │
        ▼
FastAPI Agent Service
        │
        ▼
LangGraph StateGraph
  ┌─────┼──────────┬────────────┐
  │     │          │            │
意图识别 任务解析   任务拆解     动态规划
  │     │          │            │
  └─────┼──────────┴────────────┘
        │
   LangChain Tools
  ┌─────┴─────────────────────────────┐
  │                                   │
Redis                              Milvus
  │                                   │
Agent Checkpoint                    历史任务经验
当前会话状态                         用户长期偏好
任务结构化数据                       拆解模板
待确认草稿                           执行反馈
幂等键与锁                           相似任务检索
```

---

## 11. 技术栈选型

### 11.1 核心 Agent 框架：LangGraph

LangGraph 负责：

- StateGraph 构建；
- Agent 状态流转；
- 节点编排；
- 条件分支；
- Interrupt；
- Human-in-the-loop；
- Checkpoint；
- 线程恢复；
- 失败重试；
- 多步骤工具调用；
- 子流程组织。

选择 LangGraph 的原因是本项目存在大量需要明确状态、暂停确认和恢复执行的多步骤流程，不适合仅依赖一次性 Prompt 或普通链式调用完成。

### 11.2 LLM 应用组件：LangChain

LangChain 负责：

- 大模型统一接口；
- Prompt 模板；
- Tool 封装；
- 消息格式；
- 结构化输出；
- Embedding 接入；
- Retriever 接入；
- 模型切换。

LangChain 主要作为组件层使用，工作流控制由 LangGraph 负责。

### 11.3 Agent 服务：FastAPI

FastAPI 负责：

- 提供 Agent API；
- 接收用户输入；
- 管理用户 ID 和线程 ID；
- 调用 LangGraph；
- 提供确认和恢复接口；
- 返回流式结果；
- 提供任务查询接口；
- 参数校验；
- 权限检查；
- 异常处理。

相关技术：

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic
- HTTPX
- SSE

第一版优先使用 SSE，后续在确有双向实时通信需求时再考虑 WebSocket。

### 11.4 实时状态与任务存储：Redis

Redis 负责：

- LangGraph Checkpoint；
- 当前会话状态；
- Agent 短期上下文；
- 任务对象；
- 子任务对象；
- 待确认草稿；
- 用户当前上下文；
- 幂等键；
- 分布式锁；
- 热点查询缓存。

计划使用：

- Redis Hash 或 RedisJSON；
- Redis Search；
- Redis TTL；
- Redis Lock；
- LangGraph Redis Checkpointer；
- Redis Streams，后续可选。

Key 示例：

```text
task:{user_id}:{task_id}
task_children:{user_id}:{task_id}
agent:thread:{thread_id}
pending_action:{thread_id}
idempotency:{tool_name}:{request_id}
lock:task:{user_id}:{task_id}
```

#### Redis 持久化要求

- 开启 AOF；
- 定期生成 RDB 快照；
- 使用 Docker Volume；
- 建立备份机制；
- 明确数据恢复流程。

随着项目数据量和可靠性要求增加，可以在后续版本中引入 PostgreSQL 作为长期结构化数据源，Redis 保留为 Checkpoint、缓存和实时状态层。

### 11.5 长期语义记忆：Milvus

Milvus 负责保存：

- 已完成任务摘要；
- 用户稳定偏好；
- 历史拆解方案；
- 执行反馈；
- 失败经验；
- 相似任务模板。

选择 Milvus 的原因：

- 支持大规模向量检索；
- 支持 HNSW、IVF 等索引；
- 支持标量字段过滤；
- 支持 Dense、Sparse 和混合检索；
- 便于后续扩展语义记忆规模；
- 适合实现按用户、任务类型和记忆类型过滤。

Collection 建议命名：

```text
task_memories
```

核心字段：

```text
id
user_id
task_id
memory_type
content
category
status
created_at
updated_at
quality_score
embedding
```

`memory_type` 包括：

```text
task_history
user_preference
decomposition_template
execution_feedback
failure_experience
```

检索时必须增加用户过滤：

```text
user_id == 当前用户
```

### 11.6 Embedding 模型

Embedding 模型需要支持中文及中英文混合语义。

第一版需要支持：

- 任务描述向量化；
- 用户偏好向量化；
- 历史任务摘要向量化；
- 相似任务检索；
- Top-K 召回。

模型必须通过配置文件切换，不在业务代码中写死。

### 11.7 前端：Vue 3 + TypeScript

主要页面：

- Agent 对话页；
- 任务确认卡片；
- 子任务拆解确认页；
- 任务树面板；
- 今日简报页；
- Agent 执行轨迹页。

相关技术：

- Vue 3；
- TypeScript；
- Vite；
- Pinia；
- Vue Router；
- Axios；
- Ant Design Vue；
- SSE。

第一阶段前端只需完成：

1. 对话窗口；
2. AI 结果确认卡片；
3. 简单任务列表；
4. 子任务打卡；
5. Agent 执行状态展示。

### 11.8 可观测性

可使用 LangSmith 或自定义追踪模块记录：

- Graph 执行路径；
- 每个节点输入输出；
- 工具调用；
- 模型调用；
- Token 消耗；
- 节点耗时；
- 异常堆栈；
- Prompt 版本；
- 中断与恢复过程。

---

## 12. 数据职责划分

| 数据类型 | Redis | Milvus |
|---|---:|---:|
| 当前 Agent State | 是 | 否 |
| LangGraph Checkpoint | 是 | 否 |
| 当前会话上下文 | 是 | 否 |
| 待确认任务草稿 | 是 | 否 |
| 任务标题与描述 | 是 | 保存摘要 |
| 任务状态 | 是 | 否 |
| 截止时间 | 是 | 可作为 Metadata |
| 优先级 | 是 | 可作为 Metadata |
| 子任务完成状态 | 是 | 否 |
| 用户长期偏好 | 可缓存 | 是 |
| 历史任务经验 | 可缓存 | 是 |
| 历史拆解模板 | 否 | 是 |
| 相似任务语义检索 | 否 | 是 |
| 幂等键 | 是 | 否 |
| 分布式锁 | 是 | 否 |

概括：

> Redis 保存系统当前正在处理的真实状态，Milvus 保存系统后续可以复用的语义经验。

---

## 13. 核心数据模型

### 13.1 Task

建议字段：

```text
id
user_id
parent_id
title
description
category
status
deadline
estimated_minutes
actual_minutes
ai_priority
user_priority
effective_priority
priority_source
urgency_score
priority_reason
progress
is_ai_generated
created_at
updated_at
completed_at
version
```

### 13.2 TaskDependency

```text
id
user_id
task_id
depends_on_task_id
dependency_type
created_at
```

### 13.3 PendingAction

```text
id
user_id
thread_id
action_type
target_id
payload
confirmation_status
idempotency_key
created_at
expires_at
```

### 13.4 ToolExecutionLog

```text
id
user_id
thread_id
trace_id
tool_call_id
tool_name
input_payload
output_payload
confirmed
success
duration_ms
error_message
created_at
```

### 13.5 MemoryRecord

```text
id
user_id
task_id
memory_type
content
category
quality_score
source
created_at
embedding
```

---

## 14. LangGraph 状态设计

建议定义统一状态：

```python
class TaskAgentState(TypedDict, total=False):
    user_id: str
    thread_id: str
    user_message: str
    timezone: str

    intent: str
    intent_confidence: float

    current_task_id: str | None
    candidate_task_ids: list[str]

    parsed_task: dict | None
    retrieved_tasks: list[dict]
    retrieved_memories: list[dict]
    proposed_subtasks: list[dict]

    urgency_score: int | None
    ai_priority: str | None
    final_priority: str | None
    priority_reason: str | None

    pending_action: dict | None
    confirmation_status: str

    tool_calls: list[dict]
    final_response: str | None
    error_message: str | None
```

状态设计要求：

- 节点之间只通过 State 传递必要信息；
- 不在 State 中存放不可序列化对象；
- 大型查询结果只保留必要字段；
- 所有关键写操作保留 PendingAction；
- 恢复执行时可以根据 Checkpoint 继续；
- 错误信息和重试次数需要显式记录。

---

## 15. LangGraph 节点规划

第一版节点：

```text
load_context
classify_intent
parse_task
validate_task
calculate_priority
query_tasks
resolve_task_reference
prepare_tool_call
request_confirmation
execute_tool
update_progress
generate_response
handle_error
```

第二阶段节点：

```text
retrieve_memory
generate_subtasks
validate_subtasks
recommend_next_action
replan_tasks
write_memory
generate_daily_brief
```

节点职责必须单一，避免一个节点同时完成识别、查询、规划和写入。

---

## 16. LangGraph 工作流

### 16.1 创建任务流程

```text
START
  ↓
load_context
  ↓
classify_intent
  ↓
parse_task
  ↓
validate_task
  ├── 信息不足 → generate_response
  └── 信息完整 → calculate_priority
                       ↓
                prepare_tool_call
                       ↓
                request_confirmation
                ├── approve → execute_tool
                ├── edit → validate_task
                ├── regenerate → parse_task
                └── reject → generate_response
                       ↓
                generate_response
                       ↓
                      END
```

### 16.2 拆解任务流程

```text
START
  ↓
load_context
  ↓
classify_intent
  ↓
query_tasks
  ↓
resolve_task_reference
  ↓
retrieve_memory
  ↓
generate_subtasks
  ↓
validate_subtasks
  ↓
request_confirmation
  ├── approve → execute_tool
  ├── edit → validate_subtasks
  ├── regenerate → generate_subtasks
  └── reject → generate_response
  ↓
generate_response
  ↓
END
```

### 16.3 查询任务流程

```text
START
  ↓
load_context
  ↓
classify_intent
  ↓
query_tasks
  ↓
generate_response
  ↓
END
```

### 16.4 更新任务流程

```text
START
  ↓
load_context
  ↓
classify_intent
  ↓
query_tasks
  ↓
resolve_task_reference
  ├── 多个候选 → generate_response
  └── 唯一候选 → prepare_tool_call
                       ↓
                request_confirmation
                       ↓
                execute_tool
                       ↓
                update_progress
                       ↓
                generate_response
                       ↓
                      END
```

### 16.5 下一步推荐流程

```text
START
  ↓
load_context
  ↓
classify_intent
  ↓
query_tasks
  ↓
retrieve_memory
  ↓
recommend_next_action
  ↓
generate_response
  ↓
END
```

---

## 17. Tool Calling 规划

### 17.1 查询类工具

```text
query_tasks
get_task_detail
get_today_tasks
get_overdue_tasks
get_task_progress
get_blocked_tasks
search_similar_memories
```

查询类工具原则上可以直接执行。

### 17.2 写入类工具

```text
create_task
create_subtasks
update_task
update_task_status
update_task_priority
update_task_deadline
update_subtask_order
delete_task
save_long_term_memory
```

关键写入类工具必须经过确认。

### 17.3 工具参数要求

每个写工具至少包含：

```text
user_id
request_id
idempotency_key
confirmed
expected_version
```

### 17.4 工具安全要求

每个工具必须执行：

- 参数 Schema 校验；
- 用户权限校验；
- 目标对象归属校验；
- 幂等校验；
- 版本冲突校验；
- 状态流转合法性校验；
- 结果日志记录；
- 异常捕获。

---

## 18. API 规划

### 18.1 Agent 接口

```http
POST /api/agent/chat
POST /api/agent/confirm
POST /api/agent/resume
GET  /api/agent/threads/{thread_id}
GET  /api/agent/threads/{thread_id}/state
GET  /api/agent/threads/{thread_id}/trace
```

### 18.2 任务接口

```http
GET    /api/tasks
POST   /api/tasks
GET    /api/tasks/today
GET    /api/tasks/overdue
GET    /api/tasks/{task_id}
PATCH  /api/tasks/{task_id}
PATCH  /api/tasks/{task_id}/status
DELETE /api/tasks/{task_id}
GET    /api/tasks/{task_id}/subtasks
GET    /api/tasks/{task_id}/progress
```

前端手动操作同样需要经过后端参数校验，不能绕过任务规则。

### 18.3 记忆接口

```http
GET    /api/memories
GET    /api/memories/search
DELETE /api/memories/{memory_id}
```

长期记忆必须允许用户查看和删除。

### 18.4 健康检查接口

```http
GET /health
GET /health/redis
GET /health/milvus
GET /health/model
```

---

## 19. 长期记忆机制

### 19.1 允许写入的记忆

- 用户明确表达且长期稳定的偏好；
- 被用户采纳的任务拆解方式；
- 完成任务后的有效经验；
- 明确记录的失败原因；
- 任务预计耗时与实际耗时差异；
- 用户多次确认的执行习惯。

### 19.2 不应直接写入的内容

- 一次性的临时情绪；
- 未经用户确认的模型推断；
- 不稳定的短期安排；
- 低置信度偏好；
- 原始完整对话；
- 包含无关隐私的信息。

### 19.3 记忆检索流程

```text
构造检索 Query
→ 添加 user_id 过滤
→ 添加 memory_type 过滤
→ 向量 Top-K 召回
→ 相似度阈值过滤
→ 可选 Rerank
→ 去重
→ 传入规划节点
```

### 19.4 记忆质量控制

每条记忆应保存：

- 来源；
- 创建时间；
- 置信度；
- 质量分数；
- 是否由用户确认；
- 对应任务 ID；
- 最近使用时间。

---

## 20. 可观测性与评测

### 20.1 可观测性指标

记录：

- Graph 完整执行路径；
- 节点输入输出；
- 节点耗时；
- 模型请求耗时；
- Token 消耗；
- 工具调用次数；
- 工具失败次数；
- 重试次数；
- 中断次数；
- 恢复成功率；
- 向量检索耗时；
- 最终响应时间。

### 20.2 任务解析评测

- JSON 输出成功率；
- 标题提取准确率；
- 截止时间识别准确率；
- 分类准确率；
- 预计耗时合理率；
- 缺失字段识别率。

### 20.3 优先级评测

- AI 优先级被用户修改的比例；
- 逾期任务识别准确率；
- 紧急任务漏判率；
- 高优先级误判率；
- 判断理由可解释性。

### 20.4 任务拆解评测

- 子任务采纳率；
- 重复步骤比例；
- 步骤可执行性；
- 步骤顺序合理性；
- 依赖关系正确率；
- 用户重新生成比例。

### 20.5 工具调用评测

- 工具选择准确率；
- 参数校验失败率；
- 工具调用成功率；
- 重复调用率；
- 写操作误执行率；
- 幂等控制成功率；
- 中断恢复成功率。

### 20.6 Milvus 检索评测

- Recall@K；
- 相似任务命中率；
- Metadata Filter 正确率；
- 用户记忆隔离正确率；
- 检索延迟；
- 无关记忆召回比例。

### 20.7 端到端评测

建立覆盖以下场景的测试集：

- 创建任务；
- 模糊时间解析；
- 缺少信息；
- 任务拆解；
- 状态更新；
- 多候选任务；
- 任务查询；
- 下一步推荐；
- 中断恢复；
- 重复请求；
- 工具异常；
- Redis 临时故障；
- 无相关长期记忆。

---

## 21. 安全性与可靠性设计

### 21.1 幂等控制

所有写操作必须携带幂等键。

```text
idempotency:{tool_name}:{request_id}
```

相同幂等键不得重复执行写入。

### 21.2 并发控制

对任务更新使用：

- Redis Lock；
- 版本号；
- 乐观锁；
- `expected_version` 校验。

### 21.3 状态流转限制

例如：

```text
TODO → DOING
TODO → CANCELLED
DOING → DONE
DOING → BLOCKED
BLOCKED → DOING
DONE → DOING，需要额外确认
```

非法状态流转必须拒绝。

### 21.4 用户数据隔离

所有任务查询、更新和记忆检索必须包含 `user_id` 条件。

Agent 不能仅根据客户端传入的任务 ID 执行操作，必须校验任务归属。

### 21.5 故障降级

当组件异常时：

- Milvus 不可用：跳过长期记忆检索，继续基础规划；
- LLM 结构化输出失败：重试并进入校验节点；
- Redis 短暂异常：返回可恢复错误，不继续写入；
- LangSmith 不可用：本地日志继续记录；
- 流式响应中断：允许通过 thread_id 查询当前状态。

---

## 22. 开发阶段与实施顺序

### 第一阶段：LangGraph 最小闭环

#### 目标

实现可运行的任务创建与查询 Agent。

#### 开发任务

- 初始化 FastAPI；
- 配置模型接口；
- 定义 Agent State；
- 构建 LangGraph；
- 实现意图识别；
- 实现任务解析；
- 实现任务字段校验；
- 实现紧急程度计算；
- 实现确认节点；
- 实现创建任务工具；
- 接入 Redis Checkpoint；
- 使用 Redis 保存任务；
- 实现基础对话接口；
- 实现任务查询工具。

#### 验收标准

用户可以通过自然语言创建任务，确认后保存，并能在后续对话中查询到该任务。

---

### 第二阶段：任务拆解与进度管理

#### 开发任务

- 实现任务引用解析；
- 实现任务拆解节点；
- 实现批量创建子任务；
- 实现任务树；
- 实现子任务状态更新；
- 实现父任务进度计算；
- 实现子任务状态与父任务完成状态的原子联动；
- 实现拆解确认卡片；
- 实现任务详情和进度查询。

#### 验收标准

用户可以将复杂任务拆解为多个直接挂载在原任务下的步骤；确认后全部子任务以原子批次写入且重复请求不会重复创建。用户逐项更新子任务状态时，父任务进度同步更新；全部有效子任务完成后父任务自动完成，任一子任务重新打开后父任务自动恢复为进行中。

---

### 第三阶段：长期语义记忆

#### 开发任务

- 使用 Docker 部署 Milvus；
- 创建 Collection；
- 接入 Embedding；
- 写入已完成任务摘要；
- 写入用户确认偏好；
- 实现 Metadata Filter；
- 实现相似任务 Top-K 检索；
- 将检索结果接入任务拆解节点；
- 实现记忆查看和删除接口。

#### 验收标准

Agent 在拆解新任务时，可以召回当前用户的相关历史任务经验。

---

### 第四阶段：每日简报与下一步推荐

#### 开发任务

- 实现今日任务查询；
- 实现逾期任务查询；
- 实现任务排序规则；
- 实现每日简报；
- 实现下一步推荐；
- 支持用户可用时间约束；
- 支持任务阻塞和依赖判断。

#### 验收标准

用户询问“今天做什么”或“只剩两小时先做什么”时，系统能基于真实数据给出具体建议。

---

### 第五阶段：动态重新规划

#### 开发任务

- 检测计划变化；
- 接收新的可用时间；
- 调整任务执行顺序；
- 处理新增紧急任务；
- 处理任务延期；
- 保存计划版本；
- 对重新规划结果进行确认；
- 保留修改原因。

#### 验收标准

用户的时间和进度发生变化后，系统能够生成新的可执行计划，并在确认后保存。

---

### 第六阶段：评测、可观测性与部署

#### 开发任务

- 接入 LangSmith 或自定义 Trace；
- 记录节点耗时；
- 记录 Tool Calling；
- 构建评测数据集；
- 增加失败重试；
- 增加降级逻辑；
- 编写 Docker Compose；
- 完善前端界面；
- 编写部署文档；
- 编写使用说明；
- 完成端到端测试。

#### 验收标准

系统具备完整部署方式、执行追踪能力和可重复运行的评测流程。

---

## 23. 第一版任务优先级

### P0：必须完成

- FastAPI 服务；
- LangGraph 基础工作流；
- Agent State；
- 意图识别；
- 任务结构化解析；
- 时间解析；
- 优先级计算；
- Human-in-the-loop；
- Redis Checkpoint；
- 创建任务工具；
- 查询任务工具；
- 更新任务状态；
- 幂等控制；
- 基础对话页面。

### P1：核心增强

- 任务拆解与结构化方案校验；
- 原子批量创建直接挂载于父任务的子任务；
- 父子任务进度及完成状态自动联动；
- 下一步推荐；
- SSE 流式响应；
- 工具执行日志；
- 基础 Trace。

### P2：后续扩展

- Milvus 长期记忆；
- 每日简报；
- 动态重新规划；
- 周期性复盘；
- Reranker；
- Dense + Sparse 混合检索；
- 完整评测平台；
- 复杂任务面板。

---

## 24. 第一版暂不实现

为了保证主流程尽快形成闭环，第一版暂不实现：

- 多 Agent 协作；
- MCP Server；
- 邮件和日历自动操作；
- 语音助手；
- 多人协作；
- 移动端 App；
- 复杂权限体系；
- 自动执行高风险外部操作；
- 大规模分布式 Milvus 集群；
- 复杂知识库 RAG；
- 复杂甘特图；
- 自动生成长期日程；
- 完整社交或团队功能。

---

## 25. 项目目录建议

```text
ai-task-agent/
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── AgentChat.vue
│   │   │   ├── TaskBoard.vue
│   │   │   └── DailyBrief.vue
│   │   ├── components/
│   │   │   ├── ConfirmationCard.vue
│   │   │   ├── TaskTree.vue
│   │   │   ├── TaskProgress.vue
│   │   │   └── AgentTrace.vue
│   │   ├── stores/
│   │   ├── api/
│   │   └── types/
│   └── package.json
│
├── agent-service/
│   ├── app/
│   │   ├── api/
│   │   ├── graph/
│   │   │   ├── state.py
│   │   │   ├── builder.py
│   │   │   ├── routing.py
│   │   │   └── nodes/
│   │   ├── tools/
│   │   │   ├── task_tools.py
│   │   │   ├── memory_tools.py
│   │   │   └── planning_tools.py
│   │   ├── storage/
│   │   │   ├── redis_client.py
│   │   │   ├── redis_task_store.py
│   │   │   ├── redis_checkpoint.py
│   │   │   └── milvus_store.py
│   │   ├── schemas/
│   │   ├── prompts/
│   │   ├── services/
│   │   ├── observability/
│   │   ├── core/
│   │   ├── config.py
│   │   └── main.py
│   └── tests/
│
├── evaluation/
│   ├── datasets/
│   ├── task_parse_eval.py
│   ├── priority_eval.py
│   ├── decomposition_eval.py
│   ├── retrieval_eval.py
│   └── tool_call_eval.py
│
├── scripts/
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── data-model.md
│   └── deployment.md
├── docker-compose.yml
├── .env.example
├── README.md
└── PROJECT_TASK_BOOK.md
```

---

## 26. 测试策略

### 26.1 单元测试

重点覆盖：

- 时间解析；
- 紧急程度计算；
- 状态流转；
- 父任务进度；
- 幂等键；
- 用户数据隔离；
- 工具参数校验。

### 26.2 节点测试

每个 LangGraph 节点独立测试：

- 输入 State；
- 输出 State；
- 异常分支；
- 缺失字段；
- 重试逻辑。

### 26.3 Graph 测试

验证：

- 条件路由；
- Interrupt；
- Resume；
- Checkpoint；
- 失败恢复；
- 重复请求；
- 用户拒绝；
- 用户编辑后恢复。

### 26.4 端到端测试

从用户输入开始，验证完整流程：

```text
自然语言输入
→ Agent 解析
→ 用户确认
→ 工具执行
→ 数据保存
→ 后续查询
→ 状态更新
```

---

## 27. 主要交付物

项目完成后应产出：

1. 可运行的 LangGraph Agent；
2. FastAPI Agent 服务；
3. Redis 状态与任务存储模块；
4. Milvus 长期记忆模块；
5. Vue 对话与任务管理界面；
6. Docker Compose 部署文件；
7. 项目 README；
8. 项目启动任务书；
9. 系统架构图；
10. LangGraph 流程图；
11. API 文档；
12. 数据模型说明；
13. 部署说明；
14. 用户使用说明；
15. 自动化测试；
16. Agent 评测报告；
17. 版本迭代记录；
18. 演示视频与项目截图。

---

## 28. 主要风险与应对方案

### 28.1 模型输出不稳定

应对：

- 使用 Pydantic Schema；
- 使用结构化输出；
- 增加校验节点；
- 失败后重试；
- 无法恢复时返回可编辑表单。

### 28.2 Agent 重复执行写工具

应对：

- 使用幂等键；
- 保存 Tool Call ID；
- Redis 记录请求状态；
- 写工具校验 `confirmed`；
- 对关键对象加锁；
- 使用版本号控制更新。

### 28.3 Redis 数据丢失

应对：

- 开启 AOF；
- 定期生成 RDB；
- 使用持久化 Volume；
- 执行定期备份；
- 后续引入 PostgreSQL 保存长期结构化数据。

### 28.4 长期记忆污染

应对：

- 仅保存稳定且高价值的内容；
- 对记忆进行类型分类；
- 保存来源任务 ID；
- 设置用户隔离过滤；
- 保存质量分数；
- 允许用户查看和删除；
- 低置信度内容不自动写入。

### 28.5 检索结果无关

应对：

- 使用 Metadata Filter；
- 设置相似度阈值；
- 调整 Top-K；
- 增加 Reranker；
- 评估 Embedding 模型；
- 后续实现混合检索。

### 28.6 Agent 流程过度复杂

应对：

- 第一版只实现一个主 Graph；
- 不急于引入多 Agent；
- 每个节点职责单一；
- 查询与写入流程分开；
- 固定高风险操作边界；
- 每个阶段单独验收。

### 28.7 前端开发占用过多时间

应对：

- 第一阶段仅实现基础对话页；
- 确认卡片优先于复杂看板；
- 任务树优先于统计图表；
- 使用成熟组件库；
- 后端流程稳定后再完善视觉效果。

---

## 29. 项目验收标准

### 29.1 第一版验收

第一版必须能够完成：

```text
创建任务
→ AI 结构化解析
→ 优先级计算
→ 用户确认
→ Redis 保存
→ 对话查询
→ 状态更新
→ Checkpoint 恢复
```

同时满足：

- 写操作不会绕过确认；
- 重复请求不会重复创建；
- 任务状态来自真实数据；
- Agent 中断后可以恢复；
- 工具调用具有日志；
- 用户数据相互隔离。

### 29.2 完整版本验收

完整版本应进一步支持：

```text
任务拆解
→ 子任务进度
→ 长期记忆
→ 相似经验检索
→ 每日简报
→ 下一步推荐
→ 动态重新规划
→ 评测与可观测性
```

---

## 30. 项目核心价值

1. 用户可以通过自然语言而不是复杂表单管理任务。
2. Agent 能够将模糊目标转化为结构化任务。
3. 任务优先级由语义理解和确定性规则共同决定。
4. 复杂任务可以被拆解为清晰、可执行的步骤。
5. 所有真实任务状态都由存储系统维护。
6. 关键写操作通过 Human-in-the-loop 控制。
7. LangGraph Checkpoint 支持中断、恢复和持续对话。
8. Redis 保存实时状态，Milvus保存可复用的历史经验。
9. 系统能够根据用户时间和任务进度推荐下一步行动。
10. 当计划发生变化时，系统能够重新规划而不是静态展示。
11. 工具调用、模型调用和任务执行全过程可追踪。
12. 项目能够持续扩展为长期个人 AI 执行助手。

---

## 31. 项目一句话介绍

> 基于 LangGraph、FastAPI、Redis 和 Milvus 构建的个人 AI 任务规划与执行助手，通过自然语言理解用户目标，结合规则计算任务优先级，并利用 Human-in-the-loop、Tool Calling、状态持久化和长期语义记忆，实现任务创建、拆解、进度跟踪、下一步推荐与动态重新规划。

---

## 32. 项目启动结论

本项目第一优先级不是搭建完整的传统待办后台，而是完成以下最小 Agent 闭环：

```text
自然语言创建任务
→ AI 结构化解析
→ 紧急程度计算
→ 用户确认
→ Redis 保存
→ 对话查询
→ 状态更新
→ LangGraph 恢复
```

完成最小闭环后，再依次增加：

```text
任务拆解
→ 子任务进度
→ Milvus 长期记忆
→ 历史经验检索
→ 每日简报
→ 下一步推荐
→ 动态重新规划
→ Agent 评测与可观测性
```

项目开发过程中应始终围绕 Agent 的状态、工具、记忆、确认、恢复和真实任务数据展开，避免重新退化为一个以表单和 CRUD 为主的普通待办系统。
