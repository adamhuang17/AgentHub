import type {
  AgentHubHealth,
  AgentProfile,
  AgentRun,
  Artifact,
  ArtifactPreview,
  Conversation,
  CreateAgentInput,
  DeploymentRelease,
  ErrorCard,
  MentionPayload,
  Message,
  SendMessageResponse,
} from "@/agenthub/types"

export class AgentHubApiError extends Error {
  readonly error_code: string
  readonly status?: number
  readonly recovery_hint?: string
  readonly payload?: unknown

  constructor(input: {
    error_code: string
    message: string
    status?: number
    recovery_hint?: string
    payload?: unknown
  }) {
    super(input.message)
    this.name = "AgentHubApiError"
    this.error_code = input.error_code
    this.status = input.status
    this.recovery_hint = input.recovery_hint
    this.payload = input.payload
  }
}

type ListEnvelope<T> = { items?: T[] }

export class AgentHubClient {
  readonly baseUrl: string
  readonly testRunId?: string

  constructor(baseUrl = defaultAgentHubBaseUrl(), testRunId = defaultTestRunId()) {
    this.baseUrl = baseUrl.replace(/\/+$/, "")
    this.testRunId = testRunId
  }

  health() {
    return this.request<AgentHubHealth>("/health")
  }

  async agents() {
    return this.items<AgentProfile>("/api/agents")
  }

  async conversations() {
    return this.items<Conversation>("/api/conversations")
  }

  createConversation(input: { title: string; mode: "private" | "single" | "group"; agent_ids?: string[] }) {
    return this.request<Conversation>("/api/conversations", {
      method: "POST",
      body: input,
    })
  }

  updateConversation(conversationId: string, input: { title: string }) {
    return this.request<Conversation>(`/api/conversations/${encodeURIComponent(conversationId)}`, {
      method: "PATCH",
      body: input,
    })
  }

  deleteConversation(conversationId: string) {
    return this.request<Conversation>(`/api/conversations/${encodeURIComponent(conversationId)}`, {
      method: "DELETE",
    })
  }

  async messages(conversationId: string) {
    return this.items<Message>(`/api/conversations/${encodeURIComponent(conversationId)}/messages`)
  }

  sendMessage(
    conversationId: string,
    input: {
      text: string
      mentions: MentionPayload[]
      orchestrate: boolean
      selected_agent_id?: string | null
      force_agent?: boolean
      source_surface?: string
    },
  ) {
    return this.request<SendMessageResponse>(`/api/conversations/${encodeURIComponent(conversationId)}/messages`, {
      method: "POST",
      body: {
        message_type: "text",
        content: { text: input.text },
        mentions: input.mentions,
        references: [],
        orchestrate: input.orchestrate,
        auto_orchestrate: input.orchestrate,
        selected_agent_id: input.selected_agent_id || undefined,
        force_agent: input.force_agent || undefined,
        source_surface: input.source_surface || undefined,
      },
    })
  }

  /**
   * Send a multi-agent message and receive results as an SSE stream.
   * Each agent's result is delivered as a separate SSE event, so the
   * UI can render them incrementally instead of waiting for all agents.
   */
  sendMessageStream(
    conversationId: string,
    input: {
      text: string
      mentions: MentionPayload[]
      orchestrate: boolean
      selected_agent_id?: string | null
      force_agent?: boolean
      source_surface?: string
    },
    callbacks: {
      onStepStarted?: (data: { step_index: number; agent_id: string; agent_name?: string; total_steps: number }) => void
      onAgentResult?: (data: { assistant_message?: Message | null; agent_run?: AgentRun | null; error_card?: ErrorCard | null; step_index: number; agent_id: string }) => void
      onAgentError?: (data: { error_card: ErrorCard; step_index: number; agent_id?: string }) => void
      onDone?: (response: SendMessageResponse) => void
      onError?: (error: Error) => void
    },
  ) {
    const url = `${this.baseUrl}/api/conversations/${encodeURIComponent(conversationId)}/messages`
    const body = {
      message_type: "text",
      content: { text: input.text },
      mentions: input.mentions,
      references: [],
      orchestrate: input.orchestrate,
      auto_orchestrate: input.orchestrate,
      selected_agent_id: input.selected_agent_id || undefined,
      force_agent: input.force_agent || undefined,
      source_surface: input.source_surface || undefined,
    }
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    }
    if (this.testRunId) headers["X-AgentHub-Test-Run"] = this.testRunId

    return fetch(url, { method: "POST", headers, body: JSON.stringify(body) })
      .then((response) => {
        if (!response.ok || !response.body) {
          callbacks.onError?.(new Error(`HTTP ${response.status}`))
          return
        }
        const contentType = response.headers.get("Content-Type") || ""
        if (!contentType.toLowerCase().includes("text/event-stream")) {
          return response
            .json()
            .then((payload) => callbacks.onDone?.(payload as SendMessageResponse))
            .catch((error) => callbacks.onError?.(error instanceof Error ? error : new Error(String(error))))
        }
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ""
        let completed = false

        function processChunk(chunk: string) {
          buffer += chunk
          const parts = buffer.split("\n\n")
          buffer = parts.pop() || ""

          for (const part of parts) {
            const lines = part.split(/\r?\n/)
            let eventType = ""
            let dataStr = ""
            for (const rawLine of lines) {
              const line = rawLine.trimEnd()
              if (line.startsWith("event:")) {
                eventType = line.slice(6).trim()
              } else if (line.startsWith("data:")) {
                dataStr += line.slice(5).trimStart()
              }
            }
            if (!eventType || !dataStr) continue

            try {
              const data = JSON.parse(dataStr) as Record<string, unknown>
              switch (eventType) {
                case "step_started":
                  callbacks.onStepStarted?.(data as Parameters<NonNullable<typeof callbacks.onStepStarted>>[0])
                  break
                case "agent_result":
                  callbacks.onAgentResult?.(data as Parameters<NonNullable<typeof callbacks.onAgentResult>>[0])
                  break
                case "agent_error":
                  callbacks.onAgentError?.(data as Parameters<NonNullable<typeof callbacks.onAgentError>>[0])
                  break
                case "done":
                  completed = true
                  callbacks.onDone?.(data as unknown as SendMessageResponse)
                  break
              }
            } catch {
              // ignore parse errors for individual events
            }
          }
        }

        function readLoop(): Promise<void> {
          return reader.read().then(({ done, value }) => {
            if (done) {
              const tail = decoder.decode()
              if (tail) processChunk(tail)
              if (buffer.trim()) processChunk("\n\n")
              if (!completed) callbacks.onError?.(new Error("SSE stream ended before done event"))
              return
            }
            processChunk(decoder.decode(value, { stream: true }))
            return readLoop()
          })
        }

        readLoop().catch((err) => callbacks.onError?.(err))
      })
      .catch((err) => callbacks.onError?.(err))
  }

  async artifacts(conversationId?: string) {
    const suffix = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ""
    return this.items<Artifact>(`/api/artifacts${suffix}`)
  }

  artifact(artifactId: string) {
    return this.request<Artifact>(`/api/artifacts/${encodeURIComponent(artifactId)}`)
  }

  previewArtifact(artifactId: string) {
    return this.request<ArtifactPreview>(`/api/artifacts/${encodeURIComponent(artifactId)}/preview`, {
      method: "POST",
      body: {},
    })
  }

  deployArtifact(artifactId: string, provider = "static_host") {
    return this.request<DeploymentRelease>(`/api/artifacts/${encodeURIComponent(artifactId)}/deploy`, {
      method: "POST",
      body: { provider },
    })
  }

  artifactDownloadUrl(artifactId: string) {
    return `${this.baseUrl}/api/artifacts/${encodeURIComponent(artifactId)}/download`
  }

  createAgent(input: CreateAgentInput) {
    return this.request<AgentProfile>("/api/agents", {
      method: "POST",
      body: { ...input },
    })
  }

  updateAgent(agentId: string, input: CreateAgentInput) {
    return this.request<AgentProfile>(`/api/agents/${encodeURIComponent(agentId)}`, {
      method: "PATCH",
      body: { ...input },
    })
  }

  deleteAgent(agentId: string) {
    return this.request<{ id: string; deleted: boolean }>(`/api/agents/${encodeURIComponent(agentId)}`, {
      method: "DELETE",
    })
  }

  retryRun(runId: string) {
    return this.request<AgentRun>(`/api/runs/${encodeURIComponent(runId)}/retry`, {
      method: "POST",
      body: {},
    })
  }

  private async items<T>(path: string) {
    const payload = await this.request<ListEnvelope<T>>(path)
    return Array.isArray(payload.items) ? payload.items : []
  }

  private async request<T>(path: string, init: { method?: string; body?: Record<string, unknown> } = {}) {
    const headers: Record<string, string> = { Accept: "application/json" }
    if (init.body) headers["Content-Type"] = "application/json"
    if (this.testRunId) headers["X-AgentHub-Test-Run"] = this.testRunId

    let response: Response
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method: init.method ?? "GET",
        headers,
        body: init.body ? JSON.stringify(init.body) : undefined,
      })
    } catch (error) {
      throw new AgentHubApiError({
        error_code: "api_unreachable",
        message: "AgentHub Control Plane is unreachable.",
        recovery_hint: "Start the legacy AgentHub API service, then retry.",
        payload: error,
      })
    }

    const payload = await readJson(response)
    if (!response.ok) {
      const errorPayload = isRecord(payload) ? payload : {}
      const code = stringValue(errorPayload.error_code) ?? stringValue(errorPayload.code) ?? "request_failed"
      throw new AgentHubApiError({
        error_code: code,
        message: stringValue(errorPayload.message) ?? `AgentHub API request failed with HTTP ${response.status}.`,
        recovery_hint: stringValue(errorPayload.recovery_hint),
        status: response.status,
        payload,
      })
    }
    return payload as T
  }
}

export function createAgentHubClient() {
  return new AgentHubClient()
}

function defaultAgentHubBaseUrl() {
  return (import.meta.env.VITE_AGENTHUB_API_BASE as string | undefined) || "http://127.0.0.1:8000"
}

function defaultTestRunId() {
  return import.meta.env.VITE_AGENTHUB_TEST_RUN as string | undefined
}

async function readJson(response: Response) {
  const text = await response.text()
  if (!text) return {}
  try {
    return JSON.parse(text) as unknown
  } catch {
    throw new AgentHubApiError({
      error_code: "invalid_json_response",
      message: "AgentHub API returned a non-JSON response.",
      status: response.status,
      recovery_hint: "Check that the request is reaching AgentHub Control Plane, not another service.",
      payload: text,
    })
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value : undefined
}
