# CI/CD test trigger - backend deploy
"""
睡前大脑关机助手 - FastAPI 后端 v2
接 腾讯云全家桶：流式TTS + 实时ASR + 千问对话
"""

import os
import asyncio
import json
import struct
import io
import base64
import uuid
import re
import hashlib
import hmac
import time
import jwt
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, AsyncGenerator
from contextlib import asynccontextmanager
from enum import Enum
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, WebSocket, WebSocketDisconnect, Depends, Header, Body, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, Response, FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import httpx
import redis

from infra.settings import settings, ADMIN_TOKEN, BACKEND_VERSION
from infra.redis_client import redis_client, async_redis_client
from services.auth import create_jwt_token, verify_jwt_token, AuthUser
from services.sleep_stats import update_streak, get_streak_days, get_user_sleep_stats, get_sleep_diary, save_sleep_diary
from srt_engine import srt_engine

# ==================== 安全验证工具 ====================

# 常见音频格式的魔数（文件头）
AUDIO_MAGIC = {
    b"\xff\xfb": "mp3",
    b"\xff\xfa": "mp3",
    b"\xff\xf3": "mp3",
    b"\xff\xf2": "mp3",
    b"RIFF": "wav",
    b"\x00\x00\x00\x18ftypmp4": "m4a",
    b"\x00\x00\x00": "mp4",
    b"\x52\x49\x46\x46": "wav",  # RIFF
}

# 允许的 MIME 类型
ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/wave", "audio/x-wav", "audio/pcm", "audio/mp4", "audio/m4a", "audio/x-m4a", "application/octet-stream"}


def _validate_audio_content(content: bytes, filename: str = "") -> bool:
    """通过魔数验证上传文件是否为合法音频。返回 True=合法，False=非法"""
    if len(content) < 12:
        return False
    # 检查文件头魔数
    for magic in AUDIO_MAGIC:
        if content[:len(magic)] == magic:
            return True
    # 备选：检查 MIME
    return False


# ==================== Rate Limiting ====================
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from collections import defaultdict
from datetime import datetime, timedelta
import threading

limiter = Limiter(key_func=get_remote_address)

# 基于用户的简易速率限制器（内存版，生产环境建议用 Redis）
_user_rate_limits: dict[str, list[datetime]] = defaultdict(list)
_user_rate_lock = threading.Lock()


def _check_user_rate_limit(uid: str, max_requests: int = 60, window_seconds: int = 60) -> bool:
    """每个用户每 window_seconds 最多 max_requests 次请求。返回 True=通过，False=超限"""
    now = datetime.now()
    cutoff = now - timedelta(seconds=window_seconds)
    with _user_rate_lock:
        _user_rate_limits[uid] = [t for t in _user_rate_limits[uid] if t > cutoff]
        if len(_user_rate_limits[uid]) >= max_requests:
            return False
        _user_rate_limits[uid].append(now)
        return True


class UserRateLimitMiddleware(BaseHTTPMiddleware):
    """基于 JWT user_id 的请求频率限制中间件"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/v1/"):
            return await call_next(request)
        # 登录/版本等公共接口不限速
        if path in ("/api/v1/auth/wx_login", "/api/v1/version", "/docs", "/openapi.json"):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        uid = "anonymous"
        if auth.startswith("Bearer "):
            try:
                payload = jwt.decode(auth[7:], settings.jwt_secret, algorithms=["HS256"])
                uid = payload.get("user_id") or "no_uid"
            except Exception:
                uid = "bad_token"
        elif request.client:
            uid = f"ip:{request.client.host}"

        if not _check_user_rate_limit(uid):
            return JSONResponse({"error": "请求过于频繁，请稍后重试"}, status_code=429)

        return await call_next(request)


# ==================== RAG / Session Logger（L2）============
try:
    import sys
    sys.path.insert(0, str(__file__).rsplit('/', 1)[0])
    from rag_engine import init_rag, build_rag_index, build_rag_system_prompt, log_cbt_turn_with_rag, finalize_session, rag_index
    from admin_routes import get_dashboard_stats, get_safety_events, get_quality_stats, get_user_list, get_user_detail, export_users_csv, export_safety_csv, export_evaluations_csv
    from session_logger import session_logger, LOG_DIR
    from dialogue_evaluator import dialogue_evaluator
    RAG_AVAILABLE = True
except ImportError as e:
    print(f"[RAG] ⚠️ 导入失败: {e}")
    RAG_AVAILABLE = False
    def init_rag(): pass
    def build_rag_system_prompt(*a, **k): return ""
    def log_cbt_turn_with_rag(*a, **k): pass
    def finalize_session(*a, **k): pass
    rag_index = None
    session_logger = None
    LOG_DIR = None

# ── 启动时关键配置校验 ─────────────────────────────────────────
def validate_startup():
    warnings = []
    errors = []
    if not settings.wx_app_id or not settings.wx_app_secret:
        warnings.append("微信小程序未配置（匿名模式）")
    if not all([settings.tencentcloud_app_id, settings.tencentcloud_secret_id, settings.tencentcloud_secret_key]):
        warnings.append("腾讯云 ASR/TTS 未配置（语音功能不可用）")
    if not settings.minimax_api_key:
        errors.append("MiniMax API Key 未配置（AI 对话不可用）")
    if settings.jwt_secret == "dev-secret-change-in-prod":
        errors.append("JWT_SECRET 使用了默认值（dev-secret-change-in-prod）！严重安全风险，请立即修改 .env 中的 JWT_SECRET")
    if settings.admin_token == "":
        warnings.append("ADMIN_TOKEN 为空（运营后台不可用）")
    if errors:
        print("\n".join([f"[ERROR] {e}" for e in errors]))
        raise RuntimeError(f"启动检查失败：{'；'.join(errors)}")
    if warnings:
        print("\n".join([f"[WARN] {w}" for w in warnings]))

validate_startup()

# ==================== 腾讯云多账号负载均衡 ====================

class TencentCredential:
    """腾讯云账号凭证"""
    def __init__(self, app_id: str, secret_id: str, secret_key: str):
        self.app_id = app_id
        self.secret_id = secret_id
        self.secret_key = secret_key

class TencentCredentialPool:
    """腾讯云多账号轮询池（负载均衡）"""
    def __init__(self):
        self.credentials: list[TencentCredential] = []
        self._index = 0
        self._lock = asyncio.Lock()
        # 主账号
        if all([settings.tencentcloud_app_id, settings.tencentcloud_secret_id, settings.tencentcloud_secret_key]):
            self.credentials.append(TencentCredential(
                settings.tencentcloud_app_id,
                settings.tencentcloud_secret_id,
                settings.tencentcloud_secret_key
            ))
        # 备用账号 2
        if all([settings.tencentcloud_app_id_2, settings.tencentcloud_secret_id_2, settings.tencentcloud_secret_key_2]):
            self.credentials.append(TencentCredential(
                settings.tencentcloud_app_id_2,
                settings.tencentcloud_secret_id_2,
                settings.tencentcloud_secret_key_2
            ))
        # 备用账号 3
        if all([settings.tencentcloud_app_id_3, settings.tencentcloud_secret_id_3, settings.tencentcloud_secret_key_3]):
            self.credentials.append(TencentCredential(
                settings.tencentcloud_app_id_3,
                settings.tencentcloud_secret_id_3,
                settings.tencentcloud_secret_key_3
            ))
        print(f"[Tencent Pool] 已加载 {len(self.credentials)} 个账号")

    async def get_credential(self) -> TencentCredential:
        if not self.credentials:
            raise Exception("腾讯云账号未配置")
        async with self._lock:
            cred = self.credentials[self._index]
            self._index = (self._index + 1) % len(self.credentials)
            return cred

    def get_all(self) -> list[TencentCredential]:
        return self.credentials.copy()

tencent_pool = TencentCredentialPool()

# ==================== TTS 并发控制 ====================

# ✅ TTS 并发 Semaphore：限制同时合成请求数 ≤ 15（腾讯云精品音色上限 20，留 5 路缓冲）
_tts_semaphore = asyncio.Semaphore(15)

# ✅ TTS 内存缓存（高频短句）
_tts_memory_cache: dict[str, str] = {}
_MAX_TTS_MEMORY_CACHE = 200  # 最多缓存 200 条

def _get_tts_cache_key(text: str, voice: str, speed: int) -> str:
    return hashlib.md5(f"{text}:{voice}:{speed}".encode()).hexdigest()

# ── 订阅方案限额配置 ─────────────────────────────────────────
# 免费版按天计费，Pro 版按月计费
# AI 回复「字数」限额（字符数），按阅读速度 300字/分钟 换算
# Free:    10分钟/天 = 3000字/天
# Basic:   15小时/月 = 900分钟/月 = 270000字/月
# Core:    30小时/月 = 1800分钟/月 = 540000字/月
TEXT_LIMIT_FREE   = 3000    # 免费版：10分钟/天
TEXT_LIMIT_BASIC  = 270000  # 基础 Pro：15小时/月
TEXT_LIMIT_CORE   = 540000  # 核心 Pro：30小时/月

# AI 语音（TTS 音频秒数）
# Free:    3分钟 = 180秒/天
# Basic:   15小时/月 = 54000秒/月
# Core:    30小时/月 = 108000秒/月
VOICE_LIMIT_FREE  = 180     # 免费版：3分钟语音/天
VOICE_LIMIT_BASIC = 54000   # 基础 Pro：15小时/月
VOICE_LIMIT_CORE  = 108000  # 核心 Pro：30小时/月

# ==================== 启动 ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    import infra.redis_client as _redis_mod
    print("🚀 知眠 API v2 启动...")
    print(f"   千问 Chat:      {'✅ 已配置' if settings.minimax_api_key else '⚠️ 未配置'}")
    print(f"   腾讯云 TTS:     {'✅ 已配置' if (settings.tencentcloud_app_id and settings.tencentcloud_secret_id) else '⚠️ 未配置'}")
    print(f"   腾讯云 ASR:     {'✅ 已配置' if (settings.tencentcloud_app_id and settings.tencentcloud_secret_id) else '⚠️ 未配置'}")
    print(f"   Edge TTS:       ✅ 备用（免费）")
    try:
        redis_client.ping()
        print("   Redis: ✅ 已连接")
        from cbt_manager import user_profile_manager, cbt_manager
        user_profile_manager.set_redis(redis_client)
        cbt_manager.set_redis(redis_client)
        print("   CBTManager: ✅ 状态机已接入 Redis 持久化")
    except Exception as e:
        print(f"   Redis: ⚠️ 连接失败 - {e}")

    # ✅ 异步 Redis 客户端初始化（高并发优化）
    try:
        import redis.asyncio
        if settings.redis_async_url:
            _redis_mod.async_redis_client = await redis.asyncio.from_url(
                settings.redis_async_url, encoding="utf-8", decode_responses=True
            )
        else:
            _redis_mod.async_redis_client = redis.asyncio.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                password=settings.redis_password or None,
                decode_responses=True,
            )
        await _redis_mod.async_redis_client.ping()
        print("   Redis (async): ✅ 已连接")
    except Exception as e:
        print(f"   Redis (async): ⚠️ 连接失败 - {e}（高并发时可能阻塞事件循环）")
        _redis_mod.async_redis_client = None

    # ✅ TTS 高频短句预热（Edge TTS 预合成，存 Redis，免费不占腾讯云并发）
    if settings.tts_warmup_phrases:
        asyncio.create_task(_warmup_tts_phrases())

    # ✅ TTS 队列消费协程（后台运行）
    asyncio.create_task(_tts_queue_worker())

    # ✅ ASR 连接预热池（启动时建立预连接，减少首次延迟）
    if settings.asr_warmup_connections > 0 and all([settings.tencentcloud_app_id, settings.tencentcloud_secret_id, settings.tencentcloud_secret_key]):
        asyncio.create_task(_warmup_asr_pool())

    # ✅ RAG 索引初始化（后台异步加载，不阻塞启动）
    if RAG_AVAILABLE:
        def _init_rag_bg():
            try:
                init_rag()
                print("   RAG 索引: ✅ 已初始化")
            except Exception as e:
                print(f"   RAG 索引: ⚠️ 初始化失败 - {e}")
        asyncio.get_event_loop().call_later(0.5, lambda: asyncio.create_task(asyncio.to_thread(_init_rag_bg)))

    yield
    print("👋 后端关闭...")
    if _redis_mod.async_redis_client:
        try:
            await _redis_mod.async_redis_client.aclose()
        except Exception:
            pass

# ==================== Auth Models ====================

class WxLoginRequest(BaseModel):
    code: str

class WxLoginResponse(BaseModel):
    token: str
    user_id: str
    is_new_user: bool

class UserProfileRequest(BaseModel):
    """用户资料更新"""
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None

async def get_current_user(authorization: str = Header(None)) -> AuthUser:
    if not authorization:
        raise HTTPException(status_code=401, detail="未登录，请先调用 /api/v1/auth/login")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization 格式错误")
    token = authorization[7:]
    user = verify_jwt_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    return user

app = FastAPI(title="知眠 API v2", version="2.0.0", description="腾讯云流式TTS + 实时ASR + 千问对话", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://sleepai.chat",
        "https://www.sleepai.chat",
        "https://anmian.com",
        "https://www.anmian.com",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Token"],
)

# ==================== 版本接口 ====================

@app.get("/api/v1/version")
async def get_version():
    return {
        "version": BACKEND_VERSION,
        "environment": "production",
        "components": {
            "wx_login": bool(settings.wx_app_id and settings.wx_app_secret),
            "tencent_asr_tts": bool(settings.tencentcloud_app_id and settings.tencentcloud_secret_id),
            "qwen_chat": bool(settings.minimax_api_key),
            "redis": True,
        }
    }

# ==================== 运营后台认证中间件 ====================

class AdminAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith("/api/v1/admin/"):
            if path == "/api/v1/admin/login":
                # 登录接口无需验证
                pass
            elif not ADMIN_TOKEN:
                # 空 TOKEN = 未配置，禁止访问（fail-safe）
                from fastapi.responses import JSONResponse
                return JSONResponse({"error": "运营后台未配置管理员密码，请联系运维"}, status_code=503)
            else:
                token = request.headers.get("X-Admin-Token", "")
                if token != ADMIN_TOKEN:
                    from fastapi.responses import JSONResponse
                    return JSONResponse({"error": "未授权"}, status_code=401)
        return await call_next(request)

app.add_middleware(AdminAuthMiddleware)
app.add_middleware(UserRateLimitMiddleware)


# ==================== Rate Limit Exception Handler ====================
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        {"error": "请求过于频繁，请稍后再试", "detail": str(exc)},
        status_code=429,
        headers={"Retry-After": "60"},
    )


# 运营后台静态文件
app.mount("/admin", StaticFiles(directory=str(Path(__file__).parent.parent / "static/admin"), html=True), name="admin")


# ==================== 微信登录 & 数据迁移 ====================

@app.post("/api/v1/auth/wx_login")
async def wx_login(body: dict = Body(...)):
    """微信小程序登录：code 换 openid，返回 JWT token"""
    code = body.get("code")
    temp_id = body.get("temp_id")
    if not code:
        raise HTTPException(status_code=400, detail="缺少 code 参数")
    if not settings.wx_app_id or not settings.wx_app_secret:
        raise HTTPException(status_code=503, detail="微信小程序未配置")

    # 调用微信 jscode2session
    wx_url = (
        f"https://api.weixin.qq.com/sns/jscode2session"
        f"?appid={settings.wx_app_id}&secret={settings.wx_app_secret}"
        f"&js_code={code}&grant_type=authorization_code"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(wx_url)
            wx_data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"微信接口调用失败: {e}")

    if wx_data.get("errcode"):
        raise HTTPException(status_code=400, detail=f"微信登录失败: {wx_data.get('errmsg')}")

    openid = wx_data.get("openid")
    if not openid:
        raise HTTPException(status_code=400, detail="无法获取 openid")

    user_id = f"wx_{openid[:16]}"
    token = create_jwt_token(openid)

    # 检查是否新用户（Redis 中是否有历史记录）
    is_new_user = not redis_client.exists(f"chat:history:{user_id}:*")

    # 如果有 temp_id，迁移数据
    if temp_id and temp_id != user_id:
        migrated = _migrate_user_data(temp_id, user_id)
        if migrated:
            print(f"[wx_login] 数据迁移: {temp_id} -> {user_id}, 迁移键数: {migrated}")

    return {"token": token, "user_id": user_id, "is_new_user": is_new_user}


@app.get("/api/v1/user/profile")
async def get_user_profile(user: AuthUser = Depends(get_current_user)):
    """获取用户资料（昵称、头像）"""
    try:
        user_id = user.user_id
        raw = redis_client.get(f"user_profile:{user_id}")
        if raw:
            profile = json.loads(raw)
            return {"nickname": profile.get("nickname", ""), "avatar_url": profile.get("avatar_url", "")}
        return {"nickname": "", "avatar_url": ""}
    except Exception as e:
        print(f"[get_user_profile error] {e}")
        return {"nickname": "", "avatar_url": ""}


@app.post("/api/v1/user/profile")
async def update_user_profile(req: UserProfileRequest, user: AuthUser = Depends(get_current_user)):
    """更新用户资料（昵称、头像）"""
    try:
        user_id = user.user_id
        key = f"user_profile:{user_id}"
        existing = {}
        raw = redis_client.get(key)
        if raw:
            existing = json.loads(raw)
        if req.nickname is not None:
            existing["nickname"] = req.nickname.strip()[:50]
        if req.avatar_url is not None:
            existing["avatar_url"] = req.avatar_url.strip()[:500]
        existing["updated_at"] = datetime.now().isoformat()
        redis_client.set(key, json.dumps(existing, ensure_ascii=False), ex=365*24*3600)
        return {"nickname": existing.get("nickname", ""), "avatar_url": existing.get("avatar_url", "")}
    except Exception as e:
        print(f"[update_user_profile error] {e}")
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")


def _migrate_user_data(temp_id: str, real_id: str) -> int:
    """将 temp_id 的数据迁移到真实 user_id，返回迁移的键数"""
    migrated = 0
    try:
        # 查找所有包含 temp_id 的 Redis 键
        pattern = f"*{temp_id}*"
        keys = []
        for key in redis_client.scan_iter(match=pattern, count=100):
            keys.append(key.decode() if isinstance(key, bytes) else key)

        for key in keys:
            new_key = key.replace(temp_id, real_id)
            data = redis_client.get(key)
            if data:
                ttl = redis_client.ttl(key)
                if ttl > 0:
                    redis_client.setex(new_key, ttl, data)
                else:
                    redis_client.set(new_key, data)
                migrated += 1
    except Exception as e:
        print(f"[migrate] 数据迁移失败: {e}")
    return migrated

# ✅ 异步 Redis 客户端（高并发优化，避免阻塞事件循环）
# 用 redis.asyncio（redis-py 4.2+ 内置），fallback 到同步客户端
# ✅ TTS 优先级等待队列（Semaphore 满时，VIP 用户优先出队）
# (priority: 0=VIP, 1=普通, asyncio.Event, text, voice, speed)
_tts_wait_queue: asyncio.Queue = asyncio.Queue()

# ==================== Enums / Models ====================

class AnxietyLevel(str, Enum):
    NORMAL = "normal"
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = Field(default=None, max_length=64)
    skip_tts: bool = False  # ✅ 文本模式下跳过 TTS 合成，加速响应

    @field_validator("message", mode="before")
    @classmethod
    def strip_message(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("session_id", mode="before")
    @classmethod
    def strip_session_id(cls, v):
        return v.strip() if isinstance(v, str) else v

class SleepRecordRequest(BaseModel):
    user_id: str
    date: str
    score: int

# ==================== Session / Memory Helpers (Redis) ====================

def get_session_history(user_id: str, session_id: str) -> List[Message]:
    key = f"chat:history:{user_id}:{session_id}"
    try:
        data = redis_client.get(key)
        if data:
            return [Message(**m) for m in json.loads(data)]
    except Exception as e:
        print(f"[Redis get history error] {e}")
    return []

def save_session_history(user_id: str, session_id: str, history: List[Message]):
    key = f"chat:history:{user_id}:{session_id}"
    try:
        data = json.dumps([{"role": m.role, "content": m.content} for m in history[-40:]], ensure_ascii=False)
        redis_client.setex(key, 7 * 86400, data)  # 7 days TTL
    except Exception as e:
        print(f"[Redis save history error] {e}")
# ── 订阅与每日用量管理 ───────────────────────────────────────
# ── 订阅与每日用量管理 ───────────────────────────────────────
def _get_subscription(user_id: str) -> dict:
    """从 Redis 读取用户订阅信息"""
    key = f"subscription:{user_id}"
    raw = redis_client.get(key)
    if not raw:
        return {}
    return json.loads(raw)


def _get_tier(user_id: str) -> str:
    """
    获取用户订阅档位: 'free' | 'basic' | 'core'
    未订阅 / 已过期 / plan 字段无效 → 'free'
    """
    sub = _get_subscription(user_id)
    if not sub.get('is_active'):
        return 'free'
    try:
        expire = datetime.strptime(sub['expire_date'], '%Y-%m-%d')
        if expire.date() < datetime.now().date():
            return 'free'
    except:
        return 'free'
    plan = sub.get('plan', '').lower()
    if plan in ('basic', 'pro', 'basic_pro'):
        return 'basic'
    if plan in ('core', 'core_pro'):
        return 'core'
    return 'free'


def _get_text_limit(user_id: str) -> int:
    """获取用户每日文本字数限额"""
    tier = _get_tier(user_id)
    return { 'free': TEXT_LIMIT_FREE, 'basic': TEXT_LIMIT_BASIC, 'core': TEXT_LIMIT_CORE }[tier]


def _get_voice_limit(user_id: str) -> int:
    """获取用户每日语音秒数限额"""
    tier = _get_tier(user_id)
    return { 'free': VOICE_LIMIT_FREE, 'basic': VOICE_LIMIT_BASIC, 'core': VOICE_LIMIT_CORE }[tier]


def _get_text_key(user_id: str) -> str:
    """获取文本用量 Redis key（免费版按天，Pro 按月）"""
    tier = _get_tier(user_id)
    if tier == 'free':
        today = datetime.now().strftime('%Y-%m-%d')
        return f"daily_text_chars:{user_id}:{today}"
    else:
        month = datetime.now().strftime('%Y-%m')
        return f"monthly_text_chars:{user_id}:{month}"


def _get_voice_key(user_id: str) -> str:
    """获取语音用量 Redis key（免费版按天，Pro 按月）"""
    tier = _get_tier(user_id)
    if tier == 'free':
        today = datetime.now().strftime('%Y-%m-%d')
        return f"daily_voice_secs:{user_id}:{today}"
    else:
        month = datetime.now().strftime('%Y-%m')
        return f"monthly_voice_secs:{user_id}:{month}"


def _get_remaining_quota(user_id: str) -> dict:
    """
    返回 {text_remaining, text_limit, voice_remaining, voice_limit, tier, period}
    免费版按天计费，Pro 版按月计费
    """
    text_limit = _get_text_limit(user_id)
    voice_limit = _get_voice_limit(user_id)
    text_used = 0
    voice_used = 0
    try:
        t_key = _get_text_key(user_id)
        v_key = _get_voice_key(user_id)
        pipe = redis_client.pipeline()
        pipe.get(t_key)
        pipe.get(v_key)
        t_val, v_val = pipe.execute()
        if t_val: text_used = float(t_val)
        if v_val: voice_used = float(v_val)
    except:
        pass
    tier = _get_tier(user_id)
    return {
        'text_remaining': max(0, text_limit - int(text_used)),
        'text_limit': text_limit,
        'text_used': int(text_used),
        'voice_remaining': max(0, voice_limit - int(voice_used)),
        'voice_limit': voice_limit,
        'voice_used': int(voice_used),
        'tier': tier,
        'period': 'day' if tier == 'free' else 'month',
    }


def _record_text_usage(user_id: str, char_count: int):
    """记录本次 AI 回复字数到用量（免费版按天，Pro 按月）"""
    if char_count <= 0:
        return
    try:
        key = _get_text_key(user_id)
        tier = _get_tier(user_id)
        pipe = redis_client.pipeline()
        pipe.incrby(key, char_count)
        if tier == 'free':
            # 次日 0 点过期
            tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
            expire_ts = datetime.strptime(tomorrow, '%Y-%m-%d').timestamp()
            ttl = max(1, int(expire_ts - time.time()))
        else:
            # 次月 1 日 0 点过期
            next_month = datetime.now().replace(day=1) + timedelta(days=32)
            next_month = next_month.replace(day=1)
            ttl = max(1, int(next_month.timestamp() - time.time()))
        pipe.expire(key, ttl)
        pipe.execute()
    except:
        pass


def _record_voice_usage(user_id: str, duration_seconds: float):
    """记录本次 TTS 时长（秒）到用量（免费版按天，Pro 按月）"""
    if duration_seconds <= 0:
        return
    try:
        key = _get_voice_key(user_id)
        tier = _get_tier(user_id)
        pipe = redis_client.pipeline()
        pipe.incrbyfloat(key, duration_seconds)
        if tier == 'free':
            tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
            expire_ts = datetime.strptime(tomorrow, '%Y-%m-%d').timestamp()
            ttl = max(1, int(expire_ts - time.time()))
        else:
            next_month = datetime.now().replace(day=1) + timedelta(days=32)
            next_month = next_month.replace(day=1)
            ttl = max(1, int(next_month.timestamp() - time.time()))
        pipe.expire(key, ttl)
        pipe.execute()
    except:
        pass


async def _async_update_profile(user_id: str, session_summary: dict):
    """L4: 异步更新用户心理档案（不阻塞主响应流）"""
    try:
        from cbt_manager import user_profile_manager
        user_profile_manager.set_redis(redis_client)
        await user_profile_manager.update_after_session(user_id, session_summary)
    except Exception as e:
        print(f"[Profile] Update failed: {e}")


def _estimate_tts_duration(text: str) -> float:
    """估算 TTS 音频时长（秒），按中文约 2.5 字符/秒"""
    return max(1.0, len(text) / 2.5)


def get_user_memory(user_id: str) -> dict:
    key = f"user:memory:{user_id}"
    try:
        data = redis_client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        print(f"[Redis get memory error] {e}")
    return {"concerns": [], "triggers": {}, "last_topic": "", "streak_days": 0}


def update_user_memory(user_id: str, message: str, response: str):
    key = f"user:memory:{user_id}"
    try:
        memory = get_user_memory(user_id)
        words = re.findall(r"[\w]{2,}", message)
        for w in words:
            memory.setdefault("triggers", {})[w] = memory["triggers"].get(w, 0) + 1
        memory["last_topic"] = message[:50]
        memory.setdefault("concerns", []).append(message[:100])
        memory["concerns"] = memory["concerns"][-10:]
        # 从失眠亚型推断（如有）
        if "睡不着" in message or "入睡" in message:
            memory["insomnia_subtype"] = memory.get("insomnia_subtype", "sleep_onset")
        redis_client.setex(key, 90 * 86400, json.dumps(memory, ensure_ascii=False))
    except Exception as e:
        print(f"[Redis update memory error] {e}")


# ==================== Sleep Diary Models ====================

class BedtimeSettingRequest(BaseModel):
    """睡前设定今晚睡眠窗口"""
    user_id: str
    planned_bed_time: str       # "23:00" 格式
    planned_wake_time: str      # "07:00" 格式
    date: Optional[str] = None  # 默认今天

class SleepDiaryEntry(BaseModel):
    """完整的睡眠日记条目（睡前设定 + 晨间记录）"""
    user_id: str
    date: str                   # 日期，如 "2024-04-08"
    
    # 睡前设定
    planned_bed_time: str
    planned_wake_time: str
    planned_tib_minutes: int    # 计划卧床时长
    
    # 晨间记录
    actual_bed_time: Optional[str] = None
    actual_wake_time: Optional[str] = None
    wake_count: int = 0
    sleep_quality: int = 3      # 1-5
    
    # 计算指标
    tib_minutes: int = 0        # Time In Bed
    tst_minutes: int = 0        # Total Sleep Time
    se: float = 0.0             # Sleep Efficiency (%)
    sol_minutes: Optional[int] = None  # Sleep Onset Latency
    waso_minutes: int = 0       # Wake After Sleep Onset
    
    created_at: str = ""
    updated_at: str = ""

class SleepDashboardRequest(BaseModel):
    """睡眠效率仪表盘请求"""
    user_id: str
    days: int = 7               # 查询天数，默认7天

# ==================== Morning Check-in Models ====================

class MorningSubmitRequest(BaseModel):
    user_id: str
    date: Optional[str] = None     # 可选，指定日记日期（默认为当天）
    bed_time_estimate: str          # "22:00" 格式
    wake_count: int                 # 0, 1, 2, 3+
    wake_time_estimate: str         # "07:00" 格式
    sleep_quality: int              # 1-5
    sleep_window_start: str         # "23:00"
    sleep_window_end: str           # "07:00"
    waso_minutes: int = 0           # WASO: Wake After Sleep Onset (夜间醒来总时长)
    nap_minutes: int = 0            # 午睡时长(分钟)
    fatigue_level: int = 3          # 白天疲劳程度 1-5
    se: float = 0.0                 # 前端计算的睡眠效率
    tst_hours: float = 0.0          # 前端计算的实际睡眠时长
    tib_hours: float = 0.0          # 前端计算的床上时间
    sleep_score: int = 0            # 前端计算的综合睡眠评分(0-100)


class SleepWindowRequest(BaseModel):
    user_id: str
    bed_hour: int                   # 0-23
    bed_min: int                    # 0-59
    wake_hour: int                  # 0-23
    wake_min: int                   # 0-59

class SleepDiarySubmitRequest(BaseModel):
    """睡眠日记提交（从睡眠效率详情页记录今早睡眠）"""
    bed_time: str                   # "23:00" 格式
    wake_time: str                  # "07:00" 格式
    sleep_latency_minutes: int = 0  # 入睡潜伏期（分钟）
    wake_count: int = 0             # 夜间醒来次数
    quality: int = 3                # 睡眠质量 1-5
    note: str = ""                  # 备注
    date: Optional[str] = None      # 默认今天

# ==================== CBT System Prompt ====================

CBT_SYSTEM_PROMPT = """你是"睡前大脑关机助手"，一个专为中国人睡前焦虑场景设计的 AI 陪伴者。

【绝对禁止】
- 禁止用固定句式开头，比如"声音在""我在""我在听"
- 禁止每句话都提到"今晚""睡觉""焦虑"，只在用户主动提及时回应
- 禁止模板化回复，比如"听起来你现在感到...""没关系，我陪着你"
- 禁止重复用户的话作为回复
- 禁止在回复末尾添加固定结束语

【你的核心使命】
帮助用户在睡前完成：
1. 说出担忧（Get it out）
2. 看清楚担忧（Look at it clearly）
3. 放下担忧（Let it go）
然后安心睡觉。

【你的风格】
- 像真人聊天一样自然，有语气变化
- 回复长度灵活：简单问候可以很短，复杂情绪可以稍长
- 温暖、不评判，但不矫情
- 用中文，不夹英文
- 可以偶尔用口语化表达，比如"嗯""是吧""我理解"

【CBT 技术】（自然融入对话，不要生硬套用）
- 情绪反映：用自己的话描述用户的感受
- 去灾难化：帮用户看到事情没那么糟
- 时间透视：提醒用户事情会过去
- 证据检验：帮用户区分想法和事实

【安全红线】
- 用户提及自杀/自伤 → 立即发送热线：010-82951332
- 绝对不说："你不应该焦虑"/"想开一点"/"你需要的是…"

【Minimax 输出约束】
- 不要输出任何思考过程（如 <think>...</think>）
- 不要输出 JSON 格式或结构化标记
- 直接输出纯文本对话内容
- 回复控制在 15-50 字之间

【重要：不要无限陪聊】
- 你最多回应 2-3 轮焦虑话题
- 第2轮结束时，主动引导放松
- 绝对不要：继续追问细节、给建议方案、让用户继续说

【回复示例】（仅供参考，不要照搬）
用户："你好"
你："你好呀，还没睡？"

用户："我有点担心明天的工作"
你："明天有什么事让你放心不下？"

用户："我睡不着"
你："是脑子里在想事情，还是就是睡不着？"
"""

# ==================== 焦虑检测（简化版）====================

def detect_anxiety(text: str) -> dict:
    """轻量级焦虑关键词检测"""
    severe_kw = ["自杀", "自伤", "不想活", "死了算了", "活不下去"]
    moderate_kw = ["崩溃", "绝望", "完蛋了", "彻底完了", "极度恐慌"]
    mild_kw = ["担心", "焦虑", "害怕", "紧张", "不安", "睡不着", "脑子停不下来", "静不下来"]
    trigger_kw = ["工作", "人际", "未来", "健康", "家庭", "感情", "金钱"]

    t = text.lower()
    level, action = "normal", "CONTINUE"
    trigger = "general"
    for kw in severe_kw:
        if kw in t: level, action = "severe", "IMMEDIATE_SWITCH"
    for kw in moderate_kw:
        if kw in t: level, action = "moderate", "PREPARE_SWITCH"
    for kw in mild_kw:
        if kw in t and level == "normal": level, action = "mild", "CONTINUE"
    for kw in trigger_kw:
        if kw in t: trigger = kw
    return {"level": level, "action": action, "trigger": trigger}

# ==================== 千问 Chat ====================

async def qwen_chat(messages: list[dict], stream: bool = True) -> AsyncGenerator[str, None]:
    """调用千问 Chat API（OpenAI 兼容格式）"""
    if not settings.minimax_api_key:
        yield "抱歉，AI 服务暂不可用，请稍后再试。"
        return

    headers = {
        "Authorization": f"Bearer {settings.minimax_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "qwen-plus",
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 80,
        "stream": stream
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream(
                "POST",
                f"{settings.qwen_base_url}/chat/completions",
                headers=headers,
                json=payload
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]": break
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0]["delta"].get("content", "")
                            if delta:
                                yield delta
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            print(f"[Qwen Chat Error] {e}")
            yield "抱歉，服务暂时不稳定，请稍后再试。"


# ==================== MiniMax Chat ====================

# ✅ P0-1: 模块级单例 HTTP 连接池，避免每次请求重建 TCP/TLS
_minimax_http_client: httpx.AsyncClient | None = None

def _get_minimax_http_client() -> httpx.AsyncClient:
    global _minimax_http_client
    if _minimax_http_client is None:
        _minimax_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _minimax_http_client

async def minimax_chat(messages: list[dict], stream: bool = True) -> AsyncGenerator[str, None]:
    """调用 MiniMax Chat API（Anthropic 兼容格式，过滤 thinking 过程）"""
    if not settings.minimax_api_key:
        yield "抱歉，AI 服务暂不可用，请稍后再试。"
        return

    headers = {
        "Authorization": f"Bearer {settings.minimax_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "MiniMax-M2.7",
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 256,
        "stream": stream
    }

    in_thinking_block = False
    client = _get_minimax_http_client()

    try:
        async with client.stream(
            "POST",
            "https://api.minimaxi.com/anthropic/v1/messages",
            headers=headers,
            json=payload
        ) as resp:
            async for line in resp.aiter_lines():
                if not line.strip() or line.strip() == "event: ping":
                    continue
                if line.startswith("data: "):
                    data = line[6:]
                    try:
                        chunk = json.loads(data)
                        # 跟踪 content_block 类型
                        if chunk.get("type") == "content_block_start":
                            block = chunk.get("content_block", {})
                            if block.get("type") == "thinking":
                                in_thinking_block = True
                            elif block.get("type") == "text":
                                in_thinking_block = False
                            continue
                        if chunk.get("type") == "content_block_stop":
                            in_thinking_block = False
                            continue
                        # 跳过 thinking 块的内容
                        if in_thinking_block:
                            continue
                        # 解析 text_delta
                        if chunk.get("type") == "content_block_delta":
                            delta = chunk.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    yield text
                        elif chunk.get("type") == "message_delta":
                            delta = chunk.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    yield text
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        print(f"[MiniMax Chat Error] {e}")
        yield "抱歉，服务暂时不稳定，请稍后再试。"


def _get_sleep_summary(user_id: str, days: int = 7) -> str:
    """获取用户最近 N 天的睡眠数据摘要，注入 system prompt"""
    try:
        from datetime import datetime, timedelta
        entries = []
        for i in range(days):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            diary = get_sleep_diary(user_id, d)
            if diary:
                entries.append(diary)
        if not entries:
            return ""
        
        # 计算平均值
        se_list = [e.get("se", 0) for e in entries if e.get("se", 0) > 0]
        tst_list = [e.get("tst_minutes", 0) / 60 for e in entries if e.get("tst_minutes", 0) > 0]
        tib_list = [e.get("tib_minutes", 0) / 60 for e in entries if e.get("tib_minutes", 0) > 0]
        quality_list = [e.get("sleep_quality", 0) for e in entries if e.get("sleep_quality", 0) > 0]
        wake_list = [e.get("wake_count", 0) for e in entries]
        
        avg_se = sum(se_list) / len(se_list) if se_list else 0
        avg_tst = sum(tst_list) / len(tst_list) if tst_list else 0
        avg_tib = sum(tib_list) / len(tib_list) if tib_list else 0
        avg_quality = sum(quality_list) / len(quality_list) if quality_list else 0
        avg_wake = sum(wake_list) / len(wake_list) if wake_list else 0
        
        # 最近一天数据
        latest = entries[0]
        latest_se = latest.get("se", 0)
        latest_tst = latest.get("tst_minutes", 0) / 60
        latest_quality = latest.get("sleep_quality", 0)
        
        # 趋势判断
        se_trend = "改善" if len(se_list) >= 2 and se_list[0] > se_list[-1] else "稳定" if len(se_list) >= 2 and abs(se_list[0] - se_list[-1]) < 5 else "波动"
        
        lines = [
            f"\n\n[用户睡眠数据（最近{len(entries)}天）]",
            f"- 平均睡眠效率: {avg_se:.1f}%（目标>85%，{'达标' if avg_se >= 85 else '偏低'}）",
            f"- 平均实际睡眠: {avg_tst:.1f}h（目标7-8h）",
            f"- 平均卧床时间: {avg_tib:.1f}h",
            f"- 平均睡眠质量: {avg_quality:.1f}/5",
            f"- 平均夜间觉醒: {avg_wake:.1f}次",
            f"- 趋势: {se_trend}",
        ]
        
        # 如果最近一天数据较差，增加提示
        if latest_se > 0 and latest_se < 70:
            lines.append(f"- 注意：昨晚睡眠效率仅{latest_se:.0f}%，可能存在睡眠维持困难")
        if latest_quality > 0 and latest_quality <= 2:
            lines.append(f"- 注意：昨晚睡眠质量较差（{latest_quality}/5）")
        
        return "\n".join(lines)
    except Exception as e:
        print(f"[SleepSummary] 获取失败: {e}")
        return ""


def _build_enhanced_system_prompt(
    user_id: str, session_id: str, cbt_result: dict, user_message: str, memory: dict = None,
    profile: dict = None
) -> str:
    """构建 RAG 增强后的系统提示词（统一供 chat_cbt 和 chat_cbt_stream 使用）"""
    current_phase = cbt_result.get('next_phase')
    cbt_base_prompt = cbt_manager.get_cbt_system_prompt(user_id, session_id, phase=current_phase, profile=profile)
    if memory is None:
        memory = get_user_memory(user_id)

    # 从 cbt_result 中提取用户风格和关系深度（用于显式注入 prompt）
    state_update = cbt_result.get('state_update', {})
    user_style = state_update.get('user_style', 'NORMAL')
    relationship_depth = profile.get('relationship_depth', 0) if profile else 0

    # RAG 增强（带容错，避免检索失败导致整个请求崩溃）
    rag_context = ""
    if RAG_AVAILABLE:
        try:
            _alvl = state_update.get('anxiety_level', 5)
            if isinstance(_alvl, AnxietyLevel):
                _alvl_map = {"severe": 8, "moderate": 5, "mild": 2, "normal": 0}
                _alvl = _alvl_map.get(_alvl.value, 5)
            rag_context = build_rag_system_prompt(
                user_id=user_id,
                session_context=memory,
                current_phase=cbt_result["next_phase"],
                user_message=user_message,
                anxiety_level=_alvl,
                user_style=user_style
            )
        except Exception as e:
            import traceback; print(f"[RAG] 构建系统提示词失败: {e}\n{traceback.format_exc()}")
            rag_context = ""
    memory_context = ""
    if memory.get("concerns"):
        top = sorted(memory.get("triggers", {}).items(), key=lambda x: -x[1])[:3]
        concerns = "、".join([f"{k}({v}次)" for k, v in top])
        memory_context = f"\n\n[用户历史] 近日常见担忧：{concerns}。最后话题：{memory.get('last_topic', '无')}"

    # 睡眠日记数据注入（改为查3天，减少 I/O 和 prompt 长度）
    sleep_context = _get_sleep_summary(user_id, days=3)
    
    # 情绪分析注入（新增）：根据用户消息动态调整回复策略
    emotion_context = ""
    try:
        analyzer = get_emotion_analyzer()
        emotion = analyzer.analyze(user_message)
        if emotion.primary != "neutral" and emotion.confidence > 0.3:
            style_hint = {
                "CONTINUE": "用户情绪可控，正常对话",
                "CONTINUE_WITH_CARE": "用户情绪较强烈，回复需更简短温和（15-25字）",
                "IMMEDIATE_SAFETY": "用户情绪危急，优先安抚和安全确认，回复极短（10-15字）"
            }.get(emotion.risk_flag, "正常对话")
            emotion_context = (
                f"\n\n[用户当前情绪] {emotion.primary}（{emotion.level}，强度{emotion.intensity}/5）"
                f"，风险标记：{emotion.risk_flag}。{style_hint}"
            )
            if emotion.worry_domains:
                emotion_context += f"\n- 担忧领域：{'、'.join(emotion.worry_domains)}"
            if emotion.cognitive_distortions:
                emotion_context += f"\n- 认知扭曲信号：{'、'.join(emotion.cognitive_distortions)}"
            if emotion.suicide_risk > 0.3:
                emotion_context += f"\n- ⚠️ 自杀风险检测：{emotion.suicide_risk:.0%}，需关注"
    except Exception as e:
        print(f"[Emotion] 分析失败: {e}")

    # 显式用户风格 + 关系深度标签（确保 LLM 能看到）
    style_label = f"\n【当前用户风格：{user_style}】请严格按上述风格指令回复。"
    if relationship_depth > 0:
        if relationship_depth == 1:
            style_label += "【关系阶段：初识】保持专业克制。"
        elif 2 <= relationship_depth <= 3:
            style_label += "【关系阶段：熟悉】可以适度自然，像了解对方的朋友。"
        elif 4 <= relationship_depth <= 9:
            style_label += "【关系阶段：信任】语气更放松，可提及之前的技术或进展。"
        elif relationship_depth >= 10:
            style_label += "【关系阶段：深度】像老朋友一样陪伴，自然提及历史偏好。"

    # 组合顺序：强制规则必须放在最后，且用极强措辞
    # ✅ P1: 精简 strict_rules，减少 prompt 长度，加快 LLM 首包响应
    strict_rules = (
        "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "【输出规则——优先级最高】\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "1. 简短自然：日常5-15字，情绪稍长20-40字。像真人聊天，不机械。\n"
        "2. 不输出标签/格式标记。语气温柔沉稳，适度柔软，不过度亲昵。\n"
        "3. 不评判、不追问为什么、不给建议、不分析。重点在陪伴。\n"
        "4. 不模板化、不固定句式、不每句提睡觉/焦虑。禁止不耐烦。\n"
        "5. 情绪强烈时回复更短更温和。可引用睡眠数据，但不数据轰炸。\n"
    )
    
    parts = [cbt_base_prompt, memory_context, sleep_context, emotion_context]
    if rag_context:
        parts.append("\n" + rag_context)
    parts.append(style_label)
    parts.append(strict_rules)
    return "".join([p for p in parts if p])


# ==================== TTS 优化：预热 + 队列 ====================

def _get_tts_cache_key(text: str, voice: str, speed: int) -> str:
    """TTS 缓存 key（MD5）"""
    import hashlib
    return hashlib.md5(f"{text}:{voice}:{speed}".encode()).hexdigest()


async def _warmup_tts_phrases():
    """
    TTS 高频短句预热：启动时用 Edge TTS 预合成，存 Redis
    不占腾讯云并发额度，永久缓存
    """
    import base64
    phrases = [p.strip() for p in settings.tts_warmup_phrases.split(",") if p.strip()]
    if not phrases:
        return
    print(f"   TTS 预热: {len(phrases)} 条短句...")
    for phrase in phrases:
        try:
            # 用 Edge TTS 预合成（免费、无并发限制）
            audio_bytes = await edge_tts(phrase, voice="female_warm", speed=0.9)
            audio_b64 = base64.b64encode(audio_bytes).decode()
            cache_key = _get_tts_cache_key(phrase, "female_warm", 90)
            if async_redis_client:
                try:
                    await async_redis_client.setex(f"tts_cache:{cache_key}", 30 * 24 * 3600, audio_b64)
                except Exception:
                    pass
            _tts_memory_cache[cache_key] = audio_b64
        except Exception as e:
            print(f"   TTS 预热失败 '{phrase}': {e}")
    print(f"   TTS 预热: ✅ {len(_tts_memory_cache)} 条已缓存")


async def _tts_queue_worker():
    """
    TTS 队列消费协程：Semaphore 满时，请求进入 _tts_wait_queue
    VIP 用户（priority=0）优先被消费
    """
    while True:
        try:
            # 优先获取 VIP 项，3秒内没有 VIP 则消费普通请求
            item = None
            # 扫描队列找 VIP
            VIP_TIMEOUT = 3.0
            deadline = asyncio.get_event_loop().time() + VIP_TIMEOUT
            for i in range(_tts_wait_queue.qsize()):
                try:
                    candidate = _tts_wait_queue.get_nowait()
                    if candidate[0] == 0:  # VIP
                        item = candidate
                        break
                    else:
                        # 非 VIP 放回队尾
                        await _tts_wait_queue.put(candidate)
                except asyncio.QueueEmpty:
                    break

            if item is None:
                try:
                    item = await asyncio.wait_for(
                        _tts_wait_queue.get(),
                        timeout=VIP_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    continue

            _, evt, text, voice, speed = item
            try:
                async for chunk in tencent_tts_stream_sse(text, voice=voice, speed=speed):
                    await evt.put(chunk)
                await evt.put(None)  # 结束信号
            except Exception as e:
                print(f"[_tts_queue] error: {e}")
                await evt.put(None)
        except Exception as e:
            print(f"[_tts_queue] worker error: {e}")
            await asyncio.sleep(1)


async def _warmup_asr_pool():
    """
    ASR 连接预热：启动时预先建立若干 ASR WS 连接，
    放入连接池供首次请求使用（节省 50-150ms 握手时间）
    """
    # TencentASRStreamConnector 在 main.py 中定义，lifespan 调用时已存在
    print(f"   ASR 预热: 建立 {settings.asr_warmup_connections} 条连接...")
    warmup_creds = await tencent_pool.get_credential()
    for i in range(settings.asr_warmup_connections):
        try:
            conn = TencentASRStreamConnector(
                str(warmup_creds.app_id),
                warmup_creds.secret_id,
                warmup_creds.secret_key,
                engine_model_type="16k_zh"
            )
            await conn.connect(timeout=5.0)
            _asr_warmup_pool.append(conn)
            print(f"   ASR 预热连接 {i+1} ✅")
        except Exception as e:
            print(f"   ASR 预热连接 {i+1} 失败: {e}")
    print(f"   ASR 预热: ✅ {len(_asr_warmup_pool)} 条可用")

_asr_warmup_pool: list = []


# ==================== Edge TTS（免费，无需 API Key） ====================

EDGE_TTS_VOICES = {
    "female_warm":  "zh-CN-XiaoxiaoNeural",   # 温暖女声（默认）
    "male_calm":    "zh-CN-YunxiNeural",      # 平静男声
    "female_young": "zh-CN-XiaoyiNeural",     # 轻柔女声
}

EDGE_TTS_RATE_MAP = {
    "female_warm":  "-5%",
    "male_calm":    "+0%",
    "female_young": "-10%",
}

async def edge_tts(text: str, voice: str = "female_warm", speed: float = 0.9) -> bytes:
    """
    调用 Edge TTS（免费），返回 mp3 音频字节
    voice: female_warm | male_calm | female_young
    speed: 0.5-2.0
    """
    import edge_tts
    import tempfile, os

    voice_id = EDGE_TTS_VOICES.get(voice, EDGE_TTS_VOICES["female_warm"])
    rate_pct = int((speed - 1.0) * 100)
    rate_str = f"{rate_pct:+d}%" if rate_pct != 0 else "+0%"

    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp_path = tmp.name
    tmp.close()

    cm = edge_tts.Communicate(text[:500], voice_id, rate=rate_str)
    await cm.save(tmp_path)

    with open(tmp_path, "rb") as f:
        audio_bytes = f.read()
    os.unlink(tmp_path)
    return audio_bytes

# ==================== ASR（通过千问 API） ====================

async def qwen_asr(audio_data: bytes, filename: str = "audio.mp3") -> str:
    """
    调用千问 ASR API，返回识别文字
    支持：mp3/wav/m4a/amr
    """
    if not settings.minimax_api_key:
        raise HTTPException(status_code=503, detail="ASR 未配置")

    files = {"file": (filename, audio_data, "audio/mpeg")}
    data = {"model": "qwen-audio-asr", "language": "zh"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.qwen_base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.minimax_api_key}"},
            files=files,
            data=data
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=f"ASR Error: {resp.text}")
        result = resp.json()
        return result.get("text", result.get("results", [{}])[0].get("text", ""))

# ==================== 腾讯云流式 TTS ====================

def tencent_sign(host: str, path: str, query_params: dict, secret_key: str) -> str:
    """通用 HMAC-SHA1 + Base64 签名（ASR HTTPS / TTS v2）"""
    import base64, urllib.parse
    items = sorted((k, v) for k, v in query_params.items() if k != 'Signature')
    qs = '&'.join(f"{k}={v}" for k, v in items)
    string_to_sign = f"GET{host}{path}?{qs}"
    sig = hmac.new(secret_key.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    return base64.b64encode(sig).decode()

def tencent_tts_sign_v2(query_params: dict, secret_key: str) -> str:
    """
    生成腾讯云流式TTS v2 API签名（HMAC-SHA1 + Base64）
    签名原文: GETtts.cloud.tencent.com/stream_wsv2?{排序后的query参数字符串}
    """
    # 按key字典序排序（不含signature）
    sorted_items = sorted((k, v) for k, v in query_params.items() if k != 'Signature')
    query_str = '&'.join(f"{k}={v}" for k, v in sorted_items)
    string_to_sign = f"GETtts.cloud.tencent.com/stream_wsv2?{query_str}"
    sig = hmac.new(
        secret_key.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1
    ).digest()
    import base64
    return base64.b64encode(sig).decode("utf-8")


TENCENT_TTS_VOICES = {
    "female_warm":  "101010",      # 中文多情感女声-小贝（更自然，支持情感）
    "male_calm":    "101011",      # 中文多情感男声-华阳
    "female_young": "101012",      # 中文多情感女声-香香
}

# 同步 TextToVoice API 使用的 VoiceType（非流式）
TENCENT_TTS_VOICES_SYNC = {
    "female_warm":  101010,   # 中文多情感女声-小贝
    "male_calm":    101011,   # 中文多情感男声-华阳
    "female_young": 101012,   # 中文多情感女声-香香
}


def _get_real_time() -> int:
    """
    获取真实当前 Unix 时间戳（秒）。
    服务器时钟漂移（Azure VM 常见问题），直接用 time.time() 会导致腾讯云签名过期。
    改用 httpx 请求外网 NTP 服务器时间做修正。
    """
    import socket, struct
    try:
        # 连接外网 NTP（pool.ntp.org 的某个 server）
        NTP_SERVER = "pool.ntp.org"
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3.0)
        # NTP version 4, mode 3 (client)
        pkt = b'\x1b' + b'\x00' * 47
        sock.sendto(pkt, (NTP_SERVER, 123))
        data, _ = sock.recvfrom(1024)
        sock.close()
        # NTP timestamps are 64-bit unsigned fixed-point, big-endian
        # The integer part starts at byte 40
        from struct import unpack
        integer_part = unpack('!I', data[40:44])[0]
        # Convert NTP epoch (Jan 1 1900) to Unix epoch (Jan 1 1970): subtract 2208988800
        unix_ts = integer_part - 2208988800
        return unix_ts
    except Exception as e:
        print(f"[NTP] 时间同步失败，使用本地时间: {e}")
        return int(time.time())


def _tencent_tts_sync_blocking(text: str, voice: str, speed: float, appid: str, secret_id: str, secret_key: str, voice_type: int) -> bytes:
    """同步 TTS，运行在线程池中避免阻塞事件循环"""
    import httpx, json

    host, service, version, action, region = "tts.tencentcloudapi.com", "tts", "2019-08-23", "TextToVoice", "ap-guangzhou"
    payload = json.dumps({
        "Text": text[:500], "SessionId": uuid.uuid4().hex, "Volume": 0, "Speed": speed,
        "ProjectId": 0, "ModelType": 1, "VoiceType": voice_type, "PrimaryLanguage": 1,
        "SampleRate": 16000, "Codec": "mp3", "EnableSubtitle": False,
    })

    def _hmac_sha256(key, msg): return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
    def _sha256_hex(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()

    real_ts = _get_real_time()
    timestamp = str(real_ts)
    from datetime import timezone
    date = datetime.fromtimestamp(real_ts, tz=timezone.utc).strftime("%Y-%m-%d")

    canonical_request = f"POST\n/\n\ncontent-type:application/json\nhost:{host}\n\ncontent-type;host\n{_sha256_hex(payload)}"
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = f"TC3-HMAC-SHA256\n{timestamp}\n{credential_scope}\n{_sha256_hex(canonical_request)}"
    secret_date = _hmac_sha256(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, service)
    secret_signing = _hmac_sha256(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    headers = {
        "Authorization": f"TC3-HMAC-SHA256 Credential={secret_id}/{credential_scope}, SignedHeaders=content-type;host, Signature={signature}",
        "Content-Type": "application/json", "Host": host,
        "X-TC-Action": action, "X-TC-Timestamp": timestamp, "X-TC-Version": version, "X-TC-Region": region,
    }

    resp = httpx.post(f"https://{host}/", headers=headers, content=payload, timeout=30.0)
    if resp.status_code != 200:
        raise Exception(f"[腾讯TTS] HTTP {resp.status_code}")
    result = resp.json()
    err = result.get("Response", {}).get("Error", {})
    if err:
        raise Exception(f"[腾讯TTS] {err.get('Code')}: {err.get('Message')}")
    audio_b64 = result.get("Response", {}).get("Audio", "")
    if not audio_b64:
        raise Exception("[腾讯TTS] 未返回音频数据")
    return base64.b64decode(audio_b64)


def _tencent_tts_sync_blocking(text: str, voice: str, speed: float, appid: str, secret_id: str, secret_key: str, voice_type: int) -> bytes:
    """同步 TTS，运行在线程池中避免阻塞事件循环"""
    import httpx, json

    host, service, version, action, region = "tts.tencentcloudapi.com", "tts", "2019-08-23", "TextToVoice", "ap-guangzhou"
    payload = json.dumps({
        "Text": text[:500], "SessionId": uuid.uuid4().hex, "Volume": 0, "Speed": speed,
        "ProjectId": 0, "ModelType": 1, "VoiceType": voice_type, "PrimaryLanguage": 1,
        "SampleRate": 16000, "Codec": "mp3", "EnableSubtitle": False,
    })

    def _hmac_sha256(key, msg): return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
    def _sha256_hex(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()

    real_ts = _get_real_time()
    timestamp = str(real_ts)
    from datetime import timezone
    date = datetime.fromtimestamp(real_ts, tz=timezone.utc).strftime("%Y-%m-%d")

    canonical_request = f"POST\n/\n\ncontent-type:application/json\nhost:{host}\n\ncontent-type;host\n{_sha256_hex(payload)}"
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = f"TC3-HMAC-SHA256\n{timestamp}\n{credential_scope}\n{_sha256_hex(canonical_request)}"
    secret_date = _hmac_sha256(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, service)
    secret_signing = _hmac_sha256(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    headers = {
        "Authorization": f"TC3-HMAC-SHA256 Credential={secret_id}/{credential_scope}, SignedHeaders=content-type;host, Signature={signature}",
        "Content-Type": "application/json", "Host": host,
        "X-TC-Action": action, "X-TC-Timestamp": timestamp, "X-TC-Version": version, "X-TC-Region": region,
    }

    resp = httpx.post(f"https://{host}/", headers=headers, content=payload, timeout=30.0)
    if resp.status_code != 200:
        raise Exception(f"[腾讯TTS] HTTP {resp.status_code}")
    result = resp.json()
    err = result.get("Response", {}).get("Error", {})
    if err:
        raise Exception(f"[腾讯TTS] {err.get('Code')}: {err.get('Message')}")
    audio_b64 = result.get("Response", {}).get("Audio", "")
    if not audio_b64:
        raise Exception("[腾讯TTS] 未返回音频数据")
    return base64.b64decode(audio_b64)


async def tencent_tts_sync(text: str, voice: str = "female_warm", speed: float = 0) -> bytes:
    """腾讯云同步 TTS - 运行在线程池中"""
    if not all([settings.tencentcloud_app_id, settings.tencentcloud_secret_id, settings.tencentcloud_secret_key]):
        raise Exception("腾讯云 TTS 未配置")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _tencent_tts_sync_blocking,
        text, voice, speed,
        str(settings.tencentcloud_app_id),
        settings.tencentcloud_secret_id,
        settings.tencentcloud_secret_key,
        TENCENT_TTS_VOICES_SYNC.get(voice, TENCENT_TTS_VOICES_SYNC["female_warm"])
    )





async def tencent_tts_stream(text: str, voice: str = "female_warm", speed: int = 0, credential: TencentCredential = None) -> AsyncGenerator[bytes, None]:
    """
    腾讯云流式 TTS（WebSocket 流式，Codec=mp3）
    voice: female_warm(610000001) | male_calm(610000002) | female_young(610000003)
    speed: 50-200（默认90）
    credential: 可选，指定腾讯云账号；None 时使用默认主账号
    返回: MP3 二进制分片（WebSocket 二进制帧）
    """
    cred = credential
    if cred is None:
        if not all([settings.tencentcloud_app_id, settings.tencentcloud_secret_id, settings.tencentcloud_secret_key]):
            raise Exception("腾讯云 TTS 未配置")
        cred = TencentCredential(settings.tencentcloud_app_id, settings.tencentcloud_secret_id, settings.tencentcloud_secret_key)

    import websocket

    appid = int(cred.app_id)
    secret_id = cred.secret_id
    secret_key = cred.secret_key
    voice_id = TENCENT_TTS_VOICES.get(voice, TENCENT_TTS_VOICES["female_warm"])

    async def _ws_stream():
        loop = asyncio.get_event_loop()
        auth_timestamp = str(int(time.time()))
        expired = str(int(time.time()) + 3600)
        session_id = uuid.uuid4().hex

        query_params = {
            "Action": "TextToStreamAudioWS",
            "AppId": appid,
            "SecretId": secret_id,
            "Timestamp": auth_timestamp,
            "Expired": expired,
            "SessionId": session_id,
            "VoiceType": int(voice_id),
            "Codec": "mp3",
            "SampleRate": "16000",
            "Speed": "0",
            "Volume": "0",
            "EnableSubtitle": "false",
            "Text": text[:500],
        }
        sorted_items = sorted((k, v) for k, v in query_params.items() if k != 'Signature')
        qs_raw = '&'.join('{}={}'.format(k, v) for k, v in sorted_items)
        string_to_sign = 'GETtts.cloud.tencent.com/stream_ws?' + qs_raw
        sig = hmac.new(secret_key.encode(), string_to_sign.encode(), hashlib.sha1).digest()
        signature = base64.b64encode(sig).decode()
        query_params['Signature'] = signature

        import urllib.parse
        qs_enc = []
        for k, v in sorted_items:
            qs_enc.append('{}={}'.format(urllib.parse.quote(str(k)), urllib.parse.quote(str(v))))
        qs_enc.append('Signature=' + urllib.parse.quote(signature))
        ws_url = 'wss://tts.cloud.tencent.com/stream_ws?' + '&'.join(qs_enc)

        qianbao = asyncio.Queue()
        done = asyncio.Event()
        got_audio = False

        def on_message(ws, message):
            nonlocal got_audio
            if isinstance(message, bytes):
                if len(message) > 4:
                    got_audio = True
                    loop.call_soon_threadsafe(qianbao.put_nowait, message)
                return
            try:
                data = json.loads(message)
                err_code = data.get('code')
                if err_code and err_code != 0:
                    print(f"[腾讯TTS] error {err_code}: {data.get('message', '')}")
                    loop.call_soon_threadsafe(done.set)
                    return
                audio_b64 = data.get('audio', '')
                if audio_b64:
                    got_audio = True
                    chunk = base64.b64decode(audio_b64)
                    loop.call_soon_threadsafe(qianbao.put_nowait, chunk)
                if data.get('done'):
                    loop.call_soon_threadsafe(done.set)
            except Exception as e:
                print(f"[腾讯TTS] on_message error: {e}")
                loop.call_soon_threadsafe(done.set)

        def on_error(ws, error):
            print(f"[腾讯TTS] WebSocket error: {error}")
            loop.call_soon_threadsafe(done.set)

        def on_close(ws, code, reason):
            print(f"[腾讯TTS] WebSocket closed: {code} {reason}")
            loop.call_soon_threadsafe(done.set)

        def on_open(ws):
            pass

        ws_client = websocket.WebSocketApp(
            ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )

        def run_ws():
            ws_client.run_forever(ping_interval=30, ping_timeout=20)

        import threading
        t = threading.Thread(target=run_ws, daemon=True)
        t.start()

        try:
            while not done.is_set():
                try:
                    chunk = await asyncio.wait_for(qianbao.get(), timeout=1.0)
                    yield chunk
                except asyncio.TimeoutError:
                    continue
            if not got_audio:
                raise Exception("[腾讯TTS] 未收到任何音频数据")
        finally:
            ws_client.close()
            t.join(timeout=5)

    async for chunk in _ws_stream():
        yield chunk



async def tencent_tts_stream_sse(text: str, voice: str = "female_warm", speed: int = 0):
    """流式 TTS：带缓存 + 并发控制 + 多账号负载均衡"""
    import base64
    cache_key = _get_tts_cache_key(text, voice, speed)

    # ✅ 1. 内存缓存命中
    cached_b64 = _tts_memory_cache.get(cache_key)
    if cached_b64:
        print(f"[TTS-cache] memory hit: {text[:20]}...")
        yield {"event": "tts_sentence", "index": 0, "audio_base64": cached_b64, "text": text, "done": False}
        yield {"event": "tts_sentence", "index": 1, "audio_base64": "", "text": "", "done": True}
        return

    # ✅ 2. Redis 缓存命中
    if async_redis_client:
        try:
            cached_b64 = await async_redis_client.get(f"tts_cache:{cache_key}")
            if cached_b64:
                print(f"[TTS-cache] redis hit: {text[:20]}...")
                _tts_memory_cache[cache_key] = cached_b64
                yield {"event": "tts_sentence", "index": 0, "audio_base64": cached_b64, "text": text, "done": False}
                yield {"event": "tts_sentence", "index": 1, "audio_base64": "", "text": "", "done": True}
                return
        except Exception as e:
            print(f"[TTS-cache] redis error: {e}")

    # ✅ 3. Semaphore 并发控制（避免超过腾讯云 20 路上限）
    async with _tts_semaphore:
        try:
            # 多账号轮询选择
            cred = await tencent_pool.get_credential()
            chunks = []
            async for chunk in tencent_tts_stream(text, voice=voice, speed=speed, credential=cred):
                chunks.append(chunk)
            merged = b''.join(chunks)
            if merged:
                audio_b64 = base64.b64encode(merged).decode()
                # ✅ 4. 缓存短句（≤20 字）
                if len(text) <= 20:
                    _tts_memory_cache[cache_key] = audio_b64
                    # 限制内存缓存大小
                    if len(_tts_memory_cache) > _MAX_TTS_MEMORY_CACHE:
                        oldest = next(iter(_tts_memory_cache))
                        del _tts_memory_cache[oldest]
                    if async_redis_client:
                        try:
                            await async_redis_client.setex(f"tts_cache:{cache_key}", 7 * 24 * 3600, audio_b64)
                        except Exception:
                            pass
                yield {"event": "tts_sentence", "index": 0, "audio_base64": audio_b64, "text": text, "done": False}
            yield {"event": "tts_sentence", "index": 1, "audio_base64": "", "text": "", "done": True}
        except Exception as e:
            print(f"[TTS-stream-sse] error: {e}")
            yield {"event": "tts_sentence", "index": 0, "audio_base64": "", "text": "", "done": True, "error": str(e)}



# ==================== 腾讯云实时 ASR ====================

async def tencent_asr_stream(audio_data: bytes, filename: str = "audio.mp3") -> str:
    """
    腾讯云 ASR（SDK 短句识别，稳定可靠）
    使用腾讯云 SDK SentenceRecognition API，上传音频并同步返回识别结果。
    MP3 格式直接上传（跳过 ffmpeg 转换），其他格式转为 WAV。
    """
    if not all([settings.tencentcloud_app_id, settings.tencentcloud_secret_id, settings.tencentcloud_secret_key]):
        raise Exception("腾讯云 ASR 未配置")

    import base64, subprocess, tempfile, os

    print(f"[腾讯ASR] 收到音频 {len(audio_data)} 字节, filename={filename}")

    suffix = os.path.splitext(filename)[1] or '.mp3'
    asr_data = audio_data
    voice_format = "mp3"

    # 非 MP3 格式才需要 ffmpeg 转换
    if suffix.lower() not in ('.mp3',):
        tmp_in = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp_out = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        tmp_in.write(audio_data)
        tmp_in.close()
        tmp_out.close()

        is_pcm = suffix.lower() in ('.pcm', '.s16le', '.raw')
        cmd = ['ffmpeg', '-y']
        if is_pcm:
            cmd.extend(['-f', 's16le', '-ar', '16000', '-ac', '1'])
        cmd.extend(['-i', tmp_in.name, '-ar', '16000', '-ac', '1', '-acodec', 'pcm_s16le', '-f', 'wav', tmp_out.name])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                print(f"[腾讯ASR] ffmpeg 转换失败: {result.stderr[-300:]}")
                raise Exception(f"ffmpeg 转换失败: {result.stderr[-200:]}")

            with open(tmp_out.name, 'rb') as f:
                asr_data = f.read()
            voice_format = "wav"
            print(f"[腾讯ASR] ffmpeg 转换后 WAV: {len(asr_data)} 字节")
        finally:
            os.unlink(tmp_in.name)
            os.unlink(tmp_out.name)
    else:
        print(f"[腾讯ASR] MP3 直接上传，跳过 ffmpeg")

    # 使用腾讯云 SDK 调用 ASR
    from tencentcloud.common import credential
    from tencentcloud.asr.v20190614 import models, asr_client

    cred = credential.Credential(settings.tencentcloud_secret_id, settings.tencentcloud_secret_key)
    client = asr_client.AsrClient(cred, "")

    req = models.SentenceRecognitionRequest()
    req.SubServiceType = 2
    req.VoiceFormat = voice_format
    req.EngSerViceType = "16k_zh"
    req.SourceType = 1
    req.Data = base64.b64encode(asr_data).decode()
    req.DataLen = len(asr_data)
    req.ProjectId = 0

    print(f"[腾讯ASR] 上传 {len(asr_data)} 字节进行识别")
    resp = client.SentenceRecognition(req)
    text = resp.Result or ""
    print(f"[腾讯ASR] 识别结果: '{text}'")
    return text



@app.get("/api/v1/asr/signature")
async def asr_v2_signature(user_id: str = ""):
    """
    生成腾讯云 ASR v2 WebSocket 签名 URL，供小程序前端直连腾讯云
    返回: { voice_id, wss_url }
    """
    import uuid, time
    voice_id = str(uuid.uuid4())
    ts = int(time.time())
    params = {
        "engine_model_type": "16k_zh",
        "expired": ts + 86400,
        "nonce": int(time.time() * 1000) % 1000000000,
        "secretid": settings.tencentcloud_secret_id,
        "timestamp": ts,
        "voice_format": 1,
        "voice_id": voice_id,
    }
    sorted_items = sorted(params.items())
    query_str = "&".join(f"{k}={v}" for k, v in sorted_items)
    path = f"/asr/v2/{settings.tencentcloud_app_id}"
    path_query = f"{path}?{query_str}"
    sign_origin = f"asr.cloud.tencent.com{path_query}"
    sig = base64.b64encode(
        hmac.new(settings.tencentcloud_secret_key.encode(), sign_origin.encode(), hashlib.sha1).digest()
    ).decode()
    wss_url = f"wss://asr.cloud.tencent.com{path_query}&signature={urllib.parse.quote(sig)}"
    print(f"[ASR-signature] voice_id={voice_id}")
    return {"voice_id": voice_id, "wss_url": wss_url}


@app.post("/api/v1/asr/quick")
async def asr_quick_upload(file: UploadFile = File(...)):
    """
    快速 ASR 识别（HTTP 直传，绕过 WebSocket 开销）
    前端录音完成后直接上传文件，后端立即识别返回
    支持 mp3/wav/pcm，最大 2MB
    """
    audio_data = await file.read()
    if len(audio_data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="音频文件不能超过2MB")
    if len(audio_data) == 0:
        raise HTTPException(status_code=400, detail="音频文件为空")
    if not _validate_audio_content(audio_data, file.filename or ""):
        raise HTTPException(status_code=400, detail="不支持的文件类型，仅支持 mp3/wav/pcm")

    try:
        text = await tencent_asr_stream(audio_data, file.filename or "audio.mp3")
        return {"text": text, "confidence": "high", "engine": "tencent", "source": "quick_upload"}
    except Exception as e:
        print(f"[ASR-Quick] 识别失败: {e}")
        raise HTTPException(status_code=500, detail=f"识别失败: {str(e)}")





# ---------- Chat ----------
@app.post("/api/v1/chat")
async def chat(req: ChatRequest, user: AuthUser = Depends(get_current_user)):
    session_id = req.session_id or f"session_{datetime.now().strftime('%Y%m%d')}"
    user_id = user.user_id

    # 1. 焦虑检测
    detection = detect_anxiety(req.message)
    print(f"[焦虑检测] level={detection['level']} trigger={detection['trigger']}")

    # 2. 获取历史（含跨会话记忆作为上下文）
    history = get_session_history(user_id, session_id)
    memory = get_user_memory(user_id)

    # 3. 构建消息（注入记忆上下文）
    memory_context = ""
    if memory.get("concerns"):
        top = sorted(memory["triggers"].items(), key=lambda x: -x[1])[:3]
        concerns = "、".join([f"{k}({v}次)" for k, v in top])
        memory_context = f"\n[用户历史] 近日常见担忧：{concerns}。最后话题：{memory.get('last_topic', '无')}"

    full_messages = [
        {"role": "system", "content": CBT_SYSTEM_PROMPT + memory_context}
    ] + [{"role": m.role, "content": m.content} for m in history]
    full_messages.append({"role": "user", "content": req.message})

    # 4. 流式生成
    response_text = ""
    async for chunk in minimax_chat(full_messages):
        response_text += chunk

    # 5. 保存
    history.append(Message(role="user", content=req.message))
    history.append(Message(role="assistant", content=response_text))
    save_session_history(user_id, session_id, history)
    update_user_memory(user_id, req.message, response_text)

    return {
        "session_id": session_id,
        "response": response_text,
        "anxiety": detection,
        "memory": {
            "streak_days": get_user_memory(user_id).get("streak_days", 0),
            "top_concerns": sorted(get_user_memory(user_id).get("triggers", {}).items(), key=lambda x: -x[1])[:3]
        }
    }

@app.post("/api/v1/chat/stream")
async def chat_stream(req: ChatRequest, user: AuthUser = Depends(get_current_user)):
    session_id = req.session_id or f"session_{datetime.now().strftime('%Y%m%d')}"
    user_id = user.user_id
    detection = detect_anxiety(req.message)

    async def sse():
        yield f"data: {json.dumps({'event': 'anxiety', 'data': detection}, ensure_ascii=False)}\n\n"

        history = get_session_history(user_id, session_id)
        memory = get_user_memory(user_id)
        memory_context = ""
        if memory.get("concerns"):
            top = sorted(memory["triggers"].items(), key=lambda x: -x[1])[:3]
            concerns = "、".join([f"{k}({v}次)" for k, v in top])
            memory_context = f"\n[用户历史] 近日常见担忧：{concerns}。最后话题：{memory.get('last_topic', '无')}"

        full_messages = [{"role": "system", "content": CBT_SYSTEM_PROMPT + memory_context}]
        full_messages += [{"role": m.role, "content": m.content} for m in history]
        full_messages.append({"role": "user", "content": req.message})

        full_resp = ""
        async for chunk in minimax_chat(full_messages):
            full_resp += chunk
            yield f"data: {json.dumps({'event': 'chunk', 'data': chunk}, ensure_ascii=False)}\n\n"

        # 保存
        history.append(Message(role="user", content=req.message))
        history.append(Message(role="assistant", content=full_resp))
        save_session_history(user_id, session_id, history)
        update_user_memory(user_id, req.message, full_resp)

        yield f"data: {json.dumps({'event': 'done', 'session_id': session_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ---------- CBT-I Chat (v2) ----------
from cbt_manager import cbt_manager, SessionPhase, user_profile_manager, RiskPredictor


@app.post("/api/v1/chat/cbt")
async def chat_cbt(req: ChatRequest, user: AuthUser = Depends(get_current_user)):
    """
    CBT-I 动态会话（非流式）
    
    使用新的 CBT-I 状态机，根据会话状态和情绪动态生成响应。
    替代固定脚本模式，实现真正的 AI 驱动的 CBT-I 引导。
    免费版：AI 语音 3分钟/天 + AI 文本 10分钟/天
    基础 Pro：AI 语音 15小时/月 + AI 文本 15小时/月（30元/月）
    核心 Pro：AI 语音 30小时/月 + AI 文本 30小时/月（45元/月）
    """
    session_id = req.session_id or f"cbt_{datetime.now().strftime('%Y%m%d')}"
    user_id = user.user_id

    # ── 时间限额检查（所有 AI 生成内容均计入）──
    # 语音模式：检查 TTS 时长
    q = _get_remaining_quota(user_id)
    estimated_tts = _estimate_tts_duration(req.message)
    if q['voice_remaining'] - estimated_tts < -5:
        period = '今日' if q['period'] == 'day' else '本月'
        raise HTTPException(
            status_code=403,
            detail={
                "error": "quota_reached",
                "message": f"{period} AI 语音时长已用完。升级到「基础 Pro」享 15 小时/月，或「核心 Pro」享 30 小时/月。",
                "quota": q,
            }
        )

    # 1. 获取历史记录
    history = get_session_history(user_id, session_id)

    # 2. 获取用户记忆 + 档案（提前，避免分支间未定义）
    memory = get_user_memory(user_id)
    profile = await user_profile_manager.load_profile(user_id)

    # 3. 让 CBT 管理器处理状态和决策（传入档案用于个性化阈值和语气）
    cbt_result = cbt_manager.process_message(
        user_id=user_id,
        session_id=session_id,
        user_message=req.message,
        conversation_history=[{"role": m.role, "content": m.content} for m in history],
        profile=profile
    )

    #音色偏好注入：用户设定音色覆盖 response_type 默认
    try:
        preferred = profile.get("preferred_voice", "female_warm")
        if preferred and preferred != "female_warm":
            tp = cbt_result.get("tts_params", {})
            tp["voice"] = preferred
            cbt_result["tts_params"] = tp
    except Exception:
        pass

    print(f"[CBT] phase={cbt_result['next_phase']} type={cbt_result['response_type']} anxiety={cbt_result['state_update'].get('anxiety_level')}")

    # 4. 如果是特殊响应类型（呼吸/PMR/关闭仪式/安全协议），直接返回
    if cbt_result['response_type'] in ['breathing', 'pmr', 'closure', 'safety']:
        history.append(Message(role="user", content=req.message))
        history.append(Message(role="assistant", content=cbt_result['content']))
        save_session_history(user_id, session_id, history)
        # L2: 记录特殊响应（技术触发）
        if RAG_AVAILABLE and session_logger:
            log_cbt_turn_with_rag(
                user_message=req.message,
                assistant_response=cbt_result['content'],
                technique_used=cbt_result['response_type'],
                cbt_state=cbt_result['state_update'],
                session_context=memory,
            user_id=user_id,
            session_id=session_id
            )
        # 记录字数（AI 回复长度）和语音时长（TTS 估算）
        _record_text_usage(user_id, len(cbt_result['content']))
        _record_voice_usage(user_id, _estimate_tts_duration(cbt_result['content']))

        # ── L4: 异步更新用户档案 & 结构化风险转介 ───────────────────
        _meta = cbt_result.get("_meta", {})
        if _meta.get("should_update_profile"):
            summary = _meta.get("session_summary", {})
            asyncio.create_task(_async_update_profile(user_id, summary))
            # 使用结构化转介流程替代简单消息拼接
            referral = await RiskPredictor.trigger_referral(user_id, user_profile_manager)
            if referral.get("triggered"):
                cbt_result["content"] = cbt_result["content"] + " " + referral["referral_message"]
                # 高风险时通知运营
                if referral.get("should_notify_admin"):
                    try:
                        from alert_manager import send_alert
                        send_alert({
                            "level": "🔴不合格",
                            "title": "高风险用户转介预警",
                            "message": f"用户 {user_id[:16]}... 触发主动转介：{referral['reason']}",
                            "user_id": user_id,
                            "referral_type": referral["referral_type"],
                            "resources": referral["referral_resources"],
                        })
                    except Exception as e:
                        print(f"[Alert] 转介告警发送失败: {e}")

        return {
            "session_id": session_id,
            "response": cbt_result['content'],
            "response_type": cbt_result['response_type'],
            "tts_params": cbt_result['tts_params'],
            "next_phase": cbt_result['next_phase'],
            "should_close": cbt_result.get('should_close', False),
            "cbt_state": cbt_result['state_update'],
            **({"safety_trigger": True} if cbt_result.get('safety_trigger') else {})
        }

    # 5. 否则调用 LLM 生成响应（RAG增强）
    cbt_system_prompt = _build_enhanced_system_prompt(
        user_id, session_id, cbt_result, req.message, memory=memory, profile=profile
    )

    full_messages = [
        {"role": "system", "content": cbt_system_prompt}
    ] + [{"role": m.role, "content": m.content} for m in history]
    full_messages.append({"role": "user", "content": req.message})

    response_text = ""
    async for chunk in minimax_chat(full_messages):
        response_text += chunk

    # L2: 记录对话到日志（用于L3训练数据积累）
    if RAG_AVAILABLE and session_logger:
        log_cbt_turn_with_rag(
            user_message=req.message,
            assistant_response=response_text,
            technique_used=cbt_result['response_type'],
            cbt_state=cbt_result['state_update'],
            session_context=memory,
            user_id=user_id,
            session_id=session_id
        )
        # 如果应该关闭，结束会话
        if cbt_result.get('should_close'):
            finalize_session(outcome="completed_closure")

    history.append(Message(role="user", content=req.message))
    history.append(Message(role="assistant", content=response_text))
    save_session_history(user_id, session_id, history)
    update_user_memory(user_id, req.message, response_text)

    # 记录字数（AI 回复长度）和语音时长（TTS 估算）
    _record_text_usage(user_id, len(response_text))
    _record_voice_usage(user_id, _estimate_tts_duration(response_text))

    return {
        "session_id": session_id,
        "response": response_text,
        "response_type": cbt_result['response_type'],
        "tts_params": cbt_result['tts_params'],
        "next_phase": cbt_result['next_phase'],
        "should_close": cbt_result.get('should_close', False),
        "cbt_state": cbt_result['state_update'],
        "rag_available": RAG_AVAILABLE
    }


async def _chat_events(req: ChatRequest, user_id: str):
    """CBT-I 动态会话事件生成器（SSE/WebSocket 共用核心逻辑）"""
    session_id = req.session_id or f"cbt_{datetime.now().strftime('%Y%m%d')}"
    skip_tts = getattr(req, 'skip_tts', False)

    # 时间限额检查（所有 AI 生成内容均计入）
    q = _get_remaining_quota(user_id)
    estimated_tts = _estimate_tts_duration(req.message)
    if q['voice_remaining'] - estimated_tts < -5:
        period = '今日' if q['period'] == 'day' else '本月'
        yield {"event": "error", "message": f"{period} AI 语音时长已用完。升级到「基础 Pro」享 15 小时/月，或「核心 Pro」享 30 小时/月。"}
        return

    # 1. 先发送 CBT 状态
    history = get_session_history(user_id, session_id)
    profile = await user_profile_manager.load_profile(user_id)
    cbt_result = cbt_manager.process_message(
        user_id=user_id,
        session_id=session_id,
        user_message=req.message,
        conversation_history=[{"role": m.role, "content": m.content} for m in history],
        profile=profile
    )

    # 音色偏好注入：用户设定音色覆盖 response_type 默认
    try:
        preferred = profile.get("preferred_voice", "female_warm")
        if preferred and preferred != "female_warm":
            tp = cbt_result.get("tts_params", {})
            tp["voice"] = preferred
            cbt_result["tts_params"] = tp
    except Exception:
        pass

    yield {"event": "cbt_state", "data": cbt_result}

    # 获取 TTS 参数（语速由 CBT 状态决定，不从 LLM 输出解析）
    tts_params = cbt_result.get('tts_params', {})
    base_tts_speed = tts_params.get('speed', -1)
    base_tts_voice = tts_params.get('voice', 'female_warm')

    # 2. 如果是特殊响应类型，直接返回内容（并即时合成 TTS）
    if cbt_result['response_type'] in ['breathing', 'pmr', 'closure', 'safety']:
        history.append(Message(role="user", content=req.message))
        history.append(Message(role="assistant", content=cbt_result['content']))
        save_session_history(user_id, session_id, history)
        has_yielded_tts = False
        if not skip_tts:
            try:
                sent_any = False
                async for evt in tencent_tts_stream_sse(cbt_result['content'][:120], voice=base_tts_voice, speed=base_tts_speed):
                    yield evt
                    sent_any = True
                if sent_any:
                    has_yielded_tts = True
            except Exception as e:
                print(f"[TTS-stream] special response error: {e}")
        yield {"event": "final", "content": cbt_result['content'], "should_close": cbt_result.get('should_close', False)}
        yield {"event": "done", "has_tts": has_yielded_tts}
        return

    # 3. 快速问候响应：省去 LLM 调用，直接返回预生成回复（大幅降低首响延迟）
    quick_greeting = None
    msg_norm = req.message.strip().replace('，', '').replace('。', '').replace('？', '').replace('?', '')
    if len(msg_norm) <= 6:
        greeting_map = {
            "你好": "你好呀，还没睡？",
            "嗨": "嗨，还没睡吗？",
            "在吗": "在的，你说。",
            "在不在": "在的，你说。",
            "能听到吗": "能听到，你说。",
            "能听到": "能听到，你说。",
            "听得到吗": "听得到，你说。",
            "喂": "嗯，我在听。",
            "哈喽": "哈喽，还没睡？",
            "hello": "你好呀，还没睡？",
            "你是谁": "我是知眠，你的睡前陪伴。",
        }
        for key, reply in greeting_map.items():
            if key in msg_norm:
                quick_greeting = reply
                break

    if quick_greeting:
        history.append(Message(role="user", content=req.message))
        history.append(Message(role="assistant", content=quick_greeting))
        save_session_history(user_id, session_id, history)
        yield {"event": "chunk", "data": quick_greeting}
        sent = False
        if not skip_tts:
            try:
                async for evt in tencent_tts_stream_sse(quick_greeting[:120], voice=base_tts_voice, speed=base_tts_speed):
                    yield evt
                    sent = True
            except Exception as e:
                print(f"[TTS-quick] error: {e}")
        yield {"event": "done", "session_id": session_id, "should_close": False, "has_tts": sent}
        return

    # 4. 调用 LLM 流式生成（RAG增强）
    memory = get_user_memory(user_id)
    cbt_system_prompt = _build_enhanced_system_prompt(
        user_id, session_id, cbt_result, req.message, memory=memory, profile=profile
    )

    full_messages = [
        {"role": "system", "content": cbt_system_prompt}
    ] + [{"role": m.role, "content": m.content} for m in history]
    full_messages.append({"role": "user", "content": req.message})

    full_resp = ""
    tts_buffer = ""
    sentence_end = set("，。？！…~")
    has_yielded_tts = False
    llm_error = False

    # 段落级 TTS 参数：累积 30-80 字后批量合成，减少调用次数，提升连贯性
    # 优化：降低下限阈值，LLM首个chunk立即触发TTS（首字响应提速）
    MIN_TTS_CHARS = 15
    MAX_TTS_CHARS = 80
    MAX_TTS_WAIT_MS = 600  # 加速强制刷新
    tts_last_flush_time = None

    try:
        async for chunk in minimax_chat(full_messages):
            full_resp += chunk
            tts_buffer += chunk
            yield {"event": "chunk", "data": chunk}

            # ✅ 文本模式下跳过所有 TTS 合成，加速响应
            if skip_tts:
                continue

            now_ms = asyncio.get_event_loop().time() * 1000
            if tts_last_flush_time is None:
                tts_last_flush_time = now_ms

            # 【优化】首个chunk立即触发：收到首个文本后立即合成TTS（无等待）
            if not has_yielded_tts and len(tts_buffer) >= 15:
                flush_text = tts_buffer.strip()
                if flush_text:
                    try:
                        sent_any = False
                        async for evt in tencent_tts_stream_sse(flush_text[:MAX_TTS_CHARS], voice=base_tts_voice, speed=base_tts_speed):
                            yield evt
                            sent_any = True
                        if sent_any:
                            has_yielded_tts = True
                            tts_buffer = ""
                            tts_last_flush_time = now_ms
                            print(f"[TTS-fast] first chunk streaming: {flush_text[:20]}...")
                    except Exception as e:
                        print(f"[TTS-fast] first flush error: {e}")
                


            # 段落级 TTS 累积策略（3 种触发条件）
            should_flush = False
            flush_text = ""

            # 条件1：累积达到 MAX_TTS_CHARS，强制切分（在标点处优先切分）
            if len(tts_buffer) >= MAX_TTS_CHARS:
                should_flush = True
                cut_idx = MAX_TTS_CHARS - 1
                for i in range(min(MAX_TTS_CHARS - 1, len(tts_buffer) - 1), -1, -1):
                    if tts_buffer[i] in sentence_end:
                        cut_idx = i
                        break
                flush_text = tts_buffer[:cut_idx + 1].strip()
                tts_buffer = tts_buffer[cut_idx + 1:]

            # 条件2：累积达到 MIN_TTS_CHARS 且遇到句子结束标点
            elif len(tts_buffer) >= MIN_TTS_CHARS:
                last_punct_idx = -1
                for i, ch in enumerate(tts_buffer):
                    if ch in sentence_end and i >= MIN_TTS_CHARS - 10:
                        last_punct_idx = i
                if last_punct_idx >= 0:
                    should_flush = True
                    flush_text = tts_buffer[:last_punct_idx + 1].strip()
                    tts_buffer = tts_buffer[last_punct_idx + 1:]

            # 条件3：累积时间超过 MAX_TTS_WAIT_MS，强制刷新（防止长句卡住）
            elif len(tts_buffer) >= 10 and (now_ms - tts_last_flush_time) > MAX_TTS_WAIT_MS:
                should_flush = True
                flush_text = tts_buffer.strip()
                tts_buffer = ""

            if should_flush and flush_text:
                try:
                    sent_any = False
                    async for evt in tencent_tts_stream_sse(flush_text[:MAX_TTS_CHARS], voice=base_tts_voice, speed=base_tts_speed):
                        yield evt
                        sent_any = True
                    if sent_any:
                        has_yielded_tts = True
                        print(f"[TTS-para] streaming {len(flush_text)} chars: {flush_text[:30]}...")
                except Exception as e:
                    print(f"[TTS-para] error: {e}")
                tts_last_flush_time = now_ms

        # 流结束：刷新剩余文本
        if not skip_tts and tts_buffer.strip():
            try:
                async for evt in tencent_tts_stream_sse(tts_buffer[:MAX_TTS_CHARS].strip(), voice=base_tts_voice, speed=base_tts_speed):
                    yield evt
                    has_yielded_tts = True
            except Exception as e:
                print(f"[TTS-para] final error: {e}")
    except Exception as e:
        print(f"[LLM-stream] 生成失败，使用兜底回复: {e}")
        llm_error = True
        fallback = "我在，继续说。"
        full_resp = fallback
        yield {"event": "chunk", "data": fallback}

    history.append(Message(role="user", content=req.message))
    history.append(Message(role="assistant", content=full_resp))
    save_session_history(user_id, session_id, history)
    update_user_memory(user_id, req.message, full_resp)

    # L2: 记录对话到日志（用于L3训练数据积累）
    if RAG_AVAILABLE and session_logger and not llm_error:
        try:
            log_cbt_turn_with_rag(
                user_message=req.message,
                assistant_response=full_resp,
                technique_used=cbt_result['response_type'],
                cbt_state=cbt_result['state_update'],
                session_context=memory,
                user_id=user_id,
                session_id=session_id
            )
            if cbt_result.get('should_close'):
                finalize_session(outcome="completed_closure")
        except Exception as e:
            print(f"[L2-log] 日志记录失败（非关键）: {e}")

    yield {"event": "done", "session_id": session_id, "should_close": cbt_result.get('should_close', False), "has_tts": has_yielded_tts}


@app.post("/api/v1/chat/cbt/stream")
async def chat_cbt_stream(req: ChatRequest, user: AuthUser = Depends(get_current_user)):
    """
    CBT-I 动态会话（流式 SSE 版本）
    """
    user_id = user.user_id
    update_streak(user_id)

    async def sse():
        async for event in _chat_events(req, user_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    return StreamingResponse(sse(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.websocket("/api/v1/chat/ws")
async def chat_ws(websocket: WebSocket):
    """CBT-I 动态会话（WebSocket 真流式版本）
    客户端需在连接时通过 query 参数传递 JWT token：
    ws://host/api/v1/chat/ws?token=<jwt>
    """
    # 从 query 参数获取 token
    token = websocket.query_params.get("token", "")
    if not token:
        await websocket.close(code=4001, reason="缺少 token 参数")
        return
    user = verify_jwt_token(token)
    if not user:
        await websocket.close(code=4001, reason="Token 无效或已过期")
        return
    user_id = user.user_id

    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            req = ChatRequest(**data)
            async for event in _chat_events(req, user_id):
                await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass




# ── 用量查询接口 ───────────────────────────────────────────
@app.get("/api/v1/usage")
async def get_usage_status(user: AuthUser = Depends(get_current_user)):
    user_id = user.user_id
    """
    查询用户 AI 用量（免费版按天，Pro 按月）
    """
    q = _get_remaining_quota(user_id)
    tier = q['tier']
    tier_name = {'free': '免费版', 'basic': '基础 Pro', 'core': '核心 Pro'}[tier]
    period = q['period']
    return {
        "tier": tier,
        "tier_name": tier_name,
        "period": period,
        "text": {
            "used": q['text_used'],
            "limit": q['text_limit'],
            "remaining": q['text_remaining'],
            "limit_minutes": q['text_limit'] // 300,  # 300字/分钟
            "remaining_minutes": q['text_remaining'] // 300,
        },
        "voice": {
            "used": q['voice_used'],
            "limit": q['voice_limit'],
            "remaining": q['voice_remaining'],
            "limit_minutes": q['voice_limit'] // 60,
            "remaining_minutes": q['voice_remaining'] // 60,
        },
        "date": datetime.now().strftime('%Y-%m-%d') if period == 'day' else datetime.now().strftime('%Y-%m'),
    }


@app.post("/api/v1/chat/cbt/reset")
async def chat_cbt_reset(req: ChatRequest, user: AuthUser = Depends(get_current_user)):
    """重置 CBT-I 会话状态"""
    user_id = user.user_id
    session_id = req.session_id or f"cbt_{datetime.now().strftime('%Y%m%d')}"
    cbt_manager.reset_session(user_id, session_id)
    return {"status": "ok", "message": "CBT-I session reset"}


@app.get("/api/v1/chat/history")
async def get_chat_history(user: AuthUser = Depends(get_current_user), session_id: str = None):
    user_id = user.user_id
    """
    获取聊天历史（从 Redis）
    - user_id: 用户ID（必填）
    - session_id: 会话ID（可选，不填则返回该用户最近7天所有会话的最新历史）
    """
    if not session_id:
        # 返回默认会话历史
        session_id = f"cbt_{datetime.now().strftime('%Y%m%d')}"
    history = get_session_history(user_id, session_id)
    return {
        "history": [{"role": m.role, "content": m.content} for m in history],
        "session_id": session_id
    }



@app.patch("/api/v1/user/voice-preference")
async def set_voice_preference(user: AuthUser = Depends(get_current_user), voice: str = Query(...)):
    user_id = user.user_id
    valid = {"female_warm", "male_calm", "female_young"}
    if voice not in valid:
        return {"error": "invalid_voice", "valid": list(valid)}
    success = await user_profile_manager.set_voice_preference(user_id, voice)
    return {"success": success, "preferred_voice": voice if success else None}


@app.get("/api/v1/chat/cbt/state/{user_id}")
async def chat_cbt_state(user: AuthUser = Depends(get_current_user), session_id: str = None):
    user_id = user.user_id
    """获取当前 CBT-I 会话状态"""
    if session_id:
        state = cbt_manager.get_or_create_session(user_id, session_id)
        return {"state": state.__dict__ if hasattr(state, '__dict__') else str(state)}
    
    # 返回该用户所有活跃会话
    active = {k: v for k, v in cbt_manager._sessions.items() if k.startswith(f"{user_id}:")}
    return {"active_sessions": len(active)}


# ---------- 用户反馈闭环 ----------
class FeedbackRequest(BaseModel):
    user_id: str
    session_id: str = None
    message_id: str = None
    rating: int  # 1=👍 好评, -1=👎 差评, 0=未评分
    comment: str = None
    turn_text: str = None  # 用户输入
    response_text: str = None  # AI 回复

@app.post("/api/v1/feedback")
async def submit_feedback(req: FeedbackRequest, user: AuthUser = Depends(get_current_user)):
    user_id = user.user_id
    """
    用户反馈闭环：对 AI 回复进行 👍/👎 评分
    用于后续训练数据筛选和模型优化
    """
    from datetime import datetime
    feedback_key = f"feedback:{user_id}:{datetime.now().strftime('%Y%m%d')}"
    feedback_entry = {
        "user_id": user_id,
        "session_id": req.session_id or "",
        "message_id": req.message_id or "",
        "rating": req.rating,
        "comment": req.comment or "",
        "turn_text": req.turn_text or "",
        "response_text": req.response_text or "",
        "timestamp": datetime.now().isoformat(),
    }
    try:
        # 使用 Redis List 存储，方便后续批量导出
        redis_client.lpush(feedback_key, json.dumps(feedback_entry, ensure_ascii=False))
        # 保留最近 90 天
        redis_client.expire(feedback_key, 90 * 86400)
        return {"success": True, "message": "反馈已记录，谢谢"}
    except Exception as e:
        print(f"[Feedback] 保存失败: {e}")
        return {"success": False, "message": "反馈保存失败"}

@app.get("/api/v1/feedback/{user_id}")
async def get_feedback(user: AuthUser = Depends(get_current_user), limit: int = Query(20, le=100)):
    user_id = user.user_id
    """获取用户最近反馈（用于前端展示"已反馈"状态）"""
    from datetime import datetime
    feedback_key = f"feedback:{user_id}:{datetime.now().strftime('%Y%m%d')}"
    try:
        items = redis_client.lrange(feedback_key, 0, limit - 1)
        return {
            "feedbacks": [json.loads(i) for i in items],
            "total": redis_client.llen(feedback_key)
        }
    except Exception as e:
        return {"feedbacks": [], "total": 0}


# ---------- TTS ----------
@app.post("/api/v1/tts")
async def tts(text: str = Form(...), voice: str = Form("female_warm"), speed: float = Form(0.9)):
    """
    文字转语音（非流式，Edge TTS 备用）
    voice: female_warm | male_calm | female_young
    """
    if len(text) > 500:
        raise HTTPException(status_code=400, detail="文本不能超过500字")
    audio_bytes = await edge_tts(text[:500], voice, speed)
    return Response(content=audio_bytes, media_type="audio/mpeg",
        headers={"Content-Disposition": f"inline; filename=tts.mp3"})


@app.post("/api/v1/tts/stream")
async def tts_stream(text: str = Query(...), voice: str = Query("female_warm"), speed: float = Query(0)):
    """
    TTS（腾讯云 TextToVoice 同步 API，Edge TTS 降级）
    voice: female_warm | male_calm | female_young
    speed: -2 到 6（相对语速调整）
    返回: 音频流（audio/mpeg）
    """
    if len(text) > 500:
        raise HTTPException(status_code=400, detail="文本不能超过500字")

    async def stream_response():
        # 优先腾讯云 TextToVoice 同步 API（直接返回 MP3）
        try:
            # speed 处理：前端传 50-200（流式 API 语义），同步 API 用 -2~6
            # 流式 Speed=90=正常90%=稍慢；同步 Speed=-1=稍慢，效果接近
            effective_speed = max(-2, min(6, int(speed / 100) - 1)) if speed > 10 else int(speed)
            audio = await tencent_tts_sync(text[:500], voice, effective_speed)
            if audio:
                print(f"[腾讯TTS] 同步API成功，返回 {len(audio)} 字节 (effective_speed={effective_speed})")
                yield audio
            else:
                raise Exception("[腾讯TTS] 返回空音频")
        except Exception as e:
            err_str = str(e).lower()
            if 'PkgExhausted' in err_str or 'quota' in err_str or '配额' in err_str:
                print(f"[腾讯TTS] 配额用尽，降级到 Edge TTS: {e}")
            else:
                print(f"[腾讯TTS] 失败，降级到 Edge TTS: {e}")
            # Edge TTS 降级（免费无限）
            try:
                # speed 范围转换：sync API 是 -2~6，edge_tts 是 0.5~2.0
                edge_speed = max(0.5, min(2.0, 1.0 + speed / 10.0))
                audio = await edge_tts(text[:500], voice, edge_speed)
                yield audio
            except Exception as e2:
                print(f"[Edge TTS] 也失败: {e2}")
                raise HTTPException(status_code=503, detail="TTS 服务暂时不可用")

    return StreamingResponse(
        stream_response(),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline; filename=tts_stream.mp3",
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        }
    )


@app.post("/api/v1/tts/stream_v2")
async def tts_stream_v2(
    text: str = Form(...),
    voice: str = Form("female_warm"),
):
    """
    TTS 流式 v2（腾讯云 WebSocket 流式 TTS，边合成边返回 MP3 分片）
    优势：首包时间比同步 API 快 30-50%（无需等待完整合成）
    注意：Speed 固定为 0（腾讯流式 TTS 限制）
    """
    if len(text) > 500:
        raise HTTPException(status_code=400, detail="文本不能超过500字")
    if voice not in TENCENT_TTS_VOICES:
        raise HTTPException(status_code=400, detail=f"无效音色: {voice}")

    async def stream_v2():
        try:
            async for chunk in tencent_tts_stream(text[:500], voice, speed=0):
                yield chunk
        except Exception as e:
            err_str = str(e).lower()
            if 'PkgExhausted' in err_str or 'quota' in err_str or '配额' in err_str:
                print(f"[腾讯TTS-v2] 配额用尽，降级 Edge TTS: {e}")
            else:
                print(f"[腾讯TTS-v2] WebSocket TTS 失败: {e}，降级 Edge TTS")
            try:
                audio = await edge_tts(text[:500], voice, 0.9)
                yield audio
            except Exception as e2:
                print(f"[EdgeTTS-v2] 也失败: {e2}")
                raise HTTPException(status_code=503, detail="TTS 服务暂时不可用")

    return StreamingResponse(
        stream_v2(),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline; filename=tts_stream_v2.mp3",
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        }
    )


# ---------- ASR ----------
@app.post("/api/v1/asr")
async def asr(file: UploadFile = File(...)):
    """
    语音转文字（支持 mp3/wav/m4a/amr，千问 ASR）
    """
    audio_data = await file.read()
    if len(audio_data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="音频文件不能超过10MB")
    if not _validate_audio_content(audio_data, file.filename or ""):
        raise HTTPException(status_code=400, detail="不支持的文件类型，仅支持 mp3/wav/pcm")
    text = await qwen_asr(audio_data, file.filename or "audio.mp3")
    return {"text": text, "confidence": "high"}


@app.post("/api/v1/asr/stream")
async def asr_stream(file: UploadFile = File(...)):
    """
    腾讯云实时 ASR（流式识别，返回更快）
    支持 mp3/wav/amr，上传后流式处理
    """
    audio_data = await file.read()
    if len(audio_data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="音频文件不能超过10MB")
    if not _validate_audio_content(audio_data, file.filename or ""):
        raise HTTPException(status_code=400, detail="不支持的文件类型，仅支持 mp3/wav/pcm")

    try:
        text = await tencent_asr_stream(audio_data, file.filename or "audio.mp3")
        return {"text": text, "confidence": "high", "engine": "tencent"}
    except Exception as e:
        print(f"[流式ASR] 降级到千问 ASR: {e}")
        # 降级到千问 ASR
        text = await qwen_asr(audio_data, file.filename or "audio.mp3")
        return {"text": text, "confidence": "high", "engine": "qwen"}


# ==================== 腾讯云实时 ASR WebSocket（双向流式）===================

import websockets
import urllib.parse


class TencentASRStreamConnector:
    """
    腾讯云 ASR WebSocket v2 流式客户端（修复 4010 错误）
    
    4010 错误根因：connect() 发送 JSON header 后没有等待服务端确认，
    立即开始发送二进制音频数据。服务端未完成初始化时将二进制数据误判为"未知文本消息"。
    
    修复要点：
    1. 发送 header 后等待服务端返回 code=0 的确认消息
    2. 确认后再启动 send_loop 发送音频数据
    3. 音频数据分片发送（每帧 6400 字节 = 200ms）
    4. 明确使用 bytes 类型发送二进制帧
    """
    def __init__(self, appid: str, secret_id: str, secret_key: str,
                 voice_id: str = None, engine_model_type: str = "16k_zh"):
        self.appid = appid
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.voice_id = voice_id or str(uuid.uuid4())
        self.engine_model_type = engine_model_type
        self.ws = None
        self._result_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._done = asyncio.Event()
        self._ready = asyncio.Event()  # 新增：等待服务端确认
        self._send_task = None
        self._recv_task = None
        self._send_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._closed = False

    def _build_url(self) -> str:
        ts = int(time.time())
        params = {
            'engine_model_type': self.engine_model_type,
            'expired': ts + 86400,
            'nonce': int(time.time() * 1000) % 1000000000,
            'secretid': self.secret_id,
            'timestamp': ts,
            'voice_format': 1,
            'voice_id': self.voice_id,
            'needvad': 1,              # 开启服务端 VAD 切句（最关键：收到 slice_type=2 后自动停止）
            'vad_silence_time': 600,   # 静音 600ms 后触发结束（默认 1000ms 太长）
            'filter_modal': 2,         # 过滤语气词（"嗯""啊"等）
            'filter_punc': 0,          # 保留标点
            'filter_dirty': 1,         # 过滤脏话
            'convert_num_mode': 1,     # 阿拉伯数字转中文
        }
        sorted_items = sorted(params.items())
        query_str = '&'.join(f"{k}={v}" for k, v in sorted_items)
        path = f"/asr/v2/{self.appid}"
        path_query = f"{path}?{query_str}"
        sign_origin = f"asr.cloud.tencent.com{path_query}"
        sig = base64.b64encode(
            hmac.new(self.secret_key.encode(), sign_origin.encode(), hashlib.sha1).digest()
        ).decode()
        return f"wss://asr.cloud.tencent.com{path_query}&signature={urllib.parse.quote(sig)}"

    async def connect(self, timeout: float = 5.0):
        """
        建立连接并等待服务端确认
        修复 4010：必须先收到服务端 code=0 的确认，才能发送音频数据
        """
        url = self._build_url()
        print(f"[ASR-v2] connecting to {url[:80]}...")
        self.ws = await websockets.connect(url)
        
        # 先启动 receive_loop 来接收服务端的确认消息
        self._recv_task = asyncio.create_task(self._receive_loop())
        
        # v2 协议：所有参数在 URL 中，连接后直接等 code=0，不发初始化 JSON
        print(f"[ASR-v2] connected, waiting for server ready...")
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
            print("[ASR-v2] server ready, starting send_loop")
        except asyncio.TimeoutError:
            print("[ASR-v2] server ready timeout, closing")
            await self.close()
            raise Exception("ASR v2 server ready timeout")
        
        # 服务端确认后再启动 send_loop
        self._send_task = asyncio.create_task(self._send_loop())

    async def _send_loop(self):
        """发送音频数据循环 - v2 协议：裸 PCM 分片"""
        try:
            while True:
                data = await self._send_queue.get()
                if data is None:
                    # 结束标记：发送 JSON text frame
                    print("[ASR-v2] sending end marker")
                    await self.ws.send(json.dumps({"type": "end"}))
                    break
                
                # 小数据块（实时转发模式，单帧 <= 6400B）：直接发送，不 sleep
                CHUNK_SIZE = 6400
                if len(data) <= CHUNK_SIZE:
                    if isinstance(data, (bytes, bytearray)):
                        await self.ws.send(bytes(data))
                    else:
                        await self.ws.send(str(data).encode())
                else:
                    # 大数据块（批量模式）：分片发送，模拟实时率
                    for i in range(0, len(data), CHUNK_SIZE):
                        chunk = data[i:i + CHUNK_SIZE]
                        if isinstance(chunk, (bytes, bytearray)):
                            await self.ws.send(bytes(chunk))
                        else:
                            print(f"[ASR-v2] WARNING: non-bytes data, type={type(chunk)}")
                            await self.ws.send(str(chunk).encode())
                        if i + CHUNK_SIZE < len(data):
                            await asyncio.sleep(0.2)
        except Exception as e:
            print(f"[ASR-v2] send_loop error: {e}")

    async def _receive_loop(self):
        """接收识别结果循环"""
        try:
            async for msg in self.ws:
                # 服务端返回的 msg 是 JSON 文本
                if isinstance(msg, str):
                    data = json.loads(msg)
                    
                    # 检查服务端状态码
                    code = data.get("code", 0)
                    if code != 0:
                        msg = data.get('message', '')
                        print(f"[ASR-v2] server error: code={code}, message={msg}")
                        # ✅ 错误码监控：4006=并发超限，4007=连接数超限
                        if code in (4006, 4007):
                            print(f"[ASR-ALERT] ⚠️ 腾讯云 ASR 并发超限！code={code}，请扩容或降低并发")
                        self._done.set()
                        break
                    
                    # 服务端确认消息（code=0 且没有 result）
                    if not self._ready.is_set() and "result" not in data:
                        print("[ASR-v2] server acknowledged, ready to receive audio")
                        self._ready.set()
                        continue
                    
                    # 识别结果
                    result = data.get("result", {})
                    if result:
                        slice_type = result.get("slice_type", 2)
                        await self._result_queue.put({
                            "text": result.get("voice_text_str", ""),
                            "slice_type": slice_type,
                            "is_final": slice_type == 2,
                        })
                    
                    # 最终结束标记
                    if data.get("final") == 1:
                        print("[ASR-v2] received final")
                        self._done.set()
                        break
                        
        except Exception as e:
            print(f"[ASR-v2] receive_loop error: {e}")
            self._done.set()

    async def send_pcm(self, pcm: bytes):
        """发送 PCM 音频数据（完整文件）"""
        if not self._ready.is_set():
            print("[ASR-v2] WARNING: sending before ready")
        await self._send_queue.put(pcm)

    async def send_end(self):
        """发送结束标记"""
        await self._send_queue.put(None)

    async def get_result(self, timeout: float = 0.5) -> Optional[dict]:
        try:
            return await asyncio.wait_for(self._result_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def wait_done(self, timeout: float = 10.0):
        try:
            await asyncio.wait_for(self._done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

    async def close(self):
        self._closed = True
        if self._send_task and not self._send_task.done():
            self._send_task.cancel()
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        self._done.set()


class TencentASRConnector:
    """
    腾讯云 ASR REST API 客户端（async）
    使用腾讯云 SDK（tencentcloud-sdk-python）调用 SentenceRecognition 接口
    支持：PCM, AMR, OPUS, WAV, MP3, M4A 等格式
    - engine: 16k_zh（中文通用）
    - 采样率：16kHz（默认）
    - 音频数据：base64 编码后 POST
    """

    def __init__(self, appid: str, secret_id: str, secret_key: str):
        self.appid = appid
        self.secret_id = secret_id
        self.secret_key = secret_key
        self._client = None  # 延迟初始化

    def _get_client(self):
        """延迟初始化腾讯云 SDK 客户端"""
        if self._client is None:
            from tencentcloud.common import credential
            from tencentcloud.asr.v20190614 import asr_client
            cred = credential.Credential(self.secret_id, self.secret_key)
            self._client = asr_client.AsrClient(cred, 'ap-guangzhou')
        return self._client

    async def recognize(self, pcm_data: bytes, sample_rate: int = 16000) -> str:
        """
        识别一段 PCM 音频
        :param pcm_data: 原始 PCM 字节数据
        :param sample_rate: 采样率，默认 16000Hz
        :return: 识别出的文字（空字符串表示无结果）
        """
        from tencentcloud.asr.v20190614 import models

        pcm_b64 = base64.b64encode(pcm_data).decode()
        req = models.SentenceRecognitionRequest()
        req.EngSerViceType = '16k_zh'
        req.SourceType = 1  # 1 = 语音数据（base64）
        req.VoiceFormat = 'pcm'
        req.SubServiceType = 2  # 2 = 一句话识别
        req.Data = pcm_b64
        req.DataLen = len(pcm_data)
        req.ProjectId = 0
        req.UsrAudioKey = str(uuid.uuid4())

        loop = asyncio.get_event_loop()

        def _do_recognize():
            client = self._get_client()
            return client.SentenceRecognition(req)

        resp = await loop.run_in_executor(None, _do_recognize)
        result = resp.Result or ''
        print(f'[ASR] PCM {len(pcm_data)} 字节 → "{result}"')
        return result


_asr_connector = None

def get_asr_connector() -> "TencentASRConnector":
    """获取全局 ASR 连接池实例（单例，预热）"""
    global _asr_connector
    if _asr_connector is None:
        appid = settings.tencentcloud_app_id
        secret_id = settings.tencentcloud_secret_id
        secret_key = settings.tencentcloud_secret_key
        if all([appid, secret_id, secret_key]):
            _asr_connector = TencentASRConnector(str(appid), secret_id, secret_key)
            # 预热：初始化 SDK 客户端
            _asr_connector._get_client()
            print(f"[ASR-Pool] 连接池已预热，appid={appid}")
    return _asr_connector


@app.websocket("/api/v1/asr/ws")
async def asr_websocket(websocket: WebSocket):
    """
    前端 WebSocket 客户端接入点（ASR 识别）—— 实时转发模式

    协议：
    - 前端 → 后端：二进制 PCM 数据帧（16kHz 单声道 PCM）
    - 前端 → 后端：{"type": "end"}  JSON 结束标记
    - 后端 → 前端：{"text": "...", "slice_type": 1/2, "is_final": false/true}  实时结果
    - 后端 → 前端：{"done": true}  识别完成

    实现：收到前端帧立即转发给腾讯云 ASR v2，结果实时回传前端
    """
    await websocket.accept()

    appid = settings.tencentcloud_app_id
    secret_id = settings.tencentcloud_secret_id
    secret_key = settings.tencentcloud_secret_key

    if not all([appid, secret_id, secret_key]):
        await websocket.send_json({"error": "腾讯云 ASR 未配置"})
        await websocket.close()
        return

    v2_connector = None
    result_task = None
    frame_count = 0

    async def result_forwarder():
        """实时转发腾讯云识别结果给前端"""
        try:
            while True:
                result = await v2_connector.get_result(timeout=0.5)
                if result:
                    print(f"[ASR-WS] forward result: {result}")
                    await websocket.send_json(result)
                    if result.get("is_final"):
                        break
                if v2_connector._done.is_set():
                    break
            await websocket.send_json({"done": True})
            print("[ASR-WS] sent done signal")
        except Exception as e:
            print(f"[ASR-WS] result forwarder error: {e}")

    try:
        while True:
            data = await websocket.receive()
            msg_keys = list(data.keys())
            if "bytes" in data:
                pcm = data["bytes"]
                pcm_len = len(pcm) if pcm else 0
                if pcm_len > 0:
                    frame_count += 1
                    # 第一个帧：创建 connector 并连接腾讯云
                    if v2_connector is None:
                        print(f"[ASR-WS] first frame {pcm_len}B, connecting to Tencent ASR v2...")
                        v2_connector = TencentASRStreamConnector(
                            str(appid), secret_id, secret_key,
                            engine_model_type="16k_zh"
                        )
                        await v2_connector.connect(timeout=3.0)
                        result_task = asyncio.create_task(result_forwarder())
                        print("[ASR-WS] v2 connected, forwarding frames...")
                    # 实时转发给腾讯云
                    await v2_connector.send_pcm(pcm)
            elif "text" in data:
                text_data = data["text"]
                ctrl = json.loads(text_data)
                if ctrl.get("type") == "end":
                    print(f"[ASR-WS] received END, frames: {frame_count}")
                    if v2_connector:
                        await v2_connector.send_end()
                    break
            else:
                print(f"[ASR-WS] unknown msg type: {msg_keys}, val: {data}")
    except WebSocketDisconnect:
        print(f"[ASR-WS] frontend disconnected")
    except Exception as e:
        print(f"[ASR-WS] receive error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if result_task:
            result_task.cancel()
            try:
                await result_task
            except asyncio.CancelledError:
                pass
        if v2_connector:
            await v2_connector.close()
        # 确保连接关闭
        try:
            await websocket.close()
        except Exception:
            pass

    try:
        await websocket.send_json({"done": True})
    except Exception:
        pass
    try:
        await websocket.close()
    except Exception:
        pass

# ---------- 呼吸引导 ----------
@app.get("/api/v1/breathing/478")
async def breathing_guide():
    return {
        "type": "breathing_478",
        "total_seconds": 180,
        "cycle_seconds": 19,
        "cycles": 4,
        "instructions": [
            {"phase": "inhale",  "duration": 4, "emoji": "🌬️", "text": "吸气...",   "color": "#7EC8A3"},
            {"phase": "hold",    "duration": 7, "emoji": "⏸️", "text": "屏住呼吸...", "color": "#6B9FD4"},
            {"phase": "exhale",  "duration": 8, "emoji": "🌬️", "text": "呼气...",   "color": "#7EC8A3"},
        ]
    }

# ---------- 白噪音（静态数据，前端播放）----------
# 本地音频文件目录
SOUNDS_DIR = Path(__file__).parent.parent / "static" / "sounds"

@app.get("/api/v1/sounds")
async def get_sounds():
    """
    返回白噪音场景列表（URL 由前端播放，后端提供元数据）
    优先使用本地上传的音频，缺失的回退到外部 CDN
    """
    return {
        "sounds": [
            {"id": "rain",      "name": "🌧️ 雨声",       "category": "自然", "duration": 300, "local": (SOUNDS_DIR / "rain.mp3").exists()},
            {"id": "forest",    "name": "🌲 森林",       "category": "自然", "duration": 300, "local": (SOUNDS_DIR / "forest.mp3").exists()},
            {"id": "fireplace", "name": "🔥 壁炉",       "category": "室内", "duration": 200, "local": (SOUNDS_DIR / "fireplace.mp3").exists()},
            {"id": "pinknoise",  "name": "📻 粉噪音",     "category": "白噪音", "duration": 300, "local": (SOUNDS_DIR / "pinknoise.mp3").exists()},
            {"id": "waves",     "name": "🌊 海浪",       "category": "自然", "duration": 300, "local": (SOUNDS_DIR / "waves.mp3").exists()},
        ]
    }

# 外部 CDN 回退地址
EXTERNAL_SOUND_URLS = {
    "rain":      "https://openaiblock.net/wp-content/uploads/2023/08/rain-sound-2.mp3",
    "forest":    "https://openaiblock.net/wp-content/uploads/2022/01/nature-sound-forest.mp3",
    "fireplace": "https://openaiblock.net/wp-content/uploads/2021/12/fireplace-burning.mp3",
    "pinknoise": "https://openaiblock.net/wp-content/uploads/2022/03/pink-noise-10-hours.mp3",
    "waves":     "https://openaiblock.net/wp-content/uploads/2022/01/ocean-waves-lg.mp3",
}

@app.get("/api/v1/sounds/{sound_id}/url")
async def get_sound_url(sound_id: str):
    """获取白噪音音频直链（优先本地文件，回退外部 CDN）"""
    if sound_id not in EXTERNAL_SOUND_URLS:
        raise HTTPException(status_code=404, detail="未找到该声音")
    local_path = SOUNDS_DIR / f"{sound_id}.mp3"
    if local_path.exists():
        return {"url": f"https://sleepai.chat/static/sounds/{sound_id}.mp3", "format": "mp3", "source": "local"}
    return {"url": EXTERNAL_SOUND_URLS[sound_id], "format": "mp3", "source": "cdn"}

@app.get("/api/v1/sounds/{sound_id}/stream")
async def get_sound_stream(sound_id: str):
    """直接流式返回白噪音音频文件（优先本地，回退外部 CDN）"""
    if sound_id not in EXTERNAL_SOUND_URLS:
        raise HTTPException(status_code=404, detail="未找到该声音")
    local_path = SOUNDS_DIR / f"{sound_id}.mp3"
    if local_path.exists():
        return FileResponse(local_path, media_type="audio/mpeg", filename=f"{sound_id}.mp3")
    # 本地不存在，代理外部 CDN
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(EXTERNAL_SOUND_URLS[sound_id])
            if resp.status_code == 200:
                return StreamingResponse(
                    iter([resp.content]),
                    media_type="audio/mpeg",
                    headers={"Content-Disposition": f"inline; filename={sound_id}.mp3"}
                )
    except Exception as e:
        print(f"[Sound Stream] CDN fallback failed: {e}")
    raise HTTPException(status_code=503, detail="音频暂不可用")

# ---------- 睡眠记录 ----------
@app.post("/api/v1/sleep/record")
async def create_sleep_record(req: SleepRecordRequest, user: AuthUser = Depends(get_current_user)):
    user_id = user.user_id
    key = f"sleep:{user_id}:{req.date}"
    record = {"user_id": user_id, "date": req.date, "score": req.score,
              "created_at": datetime.now().isoformat()}
    redis_client.set(key, json.dumps(record, ensure_ascii=False))
    list_key = f"sleep_list:{user_id}"
    redis_client.lpush(list_key, json.dumps(record, ensure_ascii=False))
    redis_client.ltrim(list_key, 0, 29)
    return {"status": "ok", "record": record}

@app.get("/api/v1/sleep/records/{user_id}")
async def get_sleep_records(user: AuthUser = Depends(get_current_user), limit: int = Query(7, le=30)):
    user_id = user.user_id
    list_key = f"sleep_list:{user_id}"
    raw = redis_client.lrange(list_key, 0, limit - 1)
    records = [json.loads(r) for r in raw]
    scores = [r["score"] for r in records]
    sleep_stats = get_user_sleep_stats(user_id)
    return {
        "records": records,
        "stats": {
            "count": len(records),
            "avg_score": round(sum(scores)/len(scores), 1) if scores else 0,
            "streak_days": get_streak_days(user_id),
            "total_minutes": sleep_stats["total_minutes"],
            "total_records": sleep_stats["total_records"],
            "latest_score": sleep_stats["latest_score"],
        }
    }

# ---------- 用户记忆 ----------
@app.get("/api/v1/memory/{user_id}")
async def get_memory(user: AuthUser = Depends(get_current_user)):
    user_id = user.user_id
    mem = get_user_memory(user_id)
    return {"memory": mem}

# ---------- 担忧记录（CBT 担忧写下来）----------

class WorryRecordRequest(BaseModel):
    user_id: str
    worry_text: str
    session_id: Optional[str] = None


@app.post("/api/v1/worry")
async def create_worry(req: WorryRecordRequest, user: AuthUser = Depends(get_current_user)):
    user_id = user.user_id
    """记录一条担忧，自动提取关键词并更新用户记忆"""
    import re
    from datetime import datetime

    # 提取关键词（简单规则）
    triggers = []
    worry_lower = req.worry_text.lower()
    trigger_map = {
        "工作": ["工作", "上班", "加班", "老板", "同事", "职场"],
        "人际": ["人际", "朋友", "家人", "关系", "别人怎么想", "社交"],
        "未来": ["未来", "以后", "人生", "方向", "选择", "不确定"],
        "健康": ["身体", "健康", "生病", "医院", "检查"],
        "睡眠": ["睡不着", "失眠", "睡眠", "困", "休息"],
        "感情": ["感情", "恋爱", "分手", "喜欢", "TA", "另一半"],
        "学习": ["考试", "学习", "成绩", "考研", "升学", "毕业"],
    }
    for category, keywords in trigger_map.items():
        if any(k in worry_lower for k in keywords):
            triggers.append(category)

    record = {
        "user_id": user_id,
        "worry_text": req.worry_text,
        "triggers": triggers,
        "session_id": req.session_id,
        "recorded_at": datetime.now().isoformat(),
        "reviewed": False,
    }

    key = f"worry:{user_id}:{int(datetime.now().timestamp() * 1000)}"
    redis_client.set(key, json.dumps(record, ensure_ascii=False))

    list_key = f"worry_list:{user_id}"
    redis_client.lpush(list_key, json.dumps(record, ensure_ascii=False))
    redis_client.ltrim(list_key, 0, 99)

    mem_key = f"memory:{user_id}"
    mem = get_user_memory(user_id)
    trigger_counts = mem.get("triggers", {})
    for t in triggers:
        trigger_counts[t] = trigger_counts.get(t, 0) + 1
    mem["triggers"] = trigger_counts
    redis_client.set(mem_key, json.dumps(mem, ensure_ascii=False))

    return {"status": "ok", "record": record}


@app.get("/api/v1/worries/{user_id}")
async def get_worries(user: AuthUser = Depends(get_current_user), limit: int = Query(20, le=100), unreviewed_only: bool = False):
    user_id = user.user_id
    list_key = f"worry_list:{user_id}"
    raw = redis_client.lrange(list_key, 0, limit - 1)
    records = [json.loads(r) for r in raw]
    if unreviewed_only:
        records = [r for r in records if not r.get("reviewed")]

    from collections import defaultdict
    by_date = defaultdict(list)
    for r in records:
        date = r["recorded_at"][:10]
        by_date[date].append(r)

    return {
        "records": records,
        "by_date": dict(by_date),
        "total": len(records),
        "unreviewed_count": sum(1 for r in records if not r.get("reviewed")),
    }


@app.patch("/api/v1/worry/{worry_key}")
async def update_worry(worry_key: str, req: dict):
    """
    更新单条担忧记录（目前仅支持标记 reviewed=True）
    worry_key 格式：worry:{user_id}:{timestamp_ms}
    """
    # 从 Redis 读取原始记录
    raw = redis_client.get(worry_key)
    if not raw:
        return {"status": "error", "message": "记录不存在"}
    record = json.loads(raw)
    # 更新字段
    if "reviewed" in req:
        record["reviewed"] = req["reviewed"]
    # 写回 Redis
    redis_client.set(worry_key, json.dumps(record, ensure_ascii=False))
    # 同步更新 worry_list 中的副本
    list_key = f"worry_list:{record['user_id']}"
    all_raw = redis_client.lrange(list_key, 0, -1)
    for i, item_raw in enumerate(all_raw):
        item = json.loads(item_raw)
        if item.get("recorded_at") == record.get("recorded_at") and item.get("worry_text") == record.get("worry_text"):
            redis_client.lset(list_key, i, json.dumps(record, ensure_ascii=False))
            break
    return {"status": "ok", "record": record}


# ==================== 订阅管理 ====================

class SubscriptionRequest(BaseModel):
    user_id: str
    plan: str
    expire_date: str
    billing_cycle: str = 'monthly'  # 'monthly' | 'yearly'


@app.post("/api/v1/subscription/activate")
async def activate_subscription(req: SubscriptionRequest, user: AuthUser = Depends(get_current_user)):
    user_id = user.user_id
    key = f"subscription:{user_id}"
    data = {
        "user_id": user_id,
        "plan": req.plan,
        "billing_cycle": req.billing_cycle,
        "expire_date": req.expire_date,
        "is_active": True,
        "activated_at": datetime.now().isoformat(),
    }
    redis_client.set(key, json.dumps(data, ensure_ascii=False))
    return {"status": "ok", "subscription": data}


@app.get("/api/v1/subscription/{user_id}")
async def get_subscription(user: AuthUser = Depends(get_current_user)):
    user_id = user.user_id
    key = f"subscription:{user_id}"
    raw = redis_client.get(key)
    if not raw:
        return {"is_active": False}
    data = json.loads(raw)
    expire = datetime.fromisoformat(data["expire_date"])
    if datetime.now() > expire:
        data["is_active"] = False
        redis_client.set(key, json.dumps(data, ensure_ascii=False))
    return data


# ==================== Morning Check-in APIs ====================

@app.post("/api/v1/morning/submit")
async def morning_submit(req: MorningSubmitRequest, user: AuthUser = Depends(get_current_user)):
    user_id = user.user_id
    """
    提交晨间打卡（完整版）
    - 计算睡眠指标（TIB, TST, SE）
    - 使用用户填写的真实 WASO 而非估算
    - 存入 Redis，key = morning:{user_id}:{date}
    """
    try:
        today = req.date or datetime.now().strftime("%Y-%m-%d")

        # 计算睡眠指标（使用用户传来的真实 WASO）
        try:
            metrics = compute_sleep_metrics(
                req.sleep_window_start,
                req.sleep_window_end,
                req.wake_count,
                waso_minutes=req.waso_minutes if req.waso_minutes > 0 else None
            )
        except NameError:
            metrics = {"sol_estimate": 30, "waso": req.waso_minutes or 0, "tib_minutes": 480, "tst_minutes": 360, "se": req.se or 0.80}

        # 如果前端传来了计算好的 SE，优先使用前端的结果
        final_se = req.se if req.se > 0 else metrics["se"]
        final_tst = req.tst_hours * 60 if req.tst_hours > 0 else metrics["tst_minutes"]
        final_tib = req.tib_hours * 60 if req.tib_hours > 0 else metrics["tib_minutes"]

        record = {
            "user_id": user_id,
            "date": today,
            "bed_time_estimate": req.bed_time_estimate,
            "wake_time_estimate": req.wake_time_estimate,
            "wake_count": req.wake_count,
            "sleep_quality": req.sleep_quality,
            "waso_minutes": req.waso_minutes,
            "nap_minutes": req.nap_minutes,
            "fatigue_level": req.fatigue_level,
            "sleep_window_start": req.sleep_window_start,
            "sleep_window_end": req.sleep_window_end,
            "tib_minutes": final_tib,
            "tst_minutes": final_tst,
            "se": final_se,
            "sol_estimate": metrics["sol_estimate"],
            "waso": metrics["waso"],
            "submitted_at": datetime.now().isoformat(),
        }

        save_morning_record(user_id, today, record)

        # L2: 晨间打卡 → 标记昨晚会话为"sleep_reported"（最高质量数据）
        if RAG_AVAILABLE and session_logger:
            finalize_session(outcome="sleep_reported", sleep_quality=req.sleep_quality)

        # 同时更新睡眠日记 - 合并睡前设定和晨间记录
        existing_diary = get_sleep_diary(user_id, today)
        if existing_diary:
            existing_diary["actual_bed_time"] = req.bed_time_estimate
            existing_diary["actual_wake_time"] = req.wake_time_estimate
            existing_diary["wake_count"] = req.wake_count
            existing_diary["sleep_quality"] = req.sleep_quality
            existing_diary["waso_minutes"] = req.waso_minutes
            existing_diary["nap_minutes"] = req.nap_minutes
            existing_diary["fatigue_level"] = req.fatigue_level
            existing_diary["tib_minutes"] = final_tib
            existing_diary["tst_minutes"] = final_tst
            existing_diary["se"] = final_se
            existing_diary["sol_estimate"] = metrics["sol_estimate"]
            existing_diary["sleep_score"] = req.sleep_score
            existing_diary["updated_at"] = datetime.now().isoformat()
        else:
            # 如果没有睡前设定，创建一个新的日记条目
            existing_diary = {
                "user_id": user_id,
                "date": today,
                "planned_bed_time": req.sleep_window_start,
                "planned_wake_time": req.sleep_window_end,
                "planned_tib_minutes": final_tib,
                "actual_bed_time": req.bed_time_estimate,
                "actual_wake_time": req.wake_time_estimate,
                "wake_count": req.wake_count,
                "sleep_quality": req.sleep_quality,
                "waso_minutes": req.waso_minutes,
                "nap_minutes": req.nap_minutes,
                "fatigue_level": req.fatigue_level,
                "tib_minutes": final_tib,
                "tst_minutes": final_tst,
                "se": final_se,
                "sol_estimate": metrics["sol_estimate"],
                "sleep_score": req.sleep_score,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
        save_sleep_diary(user_id, today, existing_diary)
        update_streak(user_id)

        return {
            "status": "ok",
            "se": final_se,
            "tst_minutes": final_tst,
            "tib_minutes": final_tib,
            "waso_minutes": req.waso_minutes,
            "nap_minutes": req.nap_minutes,
            "fatigue_level": req.fatigue_level,
            "quality_score": req.sleep_quality,
        }
    except Exception as e:
        print(f"[morning_submit error] {e}")
        return {"status": "degraded", "error": "存储服务暂时不可用"},


@app.get("/api/v1/morning/check")
async def morning_check(user: AuthUser = Depends(get_current_user)):
    user_id = user.user_id
    """
    检查今日是否已完成晨间打卡
    - 查询 Redis key morning:{user_id}:{today}
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        record = get_morning_record(user_id, today)
        return {
            "completed": record is not None,
            "record": record,
        }
    except Exception as e:
        print(f"[morning_check error] {e}")
        return {"completed": False, "record": None, "status": "degraded"}


@app.get("/api/v1/sleep/recommendation/{user_id}")
async def sleep_recommendation(user: AuthUser = Depends(get_current_user)):
    user_id = user.user_id
    """
    TIB Sleep Restriction Algorithm（Sleepio 风格）
    - 基于最近 7 天晨间记录计算平均 SE
    - 根据 SE 调整推荐睡眠窗口
    """
    try:
        records = get_last_n_morning_records(user_id, n=7)

        # 默认推荐（数据不足时）
        if len(records) < 3:
            return {
                "recommended_bed_time": "23:00",
                "recommended_wake_time": "07:00",
                "current_tib_hours": 7.0,
                "se_trend": "insufficient_data",
                "avg_se": None,
                "message": "积累更多数据后给出个性化建议",
            }

        # 计算平均 SE
        se_values = [r["se"] for r in records]
        avg_se = round(sum(se_values) / len(se_values), 1)

        # 计算 SE 趋势
        if len(se_values) >= 2:
            recent = sum(se_values[:2]) / 2
            older = sum(se_values[-2:]) / 2
            if recent > older + 2:
                se_trend = "improving"
            elif recent < older - 2:
                se_trend = "declining"
            else:
                se_trend = "stable"
        else:
            se_trend = "stable"

        # 获取当前睡眠窗口
        window = get_sleep_window(user_id)
        current_tib_minutes = (window["wake_hour"] * 60 + window["wake_min"]) - (window["bed_hour"] * 60 + window["bed_min"])
        if current_tib_minutes < 0:
            current_tib_minutes += 24 * 60
        current_tib_hours = round(current_tib_minutes / 60, 1)

        # 根据平均 SE 调整 TIB
        if avg_se >= 85:
            new_tib_minutes = min(current_tib_minutes + 30, 9 * 60)
            message = "睡眠效率优秀，建议适当增加睡眠时间"
        elif avg_se <= 80:
            new_tib_minutes = max(current_tib_minutes, 4.5 * 60)
            message = "睡眠效率有待提升，建议保持当前睡眠窗口"
        else:
            new_tib_minutes = current_tib_minutes
            message = "睡眠效率良好，维持当前睡眠习惯"

        # 保持中间点不变，计算新窗口
        midpoint = (window["bed_hour"] * 60 + window["bed_min"]) + current_tib_minutes // 2
        midpoint = midpoint % (24 * 60)
        half_tib = new_tib_minutes // 2
        new_bed_minutes = (midpoint - half_tib) % (24 * 60)
        new_wake_minutes = (midpoint + half_tib) % (24 * 60)

        return {
            "recommended_bed_time": minutes_to_time_str(new_bed_minutes),
            "recommended_wake_time": minutes_to_time_str(new_wake_minutes),
            "current_tib_hours": current_tib_hours,
            "se_trend": se_trend,
            "avg_se": avg_se,
            "message": message,
        }
    except Exception as e:
        print(f"[sleep_recommendation error] {e}")
        return {
            "recommended_bed_time": "23:00",
            "recommended_wake_time": "07:00",
            "current_tib_hours": 7.0,
            "se_trend": "error",
            "avg_se": None,
            "message": "建议服务暂时不可用",
        }


# ==================== Sleep Window Settings API ====================

@app.post("/api/v1/sleep/window")
async def set_sleep_window(req: SleepWindowRequest, user: AuthUser = Depends(get_current_user)):
    user_id = user.user_id
    """
    设置用户睡眠窗口
    - 存入 Redis key = sleep_window:{user_id}，TTL 30 天
    """
    save_sleep_window(user_id, req.bed_hour, req.bed_min, req.wake_hour, req.wake_min)

    # 计算 TIB
    bed_total = req.bed_hour * 60 + req.bed_min
    wake_total = req.wake_hour * 60 + req.wake_min
    if wake_total <= bed_total:
        wake_total += 24 * 60
    tib_hours = round((wake_total - bed_total) / 60, 1)

    return {
        "status": "ok",
        "tib_hours": tib_hours,
    }


@app.get("/api/v1/sleep/window/{user_id}")
async def get_sleep_window_endpoint(user: AuthUser = Depends(get_current_user)):
    user_id = user.user_id
    """
    获取用户睡眠窗口
    - 未设置时返回默认值（bed=23:00, wake=07:00）
    """
    return get_sleep_window(user_id)


# ==================== RAG / Training Stats APIs（L2）============

@app.get("/api/v1/rag/status")
async def rag_status():
    """RAG索引状态"""
    if not RAG_AVAILABLE:
        return {"status": "unavailable", "message": "RAG模块未安装"}
    try:
        rag_index.load_index()
        return {
            "status": "available",
            "vector_count": len(rag_index.chunks),
            "vocab_size": len(rag_index.chunks),
            "index_path": "hybrid_rag_index"
        }
    except FileNotFoundError:
        return {"status": "not_built", "message": "索引未构建，请调用 /api/v1/rag/build"}

@app.post("/api/v1/rag/build")
async def rag_build(force: bool = False):
    """构建RAG索引"""
    if not RAG_AVAILABLE:
        raise HTTPException(status_code=503, detail="RAG模块未安装")
    try:
        build_rag_index(force=force)
        rag_index.load_index()
        return {
            "status": "ok",
            "message": "索引构建完成",
            "vector_count": len(rag_index.chunks),
            "vocab_size": len(rag_index.chunks),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/training/stats")
async def training_stats(min_score: float = 6.0):
    """L3训练数据统计"""
    if not RAG_AVAILABLE or not session_logger:
        return {"status": "unavailable"}
    try:
        logs = session_logger.get_high_quality_sessions(min_score=min_score, limit=1000)
        total = len(logs)
        avg_score = sum(l.get("effect_score", 0) for l in logs) / total if total else 0
        scenarios = {}
        for l in logs:
            s = l.get("scenario_id", "unknown")
            scenarios[s] = scenarios.get(s, 0) + 1
        return {
            "total_sessions": total,
            "avg_effect_score": round(avg_score, 2),
            "by_scenario": scenarios,
            "min_score_threshold": min_score,
            "log_dir": str(logs[0]) if logs else ""
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/training/export")
async def training_export(min_score: float = 6.0, limit: int = Query(500, le=2000)):
    """导出L3训练数据集（JSONL）"""
    if not RAG_AVAILABLE or not session_logger:
        raise HTTPException(status_code=503, detail="RAG模块未安装")
    try:
        data = session_logger.get_training_data_for_l3(min_score=min_score, limit=limit)
        return {
            "count": len(data),
            "data": data[:10],  # 预览前10条
            "message": f"共 {len(data)} 条，可用 /api/v1/training/download 下载完整文件"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Sleep Diary APIs ====================

@app.post("/api/v1/sleep/diary/bedtime")
async def set_bedtime(req: BedtimeSettingRequest):
    """
    睡前设定今晚睡眠窗口
    - 创建/更新今日睡眠日记的睡前设定部分
    """
    try:
        date = req.date or datetime.now().strftime("%Y-%m-%d")
        
        # 计算计划 TIB
        bed = datetime.strptime(req.planned_bed_time, "%H:%M")
        wake = datetime.strptime(req.planned_wake_time, "%H:%M")
        bed_minutes = bed.hour * 60 + bed.minute
        wake_minutes = wake.hour * 60 + wake.minute
        if wake_minutes <= bed_minutes:
            wake_minutes += 24 * 60
        planned_tib = wake_minutes - bed_minutes
        
        # 保存睡眠窗口设置（用于后续计算）
        save_sleep_window(user_id, bed.hour, bed.minute, wake.hour, wake.minute)
        
        # 获取或创建今日日记
        existing = get_sleep_diary(user_id, date)
        if existing:
            existing["planned_bed_time"] = req.planned_bed_time
            existing["planned_wake_time"] = req.planned_wake_time
            existing["planned_tib_minutes"] = planned_tib
            existing["updated_at"] = datetime.now().isoformat()
        else:
            existing = {
                "user_id": user_id,
                "date": date,
                "planned_bed_time": req.planned_bed_time,
                "planned_wake_time": req.planned_wake_time,
                "planned_tib_minutes": planned_tib,
                "wake_count": 0,
                "sleep_quality": 0,
                "tib_minutes": 0,
                "tst_minutes": 0,
                "se": 0.0,
                "waso_minutes": 0,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
        
        save_sleep_diary(user_id, date, existing)
        
        return {
            "status": "ok",
            "date": date,
            "planned_bed_time": req.planned_bed_time,
            "planned_wake_time": req.planned_wake_time,
            "planned_tib_hours": round(planned_tib / 60, 1),
            "message": f"今晚计划 {req.planned_bed_time} 入睡，{req.planned_wake_time} 起床"
        }
    except Exception as e:
        print(f"[set_bedtime error] {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/v1/sleep/diary")
async def submit_sleep_diary(req: SleepDiarySubmitRequest, user: AuthUser = Depends(get_current_user)):
    """
    提交睡眠日记（从"记录今早睡眠"入口）
    - 计算 TIB/TST/SE
    - 存入 Redis sleep_diary:{user_id}:{date}
    """
    try:
        user_id = user.user_id
        date = req.date or datetime.now().strftime("%Y-%m-%d")

        # 解析时间，计算 TIB（卧床时长，分钟）
        bed = datetime.strptime(req.bed_time, "%H:%M")
        wake = datetime.strptime(req.wake_time, "%H:%M")
        bed_minutes = bed.hour * 60 + bed.minute
        wake_minutes = wake.hour * 60 + wake.minute
        if wake_minutes <= bed_minutes:
            wake_minutes += 24 * 60
        tib_minutes = wake_minutes - bed_minutes

        # 估算 WASO（每次醒来约 10 分钟）
        waso_minutes = req.wake_count * 10
        # TST = TIB - latency - WASO
        tst_minutes = max(0, tib_minutes - req.sleep_latency_minutes - waso_minutes)
        # SE = TST / TIB
        se = round(tst_minutes / tib_minutes, 2) if tib_minutes > 0 else 0.0

        # 获取或创建今日日记
        existing = get_sleep_diary(user_id, date)
        if existing:
            existing["actual_bed_time"] = req.bed_time
            existing["actual_wake_time"] = req.wake_time
            existing["sleep_latency_minutes"] = req.sleep_latency_minutes
            existing["wake_count"] = req.wake_count
            existing["sleep_quality"] = req.quality
            existing["note"] = req.note
            existing["tib_minutes"] = tib_minutes
            existing["tst_minutes"] = tst_minutes
            existing["se"] = se
            existing["waso_minutes"] = waso_minutes
            existing["updated_at"] = datetime.now().isoformat()
        else:
            existing = {
                "user_id": user_id,
                "date": date,
                "actual_bed_time": req.bed_time,
                "actual_wake_time": req.wake_time,
                "sleep_latency_minutes": req.sleep_latency_minutes,
                "wake_count": req.wake_count,
                "sleep_quality": req.quality,
                "note": req.note,
                "tib_minutes": tib_minutes,
                "tst_minutes": tst_minutes,
                "se": se,
                "waso_minutes": waso_minutes,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }

        save_sleep_diary(user_id, date, existing)
        update_streak(user_id)

        return {
            "status": "ok",
            "date": date,
            "tib_minutes": tib_minutes,
            "tst_minutes": tst_minutes,
            "se": se,
            "message": f"睡眠记录已保存，睡眠效率 {int(se * 100)}%"
        }
    except Exception as e:
        print(f"[submit_sleep_diary error] {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/sleep/diary/today")
async def get_today_diary(user: AuthUser = Depends(get_current_user)):
    user_id = user.user_id
    """
    获取今日睡眠日记
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        diary = get_sleep_diary(user_id, today)
        
        if not diary:
            # 返回空模板
            return {
                "exists": False,
                "date": today,
                "diary": None,
                "message": "今晚还没有设定睡眠时间"
            }
        
        return {
            "exists": True,
            "date": today,
            "diary": diary
        }
    except Exception as e:
        print(f"[get_today_diary error] {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/sleep/diary/history")
async def get_diary_history(user: AuthUser = Depends(get_current_user), days: int = 7):
    user_id = user.user_id
    """
    获取最近 N 天的睡眠日记历史
    """
    try:
        records = []
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            diary = get_sleep_diary(user_id, date)
            if diary:
                records.append(diary)
        
        return {
            "user_id": user_id,
            "days": days,
            "records": records,
            "count": len(records)
        }
    except Exception as e:
        print(f"[get_diary_history error] {e}")
        return {"status": "error", "message": str(e)}


def _get_srt_data(records, user_id):
    try:
        if records:
            latest = records[0]
            bed = latest.get('planned_bed_time', latest.get('sleep_window_start', '23:00'))
            wake = latest.get('planned_wake_time', latest.get('sleep_window_end', '07:00'))
        else:
            window = get_sleep_window(user_id)
            bed = f"{window['bed_hour']:02d}:{window['bed_min']:02d}"
            wake = f"{window['wake_hour']:02d}:{window['wake_min']:02d}"
        window_dict = {'bed': bed, 'wake': wake}
        result = srt_engine.analyze(records, window_dict)
        phase_labels = {'learning': '📝 学习期', 'restricting': '📉 限制期', 'stabilizing': '👍 稳定期', 'optimizing': '🌟 优化期', 'maintenance': '✨ 维持期'}
        return {
            'phase': result.phase.value,
            'phase_label': phase_labels.get(result.phase.value, '未知'),
            'current_tib_hours': result.current_tib_hours,
            'recommended_tib_hours': result.recommended_tib_hours,
            'recommended_bed_time': result.recommended_bed_time,
            'recommended_wake_time': result.recommended_wake_time,
            'adjustment_needed': result.adjustment_minutes > 0,
            'adjustment_minutes': result.adjustment_minutes,
            'avg_se': result.avg_se,
            'avg_tst_minutes': result.avg_tst_minutes,
            'avg_sol_minutes': result.avg_sol_minutes,
            'avg_waso_minutes': result.avg_waso_minutes,
            'avg_fatigue': result.avg_fatigue,
            'se_trend': result.se_trend,
            'tst_trend': result.tst_trend,
            'poor_nights_count': result.poor_nights_count,
            'consecutive_poor_nights': result.consecutive_poor_nights,
            'record_count': result.record_count,
            'week_tip': result.week_tip,
            'daily_tips': result.daily_tips,
        }
    except Exception as e:
        print(f'[SRT data error] {e}')
        import traceback
        traceback.print_exc()
        # Return default learning phase
        return {
            'phase': 'learning',
            'phase_label': '📝 学习期',
            'current_tib_hours': 8.0,
            'recommended_tib_hours': 8.0,
            'recommended_bed_time': '23:00',
            'recommended_wake_time': '07:00',
            'adjustment_needed': False,
            'adjustment_minutes': 0,
            'avg_se': 0,
            'avg_tst_minutes': 0,
            'avg_sol_minutes': 0,
            'avg_waso_minutes': 0,
            'avg_fatigue': 0,
            'se_trend': 'stable',
            'tst_trend': 'stable',
            'poor_nights_count': 0,
            'consecutive_poor_nights': 0,
            'record_count': 0,
            'week_tip': '开始记录睡眠日记，获得个性化分析',
            'daily_tips': ['记录睡眠日记是改善睡眠的第一步'],
        }


@app.get("/api/v1/sleep/dashboard")
async def sleep_dashboard(user: AuthUser = Depends(get_current_user), days: int = 7):
    user_id = user.user_id
    """
    睡眠效率仪表盘
    - 返回最近 N 天的睡眠效率趋势
    - 计算平均 SE、TST、睡眠质量
    - 给出建议
    """
    try:
        # 获取历史记录
        records = []
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            diary = get_sleep_diary(user_id, date)
            if diary and diary.get("se", 0) > 0:
                records.append(diary)
        
        if not records:
            return {
                "user_id": user_id,
                "days": days,
                "has_data": False,
                "message": "还没有睡眠记录，开始记录你的第一晚吧 🌙",
                "stats": None,
                "trend": [],
                "recommendation": None
            }
        
        # 计算统计数据
        se_values = [r["se"] for r in records]
        tst_values = [r["tst_minutes"] for r in records if r.get("tst_minutes", 0) > 0]
        quality_values = [r["sleep_quality"] for r in records if r.get("sleep_quality", 0) > 0]
        
        avg_se = round(sum(se_values) / len(se_values), 1)
        avg_tst = round(sum(tst_values) / len(tst_values) / 60, 1) if tst_values else 0
        avg_quality = round(sum(quality_values) / len(quality_values), 1) if quality_values else 0
        
        # 计算趋势（最近3天 vs 之前4天）
        if len(records) >= 5:
            recent_se = sum([r["se"] for r in records[:3]]) / 3
            older_se = sum([r["se"] for r in records[3:]]) / max(1, len(records) - 3)
            if recent_se > older_se + 3:
                trend_direction = "improving"
                trend_emoji = "📈"
            elif recent_se < older_se - 3:
                trend_direction = "declining"
                trend_emoji = "📉"
            else:
                trend_direction = "stable"
                trend_emoji = "➡️"
        else:
            trend_direction = "insufficient_data"
            trend_emoji = "📝"
        
        # 生成建议
        if avg_se >= 85:
            se_level = "excellent"
            se_message = "🌟 睡眠效率优秀！你的睡眠质量很高"
        elif avg_se >= 80:
            se_level = "good"
            se_message = "👍 睡眠效率良好，继续保持"
        elif avg_se >= 70:
            se_level = "fair"
            se_message = "💡 睡眠效率一般，试试睡前放松练习"
        else:
            se_level = "poor"
            se_message = "⚠️ 睡眠效率偏低，建议调整睡眠习惯"
        
        # TIB 调整建议（Sleep Restriction）
        window = get_sleep_window(user_id)
        current_tib_minutes = (window["wake_hour"] * 60 + window["wake_min"]) - (window["bed_hour"] * 60 + window["bed_min"])
        if current_tib_minutes < 0:
            current_tib_minutes += 24 * 60
        
        if avg_se >= 85 and current_tib_minutes < 9 * 60:
            tib_suggestion = "可以逐渐增加 15 分钟睡眠时间"
        elif avg_se <= 80:
            tib_suggestion = "建议保持当前睡眠窗口，提高效率比增加时长更重要"
        else:
            tib_suggestion = "当前睡眠窗口合适"
        
        # 构建趋势数据（按日期倒序）
        trend = []
        for r in sorted(records, key=lambda x: x["date"], reverse=True)[:7]:
            trend.append({
                "date": r["date"],
                "se": r["se"],
                "tst_hours": round(r.get("tst_minutes", 0) / 60, 1),
                "quality": r.get("sleep_quality", 0),
                "planned_bed": r.get("planned_bed_time", "--:--"),
                "actual_bed": r.get("actual_bed_time", "--:--"),
            })
        
        return {
            "user_id": user_id,
            "days": days,
            "has_data": True,
            "stats": {
                "avg_se": avg_se,
                "avg_tst_hours": avg_tst,
                "avg_quality": avg_quality,
                "total_records": len(records),
                "se_level": se_level,
                "se_message": se_message
            },
            "trend": trend,
            "trend_direction": trend_direction,
            "trend_emoji": trend_emoji,
            "recommendation": {
                "tib_suggestion": tib_suggestion,
                "general_advice": get_sleep_advice(avg_se, avg_tst),
            "srt": _get_srt_data(records, user_id)
            }
        }
    except Exception as e:
        print(f"[sleep_dashboard error] {e}")
        return {"status": "error", "message": str(e)}


def get_sleep_advice(avg_se: float, avg_tst: float) -> str:
    """根据睡眠数据生成建议"""
    if avg_se >= 85 and avg_tst >= 7:
        return "你的睡眠状况很好！继续保持规律的作息。"
    elif avg_se >= 85 and avg_tst < 7:
        return "睡眠效率很高，但可以尝试稍微延长睡眠时间。"
    elif avg_se < 80 and avg_tst >= 7:
        return "在床上的时间很长但实际睡眠效率不高，建议只在困了才上床。"
    else:
        return "睡眠效率有待提升。试试固定起床时间，建立规律的睡眠节律。"


# ==================== Sleep Window Helpers ====================

def get_sleep_window(user_id: str) -> dict:
    """获取用户当前睡眠窗口，未设置则返回默认值 23:00-07:00"""
    key = f"sleep_window:{user_id}"
    raw = redis_client.get(key)
    if raw:
        return json.loads(raw)
    return {"bed_hour": 23, "bed_min": 0, "wake_hour": 7, "wake_min": 0}


def save_sleep_window(user_id: str, bed_hour: int, bed_min: int, wake_hour: int, wake_min: int):
    """保存用户睡眠窗口，TTL 30 天"""
    key = f"sleep_window:{user_id}"
    data = {"bed_hour": bed_hour, "bed_min": bed_min, "wake_hour": wake_hour, "wake_min": wake_min}
    redis_client.setex(key, 30 * 86400, json.dumps(data, ensure_ascii=False))


def get_sleep_baseline(user_id: str) -> Optional[dict]:
    """获取睡眠限制基线数据"""
    key = f"sleep_baseline:{user_id}"
    raw = redis_client.get(key)
    if raw:
        return json.loads(raw)
    return None


def save_sleep_baseline(user_id: str, data: dict):
    """保存睡眠限制基线数据，TTL 365 天"""
    key = f"sleep_baseline:{user_id}"
    redis_client.setex(key, 365 * 86400, json.dumps(data, ensure_ascii=False))


def get_last_n_sleep_records(user_id: str, n: int = 7) -> list:
    """获取最近 N 天有 SE 记录的睡眠日记（优先从 morning_record 读）"""
    records = []
    for i in range(n):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        # morning_record 包含前端计算的完整 SE/TST，是权威数据源
        record = get_morning_record(user_id, date)
        if record and record.get("se", 0) > 0:
            records.append(record)
        else:
            # 降级：从 sleep_diary 读（睡前设定场景）
            diary = get_sleep_diary(user_id, date)
            if diary and diary.get("se", 0) > 0:
                records.append(diary)
    return records


# ==================== Sleep Restriction Algorithm ====================
# 基于 Sleepio 睡眠限制疗法（Sleep Restriction Therapy）
# 参考：AASM 2025 指南 / European Insomnia Guideline 2023
#
# 核心逻辑：
# - 学习期（前 7 天）：收集 TST，计算初始 TIB = avg(TST) + 30 分钟
# - 每周评估：SE ≥ 85% → TIB +15~30min；SE ≤ 80% → 保持（不缩短）
# - TIB 范围：4.5h ~ 9h（临床安全边界）
# - 起床时间固定，入睡时间动态调整

@app.get("/api/v1/sleep/restriction")
async def get_sleep_restriction(user: AuthUser = Depends(get_current_user)):
    user_id = user.user_id
    """
    获取当前睡眠限制状态和建议 TIB 窗口
    - phase: "learning" | "active" | "optimizing"
    - learning: < 7 天记录，返回基于历史的预估 TIB
    - active: ≥ 7 天，进入睡眠限制正式阶段
    - optimizing: SE ≥ 85%，可以扩展 TIB
    """
    try:
        records = get_last_n_sleep_records(user_id, n=7)
        window = get_sleep_window(user_id)
        baseline = get_sleep_baseline(user_id)

        # 计算当前 TIB
        current_tib = (window["wake_hour"] * 60 + window["wake_min"]) - (window["bed_hour"] * 60 + window["bed_min"])
        if current_tib < 0:
            current_tib += 24 * 60

        # 无记录：返回默认值
        if not records:
            return {
                "phase": "learning",
                "has_baseline": False,
                "current_tib_minutes": current_tib,
                "current_tib_hours": round(current_tib / 60, 1),
                "planned_bed_time": f"{window['bed_hour']:02d}:{window['bed_min']:02d}",
                "planned_wake_time": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
                "recommended_tib_minutes": current_tib,
                "recommended_bed_time": f"{window['bed_hour']:02d}:{window['bed_min']:02d}",
                "recommended_wake_time": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
                "avg_se": None,
                "avg_tst_minutes": None,
                "record_count": 0,
                "message": "开始记录睡眠日记，我会为你计算最佳卧床时间",
                "days_needed": 7,
                "week_tip": "每晚睡前记录睡眠日记，7 天后我会给你个性化的睡眠窗口建议 🌙",
            }

        record_count = len(records)
        avg_se = round(sum(r["se"] for r in records) / record_count, 1)
        avg_tst = round(sum(r.get("tst_minutes", 0) for r in records) / record_count)

        # 计算预估 TIB（用于学习期）
        estimated_tib = min(max(avg_tst + 30, 4.5 * 60), 9 * 60)
        # 固定起床时间，计算建议入睡时间
        fixed_wake_min = window["wake_hour"] * 60 + window["wake_min"]
        suggested_bed_min = fixed_wake_min - estimated_tib
        if suggested_bed_min < 0:
            suggested_bed_min += 24 * 60
        suggested_bed_h = suggested_bed_min // 60
        suggested_bed_m = suggested_bed_min % 60

        if record_count < 7:
            # 学习期：展示预估数据，鼓励继续记录
            pct = round(record_count / 7 * 100)
            return {
                "phase": "learning",
                "has_baseline": False,
                "current_tib_minutes": current_tib,
                "current_tib_hours": round(current_tib / 60, 1),
                "planned_bed_time": f"{window['bed_hour']:02d}:{window['bed_min']:02d}",
                "planned_wake_time": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
                "estimated_tib_minutes": estimated_tib,
                "estimated_tib_hours": round(estimated_tib / 60, 1),
                "recommended_bed_time": f"{suggested_bed_h:02d}:{suggested_bed_m:02d}",
                "recommended_wake_time": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
                "avg_se": avg_se,
                "avg_tst_minutes": avg_tst,
                "record_count": record_count,
                "message": f"已记录 {record_count}/7 天，继续记录获得准确建议",
                "days_needed": 7 - record_count,
                "week_tip": f"📊 当前平均睡眠效率 {avg_se}%，入睡时间 {avg_tst} 分钟。保持记录，{7 - record_count} 天后我会给出精确的睡眠窗口！",
            }

        # ========== 正式睡眠限制阶段（≥7 天记录）==========
        # CBT-I Sleep Restriction 核心公式：TIB = avg(TST) + 30min 缓冲
        # 参考：AASM 2025 指南 / Sleepio 算法
        # 安全边界：4.5h ~ 8.5h（不推荐超过9h）
        MIN_TIB = 4.5 * 60   # 270 min
        MAX_TIB = 8.5 * 60  # 510 min

        # 初始目标 TIB = avg(TST) + 30min
        target_tib = min(max(avg_tst + 30, MIN_TIB), MAX_TIB)

        if avg_se >= 85:
            # 优化阶段：SE 优秀 → 可扩展 TIB（+15~30min）
            new_tib = min(target_tib + 30, MAX_TIB)
            phase = "optimizing"
            tib_adjustment = new_tib - target_tib
            suggestion = f"🌟 睡眠效率 {avg_se}% 优秀！本周可增加 {tib_adjustment:.0f} 分钟卧床时间"
        elif avg_se >= 80:
            # 稳定阶段：SE 良好 → 维持当前 TIB
            new_tib = target_tib
            phase = "stable"
            tib_adjustment = 0
            suggestion = f"👍 睡眠效率 {avg_se}% 良好，维持当前 {round(target_tib/60, 1)} 小时睡眠窗口"
        else:
            # 限制阶段：SE < 80% → 主动限制 TIB = avg(TST) + 30min
            # 这是 CBT-I 核心机制：减少卧床时间以提高 SE
            if current_tib <= target_tib:
                new_tib = current_tib
                phase = "restricting"
                tib_adjustment = 0
                suggestion = f"💡 睡眠效率 {avg_se}% 偏低。当前卧床 {round(current_tib/60,1)} 小时已接近最优，继续保持"
            else:
                new_tib = target_tib
                phase = "restricting"
                tib_adjustment = current_tib - new_tib
                suggestion = f"📉 睡眠效率 {avg_se}% 偏低，建议将卧床时间调整为 {round(new_tib/60,1)} 小时（推迟入睡时间）"

        # 如果当前 TIB 已在建议值 ±15min 内，不需要调整
        diff = abs(current_tib - new_tib)
        if diff <= 15:
            final_tib = current_tib
            final_bed_min = window["bed_hour"] * 60 + window["bed_min"]
            adjustment_needed = False
            suggestion = f"当前睡眠窗口已经很合适（{round(current_tib/60,1)} 小时），继续保持！"
        else:
            final_tib = new_tib
            adjustment_needed = True

        # 计算建议入睡时间（固定起床时间）
        fixed_wake_min = window["wake_hour"] * 60 + window["wake_min"]
        recommended_bed_min = fixed_wake_min - final_tib
        if recommended_bed_min < 0:
            recommended_bed_min += 24 * 60
        rec_bed_h = recommended_bed_min // 60
        rec_bed_m = recommended_bed_min % 60

        return {
            "phase": phase,
            "has_baseline": True,
            "current_tib_minutes": current_tib,
            "current_tib_hours": round(current_tib / 60, 1),
            "planned_bed_time": f"{window['bed_hour']:02d}:{window['bed_min']:02d}",
            "planned_wake_time": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
            "baseline_tib_minutes": baseline_tib,
            "baseline_tib_hours": round(baseline_tib / 60, 1),
            "avg_se": avg_se,
            "avg_tst_minutes": avg_tst,
            "record_count": record_count,
            "tib_adjustment_minutes": tib_adjustment,
            "adjustment_needed": adjustment_needed,
            "recommended_tib_minutes": final_tib,
            "recommended_tib_hours": round(final_tib / 60, 1),
            "recommended_bed_time": f"{rec_bed_h:02d}:{rec_bed_m:02d}",
            "recommended_wake_time": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
            "message": suggestion,
            "week_tip": _build_restriction_tip(phase, avg_se, avg_tst, final_tib),
        }
    except Exception as e:
        print(f"[sleep_restriction error] {e}")
        return {"status": "error", "message": str(e)}


def _build_restriction_tip(phase: str, avg_se: float, avg_tst: float, tib: int) -> str:
    """根据阶段生成睡眠限制提示语（CBT-I Sleep Restriction Therapy）"""
    tib_h = round(tib / 60, 1)
    tst_h = round(avg_tst / 60, 1)
    if phase == "optimizing":
        return f"🌟 SE {avg_se}% 优秀！本周建议卧床 {tib_h}h（实际睡眠约 {tst_h}h）。睡眠效率越高，可适度多休息。"
    elif phase == "stable":
        return f"👍 SE {avg_se}% 良好，维持 {tib_h}h 睡眠窗口。继续记录，保持规律。"
    elif phase == "restricting":
        return f"📉 SE {avg_se}% 偏低。卧床压缩至 {tib_h}h（入睡时间推迟），目标是让 SE 达到 85% 以上。"
    else:
        return f"继续记录睡眠日记，{max(0, 7 - int(avg_se // 10))} 天后可给出精确建议。"


@app.post("/api/v1/sleep/restriction/apply")
async def apply_sleep_restriction(user: AuthUser = Depends(get_current_user), recommended_bed_time: str = None, recommended_wake_time: str = None):
    user_id = user.user_id
    """
    用户确认应用睡眠限制建议
    - 更新 sleep_window 为推荐值
    - 保存 baseline 数据
    """
    try:
        # 解析推荐时间
        if recommended_bed_time and recommended_wake_time:
            bh, bm = map(int, recommended_bed_time.split(":"))
            wh, wm = map(int, recommended_wake_time.split(":"))
        else:
            window = get_sleep_window(user_id)
            bh, bm = window["bed_hour"], window["bed_min"]
            wh, wm = window["wake_hour"], window["wake_min"]

        save_sleep_window(user_id, bh, bm, wh, wm)

        # 保存基线（来自本周数据）
        records = get_last_n_sleep_records(user_id, 7)
        if records:
            avg_se = round(sum(r["se"] for r in records) / len(records), 1)
            avg_tst = round(sum(r.get("tst_minutes", 0) for r in records) / len(records))
            save_sleep_baseline(user_id, {
                "baseline_tib_minutes": min(max(avg_tst + 30, 4.5 * 60), 9 * 60),
                "avg_se": avg_se,
                "avg_tst_minutes": avg_tst,
                "established_at": datetime.now().isoformat(),
                "固定起床时间": f"{wh:02d}:{wm:02d}",
            })

        return {"status": "ok", "message": f"睡眠窗口已更新：{bh:02d}:{bm:02d} - {wh:02d}:{wm:02d}"}
    except Exception as e:
        print(f"[apply_sleep_restriction error] {e}")
        return {"status": "error", "message": str(e)}


# ==================== Morning Record Helpers ====================

def save_morning_record(user_id: str, date: str, record: dict):
    """保存晨间打卡记录，TTL 365 天"""
    key = f"morning:{user_id}:{date}"
    redis_client.set(key, json.dumps(record, ensure_ascii=False), ex=365*24*3600)


def get_morning_record(user_id: str, date: str) -> Optional[dict]:
    """获取指定日期的晨间打卡"""
    key = f"morning:{user_id}:{date}"
    raw = redis_client.get(key)
    if raw:
        return json.loads(raw)
    return None


def get_last_n_morning_records(user_id: str, n: int = 7) -> list:
    """获取最近 N 天有 SE 记录的晨间打卡（用于睡眠限制算法）"""
    records = []
    for i in range(n):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        record = get_morning_record(user_id, date)
        if record and record.get("se", 0) > 0:
            records.append(record)
    return records


@app.post("/api/v1/evaluate/session")
async def evaluate_session(session_data: dict):
    """评估单个会话的对话质量"""
    try:
        result = dialogue_evaluator.evaluate_session(session_data)
        return dialogue_evaluator.to_dict(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/evaluate/recent")
async def get_recent_evaluations(days: int = Query(7, le=90), limit: int = Query(50, le=200)):
    """获取最近会话的评估结果"""
    from datetime import datetime, timedelta
    import glob
    
    results = []
    cutoff = datetime.now() - timedelta(days=days)
    
    log_files = sorted(
        glob.glob(str(LOG_DIR / "sess_*.json")),
        key=lambda x: os.path.getmtime(x),
        reverse=True
    )[:limit]
    
    for fpath in log_files:
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                continue
            with open(fpath, 'r', encoding='utf-8') as f:
                log = json.load(f)
            eval_data = log.get("quality_evaluation")
            if eval_data:
                report = eval_data.get("report", {})
                results.append({
                    "session_id": log.get("session_id"),
                    "user_id": log.get("user_id"),
                    "timestamp": mtime.isoformat(),
                    "overall_score": eval_data.get("overall_score"),
                    "overall_rating": report.get("overall_rating"),
                    "empathy": report.get("empathy", {}).get("score"),
                    "technical": report.get("technical", {}).get("total"),
                    "coherence": report.get("coherence", {}).get("score"),
                    "safety_pass": report.get("safety", {}).get("pass"),
                    "summary": eval_data.get("summary"),
                    "top_suggestion": report.get("top_suggestion"),
                })
        except Exception:
            continue
    
    return {
        "count": len(results),
        "days": days,
        "evaluations": results,
    }


@app.get("/api/v1/evaluate/summary")
async def get_evaluation_summary(days: int = 30):
    """获取评估统计摘要"""
    from datetime import datetime, timedelta
    import glob
    import statistics
    
    scores = []
    dimension_scores = {}
    
    cutoff = datetime.now() - timedelta(days=days)
    log_files = glob.glob(str(LOG_DIR / "sess_*.json"))
    
    for fpath in log_files:
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                continue
            with open(fpath, 'r', encoding='utf-8') as f:
                log = json.load(f)
            eval_data = log.get("quality_evaluation")
            if eval_data:
                scores.append(eval_data.get("overall_score", 0))
                for d in eval_data.get("dimensions", []):
                    name = d["name"]
                    dimension_scores.setdefault(name, []).append(d["score"])
        except Exception:
            continue
    
    if not scores:
        return {"message": "指定时间范围内无评估数据", "count": 0}
    
    # 同时统计文档对齐的评级分布
    rating_counts = {"🟢优秀": 0, "🟡良好": 0, "🟠需改进": 0, "🔴不合格": 0}
    for fpath in log_files:
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                continue
            with open(fpath, 'r', encoding='utf-8') as f:
                log = json.load(f)
            r = log.get("quality_evaluation", {}).get("report", {}).get("overall_rating", "")
            if r in rating_counts:
                rating_counts[r] += 1
        except Exception:
            continue

    summary = {
        "period_days": days,
        "session_count": len(scores),
        "overall": {
            "mean": round(statistics.mean(scores), 1),
            "median": round(statistics.median(scores), 1),
            "min": round(min(scores), 1),
            "max": round(max(scores), 1),
        },
        "dimensions": {
            name: {
                "mean": round(statistics.mean(vals), 1),
                "median": round(statistics.median(vals), 1),
            }
            for name, vals in dimension_scores.items() if vals
        },
        "rating_distribution": rating_counts,
    }
    return summary


# ==================== 启动 ====================

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)


# ==================== 用户评分 & 评估报告 API ====================

@app.post("/api/v1/sessions/{session_id}/rating")
async def submit_rating(session_id: str, request: Request):
    """用户提交会话评分（支持延迟收集）"""
    try:
        data = await request.json()
        rating = data.get("rating")
        notes = data.get("notes", "")
        if not isinstance(rating, int) or not (1 <= rating <= 5):
            raise HTTPException(status_code=400, detail="rating 必须是 1-5 的整数")
        if not session_logger:
            raise HTTPException(status_code=503, detail="session_logger 不可用")
        success = session_logger.update_rating(session_id, rating, notes if notes else None)
        if success:
            return {"success": True, "session_id": session_id, "rating": rating}
        else:
            raise HTTPException(status_code=404, detail=f"未找到会话 {session_id}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/sessions/{session_id}/report")
async def get_session_report(session_id: str):
    """获取单个会话的《知眠AI沟通质量评估表》格式报告"""
    try:
        log_file = LOG_DIR / f"{session_id}.json"
        if not log_file.exists():
            raise HTTPException(status_code=404, detail=f"未找到会话 {session_id}")
        with open(log_file, 'r', encoding='utf-8') as f:
            log = json.load(f)
        quality = log.get("quality_evaluation", {})
        report = quality.get("report", {})
        if not report:
            # 如果旧数据没有 report，实时评估
            eval_result = dialogue_evaluator.evaluate_session(log)
            report = dialogue_evaluator.to_dict(eval_result).get("report", {})
        return {
            "session_id": session_id,
            "report": report,
            "user_rating": log.get("rating"),
            "user_notes": log.get("notes"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/evaluate/llm_review")
async def llm_review_endpoint(session_data: dict):
    """LLM-as-a-Judge 二次复核（千问）"""
    try:
        if not settings.minimax_api_key:
            raise HTTPException(status_code=503, detail="Minimax API 未配置")
        result = dialogue_evaluator.llm_review(
            session_data.get("session", {}),
            api_key=settings.minimax_api_key,
            base_url=settings.minimax_base_url,
        )
        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["error"])
        return {
            "success": True,
            "review": result,
            "reviewer": "llm_qwen_turbo",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




# ==================== 运营后台 API ====================

@app.post("/api/v1/admin/login")
async def admin_login(request: Request):
    """运营后台登录验证"""
    data = await request.json()
    token = data.get("token", "")
    if not ADMIN_TOKEN:
        return {"success": True, "message": "未配置认证，直接访问"}
    if token == ADMIN_TOKEN:
        return {"success": True, "message": "登录成功"}
    raise HTTPException(status_code=401, detail="Token 错误")


@app.get("/api/v1/admin/dashboard")
async def admin_dashboard(days: int = Query(7, le=90), limit: int = Query(500, le=2000)):
    """仪表盘数据"""
    return get_dashboard_stats(days=days, limit=limit)


@app.get("/api/v1/admin/safety")
async def admin_safety(days: int = Query(30, le=90), limit: int = Query(500, le=2000)):
    """安全中心事件列表"""
    return get_safety_events(days=days, limit=limit)


@app.get("/api/v1/admin/quality")
async def admin_quality(days: int = Query(30, le=90), limit: int = Query(500, le=2000)):
    """AI 质量监控统计"""
    return get_quality_stats(days=days, limit=limit)


@app.get("/api/v1/admin/users")
async def admin_users(days: int = Query(30, le=90), limit: int = Query(500, le=2000)):
    """用户列表"""
    return get_user_list(days=days, limit=limit)


@app.get("/api/v1/admin/users/{user_id}")
async def admin_user_detail(user_id: str, limit: int = Query(20, le=100)):
    """用户详情"""
    return get_user_detail(user_id, limit=limit)



# ==================== 用户数据合规（GDPR/PIPL）====================

@app.get("/api/v1/user/export")
async def export_user_data(user: AuthUser = Depends(get_current_user)):
    """
    导出用户全部数据（GDPR/PIPL 数据可携带权）
    返回 JSON 格式，包含：profile、记忆、睡眠记录、担忧、反馈等
    """
    user_id = user.user_id
    try:
        data = {"user_id": user_id, "exported_at": datetime.now().isoformat(), "data": {}}

        # 1. 用户资料
        profile_raw = redis_client.get(f"user_profile:{user_id}")
        if profile_raw:
            data["data"]["profile"] = json.loads(profile_raw)

        # 2. 用户记忆
        memory_raw = redis_client.get(f"user:memory:{user_id}")
        if memory_raw:
            data["data"]["memory"] = json.loads(memory_raw)

        # 3. 连续使用天数
        streak_raw = redis_client.get(f"user:streak:{user_id}")
        if streak_raw:
            data["data"]["streak"] = json.loads(streak_raw)

        # 4. 睡眠统计
        stats_raw = redis_client.get(f"user:sleep_stats:{user_id}")
        if stats_raw:
            data["data"]["sleep_stats"] = json.loads(stats_raw)

        # 5. 睡眠日记（最近 90 天）
        diaries = []
        for i in range(90):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            diary = get_sleep_diary(user_id, date)
            if diary:
                diaries.append(diary)
        data["data"]["sleep_diaries"] = diaries

        # 6. 主观评分记录
        list_key = f"sleep_list:{user_id}"
        raw_records = redis_client.lrange(list_key, 0, -1)
        data["data"]["sleep_records"] = [json.loads(r) for r in raw_records]

        # 7. 担忧记录
        worry_list_key = f"worry_list:{user_id}"
        raw_worries = redis_client.lrange(worry_list_key, 0, -1)
        data["data"]["worries"] = [json.loads(w) for w in raw_worries]

        # 8. 反馈记录（最近 30 天）
        feedbacks = []
        for i in range(30):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
            fb_key = f"feedback:{user_id}:{date}"
            items = redis_client.lrange(fb_key, 0, -1)
            for item in items:
                feedbacks.append(json.loads(item))
        data["data"]["feedbacks"] = feedbacks

        return {"status": "ok", "data": data}
    except Exception as e:
        print(f"[export_user_data error] {e}")
        raise HTTPException(status_code=500, detail="数据导出失败")


@app.delete("/api/v1/user")
async def delete_user_data(user: AuthUser = Depends(get_current_user)):
    """
    删除用户全部数据（GDPR/PIPL 数据删除权）
    硬删除 Redis 中所有与该用户相关的 key
    """
    user_id = user.user_id
    try:
        deleted_keys = []

        # 1. 删除用户资料
        for key in [f"user_profile:{user_id}", f"user:memory:{user_id}",
                    f"user:streak:{user_id}", f"user:sleep_stats:{user_id}"]:
            if redis_client.delete(key):
                deleted_keys.append(key)

        # 2. 删除睡眠日记
        for i in range(90):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            key = f"sleep_diary:{user_id}:{date}"
            if redis_client.delete(key):
                deleted_keys.append(key)

        # 3. 删除主观评分记录
        list_key = f"sleep_list:{user_id}"
        redis_client.delete(list_key)
        deleted_keys.append(list_key)

        # 4. 删除担忧记录
        worry_key = f"worry_list:{user_id}"
        redis_client.delete(worry_key)
        deleted_keys.append(worry_key)

        # 5. 删除反馈记录
        for i in range(30):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
            key = f"feedback:{user_id}:{date}"
            if redis_client.delete(key):
                deleted_keys.append(key)

        # 6. 清除本地 token（让用户重新登录）
        # 注意：这里只删除数据，不删除微信登录绑定关系

        return {"status": "ok", "deleted_keys_count": len(deleted_keys), "message": "您的数据已删除"}
    except Exception as e:
        print(f"[delete_user_data error] {e}")
        raise HTTPException(status_code=500, detail="数据删除失败")


@app.get("/api/v1/admin/export/users")
async def export_users(days: int = 30):
    """导出用户列表 CSV"""
    csv_data = export_users_csv(days=days)
    return StreamingResponse(
        io.StringIO(csv_data),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"}
    )


@app.get("/api/v1/admin/export/safety")
async def export_safety(days: int = 30):
    """导出安全事件 CSV"""
    csv_data = export_safety_csv(days=days)
    return StreamingResponse(
        io.StringIO(csv_data),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=safety_events.csv"}
    )


@app.get("/api/v1/admin/export/evaluations")
async def export_evaluations(days: int = 30):
    """导出评估数据 CSV"""
    csv_data = export_evaluations_csv(days=days)
    return StreamingResponse(
        io.StringIO(csv_data),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=evaluations.csv"}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


# ==================== 评估偏差追踪 & 告警 API ====================

from evaluation_tracker import record_evaluation, get_bias_stats
from alert_manager import send_alert, send_daily_report
from emotion_analyzer import get_emotion_analyzer, EmotionAnalyzer, EmotionResult

@app.post("/api/v1/evaluate/track")
async def track_evaluation(request: Request):
    """记录 LLM 复核结果，与 auto_v2 做偏差对比"""
    try:
        data = await request.json()
        session_id = data.get("session_id", "")
        auto_report = data.get("auto_report", {})
        llm_report = data.get("llm_report", {})
        record_evaluation(session_id, auto_report, llm_report)
        return {"success": True, "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/evaluate/bias")
async def get_evaluation_bias(days: int = 30):
    """获取 auto_v2 vs LLM 评估偏差统计"""
    return get_bias_stats(days=days)


@app.post("/api/v1/alerts/test")
async def test_alert(request: Request):
    """测试告警推送（模拟一个需改进会话）"""
    try:
        data = await request.json()
        report = data.get("report", {
            "session_id": "test_alert",
            "user_id": "test_user",
            "stage": "intake",
            "overall_rating": "🟠需改进",
            "empathy": {"score": 2},
            "technical": {"total": 2, "cognitive": {"score": 0}, "behavioral": {"score": 1}, "habit": {"score": 1}},
            "coherence": {"score": 2},
            "safety": {"pass": True, "crisis_status": "未触发", "bad_advice_found": False},
            "top_suggestion": "测试告警：共情质量偏低，建议增加确认和接纳。",
        })
        success = send_alert(report)
        return {"success": success, "webhook_configured": bool(os.getenv("ALERT_WEBHOOK_URL", ""))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/alerts/daily")
async def push_daily_report(days: int = 1):
    """手动推送日报"""
    try:
        from datetime import datetime, timedelta
        import glob, statistics
        scores = []
        dimension_scores = {}
        rating_counts = {"🟢优秀": 0, "🟡良好": 0, "🟠需改进": 0, "🔴不合格": 0}
        cutoff = datetime.now() - timedelta(days=days)
        log_files = glob.glob(str(LOG_DIR / "sess_*.json"))
        for fpath in log_files:
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                if mtime < cutoff:
                    continue
                with open(fpath, "r", encoding="utf-8") as f:
                    log = json.load(f)
                eval_data = log.get("quality_evaluation")
                if eval_data:
                    scores.append(eval_data.get("overall_score", 0))
                    for d in eval_data.get("dimensions", []):
                        name = d["name"]
                        dimension_scores.setdefault(name, []).append(d["score"])
                    r = eval_data.get("report", {}).get("overall_rating", "")
                    if r in rating_counts:
                        rating_counts[r] += 1
            except Exception:
                continue
        if not scores:
            return {"message": "指定时间范围内无数据"}
        summary = {
            "period_days": days,
            "session_count": len(scores),
            "overall": {
                "mean": round(statistics.mean(scores), 1),
                "median": round(statistics.median(scores), 1),
                "min": round(min(scores), 1),
                "max": round(max(scores), 1),
            },
            "dimensions": {
                name: {
                    "mean": round(statistics.mean(vals), 1),
                    "median": round(statistics.median(vals), 1),
                }
                for name, vals in dimension_scores.items() if vals
            },
            "rating_distribution": rating_counts,
        }
        success = send_daily_report(summary)
        return {"success": success, "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# Actions test 3 - PEM key
# debug deploy test
# test deploy v2
# deploy test v3
# deploy v4


# ==================== 情感分析 API ====================

class EmotionAnalyzeRequest(BaseModel):
    text: str
    user_id: Optional[str] = None

@app.post("/api/v1/emotion/analyze")
async def emotion_analyze(req: EmotionAnalyzeRequest):
    """
    分析用户文本的情绪状态
    返回：主情绪、强度、风险标记、担忧领域、认知扭曲信号、自杀风险
    """
    try:
        analyzer = get_emotion_analyzer()
        result = analyzer.analyze(req.text)
        return analyzer.to_dict(result)
    except Exception as e:
        print(f"[EmotionAPI] 分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"情感分析失败: {str(e)}")
