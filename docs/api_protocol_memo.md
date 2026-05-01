# 前后端 API 协议与参数格式技术备忘录

## 一、流式协议：SSE vs WebSocket

### 1.1 后端同时支持两种协议（复用同一核心逻辑）

```
┌─────────────────┐     ┌─────────────────┐
│  POST /api/v1/  │     │   WS /api/v1/   │
│  chat/cbt/stream│     │     chat/ws     │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
    ┌─────────────────────────────────┐
    │     async def _chat_events()    │  ← 第1472行，同一套生成器
    │        (核心CBT流式逻辑)          │
    └─────────────────────────────────┘
```

| 维度 | SSE 端点 | WebSocket 端点 |
|------|---------|---------------|
| **路径** | `POST /api/v1/chat/cbt/stream` | `WS /api/v1/chat/ws` |
| **协议** | HTTP + Server-Sent Events | WebSocket |
| **输出格式** | `data: {json}\n\n` | `JSON` |
| **前端接收** | `wx.request` + `enableChunked` | `wx.connectSocket` |
| **核心逻辑** | 调用 `_chat_events(req)` | 调用 `_chat_events(req)` |

### 1.2 两种协议的输出事件完全一致

`_chat_events()` 生成的事件序列（按顺序）：

```
1. {"event": "llm_token", "data": "..."}      ← 逐字流式输出
2. {"event": "cbt_state", "data": {...}}       ← CBT状态对象
3. {"event": "tts_audio", "audio_base64": "..."} ← 特殊响应时直接TTS
4. {"event": "final", "content": "...", "should_close": bool}
5. {"event": "done", "has_tts": bool}
```

### 1.3 微信小程序端建议

| 方案 | 优点 | 缺点 |
|------|------|------|
| **SSE（推荐）** | 基于HTTP，域名配置简单；支持重连；微信兼容性更好 | `enableChunked` 在部分基础库有已知问题 |
| **WebSocket** | 真机流式体验更丝滑；双向通信灵活 | 需额外配置wss域名；微信有连接数限制；需处理心跳重连 |

**建议：统一使用 SSE**，因为：
- 后端两套逻辑完全等价，无功能差异
- SSE 基于标准 HTTP，域名配置、调试、监控都更简单
- WebSocket 在微信小程序中有 `wss://` 域名白名单要求，且需要处理心跳/重连

---

## 二、TTS speed 参数：-1 vs 90

### 2.1 后端兼容逻辑（main.py 第1851行）

```python
# speed 处理：前端传 50-200（流式API语义），同步API用 -2~6
effective_speed = max(-2, min(6, int(speed / 100) - 1)) if speed > 10 else int(speed)
```

### 2.2 参数映射表

| 前端传入值 | 计算过程 | effective_speed | 腾讯TTS语义 | 实际效果 |
|-----------|---------|-----------------|------------|---------|
| `-1` | `<=10` → `int(-1)` | **-1** | 稍慢 | ✅ 正常语速90% |
| `90` | `>10` → `int(90/100)-1 = -1` | **-1** | 稍慢 | ✅ 正常语速90% |
| `-2` | `<=10` → `int(-2)` | **-2** | 慢速 | 更慢 |
| `80` | `>10` → `int(80/100)-1 = -1` | **-1** | 稍慢 | 正常语速90% |
| `0` | `<=10` → `int(0)` | **0** | 正常 | 标准语速 |
| `100` | `>10` → `int(100/100)-1 = 0` | **0** | 正常 | 标准语速 |

### 2.3 结论：-1 和 90 效果完全相同

- **传 `-1`**：后端走 `speed <= 10` 分支，直接 `int(-1) = -1`
- **传 `90`**：后端走 `speed > 10` 分支，`int(90/100) - 1 = 0 - 1 = -1`

**两者最终都映射到腾讯 TTS 的 `-1`（稍慢，约正常语速的90%）**

### 2.4 建议统一格式

| 格式 | 语义 | 建议 |
|------|------|------|
| **`-1`** | 腾讯TTS原生枚举值 | ❌ 语义不够直观 |
| **`90`** | 百分比（90% = 正常语速的90%） | ✅ 推荐，语义清晰 |

**统一建议：前端统一传 `90`**（百分比语义，与 CBT 流式 API 设计一致）

---

## 三、CBTManager 内部 TTS 参数来源

CBT 状态中的 `tts_params.speed` 由 `cbt_manager.py` 根据焦虑等级动态决定：

```python
# cbt_manager.py 第378-394行
AnxietyLevel.SEVERE:   speed=-2  # 严重焦虑 → 更慢更温和
AnxietyLevel.MODERATE: speed=-2  # 中度焦虑 → 更慢更温和
AnxietyLevel.MILD:     speed=-1  # 轻度焦虑 → 稍慢
AnxietyLevel.NORMAL:   speed=-1  # 正常 → 稍慢

"breathing":  speed=-2   # 呼吸指导 → 慢速
"pmr":        speed=-2   # 渐进放松 → 慢速
"closure":    speed=-2   # 结束语 → 慢速
"normal":     speed=0    # 普通对话 → 正常
"llm_stream": speed=0    # 流式LLM → 正常
```

**注意**：CBTManager 输出的 speed 是 **枚举值**（-2, -1, 0），通过 `tts_params` 传递到 `_chat_events`。如果后续 CBTManager 改成输出百分比格式（如 80, 90, 100），后端无需修改（因为兼容逻辑已存在）。

---

## 四、统一决策建议

| 项目 | 当前状态 | 建议统一为 |
|------|---------|-----------|
| **流式协议** | 本地用 WS，服务器用 SSE | **统一 SSE** |
| **TTS speed** | 本地传 -1，服务器传 90 | **统一传 90** |
| **录音格式** | 本地 MP3，服务器 PCM | **统一 PCM**（腾讯云ASR偏好） |
| **VAD超时** | 本地 3500ms，服务器 3000ms | **统一 3000ms** |
| **陪伴静默** | 本地 20s，服务器 3min | **统一 3min** |

---

## 五、双向同步清单

| 功能 | 本地独有 | 服务器独有 |
|------|---------|-----------|
| 页面 | `pages/privacy/` 隐私政策 | `pages/morning/` 晨间打卡 |
| 页面 | `pages/profile/` 个人中心 | — |
| 登录 | `wxLogin()` + JWT Token | — |
| 隐私合规 | `needShowPrivacy` + `agreePrivacy()` | — |

**下一步行动**：
1. ✅ 确认后端 SSE + TTS speed=90 兼容性（已完成）
2. ⏳ 将本地 chat.js 改为 SSE 协议
3. ⏳ 将本地 chat.js TTS speed 改为 90
4. ⏳ 将本地 `pages/morning/` 同步到本地
5. ⏳ 将服务器 `pages/privacy/` + `pages/profile/` 同步到服务器
