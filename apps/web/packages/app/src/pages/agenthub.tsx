import { Button } from "@opencode-ai/ui/button"
import { Icon } from "@opencode-ai/ui/icon"
import { ScrollView } from "@opencode-ai/ui/scroll-view"
import { Spinner } from "@opencode-ai/ui/spinner"
import { Marked } from "marked"

// 独立的 Marked 实例：避免被 MarkedProvider 通过 marked.use() 注册的 async 扩展
// （marked-shiki）污染全局单例，从而保证同步返回字符串。
const markdownInstance = new Marked({ gfm: true, breaks: false })
import { createEffect, createMemo, createResource, createSignal, For, onCleanup, Show } from "solid-js"
import { createStore } from "solid-js/store"
import { AgentHubApiError, createAgentHubClient } from "@/agenthub/api/agenthub-client"
import type {
  AgentProfile,
  Artifact,
  ArtifactCardData,
  ArtifactPreview,
  AgentRun,
  Conversation,
  CreateAgentInput,
  DeploymentRelease,
  ErrorCard,
  Message,
  MentionPayload,
  OrchestratorTask,
  SendMessageResponse,
} from "@/agenthub/types"
import { playSoundById } from "@/utils/sound"

const client = createAgentHubClient()

type SendState = "idle" | "sending" | "completed" | "failed"
type LocalMessage = Message & { local_status?: "pending" | "sent" | "failed" }
type ConversationDialogState =
  | { kind: "rename"; conversation: Conversation }
  | { kind: "delete"; conversation: Conversation }

export default function AgentHubPage() {
  return <AgentHubShell />
}

export function AgentHubShell() {
  const [selectedConversationId, setSelectedConversationId] = createSignal<string>()
  const [draft, setDraft] = createSignal("")
  const [mentions, setMentions] = createSignal<MentionPayload[]>([])
  const [pickerOpen, setPickerOpen] = createSignal(false)
  const [sendErrors, setSendErrors] = createSignal<ErrorCard[]>([])
  const [recentTask, setRecentTask] = createSignal<OrchestratorTask | null>(null)
  const [recentRuns, setRecentRuns] = createSignal<AgentRun[]>([])
  const [selectedArtifactId, setSelectedArtifactId] = createSignal<string>()
  const [deployment, setDeployment] = createSignal<DeploymentRelease | null>(null)
  const [deployError, setDeployError] = createSignal<AgentHubApiError | null>(null)
  const [creatingAgent, setCreatingAgent] = createSignal(false)
  const [configuringAgent, setConfiguringAgent] = createSignal<AgentProfile | null>(null)
  const [conversationDialog, setConversationDialog] = createSignal<ConversationDialogState | null>(null)
  const [localMessages, setLocalMessages] = createSignal<LocalMessage[]>([])
  const [persistedMessages, setPersistedMessages] = createSignal<Message[]>([])
  const [messageCacheConversationId, setMessageCacheConversationId] = createSignal<string>()
  const [sendState, setSendState] = createSignal<SendState>("idle")
  const [lastCompletedAt, setLastCompletedAt] = createSignal<number | null>(null)
  const [activeTargetLabel, setActiveTargetLabel] = createSignal("调度器")
  const [retryingRunIds, setRetryingRunIds] = createSignal<Set<string>>(new Set())

  const [health] = createResource(() => client.health())
  const [agents, agentsActions] = createResource(() => client.agents())
  const [conversations, conversationsActions] = createResource(() => client.conversations())
  const [messages, messagesActions] = createResource(selectedConversationId, (id) => client.messages(id))
  const [artifacts, artifactsActions] = createResource(selectedConversationId, (id) => client.artifacts(id))
  const [preview] = createResource(selectedArtifactId, (id) => client.previewArtifact(id))

  let transcriptEnd: HTMLDivElement | undefined
  let completionTimer: number | undefined

  const apiError = createMemo(() => firstApiError(health.error, agents.error, conversations.error))
  const isApiUnreachable = createMemo(() => apiError()?.error_code === "api_unreachable")
  const agentsValue = createMemo(() => safeResource(() => agents()) ?? [])
  const conversationsValue = createMemo(() => safeResource(() => conversations()) ?? [])
  const messagesValue = createMemo(() => {
    const value = safeResource(() => messages())
    if (Array.isArray(value)) return value
    return messageCacheConversationId() === selectedConversationId() ? persistedMessages() : []
  })
  const artifactsValue = createMemo(() => safeResource(() => artifacts()) ?? [])
  const previewValue = createMemo(() => safeResource(() => preview()))
  const selectedConversation = createMemo(() =>
    conversationsValue().find((conversation) => conversation.id === selectedConversationId()),
  )
  const selectedConversationIsPrivate = createMemo(() => isPrivateConversationMode(selectedConversation()?.mode))
  const diffCards = createMemo(() => collectDiffCards(messagesValue(), artifactsValue()))
  const artifactCards = createMemo(() => collectArtifactCards(messagesValue(), artifactsValue()))
  const selectedAgentLabel = createMemo(() => {
    if (selectedConversationIsPrivate()) return selectedConversation()?.title ?? "Agent"
    if (!mentions().length) return "调度器"
    return mentions()
      .map((mention) => mention.display ?? agentName(agentsValue(), mention.agent_id) ?? "Agent")
      .join("、")
  })
  const activeSendTargetLabel = createMemo(() => (sendState() === "sending" ? activeTargetLabel() : selectedAgentLabel()))
  const visibleMessages = createMemo(() =>
    mergeMessages(
      messagesValue(),
      localMessages().filter((message) => message.conversation_id === selectedConversationId()),
    ),
  )

  createEffect(() => {
    const conversationId = selectedConversationId()
    const value = safeResource(() => messages())
    if (Array.isArray(value)) {
      setMessageCacheConversationId(conversationId)
      setPersistedMessages(value)
    }
  })

  createEffect(() => {
    const list = conversationsValue()
    if (!list?.length || selectedConversationId()) return
    setSelectedConversationId(list[0]?.id)
  })

  createEffect(() => {
    visibleMessages().length
    sendState()
    window.setTimeout(() => transcriptEnd?.scrollIntoView({ block: "end", behavior: "smooth" }), 25)
  })

  createEffect(() => {
    if (!selectedConversationIsPrivate()) return
    setMentions([])
    setPickerOpen(false)
    setDraft((current) => stripAgentMentionTokens(current, agentsValue()))
  })

  onCleanup(() => {
    if (completionTimer !== undefined) window.clearTimeout(completionTimer)
  })

  function flashSendState(state: SendState) {
    setSendState(state)
    if (completionTimer !== undefined) window.clearTimeout(completionTimer)
    if (state !== "idle" && state !== "sending") {
      completionTimer = window.setTimeout(() => setSendState("idle"), 2200)
    }
  }

  async function refreshConversationData(conversationId = selectedConversationId()) {
    await Promise.all([messagesActions.refetch(), artifactsActions.refetch(), conversationsActions.refetch()])
    if (conversationId) setSelectedConversationId(conversationId)
  }

  async function refreshAfterSuccessfulSend(conversationId: string, pendingId: string) {
    try {
      await refreshConversationData(conversationId)
    } catch {
      return
    }
    const persistedIds = new Set(messagesValue().map((message) => message.id))
    setLocalMessages((current) =>
      current.filter(
        (message) =>
          message.local_status === "failed" ||
          (message.id !== pendingId && !persistedIds.has(message.id)),
      ),
    )
  }

  async function createGroupConversation() {
    setSendErrors([])
    const suffix = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    try {
      const conversation = await client.createConversation({
        title: `AgentHub 对话 ${suffix}`,
        mode: "group",
        agent_ids: [],
      })
      await conversationsActions.refetch()
      setSelectedConversationId(conversation.id)
    } catch (error) {
      setSendErrors([errorToCard(error)])
    }
  }

  async function createPrivateConversation(agent: AgentProfile) {
    setSendErrors([])
    try {
      const conversation = await client.createConversation({
        title: agent.name,
        mode: "private",
        agent_ids: [agent.id],
      })
      await conversationsActions.refetch()
      setSelectedConversationId(conversation.id)
      setMentions([])
      setPickerOpen(false)
      setDraft((current) => stripAgentMentionTokens(current, agentsValue()))
    } catch (error) {
      setSendErrors([errorToCard(error)])
    }
  }

  function requestRenameConversation(conversation: Conversation) {
    setConversationDialog({ kind: "rename", conversation })
  }

  async function renameConversation(conversation: Conversation, nextTitleInput: string) {
    const nextTitle = nextTitleInput.trim()
    if (!nextTitle || nextTitle === conversation.title) return
    try {
      await client.updateConversation(conversation.id, { title: nextTitle })
      await conversationsActions.refetch()
    } catch (error) {
      setSendErrors([errorToCard(error)])
    }
  }

  function requestDeleteConversation(conversation: Conversation) {
    setConversationDialog({ kind: "delete", conversation })
  }

  async function deleteConversation(conversation: Conversation) {
    try {
      await client.deleteConversation(conversation.id)
      const remaining = conversationsValue().filter((item) => item.id !== conversation.id)
      await conversationsActions.refetch()
      setLocalMessages((current) => current.filter((message) => message.conversation_id !== conversation.id))
      if (selectedConversationId() === conversation.id) {
        setSelectedConversationId(remaining[0]?.id)
        setPersistedMessages([])
        setMessageCacheConversationId(undefined)
      }
    } catch (error) {
      setSendErrors([errorToCard(error)])
    }
  }

  function pickMention(agent: AgentProfile) {
    if (selectedConversationIsPrivate()) return
    if (!isAgentReady(agent)) return
    setMentions((current) => uniqueMentions([...current, { agent_id: agent.id, display: agent.name }]))
    setDraft((current) => insertMentionToken(current, agent.name))
    setPickerOpen(false)
  }

  async function sendMessage() {
    const conversationId = selectedConversationId()
    const text = draft().trim()
    if (!conversationId || !text || isApiUnreachable() || sendState() === "sending") return

    const privateConversation = selectedConversationIsPrivate()
    const mentionSnapshot = privateConversation ? [] : collectMentionsFromDraft(text, mentions(), agentsValue())
    const targetLabel = mentionSnapshot.length
      ? mentionSnapshot.map((mention) => mention.display ?? agentName(agentsValue(), mention.agent_id) ?? "Agent").join("、")
      : privateConversation
        ? selectedConversation()?.title ?? "Agent"
        : "调度器"
    const pendingId = `local-${Date.now()}`
    const pendingMessage = makeLocalMessage({
      id: pendingId,
      conversationId,
      text,
      mentions: mentionSnapshot,
      status: "pending",
    })

    setDraft("")
    setMentions([])
    setPickerOpen(false)
    setSendErrors([])
    setRecentTask(null)
    setRecentRuns([])
    setActiveTargetLabel(targetLabel)
    setLocalMessages((current) => [...current.filter((message) => message.local_status !== "sent"), pendingMessage])
    flashSendState("sending")

    // Use SSE streaming when multiple agents are mentioned so each
    // agent result appears immediately instead of waiting for all.
    const useStream = mentionSnapshot.length > 1

    try {
      if (useStream) {
        // --- Streaming multi-agent path ---
        const streamingMessages: LocalMessage[] = []
        const streamingRuns: AgentRun[] = []
        const streamingErrors: ErrorCard[] = []

        await new Promise<void>((resolve, reject) => {
          client.sendMessageStream(
            conversationId,
            {
              text,
              mentions: mentionSnapshot,
              orchestrate: true,
              force_agent: true,
              source_surface: "web",
            },
            {
              onStepStarted(data) {
                // Could show a per-step spinner here in the future
              },
              onAgentResult(data) {
                if (data.assistant_message) {
                  streamingMessages.push({ ...data.assistant_message, local_status: "sent" })
                  setLocalMessages((current) => [
                    ...current.filter((m) => m.id !== pendingId && m.local_status !== "sent"),
                    { ...pendingMessage, local_status: "sent" },
                    ...streamingMessages,
                  ])
                }
                if (data.agent_run) {
                  streamingRuns.push(data.agent_run)
                }
              },
              onAgentError(data) {
                streamingErrors.push(data.error_card)
                setSendErrors([...streamingErrors])
              },
              onDone(response) {
                const userMessage = response.message
                  ? ({ ...response.message, local_status: "sent" } as LocalMessage)
                  : ({ ...pendingMessage, local_status: "sent" } as LocalMessage)
                setLocalMessages((current) => [
                  ...current.filter((m) => m.id !== pendingId && m.local_status !== "sent"),
                  userMessage,
                  ...streamingMessages,
                  ...streamingErrors
                    .map((error) => errorMessageFromCard(error, conversationId, pendingId))
                    .filter((message): message is LocalMessage => Boolean(message)),
                ])
                setSendErrors(response.error_cards?.length ? response.error_cards : response.error_card ? [response.error_card] : [])
                setRecentTask(response.task ?? null)
                setRecentRuns(response.agent_runs?.length ? response.agent_runs : response.agent_run ? [response.agent_run] : [])
                resolve()
              },
              onError(error) {
                reject(error)
              },
            },
          )
        })

        await refreshAfterSuccessfulSend(conversationId, pendingId)
        setLastCompletedAt(Date.now())
        flashSendState("completed")
        void playSoundById("yup-02")
      } else {
        // --- Original single-agent / non-streaming path ---
        const response = await client.sendMessage(conversationId, {
          text,
          mentions: mentionSnapshot,
          orchestrate: mentionSnapshot.length !== 1,
          force_agent: mentionSnapshot.length > 0,
          source_surface: "web",
        })
        const responseMessages = responseToMessages(response, pendingMessage)
        setLocalMessages((current) => [
          ...current.filter((message) => message.id !== pendingId && message.local_status !== "sent"),
          ...responseMessages,
        ])
        setSendErrors(response.error_cards?.length ? response.error_cards : response.error_card ? [response.error_card] : [])
        setRecentTask(response.task ?? null)
        setRecentRuns(response.agent_runs?.length ? response.agent_runs : response.agent_run ? [response.agent_run] : [])
        await refreshAfterSuccessfulSend(conversationId, pendingId)
        setLastCompletedAt(Date.now())
        flashSendState("completed")
        void playSoundById("yup-02")
      }
    } catch (error) {
      setLocalMessages((current) =>
        current.map((message) => (message.id === pendingId ? { ...message, local_status: "failed" } : message)),
      )
      setSendErrors([errorToCard(error)])
      flashSendState("failed")
    }
  }

  async function deploySelectedArtifact() {
    const artifactId = selectedArtifactId()
    if (!artifactId) return
    setDeployment(null)
    setDeployError(null)
    try {
      setDeployment(await client.deployArtifact(artifactId))
      await artifactsActions.refetch()
    } catch (error) {
      setDeployError(error instanceof AgentHubApiError ? error : errorToApiError(error))
    }
  }

  async function createAgent(input: CreateAgentInput) {
    await client.createAgent(input)
    await agentsActions.refetch()
    setCreatingAgent(false)
  }

  async function updateAgent(agent: AgentProfile, input: CreateAgentInput) {
    await client.updateAgent(agent.id, input)
    await agentsActions.refetch()
    setConfiguringAgent(null)
  }

  async function deleteAgent(agent: AgentProfile) {
    if (!window.confirm(`删除「${agent.name}」？`)) return
    try {
      await client.deleteAgent(agent.id)
      await agentsActions.refetch()
      if (configuringAgent()?.id === agent.id) setConfiguringAgent(null)
    } catch (error) {
      setSendErrors([errorToCard(error)])
    }
  }

  async function retryRun(run: AgentRun) {
    if (retryingRunIds().has(run.id)) return
    setRetryingRunIds((current) => new Set([...current, run.id]))
    setSendErrors([])
    setActiveTargetLabel(agentName(agentsValue(), run.target_agent_id) ?? "Agent")
    flashSendState("sending")
    try {
      const retried = (await client.retryRun(run.id)) as AgentRun & Partial<SendMessageResponse>
      setRecentRuns((current) => [retried, ...current.filter((item) => item.id !== retried.id)])
      setSendErrors(retried.error_cards?.length ? retried.error_cards : retried.error_card ? [retried.error_card] : [])
      await refreshConversationData(run.conversation_id)
      setLastCompletedAt(Date.now())
      flashSendState(retried.status === "failed" ? "failed" : "completed")
      if (retried.status !== "failed") void playSoundById("yup-02")
    } catch (error) {
      setSendErrors([errorToCard(error)])
      flashSendState("failed")
    } finally {
      setRetryingRunIds((current) => {
        const next = new Set(current)
        next.delete(run.id)
        return next
      })
    }
  }

  return (
    <div class="isolate flex h-[100dvh] min-h-0 flex-col overflow-hidden bg-[#f6f7f9] text-[#20232a]">
      <div class="shrink-0 border-b border-[#d9dee8] bg-[#ffffff]/90 px-5 py-3 shadow-[0_1px_0_rgba(30,36,48,0.04)] backdrop-blur">
        <div class="flex min-w-0 items-center justify-between gap-4">
          <div class="flex min-w-0 items-center gap-3">
            <div class="flex size-9 shrink-0 items-center justify-center rounded-[8px] bg-[#1f2a37] text-white shadow-sm">
              <Icon name="brain" size="small" />
            </div>
            <div class="min-w-0">
              <div class="truncate text-14-medium text-[#111827]">AgentHub 对话台</div>
              <div class="truncate text-12-regular text-[#667085]">多 Agent 协作与任务执行</div>
            </div>
            <StatusPill code={isApiUnreachable() ? "api_unreachable" : health.loading ? "waiting_for_backend" : "api_connected"} />
          </div>
        </div>
      </div>

      <Show when={apiError()}>
        {(error) => (
          <div class="shrink-0 border-b border-[#ffd6bf] bg-[#fff5ef] px-5 py-2 text-12-regular text-[#8a3b12]">
            <span class="font-medium">连接异常：</span>
            <span>{friendlyErrorCode(error().error_code)}</span>
            <span class="ml-2">{friendlyMessage(error().message)}</span>
            <Show when={error().recovery_hint}>
              <span class="ml-2 text-[#a15c32]">{friendlyHint(error().recovery_hint)}</span>
            </Show>
          </div>
        )}
      </Show>

      <div class="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)_360px] gap-0 overflow-hidden">
        <ConversationList
          conversations={conversationsValue()}
          agents={agentsValue()}
          loading={conversations.loading}
          selectedId={selectedConversationId()}
          apiBlocked={isApiUnreachable()}
          onSelect={setSelectedConversationId}
          onCreateGroup={createGroupConversation}
          onCreatePrivate={(agent) => void createPrivateConversation(agent)}
          onRename={requestRenameConversation}
          onDelete={requestDeleteConversation}
        />

        <main class="grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden border-x border-[#d9dee8] bg-[#fbfcfe]">
          <RoomHeader conversation={selectedConversation()} sendState={sendState()} lastCompletedAt={lastCompletedAt()} />
          <ScrollView class="h-full min-h-0 overflow-x-hidden">
            <div class="flex min-h-full w-full max-w-full flex-col gap-4 overflow-x-hidden px-5 py-5">
              <Show
                when={visibleMessages().length > 0}
                fallback={
                  <EmptyState
                    title={messages.loading ? "正在载入对话" : "开始一段新对话"}
                    detail={messages.loading ? "正在同步后端消息。" : "输入问题后会立即显示你的消息，并在 Agent 思考时给出反馈。"}
                  />
                }
              >
                <For each={visibleMessages()}>{(message) => <MessageBubble message={message} agents={agentsValue()} />}</For>
              </Show>

              <Show when={sendState() === "sending"}>
                <ThinkingIndicator label={activeSendTargetLabel()} />
              </Show>
              <div ref={transcriptEnd} />
            </div>
          </ScrollView>

          <Composer
            draft={draft()}
            mentions={mentions()}
            pickerOpen={pickerOpen()}
            agents={agentsValue()}
            apiBlocked={isApiUnreachable()}
            disabled={!selectedConversationId()}
            sending={sendState() === "sending"}
            mentionPickerEnabled={!selectedConversationIsPrivate()}
            onDraft={setDraft}
            onPickerOpen={setPickerOpen}
            onPickMention={pickMention}
            onSend={() => void sendMessage()}
          />
        </main>

        <aside class="flex h-full min-w-0 flex-col overflow-hidden bg-[#f8fafc]">
          <AgentRoster
            agents={agentsValue()}
            loading={agents.loading}
            onCreateAgent={() => setCreatingAgent(true)}
            onConfigure={(agent) => setConfiguringAgent(agent)}
            onDelete={(agent) => void deleteAgent(agent)}
          />
          <ActivityPanel
            task={recentTask()}
            runs={recentRuns()}
            errors={sendErrors()}
            agents={agentsValue()}
            sending={sendState() === "sending"}
            targetLabel={activeSendTargetLabel()}
            retryingRunIds={retryingRunIds()}
            onRetryRun={(run) => void retryRun(run)}
          />
          <div class="min-h-0 flex-1 border-t border-[#d9dee8]">
            <ArtifactPanel
              artifacts={artifactCards()}
              diffs={diffCards()}
              selectedArtifactId={selectedArtifactId()}
              preview={previewValue()}
              previewLoading={preview.loading}
              deployment={deployment()}
              deployError={deployError()}
              onSelect={setSelectedArtifactId}
              onDeploy={() => void deploySelectedArtifact()}
            />
          </div>
        </aside>
      </div>

      <Show when={creatingAgent()}>
        <AgentConfigDialog onClose={() => setCreatingAgent(false)} onSave={(input) => createAgent(input)} />
      </Show>
      <Show when={configuringAgent()}>
        {(agent) => (
          <AgentConfigDialog
            agent={agent()}
            onClose={() => setConfiguringAgent(null)}
            onSave={(input) => updateAgent(agent(), input)}
          />
        )}
      </Show>
      <Show when={conversationDialog()}>
        {(dialog) => (
          <ConversationActionDialog
            dialog={dialog()}
            onClose={() => setConversationDialog(null)}
            onRename={renameConversation}
            onDelete={deleteConversation}
          />
        )}
      </Show>
    </div>
  )
}

export function ConversationList(props: {
  conversations: Conversation[]
  agents: AgentProfile[]
  loading: boolean
  selectedId?: string
  apiBlocked: boolean
  onSelect: (id: string) => void
  onCreateGroup: () => void
  onCreatePrivate: (agent: AgentProfile) => void
  onRename: (conversation: Conversation) => void
  onDelete: (conversation: Conversation) => void
}) {
  const [menuOpen, setMenuOpen] = createSignal(false)
  const [privateOpen, setPrivateOpen] = createSignal(false)
  return (
    <aside class="flex h-full min-w-0 flex-col overflow-hidden border-r border-[#d5dde8] bg-[linear-gradient(180deg,#edf4fb_0%,#f8fafc_48%,#eef4f8_100%)]">
      <div class="relative z-[30] shrink-0 px-4 pb-3 pt-4">
        <div class="relative">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-14-medium text-[#111827]">全部对话</div>
              <div class="mt-1 text-11-regular text-[#667085]">{props.conversations.length} 条记录</div>
            </div>
            <Button
              size="small"
              icon="plus"
              onClick={() => {
                setMenuOpen(!menuOpen())
                setPrivateOpen(false)
              }}
              disabled={props.apiBlocked}
            />
          </div>
          <Show when={menuOpen()}>
            <div class="absolute left-0 right-0 top-12 z-[60] grid gap-1 rounded-[8px] border border-[#c8d0dc] bg-[#ffffff] p-2 shadow-[0_22px_64px_rgba(31,42,55,0.24)]">
              <button
                type="button"
                class="flex min-h-10 w-full items-center justify-start rounded-[7px] px-3 py-2 text-left text-13-medium leading-5 text-[#111827] hover:bg-[#eef6f4]"
                onClick={() => setPrivateOpen(!privateOpen())}
              >
                新建私聊
              </button>
              <Show when={privateOpen()}>
                <div class="mb-1 max-h-56 overflow-auto rounded-[7px] bg-[#f8fafc] p-1">
                  <Show
                    when={props.agents.length > 0}
                  fallback={<div class="px-3 py-3 text-12-regular leading-5 text-[#667085]">暂无可私聊 Agent</div>}
                  >
                    <For each={props.agents}>
                      {(agent) => (
                        <button
                          type="button"
                          class="flex min-h-10 w-full items-center justify-between gap-2 rounded-[7px] px-3 text-left hover:bg-[#ffffff]"
                          onClick={() => {
                            setMenuOpen(false)
                            setPrivateOpen(false)
                            props.onCreatePrivate(agent)
                          }}
                        >
                          <span class="min-w-0 truncate text-13-regular text-[#111827]">{agent.name}</span>
                          <span
                            class="shrink-0 text-11-regular"
                            classList={{ "text-[#047857]": isAgentReady(agent), "text-[#b42318]": !isAgentReady(agent) }}
                          >
                            {isAgentReady(agent) ? "可用" : friendlyErrorCode(agent.error_code ?? "runtime_not_ready")}
                          </span>
                        </button>
                      )}
                    </For>
                  </Show>
                </div>
              </Show>
              <button
                type="button"
                class="flex min-h-10 w-full items-center justify-start rounded-[7px] px-3 py-2 text-left text-13-medium leading-5 text-[#111827] hover:bg-[#eef6f4]"
                onClick={() => {
                  setMenuOpen(false)
                  props.onCreateGroup()
                }}
              >
                新建群聊
              </button>
            </div>
          </Show>
        </div>
      </div>
      <ScrollView class="relative z-0 min-h-0 flex-1 overflow-x-hidden">
        <div class="flex flex-col gap-2.5 px-3 pb-4">
          <Show when={!props.loading} fallback={<InlineLoading label="正在同步对话" />}>
            <Show
              when={props.conversations.length > 0}
              fallback={<EmptyState title="暂无对话" detail="新建一条对话后即可开始协作。" compact />}
            >
              <For each={props.conversations}>
                {(conversation) => {
                  const selected = () => props.selectedId === conversation.id
                  return (
                    <div
                      role="button"
                      tabIndex={0}
                      class="group relative grid min-w-0 cursor-pointer grid-cols-[38px_1fr] gap-3 overflow-hidden rounded-[8px] border border-transparent bg-[#ffffff] px-3 py-3 text-left shadow-[0_8px_22px_rgba(31,42,55,0.04)] transition hover:-translate-y-px hover:border-[#c8d0dc] hover:bg-[#ffffff] hover:shadow-[0_12px_30px_rgba(31,42,55,0.08)]"
                      classList={{
                        "border-[#8fb5d9] bg-[#ffffff] shadow-[0_14px_36px_rgba(31,42,55,0.10)]": selected(),
                      }}
                      onClick={() => props.onSelect(conversation.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") props.onSelect(conversation.id)
                      }}
                    >
                      <span
                        class="absolute inset-y-3 left-0 w-1 rounded-r-full bg-[#0f766e] opacity-0 transition"
                        classList={{ "opacity-100": selected() }}
                      />
                      <ConversationAvatar title={conversation.title} active={selected()} />
                      <span class="min-w-0 pr-10">
                        <span class="flex min-w-0 items-start justify-between gap-2">
                          <span class="truncate text-13-medium text-[#111827]">{conversation.title}</span>
                          <span class="shrink-0 text-[10px] leading-4 text-[#8a96a8]">
                            {formatConversationTime(conversation.last_active_at || conversation.updated_at || conversation.created_at)}
                          </span>
                        </span>
                        <span class="mt-2 flex min-w-0 items-center justify-between gap-2">
                          <span class="truncate text-11-regular text-[#667085]">{modeLabel(conversation.mode)}</span>
                          <span
                            class="size-1.5 shrink-0 rounded-full"
                            classList={{
                              "bg-[#12b76a]": conversation.status !== "archived",
                              "bg-[#98a2b3]": conversation.status === "archived",
                            }}
                          />
                        </span>
                      </span>
                      <div class="absolute bottom-2 right-2 flex gap-1 opacity-0 transition group-hover:opacity-100">
                        <button
                          type="button"
                          class="rounded-[6px] bg-[#eef2f6] px-2 py-1 text-[10px] text-[#475467] hover:bg-[#dde6ef]"
                          onClick={(event) => {
                            event.stopPropagation()
                            props.onRename(conversation)
                          }}
                        >
                          改名
                        </button>
                        <button
                          type="button"
                          class="rounded-[6px] bg-[#fff0f0] px-2 py-1 text-[10px] text-[#b42318] hover:bg-[#ffe1e1]"
                          onClick={(event) => {
                            event.stopPropagation()
                            props.onDelete(conversation)
                          }}
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  )
                }}
              </For>
            </Show>
          </Show>
        </div>
      </ScrollView>
    </aside>
  )
}
export function AgentRoster(props: {
  agents: AgentProfile[]
  loading: boolean
  onCreateAgent: () => void
  onConfigure: (agent: AgentProfile) => void
  onDelete: (agent: AgentProfile) => void
}) {
  return (
    <section class="flex max-h-[38%] min-h-[230px] flex-col">
      <div class="flex h-[52px] shrink-0 items-center justify-between gap-3 px-4">
        <div>
          <div class="text-13-medium text-[#1f2937]">Agent 列表</div>
          <div class="text-11-regular text-[#667085]">选择 @ 后参与回复</div>
        </div>
        <Button size="small" icon="plus" onClick={props.onCreateAgent}>
          新建 Agent
        </Button>
      </div>
      <ScrollView class="min-h-0 flex-1">
        <div class="flex flex-col gap-3 p-4 pt-1">
          <Show when={!props.loading} fallback={<InlineLoading label="正在载入 Agent" />}>
            <Show
              when={props.agents.length > 0}
              fallback={<EmptyState title="暂无 Agent" detail="后端返回 Agent 配置后会显示在这里。" compact />}
            >
              <For each={props.agents}>
                {(agent) => (
                  <div
                    role="button"
                    tabindex="0"
                    class="w-full rounded-[8px] border border-[#d9dee8] bg-[#ffffff] p-3 text-left shadow-[0_8px_24px_rgba(31,42,55,0.05)] transition hover:border-[#14b8a6] hover:bg-[#fbfffe]"
                    onClick={() => props.onConfigure(agent)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault()
                        props.onConfigure(agent)
                      }
                    }}
                  >
                    <div class="flex items-center justify-between gap-2">
                      <div class="flex min-w-0 items-center gap-2">
                        <Avatar label={agent.name} initials={agent.initials} />
                        <div class="min-w-0">
                          <div class="truncate text-13-medium text-[#111827]">{agent.name}</div>
                          <div class="truncate text-11-regular text-[#667085]">{providerLabel(agent.provider)} · 点击配置</div>
                        </div>
                      </div>
                      <RuntimeDot agent={agent} />
                    </div>
                    <div class="mt-3 flex flex-wrap gap-1.5">
                      <For each={agent.capability_tags.slice(0, 5)}>
                        {(tag) => <Tag>{capabilityLabel(tag)}</Tag>}
                      </For>
                    </div>
                    <Show when={agent.error_code}>
                      <div class="mt-2 rounded-[6px] bg-[#fff0f0] px-2 py-1 text-11-regular text-[#b42318]">
                        {friendlyErrorCode(agent.error_code)}：{agent.error_code}
                      </div>
                    </Show>
                    <Show when={!isAgentReady(agent) && !agent.error_code}>
                      <div class="mt-2 rounded-[6px] bg-[#fff7ed] px-2 py-1 text-11-regular text-[#b45309]">
                        runtime_not_ready
                      </div>
                    </Show>
                    <div class="mt-3 flex justify-end gap-2">
                      <span
                        role="button"
                        tabindex="0"
                        class="rounded-[6px] bg-[#fff0f0] px-2 py-1 text-11-medium text-[#b42318] hover:bg-[#ffe1e1]"
                        onClick={(event) => {
                          event.stopPropagation()
                          props.onDelete(agent)
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault()
                            event.stopPropagation()
                            props.onDelete(agent)
                          }
                        }}
                      >
                        删除
                      </span>
                    </div>
                  </div>
                )}
              </For>
            </Show>
          </Show>
        </div>
      </ScrollView>
    </section>
  )
}

export function RoomHeader(props: {
  conversation?: Conversation
  sendState: SendState
  lastCompletedAt: number | null
}) {
  return (
    <header class="flex h-14 shrink-0 items-center border-b border-[#d9dee8] bg-[#ffffff] px-5">
      <div class="min-w-0">
        <div class="truncate text-14-medium text-[#111827]">{props.conversation?.title ?? "AgentHub 对话"}</div>
        <div class="mt-0.5 flex items-center gap-2 text-11-regular text-[#667085]">
          <span>{modeLabel(props.conversation?.mode)}</span>
          <Show when={props.sendState === "sending"}>
            <span class="text-[#0f766e]">模型正在思考中</span>
          </Show>
          <Show when={props.sendState === "completed" && props.lastCompletedAt}>
            <span class="text-[#047857]">回复已完成</span>
          </Show>
        </div>
      </div>
    </header>
  )
}

function Composer(props: {
  draft: string
  mentions: MentionPayload[]
  pickerOpen: boolean
  agents: AgentProfile[]
  apiBlocked: boolean
  disabled: boolean
  sending: boolean
  mentionPickerEnabled: boolean
  onDraft: (value: string) => void
  onPickerOpen: (open: boolean) => void
  onPickMention: (agent: AgentProfile) => void
  onSend: () => void
}) {
  const [mentionQuery, setMentionQuery] = createSignal("")
  const [highlightedIndex, setHighlightedIndex] = createSignal(0)
  const mentionCandidates = createMemo(() => {
    if (!props.mentionPickerEnabled) return []
    const query = mentionQuery().toLowerCase()
    return props.agents
      .filter(isAgentReady)
      .filter((agent) => !query || agent.name.toLowerCase().includes(query) || String(agent.provider ?? "").toLowerCase().includes(query))
  })
  const chooseMention = (agent: AgentProfile) => {
    if (!props.mentionPickerEnabled) return
    props.onPickMention(agent)
    setMentionQuery("")
    setHighlightedIndex(0)
  }
  const updateDraft = (value: string) => {
    props.onDraft(value)
    if (!props.mentionPickerEnabled) {
      if (props.pickerOpen) props.onPickerOpen(false)
      setMentionQuery("")
      setHighlightedIndex(0)
      return
    }
    const query = detectMentionQuery(value)
    if (query === null) return
    setMentionQuery(query)
    setHighlightedIndex(0)
    props.onPickerOpen(true)
  }
  createEffect(() => {
    if (props.mentionPickerEnabled) return
    setMentionQuery("")
    setHighlightedIndex(0)
    if (props.pickerOpen) props.onPickerOpen(false)
  })
  return (
    <div class="relative z-10 shrink-0 border-t border-[#d9dee8] bg-[#ffffff] px-5 py-2.5 shadow-[0_-10px_28px_rgba(31,42,55,0.05)]">
      <div class="relative w-full">
        <Show when={props.mentionPickerEnabled && props.pickerOpen}>
          <AgentMentionPicker
            agents={mentionCandidates()}
            selected={props.mentions}
            highlightedIndex={highlightedIndex()}
            query={mentionQuery()}
            onPick={chooseMention}
          />
        </Show>
        <div
          class="grid min-h-[52px] items-end gap-3 rounded-[8px] border border-[#c8d0dc] bg-[#ffffff] p-2.5 shadow-sm transition"
          classList={{
            "grid-cols-[auto_1fr_auto]": props.mentionPickerEnabled,
            "grid-cols-[minmax(0,1fr)_auto]": !props.mentionPickerEnabled,
            "border-[#14b8a6] ring-2 ring-[#99f6e4]/60": props.draft.trim().length > 0,
          }}
        >
          <Show when={props.mentionPickerEnabled}>
            <Button
              size="small"
              variant={props.mentions.length ? "primary" : "secondary"}
              onClick={() => {
                setMentionQuery("")
                setHighlightedIndex(0)
                props.onPickerOpen(!props.pickerOpen)
              }}
              disabled={props.apiBlocked || props.agents.length === 0 || props.sending}
            >
              @{props.mentions.length || "Agent"}
            </Button>
          </Show>
          <textarea
            class="max-h-28 min-h-8 resize-none border-0 bg-transparent px-1 py-1.5 text-14-regular leading-6 text-[#111827] outline-none placeholder:text-[#98a2b3]"
            value={props.draft}
            placeholder={props.apiBlocked ? "后端未连接，暂时无法发送" : props.disabled ? "请先新建或选择对话" : "输入消息，回车发送，组合键换行"}
            disabled={props.apiBlocked || props.disabled}
            onInput={(event) => updateDraft(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (props.mentionPickerEnabled && props.pickerOpen && mentionCandidates().length > 0) {
                if (event.key === "ArrowDown") {
                  event.preventDefault()
                  setHighlightedIndex((highlightedIndex() + 1) % mentionCandidates().length)
                  return
                }
                if (event.key === "ArrowUp") {
                  event.preventDefault()
                  setHighlightedIndex((highlightedIndex() - 1 + mentionCandidates().length) % mentionCandidates().length)
                  return
                }
                if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
                  event.preventDefault()
                  chooseMention(mentionCandidates()[highlightedIndex()] ?? mentionCandidates()[0])
                  return
                }
              }
              if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
                event.preventDefault()
                props.onSend()
              }
              if (event.key === "Escape") props.onPickerOpen(false)
            }}
          />
          <Button
            size="small"
            icon={props.sending ? undefined : "arrow-up"}
            variant="primary"
            onClick={props.onSend}
            disabled={props.apiBlocked || props.disabled || props.sending || !props.draft.trim()}
          >
            {props.sending ? "发送中" : "发送"}
          </Button>
        </div>
      </div>
    </div>
  )
}

export function AgentMentionPicker(props: {
  agents: AgentProfile[]
  selected: MentionPayload[]
  highlightedIndex: number
  query: string
  onPick: (agent: AgentProfile) => void
}) {
  return (
    <div class="absolute bottom-full left-0 z-[60] mb-3 w-[21.5rem] rounded-[8px] border border-[#c8d0dc] bg-[#ffffff] p-2 shadow-[0_18px_54px_rgba(31,42,55,0.16)]">
      <div class="px-2 pb-2 text-11-regular text-[#667085]">
        {props.query ? `匹配 “${props.query}”` : "选择可用 Agent"}
      </div>
      <Show when={props.agents.length > 0} fallback={<div class="px-2 py-3 text-12-regular text-[#667085]">暂无可用 Agent</div>}>
        <For each={props.agents}>
          {(agent, index) => {
          const selected = () => props.selected.some((mention) => mention.agent_id === agent.id)
          return (
            <button
              type="button"
              class="flex w-full items-center justify-between rounded-[7px] px-2 py-2 text-left transition hover:bg-[#eef6f4]"
              classList={{ "bg-[#e6fffb]": index() === props.highlightedIndex }}
              onClick={() => props.onPick(agent)}
            >
              <span class="min-w-0 truncate text-13-regular text-[#111827]">@{agent.name}</span>
              <span class="text-11-regular text-[#667085]">
                {selected() ? "已选择" : providerLabel(agent.provider)}
              </span>
            </button>
          )
        }}
        </For>
      </Show>
    </div>
  )
}

function ActivityPanel(props: {
  task: OrchestratorTask | null
  runs: AgentRun[]
  errors: ErrorCard[]
  agents: AgentProfile[]
  sending: boolean
  targetLabel: string
  retryingRunIds: Set<string>
  onRetryRun: (run: AgentRun) => void
}) {
  return (
    <section class="flex max-h-[34%] min-h-[210px] flex-col border-t border-[#d9dee8]">
      <div class="flex h-[52px] shrink-0 items-center justify-between px-4">
        <div>
          <div class="text-13-medium text-[#1f2937]">执行动态</div>
          <div class="text-11-regular text-[#667085]">任务与 Agent 运行记录</div>
        </div>
        <Show when={props.sending} fallback={<StatusPill code="idle" />}>
          <div class="flex items-center gap-2 rounded-full bg-[#e6fffb] px-2 py-1 text-11-regular text-[#0f766e]">
            <Spinner class="size-3" />
            思考中
          </div>
        </Show>
      </div>
      <ScrollView class="min-h-0 flex-1">
        <div class="flex flex-col gap-3 p-4 pt-1">
          <Show when={props.sending}>
            <div class="rounded-[8px] border border-[#b8ece3] bg-[#f0fdfa] p-3">
              <div class="text-12-medium text-[#115e59]">{props.targetLabel} 正在处理</div>
              <div class="mt-1 text-11-regular text-[#4b817a]">收到发送请求，等待后端返回结果。</div>
            </div>
          </Show>
          <Show when={props.task}>
            {(task) => <OrchestratorPlanCard task={task()} agents={props.agents} />}
          </Show>
          <For each={props.runs}>
            {(run) => (
              <AgentRunCard
                run={run}
                agents={props.agents}
                retrying={props.retryingRunIds.has(run.id)}
                onRetry={() => props.onRetryRun(run)}
              />
            )}
          </For>
          <For each={props.errors}>{(error) => <ErrorCardView error={error} />}</For>
          <Show when={!props.sending && !props.task && props.runs.length === 0 && props.errors.length === 0}>
            <EmptyState title="暂无执行记录" detail="发送消息后，任务进度会显示在这里。" compact />
          </Show>
        </div>
      </ScrollView>
    </section>
  )
}

export function OrchestratorPlanCard(props: { task: OrchestratorTask; agents: AgentProfile[] }) {
  const steps = () => props.task.steps ?? props.task.plan?.steps ?? []
  return (
    <div class="rounded-[8px] border border-[#d9dee8] bg-[#ffffff] p-3 shadow-sm">
      <div class="text-12-medium text-[#1f2937]">调度计划</div>
      <div class="mt-1 text-12-regular text-[#667085]">{props.task.goal}</div>
      <div class="mt-3 flex flex-col gap-2">
        <For each={steps()}>
          {(step) => (
            <div class="rounded-[7px] bg-[#f6f7f9] p-2">
              <div class="flex items-center justify-between gap-2">
                <span class="truncate text-12-medium text-[#111827]">{step.title || capabilityLabel(step.kind)}</span>
                <span class="text-11-regular text-[#667085]">{statusLabel(step.status)}</span>
              </div>
              <div class="mt-1 text-11-regular text-[#667085]">
                负责 Agent：{agentName(props.agents, step.assigned_agent_id) ?? "待分配"}
              </div>
              <Show when={step.instruction || step.expected_output?.instruction}>
                <div class="mt-1 text-12-regular text-[#344054]">
                  {String(step.instruction ?? step.expected_output?.instruction)}
                </div>
              </Show>
              <Show when={step.blocked_reason}>
                <div class="mt-1 text-11-regular text-[#b42318]">阻塞原因：{step.blocked_reason}</div>
              </Show>
            </div>
          )}
        </For>
      </div>
    </div>
  )
}

export function AgentRunCard(props: { run: AgentRun; agents: AgentProfile[]; retrying?: boolean; onRetry?: () => void }) {
  const failed = () => ["failed", "incomplete", "final_content_empty"].includes(props.run.status)
  return (
    <div
      class="rounded-[8px] border bg-[#ffffff] p-3 shadow-sm"
      classList={{
        "border-[#fecaca]": failed(),
        "border-[#d9dee8]": !failed(),
      }}
    >
      <div class="flex items-center justify-between gap-2">
        <div class="text-12-medium text-[#1f2937]">执行记录</div>
        <span class="text-11-regular text-[#667085]">{statusLabel(props.run.status)}</span>
      </div>
      <div class="mt-1 text-12-regular text-[#667085]">
        {agentName(props.agents, props.run.target_agent_id) ?? props.run.target_agent_id} · {runModeLabel(props.run.run_mode)}
      </div>
      <Show when={props.run.error_code}>
        <div class="mt-2 rounded-[6px] bg-[#fff0f0] px-2 py-1 text-11-regular text-[#b42318]">
          {friendlyErrorCode(props.run.error_code)}
        </div>
      </Show>
      <Show when={failed() && props.onRetry}>
        <Button class="mt-3" size="small" icon="reset" onClick={props.onRetry} disabled={props.retrying}>
          {props.retrying ? "重试中" : "重试"}
        </Button>
      </Show>
    </div>
  )
}

export function ArtifactCard(props: { artifact: Artifact | ArtifactCardData; selected?: boolean; onSelect: (id: string) => void }) {
  const id = () => ("id" in props.artifact ? props.artifact.id : props.artifact.artifact_id)
  return (
    <button
      type="button"
      class="w-full rounded-[8px] border border-[#d9dee8] bg-[#ffffff] p-3 text-left transition hover:border-[#14b8a6] hover:bg-[#f7fffd]"
      classList={{ "border-[#14b8a6] ring-2 ring-[#99f6e4]/50": props.selected }}
      onClick={() => props.onSelect(id())}
    >
      <div class="flex items-center justify-between gap-2">
        <span class="truncate text-13-medium text-[#111827]">{props.artifact.title}</span>
        <span class="text-11-regular text-[#667085]">{statusLabel(props.artifact.status)}</span>
      </div>
      <div class="mt-1 text-11-regular text-[#667085]">{artifactTypeLabel(props.artifact.type)}</div>
    </button>
  )
}

export function DiffCard(props: { diff: Artifact | ArtifactCardData; selected?: boolean; onSelect: (id: string) => void }) {
  const id = () => ("id" in props.diff ? props.diff.id : props.diff.artifact_id)
  const additions = () => ("additions" in props.diff ? Number(props.diff.additions ?? 0) : 0)
  const deletions = () => ("deletions" in props.diff ? Number(props.diff.deletions ?? 0) : 0)
  return (
    <button
      type="button"
      class="w-full rounded-[8px] border border-[#d9dee8] bg-[#ffffff] p-3 text-left transition hover:border-[#f59e0b] hover:bg-[#fffaf0]"
      classList={{ "border-[#f59e0b] ring-2 ring-[#fde68a]/50": props.selected }}
      onClick={() => props.onSelect(id())}
    >
      <div class="flex items-center justify-between gap-2">
        <span class="truncate text-13-medium text-[#111827]">{props.diff.title}</span>
        <span class="text-11-regular text-[#667085]">代码变更</span>
      </div>
      <div class="mt-1 text-11-regular text-[#667085]">
        新增 {additions()} · 删除 {deletions()}
      </div>
    </button>
  )
}

export function DeploymentCard(props: { release?: DeploymentRelease | null; error?: AgentHubApiError | null; onDeploy: () => void }) {
  const failed = () => props.release?.status === "failed" || Boolean(props.error)
  return (
    <div
      class="rounded-[8px] border bg-[#ffffff] p-3 shadow-sm"
      classList={{
        "border-[#fecaca]": failed(),
        "border-[#d9dee8]": !failed(),
      }}
    >
      <div class="text-12-medium text-[#1f2937]">发布</div>
      <Show when={props.release} fallback={<div class="mt-1 text-12-regular text-[#667085]">选择产物后可以发布预览。</div>}>
        {(release) => (
          <div class="mt-1 text-12-regular text-[#667085]">
            {statusLabel(release().status)}
            <Show when={release().error_code}> · {friendlyErrorCode(release().error_code)}</Show>
            <Show when={release().url}>
              {" "}
              ·{" "}
              <a class="text-[#0f766e] underline" href={release().url ?? undefined} target="_blank">
                打开链接
              </a>
            </Show>
          </div>
        )}
      </Show>
      <Show when={props.error}>
        {(error) => <div class="mt-2 text-12-regular text-[#b42318]">{friendlyErrorCode(error().error_code)}</div>}
      </Show>
      <Button class="mt-3" size="small" icon="square-arrow-top-right" onClick={props.onDeploy}>
        发布
      </Button>
    </div>
  )
}

export function AgentConfigDialog(props: { agent?: AgentProfile; onClose: () => void; onSave: (input: CreateAgentInput) => Promise<void> | void }) {
  const initialType = isLocalAgentProvider(props.agent?.provider) || props.agent?.kind === "local" ? "local_cli" : "custom_cloud"
  const [agentType, setAgentType] = createSignal<"custom_cloud" | "local_cli">(initialType)
  const [submitting, setSubmitting] = createSignal(false)
  const [error, setError] = createSignal<ErrorCard | null>(null)
  const [form, setForm] = createStore({
    name: props.agent?.name ?? "",
    system_prompt: props.agent?.system_prompt ?? "",
    capability_tags: props.agent?.capability_tags?.length
      ? props.agent.capability_tags.map(capabilityLabel).join("，")
      : initialType === "local_cli"
        ? "代码，审查，工作区"
        : "对话，模型",
    provider: props.agent?.provider ?? "custom_openai",
    local_provider: isLocalAgentProvider(props.agent?.provider) ? props.agent?.provider ?? "codex" : "codex",
    model: props.agent?.model ?? "",
    api_base: props.agent?.api_base ?? "",
    api_key: "",
    executable_path: props.agent?.executable_path ?? "",
  })
  const editing = createMemo(() => Boolean(props.agent))
  const valid = createMemo(() => {
    if (!form.name.trim()) return false
    if (agentType() === "custom_cloud") {
      if (!form.provider.trim() || !form.api_base.trim() || !form.model.trim()) return false
      return editing() || Boolean(form.api_key.trim())
    }
    return Boolean(form.local_provider.trim() && form.executable_path.trim())
  })

  async function submit() {
    if (!valid() || submitting()) return
    setSubmitting(true)
    setError(null)
    const provider = agentType() === "custom_cloud" ? form.provider.trim() || "custom_openai" : form.local_provider
    const input: CreateAgentInput = {
      name: form.name.trim(),
      avatar: null,
      system_prompt: form.system_prompt.trim(),
      provider,
      adapter_kind: adapterKindForProvider(provider),
      kind: agentType() === "custom_cloud" ? "custom" : "local",
      agent_type: agentType(),
      model: agentType() === "custom_cloud" ? form.model.trim() : null,
      api_base: agentType() === "custom_cloud" ? form.api_base.trim() : null,
      api_key: agentType() === "custom_cloud" && form.api_key.trim() ? form.api_key.trim() : null,
      executable_path: agentType() === "local_cli" ? form.executable_path.trim() : null,
      connection_test_required: true,
      capability_tags: form.capability_tags
        .split(/[,，]/)
        .map((tag) => tag.trim())
        .map(capabilityValue)
        .filter(Boolean),
    }
    try {
      await props.onSave(input)
    } catch (err) {
      setError(errorToCard(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div class="fixed inset-0 z-[200] flex items-center justify-center bg-[#111827]/60 p-6">
      <div class="w-full max-w-xl rounded-[8px] border border-[#d9dee8] bg-[#ffffff] p-5 shadow-[0_24px_80px_rgba(17,24,39,0.32)]">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-14-medium text-[#111827]">{editing() ? "配置 Agent" : "新建 Agent"}</div>
            <div class="mt-1 text-12-regular text-[#667085]">
              {agentType() === "custom_cloud" ? "自定义云模型需要连接测试通过后保存。" : "本地 Agent 需要可执行路径通过预检后保存。"}
            </div>
          </div>
          <Button size="small" variant="ghost" icon="close" onClick={props.onClose} />
        </div>
        <div class="mt-4 grid gap-3">
          <div class="grid grid-cols-2 gap-2 rounded-[8px] bg-[#eef2f6] p-1">
            <button
              type="button"
              class="h-9 rounded-[7px] text-12-medium transition"
              classList={{
                "bg-[#ffffff] text-[#0f766e] shadow-sm": agentType() === "custom_cloud",
                "text-[#667085]": agentType() !== "custom_cloud",
              }}
              onClick={() => setAgentType("custom_cloud")}
            >
              自定义 Agent
            </button>
            <button
              type="button"
              class="h-9 rounded-[7px] text-12-medium transition"
              classList={{
                "bg-[#ffffff] text-[#0f766e] shadow-sm": agentType() === "local_cli",
                "text-[#667085]": agentType() !== "local_cli",
              }}
              onClick={() => setAgentType("local_cli")}
            >
              本地 Agent
            </button>
          </div>
          <Field label="名称" value={form.name} onInput={(value) => setForm("name", value)} />
          <Show
            when={agentType() === "custom_cloud"}
            fallback={
              <>
                <label class="grid gap-1">
                  <span class="text-11-regular text-[#667085]">本地 Agent</span>
                  <select
                    class="h-9 rounded-[8px] border border-[#d9dee8] bg-[#ffffff] px-3 text-13-regular text-[#111827] outline-none transition focus:border-[#14b8a6] focus:ring-2 focus:ring-[#99f6e4]/60"
                    value={form.local_provider}
                    onInput={(event) => setForm("local_provider", event.currentTarget.value)}
                  >
                    <option value="codex">Codex</option>
                    <option value="anthropic">Claude Code</option>
                  </select>
                </label>
                <Field label="本地运行路径" value={form.executable_path} onInput={(value) => setForm("executable_path", value)} />
              </>
            }
          >
            <Field label="提供商标识" value={form.provider} onInput={(value) => setForm("provider", value)} />
            <Field label="base_url" value={form.api_base} onInput={(value) => setForm("api_base", value)} />
            <Field label="模型名称" value={form.model} onInput={(value) => setForm("model", value)} />
            <Field label={editing() ? "key（留空沿用原 key）" : "key"} value={form.api_key} type="password" onInput={(value) => setForm("api_key", value)} />
          </Show>
          <Field label="能力标签" value={form.capability_tags} onInput={(value) => setForm("capability_tags", value)} />
          <label class="grid gap-1">
            <span class="text-11-regular text-[#667085]">系统提示词</span>
            <textarea
              class="min-h-24 rounded-[8px] border border-[#d9dee8] bg-[#ffffff] px-3 py-2 text-13-regular text-[#111827] outline-none transition focus:border-[#14b8a6] focus:ring-2 focus:ring-[#99f6e4]/60"
              value={form.system_prompt}
              onInput={(event) => setForm("system_prompt", event.currentTarget.value)}
            />
          </label>
          <Show when={error()}>
            {(card) => <ErrorCardView error={card()} />}
          </Show>
        </div>
        <div class="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={props.onClose} disabled={submitting()}>
            取消
          </Button>
          <Button variant="primary" onClick={() => void submit()} disabled={!valid() || submitting()}>
            {submitting() ? "测试中" : editing() ? "测试并保存" : "测试并创建"}
          </Button>
        </div>
      </div>
    </div>
  )
}

function ConversationActionDialog(props: {
  dialog: ConversationDialogState
  onClose: () => void
  onRename: (conversation: Conversation, title: string) => Promise<void> | void
  onDelete: (conversation: Conversation) => Promise<void> | void
}) {
  const [title, setTitle] = createSignal(props.dialog.kind === "rename" ? props.dialog.conversation.title : "")
  const [submitting, setSubmitting] = createSignal(false)
  const isRename = createMemo(() => props.dialog.kind === "rename")
  const canSubmit = createMemo(() => !isRename() || Boolean(title().trim()))

  async function submit() {
    if (!canSubmit() || submitting()) return
    setSubmitting(true)
    try {
      if (props.dialog.kind === "rename") {
        await props.onRename(props.dialog.conversation, title())
      } else {
        await props.onDelete(props.dialog.conversation)
      }
      props.onClose()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div class="fixed inset-0 z-[210] flex items-center justify-center bg-[#111827]/60 p-6">
      <div class="w-full max-w-md rounded-[8px] border border-[#d9dee8] bg-[#ffffff] p-5 shadow-[0_24px_80px_rgba(17,24,39,0.32)]">
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <div class="text-14-medium text-[#111827]">{isRename() ? "修改会话名称" : "删除会话"}</div>
            <div class="mt-1 text-12-regular leading-5 text-[#667085]">
              {isRename() ? "给当前会话换一个更容易识别的标题。" : `删除「${props.dialog.conversation.title}」后，这条本地会话会从列表中移除。`}
            </div>
          </div>
          <Button size="small" variant="ghost" icon="close" onClick={props.onClose} disabled={submitting()} />
        </div>
        <Show when={isRename()}>
          <label class="mt-4 grid gap-1">
            <span class="text-11-regular text-[#667085]">会话标题</span>
            <input
              class="h-10 rounded-[8px] border border-[#c8d0dc] bg-[#ffffff] px-3 text-13-regular text-[#111827] outline-none transition focus:border-[#14b8a6] focus:ring-2 focus:ring-[#99f6e4]/60"
              value={title()}
              autofocus
              onInput={(event) => setTitle(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault()
                  void submit()
                }
                if (event.key === "Escape") props.onClose()
              }}
            />
          </label>
        </Show>
        <div class="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={props.onClose} disabled={submitting()}>
            取消
          </Button>
          <Button
            variant="primary"
            onClick={() => void submit()}
            disabled={!canSubmit() || submitting()}
          >
            {submitting() ? "处理中" : isRename() ? "保存" : "删除"}
          </Button>
        </div>
      </div>
    </div>
  )
}

function ArtifactPanel(props: {
  artifacts: Array<Artifact | ArtifactCardData>
  diffs: Array<Artifact | ArtifactCardData>
  selectedArtifactId?: string
  preview?: ArtifactPreview
  previewLoading: boolean
  deployment?: DeploymentRelease | null
  deployError?: AgentHubApiError | null
  onSelect: (id: string) => void
  onDeploy: () => void
}) {
  return (
    <div class="flex h-full min-h-0 flex-col">
      <div class="flex h-[52px] shrink-0 items-center justify-between px-4">
        <div>
          <div class="text-13-medium text-[#1f2937]">产物</div>
          <div class="text-11-regular text-[#667085]">文件、预览与变更</div>
        </div>
      </div>
      <ScrollView class="min-h-0 flex-1">
        <div class="flex flex-col gap-3 p-4 pt-1">
          <Show
            when={props.artifacts.length > 0 || props.diffs.length > 0}
            fallback={<EmptyState title="暂无产物" detail="当 Agent 返回文件、预览或变更时会显示在这里。" compact />}
          >
            <For each={props.diffs}>
              {(diff) => <DiffCard diff={diff} selected={artifactId(diff) === props.selectedArtifactId} onSelect={props.onSelect} />}
            </For>
            <For each={props.artifacts}>
              {(artifact) => <ArtifactCard artifact={artifact} selected={artifactId(artifact) === props.selectedArtifactId} onSelect={props.onSelect} />}
            </For>
          </Show>
          <Show when={props.selectedArtifactId}>
            <PreviewPane artifactId={props.selectedArtifactId} preview={props.preview} loading={props.previewLoading} />
            <DeploymentCard release={props.deployment} error={props.deployError} onDeploy={props.onDeploy} />
          </Show>
        </div>
      </ScrollView>
    </div>
  )
}

function PreviewPane(props: { artifactId?: string; preview?: ArtifactPreview; loading: boolean }) {
  const downloadHref = createMemo(() => (props.artifactId ? client.artifactDownloadUrl(props.artifactId) : undefined))
  return (
    <div class="rounded-[8px] border border-[#d9dee8] bg-[#ffffff] p-3 shadow-sm">
      <div class="mb-2 flex items-center justify-between gap-2">
        <div class="text-12-medium text-[#1f2937]">预览</div>
        <Show when={downloadHref()}>
          {(href) => (
            <a
              class="inline-flex h-7 items-center gap-1 rounded-[7px] border border-[#cfd6e2] px-2 text-11-medium text-[#344054] transition hover:border-[#14b8a6] hover:text-[#0f766e]"
              href={href()}
              target="_blank"
              rel="noreferrer"
            >
              <Icon name="download" size="small" />
              下载
            </a>
          )}
        </Show>
      </div>
      <Show when={!props.loading} fallback={<InlineLoading label="正在载入预览" />}>
        <Show when={props.preview} fallback={<div class="text-12-regular text-[#667085]">暂无预览内容</div>}>
          {(preview) => (
            <PreviewContent preview={preview()} />
          )}
        </Show>
      </Show>
    </div>
  )
}

function PreviewContent(props: { preview: ArtifactPreview }) {
  const preview = () => props.preview
  return (
    <Show
      when={preview().preview_type === "structured_diff"}
      fallback={
        <Show
          when={preview().type === "web_preview" && preview().content}
          fallback={
            <Show
              when={isMarkdownPreview(preview()) || preview().preview_type === "office_document"}
              fallback={
                <pre class="max-h-80 overflow-auto whitespace-pre-wrap rounded-[7px] bg-[#f6f7f9] p-2 text-11-mono text-[#344054]">
                  {preview().content ?? JSON.stringify({ files: preview().files, hunks: preview().hunks }, null, 2)}
                </pre>
              }
            >
              <div class="max-h-96 overflow-auto rounded-[7px] border border-[#e4e7ec] bg-[#fcfcfd] p-3">
                <MarkdownContent content={preview().content ?? ""} />
              </div>
            </Show>
          }
        >
          <iframe
            class="h-72 w-full rounded-[7px] border border-[#d9dee8] bg-[#ffffff]"
            sandbox=""
            srcdoc={preview().content}
            title="AgentHub 产物预览"
          />
        </Show>
      }
    >
      <StructuredDiffPreview preview={preview()} />
    </Show>
  )
}

function StructuredDiffPreview(props: { preview: ArtifactPreview }) {
  const files = () => props.preview.files ?? []
  return (
    <div class="max-h-96 overflow-auto rounded-[7px] border border-[#e4e7ec] bg-[#fbfcfe]">
      <div class="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-[#e4e7ec] bg-[#ffffff] px-3 py-2">
        <div class="min-w-0 truncate text-12-medium text-[#1f2937]">结构化 Diff</div>
        <div class="shrink-0 text-11-regular">
          <span class="text-[#067647]">+{props.preview.additions ?? 0}</span>
          <span class="mx-1 text-[#98a2b3]">/</span>
          <span class="text-[#b42318]">-{props.preview.deletions ?? 0}</span>
        </div>
      </div>
      <div class="divide-y divide-[#e4e7ec]">
        <For each={files()}>
          {(file) => (
            <div>
              <div class="flex items-center justify-between gap-3 bg-[#f8fafc] px-3 py-2">
                <div class="min-w-0 truncate text-12-medium text-[#344054]">{file.path ?? file.new_path ?? "workspace.diff"}</div>
                <div class="shrink-0 text-11-regular">
                  <span class="text-[#067647]">+{Number(file.additions ?? 0)}</span>
                  <span class="mx-1 text-[#98a2b3]">/</span>
                  <span class="text-[#b42318]">-{Number(file.deletions ?? 0)}</span>
                </div>
              </div>
              <For each={file.hunks ?? []}>{(hunk) => <DiffHunk hunk={hunk} />}</For>
            </div>
          )}
        </For>
      </div>
    </div>
  )
}

function DiffHunk(props: { hunk: NonNullable<ArtifactPreview["hunks"]>[number] }) {
  return (
    <div class="border-t border-[#eef2f6]">
      <div class="bg-[#eef6ff] px-3 py-1 font-mono text-[11px] leading-5 text-[#175cd3]">
        {props.hunk.header ?? props.hunk.file_path ?? props.hunk.path ?? "@@"}
      </div>
      <For each={props.hunk.lines ?? []}>
        {(line) => (
          <div
            class="grid grid-cols-[42px_42px_minmax(0,1fr)] gap-2 px-3 py-0.5 font-mono text-[11px] leading-5"
            classList={{
              "bg-[#ecfdf3] text-[#067647]": line.type === "addition",
              "bg-[#fff1f3] text-[#b42318]": line.type === "deletion",
              "text-[#475467]": line.type !== "addition" && line.type !== "deletion",
            }}
          >
            <span class="select-none text-right text-[#98a2b3]">{line.old_line ?? ""}</span>
            <span class="select-none text-right text-[#98a2b3]">{line.new_line ?? ""}</span>
            <span class="min-w-0 whitespace-pre-wrap break-words">{diffPrefix(line.type) + (line.content ?? "")}</span>
          </div>
        )}
      </For>
    </div>
  )
}

function MessageBubble(props: { message: LocalMessage; agents: AgentProfile[] }) {
  const fromUser = createMemo(() => props.message.sender_type === "user")
  const isError = createMemo(() => props.message.message_type === "error")
  const errorCard = createMemo(() => normalizeMessageErrorCard(props.message))
  const [thinkingOpen, setThinkingOpen] = createSignal(false)
  const [rawOpen, setRawOpen] = createSignal(false)
  const finalContent = createMemo(() => stringValue(props.message.content.final_content) ?? stringValue(props.message.content.text) ?? "")
  const thinkingContent = createMemo(() => stringValue(props.message.content.thinking_content) ?? "")
  const rawContent = createMemo(() => stringValue(props.message.content.raw_content) ?? "")
  const finalContentEmpty = createMemo(() => !finalContent().trim() && Boolean(rawContent().trim()))
  const sender = createMemo(() =>
    props.message.sender_type === "assistant"
      ? agentName(props.agents, props.message.sender_id) ?? props.message.sender_id
      : senderLabel(props.message.sender_type),
  )
  return (
    <div class="flex min-w-0" classList={{ "justify-end": fromUser(), "justify-start": !fromUser() }}>
      <div
        class="min-w-0 select-text rounded-[8px] border px-4 py-3 shadow-sm"
        classList={{
          "max-w-[88%] border-[#d9dee8] bg-[#ffffff] text-[#111827]": !fromUser(),
          "max-w-[72%] border-[#0f766e] bg-[#0f766e] text-white shadow-[0_10px_28px_rgba(15,118,110,0.22)]": fromUser(),
          "max-w-[88%] border-[#fecaca] bg-[#fff5f5] text-[#7a271a]": isError(),
          "opacity-70": props.message.local_status === "pending",
          "border-[#fda29b] bg-[#fff5f5] text-[#7a271a]": props.message.local_status === "failed",
        }}
      >
        <div
          class="mb-1 flex items-center justify-between gap-3 text-11-regular"
          classList={{
            "text-white/75": fromUser() && props.message.local_status !== "failed",
            "text-[#667085]": !fromUser() || props.message.local_status === "failed",
          }}
        >
          <span>{sender()}</span>
          <span>{new Date(props.message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
        </div>
        <Show
          when={isError()}
          fallback={
            <>
              <Show
                when={finalContentEmpty()}
                fallback={
                  <RichMessageContent content={finalContent() || "No final content."} inverse={fromUser()} />
                }
              >
                <div class="rounded-[7px] border border-[#fed7aa] bg-[#fff7ed] p-3 text-[#7c2d12]">
                  <div class="text-12-medium">final_content_empty</div>
                  <div class="mt-1 text-12-regular">Agent returned raw output but no final_content.</div>
                  <button
                    type="button"
                    class="mt-2 text-11-medium text-[#9a3412] underline decoration-[#fdba74] underline-offset-2"
                    onClick={() => setRawOpen(!rawOpen())}
                  >
                    Raw output
                  </button>
                  <Show when={rawOpen()}>
                    <pre class="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-[6px] border border-[#fed7aa] bg-[#ffffff]/80 p-2 text-11-mono text-[#7c2d12] [overflow-wrap:anywhere]">
                      {rawContent()}
                    </pre>
                  </Show>
                </div>
              </Show>
              <Show when={thinkingContent().trim()}>
                <div class="mt-3 border-t border-[#eef2f6] pt-2">
                  <button
                    type="button"
                    class="text-11-medium text-[#667085] underline decoration-[#cfd4dc] underline-offset-2 hover:text-[#344054]"
                    onClick={() => setThinkingOpen(!thinkingOpen())}
                  >
                    Thinking
                  </button>
                  <Show when={thinkingOpen()}>
                    <pre class="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-[6px] border border-[#e4e7ec] bg-[#f9fafb] p-2 text-11-mono leading-5 text-[#667085] [overflow-wrap:anywhere]">
                      {thinkingContent()}
                    </pre>
                  </Show>
                </div>
              </Show>
            </>
          }
        >
          <div class="rounded-[7px] border border-[#fecaca] bg-[#ffffff]/70 p-3">
            <div class="text-12-medium text-[#b42318]">执行异常</div>
            <div class="mt-1 font-mono text-11-regular text-[#b42318]">{errorCard()?.error_code ?? "request_failed"}</div>
            <div class="mt-2 whitespace-pre-wrap break-words text-13-regular leading-6 text-[#7a271a] [overflow-wrap:anywhere]">
              {friendlyMessage(errorCard()?.message ?? props.message.content.text)}
            </div>
            <Show when={errorCard()?.recovery_hint}>
              <div class="mt-2 text-11-regular text-[#9b4a3a]">{friendlyHint(errorCard()?.recovery_hint)}</div>
            </Show>
          </div>
        </Show>
        <Show when={props.message.mentions.length}>
          <div
            class="mt-2 text-11-regular"
            classList={{
              "text-white/75": fromUser() && props.message.local_status !== "failed",
              "text-[#667085]": !fromUser() || props.message.local_status === "failed",
            }}
          >
            <For each={props.message.mentions}>{(mention) => <span class="mr-2">@{mention.display ?? mention.agent_id}</span>}</For>
          </div>
        </Show>
        <Show when={props.message.local_status === "pending"}>
          <div class="mt-2 text-11-regular text-white/75">已发送，等待 Agent 回复</div>
        </Show>
        <Show when={props.message.local_status === "failed"}>
          <div class="mt-2 text-11-regular text-[#b42318]">发送失败，请稍后重试</div>
        </Show>
      </div>
    </div>
  )
}

function RichMessageContent(props: { content: string; inverse?: boolean }) {
  const diffBlocks = createMemo(() => extractDiffFences(props.content))
  const markdown = createMemo(() => stripDiffFences(props.content).trim())
  return (
    <div class="min-w-0">
      <Show when={markdown()}>
        {(content) => <MarkdownContent content={content()} inverse={props.inverse} />}
      </Show>
      <For each={diffBlocks()}>
        {(block) => (
          <div class="mt-3 first:mt-0">
            <InlineDiffBlock diff={block.content} title={block.title} />
          </div>
        )}
      </For>
    </div>
  )
}

function MarkdownContent(props: { content: string; inverse?: boolean }) {
  const html = createMemo(() => renderMarkdownHtml(props.content))
  return (
    <div
      class="agenthub-markdown text-13-regular leading-6"
      classList={{ "agenthub-markdown-inverse": props.inverse }}
      innerHTML={html()}
    />
  )
}

function InlineDiffBlock(props: { diff: string; title?: string }) {
  const lines = createMemo(() => props.diff.replace(/\r\n?/g, "\n").split("\n").filter((line) => line.length > 0))
  const additions = createMemo(() => lines().filter((line) => line.startsWith("+") && !line.startsWith("+++")).length)
  const deletions = createMemo(() => lines().filter((line) => line.startsWith("-") && !line.startsWith("---")).length)
  return (
    <div class="overflow-hidden rounded-[7px] border border-[#e4e7ec] bg-[#fbfcfe] text-[#344054]">
      <div class="flex items-center justify-between gap-2 border-b border-[#e4e7ec] bg-[#ffffff] px-3 py-2">
        <div class="min-w-0 truncate text-12-medium">{props.title ?? "Diff Preview"}</div>
        <div class="shrink-0 text-11-regular">
          <span class="text-[#067647]">+{additions()}</span>
          <span class="mx-1 text-[#98a2b3]">/</span>
          <span class="text-[#b42318]">-{deletions()}</span>
        </div>
      </div>
      <div class="max-h-80 overflow-auto">
        <For each={lines()}>
          {(line) => (
            <div
              class="whitespace-pre-wrap break-words px-3 py-0.5 font-mono text-[11px] leading-5"
              classList={{
                "bg-[#ecfdf3] text-[#067647]": line.startsWith("+") && !line.startsWith("+++"),
                "bg-[#fff1f3] text-[#b42318]": line.startsWith("-") && !line.startsWith("---"),
                "bg-[#eef6ff] text-[#175cd3]": line.startsWith("@@") || line.startsWith("+++") || line.startsWith("---"),
              }}
            >
              {line}
            </div>
          )}
        </For>
      </div>
    </div>
  )
}

function ThinkingIndicator(props: { label: string }) {
  return (
    <div class="flex justify-start">
      <div class="rounded-[8px] border border-[#b8ece3] bg-[#f0fdfa] px-4 py-3 shadow-sm">
        <div class="flex items-center gap-3">
          <Spinner class="size-4 text-[#0f766e]" />
          <div>
            <div class="text-13-medium text-[#115e59]">{props.label} 正在思考中</div>
            <div class="mt-0.5 text-11-regular text-[#4b817a]">回复完成后会自动刷新并播放提示音。</div>
          </div>
        </div>
      </div>
    </div>
  )
}

function ErrorCardView(props: { error: ErrorCard }) {
  return (
    <div class="rounded-[8px] border border-[#fecaca] bg-[#fff5f5] p-3 shadow-sm">
      <div class="text-12-medium text-[#b42318]">{friendlyErrorCode(props.error.error_code)}</div>
      <div class="mt-1 font-mono text-11-regular text-[#b42318]">{props.error.error_code}</div>
      <div class="mt-1 text-12-regular text-[#7a271a]">{friendlyMessage(props.error.message)}</div>
      <Show when={props.error.recovery_hint}>
        <div class="mt-2 text-11-regular text-[#9b4a3a]">{friendlyHint(props.error.recovery_hint)}</div>
      </Show>
    </div>
  )
}

function Field(props: { label: string; value: string; type?: string; onInput: (value: string) => void }) {
  return (
    <label class="grid gap-1">
      <span class="text-11-regular text-[#667085]">{props.label}</span>
      <input
        type={props.type ?? "text"}
        class="h-9 rounded-[8px] border border-[#d9dee8] bg-[#ffffff] px-3 text-13-regular text-[#111827] outline-none transition focus:border-[#14b8a6] focus:ring-2 focus:ring-[#99f6e4]/60"
        value={props.value}
        onInput={(event) => props.onInput(event.currentTarget.value)}
      />
    </label>
  )
}

function RuntimeDot(props: { agent: AgentProfile }) {
  const ready = () =>
    props.agent.enabled === true &&
    props.agent.configured === true &&
    props.agent.execution_enabled === true &&
    ["ready", "healthy", "configured"].includes(String(props.agent.health_status))
  return (
    <span
      class="size-2.5 shrink-0 rounded-full"
      classList={{
        "bg-[#12b76a] shadow-[0_0_0_4px_rgba(18,183,106,0.12)]": ready(),
        "bg-[#f04438] shadow-[0_0_0_4px_rgba(240,68,56,0.12)]": !ready() && Boolean(props.agent.error_code),
        "bg-[#98a2b3]": !ready() && !props.agent.error_code,
      }}
      title={ready() ? "可用" : friendlyErrorCode(props.agent.error_code ?? "not_connected")}
    />
  )
}

function Avatar(props: { label: string; initials?: string | null }) {
  return (
    <div class="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-[8px] bg-[#eef2f6] text-12-medium text-[#344054]">
      {(props.initials || props.label.slice(0, 2)).toUpperCase()}
    </div>
  )
}

function ConversationAvatar(props: { title: string; active: boolean }) {
  return (
    <span
      class="flex size-9 shrink-0 items-center justify-center rounded-[8px] text-12-medium shadow-inner"
      classList={{
        "bg-[#0f766e] text-white": props.active,
        "bg-[#e6edf5] text-[#475467]": !props.active,
      }}
    >
      {conversationInitial(props.title)}
    </span>
  )
}

function StatusPill(props: { code: string }) {
  const tone = () => statusTone(props.code)
  return (
    <span
      class="rounded-full px-2 py-1 text-11-regular"
      classList={{
        "bg-[#ecfdf3] text-[#047857]": tone() === "success",
        "bg-[#fff7ed] text-[#b45309]": tone() === "wait",
        "bg-[#fff1f2] text-[#be123c]": tone() === "error",
        "bg-[#eef2f6] text-[#667085]": tone() === "neutral",
      }}
    >
      {statusText(props.code)}
    </span>
  )
}

function EmptyState(props: { title: string; detail: string; compact?: boolean }) {
  return (
    <div
      class="rounded-[8px] border border-dashed border-[#c8d0dc] bg-[#ffffff]/65 text-center"
      classList={{ "p-4": !props.compact, "p-3": props.compact }}
    >
      <div class="text-12-medium text-[#1f2937]">{props.title}</div>
      <div class="mt-1 text-12-regular text-[#667085]">{props.detail}</div>
    </div>
  )
}

function InlineLoading(props: { label: string }) {
  return (
    <div class="flex items-center justify-center gap-2 px-3 py-4 text-12-regular text-[#667085]">
      <Spinner class="size-3" />
      {props.label}
    </div>
  )
}

function Tag(props: { children: string }) {
  return <span class="rounded-full bg-[#eef2f6] px-2 py-0.5 text-11-regular text-[#667085]">{props.children}</span>
}

function isMarkdownPreview(preview: ArtifactPreview) {
  return (
    preview.mime_type === "text/markdown" ||
    preview.type === "markdown_doc" ||
    preview.type === "document" ||
    preview.type === "word_doc" ||
    preview.type === "presentation"
  )
}

function diffPrefix(type?: string | null) {
  if (type === "addition") return "+"
  if (type === "deletion") return "-"
  return " "
}

function extractDiffFences(content: string) {
  const blocks: Array<{ title?: string; content: string }> = []
  const pattern = /```(?:diff|patch)\s*\n([\s\S]*?)```/gi
  let match: RegExpExecArray | null
  while ((match = pattern.exec(content)) !== null) {
    const diff = match[1]?.trimEnd()
    if (!diff) continue
    const firstFile = diff
      .split(/\r?\n/)
      .find((line) => line.startsWith("+++ ") || line.startsWith("diff --git "))
      ?.replace(/^(\+\+\+ b\/|diff --git a\/)/, "")
      .trim()
    blocks.push({ title: firstFile || "Diff Preview", content: diff })
  }
  return blocks
}

function stripDiffFences(content: string) {
  return content.replace(/```(?:diff|patch)\s*\n[\s\S]*?```/gi, "").trim()
}

function renderMarkdownHtml(content: string) {
  const html = markdownInstance.parse(content) as string
  return sanitizeMarkdownHtml(html)
}

function sanitizeMarkdownHtml(html: string) {
  if (typeof DOMParser === "undefined") return escapeHtml(html)
  const document = new DOMParser().parseFromString(html, "text/html")
  const allowedTags = new Set([
    "A",
    "BLOCKQUOTE",
    "BR",
    "CODE",
    "DEL",
    "DIV",
    "EM",
    "H1",
    "H2",
    "H3",
    "H4",
    "H5",
    "H6",
    "HR",
    "LI",
    "OL",
    "P",
    "PRE",
    "SPAN",
    "STRONG",
    "TABLE",
    "TBODY",
    "TD",
    "TH",
    "THEAD",
    "TR",
    "UL",
  ])
  const walk = (node: Node) => {
    for (const child of Array.from(node.childNodes)) {
      if (child.nodeType === Node.ELEMENT_NODE) {
        const element = child as HTMLElement
        if (!allowedTags.has(element.tagName)) {
          element.replaceWith(...Array.from(element.childNodes))
          continue
        }
        for (const attribute of Array.from(element.attributes)) {
          const name = attribute.name.toLowerCase()
          if (element.tagName === "A" && name === "href" && safeHref(attribute.value)) continue
          element.removeAttribute(attribute.name)
        }
        if (element.tagName === "A") {
          element.setAttribute("target", "_blank")
          element.setAttribute("rel", "noreferrer")
        }
      }
      walk(child)
    }
  }
  walk(document.body)
  return document.body.innerHTML
}

function safeHref(value: string) {
  return /^(https?:|mailto:|#|\/)/i.test(value)
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
}

function safeResource<T>(read: () => T): T | undefined {
  try {
    return read()
  } catch {
    return undefined
  }
}

function firstApiError(...errors: unknown[]) {
  for (const error of errors) {
    if (error instanceof AgentHubApiError) return error
  }
  return null
}

function errorToApiError(error: unknown) {
  if (error instanceof AgentHubApiError) return error
  return new AgentHubApiError({
    error_code: "request_failed",
    message: error instanceof Error ? error.message : "AgentHub 请求失败。",
    recovery_hint: "请检查后端服务日志后重试。",
  })
}

function errorToCard(error: unknown): ErrorCard {
  const apiError = errorToApiError(error)
  return {
    card_type: "send_failure",
    error_code: apiError.error_code,
    message: apiError.message,
    recovery_hint: apiError.recovery_hint,
  }
}

function normalizeMessageErrorCard(message: Message): ErrorCard | null {
  const raw = message.content.error_card
  if (raw && typeof raw === "object") {
    const card = raw as Partial<ErrorCard>
    return {
      card_type: card.card_type ?? "send_failure",
      error_code: card.error_code ?? String(message.content.error_code ?? "request_failed"),
      message: card.message ?? String(message.content.text ?? "请求没有成功，请检查后端状态。"),
      recovery_hint: card.recovery_hint ?? (typeof message.content.recovery_hint === "string" ? message.content.recovery_hint : null),
      target_agent_id: card.target_agent_id,
      run_id: card.run_id,
    }
  }
  if (message.message_type !== "error") return null
  return {
    card_type: "send_failure",
    error_code: String(message.content.error_code ?? "request_failed"),
    message: String(message.content.text ?? "请求没有成功，请检查后端状态。"),
    recovery_hint: typeof message.content.recovery_hint === "string" ? message.content.recovery_hint : null,
  }
}

function collectArtifactCards(messages: Message[], artifacts: Artifact[]) {
  const fromMessages = messages.flatMap((message) => message.artifact_cards ?? [])
  const artifactIds = new Set(fromMessages.map((artifact) => artifact.artifact_id))
  const directArtifacts = artifacts.filter((artifact) => artifact.type !== "source_diff" && artifact.type !== "diff_preview")
  return [...fromMessages, ...directArtifacts.filter((artifact) => !artifactIds.has(artifact.id))]
}

function collectDiffCards(messages: Message[], artifacts: Artifact[]) {
  const fromMessages = messages.flatMap((message) => message.diff_cards ?? [])
  const diffIds = new Set(fromMessages.map((artifact) => artifact.artifact_id))
  const directDiffs = artifacts.filter((artifact) => artifact.type === "source_diff" || artifact.type === "diff_preview")
  return [...fromMessages, ...directDiffs.filter((artifact) => !diffIds.has(artifact.id))]
}

function artifactId(artifact: Artifact | ArtifactCardData) {
  return "id" in artifact ? artifact.id : artifact.artifact_id
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : null
}

function agentName(agents: AgentProfile[], agentId?: string | null) {
  if (!agentId) return null
  return agents.find((agent) => agent.id === agentId)?.name ?? null
}

function isAgentReady(agent: AgentProfile) {
  return (
    agent.enabled === true &&
    agent.configured === true &&
    agent.execution_enabled === true &&
    ["ready", "healthy", "configured"].includes(String(agent.health_status))
  )
}

function isPrivateConversationMode(mode?: string) {
  return mode === "private" || mode === "private_agent" || mode === "single"
}

function uniqueMentions(mentions: MentionPayload[]) {
  const seen = new Set<string>()
  return mentions.filter((mention) => {
    if (!mention.agent_id || seen.has(mention.agent_id)) return false
    seen.add(mention.agent_id)
    return true
  })
}

function detectMentionQuery(value: string) {
  const atIndex = value.lastIndexOf("@")
  if (atIndex < 0) return null
  const tail = value.slice(atIndex + 1)
  if (tail.includes("\n") || tail.endsWith(" ") || tail.length > 48) return null
  return tail.trim().toLowerCase()
}

function insertMentionToken(value: string, name: string) {
  const token = `@${name} `
  const atIndex = value.lastIndexOf("@")
  if (atIndex >= 0) {
    const before = value.slice(0, atIndex)
    const tail = value.slice(atIndex + 1)
    if (!tail.includes("\n") && !tail.endsWith(" ") && tail.length <= 48) {
      return `${before}${token}`
    }
  }
  return value.trim() ? `${value.trimEnd()} ${token}` : token
}

function stripAgentMentionTokens(value: string, agents: AgentProfile[]) {
  let next = value
  for (const agent of agents) {
    const name = agent.name.trim()
    if (!name) continue
    next = next.replace(new RegExp(`(^|\\s)@${escapeRegExp(name)}\\s*`, "g"), "$1")
  }
  return next.replace(/[ \t]{2,}/g, " ").trimStart()
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

function collectMentionsFromDraft(text: string, selected: MentionPayload[], agents: AgentProfile[]) {
  const detected = agents
    .filter((agent) => text.includes(`@${agent.name}`))
    .map((agent) => ({ agent_id: agent.id, display: agent.name }))
  return uniqueMentions([...selected, ...detected])
}

function makeLocalMessage(input: {
  id: string
  conversationId: string
  text: string
  mentions: MentionPayload[]
  status: LocalMessage["local_status"]
}): LocalMessage {
  return {
    id: input.id,
    conversation_id: input.conversationId,
    sender_type: "user",
    sender_id: "local-user",
    message_type: "chat",
    content: { text: input.text },
    mentions: input.mentions,
    references: [],
    created_at: new Date().toISOString(),
    local_status: input.status,
  }
}

function responseToMessages(response: SendMessageResponse, fallback: LocalMessage): LocalMessage[] {
  const messages: LocalMessage[] = []
  if (response.message) messages.push({ ...response.message, local_status: "sent" })
  else messages.push({ ...fallback, local_status: "sent" })
  if (response.assistant_message) messages.push({ ...response.assistant_message, local_status: "sent" })
  if (response.assistant_messages?.length) {
    messages.push(...response.assistant_messages.map((message) => ({ ...message, local_status: "sent" as const })))
  }
  if (response.error_message) messages.push({ ...response.error_message, local_status: "sent" })
  if (response.error_messages?.length) {
    messages.push(...response.error_messages.map((message) => ({ ...message, local_status: "sent" as const })))
  }
  return messages
}

function errorMessageFromCard(error: ErrorCard, conversationId: string, replyToId: string): LocalMessage {
  return {
    id: `local-error-${replyToId}-${error.target_agent_id ?? error.error_code}`,
    conversation_id: conversationId,
    sender_type: "assistant",
    sender_id: error.target_agent_id ?? "orchestrator",
    message_type: "error",
    content: {
      text: error.message,
      error_card: error,
      error_code: error.error_code,
      recovery_hint: error.recovery_hint ?? null,
    },
    mentions: [],
    references: [],
    reply_to_id: replyToId,
    created_at: new Date().toISOString(),
    local_status: "sent",
  }
}

function mergeMessages(persisted: Message[], local: LocalMessage[]) {
  const ids = new Set<string>()
  const merged: LocalMessage[] = []
  for (const message of persisted) {
    ids.add(message.id)
    merged.push(message as LocalMessage)
  }
  for (const message of local) {
    if (ids.has(message.id)) continue
    ids.add(message.id)
    merged.push(message)
  }
  return merged
    .map((message) => message as LocalMessage)
    .sort((a, b) => timeValue(a.created_at) - timeValue(b.created_at))
}

function timeValue(value?: string) {
  const parsed = Date.parse(value ?? "")
  return Number.isFinite(parsed) ? parsed : 0
}

function formatConversationTime(value?: string | null) {
  const parsed = Date.parse(value ?? "")
  if (!Number.isFinite(parsed)) return "刚刚"
  const date = new Date(parsed)
  const today = new Date()
  const sameDay = date.toDateString() === today.toDateString()
  if (sameDay) return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  return date.toLocaleDateString([], { month: "2-digit", day: "2-digit" })
}

function conversationInitial(title: string) {
  const first = title.trim().charAt(0)
  return first ? first.toUpperCase() : "A"
}

function statusText(code: string) {
  const labels: Record<string, string> = {
    not_connected: "未连接",
    waiting_for_backend: "同步中",
    no_runtime_result: "暂无结果",
    api_unreachable: "后端离线",
    api_connected: "后端已连接",
    runtime_not_ready: "Agent runtime 不可用",
    idle: "就绪",
    request_failed: "请求失败",
    retrying: "重试中",
  }
  return labels[code] ?? statusLabel(code)
}

function statusTone(code: string) {
  if (code === "api_connected" || code === "succeeded" || code === "completed" || code === "ready") return "success"
  if (code === "api_unreachable" || code === "request_failed" || code === "failed" || code === "not_connected") return "error"
  if (code === "waiting_for_backend" || code === "running" || code === "pending" || code === "retrying") return "wait"
  return "neutral"
}

function modeLabel(mode?: string) {
  const labels: Record<string, string> = {
    private: "Agent 私聊",
    single: "单人对话",
    group: "群组对话",
    private_agent: "私有 Agent 对话",
    group_agent: "群组 Agent 对话",
  }
  return mode ? labels[mode] ?? "协作对话" : "未选择对话"
}

function senderLabel(sender: string) {
  const labels: Record<string, string> = {
    user: "你",
    assistant: "Agent",
    orchestrator: "调度器",
    system: "系统",
  }
  return labels[sender] ?? "消息"
}

function isLocalAgentProvider(provider?: string | null) {
  return provider === "codex" || provider === "anthropic" || provider === "opencode"
}

function adapterKindForProvider(provider: string) {
  if (provider === "codex") return "codex_cli"
  if (provider === "anthropic") return "claude_code_cli"
  if (provider === "opencode") return "opencode_http"
  return "custom_openai"
}

function providerLabel(provider?: string | null) {
  const labels: Record<string, string> = {
    custom_openai: "自定义模型",
    openai: "兼容模型",
    anthropic: "claude",
    claude: "claude",
    codex: "Codex",
    opencode: "AgentHub Coding Agent",
  }
  if (!provider) return "未配置模型"
  return labels[provider] ?? "模型服务"
}

function providerInputLabel(provider?: string | null) {
  if (!provider) return "自定义模型"
  const label = providerLabel(provider)
  return label === "模型服务" ? provider : label
}

function providerValue(label: string) {
  const values: Record<string, string> = {
    自定义模型: "custom_openai",
    兼容模型: "openai",
    claude: "anthropic",
    Codex: "codex",
    代码模型: "opencode",
  }
  return values[label] ?? label
}

function capabilityLabel(tag?: string | null) {
  const labels: Record<string, string> = {
    analysis: "分析",
    chat: "对话",
    code: "代码",
    deploy: "发布",
    direct_response: "直接回复",
    implementation: "实现",
    model: "模型",
    review: "审查",
    workspace: "工作区",
  }
  if (!tag) return "能力"
  return labels[tag] ?? "能力"
}

function capabilityValue(label: string) {
  const values: Record<string, string> = {
    分析: "analysis",
    对话: "chat",
    代码: "code",
    发布: "deploy",
    直接回复: "direct_response",
    实现: "implementation",
    模型: "model",
    审查: "review",
    工作区: "workspace",
  }
  return values[label] ?? label
}

function statusLabel(status?: string | null) {
  const labels: Record<string, string> = {
    blocked: "已阻塞",
    assigned: "待执行",
    completed: "已完成",
    configured: "已配置",
    created: "已创建",
    failed: "失败",
    healthy: "健康",
    pending: "等待中",
    published: "已发布",
    publishing: "发布中",
    ready: "可用",
    running: "进行中",
    succeeded: "已完成",
    retrying: "重试中",
  }
  if (!status) return "未知"
  return labels[status] ?? "进行中"
}

function runModeLabel(mode?: string | null) {
  const labels: Record<string, string> = {
    direct_response: "直接回复",
    orchestrated: "调度执行",
    planned_step: "计划阶段",
    review: "审查",
  }
  if (!mode) return "执行"
  return labels[mode] ?? "执行"
}

function artifactTypeLabel(type?: string | null) {
  const labels: Record<string, string> = {
    document: "文档",
    markdown_doc: "Markdown",
    word_doc: "Word 文档",
    presentation: "PPT 演示",
    diff_preview: "变更预览",
    source_diff: "代码变更",
    web_preview: "网页预览",
    text: "文本",
  }
  if (!type) return "产物"
  return labels[type] ?? "产物"
}

function friendlyErrorCode(code?: string | null) {
  const labels: Record<string, string> = {
    api_unreachable: "后端服务不可达",
    not_connected: "未连接",
    runtime_not_ready: "Agent runtime 不可用",
    missing_credentials: "缺少凭据",
    opencode_server_unavailable: "AgentHub 本地编码运行时不可用",
    turn_router_not_configured: "调度器未配置",
    provider_not_configured: "模型服务未配置",
    backend_network_failed: "网络连接失败",
    backend_rate_limited: "模型服务限流",
    adapter_timeout: "执行超时",
    request_failed: "请求失败",
  }
  if (!code) return "未知错误"
  return labels[code] ?? "执行异常"
}

function friendlyHint(hint?: string | null) {
  if (!hint) return ""
  if (hint.includes("Start")) return "请先启动 AgentHub 后端服务，然后重试。"
  if (hint.includes("logs")) return "请查看后端日志后重试。"
  if (hasChinese(hint)) return hint
  return "请根据后端日志处理后重试。"
}

function friendlyMessage(message?: string | null) {
  if (!message) return "请求没有成功，请稍后重试。"
  if (hasChinese(message)) return message
  const normalized = message.toLowerCase()
  if (normalized.includes("unreachable")) return "无法连接 AgentHub 后端服务。"
  if (normalized.includes("failed")) return "请求执行失败，请稍后重试。"
  return "请求没有成功，请检查后端服务状态。"
}

function hasChinese(value: string) {
  return /[\u4e00-\u9fff]/.test(value)
}
