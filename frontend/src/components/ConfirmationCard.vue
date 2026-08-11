<script setup lang='ts'>
import { computed, reactive, ref, watch } from 'vue'

import type {
  AgentResponse,
  ConfirmationAction,
  ConfirmationOptions,
  SubtaskDraft,
  SubtaskPlanEdit,
  TaskDraftEdit,
  TaskPriority,
} from '../types/agent'

const props = defineProps<{
  response: AgentResponse
  loading: boolean
}>()

const emit = defineEmits<{
  action: [
    action: ConfirmationAction,
    options?: ConfirmationOptions,
  ]
}>()

const editing = ref(false)
const draft = computed(() => props.response.task_draft)
const plan = computed(() => props.response.subtask_plan)
const pending = computed(() => props.response.pending_action)
const isStatusUpdate = computed(
  () => pending.value?.action_type === 'update_task_status',
)
const isAttributeUpdate = computed(
  () => pending.value?.action_type === 'update_task',
)
const isSubtaskBatch = computed(
  () => pending.value?.action_type === 'create_subtasks_batch',
)
const isTaskDelete = computed(
  () => ['delete_task', 'delete_tasks_batch'].includes(
    pending.value?.action_type || '',
  ),
)
const isBatchDelete = computed(
  () => pending.value?.action_type === 'delete_tasks_batch',
)
const isTaskRestore = computed(
  () => pending.value?.action_type === 'restore_task',
)
const isRestrictedUpdate = computed(
  () => isStatusUpdate.value
    || isAttributeUpdate.value
    || isTaskDelete.value
    || isTaskRestore.value,
)
const confirmationTitle = computed(() => {
  if (isStatusUpdate.value) return '确认状态更新'
  if (isAttributeUpdate.value) return '确认属性修改'
  if (isSubtaskBatch.value) return '确认任务拆解方案'
  if (isBatchDelete.value) return '确认批量永久删除'
  if (isTaskDelete.value) return '确认永久删除任务'
  if (isTaskRestore.value) return '确认恢复已取消任务'
  return '确认创建任务'
})

const subtaskEditSummary = ref<string | null>(null)
const subtaskEditItems = ref<SubtaskDraft[]>([])
const subtaskEditError = ref<string | null>(null)

const editForm = reactive<TaskDraftEdit>({
  title: draft.value?.title,
  description: draft.value?.description,
  category: draft.value?.category,
  deadline: draft.value?.deadline,
  estimated_minutes: draft.value?.estimated_minutes,
  user_priority: null,
})
const deadlineDate = ref<string>()
const deadlineTime = ref<string>()
const deadlineError = ref<string | null>(null)


const priorityOptions: Array<{ label: string; value: TaskPriority }> = [
  { label: '紧急', value: 'URGENT' },
  { label: '高', value: 'HIGH' },
  { label: '中', value: 'MEDIUM' },
  { label: '低', value: 'LOW' },
]

const priorityLabels: Record<TaskPriority, string> = {
  URGENT: '紧急',
  HIGH: '高',
  MEDIUM: '中',
  LOW: '低',
}

const selectedUserPriority = computed(() =>
  asTaskPriority(pending.value?.payload.user_priority),
)
const displayedPriority = computed(
  () =>
    selectedUserPriority.value
    || asTaskPriority(pending.value?.payload.ai_priority),
)
const displayedPriorityText = computed(() => {
  const priority = displayedPriority.value
  if (!priority) return '未设置'
  const source = selectedUserPriority.value ? '用户设置' : 'AI 建议'
  return `${priorityLabels[priority]}（${source}）`
})

function asTaskPriority(value: unknown): TaskPriority | null {
  return typeof value === 'string' && value in priorityLabels
    ? value as TaskPriority
    : null
}

function formatAttributeValue(field: string, value: unknown) {
  if (value === null || value === undefined || value === '') return '清空'
  if (field === 'deadline' && typeof value === 'string') {
    const parsed = parseShanghaiDateTime(value)
    return parsed ? `${parsed.date} ${parsed.time}（北京时间）` : value
  }
  if (field === 'estimated_minutes') return `${String(value)} 分钟`
  if (field === 'user_priority') {
    const priority = asTaskPriority(value)
    return priority ? priorityLabels[priority] : String(value)
  }
  return String(value)
}

function hasAttribute(field: string) {
  return Object.prototype.hasOwnProperty.call(
    pending.value?.payload || {},
    field,
  )
}

function attributeValue(field: string) {
  return formatAttributeValue(field, pending.value?.payload[field])
}
const displayedDeadline = computed(() => {
  const deadline = draft.value?.deadline
  if (!deadline) return null
  const parsed = parseShanghaiDateTime(deadline)
  return parsed
    ? `${parsed.date} ${parsed.time}（北京时间）`
    : deadline
})

watch([deadlineDate, deadlineTime], () => {
  deadlineError.value = null
})

watch(
  () => pending.value?.id,
  () => {
    editing.value = false
    subtaskEditError.value = null
  },
)

function parseShanghaiDateTime(value: string | null | undefined) {
  const instant = value ? new Date(value) : new Date()
  if (Number.isNaN(instant.getTime())) return null

  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(instant)
      .filter((part) => part.type !== 'literal')
      .map((part) => [part.type, part.value]),
  )
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    time: `${parts.hour}:${parts.minute}`,
  }
}

function startEditing() {
  if (isSubtaskBatch.value) {
    const currentPlan = plan.value
    if (!currentPlan) return
    subtaskEditSummary.value = currentPlan.summary
    subtaskEditItems.value = currentPlan.items.map((item) => ({
      ...item,
      depends_on: [...item.depends_on],
    }))
    subtaskEditError.value = null
    editing.value = true
    return
  }
  const currentDraft = draft.value
  if (!currentDraft) return

  editForm.title = currentDraft.title
  editForm.description = currentDraft.description
  editForm.category = currentDraft.category
  editForm.deadline = currentDraft.deadline
  editForm.estimated_minutes = currentDraft.estimated_minutes
  editForm.user_priority = selectedUserPriority.value

  const deadline = parseShanghaiDateTime(currentDraft.deadline)
  deadlineDate.value = deadline?.date
  deadlineTime.value = deadline?.time
  deadlineError.value = null
  editing.value = true
}

function buildShanghaiIso(date: string, time: string) {
  return `${date}T${time}:00+08:00`
}


function submitEdit() {
  if (isSubtaskBatch.value) {
    const items = subtaskEditItems.value.map((item, index) => ({
      ...item,
      title: item.title.trim(),
      description: item.description.trim(),
      order: index + 1,
    }))
    if (items.length < 3) {
      subtaskEditError.value = '拆解方案至少需要 3 个子任务'
      return
    }
    if (items.some((item) => !item.title)) {
      subtaskEditError.value = '每个子任务都必须填写标题'
      return
    }
    const edits: SubtaskPlanEdit = {
      summary: subtaskEditSummary.value?.trim() || null,
      items,
    }
    emit('action', 'edit', { edits })
    editing.value = false
    return
  }
  if (!editForm.title?.trim()) return
  if (!deadlineDate.value) {
    deadlineError.value = '请选择截止日期'
    return
  }
  if (!deadlineTime.value) {
    deadlineError.value = '请选择截止时间'
    return
  }

  const deadline = buildShanghaiIso(deadlineDate.value, deadlineTime.value)
  const selectedTime = Date.parse(deadline)
  const currentMinute = Math.floor(Date.now() / 60_000) * 60_000
  if (Number.isNaN(selectedTime)) {
    deadlineError.value = '截止时间格式无效，请重新选择'
    return
  }
  if (selectedTime < currentMinute) {
    deadlineError.value = '截止时间不能早于当前时间'
    return
  }

  emit('action', 'edit', {
    edits: {
      ...editForm,
      title: editForm.title.trim(),
      deadline,
    },
  })
  editing.value = false
}

function sendAction(action: ConfirmationAction) {
  emit('action', action)
}

function approve() {
  sendAction('approve')
}

function reject() {
  sendAction('reject')
}

function regenerate() {
  sendAction('regenerate')
}

function displayedSubtaskDeadline(value: string | null) {
  if (!value) return null
  const parsed = parseShanghaiDateTime(value)
  return parsed ? `${parsed.date} ${parsed.time}` : value
}

function dependencyLabel(stepKey: string) {
  const items = editing.value ? subtaskEditItems.value : plan.value?.items || []
  const dependency = items.find((item) => item.step_key === stepKey)
  return dependency ? `${dependency.order}. ${dependency.title}` : stepKey
}
</script>

<template>
  <a-card class='confirmation-card' size='small'>
    <template #title>
      <span>{{ confirmationTitle }}</span>
    </template>

    <template v-if='isTaskDelete'>
      <a-alert
        type='error'
        show-icon
        message='该操作会永久删除任务，且无法恢复。'
      />
      <a-list
        v-if='isBatchDelete'
        class='delete-details'
        size='small'
        bordered
        :data-source='response.deletion_tasks'
      >
        <template #renderItem='{ item }'>
          <a-list-item>
            <a-list-item-meta :description='`${item.status}${item.category ? ` · ${item.category}` : ""}`'>
              <template #title>{{ item.title }}</template>
            </a-list-item-meta>
          </a-list-item>
        </template>
      </a-list>
      <a-descriptions v-else class='delete-details' :column='1' size='small'>
        <a-descriptions-item label='任务'>
          {{ response.task?.title || pending?.target_id }}
        </a-descriptions-item>
        <a-descriptions-item label='任务 ID'>
          {{ response.task?.id || pending?.target_id }}
        </a-descriptions-item>
        <a-descriptions-item v-if='response.task' label='当前状态'>
          {{ response.task.status }}
        </a-descriptions-item>
        <a-descriptions-item v-if='response.parent_task' label='父任务影响'>
          删除后将重新计算“{{ response.parent_task.title }}”的进度
        </a-descriptions-item>
      </a-descriptions>
    </template>

    <template v-else-if='isTaskRestore'>
      <a-alert
        type='warning'
        show-icon
        message='该任务已被取消，必须先恢复为待办，才能继续当前修改。'
      />
      <a-descriptions :column='1' size='small'>
        <a-descriptions-item label='任务'>
          {{ response.task?.title || pending?.target_id }}
        </a-descriptions-item>
        <a-descriptions-item label='状态变化'>
          CANCELLED → TODO
        </a-descriptions-item>
      </a-descriptions>
    </template>

    <template v-else-if='isStatusUpdate'>
      <a-descriptions :column='1' size='small'>
        <a-descriptions-item label='任务'>
          {{ response.task?.title || pending?.target_id }}
        </a-descriptions-item>
        <a-descriptions-item label='状态变化'>
          {{ pending?.payload.current_status }} → {{ pending?.payload.target_status }}
        </a-descriptions-item>
      </a-descriptions>
    </template>

    <template v-else-if='isAttributeUpdate'>
      <a-descriptions :column='1' size='small'>
        <a-descriptions-item label='任务'>
          {{ response.task?.title || pending?.target_id }}
        </a-descriptions-item>
        <a-descriptions-item v-if='hasAttribute("title")' label='标题'>
          {{ attributeValue('title') }}
        </a-descriptions-item>
        <a-descriptions-item v-if='hasAttribute("description")' label='描述'>
          {{ attributeValue('description') }}
        </a-descriptions-item>
        <a-descriptions-item v-if='hasAttribute("category")' label='分类'>
          {{ attributeValue('category') }}
        </a-descriptions-item>
        <a-descriptions-item v-if='hasAttribute("deadline")' label='截止时间'>
          {{ attributeValue('deadline') }}
        </a-descriptions-item>
        <a-descriptions-item
          v-if='hasAttribute("estimated_minutes")'
          label='预计耗时'
        >
          {{ attributeValue('estimated_minutes') }}
        </a-descriptions-item>
        <a-descriptions-item
          v-if='hasAttribute("user_priority")'
          label='用户优先级'
        >
          {{ attributeValue('user_priority') }}
        </a-descriptions-item>
      </a-descriptions>
    </template>

    <template v-else-if='isSubtaskBatch && plan'>
      <div v-if='!editing' class='subtask-plan'>
        <div class='subtask-plan-context'>
          <div>
            <span class='subtask-plan-label'>父任务</span>
            <strong>{{ response.parent_task?.title || response.task?.title || plan.parent_task_id }}</strong>
          </div>
          <a-tag color='blue'>{{ plan.items.length }} 个子任务</a-tag>
        </div>

        <p v-if='plan.summary' class='subtask-plan-summary'>
          {{ plan.summary }}
        </p>

        <a-alert
          v-for='warning in plan.warnings'
          :key='warning'
          class='subtask-warning'
          type='warning'
          show-icon
          :message='warning'
        />

        <ol class='subtask-items'>
          <li
            v-for='item in plan.items'
            :key='item.step_key'
            class='subtask-item'
          >
            <div class='subtask-item-heading'>
              <span class='subtask-order'>{{ item.order }}</span>
              <strong>{{ item.title }}</strong>
              <span v-if='item.estimated_minutes' class='subtask-duration'>
                {{ item.estimated_minutes }} 分钟
              </span>
            </div>
            <p v-if='item.description' class='subtask-description'>
              {{ item.description }}
            </p>
            <div
              v-if='item.depends_on.length || item.deadline'
              class='subtask-meta'
            >
              <span v-if='item.depends_on.length'>
                前置：{{ item.depends_on.map(dependencyLabel).join('、') }}
              </span>
              <span v-if='item.deadline'>
                截止：{{ displayedSubtaskDeadline(item.deadline) }}
              </span>
            </div>
          </li>
        </ol>
      </div>

      <a-form v-else layout='vertical' class='subtask-edit-form'>
        <a-alert
          v-if='subtaskEditError'
          class='subtask-edit-error'
          type='error'
          show-icon
          :message='subtaskEditError'
        />
        <a-form-item label='方案说明'>
          <a-textarea
            v-model:value='subtaskEditSummary'
            :rows='2'
            :maxlength='1000'
          />
        </a-form-item>
        <div
          v-for='item in subtaskEditItems'
          :key='item.step_key'
          class='subtask-edit-item'
        >
          <div class='subtask-edit-heading'>
            <span class='subtask-order'>{{ item.order }}</span>
            <strong>步骤 {{ item.order }}</strong>
            <span v-if='item.depends_on.length' class='subtask-dependency-note'>
              前置：{{ item.depends_on.map(dependencyLabel).join('、') }}
            </span>
          </div>
          <a-form-item label='标题' required>
            <a-input v-model:value='item.title' :maxlength='200' />
          </a-form-item>
          <a-form-item label='描述'>
            <a-textarea v-model:value='item.description' :rows='2' />
          </a-form-item>
          <a-form-item label='预计分钟'>
            <a-input-number
              v-model:value='item.estimated_minutes'
              :min='1'
            />
          </a-form-item>
        </div>
      </a-form>
    </template>

    <template v-else-if='draft'>
      <a-descriptions v-if='!editing' :column='1' size='small'>
        <a-descriptions-item label='标题'>{{ draft.title }}</a-descriptions-item>
        <a-descriptions-item v-if='draft.description' label='描述'>
          {{ draft.description }}
        </a-descriptions-item>
        <a-descriptions-item v-if='displayedDeadline' label='截止时间'>
          {{ displayedDeadline }}
        </a-descriptions-item>
        <a-descriptions-item label='优先级'>
          {{ displayedPriorityText }}
        </a-descriptions-item>
        <a-descriptions-item v-if='draft.estimated_minutes' label='预计耗时'>
          {{ draft.estimated_minutes }} 分钟
        </a-descriptions-item>
      </a-descriptions>

      <a-form v-else layout='vertical' class='edit-form'>
        <a-form-item label='标题' required>
          <a-input v-model:value='editForm.title' :maxlength='200' />
        </a-form-item>
        <a-form-item label='描述'>
          <a-textarea v-model:value='editForm.description' :rows='2' />
        </a-form-item>
        <a-form-item
          label='截止时间（北京时间）'
          required
          :validate-status='deadlineError ? "error" : undefined'
          :help='deadlineError || undefined'
        >
          <div class='deadline-fields'>
            <a-date-picker
              v-model:value='deadlineDate'
              value-format='YYYY-MM-DD'
              format='YYYY-MM-DD'
              placeholder='选择日期'
              @change='deadlineError = null'
            />
            <a-time-picker
              v-model:value='deadlineTime'
              value-format='HH:mm'
              format='HH:mm'
              :show-second='false'
              placeholder='选择时间'
              @change='deadlineError = null'
            />
          </div>
        </a-form-item>
        <a-form-item label='预计分钟'>
          <a-input-number v-model:value='editForm.estimated_minutes' :min='1' />
        </a-form-item>
        <a-form-item label='用户优先级'>
          <a-select
            v-model:value='editForm.user_priority'
            allow-clear
            :options='priorityOptions'
          />
        </a-form-item>
      </a-form>
    </template>

    <div class='confirmation-actions'>
      <template v-if='editing'>
        <a-button @click='editing = false'>返回</a-button>
        <a-button type='primary' :loading='loading' @click='submitEdit'>
          保存并继续
        </a-button>
      </template>
      <template v-else>
        <a-button
          :danger='!isTaskDelete'
          :disabled='loading'
          @click='reject'
        >
          取消
        </a-button>
        <a-button
          v-if='!isRestrictedUpdate'
          :disabled='loading'
          @click='regenerate'
        >
          重新生成
        </a-button>
        <a-button
          v-if='!isRestrictedUpdate'
          :disabled='loading'
          @click='startEditing'
        >
          编辑
        </a-button>
        <a-button
          type='primary'
          :danger='isTaskDelete'
          :loading='loading'
          @click='approve'
        >
          {{ isTaskDelete ? '确认永久删除' : (isTaskRestore ? '确认恢复' : '确认') }}
        </a-button>
      </template>
    </div>
  </a-card>
</template>
