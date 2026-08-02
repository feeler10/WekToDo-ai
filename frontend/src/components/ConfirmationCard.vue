<script setup lang='ts'>
import { computed, reactive, ref } from 'vue'

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

const editForm = reactive<TaskDraftEdit>({
  title: draft.value?.title,
  description: draft.value?.description,
  category: draft.value?.category,
  deadline: draft.value?.deadline,
  estimated_minutes: draft.value?.estimated_minutes,
  user_priority: null,
})

const priorityOptions: Array<{ label: string; value: TaskPriority }> = [
  { label: '紧急', value: 'URGENT' },
  { label: '高', value: 'HIGH' },
  { label: '中', value: 'MEDIUM' },
  { label: '低', value: 'LOW' },
]

function submitEdit() {
  if (!editForm.title?.trim()) return
  emit('action', 'edit', { edits: { ...editForm, title: editForm.title.trim() } })
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
      <span>{{ isStatusUpdate ? '确认状态更新' : '确认创建任务' }}</span>
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

    <template v-else-if='draft'>
      <a-descriptions v-if='!editing' :column='1' size='small'>
        <a-descriptions-item label='标题'>{{ draft.title }}</a-descriptions-item>
        <a-descriptions-item v-if='draft.description' label='描述'>
          {{ draft.description }}
        </a-descriptions-item>
        <a-descriptions-item v-if='draft.deadline' label='截止时间'>
          {{ draft.deadline }}
        </a-descriptions-item>
        <a-descriptions-item label='建议优先级'>
          {{ pending?.payload.ai_priority || '未设置' }}
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
        <a-form-item label='截止时间（ISO 8601，需含时区）'>
          <a-input v-model:value='editForm.deadline' placeholder='2026-08-07T23:59:00+08:00' />
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
          v-if='!isStatusUpdate'
          :disabled='loading'
          @click='regenerate'
        >
          重新生成
        </a-button>
        <a-button
          v-if='!isStatusUpdate'
          :disabled='loading'
          @click='editing = true'
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
