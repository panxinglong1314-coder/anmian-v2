# 知眠 - CBT-I AI 睡前焦虑陪伴小程序

> 🛏️ "睡前来聊，把焦虑关在门外"

基于**认知行为疗法-失眠（CBT-I）**的 AI 睡前焦虑陪伴小程序，提供语音+文字双模式，通过 VAD 免手动、关闭仪式、PMR 呼吸引导等干预手段，帮助用户睡前放下焦虑。

---

## 核心功能

### 睡眠模式（默认）
- **VAD 免手动**：开口说话自动开始，停止说话自动结束，无需按键
- **语音 + 文字双模式**：语音识别（腾讯云 ASR）+ 语音播报（MiniMax TTS），麦克风拒绝时自动降级文字模式
- **CBT-I 担忧关闭仪式**：根据焦虑话题（工作/健康/人际/财务/学业）匹配关闭模板
- **PMR 渐进式肌肉放松**：引导用户逐步收紧释放身体各部位
- **呼吸引导**：4-7-8 呼吸法，配合 TTS 语音节奏
- **白噪音**：5 个免费场景（雨声/森林/壁炉/粉噪音/海浪）
- **CBT 认知重构**：识别扭曲思维（灾难化/过度概括/贴标签等）
- **睡前担忧捕获**：结构化记录担忧类型、场景、强度

### 文字模式
- 完整 CBT-I 对话流程：担忧捕获 → 关闭仪式 → 睡眠窗口推荐
- 支持语音输入切换

### 睡眠追踪
- **睡眠日记**：记录入睡时间、起床时间、睡眠质量评分
- **晨间问卷**：TIB（睡眠时机）、起床时间、焦虑评估
- **连续天数 + 7 天焦虑趋势图**
- **睡眠窗口推荐**：根据记录智能推荐最优入睡时间

### 订阅制
- 免费用户：每晚 5 次对话额度
- 付费解锁：全部功能 + 无限对话

### 管理后台
- 仪表盘：活跃用户、会话量、评分分布、夜间使用占比
- 安全监控：危机检测、不当建议告警
- AI 质量评估：对话安全 + 疗效指标
- 用户列表与详情

---

## 技术架构

### 小程序端
| 模块 | 技术 |
|------|------|
| 框架 | 微信原生 WXML/WXSS/JS |
| 语音输入 | VAD 免手动 + 腾讯云 ASR（实时流式） |
| 语音播报 | MiniMax Speech-02-HD + 腾讯云 TTS Fallback |
| 隐私授权 | 微信隐私协议 + 麦克风预检（app.js onLaunch） |

### 后端
| 模块 | 技术 |
|------|------|
| 框架 | FastAPI + uvicorn + Python 3.10 |
| AI 对话 | MiniMax Text（`https://api.minimaxi.com`） |
| TTS | 腾讯云 / MiniMax Speech-02-HD |
| ASR | 腾讯云实时 ASR WebSocket |
| RAG 检索 | **PageIndex**（LLM 推理导航）+ LSA Fallback |
| CBT 语料 | 132 节点层级树（102 叶子），涵盖关闭仪式/担忧场景/PMR/呼吸引导/CBT认知扭曲 |
| 会话存储 | Redis（会话日志 + 睡眠记录 + 用户配额） |
| 对话评估 | LLM 安全检测 + 疗效指标追踪 |
| 缓存 | jieba LSA 向量索引（2576 chunks，dim=128） |
| 部署 | Docker + nginx + systemd（腾讯云 Ubuntu） |

### RAG 架构（PageIndex）

```
用户消息 → PageIndex Engine（MiniMax-M2.7 推理导航）
           ↓ 阅读 30 个非叶节点摘要（LLM 自主决策）
           ↓ 选中 4 个最相关叶节点
           ↓ 格式化注入 system prompt → 千问对话
           
Fallback → LSA TF-IDF（本地计算，< 1s）
```

**与纯向量检索的区别**：传统 RAG 靠字面相似度；PageIndex 让 LLM 理解焦虑等级×失眠亚型×对话阶段后路由到精准 CBT 节点。

---

## 项目结构

```
.
├── backend/                    # FastAPI 后端
│   ├── main.py                 # API 入口（lifespan + 路由注册）
│   ├── rag_engine.py           # RAG 主引擎（PageIndex + LSA）
│   ├── page_index/             # PageIndex RAG 模块
│   │   ├── page_index_tree.py  # 132 节点语料库树 + CorpusTreeBuilder
│   │   └── page_index_engine.py # LLM 推理导航 + LSA fallback
│   ├── hybrid_rag_index.py     # LSA TF-IDF 向量索引
│   ├── cbt_manager.py          # CBT-I 会话状态管理
│   ├── session_logger.py       # Redis 会话日志写入
│   ├── dialogue_evaluator.py   # LLM 安全 + 疗效评估
│   ├── admin_routes.py         # 管理后台 API
│   └── requirements.txt
├── miniprogram/                # 微信小程序
│   ├── app.js                  # 入口（隐私预检 + wxLogin + 会话初始化）
│   ├── pages/
│   │   ├── chat/               # Tab 1：今晚聊聊
│   │   │   ├── chat.js         # VAD + ASR + TTS + CBT 对话流程
│   │   │   ├── chat.wxml       # 语音波形 + 模式切换 + 关闭仪式
│   │   │   └── chat.wxss
│   │   ├── subscribe/          # 订阅页
│   │   ├── morning/            # 晨间问卷
│   │   └── privacy/            # 隐私说明
│   └── js_sdk/
│       └── tencent-asr-realtime/ # 腾讯云 ASR 实时 WebSocket
├── corpus/                     # CBT-I 语料库
│   ├── worry_scenarios.json   # 担忧场景（工作/健康/人际/财务/学业）
│   ├── closure_rituals.json   # 关闭仪式（标准模板 + 15 变体 + 诱导语）
│   ├── pmr_scripts.json       # PMR 渐进式肌肉放松
│   ├── breathing_scripts.json # 呼吸引导（4-7-8 / Box Breathing）
│   ├── cbt_distortions.json  # 认知扭曲识别
│   └── sleep_hygiene.json     # 睡眠卫生教育
├── evaluation_tracking/        # 对话质量追踪数据
├── docs/                        # 设计文档
├── requirements.txt             # Python 依赖
└── docker-compose.yml          # Docker 部署
```

---

## API 概览（v2.1）

### 认证
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/wx_login` | 微信登录换取 JWT |
| GET | `/api/v1/version` | 版本信息 |

### AI 对话（CBT-I）
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat/cbt` | CBT-I 结构化对话 |
| POST | `/api/v1/chat/cbt/stream` | CBT-I 流式对话（SSE） |
| POST | `/api/v1/chat/cbt/reset` | 重置会话 |
| GET | `/api/v1/chat/history` | 获取会话历史 |
| GET | `/api/v1/chat/cbt/state/{user_id}` | 获取 CBT 状态 |
| WS | `/api/v1/chat/ws` | WebSocket 实时对话 |

### 语音
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/asr` | 语音转文字 |
| POST | `/api/v1/asr/stream` | 流式 ASR |
| WS | `/api/v1/asr/ws` | ASR WebSocket |
| POST | `/api/v1/tts` | 文字转语音（mp3） |
| POST | `/api/v1/tts/stream` | 流式 TTS |

### 睡眠追踪
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/sleep/record` | 记录睡眠 |
| GET | `/api/v1/sleep/records/{user_id}` | 获取睡眠记录 |
| POST | `/api/v1/sleep/window` | 设置睡眠窗口 |
| GET | `/api/v1/sleep/window/{user_id}` | 获取睡眠窗口 |
| POST | `/api/v1/morning/submit` | 提交晨间问卷 |
| GET | `/api/v1/morning/check` | 检查晨间问卷 |
| GET | `/api/v1/sleep/diary` | 睡眠日记 |
| POST | `/api/v1/sleep/diary` | 创建日记 |
| GET | `/api/v1/sleep/recommendation/{user_id}` | 睡眠推荐 |

### 担忧管理
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/worry` | 记录担忧 |
| GET | `/api/v1/worries/{user_id}` | 获取担忧列表 |

### 订阅
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/subscription/{user_id}` | 订阅状态 |
| POST | `/api/v1/subscription/activate` | 激活订阅 |

### AI 评估
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/evaluate/session` | 评估会话 |
| GET | `/api/v1/evaluate/recent` | 最近评估 |
| POST | `/api/v1/sessions/{id}/rating` | 用户评分 |
| GET | `/api/v1/sessions/{id}/report` | 会话报告 |

### 管理后台
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/dashboard` | 仪表盘 |
| GET | `/api/v1/admin/safety` | 安全事件 |
| GET | `/api/v1/admin/quality` | AI 质量统计 |
| GET | `/api/v1/admin/users` | 用户列表 |
| GET | `/api/v1/admin/users/{user_id}` | 用户详情 |

### 其他
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/rag/status` | RAG 索引状态 |
| POST | `/api/v1/feedback` | 提交反馈 |
| GET | `/api/v1/breathing/478` | 4-7-8 呼吸引导数据 |
| GET | `/api/v1/sounds` | 白噪音列表 |

---

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `MINIMAX_API_KEY` | ✅ | MiniMax API 密钥 |
| `TENANTCLOUD_APP_ID` | ✅ | 腾讯云 AppID（ASR/TTS） |
| `TENANTCLOUD_SECRET_ID` | ✅ | 腾讯云 SecretID |
| `TENANTCLOUD_SECRET_KEY` | ✅ | 腾讯云 SecretKey |
| `REDIS_HOST` | 否 | Redis 主机（默认 localhost） |
| `REDIS_PASSWORD` | 否 | Redis 密码 |
| `REDIS_ASYNC_URL` | 否 | Redis Async URL |
| `JWT_SECRET` | ✅ | JWT 密钥（生产必改） |
| `ANMIAN_CORPUS_DIR` | 否 | 语料库目录（默认 `../corpus`） |
| `ANMIAN_INDEX_DIR` | 否 | 向量索引目录（默认 `backend/vector_index`） |

---

## 快速开始

### 1. 后端

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# 填写 MINIMAX_API_KEY 等环境变量

# 开发模式
uvicorn main:app --reload --port 8000

# 生产模式（systemd）
sudo systemctl restart anmian
```

### 2. 小程序

1. 打开**微信开发者工具**，导入 `miniprogram` 目录
2. 修改 `app.js` 中的 `apiBaseUrl` 为你的后端地址
3. 填入 AppID：`wx5ce7c0b5a7748df5`
4. 点击"编译"预览

---

## 版本历史

- **v2.1.0** — PageIndex RAG（LLM 推理导航）+ LSA Fallback、API limit 上限校验、管理后台分页、隐私授权零感知
- **v2.0.0** — CBT-I 结构化对话、VAD 免手动、PMR 呼吸引导、订阅系统
- **v1.x** — 基础对话 + TTS/ASR

---

## 许可证

Private - All Rights Reserved
