# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**知眠 (ZhiMian / Anmian)** — a WeChat miniprogram for CBT-I (Cognitive Behavioral Therapy for Insomnia) AI companion. Voice-first chat that walks users through 5 phases (assessment → worry capture → cognitive restructuring → relaxation → closure) before sleep, plus a sleep diary tab with sleep restriction therapy (SRT).

Production: `https://sleepai.chat` (Nginx + FastAPI + Redis on `124.222.43.248`).

## Repository layout trap

This repo is wrapped one level deep — the directory most things refer to as "project root" is **`miniprogram/`** (this directory), not the outer `anmian-v2/`. Inside this directory:

```
miniprogram/                          ← cwd / git repo / what README "anmian-v2/" means
├── backend/                          ← FastAPI app (main.py is ~5000 lines)
├── miniprogram/                      ← actual WeChat mini-program source (wxml/wxss/js)
│   ├── app.js                        ← apiBaseUrl = https://sleepai.chat
│   ├── pages/{chat,record,profile,worries,subscribe,morning,…}/
│   └── …
├── corpus/                           ← CBT-I JSON knowledge base (cognitive_distortions,
│                                       breathing_scripts, pmr_scripts, emotion_keywords…)
├── static/                           ← Nginx-served (avatars, white-noise mp3s)
├── scripts/deploy-prod.sh
└── .github/workflows/{test,deploy-backend,deploy-miniprogram}.yml
```

When the README or docs mention "`anmian-v2/backend/`", it means **`miniprogram/backend/`** in this repo.

## Commands

### Backend dev

```bash
# Run locally (uvicorn auto-reload)
cd backend && pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Run all tests (uses fakeredis; no real Redis/LLM required)
cd backend && python -m pytest tests/ -v --tb=short

# Run one test file or test
cd backend && python -m pytest tests/test_cbt_manager.py -v
cd backend && python -m pytest tests/test_emotion_analyzer.py::test_crisis_detection_severe -v

# Syntax check before deploy (no test run)
python3 -c "import ast; ast.parse(open('backend/main.py').read()); print('SYNTAX OK')"
```

### WeChat mini-program

There is no CLI build. Open `miniprogram/` (the inner one) in WeChat 开发者工具 (AppID `wx9e51d39bc9fd64ac`), then Cmd+B to compile. Static URLs in code point at `https://sleepai.chat` so the dev tool talks to production unless you change `app.js` `apiBaseUrl`.

### Deploying backend changes to production

There are two paths:

1. **GitHub Actions** (`.github/workflows/deploy-backend.yml`) — pushes on `main`/`develop` touching `backend/**` run `test.yml` (pytest gate) then SSH-deploy via `appleboy/ssh-action`.
2. **Manual scp + systemctl restart** (what you'll do during interactive iteration):
   ```bash
   # uploads main.py and restarts systemd service `anmian-backend`
   sshpass -e scp backend/main.py ubuntu@124.222.43.248:/tmp/main.py
   sshpass -e ssh ubuntu@124.222.43.248 \
     "cp /tmp/main.py /home/ubuntu/anmian/backend/main.py && \
      echo \$PASSWORD | sudo -S systemctl restart anmian-backend && \
      sleep 3 && sudo systemctl is-active anmian-backend"
   ```
   SSH gets rate-limited after a few connection failures — wait ~30-60s and retry; do not chain short `sleep`s in Bash (the harness blocks that pattern — use `ScheduleWakeup` or `run_in_background` instead).

Server paths: code at `/home/ubuntu/anmian/`, Python venv at `/home/ubuntu/venv/`, static files (Nginx) at `/home/ubuntu/anmian/static/{avatars,sounds}/`, secrets in `/home/ubuntu/anmian/backend/.env`.

### Pre-push hook

`.git/hooks/pre-push` SSHes to the server and runs `pytest tests/` if backend/** changed. Use `git push --no-verify` to skip (only when you've already verified locally).

## High-level architecture

### Request flow

```
WeChat miniprogram → HTTPS → Nginx (sleepai.chat) → uvicorn :8000
                                                       │
                              ┌────────────────────────┤
                              ▼                        ▼
                         Redis (everything)     DeepSeek-chat (LLM)
                                                MiniMax (TTS/ASR fallback)
                                                腾讯云 (streaming TTS/ASR)
```

Auth is JWT (HS256, secret in `.env JWT_SECRET`). Middleware whitelists `/api/v1/auth/wx_login` and `/api/v1/version`; everything else needs `Authorization: Bearer <jwt>`. Initial login: `wx.login()` → backend exchanges `code` for openid via WeChat jscode2session → returns JWT. `user_id = "wx_" + openid[:16]`.

### Conversation flow (today's hot path)

1. Front-end captures speech via WeChat recorder (16kHz mp3) → POST `/api/v1/asr` or streams to `/api/v1/asr/ws` (WebSocket to 腾讯云 ASR)
2. Final transcript → POST `/api/v1/chat/cbt/stream` (SSE) with user message
3. **`cbt_manager.process_message`** is the brain:
   - Loads `SessionState` from Redis (`session_state:{user_id}:{session_id}`)
   - `emotion_analyzer` checks for crisis keywords (5 types × 3 levels) and anxiety score
   - State machine transitions phase (assessment → worry_capture → cognitive_restructuring → relaxation_induction → closure), bails to `_safety_response` on crisis
   - Picks a relaxation technique by anxiety × insomnia subtype × user style × scenario
   - Returns `(template_id, state_update, _meta)` and the LLM prompt is built from the template + corpus snippets injected via RAG
4. `deepseek_chat(messages, stream=True)` streams tokens back over SSE
5. Front-end chunks accumulated text every `MIN_TTS_CHARS=6` chars or `MAX_TTS_WAIT_MS=400`ms → POST `/api/v1/tts/stream` → plays audio chunks via `_ttsStreamQueue` (separate `InnerAudioContext` from white noise)

### CBT-I state machine (`backend/cbt_manager.py`)

Phases live as `SessionPhase` enum. Transitions are deterministic in code, not LLM-driven. Each phase has a `_xxx_response` method that updates state and returns a template id; LLM only fills the template. **The state machine is the safety boundary** — adding new phases requires updating Redis (de)serialization (`_save_state`/`_load_state` at lines ~1382/1405) and the transition table.

Personalization: `user:profile:{user_id}` carries `avg_anxiety_recovery_turns` to dynamically pick relaxation threshold (default 4 turns, range 2-6 based on user history).

### Worry capture (`POST /api/v1/worry`)

Two-stage classification: **fallback regex returns immediately** (type ∈ {vent, action, ruminate}, domain ∈ 8 categories), then `BackgroundTasks` queues `_classify_worry_async` which calls DeepSeek to upgrade type+domain and rewrites both `worry:{user_id}:{ts}` and the corresponding entry in `worry_list:{user_id}` (Redis pipeline for atomicity). Crisis content is intercepted via `_detect_crisis` → `emit_crisis_alert` (writes to `crisis_alerts:pending` zset) and **not** stored as a normal worry — frontend gets `status: "crisis"` + hotlines. 24h dedup by exact-text match in last 30 list entries.

### Data conventions to watch

- **SE (sleep efficiency)** is stored as a fraction `0-1` (e.g. `0.85`) in `sleep_diary:{user_id}:{date}`, but compared to thresholds as percentage (`SE_OPTIMIZING=90`, `SE_STABLE=85`) and displayed with `%` suffix in WXML. **Always multiply by 100 at read sites** before comparing or returning to frontend (this was a system-wide bug; see commits touching `srt_engine.py` and `sleep_dashboard`).
- **WeChat WXSS does not support `:root`** for CSS variables — use `page` selector. `app.wxss` defines `--text-primary` etc. on `page`. When in doubt, also inline literal colors as fallback (see `chat.wxss`).
- **Worry record schema** evolved: `type` and `domain` were added late. Records older than commit 1523881 won't have these fields; consumer code must default-handle missing.
- **streak_days vs diary_streak_days**: `streak_days` = consecutive app opens (counts even without logging anything), `diary_streak_days` = consecutive sleep-diary fills. The "睡眠窗口" card uses the latter; "连续使用" stat card uses the former. Don't conflate.

### LLM call gotcha

`deepseek_chat(messages, stream)` is an `AsyncGenerator`. With `stream=True` it parses SSE `data:` lines; **with `stream=False` it returns nothing** because the SSE parser still iterates `aiter_lines()` and skips non-data lines. Always pass `stream=True` even for one-shot classification calls.

### WeChat platform constraints worth knowing

- `<button open-type="chooseAvatar">` — only way to get the user's WeChat avatar (programmatic `wx.getUserProfile` is deprecated since 2022).
- `<button open-type="getPhoneNumber">` — **enterprise accounts only**. This repo's appid is an individual account, so phone number must be collected as free-form input (see "紧急联系人" pattern in `pages/profile`).
- `<button open-type="share">` — only `button` can trigger share-to-friend directly; `<view bindtap>` cannot.
- Page navigation bar title comes from `<page>.json navigationBarTitleText`. Do not also draw a custom nav-bar inside the page (results in duplicate titles, see profile.wxml).
- `wx.createInnerAudioContext` shared between TTS and white noise will fight; the chat page uses a separate `_currentTTSCtx` for TTS streaming.
- **WXML `{{}}` expressions are NOT JavaScript** — no property access like `text.length`, no function calls like `Math.max()`. Compute in JS, store on `data`, bind the result. (Compile error: "Bad value with message: unexpected token `.`")
- **All authenticated API calls must use `app.authRequest`** — it injects `Authorization: Bearer <jwt>`. Raw `wx.request` to protected endpoints returns 401. The only paths that don't need auth are `/api/v1/auth/wx_login` and `/api/v1/version`. (Profile/chat/record/morning/subscribe pages have already been corrected; check any new page you add.)
- **`app.globalData` keys**: `userId`, `apiBaseUrl`, `sessionId`. **There is no `baseUrl` or `token` field** — token lives in `wx.getStorageSync('jwt_token')`, accessed via `app.getToken()`. The string `app.globalData.token` is always undefined.

### Tests

`backend/tests/` uses `fakeredis` (`conftest.py` provides a `fake_redis` fixture) and a real `corpus/emotion_keywords.json`. Tests are unit-level — they don't hit the network or real LLM. When adding new endpoints, **don't add tests that require real DeepSeek/MiniMax/腾讯云 keys**; use mocks or skip.

### Big files to navigate carefully

| File | Lines | Notes |
|---|---|---|
| `backend/main.py` | 5500+ | All routes + middleware + LLM glue. Imports at line 5489 are module-level but **AFTER** many endpoint definitions — when adding a function from `services.crisis_alert`, verify it's in the explicit `from … import (…)` list at that line. |
| `backend/cbt_manager.py` | 1800+ | The state machine. Don't change phase logic without updating `_save_state` / `_load_state` serialization. |
| `miniprogram/miniprogram/pages/chat/chat.js` | 2700+ | Lots of audio context juggling. Modifying `_ttsStreamQueue` or `_currentTTSCtx` lifecycle has high regression risk. |

### Obsidian docs (off-repo)

Project author keeps engineering notes at `~/Documents/Obsidian Vault/知眠/`. When a task asks to "save to Obsidian" or references SOP docs, that's the location. Don't try to git-track those files.
