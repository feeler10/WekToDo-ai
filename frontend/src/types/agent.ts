export type TaskStatus = 'TODO' | 'DOING' | 'DONE' | 'BLOCKED' | 'CANCELLED'
export type TaskPriority = 'URGENT' | 'HIGH' | 'MEDIUM' | 'LOW'
export type ConfirmationAction = 'approve' | 'edit' | 'reject' | 'regenerate'

export interface TaskDraft {
  title: string
  description: string
  category: string | null
  deadline: string | null
  estimated_minutes: number | null
  semantic_importance: number
  impact_score: number
  deadline_score: number
  workload_risk_score: number
  dependency_score: number
  priority_reason: string | null
}

export interface TaskDraftEdit {
  title?: string
  description?: string
  category?: string | null
  deadline?: string | null
  estimated_minutes?: number | null
  user_priority?: TaskPriority | null
}

export interface PendingAction {
  id: string
  user_id: string
  thread_id: string
  action_type: string
  target_id: string | null
  payload: Record<string, unknown>
  confirmation_status: 'pending' | 'approved' | 'rejected' | 'cancelled'
  idempotency_key: string
  created_at: string
  expires_at: string
}

export interface Task {
  id: string
  user_id: string
  parent_id: string | null
  title: string
  description: string
  category: string | null
  status: TaskStatus
  deadline: string | null
  estimated_minutes: number | null
  actual_minutes: number | null
  ai_priority: TaskPriority | null
  user_priority: TaskPriority | null
  effective_priority: TaskPriority | null
  priority_source: 'ai' | 'user' | null
  urgency_score: number | null
  priority_reason: string | null
  progress: number
  is_ai_generated: boolean
  created_at: string
  updated_at: string
  completed_at: string | null
  version: number
}

export interface AgentResponse {
  status: string
  thread_id: string
  message: string
  pending_action: PendingAction | null
  task_draft: TaskDraft | null
  task: Task | null
  tasks: Task[]
  candidates: Task[]
}

export interface AgentChatRequest {
  user_id: string
  thread_id: string
  message: string
  timezone: string
  request_id: string
}

export interface AgentConfirmRequest {
  user_id: string
  thread_id: string
  action_id: string
  action: ConfirmationAction
  edits?: TaskDraftEdit
  feedback?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'agent'
  content: string
  response?: AgentResponse
}
