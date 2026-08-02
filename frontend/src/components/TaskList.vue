<script setup lang='ts'>
import type { Task, TaskStatus } from '../types/agent'

defineProps<{
  tasks: Task[]
  loading: boolean
}>()

const emit = defineEmits<{
  refresh: []
  updateStatus: [task: Task, status: TaskStatus]
}>()

const statusLabels: Record<TaskStatus, string> = {
  TODO: '待办',
  DOING: '进行中',
  DONE: '已完成',
  BLOCKED: '已阻塞',
  CANCELLED: '已取消',
}

const statusColors: Record<TaskStatus, string> = {
  TODO: 'default',
  DOING: 'processing',
  DONE: 'success',
  BLOCKED: 'warning',
  CANCELLED: 'error',
}

const transitions: Record<TaskStatus, TaskStatus[]> = {
  TODO: ['DOING', 'CANCELLED'],
  DOING: ['DONE', 'BLOCKED'],
  BLOCKED: ['DOING'],
  DONE: ['DOING'],
  CANCELLED: [],
}

function optionsFor(task: Task) {
  return transitions[task.status].map((status) => ({
    label: statusLabels[status],
    value: status,
  }))
}

function statusLabel(task: Task) {
  return statusLabels[task.status]
}

function statusColor(task: Task) {
  return statusColors[task.status]
}

function handleStatusChange(task: Task, value: unknown) {
  if (typeof value === 'string' && value in statusLabels) {
    emit('updateStatus', task, value as TaskStatus)
  }
}

function formatDeadline(value: string | null) {
  return value ? new Date(value).toLocaleString() : '无截止时间'
}

function refresh() {
  emit('refresh')
}
</script>

<template>
  <section class='task-panel'>
    <div class='task-panel-header'>
      <div>
        <span class='eyebrow'>真实任务数据</span>
        <h2>任务列表</h2>
      </div>
      <a-button size='small' :loading='loading' @click='refresh'>刷新</a-button>
    </div>

    <a-empty v-if='tasks.length === 0' description='查询后将在这里显示任务' />
    <a-list v-else :data-source='tasks' item-layout='vertical'>
      <template #renderItem='{ item }'>
        <a-list-item class='task-item'>
          <div class='task-title-row'>
            <a-typography-text strong>{{ item.title }}</a-typography-text>
            <a-tag :color='statusColor(item)'>
              {{ statusLabel(item) }}
            </a-tag>
          </div>
          <p class='task-meta'>{{ formatDeadline(item.deadline) }}</p>
          <a-select
            v-if='optionsFor(item).length'
            size='small'
            placeholder='更新状态'
            :disabled='loading'
            :options='optionsFor(item)'
            @change='(value: unknown) => handleStatusChange(item, value)'
          />
        </a-list-item>
      </template>
    </a-list>
  </section>
</template>
