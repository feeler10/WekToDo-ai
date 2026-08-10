<script setup lang='ts'>
import { computed, reactive, ref, watch } from 'vue'

import type {
  AgentResponse,
  ConfirmationAction,
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
    options?: { edits?: TaskDraftEdit; feedback?: string },
  ]
}>()

const editing = ref(false)
const draft = computed(() => props.response.task_draft)
const pending = computed(() => props.response.pending_action)
const isStatusUpdate = computed(
  () => pending.value?.action_type === 'update_task_status',
)
const isAttributeUpdate = computed(
  () => pending.value?.action_type === 'update_task',
)
const isRestrictedUpdate = computed(
  () => isStatusUpdate.value || isAttributeUpdate.value,
)
const confirmationTitle = computed(() => {
  if (isStatusUpdate.value) return '确认状态更新'
  if (isAttributeUpdate.value) return '确认属性修改'
  return '确认创建任务'
})

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
</script>

<template>
  <a-card class='confirmation-card' size='small'>
    <template #title>
      <span>{{ confirmationTitle }}</span>
    </template>

    <template v-if='isStatusUpdate'>
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
        <a-button danger :disabled='loading' @click='reject'>取消</a-button>
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
          :loading='loading'
          @click='approve'
        >
          确认
        </a-button>
      </template>
    </div>
  </a-card>
</template>
