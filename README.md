# 睡前大脑关机助手 - 微信小程序 v2

> 🛏️ "睡前来聊，把焦虑关在门外"

基于 CBT 的 AI 睡前焦虑陪伴小程序，接 MiniMax 全家桶（chat + TTS + ASR）。

---

## 新增功能（v2）

- **MiniMax 真实 AI 对话** — 跨天记忆用户担忧关键词
- **MiniMax TTS** — 文字转语音，自动播放 AI 回复
- **MiniMax ASR** — 语音转文字，真正语音输入
- **白噪音** — 5 个免费场景（雨声/森林/壁炉/粉噪音/海浪）
- **跨会话记忆** — Redis 存储，AI 记住你近日常担忧

---

## 功能概览

- **Tab 1：今晚聊聊** — AI 对话，VAD 免手动，真实 TTS/ASR，关闭仪式
- **Tab 2：我的记录** — 连续天数 + 焦虑趋势

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 小程序 | 原生 WXML/WXSS/JS |
| 后端 | FastAPI + uvicorn |
| AI 对话 | MiniMax-Text-01 |
| TTS | MiniMax Speech-02-HD |
| ASR | MiniMax Whisper-large |
| 缓存/存储 | Redis |
| 部署 | Docker + Docker Compose |

---

## 快速开始

### 1. 配置环境变量

```bash
cd code/backend
cp .env.example .env
# 填写以下三个值：
#   MINIMAX_API_KEY=你的API密钥
#   MINIMAX_GROUP_ID=你的GroupID
#   MINIMAX_SECRET_ID=你的SecretID
```

### 2. 启动后端

```bash
cd code/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 3. 小程序开发

1. 打开微信开发者工具，导入 `miniprogram` 目录
2. 修改 `app.js` 中的 `apiBaseUrl` 为你的后端地址（如 `http://localhost:8000`）
3. 填入 AppID: `wx5ce7c0b5a7748df5`
4. 点击"编译"即可预览

---

## API 端点（v2）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| **POST** | `/api/v1/chat` | AI 对话（含焦虑检测+记忆） |
| POST | `/api/v1/chat/stream` | 流式对话（SSE） |
| **POST** | `/api/v1/tts` | 文字转语音（返回 mp3） |
| **POST** | `/api/v1/asr` | 语音转文字（支持 mp3/wav） |
| GET | `/api/v1/breathing/478` | 呼吸引导数据 |
| GET | `/api/v1/sounds` | 白噪音场景列表 |
| GET | `/api/v1/sounds/{id}/url` | 白噪音音频直链 |
| POST | `/api/v1/sleep/record` | 创建睡眠记录 |
| GET | `/api/v1/sleep/records/{user_id}` | 获取睡眠记录 |
| GET | `/api/v1/memory/{user_id}` | 获取用户跨会话记忆 |

---

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `MINIMAX_API_KEY` | ✅ | MiniMax API 密钥（对话 + TTS + ASR） |
| `MINIMAX_GROUP_ID` | ✅ | MiniMax GroupID（TTS/ASR 签名用） |
| `MINIMAX_SECRET_ID` | ✅ | MiniMax SecretID（TTS/ASR 签名用） |
| `REDIS_HOST` | 否 | Redis 主机，默认 localhost |
| `REDIS_PASSWORD` | 否 | Redis 密码 |
| `JWT_SECRET` | 是 | JWT 密钥（生产环境必须修改）|

---

## 产品结构（简化版）

```
睡前大脑关机
├── Tab 1: 今晚聊聊
│   ├── 睡眠模式（默认）
│   │   ├── VAD 语音活动检测（开口说话自动开始）
│   │   ├── MiniMax ASR → AI 回复 → MiniMax TTS 自动播放
│   │   ├── 白噪音（5个场景，呼吸引导前铺垫）
│   │   └── 关闭仪式 → 呼吸引导（步骤1）→ 入睡确认（步骤2）
│   └── 文字模式（辅助切换）
│
└── Tab 2: 我的记录
    ├── 连续使用天数
    ├── 本周对话次数
    └── 7天焦虑趋势柱状图
```

---

## 开发进度

- [x] PRD 文档
- [x] UI 设计稿
- [x] AI 对话系统设计
- [x] 焦虑检测算法（简化版）
- [x] MiniMax 全家桶接入（chat + TTS + ASR）
- [x] 跨会话用户记忆
- [x] 白噪音场景（5个）
- [x] 小程序核心页面（简化版）
- [ ] 服务器部署
- [ ] 小程序审核上线
- [ ] 种子用户内测
# CI/CD Test Trigger
