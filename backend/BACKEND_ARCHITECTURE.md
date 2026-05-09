# 知眠后端架构文档

> 文档版本：v2.1.0
> 更新日期：2026-05-09

---

## 一、系统架构总览

```
                                    ┌─────────────────┐
  微信小程序 ───── HTTPS ──────────▶│   Nginx 反向代理  │
  (miniprogram)                      │   (sslTermination)│
                                    └──────┬──────────┘
                                           │
                                    ┌──────▼──────────┐
                                    │  uvicorn + FastAPI │
                                    │   后端 (8000)      │
                                    └──┬──────┬──────┬──┘
                                       │      │      │
                               ┌───────▼──┐ ┌▼──────▼───┐
                               │ PageIndex │ │ LSA Index  │
                               │  (RAG)   │ │ (2576chunks)│
                               └──────────┘ └────────────┘
                                       │
                               ┌───────▼──────────┐
                               │  Redis            │
                               │  (会话/睡眠/配额)  │
                               └────────────────────┘
```

### 核心组件

| 组件 | 技术 | 职责 |
|------|------|------|
| **API 网关** | Nginx + SSL | HTTPS 终止，反向代理到 uvicorn |
| **Web 框架** | FastAPI + uvicorn | 异步 HTTP/WS 处理，lifespan 管理 |
| **RAG 引擎** | PageIndex + LSA | CBT-I 语料检索增强生成 |
| **会话存储** | Redis | 会话日志、睡眠记录、用户配额 |
| **AI 对话** | MiniMax Text (`minimaxi.com`) | CBT-I 对话生成 |
| **语音合成** | 腾讯云 TTS / MiniMax TTS | AI 回复语音播报 |
| **语音识别** | 腾讯云 ASR WebSocket | 实时语音转文字 |
| **对话评估** | MiniMax Text | 安全检测 + 疗效评估 |

---

## 二、目录结构

```
backend/
├── main.py                      # FastAPI 入口，lifespan 管理，所有路由注册
├── rag_engine.py                 # RAG 主引擎（PageIndex + LSA）
│
├── page_index/                   # PageIndex LLM 推理导航 RAG
│   ├── __init__.py
│   ├── page_index_tree.py       # PageNode 模型 + CorpusTreeBuilder
│   └── page_index_engine.py     # LLM 导航 + LSA fallback + JSON 解析
│
├── hybrid_rag_index.py           # LSA TF-IDF 向量索引（本地计算）
├── vector_store.py               # 向量存储工具（未使用，兼容旧代码）
├── cbt_manager.py                # CBT-I 会话状态机（担忧捕获→关闭仪式→PMR）
├── session_logger.py             # Redis 会话日志写入
├── dialogue_evaluator.py        # LLM 安全检测 + 疗效评估
├── admin_routes.py               # 管理后台 API（仪表盘/安全/质量/用户）
│
├── requirements.txt
└── .env                          # 环境变量（不上传 git）
```

---

## 三、模块详解

### 3.1 `main.py` — 应用入口

**职责**：
- FastAPI lifespan 管理：Redis 连接池、异步客户端、ASR/TTS 预热
- `init_rag()` 在 lifespan 中调用（启动时加载 RAG 索引）
- 注册所有路由（chat/ASR/TTS/sleep/admin 等）

**关键设计**：
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 连接 Redis
    # 2. 异步 Redis 客户端初始化
    # 3. TTS 预热（Edge TTS 预合成存 Redis）
    # 4. ASR 连接池预热
    # 5. ✅ RAG 索引初始化（PageIndex + LSA）
    init_rag()
    # yield 后执行 shutdown
```

**API limit 校验**（已添加 `Query(le=xxx)`）：
| 端点 | 默认值 | 上限 |
|------|--------|------|
| `GET /feedback/{user_id}` | 20 | 100 |
| `GET /sleep/records/{user_id}` | 7 | 30 |
| `GET /worries/{user_id}` | 20 | 100 |
| `GET /evaluate/recent` | 50 | 200 |
| `GET /training/export` | 500 | 2000 |

**管理后台端点**（5 个，均有 `limit` 参数）：
```
GET /admin/dashboard  → get_dashboard_stats(days, limit=500)
GET /admin/safety     → get_safety_events(days, limit=500)
GET /admin/quality    → get_quality_stats(days, limit=500)
GET /admin/users      → get_user_list(days, limit=500)
GET /admin/users/{id} → get_user_detail(user_id, limit=20)
```

---

### 3.2 `rag_engine.py` — RAG 主引擎

**设计原则**：PageIndex 主检索 + LSA 兜底

```python
# 初始化（init_rag）
def init_rag():
    # 1. 加载 PageIndex 树（从 vector_index/page_tree.json）
    # 2. 若失败，加载 LSA（TF-IDF + TruncatedSVD）
    # 3. 打印就绪状态
```

**检索流程**（`enhance_cbt_response`）：
```
用户消息 + CBT 上下文（焦虑等级/阶段/失眠亚型）
    ↓
PageIndex.navigate(user_msg, ctx=ctx)
    ↓ LLM 阅读 30 个非叶节点摘要，选择 4 个最相关节点
    ↓
_format_page_index_result() → 格式化注入 system prompt
    ↓
PageIndex 结果 + LSA 结果同时返回（去重）
```

**LLM 导航提示词设计**：
```python
SYSTEM_PROMPT = """你是一个 CBT-I 睡眠治疗师。
根据用户消息和焦虑上下文，从以下 30 个非叶节点摘要中选择最相关的节点。
每个非叶节点下辖若干叶节点（实际 CBT 脚本内容）。

输出 JSON（纯 JSON，不要 markdown）：
{"reasoning": "...", "selected_node_ids": ["0001.001", "0002.05.001", ...]}
"""
```

**JSON 解析容错**（MiniMax-M2.7 输出 `<think>` 导致截断）：
```python
def _extract_json(raw: str) -> dict:
    # 1. rfind('"reasoning"') 找 JSON 块起始
    # 2. 括号匹配从该位置向后找匹配的 '}'
    # 3. 截取完整 JSON 返回
```

---

### 3.3 `page_index/` — PageIndex RAG 模块

**`page_index_tree.py`**：
- `PageNode` 数据类：node_id/title/summary/content/parent_id/children
- `CorpusTreeBuilder`：从 JSON 文件构建树，展开目录结构
- `load_tree(cache_path)`：从缓存加载，避免重复构建
- 树结构：132 节点，102 叶子，8 顶级分类

**顶级分类**（8 个）：
| ID | 分类 | 叶节点数 |
|----|------|---------|
| 0001 | 关闭仪式语料 | 4 个子节点 |
| 0002 | 担忧场景语料 | 8 个子节点 |
| 0003 | PMR 渐进式肌肉放松 | 4 个子节点 |
| 0004 | 呼吸引导脚本 | 3 个子节点 |
| 0005 | 认知扭曲识别 | 15 个子节点 |
| 0006 | 睡眠卫生教育 | 0 个（空） |
| 0007 | CBT-I 协议 | 50 个子节点 |
| 0008 | 安心脚本 & 情绪关键词 | 2 个子节点 |

**`page_index_engine.py`**：
- `PageIndexEngine.get_engine()`：单例模式
- `navigate(user_msg, ctx, top_k)`：调用 LLM 导航，返回节点列表
- `_call_minimax(prompt)`：调用 MiniMax-M2.7，temperature=0.1，max_tokens=12000
- LSA fallback：当 PageIndex 不可用或节点不足时调用

**LLM 推理示例**：
```
输入: "我睡不着，总是很担心明天的工作"
Ctx: anxiety_level=7, phase=worry_capture, insomnia_subtype=sleep_onset

LLM 推理:
"用户担心明天工作且焦虑等级7（重度），处于worry_capture阶段。
需选择工作场景担忧节点匹配话题，选用中重度关闭模板和焦虑关闭仪式。"

选中节点: ["0002.05.001", "0001.003.002", "0001.002.003", "0001.001.02", "0001.002.005"]
```

---

### 3.4 `hybrid_rag_index.py` — LSA Fallback

**技术**：jieba 分词 + TF-IDF 向量化 + TruncatedSVD 降维

```python
# 索引配置（支持环境变量覆盖）
CORPUS_DIR = Path(os.environ.get("ANMIAN_CORPUS_DIR", "corpus"))
INDEX_DIR = Path(os.environ.get("ANMIAN_INDEX_DIR", "backend/vector_index"))
```

**索引数据**：
- `lsa_vectors.npy`：形状 `(2576, 128)`，每行是一个 chunk 的向量
- `corpus_chunks.json`：chunk 元数据（source/id/content）
- `vectorizer.pkl`：TF-IDF vectorizer
- `svd_model.pkl`：TruncatedSVD 模型

**检索**：`hybrid_rag.retrieve(query, top_k)` → 返回 top-k 相关 chunk

---

### 3.5 `cbt_manager.py` — CBT-I 会话状态机

**状态流转**：
```
assessment（评估） → worry_capture（担忧捕获） → closure_ritual（关闭仪式）
                                                              ↓
                                                    relaxation（放松引导）
                                                              ↓
                                                    cognitive（认知重构）
                                                              ↓
                                                    sleep_hygiene（睡眠卫生教育）
                                                              ↓
                                                    session_end（会话结束）
```

**核心状态**：
```python
@dataclass
class CBTState:
    user_id: str
    session_id: str
    anxiety_level: int          # 1-10
    phase: str                  # assessment/worry_capture/closure_ritual/...
    insomnia_subtype: str       # sleep_onset/sleep_maintenance/early awakening/mixed
    detected_worry_topic: str  # 工作/健康/人际/财务/学业/其他
    worry_recorded: bool
    closure_completed: bool
    pmr_completed: bool
```

---

### 3.6 `session_logger.py` — Redis 会话日志

**存储结构**：
```
sess_{session_id}.json  # 单会话日志（JSON 文件）
  ├── user_id
  ├── start_time / end_time
  ├── turns[]            # 对话轮次
  │   ├── role / content / timestamp
  │   └── rag_enhanced / anxiety_level
  ├── rating             # 用户评分 1-5
  ├── quality_evaluation  # AI 评估报告
  │   ├── safety / effectiveness / adherence
  │   └── crisis_detected / bad_advice_found
  └── outcome            # 会话结局标签
```

**Redis Key 模式**：
```
user:{user_id}:sleep_list    → List[睡眠记录 JSON]
user:{user_id}:worry_list     → List[担忧记录 JSON]
feedback:{user_id}:{date}     → List[反馈 JSON]
quota:{user_id}:{date}        → Hash[剩余对话次数]
```

---

### 3.7 `dialogue_evaluator.py` — 对话质量评估

**评估维度**：
| 维度 | 说明 |
|------|------|
| `safety` | 危机检测、不当建议、心理伤害风险 |
| `effectiveness` | CBT 技术使用准确度、疗效指标 |
| `adherence` | 用户依从性（是否配合关闭仪式/PMR） |

**评估触发时机**：
- 每轮 AI 回复后（异步，批量）
- 会话结束时（`finalize_session`）
- 用户主动触发（晨间问卷后）

---

## 四、部署架构

### 4.1 生产环境

| 组件 | 配置 |
|------|------|
| 服务器 | 腾讯云 Ubuntu 22.04，2核4G |
| Python | 3.10，venv 隔离 |
| Web 服务 | uvicorn（8 workers，--host 0.0.0.0 --port 8000） |
| 进程管理 | systemd `anmian` service |
| 反向代理 | Nginx（SSL + 负载均衡） |
| 数据库 | Redis（内存存储，会话 + 睡眠记录） |

### 4.2 systemd 服务配置

```ini
[Unit]
Description=知眠 API v2
After=network.target redis.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/anmian/backend
Environment=PATH=/home/ubuntu/venv/bin
ExecStart=/home/ubuntu/venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always

[Install]
WantedBy=multi-user.target
```

**管理命令**：
```bash
sudo systemctl restart anmian   # 重启
sudo systemctl status anmian      # 查看状态
journalctl -u anmian -f          # 查看日志
```

---

## 五、环境变量

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `MINIMAX_API_KEY` | ✅ | - | MiniMax API 密钥 |
| `TENANTCLOUD_APP_ID` | ✅ | - | 腾讯云 AppID |
| `TENANTCLOUD_SECRET_ID` | ✅ | - | 腾讯云 SecretID |
| `TENANTCLOUD_SECRET_KEY` | ✅ | - | 腾讯云 SecretKey |
| `JWT_SECRET` | ✅ | - | JWT 签名密钥 |
| `REDIS_HOST` | 否 | localhost | Redis 主机 |
| `REDIS_PORT` | 否 | 6379 | Redis 端口 |
| `REDIS_PASSWORD` | 否 | - | Redis 密码 |
| `REDIS_DB` | 否 | 0 | Redis DB |
| `REDIS_ASYNC_URL` | 否 | - | Redis Async 连接 URL |
| `ANMIAN_CORPUS_DIR` | 否 | `../corpus` | 语料库目录 |
| `ANMIAN_INDEX_DIR` | 否 | `backend/vector_index` | 向量索引目录 |

---

## 六、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v2.1.0 | 2026-05-09 | PageIndex RAG（LLM 推理导航）接入；API limit 上限校验；管理后台分页；init_rag 启动初始化；隐私授权零感知 |
| v2.0.0 | 2026-05-03 | CBT-I 结构化对话；VAD 免手动；PMR/呼吸引导；订阅系统 |
| v1.x | 早期 | 基础对话 + TTS/ASR |

---

## 七、后续规划

| 规划 | 优先级 | 说明 |
|------|--------|------|
| 财务/学业担忧节点补全 | P0 | 减少"工作"兜底 |
| PageIndex 缓存预热 | P1 | 首次调用从 18s→<1s |
| Prompt 精简 | P1 | tree_repr 从 3000→2000 chars |
| CBT 评估数据集 | P2 | query-expected_nodes 标注集 |