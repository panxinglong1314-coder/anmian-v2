# 知眠 - AI 睡前焦虑陪伴小程序

> 🛏️ **"睡前来聊，把焦虑关在门外"**
>
> 基于 CBT-I（失眠认知行为疗法）的 AI 睡前陪伴，通过语音对话帮用户释放焦虑、安心入睡。

![Version](https://img.shields.io/badge/version-v2.0-blue)
![Platform](https://img.shields.io/badge/platform-WeChat%20Miniprogram-green)
![Framework](https://img.shields.io/badge/backend-FastAPI-purple)

---

## 产品介绍

知眠是一款**AI 睡前陪伴**小程序，核心解决**睡前焦虑导致失眠**的问题。

用户睡前躺在床上，通过语音或文字与 AI 对话，AI 引导完成 CBT-I 五阶段流程：评估 → 担忧捕获 → 认知重构 → 放松诱导 → 关闭仪式。

### 核心功能

| Tab | 功能 |
|-----|------|
| **今晚聊聊** | AI 对话（语音优先）+ 白噪音 5 种 + 关闭仪式（4-7-8 呼吸 + PMR 身体扫描）|
| **我的记录** | 睡眠日记 + Morning Check-in 7 步问卷 + 焦虑趋势图 + 担忧箱 |
| **订阅** | 基础 Pro ¥30/月 · 核心 Pro ¥45/月（微信支付接入中）|

### 差异化定位

- **AI 情感陪伴感** ✗ Sleepio ✗ 绘睡 ✗ 小睡眠：知眠的 AI 陪伴体验在国内竞品中领先
- **语音优先交互**：VAD 语音活动检测，开口说话自动开始，无需手动按键
- **CBT-I 结构化**：完整五阶段状态机，非固定脚本，由 LLM 动态组合话术

---

## 技术架构

### 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│  微信小程序（原生 WXML/WXSS/JS）                              │
│  pages: chat / record / subscribe / train / index / morning  │
└──────────────────────────────────────────────────────────────┘
                              │ HTTPS
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  Nginx (sleepai.chat) — SSL 终结，反向代理                   │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI 后端 — Uvicorn :8000                                │
│  main.py (4220 行)                                          │
│  ├── /api/v1/chat      — AI 对话（含 CBT-I 状态机）          │
│  ├── /api/v1/chat/stream — SSE 流式对话                      │
│  ├── /api/v1/chat/ws  — WebSocket 对话                      │
│  ├── /api/v1/tts       — 文字转语音                          │
│  ├── /api/v1/asr       — 语音转文字                          │
│  ├── /api/v1/sleep/*  — 睡眠日记/窗口                       │
│  ├── /api/v1/worry/*  — 担忧捕获                            │
│  ├── /api/v1/morning/* — 晨间打卡                           │
│  └── /api/v1/subscription/* — 订阅                          │
└──────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────────┐
│  Redis 7                │     │  千问 / MiniMax LLM         │
│  会话历史 / CBT状态      │     │  AI 对话生成                │
│  睡眠记录 / 担忧箱        │     │  TTS / ASR                  │
│  用量限额 / 用户画像      │     │  RAG 向量检索               │
└─────────────────────────┘     └─────────────────────────────┘
```

### 后端模块

| 模块 | 文件 | 行数 | 职责 |
|------|------|------|------|
| API 路由/鉴权/TTS/ASR | `main.py` | 4220 | 核心业务逻辑 |
| CBT-I 状态机 | `cbt_manager.py` | 1779 | 五阶段流转/焦虑检测/阶段自适应 |
| 焦虑等级识别 | `anxiety_detector.py` | 331 | 四级焦虑（正常/轻度/中度/严重）|
| RAG 检索引擎 | `rag_engine.py` | 271 | 11 个语料库向量检索 |
| 向量存储 | `vector_store.py` | 347 | 自研 TF-IDF 索引（无外部 API）|
| 会话日志 | `session_logger.py` | 309 | 训练数据积累，支持导出 |

### 前端模块

| 模块 | 文件 | 行数 | 职责 |
|------|------|------|------|
| 今晚聊聊 | `chat.js` | 2049 | 语音/文字对话/VAD/TTS播放/担忧弹窗/关闭仪式 |
| 我的记录 | `record.js` | 707 | 睡眠日记/仪表盘/焦虑趋势/担忧箱/晨间打卡 |
| 订阅页 | `subscribe.js` | — | 定价 UI/订阅激活 |

### AI 四层进化架构

```
L1 Prompt 层      ✅ 系统指令 + 情绪自适应
L2 RAG 检索层      ✅ 11 个语料库 + 治疗师手记式注入
L3 Fine-tuning    📋 规划中（已具备训练数据导出能力）
L4 RLHF 进化      📋 长期规划
```

---

## CBT-I 五阶段状态机

```
ASSESSMENT → WORRY_CAPTURE → COGNITIVE_RESTRUCTURING 
→ RELAXATION_INDUCTION → CLOSURE
```

| 阶段 | 触发条件 | AI 行为 |
|------|---------|--------|
| `ASSESSMENT` | 初始/每天重置 | 了解今晚心情，评估焦虑等级 |
| `WORRY_CAPTURE` | 检测到担忧意图 | 引导外化担忧，进入"担忧箱" |
| `COGNITIVE_RESTRUCTURING` | 担忧表达后 | 苏格拉底提问重构认知扭曲 |
| `RELAXATION_INDUCTION` | 认知重构后 | 4-7-8 呼吸 / PMR 身体扫描 |
| `CLOSURE` | 放松完成后 | 关闭仪式 + 入睡确认 |

另有 `NORMAL_CHAT`（非 CBT 场景）和 `SAFETY_PROTOCOL`（危机干预）。

---

## 部署架构

### 环境

| 环境 | 地址 | 用途 |
|------|------|------|
| 开发 | `localhost:8000` | 本地调试 |
| 服务器测试 | `124.222.43.248:8000` | `dev-sync.sh` 快速同步 |
| 生产后端 | `https://sleepai.chat` | 正式 API |
| 小程序体验版 | 微信后台 | 团队预览 |
| 小程序正式版 | 微信后台 | 用户访问 |

### 部署方式

| 方式 | 触发 | 说明 |
|------|------|------|
| **GitHub Actions 自动部署** | `git push main`（backend/ 或 workflow 变更）| 自动部署后端 + 上传体验版 |
| **本地 `dev-sync.sh`** | 手动运行 | rsync 快速同步小程序到服务器 |
| **微信开发者工具** | 手动 | 真机调试 |

### 服务器信息

- **IP:** `124.222.43.248`
- **代码路径:** `/home/ubuntu/anmian/`
- **后端:** Uvicorn `:8000`（systemd 管理）
- **Nginx:** 443 HTTPS（Docker 部署）
- **Redis:** Docker 内网访问

### CI/CD 工作流

```
GitHub: panxinglong1314-coder/anmian-v2
├── .github/workflows/deploy-backend.yml     — 后端自动部署
└── .github/workflows/deploy-miniprogram.yml — 小程序体验版上传

服务器: 124.222.43.248
├── Nginx (Docker) — SSL + 反向代理
├── Backend (Docker) — FastAPI + Uvicorn
└── Redis (Docker) — 会话/数据持久化
```

---

## 快速开始

### 后端

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 小程序

1. 打开微信开发者工具，导入 `miniprogram/` 目录
2. 修改 `app.js` 中的 `apiBaseUrl` 为后端地址
3. 填入 AppID: `wx5ce7c0b5a7748df5`
4. 点击"编译"预览

### 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `MINIMAX_API_KEY` | ✅ | 对话 + TTS + ASR |
| `QWEN_API_KEY` | ✅ | AI 对话（千问）|
| `TENCENTCLOUD_APP_ID/SECRET_ID/SECRET_KEY` | ✅ | 腾讯云 TTS/ASR |
| `REDIS_HOST` | 否 | 默认 localhost |
| `REDIS_PASSWORD` | 否 | 默认空 |
| `JWT_SECRET` | ✅ 生产 | 生产环境必须修改 |

---

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/api/v1/chat` | AI 对话（含 CBT-I）|
| POST | `/api/v1/chat/cbt/stream` | SSE 流式对话 |
| WS | `/api/v1/chat/ws` | WebSocket 对话 |
| POST | `/api/v1/tts` | 文字转语音（mp3）|
| POST | `/api/v1/asr` | 语音转文字 |
| WS | `/api/v1/asr/ws` | 实时语音识别 |
| GET | `/api/v1/sounds` | 白噪音场景列表 |
| GET | `/api/v1/sounds/{id}/url` | 白噪音音频 |
| GET/POST | `/api/v1/sleep/window` | TIB 睡眠窗口 |
| POST | `/api/v1/sleep/record` | 创建睡眠记录 |
| GET | `/api/v1/sleep/records/{user_id}` | 历史记录 |
| GET | `/api/v1/sleep/dashboard` | 睡眠仪表盘 |
| POST | `/api/v1/worry` | 捕获担忧 |
| GET | `/api/v1/worries/{user_id}` | 担忧箱列表 |
| PATCH | `/api/v1/worry/{worry_key}` | 更新担忧状态 |
| POST | `/api/v1/morning/submit` | 晨间打卡 |
| GET | `/api/v1/morning/check` | 打卡状态 |
| GET | `/api/v1/subscription/{user_id}` | 订阅状态 |
| POST | `/api/v1/subscription/activate` | 激活订阅 |
| GET | `/api/v1/memory/{user_id}` | 跨会话记忆 |
| GET | `/api/v1/breathing/478` | 4-7-8 呼吸引导数据 |

---

## 目录结构

```
anmian-v2/
├── backend/
│   ├── main.py              # FastAPI 核心（4220 行）
│   ├── cbt_manager.py       # CBT-I 状态机（1779 行）
│   ├── anxiety_detector.py   # 焦虑检测（331 行）
│   ├── rag_engine.py         # RAG 检索（271 行）
│   ├── vector_store.py       # 向量存储（347 行）
│   ├── session_logger.py     # 会话日志（309 行）
│   └── requirements.txt
├── miniprogram/
│   ├── app.js               # 应用入口
│   ├── pages/
│   │   ├── chat/            # 今晚聊聊（语音优先 + CBT-I）
│   │   ├── record/          # 我的记录（睡眠日记 + 仪表盘）
│   │   ├── subscribe/       # 订阅页
│   │   ├── morning/         # 晨间打卡
│   │   └── ...
│   └── sitemap.json
├── corpus/                   # CBT-I 语料库（11 个文件）
│   ├── CBT-I_MANUAL.md      # 核心协议文档
│   ├── cognitive_distortions.json
│   ├── breathing_scripts.json
│   ├── pmr_scripts.json
│   ├── closure_rituals.json
│   └── ...
├── nginx/
│   └── nginx.conf           # Nginx 配置
├── docker-compose.yml        # Docker 编排
├── deploy.sh                 # 部署脚本
└── .github/workflows/       # CI/CD
```

---

## 产品路线图（待完成）

| 优先级 | 功能 | 状态 |
|--------|------|------|
| P0 | 刺激控制提醒（20 分钟计时器接 TIB）| ⚠️ 代码有结构，触发未通 |
| P0 | 订阅微信支付接入 | ⚠️ UI 完成，未接入 |
| P1 | 失眠亚型激活 | ❌ 未做 |
| P1 | CBT-I 会话进度感知（用户知道当前阶段）| ❌ 未做 |
| P1 | 担忧主题周汇总（worry_themes:weekly）| ❌ 未实现 |
| P2 | 睡眠限制完整功能（TIB/SE 动态调整）| ❌ 未做 |
| P2 | 每日睡前推送 + 睡眠日记闭环 | ❌ 不做 |

---

## 相关文档

- [知眠项目架构与进展总览](./知眠/知眠%20项目架构与进展总览.md)（Obsidian）
- [知眠 CI/CD 方案](./知眠%20CI_CD%20方案.md)（Obsidian）
- [知眠代码功能全面评估报告](./知眠/知眠-代码功能全面评估报告.md)（Obsidian）
- [知眠技术架构与API文档](./知眠/AI架构/知眠-技术架构与API文档.md)（Obsidian）
- [前后端同步与部署优化方案](./知眠/前后端同步与部署优化方案.md)（Obsidian）

---

*最后更新：2026-05-10*