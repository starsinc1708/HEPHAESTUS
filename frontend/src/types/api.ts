/* API type definitions — mirrors the Python dashboard server */

// ── Items ──

export type ItemStatus =
  | 'pending'
  | 'queued'
  | 'in_progress'
  | 'in_review'
  | 'done'
  | 'merged'
  | 'needs_revision'
  | 'discarded'
  | `failed:${string}`

export type Severity = 'bug' | 'security' | 'perf' | 'quality' | 'test' | 'docs' | null

export interface Item {
  id: string
  title: string
  status: ItemStatus
  attempts: number
  proposal: string
  why: string
  acceptance: string
  touches: string[]
  branch: string | null
  lastIter: string | null
  previousBranches: string[]
  commit: string | null
  planFile: string
  planSection: string
  wave: string
  severity: Severity
  category: string | null
  tags?: string[]
  sourceScan: string | null
  selfReportedFailure: boolean
  requeuedAt: string | null
  review: string | Record<string, unknown> | null
  mergeCommit: string | null
  mergedAt: string | null
  /** ad-hoc / scan items may include this */
  agreement_count?: number
  agent_override?: string | null
  requeued_at?: string | null
  /** Stage 2: dependency graph */
  dependsOn?: string[]
  blocks?: string[]
  /** Stage 2: execution order */
  orderIndex?: number
  /** Stage 2: conflict group (files conflict → fixed order) */
  conflictGroup?: string | null
  /** Stage 2: epic / parent linkage */
  epicId?: string | null
  parent?: string | null
  /** Stage 2: result summary */
  resultSummary?: string
  diffRef?: string | null
  /** Stage 3: validation funnel result */
  validation?: ValidationResult | null
  verifyOutcome?: VerifyOutcome | null
  /** Epic 1: AI-powered merge resolution method */
  mergeResolution?: 'auto' | 'ai' | 'manual'
  /** Epic 2: per-task model override */
  modelOverride?: { provider: string; model: string; agent?: string } | null
  /** Epic 2: task complexity hint */
  complexity?: 'simple' | 'medium' | 'complex' | null
}

export interface VerifyOutcome {
  passed: boolean
  checks_ran: number
  unverified: boolean
  detail?: string
}

/** Response of GET /api/v1/tasks/{id}/checks (Improvements 1 & 3). */
export interface TaskChecks {
  verifyOutcome: VerifyOutcome | null
  /** Files the scope-guard flagged outside item.touches. */
  scopeExtra: string[]
}

// ── Epic 2: Goals ──

export interface Goal {
  id: string
  title: string
  description: string
  status: string
  taskIds: string[]
  createdAt?: string | null
  dryRounds: number
}

// ── Epic 2: Run summary ──

export interface RunSummary {
  runMode: string
  startedAtMs: number
  endedAtMs?: number
  itemsDone: number
  itemsFailed: number
  consecFail: number
  costUsd: number
  stoppedReason?: string | null
}

export interface CostSummary {
  ok: boolean
  totalCostUsd: number
  totalTokens: number
  topTasks: Array<{ id: string; title: string; costUsd: number }>
  budgetUsd: number | null
}

// ── State snapshot (GET /api/state) ──

export interface StateSnapshot {
  items: Item[]
  summary: Summary
  // Backend `current` = the live phase object; the rich live-iter block is `current_iter`.
  current: { itemId: string | null; phase: string; detail: string } | null
  current_iter?: CurrentIter
  log_tail: string[]
  loopStatus: LoopStatus
  git: GitInfo
  updatedAt: string
}

export interface Summary {
  pending: number
  queued: number
  in_progress: number
  done: number
  merged: number
  needs_revision: number
  discarded: number
  failed_total: number
  failed_breakdown: Record<string, number>
  total: number
  percent_done: number
}

export interface CurrentIter {
  dir: string | null
  active_agent: string | null
  events: ParsedEvent[]
  primary_size: number
  fallback_size: number
  events_count: number
  started_at_ms: number | null
  now_ms: number
}

export interface ProcessManagerStatus {
  state: 'idle' | 'running' | 'stopping' | 'exited'
  pid: number | null
  children: number[]
}
export interface LoopStatus {
  process: ProcessManagerStatus
  tmux?: boolean
  driver_pid?: number | null
  opencode_pids?: number[]
}
/** GET /api/driver/status — auto-driver runtime state (Sub-project #3). */
export interface DriverStatus {
  process: ProcessManagerStatus
  tmux?: boolean
  driver_pid?: number | null
  opencode_pids?: number[]
  runSummary?: RunSummary | null
  paused: boolean
  queued: number
  inProgress: number
}
export interface AgentRef {
  provider: string
  model: string
  agent?: string | null
  engineProfile?: string | null
}
export interface EngineProfile {
  name: string
  engine: 'opencode' | 'claude'
  env: Record<string, string>
}
export interface AgentsConfig {
  useModels: boolean
  primary: AgentRef
  fallback: AgentRef
  planner?: AgentRef | null
  validators: AgentRef[]
  arbiters: AgentRef[]
  final: AgentRef | null
}
export interface ReviewConfig {
  enabled: boolean
  tier1Threshold: number
  tier2Threshold: number
  maxRevisions: number
}
export interface RepoProfile {
  id: string; name: string; repoPath: string; baseBranch: string; remote: string
  branchPrefix: string; strictness: string; onboarded: boolean
  agents: AgentsConfig
  review?: ReviewConfig
  verifySource: 'agent' | 'manual'; verifyCommandsOverride: string[]
  verifyTimeoutSec?: number; autopush?: boolean; memoryDir?: string; createdAt?: string | null
  engine?: 'opencode' | 'claude'
  engineEnv?: Record<string, string>
  engineProfiles?: EngineProfile[]
  /** Agent connections & presets: per-role assignment of global connection ids. */
  roleConnections?: RoleConnections
  /** Dangling connection ids the registry could not resolve at load. */
  roleWarnings?: string[]
}

// ---- Agent connections & catalog (global model endpoints) ----
/** A single (engine, authMethod) combo for a provider in the catalog. */
export interface Combo {
  engine: string
  authMethod: 'subscription' | 'api_key'
  models: string[]
  baseUrl?: string | null
  keyEnv?: string | null
  loginCmd?: string | null
}
/** One provider entry in the provider catalog (replaces the old flat presets). */
export interface ProviderCatalogEntry {
  provider: string
  label: string
  blurb: string
  combos: Combo[]
}
/** Installed/auth state of an agent CLI (claude/opencode/codex). */
export interface CliInfo {
  installed: boolean
  version?: string | null
  auth: Record<string, unknown>
}
export interface Connection {
  id: string
  label: string
  provider: string
  engine: string
  model: string
  authMethod: 'subscription' | 'api_key'
  env: Record<string, string>
  status: 'untested' | 'connected' | 'failed'
  lastTestedAt?: string | null
  lastError?: string | null
}
export interface RoleConnections {
  primary?: string | null
  fallback?: string | null
  planner?: string | null
  final?: string | null
  merge?: string | null
  validators?: string[]
  arbiters?: string[]
}

// ---- Prompts (global templates + per-workspace overrides) ----
export interface PromptSummary { name: string; variables: string[]; overridden?: boolean }
export interface WsPromptDetail {
  name: string
  content: string
  global: string | null
  overridden: boolean
  variables: string[]
}

export interface GitInfo {
  branch?: string
  head?: string
  // Backend (/api/state) emits these snake_case keys.
  auto_branches: GitBranch[]
  recent_commits: GitCommit[]
}

export interface GitBranch {
  name: string
  lastCommitAt: string
  subject: string
  sha: string
  ahead: string
}

export interface GitCommit {
  sha: string
  author: string
  ts: string
  subject: string
}

// ── Worktrees (sub-project #6) ──

export interface WorktreeTask {
  id: string
  title: string
  status: string
}

export interface WorktreeConflict {
  branch: string
  task: WorktreeTask | null
  files: string[]
}

export interface Worktree {
  branch: string
  task: WorktreeTask | null
  changedFiles: string[]
  changedCount: number
  preflight: MergePreflightResponse
  conflictsWith: WorktreeConflict[]
}

// ── Events ──

export type EventKind = 'tool_call' | 'tool_result' | 'reasoning' | 'text' | 'session' | 'finish' | 'raw'

export interface ParsedEvent {
  idx: number
  kind: EventKind
  icon: string
  role?: string
  text: string
  ts_ms?: number | null
  // tool_call extras
  tool?: string
  tool_use_id?: string
  args_preview?: string
  args_full?: Record<string, unknown>
  output_preview?: string | null
  output_full?: unknown
  ts_started_ms?: number | null
  ts_completed_ms?: number | null
  status?: string
  // reasoning / text extras
  text_full?: string
  // finish extras
  boundary?: string
  tokens?: Record<string, number> | null
  cost?: number | null
}

// ── Iter details ──

export interface IterDetails {
  ok: boolean
  dir: string
  files: string[]
  commit_msg?: string
  verify_summary?: string
  verify_lines?: number
  verify_size?: number
  has_reviews?: boolean
  tier1_summary?: Record<string, unknown>
  tier2_summary?: Record<string, unknown>
  final_decision?: Record<string, unknown>
  verdicts?: Verdict[]
  cost: IterCost
}

export interface Verdict {
  reviewer: string
  tier: string
  verdict: string
  confidence?: number
  top_issues?: string[]
  reasoning?: string
}

// ---- Stage 3: validation funnel + merge ----

export interface LensVerdict {
  lens: 'correctness' | 'tests' | 'security' | 'conventions' | 'scope'
  verdict: 'approve' | 'needs_revision' | 'reject'
  confidence: number
  reasoning: string
}

export interface ValidationResult {
  layer1: LensVerdict[]
  layer2Summary: Array<Record<string, unknown>>
  gate: 'pass' | 'needs_revision'
  blocking: string[]
  revision: number
  notes?: string
}

export interface MergePreflightResponse {
  cleanTree: boolean
  verifyGreen: boolean
  /** verifyGreen is false because nothing ran (no verify config + no test files in
   * the diff), not because a check failed. Lets the UI explain *why* merge is blocked. */
  verifyUnverified?: boolean
  validationPassed: boolean
  loopActive: boolean
  baseBranch: string
  conflicts: string[]
  ok: boolean
}

export interface MergeResult {
  ok: boolean
  action?: 'merge'
  branch?: string
  newHead?: string
  push?: string
  conflicts?: string[]
  error?: string
  preflight?: MergePreflightResponse
}

// ---- Epic 1: AI-powered merge job ----

export type MergeJobStatus = 'running' | 'resolving' | 'verifying' | 'resolved'
  | 'conflict' | 'failed' | 'accepted' | 'rejected'
export type MergeDecision = 'auto_merged' | 'ai_merged' | 'needs_human' | 'failed'
export interface MergeJob {
  id: string; branch: string; baseBranch: string; status: MergeJobStatus
  decision?: MergeDecision | null; conflicts: string[]; resolvedFiles: string[]
  diff?: string | null; verifyOk?: boolean | null; error?: string | null
  worktreeBranch?: string | null; itemId?: string | null
}

export interface IterCost {
  input: number
  output: number
  reasoning: number
  cache_read: number
  cache_write: number
  total: number
  cost_usd: number
  streams: Record<string, StreamCost>
}

export interface StreamCost {
  input: number
  output: number
  reasoning: number
  cache_read: number
  cache_write: number
  total: number
  cost_usd: number
  events_seen: number
}

// ── History ──

export interface IterSummary {
  iter: string
  mtime: string
  item_id: string | null
  status: ItemStatus | null
  branch: string | null
  commit_short: string | null
  review: unknown
  final_decision: string | null
  tokens: number
}

// ── Config ──

export interface EffectiveConfig extends Record<string, string | undefined> {
  HEPHAESTUS_REPO?: string
  HEPHAESTUS_BRANCH_PREFIX?: string
  HEPHAESTUS_BASE_BRANCH?: string
  HEPHAESTUS_REMOTE?: string
  HEPHAESTUS_PRIMARY_AGENT?: string
  HEPHAESTUS_FALLBACK_AGENT?: string
  HEPHAESTUS_MAX_ITER?: string
  HEPHAESTUS_TIER_REVIEW?: string
  HEPHAESTUS_AUTOPUSH?: string
  HEPHAESTUS_ITER_TIMEOUT_SEC?: string
  HEPHAESTUS_MAX_CONSEC_FAIL?: string
  [key: string]: string | undefined
}

// ── Agent activity ──

export interface AgentActivity {
  agents: AgentInfo[]
  edges: AgentEdge[]
  timeline: AgentTimelineEntry[]
}

export interface AgentInfo {
  name: string
  roles: Record<string, number>
  invocations: number
  first_seen: string | null
  last_seen: string | null
  tasks: AgentTask[]
}

export interface AgentTask {
  task: string
  role: string
  outcome: string | null
  when: string | null
}

export interface AgentEdge {
  source: string
  target: string
  kind: string
  weight: number
}

export interface AgentTimelineEntry {
  type: 'iter' | 'scan'
  id: string
  when: string
  item_id?: string | null
  implementer?: string | null
  reviewers?: Array<{ agent: string; tier: string; verdict: string }>
  outcome?: string | null
  scanners?: Array<{ agent: string; findings: number }>
  reducers?: Array<{ agent: string; proposals: number }>
}

// ── Branch actions ──

export interface BranchActionResponse {
  ok: boolean
  error?: string
  note?: string
}

export interface ReorderResult {
  ok: boolean
  order?: string[]
  error?: string
}

// ── Scan ──

export interface ScanStatus {
  running: boolean
  scan_dir: string | null
  phase: string            // idle|queued|chunking|mapping|reducing|done|error
  detail?: string
  scanners?: number
  reviewers?: number
  scanners_done?: number
  reducers_done?: number
  n_findings?: number
  n_proposals?: number
  scope?: string
  error?: string
  updatedAt?: string
}

export interface ScanListItem {
  dir: string
  phase: string
  detail: string
  scanners?: number
  reviewers?: number
  updatedAt?: string
  n_proposals?: number | null
}

/** A single scan finding/proposal from results.json (importable to the board). */
export interface ScanFinding {
  id: string
  title: string
  proposal: string
  rationale?: string
  category?: string
  severity?: string
  touches?: string[]
  agreement_count?: number
}

// ── Decisions log ──

export interface Decision {
  ts: string
  actor: string
  action: string
  branch: string
  result: string
  extra: string
}

// ── API request types ──

export interface ItemPatch {
  status?: string
  severity?: string
  category?: string
  agent_override?: string | null
  [key: string]: unknown
}

export interface AddItemRequest {
  title: string
  proposal: string
  why: string
  acceptance: string
  touches: string[]
  severity?: string | null
  category?: string | null
  sourceScan?: string | null
  [key: string]: unknown
}

export interface ScanStartRequest {
  scanners?: number
  reviewers?: number
  scope?: string
}

/** A subdirectory of the active repo, for the scan-scope checkbox picker. */
export interface DirEntry {
  path: string          // repo-relative POSIX path — the token chunk_files() expects in `scope`
  name: string
  files: number         // recursive source-file count (vendor/build dirs pruned)
  hasChildren: boolean  // has further non-skipped subdirs (expandable)
}

/** A child directory on the *server* filesystem, for the onboarding repo picker. */
export interface FsEntry {
  name: string
  path: string          // absolute server/container POSIX path (what the picker selects)
  isGitRepo: boolean    // contains a `.git` → selectable as a repository
}

/** Response of GET /api/v1/fs/browse — immediate subdirs of a server directory. */
export interface FsBrowseResponse {
  ok: boolean
  path: string              // the resolved directory being listed
  parent: string | null     // its parent, or null at the filesystem root
  entries: FsEntry[]
}

export interface DriverStartOptions {
  maxIter?: number
  dryRun?: boolean
  tierReview?: boolean
  runMode?: 'queue' | 'ralph'
  costBudgetUsd?: number
  wallclockSec?: number
  maxConsecFail?: number
  [key: string]: unknown
}

export interface IterReviewsResponse {
  verdicts?: Verdict[]
  tier1_summary?: Record<string, unknown>
  tier2_summary?: Record<string, unknown>
  final_decision?: Record<string, unknown>
  [key: string]: unknown
}

// ── Epic 3 + v2 #8: Integrations (UI connect) ──

export interface IntegrationProvider {
  name: string
  available: boolean
  connected: boolean
  status: string          // connected | failed | untested | disconnected
  hasToken: boolean
  token: string | null    // masked, null when not connected
  host: string | null     // GitLab base URL; null for GitHub
  lastError: string | null
  lastTestedAt: string | null
  capabilities: {
    issues: boolean
    pullRequests: boolean
  }
}

export interface IntegrationConnectResult {
  ok: boolean
  name: string
  status: string
  connected: boolean
  error: string | null
  token: string | null
  host: string | null
}

// ── Epic 4: Ideas ──

export interface Idea {
  id: string
  title: string
  proposal: string
  rationale: string
  category: string
  severity: string
  touches: string[]
  imported: boolean
}

// ── Epic 4: Insights ──

export interface InsightsTurn {
  role: string
  content: string
  iterDir?: string | null
}

export interface InsightsSession {
  id: string
  title: string
  turns: InsightsTurn[]
  createdAt?: string | null
  updatedAt?: string | null
}

// ── Agent Jobs (async job-mode: rebuild-map / ideas) ──

export type AgentJobStatus = 'running' | 'done' | 'failed'

export interface AgentJob {
  id: string
  kind: string
  status: AgentJobStatus
  result?: any | null
  error?: string | null
  outputDir: string
  createdAt?: string | null
  updatedAt?: string | null
}

// ── Toast ──

export type ToastKind = 'info' | 'success' | 'warn' | 'error'

export interface Toast {
  id: number
  kind: ToastKind
  message: string
  createdAt: number
  undoAction?: () => void
}

// ── Conversation viewer (#5) ──
export interface ConversationAgentRun {
  stream: string
  role: string          // 'implementer' | 'validator:<lens>' | 'arbiter' | 'final'
  revision: number
  current: boolean
  model: string | null
  status: string
  messages: number
  costUsd: number
}
export interface ConversationStage {
  stage: string         // 'implement' | 'validate'
  agents: ConversationAgentRun[]
}
export interface ConversationIteration {
  dir: string
  createdAt: string
  attempts: number
  stages: ConversationStage[]
}
export interface TaskConversations {
  ok: boolean
  itemId: string
  iterations: ConversationIteration[]
}
export interface ConversationToolPayload {
  name: string | null
  input: unknown
  output: string | null
}
export type ConversationKind = 'text' | 'thinking' | 'tool' | 'tool_result'
export interface ConversationMessage {
  role: string | null
  kind: ConversationKind
  text?: string
  thinking?: string
  tool?: ConversationToolPayload
  tsMs?: number | null
  tokens?: Record<string, number> | null
  toolUseId?: string | null
}
export interface ConversationResponse {
  ok: boolean
  stream: string
  messages: ConversationMessage[]
}
