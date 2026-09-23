<script setup lang='ts'>
import { computed, ref, watch } from 'vue'

import { getTraceDetail } from '../api/agent'
import type {
  ToolExecutionStatus,
  TraceDetailResponse,
  TraceEvent,
  TraceEventType,
  TraceStatus,
} from '../types/agent'

const props = defineProps<{
  open: boolean
  traceId: string | null
  userId: string
}>()

const emit = defineEmits<{
  close: []
}>()

const detail = ref<TraceDetailResponse | null>(null)
const currentTraceId = ref<string | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
let requestVersion = 0

const sortedEvents = computed(() =>
  [...(detail.value?.events ?? [])].sort((left, right) => left.sequence - right.sequence),
)

const intentDecision = computed(() => {
  for (const event of sortedEvents.value) {
    const patch = event.metadata.output_patch
    if (!patch || typeof patch !== 'object' || Array.isArray(patch)) continue
    const intent = (patch as Record<string, unknown>).intent
    if (typeof intent !== 'string' || !intent) continue
    const confidence = (patch as Record<string, unknown>).intent_confidence
    return {
      intent,
      confidence: typeof confidence === 'number' ? confidence : null,
    }
  }
  return null
})

const modelCallCount = computed(() =>
  sortedEvents.value.filter((event) => event.event_type === 'MODEL_COMPLETED').length,
)

watch(
  () => [props.open, props.traceId, props.userId] as const,
  ([open, traceId]) => {
    if (!open || !traceId) return
    currentTraceId.value = traceId
    void loadTrace(traceId)
  },
  { immediate: true },
)

async function loadTrace(traceId: string) {
  const version = ++requestVersion
  loading.value = true
  error.value = null
  detail.value = null
  try {
    const response = await getTraceDetail(props.userId, traceId)
    if (version === requestVersion) detail.value = response
  } catch (reason) {
    if (version === requestVersion) {
      error.value = reason instanceof Error ? reason.message : '读取执行轨迹失败'
    }
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function openParentTrace() {
  const parentTraceId = detail.value?.trace.parent_trace_id
  if (!parentTraceId) return
  currentTraceId.value = parentTraceId
  void loadTrace(parentTraceId)
}

function formatTime(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(value))
}

function formatDuration(value: number | null) {
  if (value === null) return '—'
  if (value < 1000) return `${value} ms`
  return `${(value / 1000).toFixed(2)} s`
}

function formatPayload(value: Record<string, unknown> | null) {
  if (!value || Object.keys(value).length === 0) return '无'
  return JSON.stringify(value, null, 2)
}

const traceStatusLabels: Record<TraceStatus, string> = {
  RUNNING: '执行中',
  INTERRUPTED: '等待确认',
  SUCCEEDED: '成功',
  FAILED: '失败',
}

const eventLabels: Record<TraceEventType, string> = {
  REQUEST_STARTED: '请求开始',
  REQUEST_COMPLETED: '请求完成',
  NODE_STARTED: '节点开始',
  NODE_COMPLETED: '节点完成',
  MODEL_STARTED: '模型调用开始',
  MODEL_COMPLETED: '模型结构化返回',
  INTERRUPTED: '等待确认',
  RESUMED: '恢复执行',
  TOOL_STARTED: '工具开始',
  TOOL_COMPLETED: '工具完成',
  ERROR: '发生错误',
}

const toolStatusLabels: Record<ToolExecutionStatus, string> = {
  STARTED: '未完成',
  SUCCEEDED: '成功',
  FAILED: '失败',
}

function statusColor(status: TraceStatus | ToolExecutionStatus) {
  if (status === 'SUCCEEDED') return 'success'
  if (status === 'FAILED') return 'error'
  if (status === 'INTERRUPTED') return 'warning'
  return 'processing'
}

function eventColor(event: TraceEvent) {
  if (event.event_type === 'ERROR' || event.success === false) return 'red'
  if (event.event_type === 'INTERRUPTED') return 'orange'
  if (
    event.event_type === 'REQUEST_STARTED'
    || event.event_type === 'NODE_STARTED'
    || event.event_type === 'MODEL_STARTED'
    || event.event_type === 'TOOL_STARTED'
  ) {
    return 'blue'
  }
  return 'green'
}

const payloadLabels: Record<string, string> = {
  input: '输入参数',
  input_state: '节点输入 State',
  output: '完整返回结果',
  output_patch: '节点输出 State 补丁',
  error: '错误详情',
}

function eventPayloads(event: TraceEvent) {
  const preferredKeys = [
    'input',
    'input_state',
    'output',
    'output_patch',
    'error',
  ]
  return preferredKeys
    .filter((key) => key in event.metadata)
    .map((key) => ({
      key,
      label: event.event_type === 'MODEL_COMPLETED' && key === 'output'
        ? '模型返回 JSON'
        : payloadLabels[key],
      value: event.metadata[key],
    }))
}

function defaultEventPanels(event: TraceEvent) {
  if (event.event_type === 'REQUEST_STARTED') return ['input']
  if (event.event_type === 'MODEL_COMPLETED') return ['output']
  return []
}

function eventComponent(event: TraceEvent) {
  const component = event.metadata.component
  return typeof component === 'string' ? component : null
}

function eventAttempt(event: TraceEvent) {
  const attempt = event.metadata.attempt
  return typeof attempt === 'number' ? attempt : null
}

function formatAnyPayload(value: unknown) {
  if (value === null || value === undefined) return '无'
  return JSON.stringify(value, null, 2)
}
</script>

<template>
  <a-drawer
    :open='open'
    title='执行轨迹'
    placement='right'
    :width='720'
    root-class-name='trace-drawer'
    @close="emit('close')"
  >
    <div class='trace-current-id'>
      <span>Trace ID</span>
      <a-typography-paragraph copyable>{{ currentTraceId }}</a-typography-paragraph>
    </div>

    <a-spin :spinning='loading'>
      <a-alert
        v-if='error'
        type='error'
        show-icon
        :message='error'
      />

      <template v-if='detail'>
        <section class='trace-section'>
          <div class='trace-section-heading'>
            <h3>请求概览</h3>
            <a-tag :color='statusColor(detail.trace.status)'>
              {{ traceStatusLabels[detail.trace.status] }}
            </a-tag>
          </div>
          <a-descriptions size='small' bordered :column='1'>
            <a-descriptions-item label='请求类型'>
              {{ detail.trace.operation === 'confirm' ? '确认并恢复' : '对话请求' }}
            </a-descriptions-item>
            <a-descriptions-item label='开始时间'>
              {{ formatTime(detail.trace.started_at) }}
            </a-descriptions-item>
            <a-descriptions-item label='总耗时'>
              {{ formatDuration(detail.trace.duration_ms) }}
            </a-descriptions-item>
            <a-descriptions-item v-if='intentDecision' label='命中意图'>
              <a-tag color='geekblue'>{{ intentDecision.intent }}</a-tag>
              <span v-if='intentDecision.confidence !== null' class='trace-confidence'>
                置信度 {{ intentDecision.confidence }}
              </span>
            </a-descriptions-item>
            <a-descriptions-item label='模型调用'>
              {{ modelCallCount }} 次
            </a-descriptions-item>
            <a-descriptions-item label='线程 ID'>
              <a-typography-text copyable>{{ detail.trace.thread_id }}</a-typography-text>
            </a-descriptions-item>
            <a-descriptions-item label='请求 ID'>
              <a-typography-text copyable>{{ detail.trace.request_id }}</a-typography-text>
            </a-descriptions-item>
            <a-descriptions-item v-if='detail.trace.parent_trace_id' label='父轨迹'>
              <a-button type='link' size='small' @click='openParentTrace'>
                查看 {{ detail.trace.parent_trace_id.slice(0, 12) }}…
              </a-button>
            </a-descriptions-item>
            <a-descriptions-item v-if='detail.trace.error_code' label='错误码'>
              <a-typography-text type='danger' code>
                {{ detail.trace.error_code }}
              </a-typography-text>
            </a-descriptions-item>
          </a-descriptions>
        </section>

        <section class='trace-section'>
          <div class='trace-section-heading'>
            <h3>Graph 执行路径</h3>
            <span>{{ sortedEvents.length }} 个事件</span>
          </div>
          <a-empty v-if='sortedEvents.length === 0' description='没有记录到节点事件' />
          <a-timeline v-else class='trace-timeline'>
            <a-timeline-item
              v-for='(event, eventIndex) in sortedEvents'
              :key='event.event_id'
              :color='eventColor(event)'
            >
              <div class='trace-event-heading'>
                <strong>{{ eventLabels[event.event_type] }}</strong>
                <a-tag v-if='event.node_name'>{{ event.node_name }}</a-tag>
                <a-tag v-if='eventComponent(event)' color='purple'>
                  {{ eventComponent(event) }}
                </a-tag>
                <a-tag v-if='eventAttempt(event) !== null'>
                  第 {{ eventAttempt(event) }} 次
                </a-tag>
              </div>
              <div class='trace-event-meta'>
                <span>#{{ eventIndex + 1 }}</span>
                <span>{{ formatTime(event.started_at) }}</span>
                <span v-if='event.duration_ms !== null'>{{ formatDuration(event.duration_ms) }}</span>
                <span v-if='event.error_code' class='trace-error-code'>{{ event.error_code }}</span>
              </div>
              <a-collapse
                v-if='eventPayloads(event).length'
                class='trace-event-details'
                ghost
                :default-active-key='defaultEventPanels(event)'
              >
                <a-collapse-panel
                  v-for='payload in eventPayloads(event)'
                  :key='payload.key'
                  :header='payload.label'
                >
                  <pre class='trace-payload'>{{ formatAnyPayload(payload.value) }}</pre>
                </a-collapse-panel>
              </a-collapse>
              <pre
                v-else-if='Object.keys(event.metadata).length'
                class='trace-payload'
              >{{ formatPayload(event.metadata) }}</pre>
            </a-timeline-item>
          </a-timeline>
        </section>

        <section class='trace-section'>
          <div class='trace-section-heading'>
            <h3>工具执行</h3>
            <span>{{ detail.tool_executions.length }} 次调用</span>
          </div>
          <a-empty
            v-if='detail.tool_executions.length === 0'
            description='本次请求没有调用任务工具'
          />
          <div v-else class='tool-execution-list'>
            <a-card
              v-for='tool in detail.tool_executions'
              :key='tool.id'
              size='small'
              class='tool-execution-card'
            >
              <template #title>{{ tool.tool_name }}</template>
              <template #extra>
                <a-tag :color='statusColor(tool.status)'>
                  {{ toolStatusLabels[tool.status] }}
                </a-tag>
              </template>
              <div class='tool-execution-meta'>
                <span>耗时 {{ formatDuration(tool.duration_ms) }}</span>
                <span>{{ tool.confirmed ? '已确认' : '只读调用' }}</span>
                <span v-if='tool.idempotency_key'>包含幂等键</span>
              </div>
              <a-collapse ghost>
                <a-collapse-panel key='input' header='完整业务输入参数'>
                  <pre class='trace-payload'>{{ formatPayload(tool.input_payload) }}</pre>
                </a-collapse-panel>
                <a-collapse-panel key='output' header='完整业务返回结果'>
                  <pre class='trace-payload'>{{ formatPayload(tool.output_payload) }}</pre>
                </a-collapse-panel>
              </a-collapse>
              <a-alert
                v-if='tool.error_code || tool.error_message'
                type='error'
                show-icon
                :message='tool.error_message || tool.error_code || "工具执行失败"'
                :description='tool.error_code || undefined'
              />
            </a-card>
          </div>
        </section>
      </template>
    </a-spin>
  </a-drawer>
</template>
