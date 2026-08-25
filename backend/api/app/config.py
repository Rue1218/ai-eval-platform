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
    # Harness 记忆层：Redis 仅存可过期短期状态，长期审计仍使用 PostgreSQL。
    # 短期 Port 默认关闭；Redis 容器经 feat/deploy-* 落地后再由环境变量开启。
    redis_url: str = "redis://localhost:6379/0"
    harness_memory_short_term_enabled: bool = False
    harness_memory_ttl_seconds: int = 86400
    # 协议档连接参数写入的受控环境文件；生产通过 Compose 挂载宿主机 .env。
    profile_env_file: str = ".env"
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
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
    # 原生网络工具：仅 API 容器读取 Firecrawl REST 凭据，模型、WS 事件与日志
    # 均不回显。未配置 Key 时 web_search 明确返回 VALIDATION；web_fetch 仍可走
    # SSRF 防护后的最小直接文本抓取。
    firecrawl_api_url: str = "https://api.firecrawl.dev/v1"
    firecrawl_api_key: str = ""
    # Harness 沙箱（bash 工具）：bwrap 内核由独立 runner 容器执行（P4-2），
    # api 不再持有 privileged/bubblewrap。engine 为 "bwrap" 时开放通用 bash；
    # engine 为 "off" 时 bash 工具 fail-closed。
    sandbox_engine: str = "bwrap"
    sandbox_memory_mb: int = 256  # 沙箱虚拟内存上限（MB）
    sandbox_nproc: int = 32  # 沙箱最大进程数（防 fork 炸弹）
    sandbox_cpu_s: int = 10  # 沙箱 CPU 时间上限（秒）
    # 独立沙箱 runner 服务（compose 内网，默认 runner:8001，不发布主机端口）
    sandbox_runner_url: str = "http://runner:8001"
    # P4-2：资源配额与熔断
    max_active_tasks_per_user: int = 5  # 每用户活动任务（queued/running/awaiting_case_confirm）上限
    circuit_failure_threshold: int = 5  # 服务器连续基础设施失败阈值，达到即熔断 open
    circuit_cooldown_s: float = 30.0  # 熔断冷却时长（秒），到期自动恢复 closed

    @property
    def cors_origin_list(self) -> list[str]:
        """将逗号分隔的可信前端 Origin 转换为中间件列表。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
