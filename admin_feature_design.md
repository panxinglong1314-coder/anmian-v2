# 知眠 Admin 后台功能扩展设计

> 版本: 2026-05-15 v1
> 涵盖: 睡眠数据大盘、敏感内容实时告警、AI 质量自动纠偏、RAG 知识库版本管理、A/B 测试配置面板

---

## 一、用户睡眠数据大盘

### 1.1 目标
聚合 `sleep:diary:{uid}:{date}` + `morning:{uid}:{date}` + `sleep_window:{uid}` + `sleep_baseline:{uid}`，在 Admin 后台展示 CBT-I 核心疗效指标。

### 1.2 后端 API

```python
# backend/admin_routes.py

def get_sleep_dashboard(days: int = 30) -> dict:
    """
    返回平台级睡眠数据大盘
    - 扫描 Redis sleep:diary:* + morning:* 键
    - 按天聚合平均 SE / TST / TIB / sleep_quality
    - 统计各 SRT 阶段用户占比
    - 识别"高风险用户"（连续3天 SE < 60% 或 sleep_quality = 1）
    """
    pass
```

**端点:** `GET /api/v1/admin/sleep_dashboard?days=30`

**响应结构:**
```json
{
  "period_days": 30,
  "summary": {
    "total_users_with_records": 45,
    "avg_se": 78.5,
    "avg_tst_hours": 5.8,
    "avg_tib_hours": 7.2,
    "avg_sleep_quality": 2.8
  },
  "phase_distribution": {
    "learning": 12,
    "restricting": 18,
    "stable": 8,
    "optimizing": 5,
    "maintenance": 2
  },
  "daily_trend": [
    {"date": "2026-05-01", "avg_se": 76.0, "avg_tst_hours": 5.5, "record_count": 23}
  ],
  "high_risk_users": [
    {
      "user_id": "wx_xxx",
      "risk_reason": "连续3天 SE < 60%",
      "latest_se": 52,
      "latest_sleep_quality": 1,
      "days_since_last_record": 1
    }
  ],
  "srt_effectiveness": {
    "users_improved_se": 15,
    "users_worsened_se": 3,
    "users_no_change": 8,
    "improvement_rate": "55%"
  }
}
```

### 1.3 数据扫描策略

```python
def _scan_sleep_records(days: int = 30) -> List[dict]:
    """
    扫描策略：
    1. 遍历 sleep:diary:* 键（主数据源，结构化程度最高）
    2. 遍历 morning:* 键（fallback，仅当 sleep_diary 不存在时补充）
    3. 按 user_id 分组，取最近 days 天的记录
    """
    r = _get_redis()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    records = []
    
    # 主数据源
    for key in r.scan_iter(match="sleep:diary:*", count=100):
        uid, date = _extract_user_date_from_key(key, "sleep:diary")
        if date >= cutoff:
            data = r.get(key)
            if data:
                rec = json.loads(data)
                rec["source"] = "diary"
                rec["user_id"] = uid
                records.append(rec)
    
    # Fallback
    for key in r.scan_iter(match="morning:*", count=100):
        uid, date = _extract_user_date_from_key(key, "morning")
        if date >= cutoff:
            # 检查是否已有 diary 数据
            diary_key = f"sleep:diary:{uid}:{date}"
            if not r.exists(diary_key):
                data = r.get(key)
                if data:
                    rec = json.loads(data)
                    rec["source"] = "morning"
                    rec["user_id"] = uid
                    records.append(rec)
    return records
```

### 1.4 前端展示

新增导航项 **"睡眠大盘"**，页面布局：

| 区域 | 内容 |
|---|---|
| 顶部卡片 | 总记录用户 / 平均 SE / 平均 TST / 平均睡眠质量 |
| 左上图 | 近30天 SE 趋势线（ECharts 折线图） |
| 右上图 | SRT 阶段分布饼图 |
| 左下图 | TST vs TIB 对比柱状图 |
| 右下图 | 高风险用户列表（可跳转用户详情） |

---

## 二、敏感内容实时告警

### 2.1 目标
在 `ApiStatsMiddleware` 中增加轻量级关键词检测，对聊天内容实时扫描，比现有的 `crisis_alert` 更早发现风险信号。

### 2.2 设计原则
- **不能影响 API 性能**：异步检测，不阻塞响应
- **低误报**：只匹配高置信度关键词，不调用 LLM
- **可配置**：后台可增删关键词和触发阈值

### 2.3 实现

```python
# backend/services/realtime_alert.py

SENSITIVE_KEYWORDS = {
    "suicide_high": ["不想活了", "想死", "自杀", "结束生命", "没意义了"],
    "suicide_medium": ["活着没意思", "痛苦得想死", "不想面对明天"],
    "self_harm": ["割腕", "自残", "伤害自己", "想流血"],
    "violence": ["想杀人", "想报复", "同归于尽"],
}

WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")

async def scan_sensitive_content(user_id: str, message: str, session_id: str):
    """异步扫描，不阻塞主流程"""
    if not WEBHOOK_URL:
        return
    
    found_keywords = []
    risk_level = "low"
    
    for category, keywords in SENSITIVE_KEYWORDS.items():
        for kw in keywords:
            if kw in message:
                found_keywords.append({"category": category, "keyword": kw})
                if category.endswith("_high"):
                    risk_level = "high"
                elif risk_level == "low":
                    risk_level = "medium"
    
    if found_keywords:
        payload = {
            "type": "realtime_sensitive",
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "session_id": session_id,
            "risk_level": risk_level,
            "matched_keywords": found_keywords,
            "message_preview": message[:100] + "..." if len(message) > 100 else message,
        }
        asyncio.create_task(_send_webhook(payload))

def _send_webhook(payload: dict):
    try:
        httpx.post(WEBHOOK_URL, json=payload, timeout=5)
    except Exception:
        pass
```

在 `ApiStatsMiddleware` 中集成（仅聊天接口）：

```python
class ApiStatsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # ... 现有统计代码 ...
        
        # 敏感内容实时检测（仅聊天接口，异步不阻塞）
        if "/chat" in path and request.method == "POST":
            try:
                body = await request.body()
                data = json.loads(body)
                message = data.get("message", "")
                user_id = data.get("user_id", "")
                session_id = data.get("session_id", "")
                if message and user_id:
                    asyncio.create_task(
                        scan_sensitive_content(user_id, message, session_id)
                    )
            except Exception:
                pass
        
        response = await call_next(request)
        # ... 现有统计代码 ...
```

### 2.4 Admin 配置面板

新增 **"实时告警配置"** 卡片：

```json
// GET /api/v1/admin/alert_config
{
  "webhook_url": "https://hooks.slack.com/xxx",
  "keywords": {
    "suicide_high": ["不想活了", "想死", "自杀"],
    "suicide_medium": ["活着没意思", "痛苦得想死"],
    "self_harm": ["割腕", "自残"]
  },
  "enabled": true
}

// POST /api/v1/admin/alert_config
{
  "webhook_url": "...",
  "keywords": {...},
  "enabled": true
}
```

存储位置：`admin:alert_config` (Redis string, JSON)

---

## 三、AI 质量自动纠偏

### 3.1 目标
当 `evaluation_tracker` 检测到低质量会话时，自动将数据和改进建议推送到外部队列（如 LLM 微调平台、企业微信），降低人工复核成本。

### 3.2 触发条件

```python
# backend/services/quality_auto_remedy.py

REMEDY_RULES = [
    {
        "id": "low_empathy",
        "condition": lambda r: r.get("auto_empathy", 5) < 3,
        "severity": "high",
        "suggestion": "共情评分低，建议增加情绪确认和接纳语句",
        "action": "push_to_review_queue"
    },
    {
        "id": "technical_bias",
        "condition": lambda r: abs(r.get("bias_technical", 0)) > 0.3,
        "severity": "high",
        "suggestion": "LLM 与自动评估偏差大，可能存在不当睡眠建议",
        "action": "push_to_review_queue"
    },
    {
        "id": "coherence_drop",
        "condition": lambda r: r.get("auto_coherence", 5) < 3,
        "severity": "medium",
        "suggestion": "对话连贯性差，建议检查上下文记忆机制",
        "action": "log_only"
    },
]
```

### 3.3 实现

在 `evaluation_tracker.py` 的 `record_session_evaluation()` 中，保存记录后触发检测：

```python
def record_session_evaluation(session_id, auto_report, user_id=None, llm_report=None):
    # ... 现有保存逻辑 ...
    
    # 自动纠偏检测
    for rule in REMEDY_RULES:
        if rule["condition"](entry):
            _trigger_remedy(rule, entry, session_id)
    
    return entry

def _trigger_remedy(rule: dict, entry: dict, session_id: str):
    remedy_record = {
        "timestamp": datetime.now().isoformat(),
        "rule_id": rule["id"],
        "severity": rule["severity"],
        "suggestion": rule["suggestion"],
        "session_id": session_id,
        "auto_report": entry,
        "status": "pending",  # pending | reviewed | resolved
    }
    
    # 1. 写入 Redis 纠偏队列
    r = _redis()
    r.lpush("quality:remedy:pending", json.dumps(remedy_record, ensure_ascii=False))
    
    # 2. 推送到 Webhook（如果配置了）
    webhook = os.getenv("QUALITY_REMEDY_WEBHOOK", "")
    if webhook:
        try:
            httpx.post(webhook, json=remedy_record, timeout=5)
        except Exception:
            pass
    
    # 3. 写入审计日志
    log_admin_action("quality_remedy_triggered", "system", {
        "rule_id": rule["id"],
        "session_id": session_id,
        "severity": rule["severity"]
    })
```

### 3.4 Admin 展示

新增 **"AI 纠偏队列"** 页面：

| 字段 | 说明 |
|---|---|
| 时间 | 触发时间 |
| 规则 | low_empathy / technical_bias / coherence_drop |
| 严重程度 | high / medium |
| 会话ID | 可点击跳转详情 |
| 自动评分 | 共情/技术/连贯性 |
| 改进建议 | 系统生成的建议 |
| 状态 | pending → reviewed → resolved |
| 操作 | 标记已处理 / 忽略 / 查看会话 |

**API:**
```python
# GET /api/v1/admin/quality/remedies?status=pending&limit=50
# POST /api/v1/admin/quality/remedies/{id}/resolve  { "note": "已人工复核" }
# POST /api/v1/admin/quality/remedies/{id}/ignore
```

---

## 四、RAG 知识库版本管理

### 4.1 目标
后台支持上传/替换/回滚睡眠医学知识库 PDF，自动重建向量索引，记录每次变更历史。

### 4.2 当前架构分析

现有 RAG 实现（从代码推断）：
- 向量索引存储在 `backend/vector_index/page_tree.json`
- 构建函数在 `rag_engine.py` 中：`build_rag_index()` / `init_rag()`
- 知识来源可能是本地 Markdown/PDF 文件

### 4.3 设计

```python
# backend/services/kb_version_manager.py

KB_DIR = Path(__file__).parent.parent / "knowledge_base"
INDEX_DIR = Path(__file__).parent.parent / "vector_index"
VERSION_FILE = KB_DIR / "versions.json"

def list_kb_versions() -> List[dict]:
    """列出所有知识库版本"""
    if not VERSION_FILE.exists():
        return []
    with open(VERSION_FILE) as f:
        return json.load(f)

def upload_kb_pdf(file_bytes: bytes, filename: str, uploader: str) -> dict:
    """
    1. 保存 PDF 到 knowledge_base/versions/{timestamp}_{filename}
    2. 解析 PDF 文本
    3. 调用 rag_engine.build_rag_index() 重建索引
    4. 记录版本信息
    5. 自动备份旧索引
    """
    version_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    version_dir = KB_DIR / "versions" / version_id
    version_dir.mkdir(parents=True, exist_ok=True)
    
    pdf_path = version_dir / filename
    with open(pdf_path, "wb") as f:
        f.write(file_bytes)
    
    # 解析 PDF（使用 PyPDF2 或 pdfplumber）
    text = _extract_pdf_text(pdf_path)
    chunks = _chunk_text(text)
    
    # 备份旧索引
    if (INDEX_DIR / "page_tree.json").exists():
        backup_dir = INDEX_DIR / "backups" / version_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(INDEX_DIR / "page_tree.json", backup_dir / "page_tree.json")
    
    # 重建索引（调用现有 RAG 引擎）
    from rag_engine import build_rag_index
    build_rag_index(source_dir=version_dir, output_dir=INDEX_DIR)
    
    # 记录版本
    versions = list_kb_versions()
    versions.insert(0, {
        "id": version_id,
        "filename": filename,
        "uploader": uploader,
        "uploaded_at": datetime.now().isoformat(),
        "chunk_count": len(chunks),
        "status": "active"
    })
    with open(VERSION_FILE, "w") as f:
        json.dump(versions[:20], f, ensure_ascii=False, indent=2)  # 保留最近20个版本
    
    return {"version_id": version_id, "chunk_count": len(chunks)}

def rollback_kb_version(version_id: str) -> dict:
    """回滚到指定版本的索引"""
    backup_path = INDEX_DIR / "backups" / version_id / "page_tree.json"
    if not backup_path.exists():
        return {"error": "版本备份不存在"}
    
    shutil.copy(backup_path, INDEX_DIR / "page_tree.json")
    
    # 更新版本状态
    versions = list_kb_versions()
    for v in versions:
        v["status"] = "archived"
    for v in versions:
        if v["id"] == version_id:
            v["status"] = "active"
    with open(VERSION_FILE, "w") as f:
        json.dump(versions, f, ensure_ascii=False, indent=2)
    
    # 重新加载 RAG 索引
    from rag_engine import init_rag
    init_rag()
    
    return {"success": True, "rolled_back_to": version_id}
```

### 4.4 Admin 前端

新增 **"知识库管理"** 页面：

| 功能 | 交互 |
|---|---|
| 上传 PDF | `<input type="file" accept=".pdf">` + 进度条 |
| 版本列表 | 表格：版本ID / 文件名 / 上传人 / 分片数 / 状态 / 操作 |
| 回滚 | 点击"回滚"按钮，确认后调用 API，成功后刷新索引 |
| 当前索引信息 | 显示当前索引的文档数、向量维度、最后更新时间 |

**API:**
```python
# GET /api/v1/admin/kb/versions
# POST /api/v1/admin/kb/upload  (multipart/form-data, file)
# POST /api/v1/admin/kb/rollback/{version_id}
# GET /api/v1/admin/kb/current  (返回当前索引元数据)
```

---

## 五、A/B 测试配置面板

### 5.1 目标
让运营/医学顾问能在后台直接调整 SRT 阈值、系统 Prompt、TTS 参数等，无需发版。

### 5.2 可配置项设计

```python
# backend/services/ab_config.py

AB_CONFIG_KEY = "admin:ab_config"
AB_CONFIG_DEFAULTS = {
    # SRT 阈值
    "srt": {
        "se_optimizing": 90,
        "se_stable": 85,
        "min_tib_hours": 4,
        "max_tib_hours": 8.5,
        "buffer_minutes": 30,
        "expansion_minutes": 15,
    },
    # CBT 系统 Prompt
    "prompt": {
        "system_prompt": None,  # None = 使用默认 CBT_SYSTEM_PROMPT
        "enable_rag": True,
        "max_context_turns": 10,
        "anxiety_detection_enabled": True,
    },
    # TTS 参数
    "tts": {
        "default_voice": "female_warm",
        "default_speed": 0.9,
        "max_text_length": 500,
    },
    # 危机检测
    "crisis": {
        "auto_escalate": True,
        "webhook_url": "",
    }
}

def get_ab_config() -> dict:
    """从 Redis 读取配置，合并默认值"""
    r = redis.Redis(...)
    raw = r.get(AB_CONFIG_KEY)
    if raw:
        stored = json.loads(raw)
        config = copy.deepcopy(AB_CONFIG_DEFAULTS)
        _deep_merge(config, stored)
        return config
    return copy.deepcopy(AB_CONFIG_DEFAULTS)

def update_ab_config(updates: dict, operator: str = "admin") -> dict:
    """更新配置，写入 Redis 并记录审计日志"""
    config = get_ab_config()
    _deep_merge(config, updates)
    
    r = redis.Redis(...)
    r.set(AB_CONFIG_KEY, json.dumps(config, ensure_ascii=False))
    
    log_admin_action("ab_config_update", operator, {
        "changes": updates,
        "final_config_hash": hashlib.sha256(json.dumps(config).encode()).hexdigest()[:16]
    })
    
    return config
```

### 5.3 与现有代码集成

**SRT 引擎改造：**

```python
# services/srt_engine.py
from services.ab_config import get_ab_config

def calculate_srt_recommendation(user_id: str) -> dict:
    cfg = get_ab_config()["srt"]
    
    # 用配置替换硬编码常量
    SE_OPTIMIZING = cfg["se_optimizing"]
    SE_STABLE = cfg["se_stable"]
    MIN_TIB_MINUTES = cfg["min_tib_hours"] * 60
    MAX_TIB_MINUTES = int(cfg["max_tib_hours"] * 60)
    BUFFER_MINUTES = cfg["buffer_minutes"]
    EXPANSION_MINUTES = cfg["expansion_minutes"]
    
    # ... 原有逻辑，使用上述变量 ...
```

**Prompt 改造：**

```python
# main.py
from services.ab_config import get_ab_config

def _build_system_prompt(user_id: str) -> str:
    cfg = get_ab_config()["prompt"]
    if cfg.get("system_prompt"):
        return cfg["system_prompt"]
    return CBT_SYSTEM_PROMPT
```

### 5.4 Admin 前端

新增 **"A/B 配置"** 页面，分组展示：

#### SRT 阈值卡片
| 参数 | 输入框 | 范围 | 默认值 |
|---|---|---|---|
| SE 优化门槛 | number | 80-95 | 90 |
| SE 稳定门槛 | number | 75-90 | 85 |
| 最小 TIB | number | 3-6 (h) | 4 |
| 最大 TIB | number | 7-9 (h) | 8.5 |
| 缓冲时间 | number | 15-60 (min) | 30 |
| 扩展增量 | number | 5-30 (min) | 15 |

#### Prompt 编辑器卡片
- 大文本框：编辑系统 Prompt（支持 Markdown 预览）
- 切换开关：启用 RAG / 启用焦虑检测
- 数字输入：最大上下文轮次

#### 变更历史
表格展示最近 20 次配置变更：时间 / 操作人 / 变更字段 / 旧值 → 新值

**API:**
```python
# GET /api/v1/admin/ab_config
# POST /api/v1/admin/ab_config  { "srt": {"se_optimizing": 88}, "prompt": {...} }
# GET /api/v1/admin/ab_config/history  (从 audit log 读取)
```

---

## 六、实施优先级与依赖

| 优先级 | 功能 | 工作量 | 依赖 | 预期收益 |
|---|---|---|---|---|
| **P0** | 睡眠数据大盘 | 2天 | 现有 Redis SCAN | ⭐⭐⭐ 核心产品指标可见 |
| **P0** | A/B 配置面板 | 2天 | srt_engine 常量提取 | ⭐⭐⭐ 运营自主权 |
| **P1** | 敏感内容实时告警 | 1天 | 现有 middleware | ⭐⭐ 安全提前量 |
| **P1** | AI 质量自动纠偏 | 1.5天 | evaluation_tracker | ⭐⭐ 降低人工复核 |
| **P2** | RAG 知识库版本 | 2天 | rag_engine 接口 | ⭐⭐ 知识可管理 |

### 建议实施顺序

```
Week 1:
  Day 1-2: A/B 配置面板（后端配置持久化 + 前端表单）
  Day 3-4: 睡眠数据大盘（数据聚合 + 图表）

Week 2:
  Day 1:   敏感内容实时告警（middleware 集成 + webhook）
  Day 2-3: AI 质量自动纠偏（触发器 + 队列 + 前端）
  Day 4-5: RAG 知识库版本（上传/回滚 + 索引重建）
```

---

## 七、数据存储汇总

| 功能 | Redis Key | 类型 | TTL |
|---|---|---|---|
| A/B 配置 | `admin:ab_config` | String (JSON) | 无 |
| 实时告警配置 | `admin:alert_config` | String (JSON) | 无 |
| 纠偏队列 | `quality:remedy:pending` | List | 无 |
| 健康快照 | `health:history` | List | 无 |
| API 统计 | `admin:api_stats` | String (JSON) | 7天 |
| 审计日志 | `admin:audit:{YYYY-MM-DD}` | List | 无 |

---

## 八、风险评估

| 风险 | 缓解措施 |
|---|---|
| A/B 配置错误导致 SRT 计算异常 | 输入框加范围限制，保存前校验 |
| RAG 索引重建期间服务不可用 | 后台异步重建，完成后热切换 |
| 敏感内容告警误报 | 关键词可配置，支持白名单用户 |
| 睡眠数据大盘扫描慢 | 加 `@cached_ttl(300)`，限制 SCAN count |
