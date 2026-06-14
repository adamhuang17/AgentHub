export type AgentHubStatusCode =
  | "not_connected"
  | "waiting_for_backend"
  | "no_runtime_result"
  | "api_unreachable"
  | "api_connected"
  | "request_failed"

export interface AgentHubHealth {
  status: string
  version?: string
  local_demo?: Record<string, unknown>
}

export interface AgentProfile {
  id: string
  name: string
  provider?: string | null
  adapter_kind?: string | null
  avatar?: string | null
  avatar_url?: string | null
  initials?: string | null
  capability_tags: string[]
  enabled: boolean
  execution_enabled?: boolean
  configured?: boolean
  health_status?: string | null
  runtime_status?: string | null
  error_code?: string | null
  recovery_hint?: string | null
  system_prompt?: string | null
  model?: string | null
  api_base?: string | null
  executable_path?: string | null
  kind?: string | null
}

export interface Conversation {
  id: string
  title: string
  mode: "private" | "group" | "single" | "private_agent" | "group_agent" | string
  status: string
  created_at: string
  updated_at: string
  last_active_at: string
  archived_at?: string | null
}

export interface MentionPayload {
  agent_id: string
  display?: string
}

export interface ArtifactCardData {
  card_type?: string
  artifact_id: string
  diff_artifact_id?: string
  title: string
  type: string
  status: string
  mime_type?: string
  version?: number
  checksum?: string
  additions?: number
  deletions?: number
}

export interface Message {
  id: string
  conversation_id: string
  sender_type: "user" | "assistant" | "orchestrator" | string
  sender_id: string
  message_type: string
  content: {
    text?: string
    final_content?: string
    thinking_content?: string
    raw_content?: string
    content_state?: string
    cleanup_method?: string
    cleanup_applied?: boolean
    output_validation?: Record<string, unknown>
    error_code?: string
    run_id?: string
    [key: string]: unknown
  }
  mentions: MentionPayload[]
  references: Array<Record<string, unknown>>
  reply_to_id?: string | null
  created_by_run_id?: string | null
  created_at: string
  artifact_cards?: ArtifactCardData[]
  artifact_card?: ArtifactCardData
  diff_cards?: ArtifactCardData[]
  diff_card?: ArtifactCardData
}

export interface PlanStep {
  id: string
  kind: "analysis" | "implementation" | "review" | "deploy" | string
  title?: string
  instruction?: string
  assigned_agent_id?: string | null
  status: string
  dispatch_source?: string
  dispatch_reason?: string
  blocked_reason?: string | null
  depends_on?: string[]
  expected_output?: Record<string, unknown>
}

export interface OrchestratorTask {
  id: string
  conversation_id: string
  goal: string
  status: string
  plan?: {
    id: string
    status: string
    steps: PlanStep[]
  }
  steps?: PlanStep[]
  runs?: AgentRun[]
}

export interface AgentRun {
  id: string
  run_id?: string
  conversation_id: string
  target_agent_id: string
  run_mode: string
  status: string
  error_code?: string | null
  created_at?: string
  updated_at?: string
}

export interface ErrorCard {
  card_type: string
  error_code: string
  message: string
  recovery_hint?: string | null
  target_agent_id?: string
  run_id?: string
}

export interface SendMessageResponse extends Message {
  message: Message
  assistant_message?: Message | null
  assistant_messages?: Message[]
  error_message?: Message | null
  error_messages?: Message[]
  agent_run?: AgentRun | null
  agent_runs?: AgentRun[]
  task?: OrchestratorTask | null
  error_card?: ErrorCard | null
  error_cards?: ErrorCard[]
  dispatch_path?: string
  selected_agent_effective?: Record<string, unknown> | null
}

export interface Artifact {
  id: string
  conversation_id: string
  type: string
  title: string
  status: string
  mime_type: string
  uri?: string
  created_by_run_id?: string | null
  created_at?: string
  version_id?: string
  current_version_id?: string
  checksum?: string
}

export interface ArtifactPreview {
  artifact_id: string
  preview_type: "text" | "structured_diff" | "office_document" | string
  type: string
  mime_type: string
  status: string
  version?: number
  version_id?: string
  checksum?: string
  read_only?: boolean
  content?: string
  files?: DiffFilePreview[]
  hunks?: DiffHunkPreview[]
  additions?: number
  deletions?: number
  error_code?: string
}

export interface DiffFilePreview {
  path?: string
  old_path?: string
  new_path?: string
  status?: string
  additions?: number
  deletions?: number
  hunks?: DiffHunkPreview[]
  unified_diff?: string
}

export interface DiffHunkPreview {
  file_path?: string
  path?: string
  header?: string
  lines?: DiffLinePreview[]
}

export interface DiffLinePreview {
  type?: "context" | "addition" | "deletion" | string
  content?: string
  old_line?: number | null
  new_line?: number | null
}

export interface DeploymentRelease {
  id: string
  artifact_id: string
  artifact_version_id: string
  provider: string
  status: "created" | "publishing" | "published" | "failed" | string
  url?: string | null
  error_code?: string | null
  created_at?: string
  published_at?: string | null
}

export interface CreateAgentInput {
  name: string
  avatar?: string | null
  system_prompt: string
  capability_tags: string[]
  provider: string
  model?: string | null
  api_base?: string | null
  api_key?: string | null
  executable_path?: string | null
  adapter_kind?: string | null
  kind?: string
  agent_type?: "custom_cloud" | "local_cli"
  connection_test_required?: boolean
}
