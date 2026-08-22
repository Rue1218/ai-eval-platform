from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """由环境变量注入的服务端运行配置。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://aieval:aieval_pass@localhost:5432/aieval"
    secret_key: str = "dev-secret-change-me"
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin123"
    key_encryption_key: str = ""
    access_token_expire_minutes: int = 720
    ws_ticket_expire_minutes: int = 5
    data_dir: str = "/data"
    # 协议档连接参数写入的受控环境文件；生产通过 Compose 挂载宿主机 .env。
    profile_env_file: str = ".env"
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Redis 只承载可过期短期记忆；生产 Compose 注入 REDIS_URL，未配置的本地环境仅使用 PG 对话归档。
    redis_url: str = ""
    memory_tenant_id: str = "internal"
    memory_redis_ttl_seconds: int = 86400
    # 音色克隆（MIMO TTS，OpenAI chat/completions 兼容）。Key 只从环境注入，禁止回显。
    mimo_tts_base_url: str = "https://token-plan-cn.xiaomimimo.com/v1"
    mimo_tts_api_key: str = ""
    mimo_tts_model: str = "mimo-v2.5-tts-voiceclone"
    mimo_tts_timeout_s: float = 90.0
    # MiMo 音频短工具（ASR/TTS，OpenAI chat/completions 兼容）。Key 只从环境注入，禁止回显。
    mimo_audio_base_url: str = "https://token-plan-cn.xiaomimimo.com/v1"
    mimo_audio_api_key: str = ""
    mimo_audio_timeout_s: float = 90.0
    mimo_asr_model: str = "mimo-v2.5-asr"
    mimo_tts_preset_model: str = "mimo-v2.5-tts"
    mimo_tts_voicedesign_model: str = "mimo-v2.5-tts-voicedesign"
    mimo_tts_voice: str = "mimo_default"
    # Qwen Image 图像生成（DashScope 多模态生成接口）。Key 只从环境注入，禁止回显。
    qwen_image_api_url: str = ""
    qwen_image_api_key: str = ""
    qwen_image_model: str = ""
    qwen_image_timeout_seconds: float = 120.0

    @property
    def cors_origin_list(self) -> list[str]:
        """将逗号分隔的可信前端 Origin 转换为中间件列表。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
