<script setup lang='ts'>
import { nextTick, ref, watch } from 'vue'

import ConfirmationCard from './ConfirmationCard.vue'
import type {
  ChatMessage,
  ConfirmationAction,
  ConfirmationOptions,
} from '../types/agent'

const props = defineProps<{
  messages: ChatMessage[]
  loading: boolean
  activeActionId: string | null
}>()

const emit = defineEmits<{
  action: [
    action: ConfirmationAction,
    options?: ConfirmationOptions,
  ]
}>()

const container = ref<HTMLElement | null>(null)

watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    container.value?.scrollTo({
      top: container.value.scrollHeight,
      behavior: 'smooth',
    })
  },
)

function forwardAction(
  action: ConfirmationAction,
  options?: ConfirmationOptions,
) {
  emit('action', action, options)
}
</script>

<template>
  <div ref='container' class='message-list'>
    <div v-if='messages.length === 0' class='empty-conversation'>
      <div class='empty-mark'>W</div>
      <h2>告诉我你想完成什么</h2>
      <p>可以创建、查询任务，或用自然语言更新任务状态。</p>
    </div>

    <article
      v-for='message in messages'
      :key='message.id'
      class='message-row'
      :class='message.role'
    >
      <div class='message-avatar'>{{ message.role === 'user' ? '你' : 'W' }}</div>
      <div class='message-content'>
        <div class='message-label'>{{ message.role === 'user' ? '你' : 'WekToDo Agent' }}</div>
        <div class='message-bubble'>{{ message.content }}</div>

        <a-list
          v-if='message.response?.candidates.length'
          class='candidate-list'
          size='small'
          bordered
          :data-source='message.response.candidates'
        >
          <template #header>找到多个候选，请使用任务 ID 再试一次</template>
          <template #renderItem='{ item }'>
            <a-list-item>
              <a-typography-text strong>{{ item.title }}</a-typography-text>
              <a-typography-text code>{{ item.id }}</a-typography-text>
            </a-list-item>
          </template>
        </a-list>

        <ConfirmationCard
          v-if='
            message.response?.pending_action?.id === activeActionId
          '
          :response='message.response'
          :loading='loading'
          @action='forwardAction'
        />
        <a-tag
          v-else-if='message.response?.pending_action'
          class='resolved-action'
          color='default'
        >
          此确认操作已处理
        </a-tag>
      </div>
    </article>

    <div v-if='loading' class='agent-typing'>
      <a-spin size='small' />
      <span>Agent 正在处理…</span>
    </div>
  </div>
</template>
