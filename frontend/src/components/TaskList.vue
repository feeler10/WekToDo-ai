<script setup lang='ts'>
import { computed, ref } from 'vue'

import type { Task, TaskPriority, TaskStatus } from '../types/agent'

const props = defineProps<{
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

const priorityLabels: Record<TaskPriority, string> = {
  URGENT: '紧急',
  HIGH: '高优先级',
  MEDIUM: '中优先级',
  LOW: '低优先级',
}

const priorityColors: Record<TaskPriority, string> = {
  URGENT: 'red',
  HIGH: 'orange',
  MEDIUM: 'blue',
  LOW: 'default',
}

const transitions: Record<TaskStatus, TaskStatus[]> = {
  TODO: ['DOING', 'CANCELLED'],
  DOING: ['DONE', 'BLOCKED'],
  BLOCKED: ['DOING'],
  DONE: ['DOING'],
  CANCELLED: [],
}

const expandedTaskIds = ref<string[]>([])

const rootTasks = computed(() =>
  props.tasks.filter((task) => task.parent_id === null),
)

const childrenByParent = computed(() => {
  const grouped = new Map<string, Task[]>()
  for (const task of props.tasks) {
    if (!task.parent_id) continue
    const children = grouped.get(task.parent_id) || []
    children.push(task)
    grouped.set(task.parent_id, children)
  }
  for (const children of grouped.values()) {
    children.sort((left, right) => {
      const orderDifference =
        (left.subtask_order ?? Number.MAX_SAFE_INTEGER) -
        (right.subtask_order ?? Number.MAX_SAFE_INTEGER)
      if (orderDifference !== 0) return orderDifference
      return left.created_at.localeCompare(right.created_at)
    })
  }
  return grouped
})

function childrenFor(taskId: string) {
  return childrenByParent.value.get(taskId) || []
}

function hasChildren(taskId: string) {
  return childrenFor(taskId).length > 0
}

function isExpanded(taskId: string) {
  return expandedTaskIds.value.includes(taskId)
}

function toggleTask(taskId: string) {
  if (!hasChildren(taskId)) return
  expandedTaskIds.value = isExpanded(taskId)
    ? expandedTaskIds.value.filter((id) => id !== taskId)
    : [...expandedTaskIds.value, taskId]
}

function completedChildren(taskId: string) {
  return childrenFor(taskId).filter((task) => task.status === 'DONE').length
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


function priorityLabel(task: Task) {
  return task.effective_priority
    ? priorityLabels[task.effective_priority]
    : null
}
function priorityColor(task: Task) {
  return task.effective_priority
    ? priorityColors[task.effective_priority]
    : 'default'
}


function handleStatusChange(task: Task, value: unknown) {
  if (typeof value === 'string' && value in statusLabels) {
    emit('updateStatus', task, value as TaskStatus)
  }
}

function formatDeadline(value: string | null) {
  return value
    ? `${new Date(value).toLocaleString('zh-CN', {
        timeZone: 'Asia/Shanghai',
        hour12: false,
      })}（北京时间）`
    : '无截止时间'
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

    <a-empty v-if='rootTasks.length === 0' description='查询后将在这里显示任务' />
    <a-list v-else :data-source='rootTasks' item-layout='vertical'>
      <template #renderItem='{ item }'>
        <a-list-item class='task-item'>
          <div
            class='task-summary'
            :class='{ "task-summary-expandable": hasChildren(item.id) }'
            :role='hasChildren(item.id) ? "button" : undefined'
            :tabindex='hasChildren(item.id) ? 0 : undefined'
            :aria-expanded='hasChildren(item.id) ? isExpanded(item.id) : undefined'
            @click='toggleTask(item.id)'
            @keydown.enter.prevent='toggleTask(item.id)'
            @keydown.space.prevent='toggleTask(item.id)'
          >
            <div class='task-title-row'>
              <div class='task-title-main'>
                <span
                  v-if='hasChildren(item.id)'
                  class='task-expand-icon'
                  aria-hidden='true'
                >{{ isExpanded(item.id) ? '⌄' : '›' }}</span>
                <a-typography-text strong>{{ item.title }}</a-typography-text>
              </div>
              <div class='task-tags'>
                <a-tag
                  v-if='priorityLabel(item)'
                  :color='priorityColor(item)'
                >{{ priorityLabel(item) }}</a-tag>
                <a-tag :color='statusColor(item)'>
                  {{ statusLabel(item) }}
                </a-tag>
              </div>
            </div>
            <div v-if='hasChildren(item.id)' class='task-children-overview'>
              <span>
                {{ completedChildren(item.id) }}/{{ childrenFor(item.id).length }} 个子任务已完成
              </span>
              <a-progress
                :percent='item.progress'
                :show-info='false'
                size='small'
              />
            </div>
            <p class='task-meta'>{{ formatDeadline(item.deadline) }}</p>
            <a-select
              v-if='optionsFor(item).length'
              size='small'
              placeholder='更新状态'
              :disabled='loading'
              :options='optionsFor(item)'
              @click.stop
              @keydown.stop
              @change='(value: unknown) => handleStatusChange(item, value)'
            />
          </div>

          <div
            v-if='hasChildren(item.id) && isExpanded(item.id)'
            class='task-children'
          >
            <article
              v-for='child in childrenFor(item.id)'
              :key='child.id'
              class='task-child'
            >
              <div class='task-title-row'>
                <div class='task-title-main'>
                  <span class='task-child-order'>{{ child.subtask_order }}</span>
                  <a-typography-text strong>{{ child.title }}</a-typography-text>
                </div>
                <a-tag :color='statusColor(child)'>
                  {{ statusLabel(child) }}
                </a-tag>
              </div>
              <p v-if='child.description' class='task-child-description'>
                {{ child.description }}
              </p>
              <p class='task-meta'>{{ formatDeadline(child.deadline) }}</p>
              <a-select
                v-if='optionsFor(child).length'
                size='small'
                placeholder='更新子任务状态'
                :disabled='loading'
                :options='optionsFor(child)'
                @change='(value: unknown) => handleStatusChange(child, value)'
              />
            </article>
          </div>
        </a-list-item>
      </template>
    </a-list>
  </section>
</template>
