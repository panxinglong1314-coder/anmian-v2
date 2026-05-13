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

    # JWT
    jwt_secret: str = "dev-secret-change-in-prod"

    # 微信小程序
    wx_app_id: str = ""
    wx_app_secret: str = ""

    # 运营后台
    admin_token: str = ""

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
