<script setup lang='ts'>
import { onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'

import ChatComposer from '../components/ChatComposer.vue'
import ChatMessageList from '../components/ChatMessageList.vue'
import TaskList from '../components/TaskList.vue'
import TraceDrawer from '../components/TraceDrawer.vue'
import { useAgentStore } from '../stores/agent'
import type {
  ConfirmationAction,
  ConfirmationOptions,
  Task,
  TaskStatus,
} from '../types/agent'

const store = useAgentStore()
const {
  userId,
  threadId,
  messages,
  tasks,
  loading,
  error,
  pendingResponse,
  hasMessages,
} = storeToRefs(store)

const quickPrompts = [
  '查询我的任务',
  '今天有哪些任务？',
  '有哪些逾期任务？',
]
const traceDrawerOpen = ref(false)
const selectedTraceId = ref<string | null>(null)

onMounted(() => {
  void store.initializeConversation()
})

function handleAction(
  action: ConfirmationAction,
  options?: ConfirmationOptions,
) {
  void store.respondToPending(action, options)
}

function updateStatus(task: Task, status: TaskStatus) {
  void store.requestStatusUpdate(task, status)
}

function showTrace(traceId: string) {
  selectedTraceId.value = traceId
  traceDrawerOpen.value = true
}
</script>

<template>
  <div class='app-shell'>
    <header class='topbar'>
      <div class='brand'>
        <div class='brand-mark'>W</div>
        <div>
          <strong>WekToDo</strong>
          <span>Task Agent</span>
        </div>
      </div>
      <div class='session-info'>
        <a-input
          v-model:value='userId'
          size='small'
          aria-label='用户 ID'
          :disabled='loading || Boolean(pendingResponse)'
          @change='store.switchUser'
        />
        <a-tag color='blue'>线程 {{ threadId.slice(0, 8) }}</a-tag>
      </div>
    </header>

    <main class='workspace'>
      <section class='chat-panel'>
        <div class='chat-heading'>
          <div>
            <span class='eyebrow'>Agent 对话</span>
            <h1>把目标变成可执行任务</h1>
          </div>
          <a-badge status='success' text='FastAPI 已连接时可用' />
        </div>

        <a-alert
          v-if='error'
          class='error-alert'
          type='error'
          show-icon
          closable
          :message='error'
          @close='store.clearError'
        />

        <div v-if='!hasMessages' class='quick-prompts'>
          <a-button
            v-for='prompt in quickPrompts'
            :key='prompt'
            :disabled='loading'
            @click='store.sendMessage(prompt)'
          >
            {{ prompt }}
          </a-button>
        </div>

        <ChatMessageList
          :messages='messages'
          :loading='loading'
          :active-action-id='pendingResponse?.pending_action?.id || null'
          @action='handleAction'
          @trace='showTrace'
        />

        <div v-if='pendingResponse' class='pending-hint'>
          请先处理当前确认卡片，再发送新消息。
        </div>
        <ChatComposer
          :loading='loading'
          :disabled='Boolean(pendingResponse)'
          @send='store.sendMessage'
        />
      </section>

      <TaskList
        :tasks='tasks'
        :loading='loading'
        @refresh='store.refreshTasks'
        @update-status='updateStatus'
      />
    </main>

    <TraceDrawer
      :open='traceDrawerOpen'
      :trace-id='selectedTraceId'
      :user-id='userId'
      @close='traceDrawerOpen = false'
    />
  </div>
</template>
