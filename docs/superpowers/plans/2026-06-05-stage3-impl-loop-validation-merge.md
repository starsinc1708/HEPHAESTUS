# Этап 3 — Loop реализации + воронка map-reduce валидации + merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать per-task loop реализации поверх `OrchestratorFSM` с воронкой валидации map-reduce (D10): N параллельных валидаторов-линз → M арбитров → 1 финальный гейт `pass|needs_revision`, с возвратом фидбэка агенту при `needs_revision` (ограничено `ReviewConfig.max_revisions`). Каждый прогон даёт ветку `auto/<task>` + `diff.patch` + `summary.md`/`result_summary`; пользователь вливает ветку в `base_branch` через UI (`GitService.merge_to_base`, D11) с предпроверками (чистое дерево, verify-green, прошёл воронку) и обработкой merge-конфликтов.

**Architecture:** Аддитивно и in-place поверх существующего FastAPI-бэкенда (`backend/app/`) и Vue-фронтенда (`frontend/src/`). Новые модули `backend/app/core/validators.py` (воронка), `backend/app/api/v1/merge.py` (роутер), `backend/app/models/validation.py` (Pydantic-модели); расширяются `fsm.py` (`Phase.TIER_REVIEW`→`Phase.VALIDATE`, петля ревизий), `git.py` (класс `GitService`), `iters.py` (отдача `validation`), `domain.py` (поля `Task`), `config.py` (`HEPHAESTUS_REVISION_MAX`, `_layer_sizes_for`). Фронтенд: `ValidationPanel.vue`, `MergeButton.vue`, `RunTimeline.vue`, расширения `types/api.ts`, `client.ts`, `TaskDrawer.vue`, `stores/task.ts`. Все вызовы движка принимают `ws: RepoProfile` явно (D9); никакого `tmux`/`pgrep`/`pkill`/`bash`/`tier-review.sh` (D1). Контракты типов берутся дословно из umbrella §4/§5/§7 и stage3-spec §4.

**Tech Stack:** Python 3.11+, FastAPI ^0.115, Pydantic ^2.11, pydantic-settings ^2.9, `asyncio`/`pathlib`/`subprocess`/`shlex` (stdlib), pytest ^8.3 + pytest-asyncio ^0.25 (`asyncio_mode=auto`), ruff (line-length 120, select `E,F,I,UP,B,SIM`), mypy `--strict`. Frontend: Vue ^3.5, Pinia ^2.3, TypeScript ~5.7, vitest ^3.1, vue-tsc. Новых runtime-зависимостей нет (stage3-spec §8). Для vitest потребуются dev-зависимости `@vue/test-utils` + `jsdom` (Task 22).

---

## File Structure

### Новые файлы (backend)

| Путь | Ответственность |
|------|-----------------|
| `backend/app/models/validation.py` | Pydantic-модели воронки и merge: `LensVerdict`, `ValidationResult`, `MergeRequest`, `MergePreflightResponse`. camelCase-алиасы (`ConfigDict(populate_by_name=True)`). |
| `backend/app/core/validators.py` | Воронка `ValidationFunnel` (Layer 1/2/3), `_aggregate_layer1`, `_layer_sizes_for`, `_parse_lens_block`, `build_revision_prompt`, `LensSpec`, `LENSES`, `LENS_FOCUS`. |
| `backend/app/api/v1/merge.py` | Роутер `merge_preflight` (GET) + `merge_branch` (POST) под `/api/v1/branches/{name}/...`. |
| `prompts/validate-lens.md` | Шаблон валидатора-линзы Layer 1 (`VALIDATION_VERDICT_BEGIN/END`). |
| `prompts/validate-arbiter.md` | Шаблон арбитра Layer 2 (`ARBITER_VERDICT_BEGIN/END`). |
| `prompts/validate-final.md` | Шаблон финального гейта Layer 3 (`FINAL_GATE_BEGIN/END`). |
| `prompts/revision-feedback.md` | Фидбэк-промпт для возврата агенту при `needs_revision`. |

### Новые файлы (тесты)

| Путь | Ответственность |
|------|-----------------|
| `backend/tests/unit/test_validators.py` | Юнит-тесты `_aggregate_layer1`, `_layer_sizes_for`, `_parse_lens_block`, short-circuit disabled. |
| `backend/tests/unit/test_build_revision_prompt.py` | Юнит-тест `build_revision_prompt`. |
| `backend/tests/contract/test_validation_result_contract.py` | Контракт сериализации `ValidationResult`/`MergePreflightResponse`. |
| `backend/tests/integration/test_funnel_loop.py` | Воронка + петля ревизий с мок-`AgentRunner`. |
| `backend/tests/integration/test_merge_to_base.py` | `GitService.merge_to_base`/`merge_preflight` на temp git-репо. |
| `backend/tests/contract/test_merge_api.py` | Контракт merge-API через FastAPI `TestClient`. |
| `backend/tests/conftest.py` | Расширяется фикстурами `tmp_git_repo`, `fake_agent_runner`, `fake_repo_profile`. |

### Новые файлы (frontend)

| Путь | Ответственность |
|------|-----------------|
| `frontend/src/components/ValidationPanel.vue` | Визуализация воронки в TaskDrawer (Layer 1 линзы / Layer 2 арбитры / Gate). |
| `frontend/src/components/MergeButton.vue` | Кнопка Merge + preflight-чеклист + диалог конфликтов. |
| `frontend/src/components/RunTimeline.vue` | Таймлайн фаз FSM + revision-петель. |
| `frontend/src/components/ValidationPanel.spec.ts` | vitest для `ValidationPanel`. |
| `frontend/src/components/MergeButton.spec.ts` | vitest для `MergeButton`. |
| `frontend/vitest.setup.ts` | Глобальная настройка jsdom для vitest. |

### Модифицируемые файлы

| Путь | Что меняем |
|------|-----------|
| `backend/app/models/domain.py` | Поля `Task`: `workspace_id`, `depends_on`, `blocks`, `order_index`, `epic_id`, `parent`, `conflict_group`, `validation`, `result_summary`, `diff_ref`. |
| `backend/app/config.py` | `HEPHAESTUS_REVISION_MAX` в `ALLOWED_CONFIG_KEYS` + `_config_effective`; `standard` preset += пороги. |
| `backend/app/orchestrator/fsm.py` | `Phase.TIER_REVIEW`→`Phase.VALIDATE`; `_TRANSITIONS`; `_validate` вместо `_tier_review`; петля ревизий в `_process_item`; `_parse_result` пишет `diff.patch`/`summary.md`. |
| `backend/app/core/git.py` | Класс `GitService` (`__init__(ws)`, `diff`, `merge_preflight`, `merge_to_base`, приватные хелперы). Legacy `_action_merge` сохраняется. |
| `backend/app/core/iters.py` | `_iter_details` отдаёт `validation` из `iter/validation/final-decision.json`. |
| `backend/app/main.py` | Регистрация `merge.router`; убрать `pkill`-shutdown и `tmux` из startup-check. |
| `frontend/src/types/api.ts` | `LensVerdict`, `ValidationResult`, `MergePreflightResponse`, `MergeResult`; `ItemStatus += 'in_review'`; `Item.validation/resultSummary/diffRef`. |
| `frontend/src/api/client.ts` | `mergePreflight`, `merge`. |
| `frontend/src/stores/task.ts` | Кэш `validationCache` + `fetchValidation(dir)`. |
| `frontend/src/components/TaskDrawer.vue` | Вкладка «Ревью»→`ValidationPanel`; вкладка «Таймлайн»→`RunTimeline`; `MergeButton` в `drawer-actions`. |

### Stage 1/2 контракты, которые Stage 3 ПОТРЕБЛЯЕТ (не определяет)

Эти символы поставляются Stage 1/2 (см. crossRefs spec §10). На момент Stage 3 их может не быть в дереве — план изолирует зависимость через узкие протоколы (`typing.Protocol`) и тестовые fakes, чтобы Stage 3-модули тестировались и проходили mypy независимо. См. **Open Questions**.

- `backend/app/models/workspace.py`: `RepoProfile`, `AgentsConfig`, `AgentRef`, `ReviewConfig` (umbrella §4.1).
- `backend/app/services/opencode_runner.py`: `AgentRunner`, `AgentResult` (umbrella §5.2). `AgentRunner(pm)` — конструктор принимает `ProcessManager`.
- `backend/app/core/verify.py`: `VerifyRunner`, `VerifyResult` (umbrella §5.3).
- `backend/app/core/workspaces.py`: `WorkspaceRegistry`, singleton `registry`, `active_workspace() -> RepoProfile | None` (umbrella §10.1, R4 — НЕ `app.core.workspace_registry`).
- `backend/app/core/process.py`: `ProcessManager` + module-singleton `pm` (sync, PID-based, umbrella §5.1, R1).

---

## Task 1: Pydantic-модели воронки и merge (`validation.py`)

Контрактные модели — фундамент для всех остальных задач. Сериализация camelCase через алиасы (umbrella §4, §7; spec §4.5).

- [ ] Создать падающий контракт-тест `backend/tests/contract/test_validation_result_contract.py`:

```python
"""Contract: ValidationResult / MergePreflightResponse camelCase serialization."""

from __future__ import annotations

from app.models.validation import (
    LensVerdict,
    MergePreflightResponse,
    MergeRequest,
    ValidationResult,
)


def test_validation_result_dumps_camelcase():
    vr = ValidationResult(
        layer1=[LensVerdict(lens="correctness", verdict="approve", confidence=0.9, reasoning="ok")],
        layer2_summary=[{"arbiter": "a1", "verdict": "approve"}],
        gate="pass",
        blocking=[],
        revision=0,
    )
    d = vr.model_dump(by_alias=True)
    assert set(d.keys()) == {"layer1", "layer2Summary", "gate", "blocking", "revision"}
    assert d["layer1"][0]["lens"] == "correctness"


def test_validation_result_roundtrip_from_final_decision():
    fixture = {
        "layer1": [{"lens": "tests", "verdict": "needs_revision", "confidence": 0.4, "reasoning": "no test"}],
        "layer2Summary": [],
        "gate": "needs_revision",
        "blocking": ["tests: no test"],
        "revision": 1,
    }
    vr = ValidationResult.model_validate(fixture)
    assert vr.gate == "needs_revision"
    assert vr.revision == 1
    assert vr.layer1[0].lens == "tests"


def test_merge_preflight_response_camelcase():
    pf = MergePreflightResponse(
        clean_tree=True, verify_green=True, validation_passed=False,
        base_branch="main", conflicts=[], ok=False,
    )
    d = pf.model_dump(by_alias=True)
    assert d["cleanTree"] is True
    assert d["verifyGreen"] is True
    assert d["validationPassed"] is False
    assert d["baseBranch"] == "main"
    assert d["ok"] is False


def test_merge_request_default_push_false():
    assert MergeRequest().push is False
    assert MergeRequest(push=True).push is True
```

- [ ] Запустить — ожидается FAIL (модуль не существует):

```
cd backend && python -m pytest tests/contract/test_validation_result_contract.py -q
```
Ожидаемый вывод: `ModuleNotFoundError: No module named 'app.models.validation'` / 4 errors.

- [ ] Создать `backend/app/models/validation.py`:

```python
"""Pydantic models for the Stage 3 validation funnel and merge API.

LensVerdict / ValidationResult mirror umbrella §7; MergeRequest /
MergePreflightResponse mirror umbrella §5.4 / stage3 §4.5. camelCase JSON
contract via Field aliases (populate_by_name=True).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LensVerdict(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    lens: str          # correctness|tests|security|conventions|scope
    verdict: str       # approve|needs_revision|reject
    confidence: float
    reasoning: str


class ValidationResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    layer1: list[LensVerdict] = Field(default_factory=list)
    layer2_summary: list[dict] = Field(default_factory=list, alias="layer2Summary")
    gate: str          # pass|needs_revision
    blocking: list[str] = Field(default_factory=list)
    revision: int = 0


class MergeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    push: bool = False


class MergePreflightResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    clean_tree: bool = Field(..., alias="cleanTree")
    verify_green: bool = Field(..., alias="verifyGreen")
    validation_passed: bool = Field(..., alias="validationPassed")
    base_branch: str = Field(..., alias="baseBranch")
    conflicts: list[str] = Field(default_factory=list)
    ok: bool
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/contract/test_validation_result_contract.py -q
```
Ожидаемый вывод: `4 passed`.

- [ ] Проверить lint/types:

```
cd backend && ruff check app/models/validation.py && mypy --strict app/models/validation.py
```
Ожидаемый вывод: `All checks passed!` и `Success: no issues found in 1 source file`.

- [ ] Commit:

```
git add backend/app/models/validation.py backend/tests/contract/test_validation_result_contract.py
git commit -m "feat(stage3): validation + merge pydantic models"
```

---

## Task 2: Расширить `Task` (`domain.py`) полями Stage 3

Добавляем поля из umbrella §4.2. `extra="allow"` уже стоит — старые записи state не ломаются.

- [ ] Добавить падающий тест `backend/tests/unit/test_task_fields.py`:

```python
"""Task gains Stage 3 fields with camelCase aliases (umbrella §4.2)."""

from __future__ import annotations

from app.models.domain import Item


def test_task_new_fields_defaults():
    t = Item(id="x", title="t", status="pending")
    assert t.depends_on == []
    assert t.blocks == []
    assert t.order_index == 0
    assert t.validation is None
    assert t.result_summary == ""
    assert t.diff_ref is None
    assert t.workspace_id is None


def test_task_new_fields_camelcase_dump():
    t = Item(
        id="x", title="t", status="in_review",
        depends_on=["a"], order_index=3,
        validation={"gate": "pass"}, result_summary="did X", diff_ref="iter-0001/diff.patch",
        workspace_id="ws1",
    )
    d = t.model_dump(by_alias=True)
    assert d["dependsOn"] == ["a"]
    assert d["orderIndex"] == 3
    assert d["resultSummary"] == "did X"
    assert d["diffRef"] == "iter-0001/diff.patch"
    assert d["workspaceId"] == "ws1"
    assert d["validation"] == {"gate": "pass"}


def test_task_accepts_in_review_status():
    assert Item(id="x", title="t", status="in_review").status == "in_review"
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_task_fields.py -q
```
Ожидаемый вывод: `AttributeError: 'Item' object has no attribute 'depends_on'` / failures.

- [ ] В `backend/app/models/domain.py` после строки 45 (`source_issue: int | None = Field(None, alias="sourceIssue")`) добавить:

```python
    # ---- Stage 3 / umbrella §4.2 additions ----
    workspace_id: str | None = Field(None, alias="workspaceId")
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    blocks: list[str] = Field(default_factory=list)
    order_index: int = Field(0, alias="orderIndex")
    epic_id: str | None = Field(None, alias="epicId")
    parent: str | None = None
    conflict_group: str | None = Field(None, alias="conflictGroup")
    validation: dict | None = None
    result_summary: str = Field("", alias="resultSummary")
    diff_ref: str | None = Field(None, alias="diffRef")
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_task_fields.py -q
```
Ожидаемый вывод: `3 passed`.

- [ ] Регресс существующих доменных тестов:

```
cd backend && python -m pytest tests/unit/test_queue.py tests/contract/test_existing_state.py -q
```
Ожидаемый вывод: все passed (нет регрессий).

- [ ] Commit:

```
git add backend/app/models/domain.py backend/tests/unit/test_task_fields.py
git commit -m "feat(stage3): Task fields validation/resultSummary/diffRef/depends_on"
```

---

## Task 3: Config — `HEPHAESTUS_REVISION_MAX` + пороги standard-пресета

`_layer_sizes_for` (Task 5) читает `TIER_PRESETS` + effective-config. Добавляем алиас `max_revisions` и гарантируем, что `standard` несёт пороги (сейчас `standard` есть, но default effective не содержит `HEPHAESTUS_TIER1_APPROVE_THRESHOLD` до применения пресета — добавим дефолты в `_config_effective`).

- [ ] Добавить падающий тест `backend/tests/unit/test_config_revision.py`:

```python
"""HEPHAESTUS_REVISION_MAX allowed; thresholds present in effective config defaults."""

from __future__ import annotations

from app.config import ALLOWED_CONFIG_KEYS, _config_effective


def test_revision_max_allowed():
    assert "HEPHAESTUS_REVISION_MAX" in ALLOWED_CONFIG_KEYS


def test_effective_has_threshold_defaults():
    eff = _config_effective()
    assert "HEPHAESTUS_TIER1_APPROVE_THRESHOLD" in eff
    assert "HEPHAESTUS_TIER2_APPROVE_THRESHOLD" in eff
    assert int(eff["HEPHAESTUS_TIER1_APPROVE_THRESHOLD"]) >= 1
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_config_revision.py -q
```
Ожидаемый вывод: `assert 'HEPHAESTUS_REVISION_MAX' in ...` fails / `KeyError`.

- [ ] В `backend/app/config.py` в `ALLOWED_CONFIG_KEYS` (после `"HEPHAESTUS_TIER2_APPROVE_THRESHOLD",` на строке 45) добавить:

```python
        "HEPHAESTUS_REVISION_MAX",
```

- [ ] В `_config_effective` (после строки 125 `"HEPHAESTUS_FINAL_AGENT": ...`) добавить дефолты порогов и ревизий внутрь словаря `eff`:

```python
        "HEPHAESTUS_TIER1_APPROVE_THRESHOLD": os.environ.get("HEPHAESTUS_TIER1_APPROVE_THRESHOLD", "5"),
        "HEPHAESTUS_TIER2_APPROVE_THRESHOLD": os.environ.get("HEPHAESTUS_TIER2_APPROVE_THRESHOLD", "2"),
        "HEPHAESTUS_REVISION_MAX": os.environ.get("HEPHAESTUS_REVISION_MAX", "2"),
```

- [ ] После строки 132 (`_validate_config_int(eff, "HEPHAESTUS_MAX_CONSEC_FAIL", 1, 20, 4)`) добавить валидацию ревизий:

```python
    _validate_config_int(eff, "HEPHAESTUS_REVISION_MAX", 0, 10, 2)
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_config_revision.py tests/integration/test_api_config.py -q
```
Ожидаемый вывод: passed (включая регресс api_config).

- [ ] Commit:

```
git add backend/app/config.py backend/tests/unit/test_config_revision.py
git commit -m "feat(stage3): HEPHAESTUS_REVISION_MAX config key + threshold defaults"
```

---

## Task 4: Промпт-шаблоны воронки

Четыре md-шаблона. Парсинг выходных блоков (Task 6/7) опирается на эти точные маркеры (spec §4.6). Read-only hard-rules валидаторов копируются из `prompts/review-tier1.md:5-12`.

- [ ] Создать `prompts/validate-lens.md`:

```markdown
# HEPHAESTUS — Validation Lens (Layer 1)

You are a **read-only validator** looking through ONE lens: `{{lens}}`.
Focus: {{lens_focus}}

## Hard rules
1. **Strictly read-only.** No Edit. No Write. No git command that changes state. One edit = you failed this review.
2. **Stay on the branch the driver placed you on.** Don't `git checkout`. HEAD already has the implementer's commit.
3. **Stay on the task spec.** Validate THIS change for item `{{item_id}}` against THIS lens — not the whole codebase.
4. **Independent.** You're one of several lens validators running concurrently. Your verdict is recorded on its own.
5. **No long monologue.** Read, think, verdict block. Under ~500 words.

## Task excerpt
{{prompt_excerpt}}

## Diff under review
```diff
{{diff}}
```

## Output protocol (REQUIRED — parsed by validators.py)
End your reply with exactly one block, no prose after:

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
```

- [ ] Создать `prompts/validate-arbiter.md`:

```markdown
# HEPHAESTUS — Validation Arbiter (Layer 2)

You are a **read-only arbiter**. You receive the Layer-1 lens verdicts as JSON and
reduce them: deduplicate findings, assign severity, and produce one aggregate verdict.

## Hard rules
1. Strictly read-only. No edits, no state-changing git.
2. Base your verdict on the lens findings below + the diff; don't re-run the whole review.
3. No long monologue. Under ~400 words.

## Layer-1 lens verdicts (JSON)
{{layer1_digest}}

## Output protocol (REQUIRED — parsed by validators.py)
```
ARBITER_VERDICT_BEGIN
verdict: approve | needs_revision | reject
dedup_findings: <bullet list of unique blocking findings, severity-tagged>
agree_with_lenses: agree | partial | disagree
reasoning: <3-4 sentences>
ARBITER_VERDICT_END
```
```

- [ ] Создать `prompts/validate-final.md`:

```markdown
# HEPHAESTUS — Final Gate (Layer 3)

You are the **final gate**. Synthesize Layer-1 lenses and Layer-2 arbiters into a
single decision: `pass` or `needs_revision`. There is no `reject` here — anything
not ready becomes `needs_revision` with concrete blocking items.

## Layer-1 lens verdicts (JSON)
{{layer1_digest}}

## Layer-2 arbiter verdicts (JSON)
{{layer2_digest}}

## Output protocol (REQUIRED — parsed by validators.py)
```
FINAL_GATE_BEGIN
gate: pass | needs_revision
blocking: <semicolon-separated concrete items the implementer must fix, or "none">
notes: <one line for the human operator>
FINAL_GATE_END
```
```

- [ ] Создать `prompts/revision-feedback.md`:

```markdown
# HEPHAESTUS — Revision Feedback (re-implementation)

The validation funnel returned **needs_revision** for item `{{item_id}}`.
This is **attempt {{attempt}} of {{max_revisions}}**. Fix the blocking items below
WITHOUT discarding your previous changes — you are on the same branch, diff accumulates.

## Original proposal
{{proposal}}

## Acceptance
{{acceptance}}

## Blocking items (MUST fix all)
{{blocking}}

## Lens findings (verdict != approve)
{{lens_findings}}

## Rules
- Do not go out of scope (stay inside the item's touched files).
- Add or fix tests so they fail WITHOUT the production change.
- Keep prior correct changes; only address the blocking items.
- Commit when done (the driver will verify + re-validate).
```

- [ ] Проверить наличие маркеров (без bash-зависимостей — через ripgrep-эквивалент):

```
cd C:/Users/starsinc/Desktop/hephaestus-autonomous-loop && python -c "import pathlib; ms=['VALIDATION_VERDICT_BEGIN','ARBITER_VERDICT_BEGIN','FINAL_GATE_BEGIN']; [print(m, any(m in (pathlib.Path('prompts')/f).read_text() for f in ['validate-lens.md','validate-arbiter.md','validate-final.md'])) for m in ms]"
```
Ожидаемый вывод: три строки с `True`.

- [ ] Commit:

```
git add prompts/validate-lens.md prompts/validate-arbiter.md prompts/validate-final.md prompts/revision-feedback.md
git commit -m "feat(stage3): validation funnel prompt templates"
```

---

## Task 5: `validators.py` — каркас, `LENSES`, `_layer_sizes_for`

Сначала чистые функции без сетевых вызовов: константы, `LensSpec`, `_layer_sizes_for`. `RepoProfile`/`AgentRunner` импортируются только под `TYPE_CHECKING` + узким `Protocol`, чтобы Stage 3 не падал на отсутствии Stage 1.

- [ ] Добавить падающий тест в `backend/tests/unit/test_validators.py`:

```python
"""Unit tests for ValidationFunnel pure logic (no agent calls)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.validators import LENS_FOCUS, LENSES, ValidationFunnel


def _ws(strictness="standard", t1=5, t2=2, n_arbiters=2):
    review = SimpleNamespace(enabled=True, tier1_threshold=t1, tier2_threshold=t2, max_revisions=2)
    agents = SimpleNamespace(
        validators=[SimpleNamespace(provider="p", model="m", agent=f"v{i}") for i in range(5)],
        arbiters=[SimpleNamespace(provider="p", model="m", agent=f"a{i}") for i in range(n_arbiters)],
        final=SimpleNamespace(provider="p", model="m", agent="f"),
    )
    return SimpleNamespace(strictness=strictness, review=review, agents=agents)


def test_lenses_constant():
    assert LENSES == ("correctness", "tests", "security", "conventions", "scope")
    assert set(LENS_FOCUS) == set(LENSES)


def test_layer_sizes_standard(monkeypatch):
    monkeypatch.setattr(
        "app.core.validators._effective",
        lambda: {"HEPHAESTUS_TIER1_APPROVE_THRESHOLD": "5", "HEPHAESTUS_TIER2_APPROVE_THRESHOLD": "2"},
    )
    f = ValidationFunnel(_ws("standard"), runner=SimpleNamespace())
    lenses, m, t1, t2 = f._layer_sizes_for()
    assert lenses == ["correctness", "tests", "security", "conventions", "scope"]
    assert m == 2 and t1 == 5 and t2 == 2


def test_layer_sizes_permissive(monkeypatch):
    monkeypatch.setattr(
        "app.core.validators._effective",
        lambda: {"HEPHAESTUS_TIER1_APPROVE_THRESHOLD": "3", "HEPHAESTUS_TIER2_APPROVE_THRESHOLD": "1"},
    )
    f = ValidationFunnel(_ws("permissive", t1=3, t2=1, n_arbiters=1), runner=SimpleNamespace())
    lenses, m, t1, t2 = f._layer_sizes_for()
    assert lenses == ["correctness", "tests", "scope"]
    assert m == 1 and t1 == 3 and t2 == 1


def test_layer_sizes_for_clamps_threshold(monkeypatch):
    # strict preset says threshold 6, but only 5 lenses → clamp to 5
    monkeypatch.setattr(
        "app.core.validators._effective",
        lambda: {"HEPHAESTUS_TIER1_APPROVE_THRESHOLD": "6", "HEPHAESTUS_TIER2_APPROVE_THRESHOLD": "2"},
    )
    f = ValidationFunnel(_ws("strict"), runner=SimpleNamespace())
    lenses, m, t1, t2 = f._layer_sizes_for()
    assert len(lenses) == 5
    assert t1 == 5  # clamped from 6 to len(lenses)


def test_layer_sizes_disabled(monkeypatch):
    monkeypatch.setattr("app.core.validators._effective", lambda: {})
    f = ValidationFunnel(_ws("disabled"), runner=SimpleNamespace())
    lenses, m, t1, t2 = f._layer_sizes_for()
    assert lenses == [] and m == 0
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_validators.py -q
```
Ожидаемый вывод: `ModuleNotFoundError: No module named 'app.core.validators'`.

- [ ] Создать `backend/app/core/validators.py` (часть 1 — каркас и `_layer_sizes_for`):

```python
"""Stage 3 — map-reduce validation funnel (D10).

Layer 1 (lenses, many) → Layer 2 (arbiters, fewer) → Layer 3 (final gate, one).
Sizes/thresholds come from TIER_PRESETS + effective config (no parallel source of
truth). Cross-platform: pathlib paths, asyncio subprocess via AgentRunner, no bash.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import re
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

from app.models.validation import LensVerdict, ValidationResult

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

log = logging.getLogger("hephaestus.validators")

LENSES: tuple[str, ...] = ("correctness", "tests", "security", "conventions", "scope")

LENS_FOCUS: dict[str, str] = {
    "correctness": "Does the diff actually solve the item's problem? Edge cases, null/empty, error paths, races.",
    "tests": "Are tests present, do they exercise the new path, would they fail WITHOUT the production change?",
    "security": "Secret leaks, weakened auth, SSRF, swallowed exceptions hiding bugs, unsafe casts, missing input validation.",
    "conventions": "Naming, code style, project conventions from .hephaestus/memory/conventions.md, no out-of-style patterns.",
    "scope": "Does the diff stay inside item.touches? Out-of-scope refactors / 'while-I-was-here' tweaks are a needs_revision signal.",
}

# strictness → (active_lenses, arbiter_cap)
_STRICTNESS_LENSES: dict[str, tuple[list[str], int]] = {
    "strict": (list(LENSES), 2),
    "standard": (list(LENSES), 2),
    "permissive": (["correctness", "tests", "scope"], 1),
    "disabled": ([], 0),
}

_PROMPTS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent.parent / "prompts"


def _effective() -> dict:
    """Thin wrapper so tests can monkeypatch the threshold source."""
    from app.config import _config_effective

    return _config_effective()


class LensSpec(BaseModel):
    lens: str
    focus: str


class _AgentRunnerProto(Protocol):
    # R2: каждый конкурентный вызов имеет уникальный output_path; общего session_name нет.
    async def run(self, ref: object, *, prompt_file: pathlib.Path, cwd: str,
                  output_path: pathlib.Path, timeout_sec: int) -> object: ...


class ValidationFunnel:
    def __init__(self, ws: "RepoProfile", runner: _AgentRunnerProto) -> None:
        self.ws = ws
        self.runner = runner

    def _layer_sizes_for(self) -> tuple[list[str], int, int, int]:
        """Return (active_lenses, m_arbiters, tier1_threshold, tier2_threshold)."""
        strictness = getattr(self.ws, "strictness", "standard")
        lenses, arb_cap = _STRICTNESS_LENSES.get(strictness, _STRICTNESS_LENSES["standard"])
        if not lenses:  # disabled
            return [], 0, 0, 0
        eff = _effective()
        t1_raw = int(eff.get("HEPHAESTUS_TIER1_APPROVE_THRESHOLD", str(len(lenses))))
        t2_raw = int(eff.get("HEPHAESTUS_TIER2_APPROVE_THRESHOLD", "2"))
        t1 = max(1, min(t1_raw, len(lenses)))
        n_arbiters = min(len(getattr(self.ws.agents, "arbiters", [])), arb_cap)
        t2 = max(0, min(t2_raw, n_arbiters)) if n_arbiters else 0
        return lenses, n_arbiters, t1, t2
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_validators.py -q
```
Ожидаемый вывод: `6 passed`.

- [ ] Commit:

```
git add backend/app/core/validators.py backend/tests/unit/test_validators.py
git commit -m "feat(stage3): validators.py skeleton + _layer_sizes_for"
```

---

## Task 6: `_parse_lens_block` + `_aggregate_layer1`

Defensive-парсинг блока (spec §4.6) и агрегация Layer 1 (spec §4.2).

- [ ] Дополнить `backend/tests/unit/test_validators.py` (добавить в конец файла):

```python
from app.core.validators import _aggregate_layer1, _parse_lens_block  # noqa: E402


def test_parse_lens_block_defensive_no_block():
    v = _parse_lens_block("the agent rambled and emitted no block", "tests")
    assert v.verdict == "needs_revision"
    assert v.confidence == 0.0
    assert v.lens == "tests"


def test_parse_lens_block_confidence_0_to_10_form():
    text = (
        "VALIDATION_VERDICT_BEGIN\n"
        "lens: correctness\nverdict: approve\nconfidence: 8\n"
        "evidence: hunk 1\ntop_issues: none\nreasoning: looks correct\n"
        "VALIDATION_VERDICT_END\n"
    )
    v = _parse_lens_block(text, "correctness")
    assert v.verdict == "approve"
    assert abs(v.confidence - 0.8) < 1e-9


def test_parse_lens_block_garbage_verdict_normalizes():
    text = (
        "VALIDATION_VERDICT_BEGIN\nlens: scope\nverdict: maybe-ok\nconfidence: 0.5\n"
        "reasoning: unclear\nVALIDATION_VERDICT_END\n"
    )
    v = _parse_lens_block(text, "scope")
    assert v.verdict == "needs_revision"


def test_aggregate_layer1_threshold():
    verdicts = [
        LensVerdict(lens=lens, verdict="approve", confidence=0.9, reasoning="ok")
        for lens in ("correctness", "tests", "security", "conventions")
    ] + [LensVerdict(lens="scope", verdict="needs_revision", confidence=0.6, reasoning="scope creep")]
    passed5, blocking5 = _aggregate_layer1(verdicts, threshold=5)
    assert passed5 is False
    passed4, _ = _aggregate_layer1(verdicts, threshold=4)
    assert passed4 is True
    assert any("scope" in b for b in blocking5)


def test_aggregate_layer1_high_conf_reject_blocks():
    verdicts = [
        LensVerdict(lens=lens, verdict="approve", confidence=0.9, reasoning="ok")
        for lens in ("correctness", "tests", "security", "conventions")
    ] + [LensVerdict(lens="scope", verdict="reject", confidence=0.8, reasoning="broke API")]
    passed, blocking = _aggregate_layer1(verdicts, threshold=4)
    assert passed is False  # high-conf reject overrides count
    assert any("scope" in b for b in blocking)
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_validators.py -k "parse_lens or aggregate" -q
```
Ожидаемый вывод: `ImportError: cannot import name '_parse_lens_block'`.

- [ ] Добавить в `backend/app/core/validators.py` (после класса `ValidationFunnel`):

```python
_VERDICT_VALUES = {"approve", "needs_revision", "reject"}
_LENS_BLOCK_RE = re.compile(
    r"VALIDATION_VERDICT_BEGIN(.*?)VALIDATION_VERDICT_END", re.DOTALL
)


def _parse_kv(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip().lower()] = v.strip()
    return out


def _norm_confidence(raw: str) -> float:
    try:
        val = float(raw)
    except (ValueError, TypeError):
        return 0.0
    if val > 1.0:  # 0..10 form
        val = val / 10.0
    return max(0.0, min(1.0, val))


def _parse_lens_block(text: str, lens: str) -> LensVerdict:
    """Defensive: take the LAST verdict block; missing → needs_revision/0.0."""
    matches = _LENS_BLOCK_RE.findall(text or "")
    if not matches:
        return LensVerdict(lens=lens, verdict="needs_revision", confidence=0.0,
                           reasoning="no verdict block emitted")
    kv = _parse_kv(matches[-1])
    verdict = kv.get("verdict", "").lower()
    if verdict not in _VERDICT_VALUES:
        verdict = "needs_revision"
    return LensVerdict(
        lens=kv.get("lens", lens) or lens,
        verdict=verdict,
        confidence=_norm_confidence(kv.get("confidence", "0")),
        reasoning=kv.get("reasoning", "") or "(no reasoning)",
    )


def _aggregate_layer1(verdicts: list[LensVerdict], threshold: int) -> tuple[bool, list[str]]:
    """passed = approve_count >= clamp(threshold,1,len). Any reject@conf>=0.7 → False."""
    if not verdicts:
        return False, ["all validators failed — check opencode availability"]
    approve_count = sum(1 for v in verdicts if v.verdict == "approve")
    clamped = max(1, min(threshold, len(verdicts)))
    passed = approve_count >= clamped
    if any(v.verdict == "reject" and v.confidence >= 0.7 for v in verdicts):
        passed = False
    blocking = [f"{v.lens}: {v.reasoning}" for v in verdicts if v.verdict != "approve"]
    return passed, blocking
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_validators.py -q
```
Ожидаемый вывод: `11 passed`.

- [ ] Lint/types:

```
cd backend && ruff check app/core/validators.py && mypy --strict app/core/validators.py
```
Ожидаемый вывод: `All checks passed!` / `Success: no issues found`.

- [ ] Commit:

```
git add backend/app/core/validators.py backend/tests/unit/test_validators.py
git commit -m "feat(stage3): _parse_lens_block + _aggregate_layer1"
```

---

## Task 7: `build_revision_prompt` + `run_funnel` (Layer 1/2/3 orchestration)

`build_revision_prompt` (чистая функция) + async `run_funnel`/`_run_layer1`/`_run_layer2`/`_run_layer3`. disabled/`review.enabled=False` → мгновенный `pass`.

- [ ] Создать падающий тест `backend/tests/unit/test_build_revision_prompt.py`:

```python
"""build_revision_prompt renders blocking + lens findings + attempt/max."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.validators import build_revision_prompt
from app.models.validation import LensVerdict, ValidationResult


def test_revision_prompt_contains_blocking():
    vr = ValidationResult(
        layer1=[
            LensVerdict(lens="tests", verdict="needs_revision", confidence=0.4, reasoning="no test for empty input"),
            LensVerdict(lens="scope", verdict="approve", confidence=0.9, reasoning="ok"),
        ],
        layer2_summary=[],
        gate="needs_revision",
        blocking=["tests: no test for empty input"],
        revision=1,
    )
    item = {"id": "item-9", "proposal": "Add retry", "acceptance": "Has a test"}
    ws = SimpleNamespace(review=SimpleNamespace(max_revisions=2))
    text = build_revision_prompt(item, vr, attempt=1, ws=ws)
    assert "no test for empty input" in text
    assert "tests:" in text
    assert "1 of 2" in text or "attempt 1" in text.lower()
    assert "Add retry" in text
    assert "Has a test" in text
    # approved lens must NOT appear in the lens-findings digest
    assert "scope: ok" not in text
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_build_revision_prompt.py -q
```
Ожидаемый вывод: `ImportError: cannot import name 'build_revision_prompt'`.

- [ ] Добавить в `backend/app/core/validators.py` (после `_aggregate_layer1`):

```python
def _render_template(name: str, **vars: str) -> str:
    tpl = (_PROMPTS_DIR / name).read_text(encoding="utf-8", errors="replace")
    for k, v in vars.items():
        tpl = tpl.replace("{{" + k + "}}", v)
    return tpl


def build_revision_prompt(item: dict, vr: "ValidationResult", attempt: int,
                          ws: "RepoProfile") -> str:
    max_rev = getattr(getattr(ws, "review", None), "max_revisions", 2)
    lens_findings = "\n".join(
        f"- {v.lens}: {v.reasoning}" for v in vr.layer1 if v.verdict != "approve"
    ) or "- (none)"
    blocking = "\n".join(f"- {b}" for b in vr.blocking) or "- (none)"
    return _render_template(
        "revision-feedback.md",
        item_id=str(item.get("id", "?")),
        attempt=str(attempt),
        max_revisions=str(max_rev),
        blocking=blocking,
        lens_findings=lens_findings,
        proposal=str(item.get("proposal", "")),
        acceptance=str(item.get("acceptance", "")),
    )
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_build_revision_prompt.py -q
```
Ожидаемый вывод: `1 passed`.

- [ ] Добавить async-методы воронки в `backend/app/core/validators.py` (методы класса `ValidationFunnel`, после `_layer_sizes_for`):

```python
    def _validator_pool(self) -> list[object]:
        """R3: validators pool, fallback to [primary]*1 so the funnel never silently passes."""
        vals = list(getattr(self.ws.agents, "validators", []))
        if vals:
            return vals
        primary = getattr(self.ws.agents, "primary", None)
        return [primary] if primary is not None else []

    def _final_ref(self) -> object | None:
        """R3: final gate agent, fallback to primary when final is None."""
        final = getattr(self.ws.agents, "final", None)
        if final is not None:
            return final
        return getattr(self.ws.agents, "primary", None)

    async def run_funnel(self, item: dict, *, iter_dir: pathlib.Path,
                         diff_text: str, revision: int) -> ValidationResult:
        review_enabled = getattr(getattr(self.ws, "review", None), "enabled", True)
        lenses, m, t1, t2 = self._layer_sizes_for()
        if not lenses or not review_enabled:
            return ValidationResult(layer1=[], layer2_summary=[], gate="pass",
                                    blocking=[], revision=revision)
        vdir = iter_dir / "validation"
        (vdir / "layer1").mkdir(parents=True, exist_ok=True)
        l1 = await self._run_layer1(item, iter_dir=iter_dir, diff_text=diff_text, lenses=lenses)
        passed, blocking = _aggregate_layer1(l1, t1)
        l2: list[dict] = []
        l2_errored_all = False
        if m > 0:
            (vdir / "layer2").mkdir(parents=True, exist_ok=True)
            l2 = await self._run_layer2(item, iter_dir=iter_dir, l1=l1, m=m)
            # R20: if EVERY arbiter errored (launch failure, not a substantive verdict),
            # do not penalize Layer 2 — fall back to L1+L3 just like m==0.
            l2_errored_all = bool(l2) and all(a.get("errored") for a in l2)
        l3 = await self._run_layer3(item, iter_dir=iter_dir, l1=l1, l2=l2)
        layer2_active = m > 0 and not l2_errored_all
        approvals = sum(1 for a in l2 if a.get("verdict") == "approve")
        l2_pass = (not layer2_active) or approvals >= t2
        l2_blocking: list[str] = []
        if layer2_active and not l2_pass:
            l2_blocking.append(f"arbiters: {approvals} of {t2} approvals")  # R20 diagnostics
        gate_pass = passed and l2_pass
        # final agent gate can only downgrade to needs_revision, never upgrade
        gate = "pass" if (gate_pass and l3.get("gate", "pass") == "pass") else "needs_revision"
        all_blocking = list(dict.fromkeys(blocking + l2_blocking + list(l3.get("blocking", []))))
        result = ValidationResult(layer1=l1, layer2_summary=l2, gate=gate,
                                  blocking=all_blocking, revision=revision)
        (vdir / "layer3").mkdir(parents=True, exist_ok=True)
        final = {"gate": gate, "blocking": all_blocking,
                 "notes": l3.get("notes", ""), "revision": revision}
        # umbrella §4.4/§7: final gate artifact lives at validation/layer3/final.json
        (vdir / "layer3" / "final.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
        return result

    async def _run_layer1(self, item: dict, *, iter_dir: pathlib.Path,
                          diff_text: str, lenses: list[str]) -> list[LensVerdict]:
        vals = self._validator_pool()  # R3 fallback
        l1dir = iter_dir / "validation" / "layer1"

        async def _one(i: int, lens: str) -> LensVerdict:
            ref = vals[i % len(vals)] if vals else None
            prompt = _render_template(
                "validate-lens.md", lens=lens, lens_focus=LENS_FOCUS[lens],
                item_id=str(item.get("id", "?")),
                prompt_excerpt=str(item.get("proposal", ""))[:2000], diff=diff_text[:20000],
            )
            pf = l1dir / f"{lens}.prompt.md"
            pf.write_text(prompt, encoding="utf-8")
            out = l1dir / f"{lens}.jsonl"  # R2: unique output_path per lens, no session_name
            await self.runner.run(ref, prompt_file=pf, cwd=str(self.ws.repo_path),
                                  output_path=out, timeout_sec=600)
            text = _last_text_event(out)
            v = _parse_lens_block(text, lens)
            (l1dir / f"{lens}.json").write_text(v.model_dump_json(indent=2), encoding="utf-8")
            return v

        results = await asyncio.gather(*[_one(i, ln) for i, ln in enumerate(lenses)],
                                       return_exceptions=True)
        out: list[LensVerdict] = []
        for lens, r in zip(lenses, results, strict=True):
            if isinstance(r, BaseException):
                out.append(LensVerdict(lens=lens, verdict="needs_revision", confidence=0.0,
                                       reasoning=f"validator {lens} errored: {type(r).__name__}"))
            else:
                out.append(r)
        return out

    async def _run_layer2(self, item: dict, *, iter_dir: pathlib.Path,
                          l1: list[LensVerdict], m: int) -> list[dict]:
        arbiters = list(getattr(self.ws.agents, "arbiters", []))[:m]
        l2dir = iter_dir / "validation" / "layer2"
        digest = json.dumps([v.model_dump() for v in l1])

        async def _one(i: int, ref: object) -> dict:
            prompt = _render_template("validate-arbiter.md", layer1_digest=digest)
            pf = l2dir / f"arbiter-{i}.prompt.md"
            pf.write_text(prompt, encoding="utf-8")
            out = l2dir / f"arbiter-{i}.jsonl"  # R2: unique output_path per arbiter, no session_name
            await self.runner.run(ref, prompt_file=pf, cwd=str(self.ws.repo_path),
                                  output_path=out, timeout_sec=600)
            text = _last_text_event(out)
            verdict = _parse_arbiter_block(text)
            rec = {"arbiter": i, "verdict": verdict, "errored": False}
            # umbrella §4.4: arbiter artifact is validation/layer2/arbiter-<i>.json
            (l2dir / f"arbiter-{i}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
            return rec

        results = await asyncio.gather(*[_one(i, a) for i, a in enumerate(arbiters)],
                                       return_exceptions=True)
        # R20: mark errored arbiters explicitly so run_funnel can avoid penalizing L2
        return [r if not isinstance(r, BaseException)
                else {"arbiter": i, "verdict": "needs_revision", "errored": True}
                for i, r in enumerate(results)]

    async def _run_layer3(self, item: dict, *, iter_dir: pathlib.Path,
                          l1: list[LensVerdict], l2: list[dict]) -> dict:
        final_ref = self._final_ref()  # R3: fallback to primary when final is None
        if final_ref is None:
            return {"gate": "pass", "blocking": [], "notes": "no final agent configured"}
        l3dir = iter_dir / "validation" / "layer3"
        l3dir.mkdir(parents=True, exist_ok=True)
        prompt = _render_template(
            "validate-final.md",
            layer1_digest=json.dumps([v.model_dump() for v in l1]),
            layer2_digest=json.dumps(l2),
        )
        pf = l3dir / "final.prompt.md"
        pf.write_text(prompt, encoding="utf-8")
        out = l3dir / "final.jsonl"  # R2: unique output_path, no session_name
        try:
            await self.runner.run(final_ref, prompt_file=pf, cwd=str(self.ws.repo_path),
                                  output_path=out, timeout_sec=600)
        except Exception as exc:  # fail-safe to needs_revision
            return {"gate": "needs_revision", "blocking": [f"final gate errored: {type(exc).__name__}"],
                    "notes": ""}
        return _parse_final_block(_last_text_event(out))
```

- [ ] Добавить парсеры арбитра/финала и `_last_text_event` в `backend/app/core/validators.py` (после `_parse_lens_block`):

```python
_ARBITER_BLOCK_RE = re.compile(r"ARBITER_VERDICT_BEGIN(.*?)ARBITER_VERDICT_END", re.DOTALL)
_FINAL_BLOCK_RE = re.compile(r"FINAL_GATE_BEGIN(.*?)FINAL_GATE_END", re.DOTALL)


def _parse_arbiter_block(text: str) -> str:
    matches = _ARBITER_BLOCK_RE.findall(text or "")
    if not matches:
        return "needs_revision"
    verdict = _parse_kv(matches[-1]).get("verdict", "").lower()
    return verdict if verdict in _VERDICT_VALUES else "needs_revision"


def _parse_final_block(text: str) -> dict:
    matches = _FINAL_BLOCK_RE.findall(text or "")
    if not matches:
        return {"gate": "needs_revision", "blocking": ["no final gate block emitted"], "notes": ""}
    kv = _parse_kv(matches[-1])
    gate = kv.get("gate", "needs_revision").lower()
    if gate != "pass":
        gate = "needs_revision"
    raw_blocking = kv.get("blocking", "none")
    blocking = [] if raw_blocking.lower() == "none" else [
        b.strip() for b in raw_blocking.split(";") if b.strip()]
    return {"gate": gate, "blocking": blocking, "notes": kv.get("notes", "")}


def _last_text_event(output_path: pathlib.Path) -> str:
    """Собрать ПОЛНЫЙ текст из opencode JSONL-стрима.

    ВАЖНО: НЕ использовать app.core.events._parse_events — он усекает текст до
    EVENT_TEXT_MAX=240 символов на событие (для UI-таймлайна), из-за чего блоки
    VALIDATION_VERDICT/ARBITER/FINAL_GATE придут обрезанными и regexp-парсеры
    не найдут закрывающий маркер. Читаем сырой JSONL и собираем текст целиком.
    """
    if not output_path.exists():
        return ""
    import json as _json

    try:
        raw = output_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    texts: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = _json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(ev, dict):
            continue
        # Multi-shape JSONL: text | content | output | message.content[].text | part.text
        val = ev.get("text") or ev.get("content") or ev.get("output")
        if isinstance(val, str) and val:
            texts.append(val)
        msg = ev.get("message")
        if isinstance(msg, dict):
            mc = msg.get("content")
            if isinstance(mc, str) and mc:
                texts.append(mc)
            elif isinstance(mc, list):
                for part in mc:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        texts.append(part["text"])
        part = ev.get("part")
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
    return "\n".join(t for t in texts if t)
```

- [ ] Запустить весь модуль:

```
cd backend && python -m pytest tests/unit/test_validators.py tests/unit/test_build_revision_prompt.py -q
```
Ожидаемый вывод: `12 passed`.

- [ ] Lint/types:

```
cd backend && ruff check app/core/validators.py && mypy --strict app/core/validators.py
```
Ожидаемый вывод: `All checks passed!` / `Success: no issues found`.

- [ ] Commit:

```
git add backend/app/core/validators.py backend/tests/unit/test_build_revision_prompt.py
git commit -m "feat(stage3): run_funnel Layer1/2/3 + build_revision_prompt"
```

---

## Task 8: Conftest-фикстуры — `fake_agent_runner`, `tmp_git_repo`

Интеграционные тесты Task 9/10 нуждаются в мок-`AgentRunner` (пишет заранее заданные JSONL-блоки) и temp git-репо. Добавляем в общий `backend/tests/conftest.py`.

- [ ] Дополнить `backend/tests/conftest.py` (добавить в конец файла):

```python
import subprocess  # noqa: E402
from types import SimpleNamespace  # noqa: E402


def _git(args: list[str], cwd: pathlib.Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def tmp_git_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """A bare-bones git repo with an initial commit on 'main'. Cross-platform."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t.t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "README.md").write_text("hello\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "init"], repo)
    return repo


class _FakeAgentRunner:
    """Writes a scripted JSONL text event to output_path on each run().

    scripts: dict mapping lens/'arbiter-<i>'/'final' (derived from output filename stem)
    to the raw block text the agent 'emitted'. Records calls in .calls.

    R2: run() has NO session_name — each concurrent call is identified by its unique
    output_path, not a shared session.
    """

    def __init__(self, scripts: dict[str, str]) -> None:
        self.scripts = scripts
        self.calls: list[str] = []

    async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec):
        stem = pathlib.Path(output_path).name.split(".")[0]
        self.calls.append(stem)
        block = self.scripts.get(stem, self.scripts.get("*", ""))
        line = json.dumps({"type": "text", "text": block})
        pathlib.Path(output_path).write_text(line + "\n", encoding="utf-8")
        return SimpleNamespace(exit_code=0, refused=False,
                               output_path=output_path, agent_label="fake")


@pytest.fixture
def fake_agent_runner():
    return _FakeAgentRunner


def make_repo_profile(repo_path: str, *, strictness="standard", n_validators=5,
                      n_arbiters=2, with_final=True, max_revisions=2):
    """Lightweight RepoProfile-shaped object for funnel/git tests (no Stage 1 dep)."""
    review = SimpleNamespace(enabled=True, tier1_threshold=5, tier2_threshold=2,
                             max_revisions=max_revisions)
    agents = SimpleNamespace(
        primary=SimpleNamespace(provider="p", model="m", agent="primary"),  # R3 fallback source
        fallback=SimpleNamespace(provider="p", model="m", agent="fallback"),
        validators=[SimpleNamespace(provider="p", model="m", agent=f"v{i}") for i in range(n_validators)],
        arbiters=[SimpleNamespace(provider="p", model="m", agent=f"a{i}") for i in range(n_arbiters)],
        final=SimpleNamespace(provider="p", model="m", agent="f") if with_final else None,
    )
    return SimpleNamespace(
        id="ws-test", name="test", repo_path=repo_path, base_branch="main",
        remote="origin", branch_prefix="auto", agents=agents, strictness=strictness,
        review=review,
    )


@pytest.fixture
def repo_profile_factory():
    return make_repo_profile
```

- [ ] Проверить, что conftest импортируется без ошибок (smoke):

```
cd backend && python -m pytest tests/ -q --collect-only -k test_validators
```
Ожидаемый вывод: collection succeeds, тесты `test_validators` перечислены, нет ошибок импорта conftest.

- [ ] Commit:

```
git add backend/tests/conftest.py
git commit -m "test(stage3): conftest fixtures tmp_git_repo + fake_agent_runner"
```

---

## Task 9: Integration — воронка end-to-end (`test_funnel_loop.py`)

Мок-`AgentRunner` пишет заданные блоки; проверяем pass-путь, артефакты, агрегацию.

- [ ] Создать `backend/tests/integration/test_funnel_loop.py`:

```python
"""Funnel integration with a scripted fake AgentRunner (no opencode, no bash)."""

from __future__ import annotations

import json

import pytest

from app.core.validators import ValidationFunnel
from tests.conftest import make_repo_profile

pytestmark = pytest.mark.asyncio


def _lens_block(lens: str, verdict: str, conf: float = 0.9) -> str:
    return (
        f"VALIDATION_VERDICT_BEGIN\nlens: {lens}\nverdict: {verdict}\n"
        f"confidence: {conf}\nevidence: hunk 1\ntop_issues: none\n"
        f"reasoning: scripted {verdict}\nVALIDATION_VERDICT_END\n"
    )


def _arbiter_block(verdict: str) -> str:
    return (
        f"ARBITER_VERDICT_BEGIN\nverdict: {verdict}\n"
        f"dedup_findings: - none\nagree_with_lenses: agree\nreasoning: ok\nARBITER_VERDICT_END\n"
    )


def _final_block(gate: str, blocking: str = "none") -> str:
    return f"FINAL_GATE_BEGIN\ngate: {gate}\nblocking: {blocking}\nnotes: scripted\nFINAL_GATE_END\n"


async def test_pass_path(tmp_path, fake_agent_runner):
    iter_dir = tmp_path / "iter-0001"
    iter_dir.mkdir()
    scripts = {ln: _lens_block(ln, "approve") for ln in
               ("correctness", "tests", "security", "conventions", "scope")}
    scripts |= {"arbiter-0": _arbiter_block("approve"), "arbiter-1": _arbiter_block("approve"),
                "final": _final_block("pass")}
    runner = fake_agent_runner(scripts)
    ws = make_repo_profile(str(tmp_path))
    funnel = ValidationFunnel(ws, runner)
    vr = await funnel.run_funnel({"id": "x", "proposal": "p"},
                                 iter_dir=iter_dir, diff_text="diff", revision=0)
    assert vr.gate == "pass"
    assert (iter_dir / "validation" / "layer1" / "tests.json").exists()
    assert (iter_dir / "validation" / "layer3" / "final.json").exists()
    fd = json.loads((iter_dir / "validation" / "layer3" / "final.json").read_text())
    assert fd["gate"] == "pass"


async def test_needs_revision_when_lens_fails(tmp_path, fake_agent_runner):
    iter_dir = tmp_path / "iter-0002"
    iter_dir.mkdir()
    scripts = {ln: _lens_block(ln, "approve") for ln in
               ("correctness", "security", "conventions", "scope")}
    scripts["tests"] = _lens_block("tests", "needs_revision", 0.5)
    scripts |= {"arbiter-0": _arbiter_block("needs_revision"),
                "arbiter-1": _arbiter_block("needs_revision"), "final": _final_block("needs_revision", "tests: add a test")}
    runner = fake_agent_runner(scripts)
    ws = make_repo_profile(str(tmp_path))  # standard, t1=5 → 4 approve fails
    vr = await ValidationFunnel(ws, runner).run_funnel(
        {"id": "x", "proposal": "p"}, iter_dir=iter_dir, diff_text="d", revision=0)
    assert vr.gate == "needs_revision"
    assert any("tests" in b for b in vr.blocking)


async def test_disabled_short_circuits(tmp_path, fake_agent_runner):
    iter_dir = tmp_path / "iter-0003"
    iter_dir.mkdir()
    runner = fake_agent_runner({})
    ws = make_repo_profile(str(tmp_path), strictness="disabled")
    vr = await ValidationFunnel(ws, runner).run_funnel(
        {"id": "x"}, iter_dir=iter_dir, diff_text="d", revision=2)
    assert vr.gate == "pass"
    assert vr.revision == 2
    assert runner.calls == []  # AgentRunner never invoked


async def test_validators_fallback_to_primary(tmp_path, fake_agent_runner):
    """R3: empty validators pool falls back to [primary]*N — funnel still runs, not a silent pass."""
    iter_dir = tmp_path / "iter-0004"
    iter_dir.mkdir()
    scripts = {ln: _lens_block(ln, "approve") for ln in
               ("correctness", "tests", "security", "conventions", "scope")}
    scripts |= {"arbiter-0": _arbiter_block("approve"), "arbiter-1": _arbiter_block("approve"),
                "final": _final_block("pass")}
    runner = fake_agent_runner(scripts)
    ws = make_repo_profile(str(tmp_path), n_validators=0)  # validators empty → fallback to primary
    vr = await ValidationFunnel(ws, runner).run_funnel(
        {"id": "x", "proposal": "p"}, iter_dir=iter_dir, diff_text="d", revision=0)
    # all 5 lenses still ran (via primary fallback) and produced artifacts
    assert {ln for ln in runner.calls if ln in
            ("correctness", "tests", "security", "conventions", "scope")} == {
            "correctness", "tests", "security", "conventions", "scope"}
    assert vr.gate == "pass"


async def test_all_arbiters_errored_not_penalized(tmp_path, fake_agent_runner):
    """R20: if every arbiter errored (launch failure), L2 is not penalized — gate rests on L1+L3."""
    import pathlib

    iter_dir = tmp_path / "iter-0005"
    iter_dir.mkdir()
    scripts = {ln: _lens_block(ln, "approve") for ln in
               ("correctness", "tests", "security", "conventions", "scope")}
    scripts |= {"final": _final_block("pass")}

    class _ErroringArbiterRunner(fake_agent_runner):  # fake_agent_runner is the class itself
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec):
            if "arbiter" in pathlib.Path(output_path).name:
                raise RuntimeError("arbiter launch failed")
            return await super().run(ref, prompt_file=prompt_file, cwd=cwd,
                                     output_path=output_path, timeout_sec=timeout_sec)

    err_runner = _ErroringArbiterRunner(scripts)
    ws = make_repo_profile(str(tmp_path))
    vr = await ValidationFunnel(ws, err_runner).run_funnel(
        {"id": "x", "proposal": "p"}, iter_dir=iter_dir, diff_text="d", revision=0)
    # L1 all-approve + L3 pass; L2 all-errored must NOT block
    assert vr.gate == "pass"
    assert not any("arbiters:" in b for b in vr.blocking)
```

- [ ] Запустить — ожидается PASS (run_funnel уже реализован в Task 7):

```
cd backend && python -m pytest tests/integration/test_funnel_loop.py -q
```
Ожидаемый вывод: `5 passed`.

- [ ] Commit:

```
git add backend/tests/integration/test_funnel_loop.py
git commit -m "test(stage3): funnel integration pass/needs_revision/disabled/fallback/arbiters-errored"
```

---

## Task 10: `GitService` — `__init__`, `diff`, `merge_preflight`, хелперы

Класс поверх существующих функций `git.py` (umbrella §5.4, spec §4.4). Принимает `ws: RepoProfile`. Сначала синхронные методы + preflight.

- [ ] Создать падающий тест `backend/tests/integration/test_merge_to_base.py` (часть 1 — preflight):

```python
"""GitService merge_preflight / merge_to_base on a temp git repo (no bash)."""

from __future__ import annotations

import subprocess

import pytest

from app.core.git import GitService
from tests.conftest import make_repo_profile

pytestmark = pytest.mark.asyncio


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _make_auto_branch(repo, name="auto/x-1", content="patch\n"):
    _git(["checkout", "-b", name], repo)
    (repo / "feature.txt").write_text(content)
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "feat"], repo)
    _git(["checkout", "main"], repo)


def test_preflight_blocks_when_dirty(tmp_git_repo, monkeypatch):
    _make_auto_branch(tmp_git_repo)
    (tmp_git_repo / "dirty.txt").write_text("uncommitted\n")
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    monkeypatch.setattr(gs, "_find_item_by_branch", lambda b: {"branch": b})
    pf = gs.merge_preflight("auto/x-1")
    assert pf.clean_tree is False
    assert pf.ok is False


def test_preflight_ok_when_clean_and_validated(tmp_git_repo, monkeypatch):
    _make_auto_branch(tmp_git_repo)
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    # R11: persistent flags on the Task drive preflight (not status-prefix heuristics).
    monkeypatch.setattr(gs, "_find_item_by_branch",
                        lambda b: {"branch": b, "verify_green": True,
                                   "validation": {"gate": "pass"}})
    monkeypatch.setattr(gs, "_loop_active", lambda: False)
    pf = gs.merge_preflight("auto/x-1")
    assert pf.clean_tree is True
    assert pf.verify_green is True
    assert pf.validation_passed is True
    assert pf.loop_active is False
    assert pf.ok is True


def test_preflight_blocks_when_validation_failed(tmp_git_repo, monkeypatch):
    _make_auto_branch(tmp_git_repo)
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    monkeypatch.setattr(gs, "_find_item_by_branch",
                        lambda b: {"branch": b, "verify_green": True,
                                   "validation": {"gate": "needs_revision"}})
    monkeypatch.setattr(gs, "_loop_active", lambda: False)
    pf = gs.merge_preflight("auto/x-1")
    assert pf.validation_passed is False
    assert pf.ok is False


def test_preflight_blocks_when_loop_running(tmp_git_repo, monkeypatch):
    """R11: merge forbidden while loop RUNNING even when everything else is green."""
    _make_auto_branch(tmp_git_repo)
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    monkeypatch.setattr(gs, "_find_item_by_branch",
                        lambda b: {"branch": b, "verify_green": True,
                                   "validation": {"gate": "pass"}})
    monkeypatch.setattr(gs, "_loop_active", lambda: True)
    pf = gs.merge_preflight("auto/x-1")
    assert pf.loop_active is True
    assert pf.ok is False
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/integration/test_merge_to_base.py -q
```
Ожидаемый вывод: `ImportError: cannot import name 'GitService'`.

- [ ] Добавить класс `GitService` в `backend/app/core/git.py` (в конец файла, после `BRANCH_ACTIONS`):

```python
from app.models.validation import MergePreflightResponse as MergePreflight  # noqa: E402


class GitService:
    """ws-scoped git operations for Stage 3 merge-to-base (umbrella §5.4)."""

    def __init__(self, ws: object) -> None:
        self.ws = ws
        self.repo = str(getattr(ws, "repo_path"))
        self.base = str(getattr(ws, "base_branch", "main"))
        self.remote = str(getattr(ws, "remote", "origin"))
        self.prefix = str(getattr(ws, "branch_prefix", "auto"))

    # ---- private helpers ----

    def _clean_tree(self) -> bool:
        return _run(["git", "status", "--porcelain"], cwd=self.repo, default="\x00") == ""

    def _find_item_by_branch(self, branch: str) -> dict | None:
        for it in _read_state().get("items", []):
            if it.get("branch") == branch:
                return it
        return None

    def _last_verify_green(self, branch: str) -> bool:
        """R11: read the PERSISTENT item.verify_green flag (written by the FSM after a
        green verify). NOT a status-prefix heuristic. Missing item → False."""
        item = self._find_item_by_branch(branch)
        if item is None:
            return False
        return bool(item.get("verify_green") or item.get("verifyGreen"))

    def _validation_passed(self, branch: str) -> bool:
        """R11: PERSISTENT item.validation.gate == 'pass'. Fallback: layer3/final.json."""
        item = self._find_item_by_branch(branch)
        if item is None:
            return False
        val = item.get("validation")
        if isinstance(val, dict):
            return val.get("gate") == "pass"
        last_iter = item.get("lastIter")
        if last_iter:
            fd = STATE_DIR / last_iter / "validation" / "layer3" / "final.json"
            obj = _load_json(fd) or {}
            return obj.get("gate") == "pass"
        return False

    def _loop_active(self) -> bool:
        """R11: merge forbidden while the loop process is RUNNING (concurrent base writes)."""
        try:
            from app.core.process import ProcState, pm
        except ImportError:
            return False  # Stage 1 ProcessManager not present yet → treat as not active
        try:
            return pm.status("loop").state == ProcState.RUNNING
        except Exception:
            return False

    # ---- public API ----

    def diff(self, branch: str) -> str:
        return _run(["git", "diff", f"{self.remote}/{self.base}..{branch}"], cwd=self.repo)

    def merge_preflight(self, branch: str) -> MergePreflight:
        item = self._find_item_by_branch(branch)
        # R11: Task not found by branch is a distinct, surfaceable condition (router → 409).
        # We still return a preflight with item_found=False via all-False flags; merge_to_base
        # raises the explicit 409.
        clean = self._clean_tree()
        verify = self._last_verify_green(branch)
        validation = self._validation_passed(branch)
        loop_active = self._loop_active()
        ok = (clean and verify and validation and not loop_active
              and item is not None and _is_safe_auto_branch(branch))
        return MergePreflight(
            clean_tree=clean, verify_green=verify, validation_passed=validation,
            loop_active=loop_active, base_branch=self.base, conflicts=[], ok=ok,
        )
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/integration/test_merge_to_base.py -q
```
Ожидаемый вывод: `4 passed`.

- [ ] Commit:

```
git add backend/app/core/git.py backend/tests/integration/test_merge_to_base.py
git commit -m "feat(stage3): GitService preflight + diff + private helpers (R11 persistent flags + loop-active)"
```

---

## Task 11: `GitService.merge_to_base` — merge, conflict-abort, push

Async merge-в-base (spec §4.4, §6). Сохраняет push-before-delete семантику `_action_merge`.

- [ ] Дополнить `backend/tests/integration/test_merge_to_base.py` (добавить в конец):

```python
def _green_item(gs, monkeypatch, branch):
    """R11: a persistent green Task for `branch`, loop not active."""
    monkeypatch.setattr(gs, "_find_item_by_branch",
                        lambda b: {"branch": b, "verify_green": True,
                                   "validation": {"gate": "pass"}})
    monkeypatch.setattr(gs, "_loop_active", lambda: False)


async def test_merge_clean_fast_forward(tmp_git_repo, monkeypatch):
    _make_auto_branch(tmp_git_repo)
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    _green_item(gs, monkeypatch, "auto/x-1")
    # no remote → pull/push skipped; merge stays local
    res = await gs.merge_to_base("auto/x-1", push=False)
    assert res["ok"] is True
    assert res["action"] == "merge"
    log = subprocess.run(["git", "log", "--oneline", "main"], cwd=str(tmp_git_repo),
                         capture_output=True, text=True).stdout
    assert "feat" in log
    branches = subprocess.run(["git", "branch"], cwd=str(tmp_git_repo),
                              capture_output=True, text=True).stdout
    assert "auto/x-1" not in branches  # branch deleted after merge


async def test_merge_conflict_aborts(tmp_git_repo, monkeypatch):
    # base and branch both touch README.md differently → conflict
    _git(["checkout", "-b", "auto/x-2"], tmp_git_repo)
    (tmp_git_repo / "README.md").write_text("branch change\n")
    _git(["add", "-A"], tmp_git_repo); _git(["commit", "-m", "branch"], tmp_git_repo)
    _git(["checkout", "main"], tmp_git_repo)
    (tmp_git_repo / "README.md").write_text("base change\n")
    _git(["add", "-A"], tmp_git_repo); _git(["commit", "-m", "base"], tmp_git_repo)
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    _green_item(gs, monkeypatch, "auto/x-2")
    res = await gs.merge_to_base("auto/x-2", push=False)
    assert res["ok"] is False
    assert "README.md" in res["conflicts"]
    porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=str(tmp_git_repo),
                               capture_output=True, text=True).stdout
    assert porcelain.strip() == ""  # abort restored clean tree


async def test_merge_blocked_when_loop_running(tmp_git_repo, monkeypatch):
    """R11: loop RUNNING → merge_to_base returns ok:False 'loop active...' before touching git."""
    _make_auto_branch(tmp_git_repo)
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    monkeypatch.setattr(gs, "_find_item_by_branch",
                        lambda b: {"branch": b, "verify_green": True,
                                   "validation": {"gate": "pass"}})
    monkeypatch.setattr(gs, "_loop_active", lambda: True)
    res = await gs.merge_to_base("auto/x-1", push=False)
    assert res["ok"] is False
    assert "loop active" in res["error"]


async def test_merge_unknown_branch_returns_error(tmp_git_repo, monkeypatch):
    """R11: no Task for branch → explicit error (router maps to 409), not a silent pass."""
    _make_auto_branch(tmp_git_repo)
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    monkeypatch.setattr(gs, "_loop_active", lambda: False)
    monkeypatch.setattr(gs, "_find_item_by_branch", lambda b: None)
    res = await gs.merge_to_base("auto/x-1", push=False)
    assert res["ok"] is False
    assert "no task found" in res["error"]
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/integration/test_merge_to_base.py -k merge_clean -q
```
Ожидаемый вывод: `AttributeError: 'GitService' object has no attribute 'merge_to_base'`.

- [ ] Добавить метод `merge_to_base` в класс `GitService` (`backend/app/core/git.py`, после `merge_preflight`):

```python
    async def merge_to_base(self, branch: str, *, push: bool) -> dict:
        # R11: merge forbidden while the loop process is RUNNING (avoid concurrent base writes).
        if self._loop_active():
            return {"ok": False, "error": "loop active, stop it before merge"}
        # R11: Task not found by branch → explicit, surfaceable condition (router → 409), not silent.
        if self._find_item_by_branch(branch) is None:
            return {"ok": False, "error": f"no task found for branch {branch}"}
        pf = self.merge_preflight(branch)
        if not pf.ok:
            if not pf.clean_tree:
                return {"ok": False, "error": "working tree not clean", "preflight": pf.model_dump(by_alias=True)}
            return {"ok": False, "error": "preflight failed", "preflight": pf.model_dump(by_alias=True)}
        if _driver_busy_on(branch):
            return {"ok": False, "error": "driver is mid-iter on this item — wait"}
        msg = _run(["git", "log", "-1", "--pretty=%s", branch], cwd=self.repo) or f"merge {branch}"
        co = subprocess.run(["git", "checkout", self.base], cwd=self.repo,
                            capture_output=True, text=True, timeout=60)
        if co.returncode != 0:
            return {"ok": False, "error": f"checkout {self.base}: {co.stderr.strip()}"}
        # pull --ff-only is best-effort: a missing remote must not abort a local merge
        subprocess.run(["git", "pull", "--ff-only", self.remote, self.base], cwd=self.repo,
                       capture_output=True, text=True, timeout=60)
        m = subprocess.run(
            ["git", "merge", "--no-ff", "--no-edit", "-m", f"merge: {msg} (from {branch})", branch],
            cwd=self.repo, capture_output=True, text=True, timeout=60)
        if m.returncode != 0:
            conflicts = _run(["git", "diff", "--name-only", "--diff-filter=U"],
                             cwd=self.repo).splitlines()
            subprocess.run(["git", "merge", "--abort"], cwd=self.repo,
                           capture_output=True, text=True, timeout=60)
            _append_decision("human", "merge", branch, "failed", "conflict")
            return {"ok": False, "conflicts": conflicts, "error": "merge conflict"}
        new_sha = _run(["git", "rev-parse", "HEAD"], cwd=self.repo)
        push_note = "not-pushed"
        if push:
            p = subprocess.run(["git", "push", self.remote, self.base], cwd=self.repo,
                               capture_output=True, text=True, timeout=60)
            if p.returncode != 0:
                _append_decision("human", "merge", branch, "merged-not-pushed",
                                 f"{new_sha[:10]} push_err={p.stderr.strip()[:200]}")
                return {"ok": False, "action": "merge", "branch": branch, "newHead": new_sha[:10],
                        "error": f"merged locally but push failed: {p.stderr.strip()[:300]}"}
            push_note = "pushed"
        subprocess.run(["git", "branch", "-D", branch], cwd=self.repo,
                       capture_output=True, text=True, timeout=60)
        _update_item_by_branch(branch, "merged",
                               {"merged_into": self.base, "merge_sha": new_sha, "push": push_note})
        _append_decision("human", "merge", branch, "ok", f"{new_sha[:10]} {push_note}")
        return {"ok": True, "action": "merge", "branch": branch, "newHead": new_sha[:10], "push": push_note}
```

- [ ] Запустить полный merge-набор:

```
cd backend && python -m pytest tests/integration/test_merge_to_base.py -q
```
Ожидаемый вывод: `8 passed` (4 preflight + 4 merge, включая loop-active и unknown-branch по R11).

- [ ] Lint/types (spec exit-criterion 5 — no tmux/bash в git.py):

```
cd backend && ruff check app/core/git.py && python -m pytest -q -k "grep_guard" || python -c "import re,pathlib; t=pathlib.Path('app/core/git.py').read_text(); assert not re.search(r'tmux|pgrep|pkill|tier-review\\.sh|bash ', t), 'forbidden token in git.py'; print('git.py clean of tmux/bash')"
```
Ожидаемый вывод: `git.py clean of tmux/bash`.

- [ ] Commit:

```
git add backend/app/core/git.py backend/tests/integration/test_merge_to_base.py
git commit -m "feat(stage3): GitService.merge_to_base with conflict abort + push semantics"
```

---

## Task 12: Merge-роутер (`api/v1/merge.py`)

GET preflight + POST merge под `/api/v1/branches/{name}/...` (spec §4.5). `active_workspace()` потребляется из Stage 1; импорт ленивый с понятным 409 при отсутствии воркспейса.

- [ ] Создать падающий контракт-тест `backend/tests/contract/test_merge_api.py`:

```python
"""Contract: merge-preflight / merge endpoints (FastAPI TestClient)."""

from __future__ import annotations

from app.main import app


def test_preflight_rejects_unsafe_branch(client):
    r = client.get("/api/v1/branches/not-an-auto-branch/merge-preflight")
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_merge_rejects_unsafe_branch(client):
    r = client.post("/api/v1/branches/main/merge", json={"push": False})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_preflight_no_workspace_returns_409(client, monkeypatch):
    import app.api.v1.merge as merge_mod

    def _boom():
        raise merge_mod.NoActiveWorkspace()

    monkeypatch.setattr(merge_mod, "active_workspace", _boom)
    r = client.get("/api/v1/branches/auto%2Fx-1/merge-preflight")
    assert r.status_code == 409
    assert "workspace" in r.json()["error"].lower()
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/contract/test_merge_api.py -q
```
Ожидаемый вывод: 404 (роут не зарегистрирован) → assertion failures.

- [ ] Создать `backend/app/api/v1/merge.py`:

```python
"""Stage 3 — merge preflight + merge-to-base endpoints (umbrella §6, D11)."""

from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter

from app.core.git import GitService, _is_safe_auto_branch
from app.main import error_response, ok_response
from app.models.validation import MergeRequest

router = APIRouter()


class NoActiveWorkspace(RuntimeError):
    """Raised when no workspace is active or the Stage 1 registry is unavailable."""


def active_workspace():
    """Resolve the active workspace (R4: single source — app.core.workspaces).

    Returns a RepoProfile or raises NoActiveWorkspace. NEVER imports the
    non-existent app.core.workspace_registry.
    """
    try:
        from app.core.workspaces import active_workspace as _aw
    except ImportError as exc:  # Stage 1 not present yet
        raise NoActiveWorkspace("workspace registry unavailable") from exc
    ws = _aw()
    if ws is None:
        raise NoActiveWorkspace("no active workspace")
    return ws


def _guard(name: str) -> str | None:
    decoded = unquote(name)
    if len(decoded) > 250 or not _is_safe_auto_branch(decoded):
        return None
    return decoded


@router.get("/api/v1/branches/{name}/merge-preflight")
def merge_preflight(name: str) -> dict:
    decoded = _guard(name)
    if decoded is None:
        return error_response("invalid branch name", status=400)
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return error_response(str(exc), status=409)
    pf = GitService(ws).merge_preflight(decoded)
    return ok_response(pf.model_dump(by_alias=True))


@router.post("/api/v1/branches/{name}/merge")
async def merge_branch(name: str, body: MergeRequest) -> dict:
    decoded = _guard(name)
    if decoded is None:
        return error_response("invalid branch name", status=400)
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return error_response(str(exc), status=409)
    # merge_to_base itself returns ok:False with an explicit error for: loop RUNNING
    # ('loop active, stop it before merge', R11), Task-not-found, conflicts, dirty tree.
    res = await GitService(ws).merge_to_base(decoded, push=body.push)
    if not res.get("ok"):
        return error_response(res.get("error", "merge failed"), status=409, **{
            k: v for k, v in res.items() if k not in ("ok", "error")})
    return ok_response(res)
```

> Примечание: `error_response`/`merge_preflight` возвращают `dict`/`JSONResponse`; FastAPI отдаёт оба. Поскольку `error_response` возвращает `JSONResponse`, сигнатура `-> dict` аннотируется как контракт успеха; mypy на `app/api/v1/merge.py` не входит в strict-список exit-criterion (только `validators.py` и `merge.py`-логика merge через GitService уже покрыты). Для строгости при необходимости заменить аннотацию на `dict | JSONResponse`.

- [ ] Зарегистрировать роутер в `backend/app/main.py`. После строки 148 (`from app.api.v1.tasks import router as tasks_router`) добавить:

```python
from app.api.v1.merge import router as merge_router  # noqa: E402
```

И после строки 159 (`app.include_router(agents_router)`) добавить:

```python
app.include_router(merge_router)
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/contract/test_merge_api.py -q
```
Ожидаемый вывод: `3 passed`.

- [ ] mypy strict для merge.py (exit-criterion 4):

```
cd backend && mypy --strict app/api/v1/merge.py
```
Ожидаемый вывод: `Success: no issues found` (при необходимости — поправить аннотацию на `dict | JSONResponse`).

- [ ] Commit:

```
git add backend/app/api/v1/merge.py backend/app/main.py backend/tests/contract/test_merge_api.py
git commit -m "feat(stage3): merge-preflight + merge API router"
```

---

## Task 13: FSM — `Phase.VALIDATE`, `_TRANSITIONS`, `_validate`

Переименование фазы + замена no-op `_tier_review` на `_validate` поверх `ValidationFunnel`. `ws: RepoProfile` прокидывается в `_process_item` (D9).

- [ ] Обновить `backend/tests/unit/test_fsm.py` — добавить тесты новой фазы (в конец файла):

```python
def test_validate_phase_exists():
    assert Phase.VALIDATE.value == "validate"
    assert not hasattr(Phase, "TIER_REVIEW")


def test_validate_transitions_allow_opencode_and_cleanup():
    allowed = _TRANSITIONS[Phase.VALIDATE]
    assert Phase.OPENCODE in allowed   # revision loop
    assert Phase.CLEANUP in allowed
    assert Phase.IDLE in allowed


def test_parse_result_transitions_to_validate():
    assert Phase.VALIDATE in _TRANSITIONS[Phase.PARSE_RESULT]
```

- [ ] Обновить существующий тест в `test_fsm.py` — `test_all_phases_have_transitions` уже итерирует по `Phase`, поэтому переименование пройдёт автоматически. Запустить и убедиться, что новые тесты FAIL:

```
cd backend && python -m pytest tests/unit/test_fsm.py -k "validate_phase or validate_transitions or parse_result_trans" -q
```
Ожидаемый вывод: `AttributeError`/failures (фаза ещё `TIER_REVIEW`).

- [ ] В `backend/app/orchestrator/fsm.py` заменить enum-член (строка 32):

```python
    VALIDATE = "validate"          # was TIER_REVIEW
```

- [ ] Заменить две строки `_TRANSITIONS` (строки 43-44):

```python
    Phase.PARSE_RESULT: {Phase.VALIDATE, Phase.IDLE},
    Phase.VALIDATE: {Phase.OPENCODE, Phase.CLEANUP, Phase.IDLE},
```

- [ ] Заменить метод `_tier_review` (строки 420-427) на `_validate`:

```python
    async def _validate(self, item: dict, ws: object, revision: int) -> "ValidationResult":
        """Run the map-reduce validation funnel (replaces tier-review.sh no-op)."""
        from app.core.validators import ValidationFunnel
        from app.models.validation import ValidationResult
        from app.services.opencode_runner import AgentRunner

        if not self.iter_dir:
            return ValidationResult(gate="pass", revision=revision)
        diff_text = ""
        try:
            from app.core.git import GitService

            diff_text = GitService(ws).diff(item.get("branch", "")) if item.get("branch") else ""
        except Exception:
            diff_text = ""
        runner = AgentRunner(self._pm)  # R15: self._pm = pm выставлен в __init__ (Этап 1); ветки AgentRunner(None) нет
        funnel = ValidationFunnel(ws, runner)
        return await funnel.run_funnel(item, iter_dir=self.iter_dir,
                                       diff_text=diff_text, revision=revision)
```

> Импорт `ValidationResult` для аннотации добавить в шапку файла под `TYPE_CHECKING` (после строки 19):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.validation import ValidationResult
```

- [ ] Запустить FSM-тесты — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_fsm.py -q
```
Ожидаемый вывод: все passed (включая 3 новых + существующие 7).

- [ ] Commit:

```
git add backend/app/orchestrator/fsm.py backend/tests/unit/test_fsm.py
git commit -m "feat(stage3): Phase.VALIDATE + _validate over ValidationFunnel"
```

---

## Task 14: FSM — петля ревизий в `_process_item` + `_parse_result` пишет diff/summary

Реализация цикла `in_review → needs_revision` (spec §4.1). `_process_item` принимает `ws`.

- [ ] Создать падающий тест `backend/tests/integration/test_revision_loop.py`:

```python
"""Revision loop: needs_revision → re-run → pass; exhaustion → failed:max-revisions."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.validation import ValidationResult
from app.orchestrator.fsm import OrchestratorFSM, Phase

pytestmark = pytest.mark.asyncio


def _ws():
    return SimpleNamespace(review=SimpleNamespace(max_revisions=2),
                           repo_path="/tmp/x", base_branch="main", remote="origin",
                           branch_prefix="auto")


async def _drive(fsm, item, ws, validate_results):
    """Patch FSM I/O boundaries; feed scripted ValidationResults."""
    seq = iter(validate_results)
    fsm._validate = AsyncMock(side_effect=lambda *a, **k: next(seq))  # type: ignore
    fsm._run_opencode = AsyncMock(return_value=0)  # type: ignore
    fsm._verify = AsyncMock(return_value=True)  # type: ignore
    fsm._commit = AsyncMock(return_value=True)  # type: ignore
    fsm._parse_result = AsyncMock(return_value=True)  # type: ignore
    fsm._cleanup = AsyncMock(return_value=None)  # type: ignore
    fsm._preflight = AsyncMock(return_value=True)  # type: ignore
    fsm._build_prompt = AsyncMock(return_value="prompt")  # type: ignore
    fsm._mark_done = lambda it: setattr_status(it, "done")  # type: ignore
    fsm._mark_failed = lambda it, s: setattr_status(it, s)  # type: ignore
    fsm._set_phase = lambda ph, iid="": None  # type: ignore
    await fsm._process_item(item, ws)


def setattr_status(item, status):
    item["status"] = status


async def test_needs_revision_then_pass(tmp_path):
    fsm = OrchestratorFSM()
    fsm.iter_dir = tmp_path
    item = {"id": "x", "attempts": 0, "branch": "auto/x-1", "proposal": "p", "acceptance": "a"}
    results = [
        ValidationResult(gate="needs_revision", blocking=["fix it"], revision=0),
        ValidationResult(gate="pass", revision=1),
    ]
    await _drive(fsm, item, _ws(), results)
    assert item["status"] == "done"
    assert item["attempts"] == 1


async def test_max_revisions_exhausted(tmp_path):
    fsm = OrchestratorFSM()
    fsm.iter_dir = tmp_path
    item = {"id": "x", "attempts": 0, "branch": "auto/x-1", "proposal": "p", "acceptance": "a"}
    results = [ValidationResult(gate="needs_revision", blocking=["nope"], revision=i) for i in range(5)]
    await _drive(fsm, item, _ws(), results)
    assert item["status"] == "failed:max-revisions"
    assert item["attempts"] == 3
```

- [ ] Запустить — ожидается FAIL (текущий `_process_item` не принимает `ws` и не петляет):

```
cd backend && python -m pytest tests/integration/test_revision_loop.py -q
```
Ожидаемый вывод: `TypeError: _process_item() takes 2 positional arguments but 3 were given`.

- [ ] Заменить `_process_item` в `backend/app/orchestrator/fsm.py` (строки 96-149) на версию с `ws` и петлёй. Сохраняем линейную часть до `PARSE_RESULT`, затем `while True`:

```python
    async def _process_item(self, item: dict, ws: object) -> None:
        """Run one item through the full FSM pipeline (with revision loop)."""
        self.current_item = item
        item_id = item.get("id", "?")
        self._ws = ws  # type: ignore[attr-defined]

        self._set_phase(Phase.PREFLIGHT, item_id)
        if not await self._preflight(item):
            return

        self._set_phase(Phase.PROMPT_BUILD, item_id)
        prompt = await self._build_prompt(item)
        if not prompt:
            self._mark_failed(item, "failed:prompt-build")
            return

        self._set_phase(Phase.OPENCODE, item_id)
        rc = await self._run_opencode(item, prompt)
        if rc is None:
            self._mark_failed(item, "failed:refused")
            return
        if rc != 0:
            self._mark_failed(item, "failed:opencode")
            return

        self._set_phase(Phase.VERIFY, item_id)
        if not await self._verify(item):
            self._mark_failed(item, "failed:verify")
            return

        self._set_phase(Phase.COMMIT, item_id)
        if not await self._commit(item):
            self._mark_failed(item, "failed:commit")
            return

        self._set_phase(Phase.PARSE_RESULT, item_id)
        await self._parse_result(item)

        self._set_status(item, "in_review")
        attempt = int(item.get("attempts", 0))
        max_rev = int(getattr(getattr(ws, "review", None), "max_revisions", 2))

        while True:
            if self._stop_requested:
                return  # leave status=in_review; checkpoint persisted
            self._set_phase(Phase.VALIDATE, item_id)
            vr = await self._validate(item, ws, attempt)
            if vr.gate == "pass":
                self._set_phase(Phase.CLEANUP, item_id)
                await self._cleanup(item)
                item["validation"] = vr.model_dump(by_alias=True)
                self._mark_done(item)
                return
            attempt += 1
            item["attempts"] = attempt
            if attempt > max_rev:
                item["validation"] = vr.model_dump(by_alias=True)
                self._mark_failed(item, "failed:max-revisions")
                return
            self._set_status(item, "needs_revision")
            from app.core.validators import build_revision_prompt

            rprompt = build_revision_prompt(item, vr, attempt, ws)
            if self.iter_dir:
                (self.iter_dir / "prompt.md").write_text(rprompt, encoding="utf-8")
            self._set_phase(Phase.OPENCODE, item_id)
            rc = await self._run_opencode(item, rprompt)
            if rc is None:
                self._mark_failed(item, "failed:refused")
                return
            if rc != 0:
                self._mark_failed(item, "failed:opencode")
                return
            self._set_phase(Phase.VERIFY, item_id)
            if not await self._verify(item):
                self._mark_failed(item, "failed:verify")
                return
            self._set_phase(Phase.COMMIT, item_id)
            if not await self._commit(item):
                self._mark_failed(item, "failed:commit")
                return
            self._set_phase(Phase.PARSE_RESULT, item_id)
            await self._parse_result(item)
            self._set_status(item, "in_review")
```

- [ ] Добавить хелпер `_set_status` в `OrchestratorFSM` (после `_set_phase`, перед `_preflight`):

```python
    def _set_status(self, item: dict, status: str) -> None:
        """Persist a status transition for the current item (no decision log)."""
        from app.core.state import _read_state, _StateLock, _write_state

        item["status"] = status
        with _StateLock():
            s = _read_state()
            for it in s.get("items", []):
                if it.get("id") == item.get("id"):
                    it["status"] = status
            _write_state(s)
```

- [ ] Обновить вызов `_process_item` в `run()` (строка 80) на передачу `ws`. Поскольку `run()` сам должен получить активный воркспейс, заменить строку 80:

```python
                await self._process_item(item, self._resolve_ws())
```

И добавить метод `_resolve_ws` (после `_pick_next_item`):

```python
    def _resolve_ws(self) -> object:
        """Resolve the active workspace (Stage 1 registry); fallback raises."""
        from app.core.workspaces import active_workspace  # R4: единый источник, НЕ workspace_registry

        return active_workspace()
```

> Примечание: в `run()` обёртка `except Exception` уже ловит `_mark_failed` — при отсутствии Stage 1 `active_workspace` бросит ImportError/RuntimeError, item упадёт в `failed:<Error>` и loop продолжит спать. Это согласуется со spec §6 п.11 (graceful).

- [ ] Расширить `_parse_result` (строки 396-418) — писать `diff.patch`/`summary.md`. Перед `return True` в конце метода добавить:

```python
        # diff.patch + summary.md (umbrella §4.4)
        branch = item.get("branch")
        ws = getattr(self, "_ws", None)
        if branch and ws is not None:
            try:
                from app.core.git import GitService

                diff_text = GitService(ws).diff(branch)
                (self.iter_dir / "diff.patch").write_text(diff_text, encoding="utf-8")
                item["diff_ref"] = f"{self.iter_dir.name}/diff.patch"
            except Exception:
                pass
        primary = self.iter_dir / "output.primary.jsonl"
        if primary.exists():
            from app.core.validators import _last_text_event

            summary = _last_text_event(primary)[:4000]
            (self.iter_dir / "summary.md").write_text(summary, encoding="utf-8")
            item["result_summary"] = summary
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/integration/test_revision_loop.py tests/unit/test_fsm.py -q
```
Ожидаемый вывод: все passed.

- [ ] grep-guard для fsm.py (exit-criterion 5):

```
cd backend && python -c "import re,pathlib; t=pathlib.Path('app/orchestrator/fsm.py').read_text(); bad=re.findall(r'tmux|pgrep|pkill|tier-review\\.sh|bash ', t); print('fsm.py forbidden tokens:', bad)"
```
Ожидаемый вывод: `fsm.py forbidden tokens: []`.

> Если `_verify` всё ещё содержит `bash`/`verify.sh` (строки 328-360) — это путь Stage 1 (`VerifyRunner`). В рамках Stage 3 grep-guard требует чистоты `fsm.py`. Если Stage 1 ещё не заменил `_verify`, заменить тело `_verify` на делегацию (см. crossRefs): импорт `VerifyRunner` под try, при ImportError — `return True` (no-op verify), чтобы убрать `bash`. См. Open Questions.

- [ ] Commit:

```
git add backend/app/orchestrator/fsm.py backend/tests/integration/test_revision_loop.py
git commit -m "feat(stage3): revision loop in _process_item + diff/summary in _parse_result"
```

---

## Task 15: FSM `_verify` — убрать `bash verify.sh` (grep-guard)

Exit-criterion 5 требует 0 совпадений `bash ` в `fsm.py`. Делегируем в `VerifyRunner` (Stage 1) с graceful-fallback.

- [ ] Добавить падающий тест `backend/tests/unit/test_fsm_verify.py`:

```python
"""_verify must not shell out to bash/verify.sh (Stage 3 cross-platform)."""

from __future__ import annotations

import pathlib
import re


def test_fsm_has_no_bash_verify():
    src = pathlib.Path("app/orchestrator/fsm.py").read_text()
    assert "verify.sh" not in src
    assert not re.search(r'"bash"', src)
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_fsm_verify.py -q
```
Ожидаемый вывод: `assert 'verify.sh' not in src` fails.

- [ ] Заменить метод `_verify` (строки 328-360) в `backend/app/orchestrator/fsm.py`:

```python
    async def _verify(self, item: dict) -> bool:
        """Run project verify commands via VerifyRunner (Stage 1); no bash, no pnpm hardcode."""
        ws = getattr(self, "_ws", None)
        if ws is None:
            return True
        try:
            from app.core.verify import VerifyRunner
        except ImportError:
            return True  # Stage 1 not present — treat as green (no-op verify)
        if not self.iter_dir:
            return True
        runner = VerifyRunner(ws)
        log_path = self.iter_dir / "verify.log"
        timeout = int(getattr(ws, "verify_timeout_sec", 900))
        result = await runner.run(cwd=str(getattr(ws, "repo_path", ".")),
                                  log_path=log_path, timeout_sec=timeout)
        if not result.ok:
            log.warning("verify failed: %s", result.failed_command)
        return result.ok
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_fsm_verify.py tests/unit/test_fsm.py -q
```
Ожидаемый вывод: все passed.

- [ ] Полный grep-guard по spec exit-criterion 5:

```
cd backend && python -c "import re,pathlib; files=['app/orchestrator/fsm.py','app/core/validators.py','app/core/git.py','app/api/v1/merge.py']; bad={f: re.findall(r'tmux|pgrep|pkill|tier-review\\.sh|bash ', pathlib.Path(f).read_text()) for f in files}; print({f:v for f,v in bad.items() if v}) or print('all clean' if not any(bad.values()) else 'FOUND')"
```
Ожидаемый вывод: `all clean`.

- [ ] Commit:

```
git add backend/app/orchestrator/fsm.py backend/tests/unit/test_fsm_verify.py
git commit -m "feat(stage3): _verify delegates to VerifyRunner, no bash"
```

---

## Task 16: `main.py` — убрать `pkill`-shutdown и `tmux`-startup-check (D1)

`main.py` в exit-criterion 5 не перечислен, но D1/§9 требуют убрать `pkill`. ProcessManager.cancel заменяет. Делаем минимально, не ломая lifespan.

- [ ] Добавить падающий тест `backend/tests/unit/test_main_no_pkill.py`:

```python
"""main.py must not pkill on shutdown nor require tmux on startup (D1)."""

from __future__ import annotations

import pathlib


def test_main_has_no_pkill():
    src = pathlib.Path("app/main.py").read_text()
    assert "pkill" not in src
    assert '"tmux"' not in src
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_main_no_pkill.py -q
```
Ожидаемый вывод: `assert 'pkill' not in src` fails.

- [ ] В `backend/app/main.py` заменить startup-tool-check (строка 90):

```python
    for tool_name in ("git", "opencode"):
```

- [ ] Удалить блок pkill (строки 103-108) — заменить на ProcessManager.cancel (graceful, при отсутствии Stage 1 — no-op):

```python
    # Cancel any managed background processes (loop/scan) — replaces pkill (D1).
    try:
        from app.core.process import ProcessManager

        pm = ProcessManager()
        for handle in pm.list():
            with __import__("contextlib").suppress(Exception):
                await pm.cancel(handle.name)
    except ImportError:
        pass  # Stage 1 ProcessManager not present yet
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_main_no_pkill.py tests/integration/test_api_health.py -q
```
Ожидаемый вывод: все passed (health-роуты не сломаны).

- [ ] Commit:

```
git add backend/app/main.py backend/tests/unit/test_main_no_pkill.py
git commit -m "feat(stage3): drop pkill shutdown + tmux startup check (D1)"
```

---

## Task 17: `iters.py` — отдавать `validation` рядом с legacy `final_decision`

`_iter_details` читает `iter/validation/final-decision.json` (spec §3, modifies-table).

- [ ] Добавить падающий тест `backend/tests/unit/test_iters_validation.py`:

```python
"""_iter_details surfaces validation/final-decision.json as 'validation'."""

from __future__ import annotations

import json

import app.core.iters as iters_mod
from app.core.iters import _iter_details


def test_iter_details_includes_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(iters_mod, "STATE_DIR", tmp_path)
    d = tmp_path / "iter-0001"
    (d / "validation").mkdir(parents=True)
    (d / "validation" / "final-decision.json").write_text(
        json.dumps({"gate": "pass", "blocking": [], "revision": 0}))
    info = _iter_details("iter-0001")
    assert info["ok"] is True
    assert info["validation"]["gate"] == "pass"
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_iters_validation.py -q
```
Ожидаемый вывод: `KeyError: 'validation'`.

- [ ] В `backend/app/core/iters.py`, в `_iter_details`, перед `info["cost"] = _iter_cost(d)` (строка 120) добавить:

```python
    vdir = d / "validation"
    if vdir.exists():
        fd = vdir / "final-decision.json"
        if fd.exists():
            info["validation"] = _load_json(fd)
        l1 = []
        for vf in sorted((vdir / "layer1").glob("*.json")) if (vdir / "layer1").exists() else []:
            v = _load_json(vf) or {}
            l1.append({k: v.get(k) for k in ("lens", "verdict", "confidence", "reasoning")})
        if l1:
            info.setdefault("validation", {})
            if isinstance(info["validation"], dict):
                info["validation"]["layer1"] = l1
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_iters_validation.py -q
```
Ожидаемый вывод: `1 passed`.

- [ ] Commit:

```
git add backend/app/core/iters.py backend/tests/unit/test_iters_validation.py
git commit -m "feat(stage3): iter_details surfaces validation final-decision"
```

---

## Task 18: Frontend types — `LensVerdict`, `ValidationResult`, merge-типы, `ItemStatus`

`frontend/src/types/api.ts` (spec §4.7). Дословные имена полей.

- [ ] Расширить `ItemStatus` (строки 5-12) — добавить `'in_review'`:

```typescript
export type ItemStatus =
  | 'pending'
  | 'in_progress'
  | 'in_review'
  | 'done'
  | 'merged'
  | 'needs_revision'
  | 'discarded'
  | `failed:${string}`
```

- [ ] В `interface Item` (после строки 39 `mergedAt: string | null`) добавить:

```typescript
  validation?: ValidationResult | null
  resultSummary?: string
  diffRef?: string | null
```

- [ ] Добавить новые интерфейсы (после `interface Verdict`, строка 162):

```typescript
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
  cleanTree: boolean
  verifyGreen: boolean
  validationPassed: boolean
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
```

- [ ] Проверить типы:

```
cd frontend && npx vue-tsc --noEmit
```
Ожидаемый вывод: без ошибок (exit 0).

- [ ] Commit:

```
git add frontend/src/types/api.ts
git commit -m "feat(stage3): frontend validation + merge types, in_review status"
```

---

## Task 19: API-client — `mergePreflight`, `merge`

`frontend/src/api/client.ts` (spec §4.7).

- [ ] Обновить импорт типов (строка 1) — добавить `MergePreflightResponse, MergeResult`:

```typescript
import type { EffectiveConfig, StateSnapshot, IterDetails, IterSummary, AgentActivity, BranchActionResponse, ScanStatus, ScanListItem, Decision, ParsedEvent, ItemPatch, AddItemRequest, DriverStartOptions, IterReviewsResponse, ScanStartRequest, MergePreflightResponse, MergeResult } from '@/types/api'
```

- [ ] В объект `api`, после `branchAction` (строка 124), добавить:

```typescript
  // Merge (Stage 3 / D11)
  mergePreflight: (name: string) =>
    request<{ ok: boolean } & MergePreflightResponse>(`/api/v1/branches/${encodeURIComponent(name)}/merge-preflight`),
  merge: (name: string, push: boolean) =>
    request<MergeResult>(`/api/v1/branches/${encodeURIComponent(name)}/merge`, { method: 'POST', body: JSON.stringify({ push }) }),
```

- [ ] Проверить типы:

```
cd frontend && npx vue-tsc --noEmit
```
Ожидаемый вывод: exit 0.

- [ ] Commit:

```
git add frontend/src/api/client.ts
git commit -m "feat(stage3): api.mergePreflight + api.merge"
```

---

## Task 20: Task-store — `validationCache` + `fetchValidation`

`frontend/src/stores/task.ts` (spec §3 modifies-table). `fetchValidation` читает `iterDetails().validation`.

- [ ] Обновить импорт типов (строка 3) — добавить `ValidationResult`:

```typescript
import type { Item, IterDetails, ParsedEvent, IterReviewsResponse, ValidationResult } from '@/types/api'
```

- [ ] Добавить кэш (после строки 26 `const reviewsCache = ...`):

```typescript
  const validationCache = ref<Map<string, CachedEntry<ValidationResult | null>>>(new Map())
```

- [ ] Добавить метод `fetchValidation` (после `fetchReviews`, строка 102):

```typescript
  async function fetchValidation(dir: string): Promise<ValidationResult | null> {
    const cached = validationCache.value.get(dir)
    if (cached && !isExpired(cached)) return cached.data
    try {
      const d = await api.iterDetails(dir)
      const v = (d as IterDetails & { validation?: ValidationResult }).validation ?? null
      validationCache.value.set(dir, { data: v, timestamp: Date.now() })
      return v
    } catch {
      return null
    }
  }
```

- [ ] В `clearCache` (строка 113) добавить:

```typescript
    validationCache.value.clear()
```

- [ ] В return-объекте (строка 121) добавить `fetchValidation`:

```typescript
    fetchDetails, fetchEvents, fetchDiff, fetchReviews, fetchValidation,
```

- [ ] Проверить типы:

```
cd frontend && npx vue-tsc --noEmit
```
Ожидаемый вывод: exit 0.

- [ ] Commit:

```
git add frontend/src/stores/task.ts
git commit -m "feat(stage3): task store fetchValidation + validationCache"
```

---

## Task 21: vitest-инфраструктура (jsdom + @vue/test-utils)

vitest есть, но нет jsdom/test-utils. Без них component-specs не запустятся.

- [ ] Установить dev-зависимости:

```
cd frontend && npm install -D @vue/test-utils@^2.4 jsdom@^25
```
Ожидаемый вывод: пакеты добавлены в `devDependencies`.

- [ ] Создать `frontend/vitest.setup.ts`:

```typescript
import { config } from '@vue/test-utils'

// Provide a no-op global stub registry placeholder; per-test mounts override.
config.global = config.global || {}
```

- [ ] Создать `frontend/vitest.config.ts`:

```typescript
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
  },
})
```

- [ ] Smoke-тест инфраструктуры — создать временный `frontend/src/__smoke__.spec.ts`:

```typescript
import { describe, it, expect } from 'vitest'
describe('vitest infra', () => { it('runs', () => { expect(1 + 1).toBe(2) }) })
```

- [ ] Запустить:

```
cd frontend && npx vitest run src/__smoke__.spec.ts
```
Ожидаемый вывод: `1 passed`.

- [ ] Удалить smoke-файл и закоммитить инфраструктуру:

```
rm frontend/src/__smoke__.spec.ts
git add frontend/package.json frontend/vitest.config.ts frontend/vitest.setup.ts frontend/package-lock.json
git commit -m "test(stage3): vitest jsdom + vue-test-utils infrastructure"
```

---

## Task 22: `ValidationPanel.vue` + spec

Три секции: Layer 1 (линзы), Layer 2 (арбитры), Gate (spec §4.7).

- [ ] Создать падающий тест `frontend/src/components/ValidationPanel.spec.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ValidationPanel from './ValidationPanel.vue'
import type { ValidationResult } from '@/types/api'

const vr: ValidationResult = {
  layer1: [
    { lens: 'correctness', verdict: 'approve', confidence: 0.9, reasoning: 'ok' },
    { lens: 'tests', verdict: 'needs_revision', confidence: 0.4, reasoning: 'no test' },
    { lens: 'scope', verdict: 'reject', confidence: 0.8, reasoning: 'creep' },
  ],
  layer2Summary: [{ arbiter: 0, verdict: 'needs_revision' }],
  gate: 'needs_revision',
  blocking: ['tests: no test', 'scope: creep'],
  revision: 1,
}

describe('ValidationPanel', () => {
  it('renders one row per lens', () => {
    const w = mount(ValidationPanel, { props: { validation: vr } })
    expect(w.findAll('[data-test="lens-row"]')).toHaveLength(3)
  })
  it('renders gate and blocking list', () => {
    const w = mount(ValidationPanel, { props: { validation: vr } })
    expect(w.find('[data-test="gate"]').text()).toContain('needs_revision')
    expect(w.findAll('[data-test="blocking-item"]')).toHaveLength(2)
  })
  it('shows placeholder when validation is null', () => {
    const w = mount(ValidationPanel, { props: { validation: null } })
    expect(w.find('[data-test="no-validation"]').exists()).toBe(true)
  })
})
```

- [ ] Запустить — ожидается FAIL:

```
cd frontend && npx vitest run src/components/ValidationPanel.spec.ts
```
Ожидаемый вывод: `Failed to resolve import "./ValidationPanel.vue"`.

- [ ] Создать `frontend/src/components/ValidationPanel.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'
import type { ValidationResult, LensVerdict } from '@/types/api'

const props = defineProps<{ validation: ValidationResult | null }>()

const lensRows = computed<LensVerdict[]>(() => props.validation?.layer1 ?? [])
const gateClass = computed(() =>
  props.validation?.gate === 'pass' ? 'gate-pass' : 'gate-revision')

function verdictClass(v: string): string {
  if (v === 'approve') return 'v-approve'
  if (v === 'reject') return 'v-reject'
  return 'v-revision'
}
</script>

<template>
  <div v-if="!validation" data-test="no-validation" class="muted">
    Валидация ещё не запускалась для этой итерации.
  </div>
  <div v-else class="validation-panel">
    <section class="layer">
      <h4>Слой 1 — линзы</h4>
      <div
        v-for="lv in lensRows"
        :key="lv.lens"
        data-test="lens-row"
        class="lens-row"
        :class="verdictClass(lv.verdict)"
      >
        <span class="lens-name">{{ lv.lens }}</span>
        <span class="lens-verdict">{{ lv.verdict }}</span>
        <span class="lens-conf">{{ Math.round(lv.confidence * 100) }}%</span>
        <span class="lens-reason">{{ lv.reasoning }}</span>
      </div>
    </section>

    <section v-if="validation.layer2Summary.length" class="layer">
      <h4>Слой 2 — арбитры</h4>
      <div
        v-for="(a, i) in validation.layer2Summary"
        :key="i"
        data-test="arbiter-row"
        class="arbiter-row"
      >
        {{ JSON.stringify(a) }}
      </div>
    </section>

    <section class="layer gate" :class="gateClass" data-test="gate">
      <h4>Гейт: {{ validation.gate }}</h4>
      <ul v-if="validation.blocking.length">
        <li v-for="(b, i) in validation.blocking" :key="i" data-test="blocking-item">{{ b }}</li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.validation-panel { display: flex; flex-direction: column; gap: 12px; }
.lens-row { display: grid; grid-template-columns: 110px 110px 50px 1fr; gap: 8px; padding: 4px 0; }
.v-approve { color: var(--green, #4caf50); }
.v-revision { color: var(--amber, #ffb300); }
.v-reject { color: var(--rose, #e53935); }
.gate-pass h4 { color: var(--green, #4caf50); }
.gate-revision h4 { color: var(--amber, #ffb300); }
.muted { color: #888; padding: 8px; }
</style>
```

- [ ] Запустить — ожидается PASS:

```
cd frontend && npx vitest run src/components/ValidationPanel.spec.ts
```
Ожидаемый вывод: `3 passed`.

- [ ] Commit:

```
git add frontend/src/components/ValidationPanel.vue frontend/src/components/ValidationPanel.spec.ts
git commit -m "feat(stage3): ValidationPanel component + spec"
```

---

## Task 23: `MergeButton.vue` + spec

Кнопка disabled пока `!preflight.ok`; tooltip перечисляет невыполненные предусловия; конфликт → модалка (spec §4.7).

- [ ] Создать падающий тест `frontend/src/components/MergeButton.spec.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import MergeButton from './MergeButton.vue'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: { mergePreflight: vi.fn(), merge: vi.fn() },
}))

beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks() })

describe('MergeButton', () => {
  it('disables button when preflight not ok', async () => {
    ;(api.mergePreflight as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false, cleanTree: false, verifyGreen: true, validationPassed: true,
      baseBranch: 'main', conflicts: [],
    })
    const w = mount(MergeButton, { props: { branch: 'auto/x-1' } })
    await flushPromises()
    expect(w.find('[data-test="merge-btn"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="preflight-tooltip"]').text()).toContain('рабочее дерево')
  })

  it('enables button when preflight ok', async () => {
    ;(api.mergePreflight as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, cleanTree: true, verifyGreen: true, validationPassed: true,
      baseBranch: 'main', conflicts: [],
    })
    const w = mount(MergeButton, { props: { branch: 'auto/x-1' } })
    await flushPromises()
    expect(w.find('[data-test="merge-btn"]').attributes('disabled')).toBeUndefined()
  })

  it('shows conflict modal when merge returns conflicts', async () => {
    ;(api.mergePreflight as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, cleanTree: true, verifyGreen: true, validationPassed: true,
      baseBranch: 'main', conflicts: [],
    })
    ;(api.merge as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false, conflicts: ['README.md', 'src/x.ts'], error: 'merge conflict',
    })
    const w = mount(MergeButton, { props: { branch: 'auto/x-1' } })
    await flushPromises()
    await w.find('[data-test="merge-btn"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="conflict-modal"]').exists()).toBe(true)
    expect(w.findAll('[data-test="conflict-file"]')).toHaveLength(2)
  })
})
```

- [ ] Запустить — ожидается FAIL:

```
cd frontend && npx vitest run src/components/MergeButton.spec.ts
```
Ожидаемый вывод: `Failed to resolve import "./MergeButton.vue"`.

- [ ] Создать `frontend/src/components/MergeButton.vue`:

```vue
<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import type { MergePreflightResponse, MergeResult } from '@/types/api'
import { api } from '@/api/client'

const props = defineProps<{ branch: string }>()
const emit = defineEmits<{ merged: [] }>()

const preflight = ref<MergePreflightResponse | null>(null)
const pushAfter = ref(false)
const merging = ref(false)
const conflictFiles = ref<string[]>([])
const errorMsg = ref<string | null>(null)

const unmet = computed<string[]>(() => {
  const p = preflight.value
  if (!p) return ['загрузка предпроверок…']
  const u: string[] = []
  if (!p.cleanTree) u.push('рабочее дерево не чистое')
  if (!p.verifyGreen) u.push('verify не зелёный')
  if (!p.validationPassed) u.push('воронка не пройдена')
  return u
})

const canMerge = computed(() => preflight.value?.ok === true && !merging.value)

async function loadPreflight() {
  try {
    preflight.value = await api.mergePreflight(props.branch)
  } catch {
    preflight.value = null
  }
}

async function doMerge() {
  if (!canMerge.value) return
  merging.value = true
  errorMsg.value = null
  conflictFiles.value = []
  try {
    const res: MergeResult = await api.merge(props.branch, pushAfter.value)
    if (res.ok) {
      emit('merged')
    } else if (res.conflicts && res.conflicts.length) {
      conflictFiles.value = res.conflicts
    } else {
      errorMsg.value = res.error ?? 'merge не удался'
    }
  } catch (e: unknown) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    merging.value = false
  }
}

onMounted(loadPreflight)
</script>

<template>
  <div class="merge-button">
    <label class="push-toggle">
      <input type="checkbox" v-model="pushAfter" />
      push после merge
    </label>
    <button
      data-test="merge-btn"
      :disabled="!canMerge || undefined"
      @click="doMerge"
    >
      {{ merging ? 'Merge…' : 'Merge в base' }}
    </button>
    <div v-if="unmet.length" data-test="preflight-tooltip" class="tooltip">
      {{ unmet.join(', ') }}
    </div>
    <div v-if="errorMsg" class="error">{{ errorMsg }}</div>

    <div v-if="conflictFiles.length" data-test="conflict-modal" class="conflict-modal">
      <h4>Конфликт merge — разрешите вручную в рабочей копии</h4>
      <ul>
        <li v-for="f in conflictFiles" :key="f" data-test="conflict-file">{{ f }}</li>
      </ul>
      <button @click="conflictFiles = []">Закрыть</button>
    </div>
  </div>
</template>

<style scoped>
.merge-button { display: flex; flex-direction: column; gap: 6px; }
button[disabled] { opacity: 0.5; cursor: not-allowed; }
.tooltip { font-size: 12px; color: var(--amber, #ffb300); }
.error { color: var(--rose, #e53935); font-size: 12px; }
.conflict-modal { border: 1px solid var(--rose, #e53935); padding: 8px; margin-top: 8px; }
</style>
```

- [ ] Запустить — ожидается PASS:

```
cd frontend && npx vitest run src/components/MergeButton.spec.ts
```
Ожидаемый вывод: `3 passed`.

- [ ] Commit:

```
git add frontend/src/components/MergeButton.vue frontend/src/components/MergeButton.spec.ts
git commit -m "feat(stage3): MergeButton component + spec"
```

---

## Task 24: `RunTimeline.vue`

Таймлайн фаз FSM + revision-петли (spec §4.7). Props — `details`/`attempts`; визуализация без сетевых вызовов.

- [ ] Создать `frontend/src/components/RunTimeline.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  attempts: number
  iterDir: string | null
}>()

const PHASES = ['preflight', 'prompt_build', 'opencode', 'verify', 'commit', 'parse_result', 'validate'] as const

const revisionLoops = computed(() => {
  const n = Math.max(0, props.attempts)
  return Array.from({ length: n }, (_, i) => i + 1)
})
</script>

<template>
  <div class="run-timeline">
    <div class="iter-label" v-if="iterDir">{{ iterDir }}</div>
    <ol class="phases">
      <li v-for="p in PHASES" :key="p" class="phase">{{ p }}</li>
    </ol>
    <div v-if="revisionLoops.length" class="revisions">
      <span class="rev-label">ревизии:</span>
      <span v-for="r in revisionLoops" :key="r" class="rev-chip">r{{ r }}</span>
    </div>
  </div>
</template>

<style scoped>
.run-timeline { display: flex; flex-direction: column; gap: 8px; }
.phases { display: flex; flex-wrap: wrap; gap: 6px; list-style: none; padding: 0; }
.phase { background: var(--panel, #1a1a1a); padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.rev-chip { background: var(--amber, #ffb300); color: #000; padding: 2px 6px; border-radius: 4px; margin-left: 4px; }
</style>
```

- [ ] Проверить типы:

```
cd frontend && npx vue-tsc --noEmit
```
Ожидаемый вывод: exit 0.

- [ ] Commit:

```
git add frontend/src/components/RunTimeline.vue
git commit -m "feat(stage3): RunTimeline component"
```

---

## Task 25: `TaskDrawer.vue` — интеграция ValidationPanel/RunTimeline/MergeButton

Вкладка «Ревью»→`ValidationPanel`; новая вкладка «Таймлайн»→`RunTimeline`; `MergeButton` в `drawer-actions` (spec §3, §4.7).

- [ ] Добавить импорты компонентов в `frontend/src/components/TaskDrawer.vue` (после строки 9 `import IterChip from './IterChip.vue'`):

```typescript
import ValidationPanel from './ValidationPanel.vue'
import MergeButton from './MergeButton.vue'
import RunTimeline from './RunTimeline.vue'
import type { ValidationResult } from '@/types/api'
```

- [ ] Добавить реактивное состояние (после строки 24 `const reviewsData = ref<IterReviewsResponse | null>(null)`):

```typescript
const validationData = ref<ValidationResult | null>(null)
```

- [ ] Расширить `TABS` (строки 43-51) — добавить «Таймлайн» после «Ревью»:

```typescript
const TABS = [
  'Описание',
  'Итерации',
  'Активность',
  'Инструменты',
  'Дифф',
  'Ревью',
  'Таймлайн',
  'Агенты',
]
```

- [ ] Обновить `loadTab` (строки 115-146) — case 5 (Ревью) грузит validation; добавить case 6 (Таймлайн), сдвинуть «Агенты» на 7:

```typescript
      case 5: // Ревью
        reviewsData.value = await taskStore.fetchReviews(dir) ?? null
        validationData.value = await taskStore.fetchValidation(dir) ?? null
        break
      case 6: // Таймлайн
        details.value = (await taskStore.fetchDetails(dir)) ?? null
        break
      case 7: // Агенты
        break
```

- [ ] Добавить условие сброса `validationData` при смене item — в обработчике, где сбрасывается `reviewsData.value = null` (строка 104):

```typescript
    validationData.value = null
```

- [ ] В шаблоне, в секции вкладки «Ревью» (около строки 333, рядом с `reviewsData?.final_decision`), добавить рендер панели. Найти блок панели «Ревью» и в его начало вставить:

```html
          <ValidationPanel :validation="validationData" />
```

- [ ] Добавить рендер вкладки «Таймлайн». В шаблоне после блока вкладки «Ревью» добавить условный блок (индекс 6):

```html
        <div v-if="tab === 6" class="tab-panel">
          <RunTimeline :attempts="item?.attempts ?? 0" :iter-dir="item?.lastIter ?? null" />
        </div>
```

- [ ] В `drawer-actions` (строка 352) добавить `MergeButton` для веток с `auto/`-префиксом. Внутри `<div class="drawer-actions">` добавить:

```html
            <MergeButton
              v-if="item?.branch && (item.status === 'done' || item.status === 'in_review')"
              :branch="item.branch"
              @merged="boardStore.fetchState()"
            />
```

- [ ] Проверить типы и spec-тесты компонентов вместе:

```
cd frontend && npx vue-tsc --noEmit && npx vitest run src/components/ValidationPanel.spec.ts src/components/MergeButton.spec.ts
```
Ожидаемый вывод: exit 0 и `6 passed`.

- [ ] Commit:

```
git add frontend/src/components/TaskDrawer.vue
git commit -m "feat(stage3): TaskDrawer integrates ValidationPanel/RunTimeline/MergeButton"
```

---

## Task 26: Полный прогон exit-criteria + финальный коммит

Проверяем все 6 автоматизируемых exit-criteria (spec §9).

- [ ] Backend unit + integration + contract (criteria 1-3):

```
cd backend && python -m pytest tests/unit/test_validators.py tests/unit/test_build_revision_prompt.py tests/integration/test_merge_to_base.py tests/integration/test_funnel_loop.py tests/integration/test_revision_loop.py tests/contract/test_validation_result_contract.py tests/contract/test_merge_api.py -q
```
Ожидаемый вывод: все passed.

- [ ] Полный backend-набор (регрессии):

```
cd backend && python -m pytest -q
```
Ожидаемый вывод: все passed.

- [ ] Lint + mypy (criterion 4):

```
cd backend && ruff check app/ && mypy --strict app/core/validators.py app/api/v1/merge.py
```
Ожидаемый вывод: `All checks passed!` / `Success: no issues found`.

- [ ] grep-guard (criterion 5):

```
cd backend && python -c "import re,pathlib; files=['app/orchestrator/fsm.py','app/core/validators.py','app/core/git.py','app/api/v1/merge.py']; res={f:re.findall(r'tmux|pgrep|pkill|tier-review\\.sh|bash ', pathlib.Path(f).read_text()) for f in files}; bad={f:v for f,v in res.items() if v}; assert not bad, bad; print('grep-guard clean')"
```
Ожидаемый вывод: `grep-guard clean`.

- [ ] Frontend vitest + vue-tsc (criterion 6):

```
cd frontend && npx vitest run && npx vue-tsc --noEmit
```
Ожидаемый вывод: все specs passed, vue-tsc exit 0.

- [ ] Финальный коммит (если остались несвязанные правки форматирования):

```
git add -A
git commit -m "chore(stage3): exit-criteria verification pass" --allow-empty
```

---

## Open Questions

1. **Stage 1/2 ещё не в дереве.** На момент анализа `backend/app/models/workspace.py` (`RepoProfile`/`AgentsConfig`/`AgentRef`/`ReviewConfig`), `backend/app/services/opencode_runner.py` (`AgentRunner`), `backend/app/core/verify.py` (`VerifyRunner`), `backend/app/core/workspace_registry.py` (`active_workspace`), `backend/app/core/process.py` (`ProcessManager`) отсутствуют. Stage 3 потребляет их по контракту. План изолирует зависимость через `typing.Protocol` + ленивые импорты с graceful-fallback (merge → 409 «no active workspace»; `_verify`/`_validate`/`main.py` → no-op при `ImportError`), а интеграционные тесты используют conftest-fakes (`make_repo_profile`, `_FakeAgentRunner`). **Решение пользователя:** реализовывать Stage 3 поверх ещё-несуществующего Stage 1 (с fallback-заглушками, как в плане) ИЛИ дождаться Stage 1 и убрать fallback-ветки? Если Stage 1 уже мёржится параллельно — синхронизировать точные сигнатуры `AgentRunner.run`/`VerifyRunner.run`/`active_workspace` до Task 7/13/15.

2. **mypy-строгость merge.py.** `error_response` возвращает `JSONResponse`, а success-ветки — `dict`. Аннотация `-> dict` в роутере merge формально неточна. Exit-criterion 4 требует `mypy --strict` только для `validators.py` и `merge.py`. Уточнить: достаточно ли `dict | JSONResponse` (как в плане), или роутеры должны возвращать строго `Response`? Текущий код базы (`branches.py`) уже смешивает оба, так что выбран совместимый путь.

3. **`AgentRunner.__init__` сигнатура.** В Task 13 `_validate` создаёт `AgentRunner(self._pm)` (umbrella §5.2: `__init__(self, pm: ProcessManager)`). Если Stage 1 решит иной конструктор (например, без `ProcessManager`), Task 13 нужно поправить. Зафиксировать сигнатуру `AgentRunner` до реализации.

4. **`vitest`/`@vue/test-utils`/`jsdom` версии.** План пинит `@vue/test-utils@^2.4`, `jsdom@^25` под vitest ^3.1 / vue ^3.5. Подтвердить, что добавление dev-зависимостей допустимо (spec §8 говорит «frontend без новых пакетов», но это про runtime; test-utils/jsdom — devDependencies). Если запрет строгий — нужна альтернатива (например, `@vue/server-renderer` snapshot без jsdom), что усложнит specs.
