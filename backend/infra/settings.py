"""
应用配置（从 main.py 提取）
"""
import os
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 千问 / DashScope 凭证
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # 腾讯云（流式 TTS + 实时 ASR）
    tencentcloud_app_id: str = ""
    tencentcloud_secret_id: str = ""
    tencentcloud_secret_key: str = ""
    tencentcloud_region: str = "ap-guangzhou"
    tencentcloud_app_id_2: str = ""
    tencentcloud_secret_id_2: str = ""
    tencentcloud_secret_key_2: str = ""
    tencentcloud_app_id_3: str = ""
    tencentcloud_secret_id_3: str = ""
    tencentcloud_secret_key_3: str = ""

    # MiniMax 对话 API
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimaxi.com/v1"
    minimax_group_id: str = ""
    minimax_secret_id: str = ""

    # DeepSeek 对话 API（首字 ~500ms，比 MiniMax 快 4 倍）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"   # 当前最快的非 thinking 模型
    # llm_provider: "deepseek" | "minimax"  (deepseek 配置就走 deepseek)
    llm_provider: str = "deepseek"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    redis_async_url: str = ""

    # TTS 预热
    tts_warmup_phrases: str = "嗯,我在,好的,稍等,嗯嗯,我在听,好,嗯嗯嗯"

    # ASR 预热
    asr_warmup_connections: int = 2

    # 腾讯云 ASR 热词表 ID (中英混读优化)。控制台 → 语音识别 → 热词管理 → 复制 ID 填这里。
    # 空字符串表示不启用。
    tencent_asr_hotword_id: str = ""

    # ASR transcript LLM 二次纠错(中英混读纠错)。
    # 仅当检测到 transcript 同时含中文 + 英文时触发,纯中文/纯英文跳过(避免无谓延迟)。
    # 走 deepseek_chat,需 deepseek_api_key 已配置。
    asr_llm_repair_enabled: bool = True
    asr_llm_repair_timeout_s: float = 4.0
    asr_llm_repair_min_len: int = 4  # 短于此长度不纠错

    # JWT
    jwt_secret: str = "dev-secret-change-in-prod"

    # 微信小程序
    wx_app_id: str = ""
    wx_app_secret: str = ""

    # 运营后台
    admin_token: str = ""

    # 邮箱登录(Web 出海)。配置 resend_api_key 即发真邮件;否则开发态返回验证码
    resend_api_key: str = ""
    auth_from_email: str = "ZhiMian <noreply@sleepai.chat>"
    env: str = "production"

    # Google 登录(Sign in with Google)。Web OAuth Client ID(xxx.apps.googleusercontent.com)
    google_client_id: str = ""
    # Google 公钥(JWKS)地址。中国服务器无法直连 googleapis.com,可改成可达的代理(如 Cloudflare Worker)
    google_jwks_url: str = "https://www.googleapis.com/oauth2/v3/certs"

    @field_validator("tts_warmup_phrases", mode="before")
    @classmethod
    def _strip_tts_phrases(cls, v):
        if v is None:
            return ""
        if isinstance(v, (list, tuple)):
            return ",".join(str(x) for x in v)
        return str(v).strip().rstrip(",")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# 全局单例
settings = Settings()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", settings.admin_token)
BACKEND_VERSION = "2.1.0"
