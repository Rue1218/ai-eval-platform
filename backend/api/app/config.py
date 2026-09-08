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
    # F2/G4：bash 默认档位（《工作区与沙箱设计方案》§6，只声明文件效果）。
    # "workspace-write" = 现状可写语义（F4 read-only 灰度前保持无行为变化）；
    # F4 灰度时翻转 "read-only"（拒写 → 升档审批）。"none"（bash 不可达）由
    # sandbox_engine=off fail-closed 承担，本字段不接受 none。
    sandbox_bash_default_mode: str = "workspace-write"
    sandbox_memory_mb: int = 256  # 沙箱虚拟内存上限（MB）
    sandbox_nproc: int = 32  # 沙箱最大进程数（防 fork 炸弹）
    sandbox_cpu_s: int = 10  # 沙箱 CPU 时间上限（秒）
    # 独立沙箱 runner 服务（compose 内网，默认 runner:8001，不发布主机端口）
    sandbox_runner_url: str = "http://runner:8001"
    # P4-2：资源配额与熔断
    max_active_tasks_per_user: int = 5  # 每用户活动任务（queued/running/awaiting_case_confirm）上限
    circuit_failure_threshold: int = 5  # 服务器连续基础设施失败阈值，达到即熔断 open
    circuit_cooldown_s: float = 30.0  # 熔断冷却时长（秒），到期自动恢复 closed
    # P3：检查点引擎。默认 memory（每回合独立 thread_id）；postgres 需单独评审
    # 多副本粘性路由后再开，禁止把 Observation 全文写入检查点。
    agent_checkpointer: str = "memory"
    # H5 批次 2：HITL 生产门禁。true 时（生产部署）若混合引擎开启且检查点为
    # memory，启动期 fail-fast（HITL resume 无法跨进程重启恢复）；false（默认）
    # 仅在 agent_trace 输出告警，便于单副本/测试环境用 memory 验证 interrupt 语义。
    agent_hitl_strict_pg: bool = False
    # H5 批次 2：API 实例标识（粘性路由用）。空 = 启动期自动派生（hostname+pid）；
    # 多副本部署时网关按 session_id 粘性路由，同一会话固定落点以保证会话级
    # abort dict 与 interrupt resume 的 thread_id 可寻址。暴露于 /api/health。
    agent_instance_id: str = ""
    # H5 收尾演练开关：true 时 discover 允许选中 worker.sandbox（仅演练专用，
    # 配合《H5 持久化 HITL 收尾演练》§3 制造危险 bash 审批卡验证重启恢复）。
    # 默认 false 保持静态排除 fail-closed；演练结束必须置回 false——放行属
    # 生产红线，须先完成 Linux/Docker 恢复演练与 bwrap 权限边界评审。
    agent_drill_sandbox_enabled: bool = False
    # P1/P4：native 首轮流式。默认开启（已落地）；false 回退 invoke，不改历史事件。
    agent_native_stream_enabled: bool = True
    # 逗号分隔协议档 ID；空 = 全部 native。``*`` 同样表示全部。
    agent_native_stream_profile_ids: str = ""
    # F0/P1：Agent 原生工具装配（《Agent 原生工具装配方案》V0.2 D1/D5）。主闸门
    # 默认关 = tools 不注入（请求逐字节保持现状）；开启后按
    # agent_native_tools_profile_ids 白名单逐协议档放行（空 = 不开任何档，
    # ``*`` = 全部——与 stream 白名单语义一致）。tool_call_mode 不担任装配
    # 许可（生产默认已 native，防主闸门一开即全量下发）；装配层是唯一消费点。
    agent_native_tools_enabled: bool = False
    agent_native_tools_profile_ids: str = ""
    # P3/P4：同轮只读 ToolBatch 并行。默认关闭。
    agent_parallel_tool_batch_enabled: bool = False
    max_parallel_tool_calls: int = 3
    # 并行灰度白名单：空 = 不开任何协议档；``*`` = 全部；否则仅列出的 ID。
    agent_parallel_tool_batch_profile_ids: str = ""
    # 工具卡片浏览器预览上限（字符，按完整行边界截取）。默认与 read 模型窗口
    # 预算（READ_MAX_CHARS=600_000）对齐，使 ToolCard 所见 == 模型真实读取
    # 内容；需要收紧回旧版安全窗时设 TOOL_PREVIEW_MAX_CHARS=4000。
    tool_preview_max_chars: int = 600_000
    # ===== 混合驱动引擎（H0 基础设施灰度开关；全部默认安全关闭）=====
    hybrid_engine_enabled: bool = False  # 主开关；关闭时保持骨架化纯对话（灰度回滚出口）
    hybrid_router_cot_enabled: bool = False  # Router L1 CoT 开关；关闭时纯 L0
    hybrid_router_confidence_threshold: float = 0.7  # L0 置信度低于此值才触发 L1 CoT
    # dsh 改进 D4/G3 并发配额：每 scope bash 闸门限时等待（秒）；runner 侧全局
    # 槽位由 RUNNER_MAX_WORKERS（默认 4）/ RUNNER_SLOT_WAIT_S（5s）env 控制
    sandbox_bash_gate_timeout_s: float = 30.0
    agent_registry_strict: bool = True  # AgentDef.allowed_tools 未注册时启动 fail-fast
    prompt_cache_enabled: bool = False  # 提示词缓存边界开关；关闭时装配行为与今日字节级一致
    external_mcp_enabled: bool = False  # 外部 MCP fail-closed（ADR-8）
    # dsh 改进 #4 事件词汇表版本化（登记《dsh 借鉴与 AgentHarness 改进方案》§6.3）：
    # false（默认）灰度——转发循环对未知 kind/版本不符事件告警并跳过；
    # true——fail-closed 拒收并落 error。灰度观察期（生产无未知事件告警）后置
    # true；若 fail-closed 长期必要，评估固化为常驻校验而非开关（复盘后删除）。
    event_vocab_strict: bool = False
    # dsh 改进 #3 审批终态（API.md §4.3 V1.73）：审批卡 TTL（秒，默认 1 小时）。
    # 超龄卡由 api 后台扫描行锁清卡并广播 approval_terminal(expired)；失效判定
    # 以卡 meta.created_at + 当前时间幂等兜底，不依赖扫描进程存活性。常量入
    # config，禁止硬编码（方案 §3.3.5 边界）。
    agent_approval_ttl_seconds: int = 3600

    @property
    def cors_origin_list(self) -> list[str]:
        """将逗号分隔的可信前端 Origin 转换为中间件列表。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
