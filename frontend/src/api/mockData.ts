/**
 * AI 测试与评估平台 — 示例 Mock 数据种子
 * 依据：Web-Prototype MOCK_SEED 与 PRD V1.6.4 / API V1.3
 */
import type {
  Profile,
  Dataset,
  DatasetRow,
  KnowledgeBase,
  KbDocument,
  GoldQA,
  AuthUser,
  AdminSettings,
  CaseSet,
  TestCase,
  Task,
  Report,
  WhitelistItem,
  McpTool,
} from './types'

export const MOCK_PROFILES: Profile[] = [
  {
    id: 'p-gpt',
    name: 'gpt-test',
    protocol: 'openai_chat',
    base_url: 'https://api.openai.com/v1',
    model: 'gpt-4o',
    usages: ['target'],
    created_at: '2026-08-02T09:00:00Z',
  },
  {
    id: 'p-claude',
    name: 'claude-x',
    protocol: 'anthropic_messages',
    base_url: 'https://api.anthropic.com/v1',
    model: 'claude-3-5-sonnet-20241022',
    usages: ['target'],
    created_at: '2026-08-02T09:10:00Z',
  },
  {
    id: 'p-agent',
    name: 'agent-主',
    protocol: 'anthropic_messages',
    base_url: 'https://api.anthropic.com/v1',
    model: 'claude-3-5-sonnet-20241022',
    usages: ['agent'],
    created_at: '2026-08-01T08:00:00Z',
  },
  {
    id: 'p-judge',
    name: 'judge-1',
    protocol: 'openai_responses',
    base_url: 'https://api.openai.com/v1',
    model: 'o4',
    usages: ['judge'],
    created_at: '2026-08-03T10:00:00Z',
  },
  {
    id: 'p-ragsvc',
    name: 'rag-客服外挂',
    protocol: 'openai_chat',
    base_url: 'http://10.0.0.8:8080',
    model: 'rag-chat-v2',
    usages: ['target'],
    created_at: '2026-08-05T11:00:00Z',
  },
]

export const MOCK_DATASETS: Dataset[] = [
  {
    id: 'ds-smoke',
    name: 'smoke-20',
    version: 3,
    row_count: 20,
    pending_complete_count: 2,
    metric: 'contain',
    owner: 'alice',
    created_at: '2026-08-10T03:00:00Z',
  },
  {
    id: 'ds-pay',
    name: '支付链路问答',
    version: 1,
    row_count: 156,
    pending_complete_count: 0,
    metric: 'rouge_l',
    owner: 'bob',
    created_at: '2026-08-12T07:30:00Z',
  },
  {
    id: 'ds-faq',
    name: 'FAQ-标准问',
    version: 2,
    row_count: 480,
    pending_complete_count: 6,
    metric: 'exact',
    owner: 'alice',
    created_at: '2026-08-14T02:20:00Z',
  },
]

export const MOCK_PENDING_ROWS: DatasetRow[] = [
  {
    row_no: 3,
    question: '',
    reference: '在「设置-账单」中申请',
    context: null,
    source_case_id: 'c-018',
    is_pending: true,
  },
  {
    row_no: 17,
    question: '如何导出上一年度对账单？',
    reference: '',
    context: null,
    source_case_id: 'c-031',
    is_pending: true,
  },
]

export const MOCK_KBS: KnowledgeBase[] = [
  {
    id: 'kb-default',
    name: 'default',
    kind: 'lightrag',
    doc_count: 12,
    is_core: true,
    owner: 'admin',
    // 内置 LightRAG 库默认具备向量投影与重排对比能力，用于解锁知识库工作台对应面板。
    capabilities: { projection: true, rerank_compare: true },
    created_at: '2026-08-01T00:00:00Z',
  },
  {
    id: 'kb-cs',
    name: '外挂客服',
    kind: 'external_chat',
    doc_count: null,
    is_core: false,
    owner: 'alice',
    profile_id: 'p-ragsvc',
    created_at: '2026-08-05T00:00:00Z',
  },
]

export const MOCK_KB_DOCS: KbDocument[] = [
  { doc_id: 'd-01', filename: 'product-manual.pdf', status: 'indexed', size: '2.4 MB', created_at: '2026-08-10' },
  { doc_id: 'd-02', filename: 'faq-2026.md', status: 'indexed', size: '88 KB', created_at: '2026-08-11' },
  { doc_id: 'd-03', filename: 'refund-policy.html', status: 'indexing', size: '41 KB', created_at: '2026-08-12' },
]

export const MOCK_GOLD_QAS: GoldQA[] = [
  {
    id: 'gq-1',
    kb_id: 'kb-default',
    name: 'qa-v1',
    version: 2,
    row_count: 20,
    owner: 'admin',
    created_at: '2026-08-13T02:00:00Z',
  },
  {
    id: 'gq-2',
    kb_id: 'kb-cs',
    name: '客服黄金集',
    version: 1,
    row_count: 64,
    owner: 'alice',
    created_at: '2026-08-15T09:30:00Z',
  },
]

export const MOCK_USERS: AuthUser[] = [
  { id: 'u-admin', username: 'admin', role: 'member', disabled: false, created_at: '2026-08-01T00:00:00Z' },
  { id: 'u-alice', username: 'alice', role: 'member', disabled: false, created_at: '2026-08-02T03:00:00Z' },
  { id: 'u-bob', username: 'bob', role: 'member', disabled: false, created_at: '2026-08-04T06:00:00Z' },
  { id: 'u-boss', username: 'boss', role: 'member', disabled: false, created_at: '2026-08-06T08:00:00Z' },
  { id: 'u-carol', username: 'carol', role: 'member', disabled: true, created_at: '2026-08-07T09:00:00Z' },
]

export const MOCK_SETTINGS: AdminSettings = {
  agent_profile_id: 'p-agent',
  agent_reasoning: { enabled: true, effort: 'medium' },
  max_running_tasks: 3,
  max_inflight_model_calls: 8,
  default_max_usd: 5,
  stress: {
    host_whitelist: ['10.0.0.8', 'api.internal.eval'],
    max_qps: 500,
    max_duration_s: 1800,
    price_per_1k_tokens: 0.002,
  },
  notify: {
    wecom: false,
    email: false,
    webhook: false,
  },
  prod_approvers: ['admin', 'bob'],
}

export const MOCK_WHITELIST: WhitelistItem[] = [
  { id: 'wl-1', host: '10.0.0.8', scope: 'test,staging', creator: 'admin', created_at: '2026-08-01', status: 'active' },
  { id: 'wl-2', host: 'api.internal.eval', scope: 'test', creator: 'admin', created_at: '2026-08-05', status: 'active' },
]

// 全量工具清单 Mock（与后端 /api/mcp/all-tools 保持一致）
// transport='native'：原生基础工具，NativeToolExecutor 直连执行
// transport='mcp'：内部 MCP 扩展，platform.tasks 任务队列桥
export const MOCK_MCP_TOOLS: McpTool[] = [
  // ── 原生基础工具（transport=native）──
  {
    name: 'read', display_name: '读取文件', desc: '按行读取沙箱目录内的文本文件（相对路径）',
    permission: 'sandbox.read', enabled: true, source: 'builtin',
    transport: 'native', category: 'native_toolcall', server_id: 'platform.native', risk_level: 'read',
    timeout_s: 20, supports_streaming: true, execution_mode: 'short',
    parameters_schema: {
      type: 'object',
      properties: {
        path: { type: 'string', description: '相对路径' },
        offset: { type: 'integer', description: '起始行号，0-based，默认 0', minimum: 0 },
        limit: { type: 'integer', description: '最多读取行数，默认/上限 2000', minimum: 1, maximum: 2000 },
      },
      required: ['path'],
    },
    output_schema: {
      type: 'object',
      properties: {
        summary: { type: 'string' },
        read: {
          type: 'object',
          properties: {
            path: { type: 'string' },
            total_lines: { type: 'integer' },
            start_line: { type: 'integer' },
            end_line: { type: 'integer' },
            next_offset: { type: 'integer' },
            preview: { type: 'string' },
          },
        },
      },
    },
    code_details: {
      source_file: 'backend/api/app/harness/execution/registry.py',
      handler_function: '_read_handler(arguments, sandbox_dir, context)',
      code_summary: '相对路径安全校验 -> 读取指定文件 -> 0-based offset/limit 分页解码 -> 字符截断与上下文防爆仓保护 -> 输出 preview 摘要',
    },
    pipeline: {
      stages: [
        { step: 1, name: '参数解析与范围校验', desc: '解析 path、offset、limit 边界' },
        { step: 2, name: '工作区防越界检查', desc: '路径归一化，严格限制在当前会话沙箱目录内' },
        { step: 3, name: '按行切片读取', desc: 'UTF-8 编码读取并按行截取目标窗口' },
        { step: 4, name: '防撑爆截断保护', desc: '单次上限 600,000 字符，生成 next_offset 引导分页' },
        { step: 5, name: '结构化结果投影', desc: '生成 summary 与 preview 结构回填 Agent 上下文' },
      ],
    },
  },
  {
    name: 'write', display_name: '写入文件', desc: '在沙箱目录内新建文本文件（相对路径）',
    permission: 'sandbox.write', enabled: true, source: 'builtin',
    transport: 'native', category: 'native_toolcall', server_id: 'platform.native', risk_level: 'modify',
    timeout_s: 10, supports_streaming: true, execution_mode: 'short',
    parameters_schema: {
      type: 'object',
      properties: {
        path: { type: 'string', description: '相对路径' },
        content: { type: 'string', description: '文件内容' },
      },
      required: ['path', 'content'],
    },
    output_schema: {
      type: 'object',
      properties: {
        summary: { type: 'string' },
        write: {
          type: 'object',
          properties: {
            path: { type: 'string' },
            bytes_written: { type: 'integer' },
            lines_written: { type: 'integer' },
            preview: { type: 'string' },
          },
        },
      },
    },
    code_details: {
      source_file: 'backend/api/app/harness/execution/registry.py',
      handler_function: '_write_handler(arguments, sandbox_dir, context)',
      code_summary: '路径沙箱检验 -> 校验非覆盖策略 -> 自动创建父目录 -> 原子写入 content 文本 -> 统计 bytes/lines',
    },
    pipeline: {
      stages: [
        { step: 1, name: '参数必填校验', desc: '检查 path 相对路径与 content 内容' },
        { step: 2, name: '非覆盖安全策略', desc: '若文件已存在则拦截并引导改用 edit' },
        { step: 3, name: '沙箱隔离约束', desc: '限制在当前会话沙箱工作区' },
        { step: 4, name: '原子写盘', desc: '递归创建父目录并原子写盘' },
        { step: 5, name: '写入统计回执', desc: '统计字节数与行数' },
      ],
    },
  },
  {
    name: 'edit', display_name: '编辑文件', desc: '在沙箱目录内对已有文本文件做精确字符串替换',
    permission: 'sandbox.write', enabled: true, source: 'builtin',
    transport: 'native', category: 'native_toolcall', server_id: 'platform.native', risk_level: 'modify',
    timeout_s: 10, supports_streaming: false, execution_mode: 'short',
    parameters_schema: {
      type: 'object',
      properties: {
        path: { type: 'string', description: '相对路径' },
        old: { type: 'string', description: '待替换的旧文本（须在文件中唯一出现）' },
        new: { type: 'string', description: '替换后的新文本' },
      },
      required: ['path', 'old', 'new'],
    },
    output_schema: {
      type: 'object',
      properties: {
        summary: { type: 'string' },
        edit: {
          type: 'object',
          properties: {
            path: { type: 'string' },
            replacements: { type: 'integer' },
            old_length: { type: 'integer' },
            new_length: { type: 'integer' },
          },
        },
      },
    },
    code_details: {
      source_file: 'backend/api/app/harness/execution/registry.py',
      handler_function: '_edit_handler(arguments, sandbox_dir, context)',
      code_summary: '读取全文 -> 验证 old 字符串在文件中唯一匹配 -> 字符串精确替换为 new -> 原子写回',
    },
    pipeline: {
      stages: [
        { step: 1, name: '目标文件存在性检查', desc: '验证文件是否存在于会话沙箱' },
        { step: 2, name: '全文精确查找', desc: '计算 old 字符串出现次数' },
        { step: 3, name: '唯一性强约束拦截', desc: '匹配非 1 次时拦截以防误改' },
        { step: 4, name: '单处精确替换', desc: '保留缩进与上下文结构替换' },
        { step: 5, name: '持久化与回执', desc: '写回沙箱工作区并返回统计' },
      ],
    },
  },
  {
    name: 'bash', display_name: '沙箱命令', desc: '在 bwrap 沙箱内执行 shell 命令（相对路径、无网络、受资源限制）',
    permission: 'sandbox.exec', enabled: true, source: 'builtin',
    transport: 'native', category: 'native_toolcall', server_id: 'platform.native', risk_level: 'code',
    timeout_s: 15, supports_streaming: true, execution_mode: 'short',
    parameters_schema: {
      type: 'object',
      properties: {
        command: { type: 'string', description: '待执行的 shell 脚本或命令' },
      },
      required: ['command'],
    },
    output_schema: {
      type: 'object',
      properties: {
        summary: { type: 'string' },
        bash: {
          type: 'object',
          properties: {
            command: { type: 'string' },
            exit_code: { type: 'integer' },
            stdout: { type: 'string' },
            stderr: { type: 'string' },
          },
        },
      },
    },
    code_details: {
      source_file: 'backend/api/app/harness/execution/sandbox.py',
      handler_function: '_bash_handler(arguments, sandbox_dir, context)',
      code_summary: '静态高危黑名单拦截 -> 一次性 bwrap 沙箱创建 -> 根系统只读绑定 + 会话工作区唯一可写 -> 无网络隔离 -> ulimit 限制 + 15s 超时整树清理 -> stdout/stderr 脱敏截断',
    },
    pipeline: {
      stages: [
        { step: 1, name: '静态安全黑名单过滤', desc: '拦截 rm -rf /、提权与破坏命令' },
        { step: 2, name: 'bwrap 命名空间构建', desc: '--unshare-net 禁用外网通信' },
        { step: 3, name: '只读环境与工作区挂载', desc: '系统只读，仅 /workspace 可写' },
        { step: 4, name: '执行监控与资源约束', desc: 'ulimit 限制内存，15s 超时 SIGKILL' },
        { step: 5, name: '凭据脱敏与输出投影', desc: '自动过滤敏感 Token 并截断' },
      ],
    },
  },
  {
    name: 'web_search', display_name: '网页检索', desc: '内部搜索引擎检索（平台自实现适配器，不走外部 MCP）',
    permission: 'web.search', enabled: true, source: 'builtin',
    transport: 'native', category: 'native_toolcall', server_id: 'platform.native', risk_level: 'network',
    timeout_s: 20, supports_streaming: false, execution_mode: 'short',
    parameters_schema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: '搜索关键词 (1-500字符)' },
        limit: { type: 'integer', description: '返回结果条数，默认 5，上限 10', minimum: 1, maximum: 10 },
      },
      required: ['query'],
    },
    output_schema: {
      type: 'object',
      properties: {
        summary: { type: 'string' },
        search: {
          type: 'object',
          properties: {
            query: { type: 'string' },
            items: { type: 'array' },
          },
        },
      },
    },
    code_details: {
      source_file: 'backend/api/app/harness/execution/registry.py',
      handler_function: '_web_search_handler(arguments, sandbox_dir, context)',
      code_summary: '清洗搜索关键词 -> 内部搜索引擎客户端发起请求 -> 提取标题/摘要/URL -> 结构化 JSON 投影',
    },
    pipeline: {
      stages: [
        { step: 1, name: '搜索关键词预处理', desc: '清洗 query 字符串与限制条数' },
        { step: 2, name: '合规与敏感词过滤', desc: '校验检索词安全性与防注入拦截' },
        { step: 3, name: '搜索引擎客户端查询', desc: '内部专有搜索引擎并发检索' },
        { step: 4, name: '结构化抽取', desc: '提取标题、摘要及源 URL' },
        { step: 5, name: '上下文防爆仓压缩', desc: '组织成标准 JSON 回传' },
      ],
    },
  },
  {
    name: 'web_fetch', display_name: '网页抓取', desc: '内部网页抓取（平台自实现适配器 + 脱敏，不走外部 MCP）',
    permission: 'web.fetch', enabled: true, source: 'builtin',
    transport: 'native', category: 'native_toolcall', server_id: 'platform.native', risk_level: 'network',
    timeout_s: 20, supports_streaming: true, execution_mode: 'short',
    parameters_schema: {
      type: 'object',
      properties: {
        url: { type: 'string', description: '公开网页 URL 地址' },
        format: { type: 'string', enum: ['markdown', 'text'], description: '返回格式，默认 markdown' },
      },
      required: ['url'],
    },
    output_schema: {
      type: 'object',
      properties: {
        summary: { type: 'string' },
        web: {
          type: 'object',
          properties: {
            url: { type: 'string' },
            format: { type: 'string' },
            content: { type: 'string' },
          },
        },
      },
    },
    code_details: {
      source_file: 'backend/api/app/harness/execution/registry.py',
      handler_function: '_web_fetch_handler(arguments, sandbox_dir, context)',
      code_summary: 'URL 防 SSRF 检查 -> HTTP GET 请求 -> 网页 HTML 转 Markdown -> 敏感数据脱敏 -> 截断输出',
    },
    pipeline: {
      stages: [
        { step: 1, name: 'SSRF 安全防御拦截', desc: '严禁抓取 127.0.0.1 及内网网段' },
        { step: 2, name: '异步 HTTP 网页请求', desc: '设置 20s 超时抓取公开网页' },
        { step: 3, name: 'HTML 转换与降噪', desc: '提取正文并转换为 Markdown' },
        { step: 4, name: '隐私凭据脱敏', desc: '抹除正文中的 API Key 与 Token' },
        { step: 5, name: '截断安全回传', desc: '限制最大 12,000 字符防止撑爆' },
      ],
    },
  },
  {
    name: 'task', display_name: '拆解任务', desc: '维护本回合的执行清单：把复杂需求拆成有限步骤并标注状态',
    permission: 'task.planner', enabled: true, source: 'builtin',
    transport: 'native', category: 'native_toolcall', server_id: 'platform.native', risk_level: 'read',
    timeout_s: 2, supports_streaming: false, execution_mode: 'short',
    parameters_schema: {
      type: 'object',
      properties: {
        tasks: {
          type: 'array',
          description: '任务清单项列表',
          items: {
            type: 'object',
            properties: {
              id: { type: 'string' },
              title: { type: 'string' },
              status: { type: 'string', enum: ['pending', 'in_progress', 'completed'] },
            },
          },
        },
      },
      required: ['tasks'],
    },
    output_schema: {
      type: 'object',
      properties: {
        summary: { type: 'string' },
        task: {
          type: 'object',
          properties: {
            tasks: { type: 'array' },
            updated_at: { type: 'string' },
          },
        },
      },
    },
    code_details: {
      source_file: 'backend/api/app/harness/execution/registry.py',
      handler_function: '_task_planner_handler(arguments, sandbox_dir, context)',
      code_summary: '解析 tasks 执行步骤 -> 校验步骤状态机 (pending/in_progress/completed) -> 更新回合 GraphState',
    },
    pipeline: {
      stages: [
        { step: 1, name: '执行清单步骤解析', desc: '读取 tasks 步骤数组' },
        { step: 2, name: '状态机跃迁合规', desc: '校验 pending -> in_progress -> completed' },
        { step: 3, name: '回合 GraphState 同步', desc: '写入 Agent 全局记忆状态机' },
        { step: 4, name: '前端可视化同步', desc: '触发 WS 事件实时更新任务清单' },
      ],
    },
  },
  // ── 内部 MCP 扩展工具（transport=mcp，server=platform.tasks）──
  {
    name: 'platform.tasks.task.create', display_name: '创建评测任务', desc: '创建评测任务并入队（benchmark/testcase/rag/stress），由 Worker 异步执行',
    permission: 'task.create', enabled: true, source: 'builtin',
    transport: 'mcp', category: 'internal_mcp', server_id: 'platform.tasks', risk_level: 'modify',
    timeout_s: 10, supports_streaming: false, execution_mode: 'short', requires_confirmation: true,
    parameters_schema: {
      type: 'object',
      properties: {
        kind: { type: 'string', enum: ['benchmark', 'rag', 'testcase'], description: '任务类别' },
        config: { type: 'object', description: '任务详细规格 TaskSpec' },
        with_stress: { type: 'boolean', description: '评测成功后是否派生压测' },
      },
      required: ['kind', 'config'],
    },
    output_schema: {
      type: 'object',
      properties: {
        summary: { type: 'string' },
        task: {
          type: 'object',
          properties: {
            task_id: { type: 'string' },
            kind: { type: 'string' },
            status: { type: 'string' },
            created_at: { type: 'string' },
          },
        },
      },
    },
    code_details: {
      source_file: 'backend/api/app/harness/execution/registry.py & routers/tasks.py',
      handler_function: '_task_create_handler(arguments, context)',
      code_summary: 'TaskSpec 校验 -> 确认卡鉴权核准 -> 写入 PG 任务表 (status=queued) -> 唤醒 Worker 异步消费',
    },
    pipeline: {
      stages: [
        { step: 1, name: '意图拆解与参数解析', desc: '解析评测类型与被测模型矩阵' },
        { step: 2, name: 'G3 反射与用户确认卡', desc: '必须由用户在前端确认卡点击同意' },
        { step: 3, name: 'Pydantic 规范校验', desc: '强校验样本量、裁判模型与压测参数' },
        { step: 4, name: '写入 PostgreSQL 队列', desc: '创建 tasks 记录并开启串行保护' },
        { step: 5, name: 'Worker 异步领取消费', desc: '后台 Worker 引擎安全抢锁消费' },
      ],
    },
  },
  {
    name: 'platform.tasks.task.status', display_name: '查询任务状态', desc: '查询评测任务当前状态（kind/status/progress/report_id），不等待完成',
    permission: 'task.read', enabled: true, source: 'builtin',
    transport: 'mcp', category: 'internal_mcp', server_id: 'platform.tasks', risk_level: 'read',
    timeout_s: 10, supports_streaming: false, execution_mode: 'short',
    parameters_schema: {
      type: 'object',
      properties: {
        task_id: { type: 'string', description: '待查询的目标任务 ID' },
      },
      required: ['task_id'],
    },
    output_schema: {
      type: 'object',
      properties: {
        summary: { type: 'string' },
        task: {
          type: 'object',
          properties: {
            task_id: { type: 'string' },
            kind: { type: 'string' },
            status: { type: 'string' },
            progress: { type: 'object' },
            report_id: { type: 'string' },
          },
        },
      },
    },
    code_details: {
      source_file: 'backend/api/app/harness/execution/registry.py',
      handler_function: '_task_status_handler(arguments, context)',
      code_summary: '查询 PG 数据库任务记录 -> 提取当前状态机、执行进度、样本数与报告关联 ID -> 立即返回',
    },
    pipeline: {
      stages: [
        { step: 1, name: '任务 ID 格式校验', desc: '校验 task_id 格式合规性' },
        { step: 2, name: '只读数据库检索', desc: '查询 PostgreSQL tasks 表最新记录' },
        { step: 3, name: '进度与指标提取', desc: '读取完成样本数与耗时指标' },
        { step: 4, name: '报告关联状态组装', desc: '已完成则提取 report_id' },
        { step: 5, name: '回填 Agent 上下文', desc: '供 Agent 生成对话解读' },
      ],
    },
  },
  {
    name: 'platform.tasks.task.cancel', display_name: '取消评测任务', desc: '取消非终态评测任务（终态任务幂等返回现状）',
    permission: 'task.cancel', enabled: true, source: 'builtin',
    transport: 'mcp', category: 'internal_mcp', server_id: 'platform.tasks', risk_level: 'modify',
    timeout_s: 10, supports_streaming: false, execution_mode: 'short',
    parameters_schema: {
      type: 'object',
      properties: {
        task_id: { type: 'string', description: '需要取消的目标任务 ID' },
        reason: { type: 'string', description: '取消原因说明' },
      },
      required: ['task_id'],
    },
    output_schema: {
      type: 'object',
      properties: {
        summary: { type: 'string' },
        task: {
          type: 'object',
          properties: {
            task_id: { type: 'string' },
            status: { type: 'string' },
          },
        },
      },
    },
    code_details: {
      source_file: 'backend/api/app/harness/execution/registry.py',
      handler_function: '_task_cancel_handler(arguments, context)',
      code_summary: '校验任务有效性 -> 将非终态任务标记为 cancelled -> 触发 Worker 中断信号 -> 幂等安全返回',
    },
    pipeline: {
      stages: [
        { step: 1, name: '任务鉴权确认', desc: '校验用户对目标任务的操作权限' },
        { step: 2, name: '终态幂等检查', desc: '若已结束直接幂等返回现状' },
        { step: 3, name: '状态流转标记', desc: '置为 cancelled 并记录审计日志' },
        { step: 4, name: 'Worker 熔断响应', desc: 'Worker 收到信号停发并回收计算' },
        { step: 5, name: '状态帧回执', desc: '推送 WS 事件通知工作台任务已中止' },
      ],
    },
  },
]

export const MOCK_CASE_SETS: CaseSet[] = [
  {
    id: 'cs-pay',
    task_id: 't-case-1',
    name: 'PRD-支付',
    status: 'generated',
    generated_count: 40,
    confirmed_count: 0,
    expires_in_h: 70.2,
    checks: [
      { level: 'error', code: 'no_core_positive', message: '无核心正向用例' },
      { level: 'error', code: 'missing_constraint_negative', message: '缺约束反向用例' },
    ],
    created_at: '2026-08-17T09:00:00Z',
  },
  {
    id: 'cs-login',
    task_id: 't-case-0',
    name: 'PRD-登录',
    status: 'confirmed',
    generated_count: 32,
    confirmed_count: 26,
    expires_in_h: 0,
    checks: [],
    created_at: '2026-08-16T14:00:00Z',
  },
  {
    id: 'cs-coupon',
    task_id: 't-case-2',
    name: 'PRD-优惠券',
    status: 'cancelled',
    generated_count: 45,
    confirmed_count: 0,
    expires_in_h: 0,
    checks: [],
    created_at: '2026-08-15T11:20:00Z',
  },
]

export const MOCK_TEST_CASES: TestCase[] = [
  { id: 'c-001', strategy: '正向', priority: 'HX', module: '登录', name: '正确账密登录成功', expected: '进入工作台首页', mapped: true, pending: false, selected: true },
  { id: 'c-002', strategy: '正向', priority: 'HX', module: '支付', name: '余额充足时支付成功', expected: '订单状态变为已支付', mapped: true, pending: false, selected: true },
  { id: 'c-003', strategy: '反向', priority: 'YC', module: '登录', name: '错误密码登录', expected: '提示用户名或密码错误', mapped: false, pending: true, selected: false },
  { id: 'c-004', strategy: '反向', priority: 'YC', module: '支付', name: '余额不足支付', expected: '返回余额不足错误码', mapped: true, pending: false, selected: true },
  { id: 'c-005', strategy: '边界', priority: 'BJ', module: '支付', name: '支付金额为 0.01', expected: '允许最小金额支付', mapped: true, pending: false, selected: true },
  { id: 'c-006', strategy: '边界', priority: 'BJ', module: '支付', name: '支付金额达单笔上限', expected: '按限额规则拦截', mapped: false, pending: true, selected: false },
  { id: 'c-007', strategy: '状态', priority: 'FHX', module: '订单', name: '重复提交支付请求', expected: '幂等返回同一订单', mapped: true, pending: false, selected: true },
  { id: 'c-008', strategy: '场景', priority: 'FHX', module: '支付', name: '支付中断网重试', expected: '恢复后可查询最终状态', mapped: true, pending: false, selected: true },
]

export const MOCK_TASKS: Task[] = [
  {
    id: 'a1f3c2',
    kind: 'benchmark',
    status: 'running',
    config: { kind: 'benchmark', profile_ids: ['p-gpt', 'p-claude'], dataset_id: 'ds-smoke' },
    progress: { percent: 40, done: 40, total: 100, message: '正在调用被测 gpt-test' },
    creator: 'alice',
    created_at: new Date(Date.now() - 120 * 1000).toISOString(),
    report_id: null,
    parent_task_id: null,
    events: [
      { id: 1, task_id: 'a1f3c2', event: 'queued', level: 'info', message: '任务已入队排队中', payload: {}, ts: '2026-08-24T12:00:00Z' },
      { id: 2, task_id: 'a1f3c2', event: 'start', level: 'info', message: '任务开始执行', payload: {}, ts: '2026-08-24T12:00:05Z' },
      { id: 3, task_id: 'a1f3c2', event: 'progress', level: 'info', message: '执行中（40/100）', payload: {}, ts: '2026-08-24T12:01:20Z' },
    ],
  },
  {
    id: 'b2e8d1',
    kind: 'rag',
    status: 'succeeded',
    config: { kind: 'rag', kb_id: 'kb-default', gold_qa_id: 'gq-1', rag_mode: ['hybrid'] },
    progress: { done: 20, total: 20, message: '完成' },
    creator: 'bob',
    created_at: new Date(Date.now() - 3700 * 1000).toISOString(),
    report_id: 'r-rag-1',
    parent_task_id: null,
  },
  {
    id: 'c3d9e7',
    kind: 'stress',
    status: 'queued',
    config: { kind: 'stress', stress: { env: 'prod', qps: 200, duration_s: 300, sla_p99_ms: 1500 } },
    progress: { done: 0, total: 1, message: '等待会签' },
    creator: 'bob',
    created_at: new Date(Date.now() - 3600 * 1000).toISOString(),
    report_id: null,
    parent_task_id: 'b2e8d1',
    need_approval: true,
  },
  {
    id: 'd4c1a9',
    kind: 'testcase',
    status: 'awaiting_case_confirm',
    config: { kind: 'testcase', case_source: { text: 'PRD-支付链路' } },
    progress: { done: 1, total: 2, message: '用例已生成，等待确认' },
    creator: 'alice',
    created_at: new Date(Date.now() - 86400 * 1000).toISOString(),
    report_id: null,
    parent_task_id: null,
  },
  {
    id: 'e5f2b8',
    kind: 'benchmark',
    status: 'succeeded',
    config: { kind: 'benchmark', profile_ids: ['p-gpt', 'p-claude'], dataset_id: 'ds-smoke' },
    progress: { done: 20, total: 20, message: '完成' },
    creator: 'alice',
    created_at: new Date(Date.now() - 90000 * 1000).toISOString(),
    report_id: 'r-bm-1',
    parent_task_id: null,
  },
  {
    id: 'f6a7c4',
    kind: 'benchmark',
    status: 'failed',
    config: { kind: 'benchmark', profile_ids: ['p-gpt'], dataset_id: 'ds-faq' },
    progress: { done: 11, total: 100, message: 'UPSTREAM：被测接口持续 5xx' },
    creator: 'bob',
    created_at: new Date(Date.now() - 180000 * 1000).toISOString(),
    report_id: null,
    parent_task_id: null,
  },
  {
    id: 'g7b3d5',
    kind: 'stress',
    status: 'succeeded',
    config: { kind: 'stress', stress: { env: 'test', qps: 120, duration_s: 120 } },
    progress: { done: 1, total: 1, message: '完成' },
    creator: 'alice',
    created_at: new Date(Date.now() - 89000 * 1000).toISOString(),
    report_id: 'r-st-1',
    parent_task_id: 'e5f2b8',
  },
  {
    id: 'h8c4e6',
    kind: 'rag',
    status: 'cancelled',
    config: { kind: 'rag', kb_id: 'kb-cs', gold_qa_id: 'gq-2' },
    progress: { done: 7, total: 20, message: '已被创建者取消' },
    creator: 'alice',
    created_at: new Date(Date.now() - 260000 * 1000).toISOString(),
    report_id: null,
    parent_task_id: null,
  },
]

export const MOCK_REPORTS: Record<string, Report> = {
  'r-bm-1': {
    id: 'r-bm-1',
    task_id: 'e5f2b8',
    kind: 'benchmark',
    created_at: '2026-08-15T06:02:00Z',
    title: 'Benchmark 报告 · smoke-20 v3 · 主指标 contain',
    snapshot: {
      dataset: 'smoke-20',
      dataset_version: 3,
      metric: 'contain',
      sample_size: 20,
      concurrency: 4,
      timeout_s: 60,
      seed: 20260815,
    },
    baseline: {
      task_id: 'e0base88',
      delta: -0.07,
    },
    scores: [
      {
        profile: 'p-gpt',
        profile_name: 'gpt-test',
        contain: 0.86,
        fail_rate: 0.02,
        latency: '820ms',
        judge: 4.2,
      },
      {
        profile: 'p-claude',
        profile_name: 'claude-x',
        contain: 0.79,
        fail_rate: 0.05,
        latency: '1.1s',
        judge: 3.9,
      },
    ],
    failed_items: [
      {
        row: 7,
        question: '如何修改默认结算账户？',
        error: 'UPSTREAM',
        raw: 'HTTP 502 Bad Gateway from upstream endpoint',
      },
      {
        row: 13,
        question: '退款多久到账？',
        error: 'TIMEOUT',
        raw: 'Request timed out after 60s without response',
      },
    ],
  },
  'r-rag-1': {
    id: 'r-rag-1',
    task_id: 'b2e8d1',
    kind: 'rag',
    created_at: '2026-08-17T01:12:00Z',
    title: 'RAG 报告 · default 库 · qa-v1 v2 · K=5',
    k: 5,
    modes: ['naive', 'local', 'global', 'hybrid'],
    rag_scores: {
      naive: { hit: 0.62, mrr: 0.55, recall: 0.7, contain: 0.74 },
      local: { hit: 0.71, mrr: 0.66, recall: 0.78, contain: 0.77 },
      global: { hit: 0.68, mrr: 0.61, recall: 0.75, contain: 0.72 },
      hybrid: { hit: 0.8, mrr: 0.74, recall: 0.85, contain: 0.83 },
    },
    degraded: {
      mode: 'hybrid',
      pp: -6,
    },
    hit_note: '20 条样本中 3 条无 expected_doc_ids，未计入 Hit Rate 分母',
  },
  'r-st-1': {
    id: 'r-st-1',
    task_id: 'g7b3d5',
    kind: 'stress',
    created_at: '2026-08-15T06:40:00Z',
    title: '压测报告 · 继承自任务 e5f2b8 · env=test',
    // 「先评后压」回溯字段：用于报告页展示父质量报告横幅
    parent_task_id: 'e5f2b8',
    parent_report_id: 'r-bm-1',
    env: 'test',
    qps_peak: 118,
    p99: '1.2s',
    error_rate: '0.4%',
    ttft: '320ms',
    tpot: '45ms',
    tokens_per_s: '1.8k',
    est_cost: '$0.42',
    sla_p99_ms: 1500,
    sla_met: true,
    knee: '第 3 分钟首次 P99 > SLA（或错误率 ≥1%）',
    series: [
      { ts: '00:00', qps: 20, rt_ms: 280, error_rate: 0 },
      { ts: '00:30', qps: 55, rt_ms: 320, error_rate: 0 },
      { ts: '01:00', qps: 90, rt_ms: 450, error_rate: 0.001 },
      { ts: '01:30', qps: 118, rt_ms: 780, error_rate: 0.002 },
      { ts: '02:00', qps: 115, rt_ms: 1100, error_rate: 0.004 },
    ],
  },
}

/**
 * 拼装 Mock 模式下的报告 Markdown 文本，模拟服务端 GET /api/reports/{id}?fmt=md 的返回。
 * 仅覆盖标题、关键 KPI 与指标表，供「导出 Markdown」按钮在演示模式下生成下载文件。
 */
export function buildMockReportMarkdown(r: Report): string {
  // 指标值统一保留两位小数，缺失时输出占位符
  const fmtNum = (v?: number) => (v === undefined ? '—' : v.toFixed(2))
  const lines: string[] = [
    `# ${r.title}`,
    '',
    `- 报告 ID: ${r.id}`,
    `- 关联任务: ${r.task_id}`,
    `- 生成时间: ${r.created_at}`,
    '',
  ]

  if (r.kind === 'benchmark' && r.scores?.length) {
    lines.push('## 核心指标', '', '| 协议档 | contain | exact | ROUGE-L | 失败率 | 平均延迟 |', '| --- | --- | --- | --- | --- | --- |')
    for (const s of r.scores) {
      lines.push(
        `| ${s.profile_name || s.profile} | ${fmtNum(s.contain)} | ${fmtNum(s.exact)} | ${fmtNum(s.rouge_l)} | ${((s.fail_rate ?? 0) * 100).toFixed(1)}% | ${s.latency ?? '—'} |`,
      )
    }
    lines.push('')
  }

  if (r.kind === 'rag' && r.rag_scores) {
    lines.push(`## RAG 检索指标 (K=${r.k ?? 5})`, '', '| 检索模式 | Hit Rate | MRR | Recall | Contain |', '| --- | --- | --- | --- | --- |')
    for (const m of r.modes || ['naive', 'local', 'global', 'hybrid']) {
      const sc = r.rag_scores[m]
      lines.push(`| ${m} | ${fmtNum(sc?.hit)} | ${fmtNum(sc?.mrr)} | ${fmtNum(sc?.recall)} | ${fmtNum(sc?.contain)} |`)
    }
    lines.push('')
  }

  if (r.kind === 'stress') {
    lines.push(
      '## 压测 KPI',
      '',
      `- 峰值 QPS: ${r.qps_peak ?? '—'}`,
      `- P99 延迟: ${r.p99 ?? '—'}`,
      `- 请求错误率: ${r.error_rate ?? '—'}`,
      `- TTFT 首字延迟: ${r.ttft ?? '—'}`,
      `- 估算费用: ${r.est_cost ?? '—'}`,
      '',
    )
  }

  return lines.join('\n')
}
