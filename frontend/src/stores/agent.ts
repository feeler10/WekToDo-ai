import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { confirmAgentAction, sendAgentMessage } from '../api/agent'
import type {
  AgentResponse,
  ChatMessage,
  ConfirmationAction,
  ConfirmationOptions,
  Task,
  TaskStatus,
} from '../types/agent'

const actionLabels: Record<ConfirmationAction, string> = {
  approve: '确认执行',
  edit: '提交编辑',
  reject: '取消操作',
  regenerate: '重新生成',
}

const statusCommands: Record<TaskStatus, string> = {
  TODO: '待办',
  DOING: '进行中',
  DONE: '完成',
  BLOCKED: '阻塞',
  CANCELLED: '取消',
}

export const useAgentStore = defineStore('agent', () => {
  const userId = ref('demo-user')
  const threadId = ref(crypto.randomUUID())
  const messages = ref<ChatMessage[]>([])
  const tasks = ref<Task[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const pendingResponse = ref<AgentResponse | null>(null)

  const hasMessages = computed(() => messages.value.length > 0)

  function addAgentResponse(response: AgentResponse) {
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'agent',
      content: response.message,
      response,
    })
    pendingResponse.value =
      response.status === 'awaiting_confirmation' ? response : null
    mergeTasks(response)
  }

  function mergeTasks(response: AgentResponse) {
    if (response.tasks.length > 0) {
      tasks.value = response.tasks
    }
    const deletedIds = new Set([
      ...response.deleted_task_ids,
      ...(response.deleted_task_id ? [response.deleted_task_id] : []),
    ])
    if (deletedIds.size > 0) {
      tasks.value = tasks.value.filter(
        (task) => !deletedIds.has(task.id),
      )
    }
    const changedTasks = [
      response.parent_task,
      response.task,
      ...response.subtasks,
      ...response.parent_tasks,
    ].filter((task): task is Task => Boolean(task))
    for (const responseTask of changedTasks) {
      const index = tasks.value.findIndex((task) => task.id === responseTask.id)
      if (index >= 0) {
        tasks.value.splice(index, 1, responseTask)
      } else {
        tasks.value.unshift(responseTask)
      }
    }
  }

  async function sendMessage(content: string) {
    const message = content.trim()
    if (!message || loading.value) return
    error.value = null
    loading.value = true
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'user',
      content: message,
    })
    try {
      const response = await sendAgentMessage({
        user_id: userId.value,
        thread_id: threadId.value,
        request_id: crypto.randomUUID(),
        message,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
      })
      addAgentResponse(response)
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : '未知错误'
    } finally {
      loading.value = false
    }
  }

  async function respondToPending(
    action: ConfirmationAction,
    options?: ConfirmationOptions,
  ) {
    const pending = pendingResponse.value?.pending_action
    if (!pending || loading.value) return
    error.value = null
    loading.value = true
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'user',
      content: actionLabels[action],
    })
    try {
      const response = await confirmAgentAction({
        user_id: userId.value,
        thread_id: pending.thread_id,
        action_id: pending.id,
        action,
        ...options,
      })
      addAgentResponse(response)
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : '未知错误'
    } finally {
      loading.value = false
    }
  }

  function requestStatusUpdate(task: Task, targetStatus: TaskStatus) {
    return sendMessage(
      '把 ' + task.id + ' 标记为' + statusCommands[targetStatus],
    )
  }

  function refreshTasks() {
    return sendMessage('查询我的任务')
  }

  function clearError() {
    error.value = null
  }

  return {
    userId,
    threadId,
    messages,
    tasks,
    loading,
    error,
    pendingResponse,
    hasMessages,
    sendMessage,
    respondToPending,
    requestStatusUpdate,
    refreshTasks,
    clearError,
  }
})
