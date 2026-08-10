<script setup lang='ts'>
import { ref } from 'vue'

const props = defineProps<{
  loading: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  send: [message: string]
}>()

const message = ref('')

function submit() {
  if (props.disabled || props.loading) return
  const value = message.value.trim()
  if (!value) return
  message.value = ''
  emit('send', value)
}
</script>

<template>
  <div class='composer'>
    <a-textarea
      v-model:value='message'
      :auto-size='{ minRows: 2, maxRows: 5 }'
      :disabled='disabled || loading'
      placeholder='例如：下周五前完成论文实验修改'
      @keydown.enter.exact.prevent='submit'
    />
    <div class='composer-footer'>
      <span>Enter 发送，Shift + Enter 换行</span>
      <a-button
        type='primary'
        :loading='loading'
        :disabled='disabled || !message.trim()'
        @click='submit'
      >
        发送
      </a-button>
    </div>
  </div>
</template>
