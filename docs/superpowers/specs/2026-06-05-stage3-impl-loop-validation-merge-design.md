---
title: Stage 3 — Implementation Loop + Map-Reduce Validation Funnel + Merge — Design Spec
status: detailed
date: 2026-06-05
audience: tool author (user) + implementing engineer
language: prose=ru, identifiers/paths/commands=en
depends_on: [2026-06-05-universal-tool-overview-design.md, stage-1-onboarding-engine, stage-2-scan-decompose-memory]
covers_vision_points: [7, 8, 9]
---

# Stage 3 — Implementation Loop + Map-Reduce Validation Funnel + Merge

> Якорный документ контрактов — `docs/superpowers/specs/2026-06-05-universal-tool-overview-design.md` (далее **umbrella**). Любые доменные типы (`RepoProfile`, `AgentsConfig`, `AgentRef`, `ReviewConfig`, `Task`, `ValidationResult`, `LensVerdict`, `ProcessManager`, `AgentRunner`, `VerifyRunner`, `GitService`, `MergePreflight`) и API-конвенции берутся из umbrella **дословно** и здесь только ссылаются/реализуются, не переопределяются. При расхождении приоритет у umbrella.

---

## 1. Goal

Реализовать per-task loop реализации поверх `OrchestratorFSM` с воронкой валидации map-reduce (D10): N параллельных валидаторов-линз → M арбитров → 1 финальный гейт `pass|needs_revision`, с возвратом фидбэка агенту при `needs_revision` (ограничено `ReviewConfig.max_revisions`). Результат каждого прогона — ветка `auto/<task>` + `diff.patch` + сгенерированное `summary.md`/`result_summary`; пользователь вливает ветку в `base_branch` через UI (`GitService.merge_to_base`, D11) с предпроверками (чистое дерево, verify-green, прошёл воронку) и обработкой merge-конфликтов.

## 2. Confirmed decisions (релевантные этому этапу)

| ID | Что фиксирует для Stage 3 |
|----|---------------------------|
| **D1** | Воронка и merge — нативный кроссплатформенный Python. Валидаторы/арбитры/финал — **внутренние конкурентные asyncio-подпроцессы оркестратора** через `AgentRunner` (НЕ `ProcessManager`-сессии backend, R1/R2); у каждого уникальный `output_path` (`validation/layer1/<lens>.jsonl`, `validation/layer2/arbiter-<i>.json`, `validation/layer3/final.json`), общего `session_name` нет. Сам `loop`-оркестратор — единственный `ProcessManager`-процесс (`python -m app.orchestrator.main --workspace <id>`). Никакого `tmux`/`pgrep`/`pkill`/`bash`/`tier-review.sh`. |
| **D2** | Валидаторы/арбитры/финал — opencode-агенты из `RepoProfile.agents.validators/arbiters/final` (`AgentRef`), а не хардкод `oracle/atlas/sisyphus-junior`. Fallback (R3): `validators` пуст → `[ws.agents.primary] * N`; `final is None` → `primary` — воронка НЕ вырождается молча в `pass`. JSONL-вывод сохраняется (`validation/**`). |
| **D4** | Перед валидацией `VerifyRunner` уже отработал (verify-green — предусловие merge). Stage 3 не дублирует verify-логику, читает её результат. |
| **D10** | Размеры слоёв и пороги — из `TIER_PRESETS` + effective-config (`HEPHAESTUS_TIER1_APPROVE_THRESHOLD`/`HEPHAESTUS_TIER2_APPROVE_THRESHOLD`). Stage 3 **не** вводит параллельный источник истины порогов. |
| **D11** | Merge из UI = локальный `git merge auto/<task>` → `base_branch` рабочей копии с предпроверками; опциональный push; `git merge --abort` при конфликте + возврат списка конфликтов. |
| **D7** | `auto/<task>`-ветки, `output.primary.jsonl`, `decisions.log`, `HEPHAESTUS_*`-неймспейс сохраняются. Vendor-агенты удаляются как дефолты. |
| **D8** | In-place: расширяем `fsm.py`, `git.py`, `branches.py`, `iters.py`, `TaskDrawer.vue`; новые модули — `validators.py`, `merge.py`-роутер. Ядро с нуля не пишем. |
| **D9** | Все вызовы движка принимают `ws: RepoProfile` явно; `config.REPO/BASE_BRANCH/REMOTE/BRANCH_PREFIX` напрямую не читаются. |

## 3. Затрагиваемые и новые файлы

### Новые файлы

| Путь | Что | Ключевые символы |
|------|-----|------------------|
| `backend/app/core/validators.py` | **NEW.** Воронка валидации map-reduce (Layer 1/2/3), агрегация голосов, построение фидбэк-промпта. | `ValidationFunnel`, `run_funnel`, `_aggregate_layer1`, `_layer_sizes_for`, `build_revision_prompt`, `LensSpec`, `LENSES` |
| `backend/app/api/v1/merge.py` | **NEW.** Роутер merge-предпроверок и merge-в-base. | `merge_preflight`, `merge_branch`, `router` |
| `backend/app/models/validation.py` | **NEW.** Pydantic-модели воронки (импорт из umbrella §7) + request-модели merge. | `LensVerdict`, `ValidationResult`, `MergeRequest`, `MergePreflightResponse` |
| `prompts/validate-lens.md` | **NEW.** Шаблон валидатора-линзы Layer 1 (заменяет `review-tier1.md` под линзовую модель). | `{{lens}}`, `{{lens_focus}}`, `VALIDATION_VERDICT_BEGIN/END` |
| `prompts/validate-arbiter.md` | **NEW.** Шаблон арбитра Layer 2 (сведение находок линз). | `{{layer1_digest}}`, `ARBITER_VERDICT_BEGIN/END` |
| `prompts/validate-final.md` | **NEW.** Шаблон финального гейта Layer 3 (`pass|needs_revision`). | `{{layer1_digest}}`, `{{layer2_digest}}`, `FINAL_GATE_BEGIN/END` |
| `prompts/revision-feedback.md` | **NEW.** Шаблон фидбэк-промпта для возврата агенту при `needs_revision`. | `{{blocking}}`, `{{lens_findings}}`, `{{attempt}}`, `{{max_revisions}}` |
| `frontend/src/components/ValidationPanel.vue` | **NEW.** Визуализация воронки в TaskDrawer (слои/линзы/гейт). | `ValidationPanel`, `gateClass`, `lensRows` |
| `frontend/src/components/MergeButton.vue` | **NEW.** Кнопка Merge + диалог конфликтов + preflight-чеклист. | `MergeButton`, `preflight`, `doMerge`, `conflictFiles` |
| `frontend/src/components/RunTimeline.vue` | **NEW.** Таймлайн прогона (фазы FSM + revision-петли). | `RunTimeline`, `phases`, `revisionLoops` |

### Модифицируемые файлы (с указанием существующих символов)

| Путь | Что меняем | Существующие символы |
|------|-----------|----------------------|
| `backend/app/orchestrator/fsm.py` | `Phase.TIER_REVIEW` → `Phase.VALIDATE`; `_tier_review` (no-op, строки 420-427) → `_validate` поверх `ValidationFunnel` (использует module-singleton `from app.core.process import pm` и `AgentRunner(pm)`, без `AgentRunner(None)`, R15); добавить `in_review`/`needs_revision`-петлю в `_process_item`; промпт строится извлечённым `_build_prompt(item)` из Этапа 1 (R14); после зелёного verify FSM пишет персистентный `item.verify_green=True` (R11); `_parse_result` пишет `summary.md`/`result_summary`/`diff_ref`; `_TRANSITIONS` обновить. | `OrchestratorFSM`, `Phase`, `_TRANSITIONS`, `_process_item`, `_build_prompt`, `_run_opencode`, `_tier_review`, `_parse_result`, `_set_phase`, `_mark_failed`, `_mark_done` |
| `backend/app/core/git.py` | Добавить `GitService`-класс поверх существующих функций (umbrella §5.4): `merge_preflight`, `merge_to_base`, `diff`. Существующий `_action_merge` остаётся как legacy для `/api/branch/{name}/merge`. | `_action_merge`, `_git_branches`, `_is_safe_auto_branch`, `_branch_exists`, `_update_item_by_branch`, `BASE_BRANCH`, `REMOTE`, `REPO` |
| `backend/app/api/v1/branches.py` | Без изменений семантики legacy; новый функционал в `merge.py`. | `branch_action`, `_VALID_ACTIONS` |
| `backend/app/core/iters.py` | `_iter_details`/`_iter_reviews` отдают `validation` (из `iter-NNNN/validation/layer3/final.json`, umbrella §4.4/§7) рядом с legacy `final_decision`. | `_iter_details`, `_iter_reviews`, `_safe_iter_dir`, `_iter_diff`, `build_state` |
| `backend/app/models/domain.py` | Добавить поля `Task` из umbrella §4.2 (`validation`, `result_summary`, `diff_ref`, `depends_on`, `order_index` и др.). Статусы — строки; добавить `in_review`. | `Item` |
| `backend/app/main.py` | Зарегистрировать `merge.router`; убрать `pkill`-shutdown (D1) — заменено `ProcessManager.cancel`. | `app`, `lifespan`, `ok_response`, `error_response` |
| `backend/app/config.py` | Добавить **ТОЛЬКО** env-ключ `HEPHAESTUS_REVISION_MAX` в `ALLOWED_CONFIG_KEYS` (+ дефолт/валидация в `_config_effective`). Пороги воронки читаются из `TIER_PRESETS` через `_config_preset`; `_layer_sizes_for` живёт **не здесь**, а как метод `ValidationFunnel` в `validators.py` (R16). | `TIER_PRESETS`, `_config_preset`, `_config_effective`, `ALLOWED_CONFIG_KEYS` |
| `frontend/src/types/api.ts` | Добавить `LensVerdict`, `ValidationResult`, `MergePreflightResponse`, `MergeResult`; `ItemStatus` += `'in_review'`; `Item.validation`/`resultSummary`/`diffRef`. | `ItemStatus`, `Item`, `IterDetails`, `Verdict` |
| `frontend/src/api/client.ts` | Добавить `mergePreflight`, `merge`. | `api` |
| `frontend/src/components/TaskDrawer.vue` | Вкладка «Ревью» → рендер `ValidationPanel`; в `drawer-actions` добавить `MergeButton`; новая вкладка «Таймлайн» (`RunTimeline`); `TABS` расширить. | `TABS`, `loadTab`, `reviewsData`, `drawer-actions` |
| `frontend/src/stores/task.ts` | Кэш для `validation`; `fetchValidation(dir)`. | `useTaskStore`, `fetchReviews`, `clearCache` |

---

## 4. Ключевые контракты

### 4.1 FSM: фазы и петля ревизий

`Phase.TIER_REVIEW` переименовывается в `Phase.VALIDATE`. `Phase.IN_REVIEW`/`Phase.NEEDS_REVISION` **не** вводятся как FSM-фазы — это статусы `Task`, а не фазы исполнения (FSM остаётся per-item линейным). Обновлённый `_TRANSITIONS`:

```python
class Phase(StrEnum):
    IDLE = "idle"
    PREFLIGHT = "preflight"
    PROMPT_BUILD = "prompt_build"
    OPENCODE = "opencode"
    VERIFY = "verify"
    COMMIT = "commit"
    PARSE_RESULT = "parse_result"
    VALIDATE = "validate"          # was TIER_REVIEW
    CLEANUP = "cleanup"

_TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.IDLE: {Phase.PREFLIGHT},
    Phase.PREFLIGHT: {Phase.PROMPT_BUILD, Phase.IDLE},
    Phase.PROMPT_BUILD: {Phase.OPENCODE, Phase.IDLE},
    Phase.OPENCODE: {Phase.VERIFY, Phase.IDLE},
    Phase.VERIFY: {Phase.COMMIT, Phase.IDLE},
    Phase.COMMIT: {Phase.PARSE_RESULT, Phase.IDLE},
    Phase.PARSE_RESULT: {Phase.VALIDATE, Phase.IDLE},
    Phase.VALIDATE: {Phase.OPENCODE, Phase.CLEANUP, Phase.IDLE},  # VALIDATE→OPENCODE = revision loop
    Phase.CLEANUP: {Phase.IDLE},
}
```

Петля ревизий внутри `_process_item` (псевдокод, дополняет существующий `backend/app/orchestrator/fsm.py:96-149`; `ws: RepoProfile` прокидывается из вызывающего):

```
_process_item(item, ws):
    PREFLIGHT → PROMPT_BUILD → OPENCODE → VERIFY → COMMIT → PARSE_RESULT  (как сейчас)
    item.status = "in_review"; persist
    attempt = item.attempts                      # 0-based номер текущей попытки
    while True:
        _set_phase(VALIDATE, item.id)
        vr: ValidationResult = await self._validate(item, ws, revision=attempt)
        if vr.gate == "pass":
            _set_phase(CLEANUP); await _cleanup(item, ws)
            item.validation = vr.model_dump(by_alias=True)
            _mark_done(item)                       # status=done, branch retained
            return
        # gate == needs_revision
        attempt += 1
        item.attempts = attempt
        if attempt > ws.review.max_revisions:
            item.validation = vr.model_dump(by_alias=True)
            _mark_failed(item, "failed:max-revisions")
            return
        item.status = "needs_revision"; persist
        prompt = build_revision_prompt(item, vr, attempt, ws)   # validators.py
        (self.iter_dir / "prompt.md").write_text(prompt)
        _set_phase(OPENCODE, item.id)
        rc = await self._run_opencode(item, prompt)             # 2 арг (R15: ws через self._ws); НА ТОЙ ЖЕ ветке
        if rc is None: _mark_failed(item, "failed:refused"); return
        if rc != 0:    _mark_failed(item, "failed:opencode"); return
        _set_phase(VERIFY); if not await self._verify(item): _mark_failed(item,"failed:verify"); return
        _set_phase(COMMIT); if not await self._commit(item): _mark_failed(item,"failed:commit"); return
        _set_phase(PARSE_RESULT); await self._parse_result(item)
        item.status = "in_review"; persist
        # цикл повторяет VALIDATE с инкрементированным revision
```

Ревизия исполняется **на той же ветке** `auto/<id>-<ts>` (PREFLIGHT не повторяется), так что diff накапливается; `iter_dir` тот же. `revision` пишется в `ValidationResult.revision` и в имя поддиректории при коллизии (`validation/r<revision>/...`). **Фидбэк-промпт ревизии передаёт дельту, а не весь diff** (research): `build_revision_prompt` подставляет diff с предыдущей ревизии (`git diff <prev-rev-commit>..HEAD`), а НЕ весь накопленный diff — incremental-review снижает шум и стоимость (CodeRabbit incremental reviews, 2026). Полный накопленный diff остаётся для финального гейта Layer 3 и merge-preflight.

### 4.2 `ValidationFunnel` — `backend/app/core/validators.py`

```python
LENSES: tuple[str, ...] = ("correctness", "tests", "security", "conventions", "scope")

class LensSpec(BaseModel):
    lens: str                 # один из LENSES
    focus: str                # одно-два предложения «на что смотреть» для промпта

# фокусы линз — единственный источник истины для промпта validate-lens.md
LENS_FOCUS: dict[str, str] = {
    "correctness": "Does the diff actually solve the item's problem? Edge cases, null/empty, error paths, races.",
    "tests":       "Are tests present, do they exercise the new path, would they fail WITHOUT the production change?",
    "security":    "Secret leaks, weakened auth, SSRF, swallowed exceptions hiding bugs, unsafe casts, missing input validation.",
    "conventions": "Naming, code style, project conventions from .hephaestus/memory/conventions.md, no out-of-style patterns.",
    "scope":       "Does the diff stay inside item.touches? Out-of-scope refactors / 'while-I-was-here' tweaks are a needs_revision signal.",
}

class ValidationFunnel:
    def __init__(self, ws: "RepoProfile", runner: "AgentRunner") -> None: ...

    def _layer_sizes_for(self) -> tuple[list[str], int, int, int]:
        """Из strictness/effective-config возвращает:
        (active_lenses, m_arbiters, tier1_threshold, tier2_threshold).
        Источник — TIER_PRESETS + ws.strictness; см. таблицу §4.3."""

    async def run_funnel(self, item: dict, *, iter_dir: pathlib.Path,
                         diff_text: str, revision: int) -> "ValidationResult":
        """Полная воронка. Пишет artifacts в iter_dir/validation/. Возвращает ValidationResult.
        Если strictness=='disabled' или review.enabled is False → немедленный pass без агентов."""

    async def _run_layer1(self, item, *, iter_dir, diff_text, lenses) -> list["LensVerdict"]: ...
    async def _run_layer2(self, item, *, iter_dir, l1: list["LensVerdict"], m: int) -> list[dict]: ...
    async def _run_layer3(self, item, *, iter_dir, l1, l2) -> dict: ...

    @staticmethod
    def _aggregate_layer1(verdicts: list["LensVerdict"], threshold: int) -> tuple[bool, list[str]]:
        """approve_count = #verdict==approve. passed = approve_count >= clamp(threshold, 1, len).
        blocking = [f'{v.lens}: {v.reasoning}' for v if v.verdict != 'approve'].
        Любой verdict=='reject' с confidence>=0.7 → passed=False независимо от счёта."""

def build_revision_prompt(item: dict, vr: "ValidationResult", attempt: int,
                          ws: "RepoProfile") -> str:
    """Рендер prompts/revision-feedback.md: подставляет vr.blocking, дайджест линз
    с verdict!=approve, attempt/ws.review.max_revisions, оригинальный item.proposal/acceptance.
    Возвращает markdown-промпт для повторного _run_opencode."""
```

**Fallback пулов (R3).** Если `ws.agents.validators` пуст — используется `[ws.agents.primary] * len(active_lenses)`; если `ws.agents.final is None` — используется `ws.agents.primary`. Воронка НИКОГДА не вырождается молча в `gate=pass` при непустом strictness из-за пустого пула.

**Layer 1 (карта).** На каждую активную линзу — один **внутренний конкурентный asyncio-подпроцесс оркестратора** через `AgentRunner.run(ref=validators[i % len], prompt_file=…, output_path=iter_dir/"validation"/"layer1"/f"{lens}.jsonl", cwd=ws.repo_path, timeout_sec=…)` (R2: уникальный `output_path` на линзу, **без** общего `session_name`; это НЕ `ProcessManager`-сессия backend). Все линзы запускаются конкурентно через `asyncio.gather` с `return_exceptions=True`; упавший/таймнутый валидатор трактуется как `verdict="needs_revision", confidence=0.0, reasoning="validator <lens> errored: <exc>"` (fail-safe в сторону строгости). Вывод парсится из блока `VALIDATION_VERDICT_BEGIN…END` (см. §4.6), нормализованный `LensVerdict` сериализуется рядом в `layer1/<lens>.json`.

**Layer 2 (свёртка).** `M` арбитров (`ws.agents.arbiters`), каждому даётся дайджест всех `LensVerdict` слоя 1; арбитр дедуплицирует находки, присваивает severity и общий вердикт `approve|needs_revision|reject`. Каждый — уникальный `output_path=validation/layer2/arbiter-<i>.json` (i = 0..M-1), без общего `session_name` (R2). Если `M==0` (permissive с одним арбитром, либо отсутствуют арбитры) — Layer 2 пропускается, его роль сводки берёт на себя Layer 3. Если ВСЕ арбитры недоступны (errored — не по существу, а из-за сбоя запуска), Layer 2 **не штрафуется**: гейт опирается на L1+L3, как при `M==0` (R20).

**Layer 3 (гейт).** Один агент (`ws.agents.final`, при `None` → `ws.agents.primary`, R3) сводит слои 1–2 → `validation/layer3/final.json` (umbrella §4.4/§7): `{"gate": "pass"|"needs_revision", "blocking": [...], "notes": "...", "revision": <int>}`. Финальный гейт `pass` требует: агрегат Layer 1 `passed==True` **И** (если Layer 2 активен и не все арбитры errored) ≥ `tier2_threshold` арбитров `approve`. Иначе `needs_revision`. При провале Layer 2 в `blocking` добавляется явная причина вида `'arbiters: X of <t2> approvals'` (R20). Гейт не имеет `reject` как терминала: семантически `reject` арбитра/линзы → `needs_revision` с этим пунктом в `blocking` (терминальный `failed:*` достигается только лимитом `max_revisions`, чтобы петля всегда давала агенту шанс исправиться).

### 4.3 Маппинг strictness → размеры/пороги (источник истины — umbrella §7 + `TIER_PRESETS`)

`_layer_sizes_for()` возвращает кортеж по `ws.strictness` и effective-config (`HEPHAESTUS_TIER1_APPROVE_THRESHOLD`/`HEPHAESTUS_TIER2_APPROVE_THRESHOLD` уже проставлены `_config_preset`):

| strictness | active_lenses (Layer 1 N) | M (arbiters) | tier1_threshold | tier2_threshold |
|---|---|---|---|---|
| `strict` | `correctness, tests, security, conventions, scope` (5) | 2 | `min(6, N)` → 5 | 2 |
| `standard` | все 5 | 2 | 5 | 2 |
| `permissive` | `correctness, tests, scope` (3) | 1 | 3 | 1 |
| `disabled` | — (0) | 0 | — | — → gate=pass без проверок |

`tier1_threshold` берётся из `int(eff["HEPHAESTUS_TIER1_APPROVE_THRESHOLD"])`, затем **клампится** в `[1, len(active_lenses)]` (страхует пресет `strict=6` при 5 линзах). Никаких новых ключей конфига для порогов не вводится. `M` для арбитров определяется `len(ws.agents.arbiters)`, ограниченный сверху значением из таблицы.

### 4.4 `GitService.merge_to_base` — `backend/app/core/git.py` (D11)

Существующий `_action_merge` (строки 115-193) сохраняется для legacy `/api/branch/{name}/merge`. Новый класс из umbrella §5.4:

```python
class GitService:
    def __init__(self, ws: "RepoProfile") -> None:
        self.ws = ws
        self.repo = ws.repo_path; self.base = ws.base_branch
        self.remote = ws.remote; self.prefix = ws.branch_prefix

    def diff(self, branch: str) -> str:
        """git diff <remote>/<base>..<branch> (cwd=repo). Кэшируется в iter_dir/diff.patch."""

    def merge_preflight(self, branch: str) -> MergePreflight:
        # Task не найден по ветке → понятная 409 в роутере, НЕ молчаливый False (R11).
        return MergePreflight(
            clean_tree   = self._clean_tree(),                 # git status --porcelain пусто
            verify_green = self._last_verify_green(branch),    # ПЕРСИСТЕНТНЫЙ item.verify_green (R11)
            validation_passed = self._validation_passed(branch),  # ПЕРСИСТЕНТНЫЙ item.validation.gate=='pass' (R11)
            loop_active  = self._loop_active(),                # pm.status('loop') == RUNNING (R11)
            base_branch  = self.base,
            conflicts    = [],                                 # заполнится только при merge-attempt
            ok           = clean and verify and validation and not loop_active and _is_safe_auto_branch(branch),
        )

    async def merge_to_base(self, branch: str, *, push: bool) -> dict:
        """0. Если pm.status('loop') == RUNNING → 409 'loop active, stop it before merge' (R11).
        1. preflight = merge_preflight(branch); если not preflight.ok → return {ok:False, error, preflight}.
        2. git checkout base; git pull --ff-only remote base (как _action_merge).
        3. git merge --no-ff --no-edit -m 'merge: <subj> (from <branch>)' branch.
           Конфликт (rc!=0) → собрать conflicts = git diff --name-only --diff-filter=U;
           git merge --abort; return {ok:False, conflicts, error:'merge conflict'}.
        4. Если push: git push remote base (сохранить push-before-delete семантику _action_merge:
           при push-failed НЕ удалять ветку, вернуть merged-not-pushed).
        5. git branch -D branch; _update_item_by_branch(branch,'merged',{...}); _append_decision.
        Возврат {ok:True, action:'merge', branch, newHead, push}."""
```

`_clean_tree`, `_last_verify_green`, `_validation_passed`, `_loop_active`, `_find_item_by_branch` — приватные хелперы:
- `_clean_tree()` → `_run(["git","status","--porcelain"], cwd=self.repo) == ""`.
- `_find_item_by_branch(branch)` → ищет `Task` в state по `item["branch"] == branch`; `None`, если не найден (роутер тогда отдаёт **409**, R11).
- `_last_verify_green(branch)` → читает **персистентный** `item.verify_green` (bool, который FSM пишет после зелёного verify, R11) — НЕ эвристика по префиксу статуса; `item is None` → False.
- `_validation_passed(branch)` → **персистентный** `item.validation["gate"] == "pass"` (R11); как fallback может прочитать `iter_dir/validation/layer3/final.json`; `item is None` → False.
- `_loop_active()` → `pm.status("loop").state == ProcState.RUNNING` через module-singleton `from app.core.process import pm` (R11); merge запрещён, пока loop RUNNING.

### 4.5 API-эндпоинты (umbrella §6; форма ответа `ok_response`/`error_response` из `main.py:57-65`)

`backend/app/api/v1/merge.py`:

```python
from app.core.workspaces import active_workspace   # R4: единый источник, НЕ workspace_registry

router = APIRouter()

@router.get("/api/v1/branches/{name}/merge-preflight")
def merge_preflight(name: str) -> dict:
    """decoded = unquote(name); guard len<=250 и _is_safe_auto_branch → 400 при провале.
    ws = active_workspace(); if ws is None → error_response('no active workspace', status=409).
    pf = GitService(ws).merge_preflight(decoded).
    return ok_response(pf.model_dump(by_alias=True))."""

@router.post("/api/v1/branches/{name}/merge")
async def merge_branch(name: str, body: MergeRequest) -> dict:
    """guard как выше → 400. ws = active_workspace(); if ws is None → 409 'no active workspace'.
    res = await GitService(ws).merge_to_base(decoded, push=body.push).
    merge_to_base сам отдаёт {ok:False,...} при loop RUNNING ('loop active, stop it before merge', R11),
    при конфликте (conflicts=[...]) и при Task-не-найден.
    if not res['ok']: return error_response(res.get('error','merge failed'), status=409, **res).
    return ok_response(res)."""
```

`backend/app/models/validation.py`:

```python
class MergeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    push: bool = False

class MergePreflightResponse(BaseModel):    # camelCase зеркало MergePreflight (R11)
    model_config = ConfigDict(populate_by_name=True)
    clean_tree: bool = Field(..., alias="cleanTree")
    verify_green: bool = Field(..., alias="verifyGreen")
    validation_passed: bool = Field(..., alias="validationPassed")
    loop_active: bool = Field(False, alias="loopActive")     # pm.status('loop')==RUNNING (R11)
    base_branch: str = Field(..., alias="baseBranch")
    conflicts: list[str] = []
    ok: bool
```

`active_workspace()` — функция из Stage 1, импортируется как `from app.core.workspaces import active_workspace, registry` (umbrella §10.1, R4: единый источник — `WorkspaceRegistry` в `backend/app/core/workspaces.py`, `registry.active() -> RepoProfile | None` и модульная обёртка `active_workspace()`). **Запрещён** несуществующий модуль `app.core.workspace_registry`. Stage 3 её **потребляет**, не определяет (см. §10 crossRefs). Если активного воркспейса нет (`active_workspace() is None`) → `error_response("no active workspace", status=409)`.

### 4.6 Форматы промптов агентов воронки

Все валидаторы — **строго read-only** (наследуют hard-rules из `prompts/review-tier1.md:5-12`), на ветке, которую поставил FSM. Выходной блок парсится `validators.py::_parse_lens_block` (по аналогии с `events.py`-defensive-parsing).

**`prompts/validate-lens.md`** (переменные `{{lens}}`, `{{lens_focus}}`, `{{item_id}}`, `{{prompt_excerpt}}`, `{{diff}}`):

```
VALIDATION_VERDICT_BEGIN
lens: {{lens}}
verdict: approve | needs_revision | reject
confidence: 0.0..1.0
evidence: <file:line cite or "diff hunk N">
top_issues: <comma-separated, or "none">
reasoning: <2-3 sentences>
VALIDATION_VERDICT_END
```

**`prompts/validate-arbiter.md`** (`{{layer1_digest}}` — JSON-массив `LensVerdict`):

```
ARBITER_VERDICT_BEGIN
verdict: approve | needs_revision | reject
dedup_findings: <bullet list of unique blocking findings, severity-tagged>
agree_with_lenses: <agree | partial | disagree>
reasoning: <3-4 sentences>
ARBITER_VERDICT_END
```

**`prompts/validate-final.md`** (`{{layer1_digest}}`, `{{layer2_digest}}`):

```
FINAL_GATE_BEGIN
gate: pass | needs_revision
blocking: <semicolon-separated concrete items the implementer must fix, or "none">
notes: <one line for the human operator>
FINAL_GATE_END
```

**`prompts/revision-feedback.md`** (`{{item_id}}`, `{{attempt}}`, `{{max_revisions}}`, `{{blocking}}`, `{{lens_findings}}`, `{{proposal}}`, `{{acceptance}}`) — НЕ read-only; это инструкция имплементеру: «attempt N of M, исправь следующее: <blocking>; не выходи за scope; добавь/почини тесты; сохрани прошлые изменения». Парсинг результата — обычный `_run_opencode` → `output.primary.jsonl`.

`_parse_lens_block(text, lens)` — defensive: ищет последний `VALIDATION_VERDICT_BEGIN…END`, парсит `key: value`-строки; `verdict` нормализуется к `{approve,needs_revision,reject}` (любое иное → `needs_revision`); `confidence` парсится как float, при `0..10`-форме делится на 10; отсутствие блока → `LensVerdict(lens, "needs_revision", 0.0, "no verdict block emitted")`.

### 4.7 Frontend-контракты

`frontend/src/types/api.ts` (добавления):

```typescript
export type ItemStatus =
  | 'pending' | 'in_progress' | 'in_review' | 'done' | 'merged'
  | 'needs_revision' | 'discarded' | `failed:${string}`

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
}
export interface MergePreflightResponse {
  cleanTree: boolean; verifyGreen: boolean; validationPassed: boolean
  loopActive: boolean; baseBranch: string; conflicts: string[]; ok: boolean
}
export interface MergeResult {
  ok: boolean; action?: 'merge'; branch?: string; newHead?: string
  push?: string; conflicts?: string[]; error?: string
  preflight?: MergePreflightResponse
}
// Item += : validation?: ValidationResult | null; resultSummary?: string; diffRef?: string | null
```

`frontend/src/api/client.ts` (добавления в `api`):

```typescript
mergePreflight: (name: string) =>
  request<{ ok: boolean } & MergePreflightResponse>(`/api/v1/branches/${encodeURIComponent(name)}/merge-preflight`),
merge: (name: string, push: boolean) =>
  request<MergeResult>(`/api/v1/branches/${encodeURIComponent(name)}/merge`, { method: 'POST', body: JSON.stringify({ push }) }),
```

`ValidationPanel.vue` (props `validation: ValidationResult | null`): три секции — Layer 1 (строка на линзу: цвет verdict `approve`=green/`needs_revision`=amber/`reject`=rose, бейдж confidence), Layer 2 (свод арбитров), Gate (крупный `pass`/`needs_revision` + `blocking`-список). `MergeButton.vue` (props `branch: string`): on-mount `api.mergePreflight`; кнопка disabled пока `!preflight.ok`, tooltip перечисляет невыполненные предусловия; чекбокс «push после merge»; при ответе с `conflicts` — модалка со списком файлов и подсказкой «разрешите конфликт вручную в рабочей копии». `RunTimeline.vue` рендерит фазы FSM + revision-петли (`attempts`) с временными метками из `iter_dir` событий.

---

## 5. Поток данных (Stage 3)

```
loop (FSM) per item:
  … COMMIT → PARSE_RESULT
  PARSE_RESULT:
     GitService(ws).diff(branch) → iter-NNNN/diff.patch  (diff_ref = "<iter>/diff.patch")
     summary.md ← из output.primary.jsonl (текст последнего text-события) → Task.result_summary
  status = in_review
  VALIDATE (ValidationFunnel.run_funnel) — внутренние asyncio-подпроцессы оркестратора (НЕ ProcessManager, R2):
     Layer1: N×AgentRunner(validators, fallback [primary]*N) ─concurrent─▶ validation/layer1/<lens>.jsonl (+<lens>.json)
        └ _aggregate_layer1(threshold=tier1_threshold) → (passed, blocking[])
     Layer2: M×AgentRunner(arbiters)   ─concurrent─▶ validation/layer2/arbiter-<i>.json
        └ все арбитры errored → L2 не штрафуется (опора на L1+L3, R20)
     Layer3: 1×AgentRunner(final, fallback primary) ─────────▶ validation/layer3/final.json
        → ValidationResult{gate, blocking, layer1, layer2Summary, revision}
  gate == pass        → CLEANUP → status=done; item.verify_green + Task.validation persisted
  gate == needs_rev   → build_revision_prompt → OPENCODE(feedback) → VERIFY → COMMIT → PARSE_RESULT
                        → status=in_review → VALIDATE (revision+1)
                        attempts > max_revisions → status=failed:max-revisions

UI merge:
  TaskDrawer → MergeButton mount → GET /api/v1/branches/<branch>/merge-preflight
     → {cleanTree, verifyGreen, validationPassed, loopActive, ok}
  click Merge → POST /api/v1/branches/<branch>/merge {push}
     → GitService(ws).merge_to_base:
          loop RUNNING? ─yes→ 409 'loop active, stop it before merge' (R11)
          Task не найден по ветке? ─yes→ 409 (R11)
          preflight.ok? ─no→ 409 {error, preflight}
          checkout base → pull --ff-only → merge --no-ff
          conflict? ─yes→ git merge --abort → 409 {conflicts:[...]}
          push? → git push (push-failed → merged-not-pushed, branch kept)
          → branch -D; item.status=merged; decisions.log
  WS /ws/board broadcast → board refresh
```

Контракт памяти/state не нарушается: `validation/**` и `diff.patch`/`summary.md` живут в `iter-NNNN/` (umbrella §4.4); `decisions.log` фиксирует `merge`/`validate`-решения через `_append_decision`.

## 6. Обработка ошибок и граничные случаи

1. **Валидатор упал/таймаут.** `asyncio.gather(..., return_exceptions=True)`; исключение/таймаут линзы → `LensVerdict(verdict="needs_revision", confidence=0.0, reasoning="validator <lens> errored: <type>")`. Воронка не падает; недостача голосов толкает к `needs_revision` (безопасная сторона).
2. **Все валидаторы упали.** `_aggregate_layer1` → `passed=False`, `blocking=["all validators failed — check opencode availability"]`; Layer 3 даёт `needs_revision`; при исчерпании попыток → `failed:max-revisions`. FSM не зависает.
2a. **Все арбитры errored (R20).** Если ВСЕ Layer 2-арбитры упали из-за сбоя запуска (не вынесли вердикт по существу), Layer 2 **не штрафуется** — гейт опирается на L1+L3, как при `M==0`. Это отличает «арбитры отклонили» (→ `needs_revision` с `'arbiters: X of <t2> approvals'` в `blocking`) от «арбитры не отработали».
3. **opencode не на PATH.** `AgentRunner.run` → `AgentResult(exit_code=-1)`; линза трактуется как (1). Для merge-фазы opencode не нужен — merge не блокируется отсутствием CLI.
4. **strictness=disabled / review.enabled=False.** `run_funnel` мгновенно `ValidationResult(gate="pass", layer1=[], layer2Summary=[], blocking=[], revision=revision)`; `validationPassed` в preflight = True (gate==pass).
5. **Грязное дерево перед merge.** `merge_preflight.clean_tree=False` → кнопка disabled; POST merge при гонке → `merge_to_base` повторно проверяет preflight, 409 `{error:"working tree not clean"}`.
6. **Merge-конфликт.** `git merge` rc!=0 → `conflicts = git diff --name-only --diff-filter=U`; `git merge --abort`; 409 `{ok:False, conflicts:[...]}`. Состояние рабочей копии возвращается к base (abort гарантирует). UI показывает файлы и инструкцию ручного разрешения; авторазрешения нет (вне scope).
7. **Push-fail после успешного merge.** Сохраняем семантику `_action_merge`: ветка НЕ удаляется, item не помечается merged, ответ `merged-not-pushed` с `ok:False` и пояснением (чтобы driver `ensure_clean_base` не затёр локальный merge).
8. **Driver занят веткой (`_driver_busy_on`).** merge-preflight/merge отклоняются 409 как в legacy `_action_merge:122`.
9. **`base_branch` не существует / нет remote.** `checkout base` rc!=0 → 409 `{error:"checkout <base>: <stderr>"}` (как `_action_merge:130`). `ws`-scoped, не глобальный.
10. **Невалидное имя ветки** (`_is_safe_auto_branch=False`, traversal, `--flag`-like) → 400 ещё до git-операций.
11. **Гонка revision-петли и stop.** `request_stop()` проверяется в `while True`-петле перед каждой новой ревизией; при stop текущая ревизия дорабатывает, статус остаётся `in_review` (не теряется), checkpoint пишется (`fsm-checkpoint.json`), при рестарте `_recover_checkpoint` чистит stale.
12. **Кроссплатформенность.** Все пути — `pathlib.Path`; JSON-чтение `read_text(errors="replace")`; subprocess — список аргументов (без `shell=True`); таймауты — `asyncio.wait_for`. Нет SIGKILL-предположений (умолчания `ProcessManager`).
13. **Merge при активном loop (R11).** `pm.status("loop").state == RUNNING` → `merge_to_base`/preflight отдают 409 `'loop active, stop it before merge'`; одновременная запись в base из loop и merge-UI исключается. (Worktree-альтернатива — будущее.)
14. **Task не найден по ветке (R11).** `_find_item_by_branch(branch) is None` → роутер отдаёт понятную **409**, а НЕ молчаливый `ok:False` без объяснения; `verify_green`/`validation_passed` при этом False.

## 7. Тестирование (кроссплатформенно, без bash)

Backend (`backend/tests/`), `pytest` + `pytest-asyncio`; все тесты должны проходить на Windows и POSIX (CI-матрица).

**Unit — `tests/unit/test_validators.py`:**
- `test_aggregate_layer1_threshold` — 5 линз, 4 approve, threshold=5 → `passed=False`; threshold=4 → `passed=True`.
- `test_aggregate_layer1_high_conf_reject_blocks` — 5 approve но один `reject@confidence=0.8` → `passed=False`.
- `test_layer_sizes_for_clamps_threshold` — strictness=strict (preset threshold=6), 5 линз → threshold клампится к 5.
- `test_layer_sizes_permissive` → `("correctness","tests","scope")`, M=1, threshold=3.
- `test_disabled_short_circuits` — `review.enabled=False` → `run_funnel` без вызова runner, `gate="pass"` (мокнутый `AgentRunner` НЕ вызывается — `assert runner.run.call_count == 0`).
- `test_parse_lens_block_defensive` — отсутствие блока → `needs_revision/0.0`; `confidence: 8` (0..10-форма) → `0.8`; мусорный verdict → `needs_revision`.

**Unit — `tests/unit/test_build_revision_prompt.py`:**
- `test_revision_prompt_contains_blocking` — `blocking` и линзы с `verdict!=approve` присутствуют в тексте; attempt/max_revisions подставлены.

**Contract — `tests/contract/test_validation_result_contract.py`:**
- `ValidationResult.model_dump(by_alias=True)` даёт ключи `layer1, layer2Summary, gate, blocking, revision`; обратно `model_validate` фикстуры из `iter-*/validation/layer3/final.json`.
- `MergePreflightResponse` сериализуется camelCase (`cleanTree`, `verifyGreen`, `validationPassed`, `loopActive`, `baseBranch`).

**Integration — `tests/integration/test_merge_to_base.py`** (создаёт временный git-репо через `subprocess` git-команды в `tmp_path`, кроссплатформенно — git есть везде; bash не используется):
- `test_merge_clean_fast_forward` — ветка `auto/x` с коммитом → `merge_to_base(push=False)` → base содержит коммит, ветка удалена, item.status=merged.
- `test_merge_conflict_aborts` — конфликтующее изменение одного файла в base и ветке → `merge_to_base` возвращает `{ok:False, conflicts:["file"]}`; `git status --porcelain` после — чистое (abort отработал).
- `test_preflight_blocks_when_dirty` — незакоммиченный файл в рабочей копии → `merge_preflight.clean_tree=False, ok=False`.
- `test_preflight_blocks_when_validation_failed` — `Task.validation.gate="needs_revision"` → `validationPassed=False, ok=False`.

**Integration — `tests/integration/test_funnel_loop.py`** (мок `AgentRunner` — пишет заранее заданные JSONL-блоки в `output_path`):
- `test_pass_path` — все линзы approve → `run_funnel.gate="pass"`; артефакты `validation/layer1/*.json` + `validation/layer3/final.json` созданы.
- `test_validators_fallback_to_primary` — `ws.agents.validators=[]` → воронка использует `[ws.agents.primary]*N`, НЕ вырождается в `gate=pass` без проверок (R3).
- `test_all_arbiters_errored_not_penalized` — все Layer 2-арбитры падают (errored) → L2 не штрафуется, гейт по L1+L3 (R20).
- `test_needs_revision_then_pass` — revision 0 → needs_revision, revision 1 → pass; `_process_item` завершает `status=done`, `attempts==1`.
- `test_max_revisions_exhausted` — всегда needs_revision; `max_revisions=2` → `status=failed:max-revisions`, `attempts==3`.

**Contract — `tests/contract/test_merge_api.py`** (FastAPI `TestClient`):
- `GET /api/v1/branches/<auto>/merge-preflight` форма `{ok, cleanTree, loopActive, ...}`.
- `POST /api/v1/branches/<unsafe>/merge` → 400; невалидное → 400; конфликт → 409 с `conflicts`.
- нет активного воркспейса (`active_workspace()` → None) → 409 'no active workspace' (R4).
- loop RUNNING (`pm.status('loop')==RUNNING`) → 409 'loop active, stop it before merge' (R11).

**Frontend (`vitest`):**
- `ValidationPanel.spec.ts` — рендерит N линз, цвет по verdict, `pass`/`needs_revision`-гейт, `blocking`-список.
- `MergeButton.spec.ts` — кнопка disabled при `ok:false`; tooltip перечисляет невыполненные предусловия; merge-конфликт → модалка со списком файлов.

**Запрещено:** любые тесты, требующие `tmux`/`bash`/`pgrep`. `test_lock_contract.py` (bash flock) из Phase 0 не расширяется в этом этапе — bash-сторона удалена (umbrella §9).

## 8. Зависимости и пины

Новых runtime-зависимостей **нет**. Используются уже запинованные (umbrella/Phase 0): `fastapi ^0.115`, `pydantic ^2.11`, `pydantic-settings ^2.9`, `pytest ^8.3`, `pytest-asyncio ^0.25`; `asyncio`/`pathlib`/`subprocess`/`shlex` — stdlib. Frontend без новых пакетов (`vue ^3.5`, `pinia ^2`). `ProcessManager`/`AgentRunner`/`VerifyRunner` — поставляются Stage 1; `task_graph`/`project_memory`/`active_workspace` — Stage 1/2 (см. §10). YAML-frontmatter памяти парсится без `pyyaml` (ручной мини-парсер `project_memory.py`, Stage 2) — Stage 3 память только читает результат verify (через `VerifyRunner`), напрямую `verify.md` не парсит.

## 9. Exit criteria (проверяемые)

1. `pytest backend/tests/unit/test_validators.py backend/tests/unit/test_build_revision_prompt.py` — green на Windows и Linux.
2. `pytest backend/tests/integration/test_merge_to_base.py backend/tests/integration/test_funnel_loop.py` — green (git-temp-repo, без bash).
3. `pytest backend/tests/contract/test_validation_result_contract.py backend/tests/contract/test_merge_api.py` — green.
4. `ruff check backend/` и `mypy --strict backend/app/core/validators.py backend/app/api/v1/merge.py` — clean.
5. `grep -RInE "tmux|pgrep|pkill|tier-review\.sh|bash " backend/app/orchestrator/fsm.py backend/app/core/validators.py backend/app/core/git.py backend/app/api/v1/merge.py` → 0 совпадений.
6. `vitest run` — `ValidationPanel.spec.ts`, `MergeButton.spec.ts` green; `vue-tsc --noEmit` clean.
7. End-to-end (ручной, с установленным opencode + ключами): онбординнутый воркспейс → loop на 1 item с `standard` → ветка `auto/<id>`, `iter/validation/layer3/final.json` с `gate`, `diff.patch`, `summary.md`; UI показывает воронку и активную кнопку Merge при зелёном preflight; merge вливает в `base_branch`.
8. `needs_revision` демонстрируется: подложенный «провальный» diff → воронка возвращает `needs_revision`, петля делает ≤ `max_revisions` ревизий, при исчерпании — `failed:max-revisions`.

## 10. Out of scope + Rollback + crossRefs

**Out of scope (в других этапах):**
- `ProcessManager`, `AgentRunner`, `VerifyRunner`, расширение `GitService`-базы, `RepoProfile`/реестр воркспейсов, `active_workspace()`, удаление tmux/bash из `driver.py`/`scan.py`, миграция state — **Stage 1**.
- Нативный map-reduce scan, декомпозиция в `Task` с `depends_on`/`order_index`/`conflict_group`, `task_graph.can_reorder`, `project_memory.py`-writers, reorder-API — **Stage 2**. (Stage 3 потребляет `Task`-поля и `can_reorder` как предикат, но их вводит Stage 2.)
- Авторазрешение merge-конфликтов (трёхстороннее слияние агентом), rebase-стратегия, multi-branch merge-train — вне всех этапов (явный non-goal).
- i18n: строки UI остаются русскими (как в текущем frontend).

**Rollback.** Stage 3 аддитивен и in-place. Откат:
1. `git revert` коммитов Stage 3; удалить новые файлы (`validators.py`, `merge.py`, `validation.py`, `prompts/validate-*.md`, `prompts/revision-feedback.md`, `ValidationPanel.vue`, `MergeButton.vue`, `RunTimeline.vue`).
2. Вернуть `Phase.TIER_REVIEW` и no-op `_tier_review` в `fsm.py` (петля ревизий выключается — item идёт сразу в `done` после `PARSE_RESULT`, как до Stage 3).
3. Снять регистрацию `merge.router` в `main.py`; legacy `/api/branch/{name}/merge` (`_action_merge`) продолжает работать.
4. Frontend: убрать `MergeButton`/`ValidationPanel`/`RunTimeline` из `TaskDrawer`, откатить `ItemStatus`/`Item`-добавления. Доменные поля `Task` с `extra="allow"` не ломают старые записи state.

**crossRefs (заимствования из umbrella / ожидания от соседних этапов):**
- Из **umbrella** заимствую дословно: `RepoProfile`, `AgentsConfig`, `AgentRef`, `ReviewConfig` (§4.1); `Task`-поля `validation/result_summary/diff_ref/depends_on` и статус `in_review` (§4.2); layout `iter-NNNN/validation/**`, `diff.patch`, `summary.md` (§4.4); интерфейсы `ProcessManager`/`AgentRunner`/`VerifyRunner`/`GitService`/`MergePreflight` (§5); API-форму `ok_response`/`error_response` и пути `/api/v1/branches/{name}/merge-preflight|merge` (§6); `ValidationResult`/`LensVerdict` и таблицу strictness→слои (§7); инвариант «strictness-источник истины = `TIER_PRESETS`» (§10.6) и «merge только при `MergePreflight.ok`» (§10.8).
- От **Stage 1** ожидаю: рабочие `ProcessManager` (sync, PID-based, module-singleton `pm` в `app.core.process`)/`AgentRunner(pm)`/`VerifyRunner`, `GitService.__init__(ws)`-база, `from app.core.workspaces import active_workspace, registry` (`active_workspace() -> RepoProfile | None`, R4 — НЕ `app.core.workspace_registry`), извлечённый `OrchestratorFSM._build_prompt(item)` и `_run_opencode(self, item, prompt)` (R14/R15), `ws.agents.validators/arbiters/final` заполнены Profiler'ом, удаление bash/tmux из путей запуска.
- От **Stage 2** ожидаю: `Task` уже несёт `depends_on`/`touches`/`order_index`; `.hephaestus/memory/conventions.md` существует (используется линзой `conventions` через контекст промпта); `can_reorder` как единственный предикат порядка (Stage 3 его не дублирует).
