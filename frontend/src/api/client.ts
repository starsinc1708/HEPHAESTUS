import type { EffectiveConfig, StateSnapshot, IterDetails, IterSummary, AgentActivity, BranchActionResponse, ReorderResult, ScanStatus, ScanListItem, ScanFinding, Decision, ParsedEvent, ItemPatch, AddItemRequest, DriverStartOptions, IterReviewsResponse, ScanStartRequest, RepoProfile, ProcessManagerStatus, MergePreflightResponse, PromptSummary, WsPromptDetail, DirEntry, MergeJob, MergeJobStatus, Goal, IntegrationProvider, IntegrationConnectResult, Idea, InsightsSession, AgentJob, VerifyOutcome, ProviderCatalogEntry, CliInfo, Connection, DriverStatus, TaskConversations, ConversationResponse, Worktree, CostSummary, RunSummary, FsBrowseResponse } from '@/types/api'

/* ── ApiError class ── */
export class ApiError extends Error {
  readonly status: number
  readonly statusText: string
  readonly body: string

  constructor(status: number, statusText: string, body: string) {
    super(`API ${status} ${statusText}: ${body.slice(0, 300)}`)
    this.name = 'ApiError'
    this.status = status
    this.statusText = statusText
    this.body = body
  }
}

/* ── Auth header injection (Phase 5 placeholder) ── */
function authHeaders(): Record<string, string> {
  return {}
}

/* ── Generic typed fetch with AbortController timeout ── */
const DEFAULT_TIMEOUT_MS = 30_000
// Long-running endpoints that drive a real LLM agent or external git/CLI work
// (plan a goal, AI-merge, ideas, insights, rebuild map, PR/issue sync).
// These run synchronously server-side and routinely exceed 30s.
const AGENT_TIMEOUT_MS = 600_000

const pendingRequests = new Map<string, Promise<unknown>>()

function dedupeKey(path: string, init: RequestInit): string {
  const method = (init.method ?? 'GET').toUpperCase()
  return `${method}:${path}`
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const key = dedupeKey(path, init)
  const existing = pendingRequests.get(key)
  if (existing) return existing as Promise<T>

  const promise = _fetch<T>(path, init, timeoutMs)
  pendingRequests.set(key, promise)

  try {
    const result = await promise
    return result
  } finally {
    pendingRequests.delete(key)
  }
}

async function _fetch<T>(path: string, init: RequestInit, timeoutMs: number): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const res = await fetch(path, {
      ...init,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
        ...(init.headers as Record<string, string> | undefined),
      },
    })
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      throw new ApiError(res.status, res.statusText, body)
    }
    const ct = res.headers.get('content-type') ?? ''
    if (ct.includes('application/json')) {
      return res.json() as Promise<T>
    }
    return res.text() as unknown as T
  } catch (e: unknown) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new ApiError(0, 'Timeout', `Request to ${path} timed out after ${timeoutMs}ms`)
    }
    throw e
  } finally {
    clearTimeout(timer)
  }
}

/* ── Typed API surface ── */

export const api = {
  // State
  getState: () => request<StateSnapshot>('/api/state'),

  // Task / item
  getItem: (id: string) => request<StateSnapshot>('/api/state'), // filter client-side
  moveTop: (id: string) => request<{ ok: boolean }>(`/api/queue/${id}/move-top`, { method: 'POST' }),
  deleteItem: (id: string) => request<{ ok: boolean }>(`/api/queue/${id}`, { method: 'DELETE' }),
  requeueItem: (id: string) => request<{ ok: boolean; was: string }>(`/api/queue/${id}/requeue`, { method: 'POST' }),
  requeueFailed: () =>
    request<{ ok: boolean; requeued: string[]; count: number }>('/api/v1/tasks/requeue-failed', { method: 'POST' }),
  patchItem: (id: string, patch: ItemPatch) =>
    request<{ ok: boolean }>(`/api/queue/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  addItem: (item: AddItemRequest) =>
    request<{ ok: boolean; id: string }>('/api/queue/add', { method: 'POST', body: JSON.stringify(item) }),
  getTaskChecks: (id: string) =>
    request<{ ok: boolean; verifyOutcome: VerifyOutcome | null; scopeExtra?: string[] }>(`/api/v1/tasks/${id}/checks`),
  setTaskTags: (id: string, tags: string[]) =>
    request<{ ok: boolean }>(`/api/v1/tasks/${encodeURIComponent(id)}/tags`, { method: 'PATCH', body: JSON.stringify({ tags }) }),

  // Iter details
  iterDetails: (dir: string) => request<IterDetails>(`/api/iter/${dir}/details`),
  iterDiff: (dir: string) => request<string>(`/api/iter/${dir}/diff`),
  iterVerify: (dir: string) => request<string>(`/api/iter/${dir}/verify`),
  iterReviews: (dir: string) => request<IterReviewsResponse>(`/api/iter/${dir}/reviews`),
  iterEvents: (dir: string, stream: string = 'primary') =>
    // Backend returns { events, stream } — unwrap to the array the UI binds to.
    request<{ events: ParsedEvent[]; stream: string }>(`/api/iter/${dir}/raw?stream=${stream}`)
      .then(r => r.events ?? []),

  // Conversation viewer (#5)
  taskConversations: (id: string) =>
    request<TaskConversations>(`/api/v1/tasks/${encodeURIComponent(id)}/conversations`),
  iterConversation: (dir: string, stream: string) =>
    request<ConversationResponse>(
      `/api/iter/${encodeURIComponent(dir)}/conversation?stream=${encodeURIComponent(stream)}`,
    ).then(r => r.messages ?? []),

  // History
  history: () => request<{ iters: IterSummary[]; total: number; page: number; per_page: number }>('/api/history').then(r => r.iters ?? []),

  // Config
  getConfig: () => request<{ effective: EffectiveConfig; overrides: Record<string, string> }>('/api/config'),
  putConfig: (overrides: Record<string, string>) =>
    request<{ ok: boolean }>('/api/config', { method: 'PUT', body: JSON.stringify(overrides) }),
  configPreset: (name: string) =>
    request<{ ok: boolean; applied: Record<string, string> }>('/api/config/preset', { method: 'POST', body: JSON.stringify({ name }) }),

  // Driver
  driverStart: (opts?: DriverStartOptions) =>
    request<{ ok: boolean }>('/api/driver/start', { method: 'POST', body: JSON.stringify(opts ?? {}) }),
  driverStop: () => request<{ ok: boolean }>('/api/driver/stop', { method: 'POST' }),
  driverKill: () => request<{ ok: boolean }>('/api/driver/kill', { method: 'POST' }),
  driverStatus: () => request<DriverStatus>('/api/driver/status'),
  driverPause: () => request<{ ok: boolean; paused: boolean }>('/api/driver/pause', { method: 'POST' }),
  driverResume: () => request<{ ok: boolean; paused: boolean }>('/api/driver/resume', { method: 'POST' }),
  // FEAT-005: finished-run history (newest first). offset/limit are optional.
  driverRuns: (offset = 0, limit = 0) =>
    request<{ ok: boolean; runs: RunSummary[]; total: number; offset: number; limit: number }>(
      `/api/driver/runs?offset=${offset}&limit=${limit}`,
    ),

  // Send-to-run / queue management (Sub-project #3 auto-driver)
  runTask: (id: string) =>
    request<{ ok: boolean; status: string }>(`/api/v1/tasks/${encodeURIComponent(id)}/run`, { method: 'POST' }),
  runTasks: (ids: string[]) =>
    request<{ ok: boolean; queued: string[] }>('/api/v1/tasks/run', { method: 'POST', body: JSON.stringify({ ids }) }),
  unqueueTask: (id: string) =>
    request<{ ok: boolean; status: string }>(`/api/v1/tasks/${encodeURIComponent(id)}/unqueue`, { method: 'POST' }),
  // Dependency editor (#4): PATCH the full new dependsOn array. Returns 400 (ApiError)
  // on a self/cycle/unknown attempt — the body carries { error, offending }.
  patchDeps: (id: string, dependsOn: string[]) =>
    request<{ ok: boolean; id?: string; dependsOn?: string[]; error?: string; offending?: string }>(
      `/api/v1/tasks/${encodeURIComponent(id)}/deps`,
      { method: 'PATCH', body: JSON.stringify({ dependsOn }) }),

  // Goals (Epic 2 / #7) — decompose is now an async agent-job: returns {jobId, kind}.
  // Poll via getAgentJob / useAgentJob; the job lands the task tree as `pending`.
  decomposeGoal: (title: string, description = '', maxTasks?: number) =>
    request<{ ok: boolean; jobId: string; kind: string }>('/api/v1/goals', {
      method: 'POST',
      body: JSON.stringify(
        maxTasks && maxTasks > 0 ? { title, description, maxTasks } : { title, description },
      ),
    }),
  goalTemplates: () =>
    request<{ ok: boolean; templates: { id: string; title: string; description: string }[] }>(
      '/api/v1/goals/templates',
    ),
  listGoals: () =>
    request<{ ok: boolean; goals: Goal[] }>('/api/v1/goals'),
  deleteGoal: (id: string) =>
    request<{ ok: boolean }>(`/api/v1/goals/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  // Branches
  branchAction: (name: string, action: 'merge' | 'requeue' | 'discard') =>
    request<BranchActionResponse>(`/api/branch/${name}/${action}`, { method: 'POST' }),

  // Worktrees (sub-project #6)
  listWorktrees: () => request<{ ok: boolean; worktrees: Worktree[] }>('/api/v1/worktrees'),
  worktreeDiff: (name: string) => request<string>(`/api/v1/branches/${encodeURIComponent(name)}/diff`),

  // Merge (Stage 3 / D11)
  mergePreflight: (name: string) =>
    request<{ ok: boolean } & MergePreflightResponse>(
      `/api/v1/branches/${encodeURIComponent(name)}/merge-preflight`,
    ),
  // AI-powered merge jobs (Epic 1)
  startMerge: (branch: string, opts: { push?: boolean; aiResolve?: boolean; autoAccept?: boolean }) =>
    request<{ ok: boolean; jobId: string; status: MergeJobStatus }>(
      `/api/v1/branches/${encodeURIComponent(branch)}/merge`,
      { method: 'POST', body: JSON.stringify(opts) },
      AGENT_TIMEOUT_MS,
    ),
  getMergeJob: (jobId: string) =>
    request<MergeJob & { ok: boolean }>(`/api/v1/merge-jobs/${encodeURIComponent(jobId)}`),
  mergeJobVerifyLog: (jobId: string) =>
    request<{ ok: boolean; log: string }>(`/api/v1/merge-jobs/${encodeURIComponent(jobId)}/verify-log`),
  getActiveMergeJob: () =>
    request<{ ok: boolean; job: MergeJob | null }>('/api/v1/active-merge-job'),
  acceptMerge: (jobId: string, push: boolean) =>
    request<{ ok: boolean; error?: string }>(`/api/v1/merge-jobs/${encodeURIComponent(jobId)}/accept`, {
      method: 'POST', body: JSON.stringify({ push }),
    }, AGENT_TIMEOUT_MS),
  rejectMerge: (jobId: string) =>
    request<{ ok: boolean }>(`/api/v1/merge-jobs/${encodeURIComponent(jobId)}/reject`, {
      method: 'POST', body: JSON.stringify({}),
    }),

  // Logs
  logTail: () => request<StateSnapshot>('/api/state').then((s: StateSnapshot) => s.log_tail),

  // Agent activity
  agentActivity: () => request<AgentActivity>('/api/agents/activity'),

  // Scans
  scanStatus: () => request<ScanStatus>('/api/scan/status'),
  scanLog: (dirname: string) =>
    request<{ ok: boolean; lines: string[] }>(`/api/scan/log/${encodeURIComponent(dirname)}`),
  scanList: () => request<{ scans: ScanListItem[] }>('/api/scan/list').then(r => r.scans ?? []),
  scanStart: (opts: ScanStartRequest) =>
    request<{ ok: boolean; session?: string; error?: string }>('/api/scan/start', { method: 'POST', body: JSON.stringify(opts) }),
  scanImport: (dirname: string, ids: string[] = []) =>
    request<{ ok: boolean; added: string[]; skipped: string[] }>(`/api/scan/import/${dirname}`, { method: 'POST', body: JSON.stringify({ ids }) }),
  scanResults: (dirname: string) =>
    request<{ ok: boolean; proposals?: ScanFinding[]; n_unique?: number; error?: string }>(
      `/api/scan/results/${encodeURIComponent(dirname)}`),
  // #7 — import selected scan findings (by id) onto the board as `pending` tasks.
  scansImport: (ids: string[], dirname?: string) =>
    request<{ ok: boolean; added: string[]; skipped: string[]; error?: string }>(
      '/api/v1/scans/import',
      { method: 'POST', body: JSON.stringify(dirname ? { ids, dirname } : { ids }) }),

  // Decisions
  decisions: () => request<Decision[]>('/api/decisions'),

  // Workspaces
  listWorkspaces: () =>
    request<{ ok: boolean; workspaces: RepoProfile[]; activeId: string | null }>('/api/v1/workspaces'),
  onboard: (repoPath: string, name?: string) =>
    request<{ ok: boolean; workspace: RepoProfile }>('/api/v1/workspaces', {
      method: 'POST', body: JSON.stringify({ repoPath, name }),
    }),
  getWorkspace: (id: string) =>
    request<{ ok: boolean; workspace: RepoProfile; onboarding: ProcessManagerStatus }>(`/api/v1/workspaces/${id}`),
  updateWorkspace: (id: string, patch: Partial<RepoProfile>) =>
    request<{ ok: boolean; workspace: RepoProfile }>(`/api/v1/workspaces/${id}`, {
      method: 'PUT', body: JSON.stringify(patch),
    }),
  activateWorkspace: (id: string) =>
    request<{ ok: boolean; activeId: string }>(`/api/v1/workspaces/${id}/activate`, { method: 'POST' }),
  listWorkspaceDirs: (id: string, under = '') =>
    request<{ ok: boolean; under: string; dirs: DirEntry[] }>(
      `/api/v1/workspaces/${id}/dirs?under=${encodeURIComponent(under)}`),

  // Agent connections & catalog (global model endpoints) + CLI detection
  getClis: () =>
    request<{ ok: boolean; clis: Record<string, CliInfo> }>('/api/v1/clis'),
  getConnectionPresets: () =>
    request<{ ok: boolean; catalog: ProviderCatalogEntry[] }>('/api/v1/connection-presets'),
  getConnections: () =>
    request<{ connections: Connection[] }>('/api/v1/connections'),
  createConnection: (body: { provider: string; engine: string; authMethod: string; model: string; key?: string; label?: string }) =>
    request<{ ok: boolean; connection: Connection }>('/api/v1/connections', {
      method: 'POST', body: JSON.stringify(body),
    }),
  deleteConnection: (id: string) =>
    request<{ ok: boolean }>(`/api/v1/connections/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  testConnection: (id: string) =>
    request<{ ok: boolean; status: 'connected' | 'failed'; error: string | null }>(
      `/api/v1/connections/${encodeURIComponent(id)}/test`, { method: 'POST' }, AGENT_TIMEOUT_MS),

  // Cost dashboard (FEAT-001)
  getCostSummary: () =>
    request<CostSummary>('/api/v1/costs'),

  // Prompts — global templates + per-workspace overrides (<repo>/.hephaestus/prompts)
  listPrompts: () =>
    request<{ prompts: PromptSummary[] }>('/api/v1/prompts'),
  listWsPrompts: (wsId: string) =>
    request<{ ok: boolean; prompts: PromptSummary[] }>(`/api/v1/workspaces/${wsId}/prompts`),
  getWsPrompt: (wsId: string, name: string) =>
    request<{ ok: boolean } & WsPromptDetail>(
      `/api/v1/workspaces/${wsId}/prompts/${encodeURIComponent(name)}`),
  putWsPrompt: (wsId: string, name: string, content: string) =>
    request<{ ok: boolean } & WsPromptDetail>(
      `/api/v1/workspaces/${wsId}/prompts/${encodeURIComponent(name)}`,
      { method: 'PUT', body: JSON.stringify({ content }) }),
  resetWsPrompt: (wsId: string, name: string) =>
    request<{ ok: boolean } & WsPromptDetail>(
      `/api/v1/workspaces/${wsId}/prompts/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  // Reorder (Stage 2)
  reorderTask: (order: string[]) =>
    request<ReorderResult>(`/api/v1/tasks/${order[0] ?? '_'}/reorder`, {
      method: 'PATCH',
      body: JSON.stringify({ order }),
    }),

  // Workspace memory (Stage 2)
  getWorkspaceMemory: (wsId: string, doc: string) =>
    request<{ ok: boolean; content: string }>(`/api/v1/workspaces/${wsId}/memory/${doc}`),
  putWorkspaceMemory: (wsId: string, doc: string, content: string) =>
    request<{ ok: boolean }>(`/api/v1/workspaces/${wsId}/memory/${doc}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),

  // Integrations (Epic 3 + v2 #8 UI connect)
  listIntegrations: () =>
    request<{ ok: boolean; providers: IntegrationProvider[]; default: string | null }>('/api/v1/integrations'),
  // connect/verify are simple HTTPS probes (server bounds the upstream call at
  // ~10s) — use the default 30s timeout, not the agent timeout.
  connectIntegration: (name: string, body: { token: string; host?: string }) =>
    request<IntegrationConnectResult>(
      `/api/v1/integrations/${encodeURIComponent(name)}/connect`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
  verifyIntegration: (name: string) =>
    request<IntegrationConnectResult>(
      `/api/v1/integrations/${encodeURIComponent(name)}/verify`,
      { method: 'POST' },
    ),
  disconnectIntegration: (name: string) =>
    request<{ ok: boolean; name: string }>(
      `/api/v1/integrations/${encodeURIComponent(name)}/disconnect`,
      { method: 'POST' },
    ),
  importIssues: (name: string, label: string) =>
    request<{ ok: boolean; added: string[]; skipped: string[]; errors: string[] }>(
      `/api/v1/integrations/${encodeURIComponent(name)}/import`,
      { method: 'POST', body: JSON.stringify({ label }) },
      AGENT_TIMEOUT_MS,
    ),
  createPr: (branch: string, opts?: { provider?: string; title?: string; body?: string; base?: string }) =>
    request<{ ok: boolean; number: number; url: string }>(
      '/api/v1/integrations/pr',
      { method: 'POST', body: JSON.stringify({ branch, ...opts }) },
      AGENT_TIMEOUT_MS,
    ),

  // Ideas (Epic 4)
  generateIdeas: (categories?: string[]) =>
    request<{ ok: boolean; jobId: string; kind: string }>('/api/v1/ideas/generate', {
      method: 'POST', body: JSON.stringify(categories !== undefined ? { categories } : {}),
    }),
  listIdeas: () =>
    request<{ ok: boolean; ideas: Idea[] }>('/api/v1/ideas'),
  importIdeas: (ids: string[]) =>
    request<{ ok: boolean; added: number }>('/api/v1/ideas/import', {
      method: 'POST', body: JSON.stringify({ ids }),
    }),

  // Insights (Epic 4)
  askInsights: (question: string, sessionId?: string) =>
    request<{ ok: boolean; sessionId: string; iterDir: string; answer: string; modifiedFiles: string[] }>(
      '/api/v1/insights/ask',
      { method: 'POST', body: JSON.stringify(sessionId !== undefined ? { question, sessionId } : { question }) },
      AGENT_TIMEOUT_MS,
    ),
  listInsightsSessions: () =>
    request<{ ok: boolean; sessions: InsightsSession[] }>('/api/v1/insights/sessions'),
  getInsightsSession: (id: string) =>
    request<{ ok: boolean; session: InsightsSession }>(`/api/v1/insights/sessions/${encodeURIComponent(id)}`),
  rebuildMap: () =>
    request<{ ok: boolean; jobId: string; kind: string }>('/api/v1/insights/rebuild-map', { method: 'POST' }),

  // Agent Jobs — generic status + result polling
  getAgentJob: (id: string) =>
    request<{ ok: boolean } & AgentJob>('/api/v1/agent-jobs/' + encodeURIComponent(id)),

  // Filesystem browser — list server/container directories for the onboarding repo picker.
  browseFs: (path = '') =>
    request<FsBrowseResponse>(`/api/v1/fs/browse?path=${encodeURIComponent(path)}`),
}
