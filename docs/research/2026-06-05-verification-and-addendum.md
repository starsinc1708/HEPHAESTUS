# Верификация и Дополнения к Prior Art Report
**Дата:** 2026-06-05  
**Источники:** июнь 2026  
**Цель:** Проверка ключевых утверждений из первого отчёта + новые находки по другим источникам

---

## 1. ВЕРИФИКАЦИЯ КЛЮЧЕВЫХ УТВЕРЖДЕНИЙ

### 1.1 `opencode run` — `--model-output-format jsonl`

**Утверждение в отчёте:** Флаг `--model-output-format jsonl` НЕ СУЩЕСТВУЕТ. Надо использовать `--format json`.

**Верификация:** ✅ **ПОДТВЕРЖДЕНО** — с уточнениями.

Проверено по 4 независимым источникам:
- **opencode.ai официальная документация** (https://opencode.ai/docs/cli/): флагов `run`: `--format` (choices: default, json), `--model`, `--agent`, `--continue`, `--session`, `--file`, `--output-format` — НЕТ.
- **opencodebook.xyz** (https://www.opencodebook.xyz/en/chapter_12_cli_and_tui/12.4_non-interactive_mode): `--format json` — единственный формат для машинного вывода.
- **GitHub run.ts source** (anomalyco/opencode): `builder: .option("format", { type: "string", choices: ["json"] })` — только `json`.
- **OpenClaw PR #16099** (реальная интеграция opencode как CLI backend): использует `opencode run --format json`.

**Критическое дополнение:** `opencode run` (новая архитектура, Go-based) использует `-p`/`--prompt` и `-f`/`--output-format` с choices `text`/`json`, НЕ `--format json`. Это видно по коммиту `103f1c1` (May 2025) в `opencode-ai/opencode` (Go-версия). Ранняя Node.js-версия (`anomalyco/opencode`) использует `run [prompt]` и `--format json`.

**Вывод для AgentRunner:** Есть ДВЕ версии opencode. Определять по `opencode --version`:
- Если Node.js-версия (`anomalyco/opencode`): `opencode run --format json --prompt <file>` или `opencode run --format json "<prompt>"` + `--output <file>`
- Если Go-версия (`opencode-ai/opencode`): `opencode -p <prompt> -f json`

**Баги:** GitHub Issue #29997 (May 30, 2026) — `opencode run --format json` не эмитит user prompt message в stream. Поток начинается с `step_start` без user-сообщения. Это может ломать парсинг output. Баг исправлен в PR #29998.

### 1.2 ETH Zurich AGENTS.md Study (Gloaguen et al.)

**Утверждение в отчёте:** LLM-генерированные context files снижают успешность задач на ~3%, увеличивают cost на 20%+.

**Верификация:** ✅ **ПОДТВЕРЖДЕНО ДОСЛОВНО.**

Проверено по:
- Оригинальному arXiv paper (arXiv:2602.11988, Feb 2026)
- ICLR 2026 Workshop proceedings
- Сайту SRI Lab ETH Zurich (sri.inf.ethz.ch)
- 8+ новостных/аналитических статей (InfoQ, heise online, the-decoder.com, MarkTechPost, i-scoop.eu, Zenn)

**Цитата (Abstract, arXiv:2602.11988):** *"Across multiple coding agents and LLMs, we find that context files tend to reduce task success rates compared to providing no repository context, while also increasing inference cost by over 20%."*

**Детали:**
| Условие | Success rate | Cost |
|---------|-------------|------|
| LLM-generated | −3% (среднее) | +20-23% |
| Developer-written | +4% (AGENTbench) | +19% |
| LLM +no documentation | +2.7% | — |

**Ключевой нюанс (InfoQ, heise, Zenn):** Когда из репозитория удалили ВСЮ существующую документацию, LLM-сгенерированные context files дали +2.7% — context files полезны когда заполняют реальные gaps, не рестайт README.

**JAWs 2026 counter-study:** Противоречивое исследование показало 28.64% reduction в completion time и 20% reduction в output tokens с AGENTS.md. Но измеряло efficiency (скорость), а не effectiveness (success rate). ETH Zurich измеряла effectiveness. Оба верны, но для разных метрик.

**Вывод для HEPHAESTUS:** ✅ Оригинальная рекомендация верна. Profiler должен генерировать КОРОТКИЕ, минимальные `.hephaestus/memory/*.md` < 120-200 строк, ТОЛЬКО с неочевидными констрейнтами (build commands, special tooling).

### 1.3 SPOQ Wave-Based Dispatch + Dual Validation

**Утверждение в отчёте:** SPOQ достигает speedup 14.3× на unbounded DAG и сокращает дефекты на 41% через dual validation gates.

**Верификация:** ✅ **ПОДТВЕРЖДЕНО.**

Проверено по arXiv:2606.03115 (опубликован June 2026) и spoqpaper.com. Цифры дословно:

| Metric | Значение |
|--------|----------|
| Wave dispatch speedup (unbounded DAG) | 14.3× (critical-path ratio 1.03-1.11) |
| Wave dispatch speedup (2-slot local) | 1.4× (hardware ceiling) |
| Field deployment speedup | 1.3-5.3× |
| Defects per task (no validation → dual) | 0.34 → 0.20 (−41%) |
| Test pass rate (no validation → dual) | 91.25% → 99.75% |
| Human-assisted defects | 0.03/task |
| Human-assisted pass rate | 99.75% |

**Дефекты сокра**щаются на **41%**, а не 41pp. Pass rate растёт на 8.5pp. **Важно:** Gains model-agnostic (воспроизведено на Qwen3.6-35B-A3B). Longitudinal study: 17 repos, 8,589 commits, 1,822 tasks, 99.87% pass rate.

**Вывод для HEPHAESTUS:** ✅ Цифры из отчёта верны. Dual validation (plan + code) — recommended. Wave-based dispatch — future enhancement для параллельного исполнения тасков.

### 1.4 CodeRabbit Model Cascade

**Утверждение в отчёте:** Model Cascade pattern — cheap router → expensive reasoning, 70% cost reduction.

**Верификация:** ✅ **ПОДТВЕРЖДЕНО** — независимо по 3 источникам.

- **learnwithparam (Nov 2025)**: 70% cost reduction, router на small model, fast path (~70% изменений) на static analysis, slow path (30%) на frontier model.
- **CodeRabbit official blog (Jan 2026)**: Nvidia Nemotron 3 Nano для summarization (1M token context), frontier models для deep reasoning. "Improves speed & cost efficiency".
- **GitHub coderabbitai/ai-pr-reviewer**: "light model" (GPT-3.5) для summarization, "heavy model" (GPT-4) для review. "Cost-effective and reduced noise".

**Вывод:** Model Cascade — proven pattern от самого CodeRabbit. Рекомендуется для сканирования (Этап 2): дешёвый router для классификации findings, дорогой reducer для deep analysis.

### 1.5 CAID Worktree Isolation

**Утверждение в отчёте:** CAID использует git worktree isolation + DAG dependency → parallel delegation.

**Верификация:** ✅ **ПОДТВЕРЖДЕНО** — arXiv:2603.21489.

CAID: Manager строит dependency graph репозитория → worktree для каждого engineer → merge-based integration. "Branch-based isolation, combined with explicit merge responsibilities, prevents parallel development from corrupting the shared codebase."

**Вывод:** CAID-подход — референс для будущего parallel loop в HEPHAESTUS.

---

## 2. НОВЫЕ НАХОДКИ (дополнение к отчёту)

### 2.1 Направление I: Model Cascade в деталях — что взять

**Новый источник:** Microsoft Foundry Model Router, AI Expert OÜ (May 2026), modelcascade (GitHub, Apr 2026).

**Хорошо документированный паттерн:**

| Tier | Тип модели | Что делает | Cost |
|------|-----------|-----------|------|
| **LOCAL / STATIC** | Ollama, linter | Deterministic checks, formatting | $0 |
| **FAST** | Haiku-4.5, Groq | Summarization, routing classification | $0.001/1K |
| **CAPABLE** | Sonnet-4.6, GPT-4o | Deep reasoning, code review | $0.005/1K |
| **FRONTIER** | Opus, GPT-5 | Complex architecture validation | $0.01-0.06/1K |

**Рекомендация для HEPHAESTUS:**
- **scan mapper router**: FAST tier → trivial findings сразу, сложные → CAPABLE/FRONTIER
- **Layer 1 validators**: смешивать FAST и CAPABLE на разные lens
- **CodeRabbit уже делает**: Nemotron для summarization (FAST), Claude/GPT для reasoning (CAPABLE/FRONTIER)

**Источники:**
- Microsoft Foundry Model Router: https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-router-how-it-works
- Multi-model orchestration: https://aiexpert.ee/en/articles/multi-model-orchestration (May 2026)
- modelcascade: https://github.com/wayneColt/modelcascade (Apr 2026)

### 2.2 Направление J: PR-Agent (Qodo) — Open Source Review Engine

**Источник:** Qodo docs, GitHub qodo-ai/pr-agent (11K+ stars).

**Архитектура:** `/review`, `/describe`, `/improve`, `/ask` — 4 команды. Multi-agent backend: code analysis → review generation. Поддержка custom YAML rules в `.pr_agent.toml`. Self-hosted option — ценнейший референс для нативных промптов HEPHAESTUS.

**Уникальные фичи:**
- **Repo-language specific prompts**: автоматическая смена системы ревью для Python vs TypeScript.
- **PR description generation**: авто-генерация описания и семантического changelog.
- **Ticket compliance**: проверка, что PR линкует issue.

**Что взять:**
- `prompts/review-tier1.md` → можно адаптировать из PR-Agent prompts (у них отличная структура для security/lint/quality)
- YAML для custom rules → но HEPHAESTUS уже использует `.hephaestus/memory/conventions.md` (то же самое, другой формат)

### 2.3 Направление K: CodeRabbit Incremental Reviews (важно для ревизий)

**Источник:** CodeRabbit docs + official GitHub action.

CodeRabbit делает **incremental reviews**: при новых коммитах анализирует только diff между base HEAD и новым commit, а не весь PR заново. Это снижает cost и noise.

**Вывод для HEPHAESTUS:** В `needs_revision` loop (Этап 3) при feedback-ревизии передавать не весь diff, а только diff с предыдущей ревизии. Уже поддерживается архитектурой (revision-петля на той же ветке, diff накапливается), но стоит явно указать в `prompts/revision-feedback.md`.

### 2.4 Направление L: GitHub Issue #2923 — JSON output missing with `--command`

**Источник:** GitHub issue anomalyco/opencode#2923 (Oct 2025, fixed).

**Важно для AgentRunner:** Если в `opencode run` указать `--command` вместе с `--format json`, JSON output пропадает. Исправлено в PR #2926. Но стоит избегать этого сочетания флагов — AgentRunner не должен использовать `--command`.

### 2.5 Направление M: Microsoft Skills Framework

**Источник:** Microsoft (2026), через awesome-harness-engineering.

"Standardized framework for defining, versioning, and distributing agent skills. Enables skill reuse across Claude Code, Copilot, VS Code, Gemini, and other platforms."

**Что это значит для HEPHAESTUS:** HEPHAESTUS-скиллы (skills) можно оформлять в Microsoft Skills-совместимом формате, что делает их портируемыми. Но это overkill для текущих этапов — отметка на future.

### 2.6 Направление N: Copilot Agentic Workflows — Референсная Оркестровка

**Источник:** ABIvan-Tech/copilot-agentic-workflows (⭐~500).

**Архитектура (независимо от исходного отчёта, найденное в awesome-harness-engineering):**
- **Orchestrator** — routing, review, debug loops, memory decisions, worktree strategy, `/delegate` boundaries. Single control plane.
- **Planner** — tracks (Quick Change / Feature / System), readiness gates (BLOCKED), plan deltas.
- **Explore** — read-only scouting, parallel x2/x3.
- **CoderJr / CoderSr** — tiered implementation.
- **Reviewer** — single + multi-review path (GPT + Gemini в параллель, затем MultiReviewer consolidation).
- **Debugger** — hypothesis-driven fixing.
- **Verifier** — independent acceptance gate (builds, tests, lint).
- **Memory** — durable (`.agent-memory/`) + session (temporary).

**Что прямо применимо к HEPHAESTUS:**
| Copilot Workflow | HEPHAESTUS эквивалент |
|-----------------|------------------|
| Orchestrator | FSM (наше) |
| Planner / readiness gates | Decomposer + depends_on validation (наше) |
| Multi-reviewer consolidation | Layer 2 (наше, но референс MultiReviewer prompt) |
| Verifier independent gate | VerifyRunner (наше) |
| Tiered coders (Jr/Sr) | primary / fallback (наше) |
| Durable + session memory | `.hephaestus/memory/` + iter-NNNN artifacts (наше) |

**Вывод:** Наша архитектура уже близка к best practice. Multi-reviewer consolidation — стоит добавить Prompts для MultiReviewer (сводит несколько review в один).

---

## 3. ИСПРАВЛЕНИЯ И УТОЧНЕНИЯ К ПЕРВОМУ ОТЧЁТУ

### 3.1 opencode — две версии CLI

**Было в отчёте:** `opencode run` — единый CLI.

**Реальность:** Есть ДВЕ версии opencode:
1. **Node.js (anomalyco/opencode)** — `opencode run [prompt]`, флаг `--format json`
2. **Go (opencode-ai/opencode)** — `opencode -p <prompt>`, флаги `-f text|json`, `-q`

**Impact:** AgentRunner должен определить версию (`opencode --version`) и выбирать флаги.

### 3.2 ETH Zurich — не «снижают на 20%+», а «увеличивают cost на 20%+»

**Было:** "LLM-генерированные context файлы снижают успешность задач на 20%+". **Неверно.** Снижают success rate на ~3%. Cost увеличивают на 20%+. Это разные вещи. Исправлено в верификации выше.

### 3.3 SPOQ defects — 41% reduction (от исходного отчёта было «41%»)

**Было:** «сокращение дефектов на 41%». Подтверждено: `(0.34 - 0.20) / 0.34 = 41.2%`. Верно.

### 3.4 CodeRabbit Gatekeeper — 40% noise vs 65% noise

**Было:** "Gatekeeper экономит 40% compute" (learnwithparam Part 1). **Уточнение:** learnwithparam Part 2 говорит "you filter out 65% of noise". Первая цифра (40%) — commits noise, вторая (65%) — files noise. Обе верны для разных метрик.

---

## 4. ИТОГ: ЧТО МЕНЯЕТСЯ ДЛЯ РЕАЛИЗАЦИИ

| Утверждение | Статус | Практическое действие |
|-------------|--------|----------------------|
| `--model-output-format jsonl` не существует | ✅ Подтверждено | Заменить на `--format json` + `--output <path>`. Определять версию opencode. |
| `opencode run` без `--command` | ✅ Подтверждено | Не использовать `--command` флаг |
| ETH Zurich — контекстные файлы | ✅ Подтверждено | Profiler: короткие файлы, только gotchas |
| SPOQ dual validation 41% дефектов | ✅ Подтверждено | Оставить dual gates в спеке |
| CodeRabbit Model Cascade | ✅ Подтверждено | Рекомендовать для scan router (future) |
| CAID worktree isolation | ✅ Подтверждено | Референс для parallel loop (future) |
| Multi-reviewer consolidation (Layer 2) | 🔍 Дополнено | copilot-agentic-workflows референс для prompts |
| CodeRabbit incremental reviews | 🔍 Дополнено | Для revision-feedback.md — передавать diff delta, не весь |
| Microsoft Skills Framework | 🔍 Дополнено | Future — HEPHAESTUS skills в portable формате |

---

## 5. ДОПОЛНИТЕЛЬНЫЕ ИСТОЧНИКИ (не в первом отчёте)

| # | Источник | URL | Тип |
|---|---------|-----|-----|
| 52 | ETH Zurich Gloaguen et al. (full paper) | arXiv:2602.11988 | Academic paper (Feb 2026) |
| 53 | ETH Zurich AGENTbench + context files (SRI Lab) | https://www.sri.inf.ethz.ch/publications/gloaguen2026agentsmd | Project page (May 2026) |
| 54 | InfoQ analysis of ETH Zurich study | https://www.infoq.com/news/2026/03/agents-context-file-value-review/ | News (Mar 2026) |
| 55 | heise.de analysis | https://www.heise.de/en/background/AGENTS-md-Helpful-agent-briefing-or-token-hog-11245317.html | News (Apr 2026) |
| 56 | the-decoder analysis | https://the-decoder.com/context-files-for-coding-agents-often-dont-help-and-may-even-hurt-performance/ | News (Feb 2026) |
| 57 | MarkTechPost on ETH study | https://www.marktechpost.com/2026/02/25/new-eth-zurich-study-proves-your-ai-coding-agents-are-failing-because-your-agents-md-files-are-too-detailed/ | News (Feb 2026) |
| 58 | Zenn analysis (JAWs counter-study) | https://zenn.dev/analysis/articles/thought-analyzer-agents-md?locale=en | Analysis (Apr 2026) |
| 59 | i-scoop analysis | https://www.i-scoop.eu/agents-md/ | Analysis (Mar 2026) |
| 60 | SPOQ paper (full) | arXiv:2606.03115 | Academic paper (Jun 2026) |
| 61 | SPOQ project site | https://www.spoqpaper.com/ | Project site |
| 62 | CodeRabbit Model Cascade + Nemotron | https://coderabbit.ai/blog/coderabbit-ai-code-reviews-now-support-nvidia-nemotron | Blog (Jan 2026) |
| 63 | CodeRabbit intelligence layer (learnwithparam) | https://www.learnwithparam.com/blog/architecting-coderabbit-ai-agent-intelligence-layer | Blog (Nov 2025) |
| 64 | Microsoft Foundry Model Router | https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-router-how-it-works | Docs (2026) |
| 65 | Multi-model orchestration (AI Expert OÜ) | https://aiexpert.ee/en/articles/multi-model-orchestration | Analysis (May 2026) |
| 66 | modelcascade (GitHub) | https://github.com/wayneColt/modelcascade | OSS (Apr 2026) |
| 67 | opencode run.ts (anomalyco/opencode) | https://github.com/anomalyco/opencode/blob/HEAD/packages/opencode/src/cli/cmd/run.ts | Source (2026) |
| 68 | opencode Issue #29997 (JSON missing user message) | https://github.com/anomalyco/opencode/issues/29997 | Bug report (May 2026) |
| 69 | opencode Issue #2923 (JSON + --command) | https://github.com/anomalyco/opencode/issues/2923 | Bug report (Oct 2025, fixed) |
| 70 | opencode-ai/opencode commit 103f1c1 | https://github.com/opencode-ai/opencode/commit/103f1c118363c226715c96d27f5ff9e1521c1cc9 | Source (May 2025) |
| 71 | copilot-agentic-workflows (ABIvan-Tech) | https://github.com/ABIvan-Tech/copilot-agentic-workflows | OSS (Feb 2026) |
| 72 | CodeRabbit code review overview | https://docs.coderabbit.ai/guides/code-review-overview | Docs (2026) |
| 73 | opencode-semgrep-coderabbit-skill | https://github.com/acedergren/opencode-semgrep-coderabbit-skill | OSS (Jan 2026) |
| 74 | Qodo PR-Agent (open source) | https://github.com/qodo-ai/pr-agent | OSS (2024-2026) |
| 75 | CodeRabbit GitHub Action (original) | https://github.com/coderabbitai/ai-pr-reviewer | OSS (2023-2026) |
