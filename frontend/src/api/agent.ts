import type {
  AgentChatRequest,
  AgentConfirmRequest,
  AgentResponse,
  ConversationHistoryResponse,
} from '../types/agent'

interface ErrorEnvelope {
  error?: {
    message?: string
  }
}

async function post<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  const data = (await response.json()) as T & ErrorEnvelope
  if (!response.ok) {
    throw new Error(data.error?.message || '请求失败，请稍后重试')
  }
  return data
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path)
  const data = (await response.json()) as T & ErrorEnvelope
  if (!response.ok) {
    throw new Error(data.error?.message || '请求失败，请稍后重试')
  }
  return data
}

export function sendAgentMessage(payload: AgentChatRequest) {
  return post<AgentResponse>('/api/agent/chat', payload)
}

export function confirmAgentAction(payload: AgentConfirmRequest) {
  return post<AgentResponse>('/api/agent/confirm', payload)
}

export function getConversationHistory(userId: string, conversationId: string) {
  const encodedConversationId = encodeURIComponent(conversationId)
  const query = new URLSearchParams({ user_id: userId })
  return get<ConversationHistoryResponse>(
    `/api/agent/conversations/${encodedConversationId}?${query.toString()}`,
  )
}
