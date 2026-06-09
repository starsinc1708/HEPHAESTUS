# Prior Art & Best Practices — HEPHAESTUS Universal Tool
**Дата:** 2026-06-05  
**Источники:** июнь 2026  
**Цель:** Цитируемый отчёт по 8 областям исследования, привязанный к этапам проекта

---

## Executive Summary (топ-10 выводов)

1. **MCP-first архитектура — тренд 2026.** Все ведущие агенты поддерживают MCP; для HEPHAESTUS это означает, что пул валидаторов/сканирующих агентов стоит сделать MCP-совместимым (C.2).
2. **«Много→мало→1» воронка валидации подтверждена research.** Multi-agent debate с judge (Liang et al., 2023) даёт лучшее качество, чем majority voting; SPOQ (2026) показала, что dual validation gates (plan + code) сокращают дефекты на 41% (B.2).
3. **Лучшие практики памяти: коротко и человеко-написано.** ETH Zurich (2026) показал, что LLM-сгенерированные контекстные файлы *снижают* успешность задач на 20%+; developer-written файлы под 200 строк — оптимум (E.3).
4. **Scan-инструменты отделяют рецепцию от процессинга буфером.** CodeRabbit использует event-driven ingestion + Gatekeeper (фильтрация 40% noise перед AI) + Model Cascade (дешёвая модель для триажа, дорогая для reasoning) (C.3, C.5).
5. **DAG конфликтов — попарно (pairwise), не транзитивно.** Tascade (2026) и CAID (2026) подтверждают: попарное пересечение file touches + зависимости DAG достаточно; транзитивные union-find метки — косметика (D.3).
6. **opencode CLI — подтверждённые флаги.** `opencode run` не имеет `--model-output-format jsonl`; реальные флаги: `--model provider/model`, `--agent <name>`, `--format json` (G.1).
7. **CLAUDE.md < AGENTS.md как cross-tool стандарт.** 60K+ репозиториев используют AGENTS.md; Linux Foundation AAIF принял как стандарт. Для HEPHAESTUS: писать `.hephaestus/memory/` в AGENTS.md-совместимом формате (E.5).
8. **Map-reduce scan (много→мало) — отраслевой паттерн.** Open SWE, Qodo, CodeRabbit все используют параллельные сканеры + редьюсеры/дедупликацию (C.1).
9. **LLM-as-a-judge: ensembling + criteria injection дают +13.5pp accuracy.** 3 модели с ensemble scoring и task-specific criteria — оптимальный баланс cost/accuracy (B.4).
10. **Wave-based topological dispatch для параллельного исполнения.** SPOQ (2026) показала ускорение до 14.3× на unbounded DAG и 1.4× на реальном backend за счёт вычисления волн независимых задач (D.2).

---

## A. Аналоги / Prior Art автономных coding-агентов и loop-инструментов

### (а) Что делают аналоги

**SWE-Agent** (Princeton/Stanford): Agent-Computer Interface (ACI) — минимальный набор команд (view/search/edit/run), контекстное окно всего 5 последних шагов (collapsed history). Мини-версия в 100 строк Python даёт >74% SWE-bench. Архитектура: ReAct loop, single-agent, Docker sandbox. [Источник: OpenHands vs SWE-Agent comparison (2026)]

**OpenHands** (ex-OpenDevin): Event-stream архитектура с детерминированным replay, multi-agent delegation (CodeAct Agent делегирует Browsing Agent), provider-abstraction memory (Mem0/Letta). V1 SDK снизил system-attributable failures на 61%. SWE-bench Verified: 72% с Claude 4.5. [Источник: OpenHands V1 SDK paper (arXiv:2511.03690)]

**Aider**: Git-aware loop (diff→edit→commit), monolithic tool dispatch (нет MCP), repo-map для контекста. Лучший для terminal-first работы. 3/3 задачи с 1-й попытки за 4.5 мин. [Источник: Dibi8 comparison 2026]

**Cline/Roo Code**: VS Code extension с ReAct loop, MCP-as-extension. Roo Code добавил custom modes (code/architect/debug с разными system prompts). [Источник: PkgPulse 2026]

**MetaGPT**: SOP-driven multi-agent (Product Manager→Architect→PM→Engineer→QA). Structured communication через документы (не диалог), publish-subscribe message pool. Pass@1: 85.9% HumanEval. [Источник: MetaGPT paper (arXiv:2308.00352)]

**ChatDev**: Waterfall model с chat chain: design→coding→testing. Dual-agent communication (instructor+assistant) с communicative dehallucination. [Источник: ChatDev paper (arXiv:2307.07924)]

**Open SWE**: Multi-agent (Planner→Programmer→Reviewer) на LangGraph, async cloud-hosted. Human-in-the-loop на этапе плана. Action-review loop до perfection. [Источник: LangChain blog (Aug 2025)]

**SPOQ** (2026): Wave-based topological dispatch + Dual validation gates (plan + code) + Human-as-an-Agent. Ускорение до 14.3×; сокращение дефектов на 41%. [Источник: SPOQ paper (arXiv:2606.03115)]

**CAID** (2026): Git worktree isolation + dependency graph → parallel delegation + merge-based integration. Менеджер строит DAG репозитория, делегирует в worktree, merge после self-verification. [Источник: CAID paper (arXiv:2603.21489)]

### (б) Что взять в наш проект

| Что | Куда применить | Почему |
|------|----------------|--------|
| CAID-style worktree isolation | Этап 3 — merge (как альтернатива одной ветке) | Параллельные агенты не ждут очереди |
| SPOQ dual validation gates | Этап 3 — воронка | Plan validation (до impl) + code validation (после) — 41% меньше дефектов |
| OpenHands event-stream replay | Этап 1 — ProcessManager | Детерминированное восстановление после сбоев |
| MetaGPT publish-subscribe | Этап 2 — scan findings dedup | Каналы для разных линз сканирования |
| Aider's repo-map для контекста | Этап 1 — Profiler (memory generation) | LLM-эффективная репрезентация репо |
| Roo Code custom modes | prompts/ — система промптов | Специализированные агенты (scan vs decompose vs validate) |
| OpenHands V1 61% failure reduction | Этап 1 — ProcessManager+AgentRunner | Event-sourced state model |

### (в) Что избегать

- **Sequential role-playing** (ChatDev/MetaGPT) — слишком медленно для нашего parallel execution (SPOQ показала 14.3× ускорение wave-based).
- **Over-engineering** — Mini-SWE-Agent (100 строк) >74% accuracy; наш validation funnel не должен быть сложнее необходимого.
- **Monolithic tool dispatch** (Aider) — без MCP масштабирование ограничено.

### (г) Источники
- OpenHands vs SWE-Agent: https://localaimaster.com/blog/openhands-vs-swe-agent (Feb 2026)
- Aider/Cline/OpenHands comparison: https://dibi8.com/resources/dev-utils/aider-cline-openhands-2026-honest-comparison/ (May 2026)
- Agent execution systems: https://www.runlocalai.co/systems/agent-execution-systems (May 2026)
- OpenHands V1 SDK: arXiv:2511.03690 (2025)
- Open SWE: https://www.langchain.com/blog/introducing-open-swe-an-open-source-asynchronous-coding-agent (Aug 2025)
- SPOQ: arXiv:2606.03115 (2026)
- CAID: arXiv:2603.21489 (2026)
- MetaGPT: arXiv:2308.00352 (2023)
- ChatDev: arXiv:2307.07924 (2023)

---

## B. Multi-agent / Map-Reduce Валидация

### (а) Что делают аналоги

**Multi-Agent Debate (Liang et al., 2023)**: Structured debate с judge — canonical citation для multi-model review. Degeneration of Thought: single model становится увереннее без улучшения. Debate с анонимизацией и judge-моделью даёт существенное улучшение factuality и reasoning. [Источник: MAD paper, arXiv:2305.19118]

**Joint Chiefs (2026)**: Структурированный debate: spoke providers (3-4 независимых модели) → moderator (анонимизированный synthesis) → spokes respond по title → до convergence. Анонимизация убирает brand bias; per-provider weighting (0.0-3.0). [Источник: https://jointchiefs.ai/articles/multi-model-code-review-2026 (Apr 2026)]

**PoLL — Panel of LLMs (Verga et al., 2024)**: 3 small models из разных provider (`command-r`, `gpt-3.5-turbo`, `haiku`) побеждают одну большую модель на 6 датасетах при 7× меньшей стоимости. [Источник: orq.ai blog]

**Vibe Coding on Trial (arXiv:2602.18492)**: Unanimous LLM juries (1-6 моделей) на SQL-задачах. Unanimous AND rule (accept только если все agree) — safety-first. Small unanimous committees из сильных моделей cut false accepts без collapse TPR.

**Cost-Effective LLM Judge (arXiv:2604.13717)**: Criteria injection (близко к бесплатно, +3pp accuracy) + ensemble scoring (k=3 даёт ~70% gain). Mini model k=8 достигает 79.2% — почти как full model на ¼ стоимости.

**CodeGenie (2026)**: 5 специализированных агентов (syntactic correctness / security / performance / style / documentation) → weighted decision fusion → F1 0.892 (+17.3% над single model). [Источник: IJSET 2026]

**SPOQ dual validation**: 10 метрик на plan + 10 на code, порог 95%. Сокращение дефектов с 0.34 до 0.20 per task. [Источник: SPOQ paper]

### (б) Что взять в наш проект

| Что | Куда (Этап/Задача) | Приоритет |
|------|---------------------|-----------|
| Lens-based специализация (correctness/tests/security/conventions/scope) | Этап 3 — Layer 1 validators | **High** — уже в спеке |
| Unanimous AND rule for merge gate | Этап 3 — Layer 3 gate | **High** — safety-first |
| Criteria injection (task-specific focus per lens) | Этап 3 — prompts/validate-lens.md | **High** — near-free accuracy gain |
| Ensemble scoring k=3 (not full pool) | Этап 3 — Layer 1 размер | **Med** — 70% gain при малой стоимости |
| Анонимизация вердиктов перед арбитром | Этап 3 — Layer 2 | **Med** — убирает brand bias |
| Convergence detection для debate | Этап 3 — Layer 2→3 | **Low** — сложно, может быть future |
| Debug/error resilience: «все валидаторы упали → needs_revision» | Этап 3 — обработка ошибок | **High** — уже в спеке (R20) |
| Валидаторы из разных provider families | Этап 3 — AgentRef валидаторов | **High** — diversity = quality |

### (в) Что избегать
- **Majority voting без debate** — теряет minority positions (MAD paper).
- **Больше 3-5 валидаторов без clear convergence detection** — лишний cost без gain.
- **Self-judging** — когда валидатор совпадает с генератором (source: Vibe Coding on Trial).

### (г) Источники
- Multi-Agent Debate: arXiv:2305.19118 (2023)
- Joint Chiefs: https://jointchiefs.ai/articles/multi-model-code-review-2026 (Apr 2026)
- PoLL: orq.ai/blog/llm-juries-in-practice (2026)
- Vibe Coding on Trial: arXiv:2602.18492 (2026)
- Cost-Effective LLM Judge: arXiv:2604.13717 (2026)
- CodeGenie: IJSET V14_issue3_178 (2026)
- AEMA: arXiv:2601.11903 (2026)

---

## C. Repo-Wide Scanning и Triage Находок

### (а) Что делают аналоги

**CodeRabbit** (market leader, 2M+ repos): Event-driven ingestion → Gatekeeper (40% noise — docs/lockfiles/bots → dropped) → GraphRAG контекст (AST parser + dependency graph) → Model Cascade (cheap router → expensive reasoning). 50+ built-in linters/SAST tools. Adaptive memory (learns from dismissed comments). [Источник: CodeRabbit architecture docs, learnwithparam blog 2025]

**Qodo (CodiumAI)**: Proprietary Context Engine (RAG + code embeddings + Qodo-7b model). 3 layers: Ingest agents (AST chunking) → Knowledge layer (Graph DB + Vector DB + PR history + auto-generated .md) → Deep research agents (deep-research, find-similar, deep-issue, ask). Multi-agent review: Critical Issue / Breaking Changes / Ticket Compliance / Duplicated Logic / Rules agents. Martian Code Review Bench: 64.3% F1 (Jan-Feb 2026). [Источник: Qodo architecture docs]

**Greptile**: Full repo indexing → code graph (all functions, classes, variables + relationships) → real-time graph queries при code review. Catches cross-file breaking changes. Sequence diagrams auto-generated. $25M Series A (Benchmark, Sep 2025). [Источник: Greptile mintlify docs]

**Ellipsis** (YC W24): LLM agents catch logical errors + execute code it generates like human. 13% faster merge time. SOC II certified, no code persistence. [Источник: Respan comparison 2026]

### (б) Что взять в наш проект

| Что | Куда (Этап/Задача) | Приоритет |
|------|---------------------|-----------|
| Gatekeeper Pattern (фильтр 40% noise перед Агентом) | Этап 2 — scan entry | **High** — экономит 40% compute |
| Lane Routing (massive PR → slow lane) | Этап 2 — scan chunking | **Med** — large repo protection |
| AST chunking vs token-window chunking | Этап 2 — scan_run.chunk_files | **High** — semantic boundaries |
| Graph DB для отношений | Этап 2 — findings (future) | **Low** — сложно, может быть future |
| Dedup по (normalized title, sorted touches) | Этап 2 — scan_run.dedup_findings | **High** — уже в спеке |
| CodeRabbit-style adaptive memory | Этап 2 — Memory update after scan | **Med** — learn from dismissed |
| Model Cascade (cheap model для triage) | Этап 2 — scan (optional) | **Med** — router до mapper |

### (в) Что избегать
- **Всегда запускать самую дорогую модель** — 40% коммитов noise. Gatekeeper обязателен.
- **Per-file review без cross-file context** — упускает breaking changes (ошибка CodeRabbit).
- **Sequence diagrams на каждый PR** — Greptile генерирует их всегда, часто не нужно.

### (г) Источники
- CodeRabbit Architecture: https://docs.coderabbit.ai/overview/architecture
- CodeRabbit at scale: https://www.learnwithparam.com/blog/architecting-coderabbit-ai-agent-at-scale (Nov 2025)
- Qodo architecture: https://docs.qodo.ai/core-concepts/qodo-platform-architecture
- Greptile: https://greptile.mintlify.dev/docs/how-greptile-works/graph-based-codebase-context
- AI Code Review comparison: https://wetheflywheel.com/en/guides/best-ai-code-review-tools-2026/ (May 2026)
- RevEval benchmark: https://research.aimultiple.com/ai-code-review-tools/ (2026)
- Ellipsis: https://www.respan.ai/market-map/compare/coderabbit-vs-ellipsis (2026)

---

## D. Декомпозиция Задач + Граф Зависимостей + Детекция Конфликтов

### (а) Что делают аналоги

**Tascade** (2026): Dependency-aware оркестратор для multi-agent. File-touch tracking → conflict detection. Task lifecycle: backlog→ready→claimed→in_progress→implemented→integrated (двухфазное завершение). Gate tasks (review_gate, merge_gate) как synchronization barriers. Леase-based claiming с heartbeat expiry. MCP server (32 tools). [Источник: github.com/sayeed-anjum/tascade]

**Lattice** (2026): Contextual bandit router (обучается на execution feedback) + Z3 verifier для DAG acyclicity / budget feasibility. Formal proof до execution. Voyager-style skill caching. [Источник: github.com/JiwaniZakir/lattice]

**SPOQ DAG**: Wave-based topological dispatch. Explicit dependency DAG (не implicit как в ChatDev/MetaGPT). Tasks → execution waves (группы независимых). Critical path lower bound ratio 1.03-1.11. [Источник: SPOQ paper]

**CAID DAG**: Manager строит dependency graph репозитория. Ready-условие: все dependencies выполнены. Files с strong/circular dependencies grouped → одному engineer (reduces cross-agent coordination). Dynamic delegation: менеджер обновляет dependency state после каждого engineer. [Источник: CAID paper]

**Task-Decoupled Planning (TDP, 2026)**: Supervisor декомпозирует → dependency graph → Planner & Executor agents решают decoupled sub-task nodes independently → Self-Revision module обновляет граф. Локализованное replanning без cascading failures. [Источник: awesome-harness-engineering]

### (б) Что взять в наш проект

| Что | Куда (Этап/Задача) | Приоритет |
|------|---------------------|-----------|
| Попарное пересечение touches (pairwise, не транзитивно) | Этап 2 — task_graph.can_reorder | **High** — уже в спеке (подтверждено практикой) |
| Wave-based execution из SPOQ | Этап 3 — loop ordering | **Med** — future, когда будет parallel agents |
| CAID «strong dependencies → одному engineer» | Этап 2 — conflict_group | **Med** — полезно для декомпозитора |
| Lease-based claiming (Tascade) | Этап 3 — loop task dispatch | **Low** — overkill для single-loop |
| Gate tasks как synchronization barriers (Tascade) | Этап 3 — merge gate | **Med** — review_gate концептуально совпадает |
| Локализованное replanning (TDP) | Этап 3 — needs_revision петля | **High** — уже в спеке (feedback → re-run) |

### (в) Что избегать
- **Транзитивные компоненты как запрет reorder** — CAID и SPOQ подтверждают, что pairwise достаточно.
- **Implicit dependencies в role sequences** (ChatDev/MetaGPT) — теряется parallelism.

### (г) Источники
- Tascade: https://github.com/sayeed-anjum/tascade (Feb 2026)
- Lattice: https://github.com/JiwaniZakir/lattice (Feb 2026)
- SPOQ: arXiv:2606.03115 (2026)
- CAID: arXiv:2603.21489 (2026)
- TDP: awesome-harness-engineering (2026)

---

## E. Память Проекта / Context Engineering

### (а) Что делают аналоги

**CLAUDE.md (Claude Code)**: До 200 строк рекомендация. Path-scoped rules в `.claude/rules/*.md` с YAML frontmatter. Auto memory (Claude пишет заметки). Hooks (PreToolUse/PostToolUse) для deterministic enforcement. @import до 5 уровней. [Источник: Claude Code memory docs]

**AGENTS.md**: Стандарт AAIF (Linux Foundation, Dec 2025). 60K+ репозиториев. Читается Codex CLI, Gemini CLI, OpenCode, Claude Code (через `@AGENTS.md`). YAML + Markdown. [Источник: Claude Lab guide Mar 2026, amux.io Apr 2026]

**ETH Zurich study (Gloaguen et al., Feb 2026)**: LLM-generated context files *снижают* task success на 20%+ на AGENTbench и увеличивают inference cost. Developer-written files (under 200 lines) improve success на 4%. [Источник: Little Bear Apps blog]

**GitHub Copilot memory engineering (Jan 2026)**: Repository-scoped memories shared across coding agent, CLI, и code review. Just-in-time verification против current code state. Memory quality = freshness + invalidation. [Источник: GitHub engineering blog via awesome-harness-engineering]

**MetaGPT memory**: Role-specific subscription (publish-subscribe) — агент активируется только после получения всех prerequisite dependencies. Structured documents (PRD → design → code), не free-form chat. [Источник: MetaGPT paper]

### (б) Что взять в наш проект

| Что | Куда (Этап/Задача) | Приоритет |
|------|---------------------|-----------|
| `.hephaestus/memory/*.md` в формате AGENTS.md-совместимости | Этап 1 — Profiler | **High** — 60K+ репо стандарт |
| <200 строк на файл памяти | Этап 1 — memory generation | **High** — ETH Zurich evidence |
| Auto-improvement памяти (scan → дописывает tech-debt) | Этап 2 — MemoryWriter | **High** — уже в спеке |
| Path-scoped rules (аналог `.claude/rules/`) | Этап 1 — memory | **Med** — useful для conventions |
| Just-in-time verification памяти (GitHub Copilot) | Этап 2 — memory | **Med** — проверка на staleness |
| Role-specific subscription (MetaGPT) | Этап 2 — decompose | **Low** — future, когда multi-agent |
| Not including architecture/file trees — only gotchas | Этап 1 — Profiler prompt | **High** — ETH Zurich: что класть |

### (в) Что избегать
- **LLM-генерированные context files** без human curation — ETH Zurich: снижают успешность.
- **Overstuffed файлы** (>300-500 строк) — снижают adherence.
- **Дублирование: directory trees и framework explanations** — агент уже знает из кода.

### (г) Источники
- Claude Code memory: https://code.claude.com/docs/en/memory
- AGENTS.md guide: https://claudelab.net/en/articles/claude-code/claude-md-agents-md-complete-guide (Mar 2026)
- Agent config files comparison: https://amux.io/guides/agent-config-files-compared/ (Apr 2026)
- Optimizing agent rules (Arize AI): https://arize.com/blog/optimizing-coding-agent-rules-claude-md-agents-md-clinerules-cursor-rules-for-improved-accuracy/ (Oct 2025)
- Little Bear Apps: https://littlebearapps.com/blog/ai-context-files-what-to-include/ (Mar 2026)
- Start Debugging CLAUDE.md guide: https://startdebugging.net/2026/04/how-to-write-a-claude-md-that-actually-changes-model-behaviour/ (Apr 2026)
- HumanLayer blog: https://www.humanlayer.dev/blog/writing-a-good-claude-md (Nov 2025)
- MetaGPT: arXiv:2308.00352 (2023)

---

## F. Универсальная Детекция Verify/Build-Команд и Кроссплатформенный Запуск

### (а) Что делают аналоги

**Aider repo-map**: Автоматически строит компактную карту репозитория (сжатие ~100×) на основе AST и git history. Использует для выбора контекста, НЕ для verify-команд. [Источник: aider.chat]

**Claude Code `/init`**: Анализирует codebase → генерирует CLAUDE.md с build commands, test instructions, conventions. Но HumanLayer: «Never use /init — carefully craft instead» (слишком много шума). [Источник: HumanLayer blog]

**OpenHands**: CodeAct Agent использует Python execution kernel для verify; Docker-based sandbox изолирует запуск. Jupyter Kernel Environment для stateful code interaction. [Источник: OpenHands paper]

**Market practice**: `pnpm`, `uv run pytest`, `cargo test`, `dotnet test` — нет универсального детектора. Большинство тулов полагаются на конфигурацию (`.coderabbit.yaml`, `.pr_agent.toml`) или CLAUDE.md.

**Windows-specific**: shims (`npm.cmd`, `pnpm.cmd`) разрешаются через PATHEXT; `shutil.which()` на Windows подхватывает .cmd/.bat/.exe; `create_subprocess_exec` с явным exe-path не требует shell.

### (б) Что взять в наш проект

| Что | Куда (Этап/Задача) | Приоритет |
|------|---------------------|-----------|
| Profiler для детекта (через Agent) + manual override | Этап 1 — Profiler/VerifyRunner | **High** — уже в спеке (D4) |
| `shutil.which()` для .cmd/.bat шимов на Windows | Этап 1 — VerifyRunner | **High** — уже в спеке (R5) |
| «Одна команда на строку, без shell-операторов» контракт | Этап 1 — VerifyRunner | **High** — уже в спеке |
| shell:true opt-in для сложных команд | Этап 1 — VerifyRunner | **Med** — полезный fallback |
| Parse lockfiles для детекта стека | Этап 1 — Profiler | **Med** — package.json, Cargo.toml, pyproject.toml |

### (в) Что избегать
- **pnpm-хардкод** — убирается в Этапе 1 (уже решено D7).
- **LLM-генерация verify-команд без валидации** — Profiler должен уметь fallback на manual override.
- `shlex.split(posix=False)` на Windows — не использовать (R5 spec уже верно).

### (г) Источники
- Aider repo-map: https://aider.chat/docs/repomap.html
- Claude Code /init: code.claude.com/docs
- OpenHands architecture: arXiv:2511.03690
- Windows shim resolution: Python docs on shutil.which / PATHEXT

---

## G. OpenCode CLI / Агенты / Провайдеры

### (а) Подтверждение интеграционных допущений

**Ключевые флаги `opencode run`** (из официальной документации opencode.ai и opencodebook.xyz):

| Флаг | Назначение | Валидно |
|------|-----------|---------|
| `--model provider/model` | Выбор модели | ✅ Да |
| `--agent <name>` | Именованный агент из config | ✅ Да |
| `--format json` | JSON-вывод событий | ✅ Да (streaming events) |
| `--prompt <file>` | Prompt из файла | ✅ Да |
| `--session`, `-s` | Resume сессии | ✅ Да |
| `--continue`, `-c` | Продолжить последнюю | ✅ Да |
| `--file`, `-f` | Attach файл(ы) | ✅ Да |
| `--variant` | Provider-specific reasoning effort | ✅ Да |

**Вывод**: В спеке допущение про `--model-output-format jsonl` — **НЕ подтверждено**. Этого флага нет. Реальный флаг `--format json` выдаёт JSON events stream (step_start/text/step_finish/...). Для сохранения в файл нужен `--output <path>` (из OpenClaw PR integration видно, что используется `--output`). Анализ openclaw/openclaw PR #16099 показывает JSONL формат: `{"type":"step_start","sessionID":"ses_xxx","part":{"text":"..."}}`.

**Важно для AgentRunner:** следует использовать `--format json` для streaming + `--output <path>` для файла. Или перенаправлять stdout в файл с `--format json`.

**Конфиг агентов** (openocode.ai/docs/agents):
- Агенты определяются в `opencode.json` секцией `"agent"` или markdown-файлами в `.opencode/agents/`
- Каждый агент: `mode` (primary/subagent), `model`, `prompt`, `permission` (allow/deny per tool)
- Subagent mode — read-only агенты (подходит для валидаторов)
- Модели: `provider/model-id` (например `anthropic/claude-sonnet-4-20250514`)

### (б) Что взять в наш проект

| Что | Куда (Этап/Задача) | Приоритет |
|------|---------------------|-----------|
| Заменить `--model-output-format jsonl` на `--format json` + `--output <path>` | Этап 1 — AgentRunner._build_cmd | **High** — critical fix |
| `--model provider/model` для use_models | Этап 1 — AgentRunner | **High** — уже в спеке |
| `--agent <name>` для named agent | Этап 1 — AgentRunner | **High** — уже в спеке |
| Permission scope (read/edit/bash alow/deny) для валидаторов | Этап 3 — агенты воронки | **Med** — subagent mode |
| sessionID из step_start для resume | Этап 1 — AgentRunner | **Low** — future, если понадобится continuations |

### (в) Что избегать
- Передавать `--model-output-format jsonl` — флаг не существует, `opencode` выдаст ошибку.
- Предполагать posix-пути (Windows: `\` vs `/`).

### (г) Источники
- OpenCode CLI docs: https://opencode.ai/docs/cli/
- OpenCode agents: https://opencode.ai/docs/agents/
- OpenCode config: https://opencode.ai/docs/config/
- OpenCode providers: https://opencode.ai/docs/providers/ (через open-code.ai)
- OpenCode Book: https://www.opencodebook.xyz/en/chapter_12_cli_and_tui/12.4_non-interactive_mode
- OpenCode Guide: https://opencodeguide.com/en/cli-commands/
- OpenCode CLI CheatSheet: https://www.agenticcodingweekly.com/p/opencode-cli-cheat-sheet (May 2026)
- OpenClaw integration (JSONL format verified): https://github.com/openclaw/openclaw/pull/16099 (Feb 2026)
- opencode run.ts source: https://github.com/anomalyco/opencode/blob/HEAD/packages/opencode/src/cli/cmd/run.ts

---

## H. Готовые Промпты и Skills для Переиспользования

### (а) Что есть

| Репозиторий | Контент | Масштаб |
|-------------|---------|---------|
| `repowise-dev/claude-code-prompts` | 26+ prompt-файлов: system prompt, 11 tool prompts, 5 agent prompts, 4 memory prompts, coordinator, 4 utilities, 9 pattern analyses | ⭐ 1071 |
| `ABIvan-Tech/copilot-agentic-workflows` | Orchestrator + Planner + Explore + CoderJr/Sr + Reviewer + Debuger + Verifier + Multi-Reviewer. 12+ skills (kotlin, planning, memory, worktree, review, code-quality, security, testing) | ⭐ ~500 |
| `mowgliph/everything-agents-skills` | 44 agents + 391+ skills + 13 language rules. Multi-CLI (Qwen, OpenCode, Gemini, Copilot, Kilo) | ⭐ ~2000 |
| `wshobson/agents` | 185 agents + 153 skills + 16 orchestrators + 80 plugins + 100 commands. Plugin architecture с PluginEval quality framework | ⭐ ~800 |
| `ki3nd/awesome-harness-engineering` | Курированный список литературы по всем аспектам harness engineering | — |

**Что можно адаптировать под `prompts/` нашего проекта:**

1. **Agent prompts** (из claude-code-prompts): Code Explorer (→ scan-mapper), Solution Architect (→ scan-reducer), Verification Specialist (→ validate-*)
2. **Memory prompts** (из claude-code-prompts): Session notes format → может использоваться для memory update после задач
3. **Coordinator prompt** (из claude-code-prompts): Multi-worker orchestration с synthesis → подходит для decomponser
4. **Language rules** (из everything-agents-skills): 13 языков — можно адаптировать conventions.md под разные стеки
5. **Review prompts** (из copilot-agentic-workflows): Multi-reviewer consolidation → подходит для Layer 2 arbiter

### (б) Что взять в наш проект

| Что | Куда (prompts/) | Приоритет |
|------|-----------------|-----------|
| Verification Specialist prompt (PASS/FAIL/PARTIAL verdicts) | `prompts/validate-lens.md` | **High** — готовый паттерн |
| Coordinator multi-worker pattern | `prompts/scan-decomposer.md` | **Med** — multi-task orchestration |
| Memory consolidation pattern | `prompts/profiler.md` output format | **Med** — структура вывода |
| Language-specific rules | `.hephaestus/memory/conventions.md` | **Med** — для разных стеков |
| Anti-overengineering rules | `prompts/system-prefix.md` | **High** — keep minimal changes |
| Reversibility tier system (safety) | `prompts/system-prefix.md` | **High** — safety guardrails |

### (в) Что избегать
- **Blind копирование** — все промпты должны быть адаптированы под HEPHAESTUS-неймспейс и opencode CLI.
- **Слишком длинные system prompts** — adherence падает после 2000 токенов system prefix.

### (г) Источники
- claude-code-prompts: https://github.com/repowise-dev/claude-code-prompts (Apr 2026)
- copilot-agentic-workflows: https://github.com/ABIvan-Tech/copilot-agentic-workflows (Feb 2026)
- everything-agents-skills: https://github.com/mowgliph/everything-agents-skills (Apr 2026)
- wshobson/agents: https://github.com/wshobson/agents/ (Jul 2025, updated 2026)
- awesome-harness-engineering: https://github.com/ki3nd/awesome-harness-engineering (Apr 2026)

---

## Сводная таблица «Рекомендация → Этап/Задача → Приоритет → Источник»

| Рекомендация | Этап/Задача | Приоритет | Источник |
|-------------|-------------|-----------|----------|
| Заменить `--model-output-format jsonl` на `--format json` + `--output` | Этап 1 — AgentRunner._build_cmd | **High** | opencode.ai/docs/cli; OpenClaw PR #16099 |
| Lens-специализация Layer 1 (5 lens) | Этап 3 — validators | **High** | CodeGenie (IJSET); umbrella spec |
| Unanimous AND rule для merge gate | Этап 3 — Layer 3 | **High** | Vibe Coding on Trial (arXiv:2602.18492) |
| Criteria injection в validate-промпты | Этап 3 — prompts | **High** | Cost-Effective LLM Judge (arXiv:2604.13717) |
| Gatekeeper: фильтр 40% noise перед AI | Этап 2 — scan entry | **High** | CodeRabbit architecture (learnwithparam) |
| .md память <200 строк | Этап 1 — Profiler | **High** | ETH Zurich (Gloaguen et al., Feb 2026) |
| Не включать архитектуру/file-tree в память | Этап 1 — Profiler prompt | **High** | ETH Zurich; Little Bear Apps |
| Pairwise конфликт (не транзитивно) | Этап 2 — task_graph | **High** | CAID (arXiv:2603.21489); SPOQ |
| Category-sharded scan (AST chunking) | Этап 2 — scan_run | **High** | Qodo; CodeRabbit |
| Debug/error resilience all-validators-down→needs_revision | Этап 3 — funnel | **High** | Joint Chiefs; umbrella R20 |
| Anti-overengineering rules в system prefix | prompts/system-prefix.md | **High** | claude-code-prompts |
| Validation gates diversity (разные provider families) | Этап 3 — AgentRef | **High** | PoLL (Verga et al., 2024) |
| Dual validation gates (plan + code) | Этап 3 — funnel | **Med** | SPOQ (arXiv:2606.03115) |
| CAID-style worktree isolation | Этап 3 — merge (future) | **Med** | CAID |
| Wave-based topological dispatch | Этап 3 — loop (future) | **Med** | SPOQ |
| Анонимизация вердиктов перед Layer 2 | Этап 3 — layer2 | **Med** | Joint Chiefs |
| Lattice Z3 verifier для budget feasibility | Этап 2 — future | **Low** | Lattice (github.com/JiwaniZakir/lattice) |
| Event-sourced state (OpenHands V1) | Этап 1 — state | **Med** | OpenHands V1 SDK (arXiv:2511.03690) |

---

## Полный список источников

| # | Название/Описание | URL/DOI | Дата |
|---|-------------------|---------|------|
| 1 | Agent Execution Systems (RunLocalAI) | https://www.runlocalai.co/systems/agent-execution-systems | May 2026 |
| 2 | Aider vs Cline vs OpenHands 2026 (Dibi8) | https://dibi8.com/resources/dev-utils/aider-cline-openhands-2026-honest-comparison/ | May 2026 |
| 3 | OpenHands vs SWE-Agent (Local AI Master) | https://localaimaster.com/blog/openhands-vs-swe-agent | Feb 2026 |
| 4 | Open SWE (LangChain) | https://www.langchain.com/blog/introducing-open-swe-an-open-source-asynchronous-coding-agent | Aug 2025 |
| 5 | Cline vs Roo Code vs Aider 2026 (PkgPulse) | https://www.pkgpulse.com/guides/cline-vs-roo-code-vs-aider-open-source-ai-coding-agents-2026 | Apr 2026 |
| 6 | Comprehensive Empirical Evaluation of Agent Frameworks | arXiv:2511.00872 | 2025 |
| 7 | OpenHands V1 Software Agent SDK | arXiv:2511.03690 | 2025 |
| 8 | Multi-Model AI Code Review (Joint Chiefs) | https://jointchiefs.ai/articles/multi-model-code-review-2026 | Apr 2026 |
| 9 | Cost-Effective LLM-as-a-Judge | arXiv:2604.13717 | 2026 |
| 10 | AEMA: Verifiable Evaluation Framework | arXiv:2601.11903 | 2026 |
| 11 | Vibe Coding on Trial (LLM Juries) | arXiv:2602.18492 | 2026 |
| 12 | Weak judges, strong panel (orq.ai) | https://orq.ai/blog/llm-juries-in-practice | 2026 |
| 13 | MAJ-Eval: Multi-Agent-as-Judge | arXiv:2507.21028 | 2025 |
| 14 | CodeGenie Multi-Agent Code Review | IJSET V14_issue3_178 | 2026 |
| 15 | CodeRabbit Architecture | https://docs.coderabbit.ai/overview/architecture | 2026 |
| 16 | CodeRabbit at scale (learnwithparam) | https://www.learnwithparam.com/blog/architecting-coderabbit-ai-agent-at-scale | Nov 2025 |
| 17 | Qodo Platform Architecture | https://docs.qodo.ai/core-concepts/qodo-platform-architecture | 2026 |
| 18 | Greptile Graph-based Codebase Context | https://greptile.mintlify.dev/docs/how-greptile-works/graph-based-codebase-context | 2026 |
| 19 | Best AI Code Review Tools 2026 | https://wetheflywheel.com/en/guides/best-ai-code-review-tools-2026/ | May 2026 |
| 20 | AI Code Review Tools Benchmark (RevEval) | https://research.aimultiple.com/ai-code-review-tools/ | 2026 |
| 21 | AI Code Review 2026 (Best AI Web) | https://www.bestaiweb.ai/how-to-integrate-ai-code-review-with-qodo-coderabbit-and-greptile-in-your-github-workflow-in-2026/ | May 2026 |
| 22 | Claude Code Memory Documentation | https://code.claude.com/docs/en/memory | 2026 |
| 23 | Writing a good CLAUDE.md (HumanLayer) | https://www.humanlayer.dev/blog/writing-a-good-claude-md | Nov 2025 |
| 24 | CLAUDE.md vs .cursorrules vs AGENTS.md (amux) | https://amux.io/guides/agent-config-files-compared/ | Apr 2026 |
| 25 | Optimizing Coding Agent Rules (Arize AI) | https://arize.com/blog/optimizing-coding-agent-rules-claude-md-agents-md-clinerules-cursor-rules-for-improved-accuracy/ | Oct 2025 |
| 26 | AGENTS.md Complete Guide (Claude Lab) | https://claudelab.net/en/articles/claude-code/claude-md-agents-md-complete-guide | Mar 2026 |
| 27 | I maintain 7 AI context files (Little Bear) | https://littlebearapps.com/blog/ai-context-files-what-to-include/ | Mar 2026 |
| 28 | Write CLAUDE.md that Changes Behaviour | https://startdebugging.net/2026/04/how-to-write-a-claude-md-that-actually-changes-model-behaviour/ | Apr 2026 |
| 29 | OpenCode CLI Documentation | https://opencode.ai/docs/cli/ | 2026 |
| 30 | OpenCode Agents | https://opencode.ai/docs/agents/ | 2026 |
| 31 | OpenCode Config | https://opencode.ai/docs/config/ | 2026 |
| 32 | OpenCode Providers | https://opencode.ai/docs/providers/ | 2026 |
| 33 | OpenCode Book (Non-Interactive Mode) | https://www.opencodebook.xyz/en/chapter_12_cli_and_tui/12.4_non-interactive_mode | 2026 |
| 34 | OpenCode CLI Commands Guide | https://opencodeguide.com/en/cli-commands/ | 2026 |
| 35 | OpenCode CLI Cheat Sheet | https://www.agenticcodingweekly.com/p/opencode-cli-cheat-sheet | May 2026 |
| 36 | OpenClaw PR #16099 (OpenCode CLI backend) | https://github.com/openclaw/openclaw/pull/16099 | Feb 2026 |
| 37 | opencode run.ts source | https://github.com/anomalyco/opencode/blob/HEAD/packages/opencode/src/cli/cmd/run.ts | 2026 |
| 38 | opencode docs (dev.open-code.ai) | https://open-code.ai/en/docs/cli | 2026 |
| 39 | MetaGPT | arXiv:2308.00352 | 2023 |
| 40 | ChatDev | arXiv:2307.07924 | 2023 |
| 41 | SPOQ | arXiv:2606.03115 | 2026 |
| 42 | CAID | arXiv:2603.21489 | 2026 |
| 43 | Multi-Agent Debate (Liang et al.) | arXiv:2305.19118 | 2023 |
| 44 | Tascade | https://github.com/sayeed-anjum/tascade | Feb 2026 |
| 45 | Lattice | https://github.com/JiwaniZakir/lattice | Feb 2026 |
| 46 | claude-code-prompts (repowise-dev) | https://github.com/repowise-dev/claude-code-prompts | Apr 2026 |
| 47 | copilot-agentic-workflows (ABIvan-Tech) | https://github.com/ABIvan-Tech/copilot-agentic-workflows | Feb 2026 |
| 48 | everything-agents-skills (mowgliph) | https://github.com/mowgliph/everything-agents-skills | Apr 2026 |
| 49 | wshobson/agents | https://github.com/wshobson/agents/ | Jul 2025 |
| 50 | awesome-harness-engineering (ki3nd) | https://github.com/ki3nd/awesome-harness-engineering | Apr 2026 |
| 51 | CodeRabbit vs Ellipsis (Respan) | https://www.respan.ai/market-map/compare/coderabbit-vs-ellipsis | 2026 |
