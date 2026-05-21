# ZhiMian Web (English Web/PWA client)

The English-market web client for ZhiMian — the CBT-I sleep companion.
Talks to the existing FastAPI backend (`/api/v1/chat/cbt/stream` with `locale=en`).

Part of the "知眠英文化" plan, **Workflow D** (Web/PWA first, native app later).

## Stack
- React 18 + Vite 5 + TypeScript
- Tailwind CSS (night palette matching the miniprogram)
- react-i18next (auto-detect browser language, manual toggle, persisted)
- vite-plugin-pwa (installable, offline shell)

## Run

```bash
cd web
npm install
npm run dev          # http://localhost:3000  (proxies /api → https://sleepai.chat)
npm run typecheck    # tsc --noEmit
npm run build        # production bundle → dist/
```

Dev proxy avoids browser CORS: the app calls `/api/...` (same origin), Vite
forwards to the backend (`VITE_API_TARGET`, default `https://sleepai.chat`).
To hit a local backend: `VITE_API_TARGET=http://127.0.0.1:8000 npm run dev`.

## Auth (MVP status)

Login currently accepts a **pasted JWT** (dev preview). Generate one against
the backend `JWT_SECRET` for `user_id` like `em_<id>`.

**Next sub-task:** replace with real auth — email magic-link + Apple + Google.
Requires new backend endpoints:
- `POST /api/v1/auth/email/request` + `/verify`
- `POST /api/v1/auth/oauth/{apple|google}`

## What works now
- English (and Chinese) CBT chat over SSE streaming, locale sent per request
- Crisis banner with US 988 / Crisis Text Line when the backend flags safety
- Optional TTS playback (English voice via backend Edge TTS) — toggle 🔊
- Language toggle (EN ⇄ 中文), persisted to localStorage

## Not yet built (roadmap)
- Real auth (email/Apple/Google) — see above
- Voice **input** (MediaRecorder → WS `/api/v1/asr/ws?locale=en`)
- Sleep diary (`/record`), morning review, worry box, profile pages
- Stripe subscription (free during MVP per product decision)
- PWA icons (`public/icon-192.png`, `icon-512.png`)
