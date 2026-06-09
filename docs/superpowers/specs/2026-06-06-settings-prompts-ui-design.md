---
title: In-browser Settings + Prompts UI (config, repo onboarding, omo/models, per-role models, prompt overrides)
status: detailed
date: 2026-06-06
audience: tool author (user) + implementing engineer
language: prose=ru, identifiers/paths/commands=en
---

# In-browser Settings + Prompts UI

Goal: всё конфигурируется в браузере — выбор/добавление репозитория, режим opencode (omo-агенты ↔ raw-модели),
модели по ролям (primary/fallback/validators/arbiters/final), strictness/verify/базовые параметры, и редактор
промптов с переопределением под репозиторий. Везде ⓘ-подсказки.

Бэкенд под агентов/конфиг/глобальные промпты уже готов (`PUT /api/v1/workspaces/{id}` принимает полный `agents`;
`/api/v1/prompts/*`; `AgentRunner` переключает omo/raw через `use_models`). Новое — только слой override промптов
под репозиторий и UI.

## 1. Backend

### 1.1 Prompt override layer (`<repo>/.hephaestus/prompts/<name>.md`)
- `PromptManager` получает опциональный override-dir. Резолв эффективного промпта: если существует
  `<active-repo>/.hephaestus/prompts/<name>.md` — он, иначе глобальный `prompts/<name>.md`.
- Рантайм: `PromptManager.render_prompt`/`build_task_prompt` и `validators._render_template` при наличии активного
  воркспейса читают override-версию (через `registry.active()` → `<repo>/.hephaestus/prompts`). Глобальные файлы не
  мутируются override-операциями.
- API (workspaces router):
  - `GET  /api/v1/workspaces/{id}/prompts/{name}` → `{ok, name, content, global, overridden, variables}`
    (content = эффективный текст; global = исходный; overridden = есть ли файл-override).
  - `PUT  /api/v1/workspaces/{id}/prompts/{name}` `{content}` → пишет `<repo>/.hephaestus/prompts/<name>.md`.
  - `DELETE /api/v1/workspaces/{id}/prompts/{name}` → удаляет override (сброс к глобальному).
- Имя промпта валидируется как safe slug (без traversal), как в существующем prompts-роутере.

### 1.2 Base config defaults
- `WorkspaceRegistry._NEUTRAL_AGENTS` дополняется рабочими дефолтами пулов: `validators` = 5×primary
  (по линзе), `arbiters` = 2×primary, `final` = primary — чтобы воронка работала из коробки и были
  редактируемые строки. (Существующие воркспейсы не трогаются; правятся через UI.)
- Пороги/ревизии/таймауты уже дефолтятся в `config._config_effective` (Stage 3) — оставляем.

## 2. Frontend

### 2.1 Types + api (`types/api.ts`, `api/client.ts`)
- `RepoProfile.agents`: добавить `validators: AgentRef[]`, `arbiters: AgentRef[]`, `final: AgentRef | null`.
- `PromptSummary { name; title?; variables: string[] }`, `WsPromptDetail { name; content; global; overridden; variables }`.
- api: `listPrompts()`, `getWsPrompt(id,name)`, `putWsPrompt(id,name,content)`, `resetWsPrompt(id,name)`.

### 2.2 Components
- `HelpHint.vue` — ⓘ с tooltip (prop `text`), используется во всех секциях настроек.
- `AgentRefEditor.vue` — редактор одного `AgentRef`: в omo-режиме поле `agent`; в режиме моделей `provider`+`model`.
  props: `modelValue: AgentRef`, `useModels: boolean`; emit `update:modelValue`.
- `AgentListEditor.vue` — список `AgentRef[]` (validators/arbiters): строки + добавить/удалить + «заполнить все».

### 2.3 Views
- `SettingsView.vue` (был заглушкой → полноценный): секции с `HelpHint`:
  1. **Репозиторий** — активный repo + форма «Добавить репозиторий» (path → `api.onboard` → активировать),
     переключение активного.
  2. **opencode / агенты** — тумблер `useModels` (omo ↔ модели); `primary`, `fallback` (AgentRefEditor),
     `validators`/`arbiters` (AgentListEditor), `final` (AgentRefEditor). Сохранение через `api.updateWorkspace`.
  3. **Валидация** — strictness-пресет (`api.configPreset`) + пороги tier1/tier2 + max_revisions.
  4. **Verify** — `verifySource` (agent/manual) + `verifyCommandsOverride` (список команд) + timeout.
  5. **Базовые параметры** — рантайм-ключи (`HEPHAESTUS_MAX_ITER`, таймауты, autopush…) человеческими подписями + help.
- `PromptsView.vue` (`/prompts`, новый) — список шаблонов слева, редактор справа: textarea (моно), список переменных,
  «Сохранить для репо» (PUT) / «Сбросить к глобальному» (DELETE), бейдж «переопределён».
- Router: добавить `/prompts`; nav-ссылки в `AppShell` на `/settings` и `/prompts`.

### 2.4 Подсказки
Короткие RU-пояснения у каждой настройки (что делает, на что влияет): omo vs модели, роли воронки, strictness,
verify-источник, autopush и т.д.

## 3. Тесты и приёмка
- Backend: unit на резолв override (override>global, reset) + contract на ws-prompts API; `ruff`+`mypy --strict app/`+`pytest` зелёные.
- Frontend: vitest на `AgentRefEditor` (omo↔модели поля), `AgentListEditor` (add/remove/fill), `PromptsView`
  (load/save/reset); `vue-tsc`+`build`+`vitest` зелёные.
- Выкатка: деплой на стенд (backend + dist) и локальный запуск на 127.0.0.1.

## 4. Out of scope
- Версионирование/история промптов; диффы; импорт/экспорт настроек; авторизация ролей. (YAGNI)
