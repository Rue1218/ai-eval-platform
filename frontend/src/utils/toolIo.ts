/** ToolCard 输入/输出展示层：把后端契约字段映射成约定的展示名，不改 schema。 */

export type IoFieldKind = 'text' | 'mono' | 'code'

/** 卡片上的一行入参或出参。 */
export interface ToolIoField {
  name: string
  hint: string
  value: string
  required?: boolean
  kind?: IoFieldKind
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function asString(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/** 按候选键取第一个非空值（兼容 path/file_path、old/old_string 等）。 */
export function pickArg(args: Record<string, unknown>, ...keys: string[]): unknown {
  for (const key of keys) {
    const value = args[key]
    if (value !== undefined && value !== null && value !== '') return value
  }
  return undefined
}

/** 沙箱相对路径统一展示为 workspace/XXX。 */
export function formatWorkspacePath(raw: unknown): string {
  const cleaned = asString(raw).replace(/\\/g, '/').replace(/^\.?\//, '')
  if (!cleaned) return ''
  if (cleaned.startsWith('workspace/')) return cleaned
  return `workspace/${cleaned}`
}

function field(
  name: string,
  hint: string,
  value: unknown,
  options: { required?: boolean; kind?: IoFieldKind; empty?: boolean } = {},
): ToolIoField | null {
  const text = asString(value)
  if (!text && !options.empty) return null
  return {
    name,
    hint,
    value: text,
    required: options.required,
    kind: options.kind || (name.endsWith('_path') || name === 'path' || name === 'taskId' ? 'mono' : 'text'),
  }
}

/** 读取工具入参：file_path / offset / limit。 */
function readInputFields(args: Record<string, unknown>): ToolIoField[] {
  const fields: ToolIoField[] = []
  const path = field('file_path', '文件路径', formatWorkspacePath(pickArg(args, 'file_path', 'path')), {
    required: true,
    kind: 'mono',
  })
  if (path) fields.push(path)
  const offset = pickArg(args, 'offset', 'next_offset')
  if (offset != null && offset !== '') {
    fields.push({
      name: 'offset',
      hint: '行号偏移，从第几行开始读（0-based）',
      value: String(offset),
      kind: 'mono',
    })
  }
  if (args.limit != null && args.limit !== '') {
    fields.push({
      name: 'limit',
      hint: '读取行数上限',
      value: String(args.limit),
      kind: 'mono',
    })
  }
  return fields
}

/** 写入工具入参：file_path / content，以及可选审查字段。 */
function writeInputFields(args: Record<string, unknown>): ToolIoField[] {
  const fields: ToolIoField[] = []
  const path = field('file_path', '目标文件路径', formatWorkspacePath(pickArg(args, 'file_path', 'path')), {
    required: true,
    kind: 'mono',
  })
  if (path) fields.push(path)
  const content = field('content', '完整文本内容', pickArg(args, 'content'), { required: true, kind: 'code' })
  if (content) fields.push(content)
  const description = field('description', '简短操作描述', pickArg(args, 'description'))
  if (description) fields.push(description)
  const review = field('reviewComment', '写操作动机', pickArg(args, 'reviewComment'))
  if (review) fields.push(review)
  return fields
}

/** 编辑工具入参：file_path / old_string / new_string。 */
function editInputFields(args: Record<string, unknown>): ToolIoField[] {
  const fields: ToolIoField[] = []
  const path = field('file_path', '要编辑的文件路径', formatWorkspacePath(pickArg(args, 'file_path', 'path')), {
    required: true,
    kind: 'mono',
  })
  if (path) fields.push(path)
  const oldText = field('old_string', '要查找的原始文本', pickArg(args, 'old_string', 'old'), {
    required: true,
    kind: 'code',
  })
  if (oldText) fields.push(oldText)
  const newText = field('new_string', '替换后的新文本', pickArg(args, 'new_string', 'new'), {
    required: true,
    kind: 'code',
  })
  if (newText) fields.push(newText)
  if (args.replace_all === true) {
    fields.push({ name: 'replace_all', hint: '替换全部匹配', value: 'true', kind: 'mono' })
  }
  return fields
}

/** 沙箱命令入参：command / timeout。 */
function bashInputFields(args: Record<string, unknown>): ToolIoField[] {
  const fields: ToolIoField[] = []
  const command = field('command', '要执行的 shell 命令', pickArg(args, 'command'), {
    required: true,
    kind: 'code',
  })
  if (command) fields.push(command)
  const description = field('description', '命令简短描述', pickArg(args, 'description'))
  if (description) fields.push(description)
  const timeout = pickArg(args, 'timeout', 'timeout_s', 'timeout_ms')
  if (timeout != null && timeout !== '') {
    fields.push({
      name: 'timeout',
      hint: '超时时间',
      value: String(timeout),
      kind: 'mono',
    })
  }
  return fields
}

/** 缺 description 时按后端别名规则从 prompt 截短补齐，保证加载态也能看到必填字段。 */
export function resolveTaskDescription(args: Record<string, unknown>): string {
  const description = asString(pickArg(args, 'description')).trim()
  if (description) return description
  const prompt = asString(pickArg(args, 'prompt', 'goal')).trim()
  if (!prompt) return ''
  return prompt.slice(0, 24) + (prompt.length > 24 ? '…' : '')
}

/** 会话内拆解入参：description / prompt，以及只展示不执行的可选字段。 */
function taskInputFields(args: Record<string, unknown>): ToolIoField[] {
  const fields: ToolIoField[] = []
  const description = field('description', '任务简短概括', resolveTaskDescription(args), { required: true })
  if (description) fields.push(description)
  const prompt = field('prompt', '完整指令', pickArg(args, 'prompt', 'goal'), { required: true, kind: 'code' })
  if (prompt) fields.push(prompt)
  for (const [name, hint] of [
    ['subagent_type', '子代理类型（本回合不执行）'],
    ['model', '指定模型（本回合不执行）'],
    ['resume', '恢复标识（本回合不执行）'],
    ['max_turns', '最大轮次（本回合不执行）'],
  ] as const) {
    const item = field(name, hint, pickArg(args, name), { kind: 'mono' })
    if (item) fields.push(item)
  }
  if (Array.isArray(args.tools) && args.tools.length) {
    fields.push({
      name: 'tools',
      hint: '允许的工具（本回合不执行）',
      value: args.tools.map((item) => String(item)).join(' / '),
      kind: 'mono',
    })
  }
  return fields
}

/** 队列任务入参：taskId / status 为主，其余保留契约键。 */
function queueTaskInputFields(args: Record<string, unknown>): ToolIoField[] {
  const fields: ToolIoField[] = []
  const taskId = field('taskId', '任务标识', pickArg(args, 'taskId', 'task_id'), { kind: 'mono' })
  if (taskId) fields.push(taskId)
  const status = field('status', '目标状态', pickArg(args, 'status'), { kind: 'mono' })
  if (status) fields.push(status)
  const kind = field('kind', '任务类型', pickArg(args, 'kind'), { kind: 'mono' })
  if (kind) fields.push(kind)
  const dataset = field('dataset_id', '数据集', pickArg(args, 'dataset_id'), { kind: 'mono' })
  if (dataset) fields.push(dataset)
  if (Array.isArray(args.profile_ids) && args.profile_ids.length) {
    fields.push({ name: 'profile_ids', hint: '协议档', value: `${args.profile_ids.length} 个`, kind: 'mono' })
  }
  const kb = field('kb_id', '知识库', pickArg(args, 'kb_id'), { kind: 'mono' })
  if (kb) fields.push(kb)
  const gold = field('gold_qa_id', '黄金 QA', pickArg(args, 'gold_qa_id'), { kind: 'mono' })
  if (gold) fields.push(gold)
  if (Array.isArray(args.rag_mode) && args.rag_mode.length) {
    fields.push({
      name: 'rag_mode',
      hint: '检索模式',
      value: args.rag_mode.map((item) => String(item)).join(' / '),
    })
  }
  if (args.with_stress === true) {
    fields.push({ name: 'with_stress', hint: '先评后压', value: 'true', kind: 'mono' })
  }
  const parent = field('parent_task_id', '父任务', pickArg(args, 'parent_task_id'), { kind: 'mono' })
  if (parent) fields.push(parent)
  return fields
}

function genericInputFields(args: Record<string, unknown>): ToolIoField[] {
  return Object.entries(args)
    .filter(([, value]) => value !== undefined)
    .slice(0, 8)
    .map(([key, value]) => ({
      name: key,
      hint: '',
      value: typeof value === 'string' ? value : asString(value),
      kind: 'mono' as const,
    }))
}

/** 按工具名投影 ToolCall 入参。 */
export function buildToolInputFields(tool: string, args: Record<string, unknown>): ToolIoField[] {
  if (tool === 'read') return readInputFields(args)
  if (tool === 'write') return writeInputFields(args)
  if (tool === 'edit') return editInputFields(args)
  if (tool === 'bash') return bashInputFields(args)
  if (tool === 'TaskCreate') {
    const fields: ToolIoField[] = []
    const subject = field('subject', '任务标题', pickArg(args, 'subject', 'title', 'goal'), { required: true })
    if (subject) fields.push(subject)
    const description = field('description', '任务说明', pickArg(args, 'description', 'prompt'))
    if (description) fields.push(description)
    const active = field('activeForm', '进行中文案', pickArg(args, 'activeForm'))
    if (active) fields.push(active)
    return fields
  }
  if (tool === 'TaskGet' || tool === 'TaskUpdate') {
    const fields: ToolIoField[] = []
    const taskId = field('taskId', '会话任务标识', pickArg(args, 'taskId', 'task_id', 'id'), {
      required: true,
      kind: 'mono',
    })
    if (taskId) fields.push(taskId)
    if (tool === 'TaskUpdate') {
      const status = field('status', '任务状态', pickArg(args, 'status'), { required: true, kind: 'mono' })
      if (status) fields.push(status)
      const subject = field('subject', '任务标题', pickArg(args, 'subject'))
      if (subject) fields.push(subject)
      const description = field('description', '任务说明', pickArg(args, 'description'))
      if (description) fields.push(description)
      const owner = field('owner', '负责人', pickArg(args, 'owner'), { kind: 'mono' })
      if (owner) fields.push(owner)
    }
    return fields
  }
  if (tool === 'TaskList') return []
  if (tool === 'ask_user_question') {
    const raw = args.questions
    if (!Array.isArray(raw) || !raw.length) return []
    return raw.slice(0, 8).map((item, index) => {
      const rec = item && typeof item === 'object' ? (item as Record<string, unknown>) : {}
      return {
        name: `questions[${index}].question`,
        hint: String(rec.id || `q${index + 1}`),
        value: String(rec.question || ''),
        required: rec.required !== false,
      }
    })
  }
  if (tool === 'task') return taskInputFields(args)
  if (tool === 'task.create' || tool === 'task.status' || tool === 'task.cancel' || tool === 'task.get') {
    return queueTaskInputFields(args)
  }
  if (tool === 'web_search') {
    const fields: ToolIoField[] = []
    const query = field('query', '搜索查询', pickArg(args, 'query'), { required: true })
    if (query) fields.push(query)
    const maxResults = field('max_results', '结果上限', pickArg(args, 'max_results', 'limit'), { kind: 'mono' })
    if (maxResults) fields.push(maxResults)
    for (const [name, hint] of [
      ['topic', '主题'],
      ['time_range', '时间筛选'],
      ['engine', '检索引擎'],
      ['search_context_size', '上下文长度'],
    ] as const) {
      const item = field(name, hint, pickArg(args, name), { kind: 'mono' })
      if (item) fields.push(item)
    }
    return fields
  }
  if (tool === 'web_fetch') {
    const fields: ToolIoField[] = []
    const url = field('url', '目标 URL', pickArg(args, 'url'), { required: true, kind: 'mono' })
    if (url) fields.push(url)
    const format = field('format', '正文格式', pickArg(args, 'format'), { kind: 'mono' })
    if (format) fields.push(format)
    const tokens = field('max_content_tokens', '内容 Token 上限', pickArg(args, 'max_content_tokens'), { kind: 'mono' })
    if (tokens) fields.push(tokens)
    const engine = field('engine', '抓取引擎', pickArg(args, 'engine'), { kind: 'mono' })
    if (engine) fields.push(engine)
    return fields
  }
  return genericInputFields(args)
}

/** 输出区顶部的正文字段名（content / result）。 */
export function outputBodyCaption(tool: string): { name: string; hint: string } | null {
  if (tool === 'read') return { name: 'content', hint: '读取的文件内容' }
  if (tool === 'write') return { name: 'content', hint: '写入的文件内容' }
  if (tool === 'bash') return { name: 'stdout', hint: '标准输出' }
  if (tool === 'edit') return { name: 'content', hint: '编辑操作确认' }
  if (tool === 'task' || tool === 'TaskCreate' || tool === 'TaskUpdate') {
    return { name: 'result', hint: '任务执行结果' }
  }
  if (tool === 'TaskGet' || tool === 'TaskList') return { name: 'result', hint: '任务快照' }
  if (tool === 'ask_user_question') return { name: 'answers', hint: '用户答案' }
  if (tool === 'web_fetch') return { name: 'content', hint: '抓取正文' }
  if (tool === 'web_search') return { name: 'result', hint: '检索结果' }
  return null
}

function nest(result: Record<string, unknown> | null, key: string): Record<string, unknown> | null {
  return asRecord(result?.[key])
}

/** 输出区标量字段：path / status / error / success / taskId 等。 */
export function buildToolOutputFields(
  tool: string,
  result: Record<string, unknown> | null,
  args: Record<string, unknown>,
  status: string,
): ToolIoField[] {
  const fields: ToolIoField[] = []
  const fail = status === 'fail' || status === 'rejected'
  const errorText = asString(result?.error || result?.message)

  if (tool === 'write') {
    const write = nest(result, 'write')
    fields.push({
      name: 'status',
      hint: '写入结果',
      value: asString(result?.status || (fail ? 'failure' : 'success')),
      kind: 'mono',
    })
    const path = formatWorkspacePath(result?.path || write?.path || pickArg(args, 'file_path', 'path'))
    if (path) fields.push({ name: 'path', hint: '写入路径', value: path, kind: 'mono' })
  }
  if (tool === 'read') {
    const read = nest(result, 'read')
    fields.push({
      name: 'status',
      hint: '读取结果',
      value: asString(result?.status || (fail ? 'failure' : 'success')),
      kind: 'mono',
    })
    const path = formatWorkspacePath(read?.path || pickArg(args, 'file_path', 'path'))
    if (path) fields.push({ name: 'file_path', hint: '读取路径', value: path, kind: 'mono' })
  }
  if (tool === 'bash') {
    const bash = nest(result, 'bash')
    const exitCode = result?.exit_code ?? bash?.exit_code
    fields.push({
      name: 'exit_code',
      hint: '退出码',
      value: fail ? 'error' : exitCode == null ? '0' : String(exitCode),
      kind: 'mono',
    })
    if (result?.stderr) fields.push({ name: 'stderr', hint: '标准错误', value: asString(result.stderr) })
    if (result?.duration_ms != null) {
      fields.push({ name: 'duration_ms', hint: '耗时（毫秒）', value: String(result.duration_ms), kind: 'mono' })
    }
    if (fail && errorText) fields.push({ name: 'error', hint: '失败原因', value: errorText })
  }
  if (tool === 'edit') {
    const edit = nest(result, 'edit')
    fields.push({
      name: 'status',
      hint: '编辑结果',
      value: asString(result?.status || (fail ? 'failure' : 'success')),
      kind: 'mono',
    })
    const modified = result?.modified_lines ?? edit?.replacements
    if (modified != null) {
      fields.push({ name: 'modified_lines', hint: '修改行数', value: String(modified), kind: 'mono' })
    }
    if (result?.diff) fields.push({ name: 'diff', hint: '结构化差异', value: asString(result.diff), kind: 'code' })
    const path = formatWorkspacePath(edit?.path || pickArg(args, 'file_path', 'path'))
    if (path) fields.push({ name: 'path', hint: '目标文件', value: path, kind: 'mono' })
    if (fail && errorText) fields.push({ name: 'error', hint: '查找失败原因', value: errorText })
  }
  if (tool === 'task') {
    const task = nest(result, 'task')
    fields.push({
      name: 'status',
      hint: '任务状态',
      value: asString(result?.status || task?.status || (fail ? 'error' : 'ok')),
      kind: 'mono',
    })
    const agentId = asString(result?.agentId || result?.agent_id || task?.agentId || task?.agent_id)
    if (agentId) fields.push({ name: 'agentId', hint: '子任务委派标识', value: agentId, kind: 'mono' })
    const duration = result?.totalDurationMs ?? result?.total_duration_ms ?? task?.totalDurationMs
    if (duration != null && duration !== '') {
      fields.push({ name: 'totalDurationMs', hint: '子任务耗时（毫秒）', value: String(duration), kind: 'mono' })
    }
  }
  if (tool === 'TaskCreate' || tool === 'TaskGet' || tool === 'TaskUpdate') {
    const task = nest(result, 'task')
    const taskId = asString(task?.id || result?.id)
    if (taskId) fields.push({ name: 'task.id', hint: '会话任务标识', value: taskId, kind: 'mono' })
    const boardStatus = asString(task?.status)
    if (boardStatus) fields.push({ name: 'status', hint: '看板状态', value: boardStatus, kind: 'mono' })
    const subject = asString(task?.subject)
    if (subject) fields.push({ name: 'subject', hint: '任务标题', value: subject })
    const owner = asString(task?.owner)
    if (owner) fields.push({ name: 'owner', hint: '负责人', value: owner, kind: 'mono' })
  }
  if (tool === 'TaskList') {
    const tasks = Array.isArray(result?.tasks) ? result.tasks : []
    fields.push({ name: 'count', hint: '未删除项数', value: String(tasks.length), kind: 'mono' })
  }
  if (tool === 'ask_user_question') {
    const answers = Array.isArray(result?.answers) ? result.answers : []
    answers.slice(0, 8).forEach((item, index) => {
      const rec = asRecord(item)
      if (!rec) return
      const selected = Array.isArray(rec.selected) ? rec.selected.join(', ') : asString(rec.custom)
      fields.push({
        name: `answers[${index}]`,
        hint: asString(rec.id) || `q${index + 1}`,
        value: selected || asString(rec.custom),
      })
    })
  }
  if (tool === 'task.create' || tool === 'task.status' || tool === 'task.cancel' || tool === 'task.get') {
    fields.push({
      name: 'success',
      hint: '是否成功',
      value: fail ? 'false' : 'true',
      kind: 'mono',
    })
    const taskId = asString(result?.task_id || result?.taskId || pickArg(args, 'task_id', 'taskId'))
    if (taskId) fields.push({ name: 'taskId', hint: '任务标识', value: taskId, kind: 'mono' })
    const queueStatus = asString(result?.status)
    if (queueStatus) fields.push({ name: 'status', hint: '队列状态', value: queueStatus, kind: 'mono' })
  }
  if (fail && tool !== 'bash' && tool !== 'edit' && errorText) {
    fields.push({ name: 'error', hint: '失败原因', value: errorText })
  }
  return fields
}
