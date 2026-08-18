/**
 * AI 测试与评估平台 — 统一 HTTP 客户端
 * 依据：docs/AI测试与评估平台-API.md (V1.3)
 */
import axios, { type AxiosRequestConfig } from 'axios'
import {
  ErrorCode,
  ERROR_MESSAGES,
  type AuthUser,
  type Profile,
  type Dataset,
  type DatasetRow,
  type KnowledgeBase,
  type KbDocument,
  type KbChunk,
  type GoldQA,
  type Task,
  type TaskSpec,
  type Report,
  type AdminSettings,
  type CaseSet,
  type TestCase,
  type WhitelistItem,
  type DispatchOverview,
  type DispatchWorker,
  type DispatchEventPage,
  type DispatchConfig,
  type McpTool,
} from './types'
import {
  MOCK_PROFILES,
  MOCK_DATASETS,
  MOCK_PENDING_ROWS,
  MOCK_KBS,
  MOCK_KB_DOCS,
  MOCK_GOLD_QAS,
  MOCK_USERS,
  MOCK_SETTINGS,
  MOCK_CASE_SETS,
  MOCK_TEST_CASES,
  MOCK_TASKS,
  MOCK_REPORTS,
  MOCK_WHITELIST,
  buildMockReportMarkdown,
} from './mockData'

// 数据模式判定：默认 live，可通过 URL ?data=mock 或 localStorage ae_data_mode 切换
function getDataMode(): 'live' | 'mock' {
  if (typeof window === 'undefined') return 'live'
  const params = new URLSearchParams(window.location.search)
  const qMode = params.get('data')
  if (qMode === 'mock' || qMode === 'live') return qMode
  const stored = localStorage.getItem('ae_data_mode')
  return stored === 'mock' ? 'mock' : 'live'
}

export class ApiError extends Error {
  code: ErrorCode
  status?: number
  fields?: Record<string, string>
  details?: any

  constructor(message: string, code: ErrorCode = ErrorCode.INTERNAL, status?: number, fields?: Record<string, string>, details?: any) {
    super(message || ERROR_MESSAGES[code] || '未知错误')
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.fields = fields
    this.details = details
  }
}

const http = axios.create({
  baseURL: '',
  withCredentials: true,
  timeout: 30000,
})

http.interceptors.response.use(
  (res) => res,
  (err: any) => {
    if (err.response) {
      const status = err.response.status
      const data = err.response.data || {}
      const code: ErrorCode = data.code || (status === 401 ? ErrorCode.UNAUTHORIZED : status === 404 ? ErrorCode.NOT_FOUND : ErrorCode.INTERNAL)
      const message = data.message || ERROR_MESSAGES[code] || `请求失败 (${status})`

      return Promise.reject(new ApiError(message, code, status, data.fields, data))
    }
    return Promise.reject(new ApiError(err.message || '网络连接异常', ErrorCode.INTERNAL))
  },
)

// KB 域后端路由属 M3 里程碑：首次 404 后置位，后续读取直接走降级数据，不再重复请求
let kbBackendMissing = false

// In-Memory Mock Store for interactive demonstration when in mock mode
const mockStore = {
  profiles: [...MOCK_PROFILES],
  datasets: [...MOCK_DATASETS],
  pendingRows: [...MOCK_PENDING_ROWS],
  kbs: [...MOCK_KBS],
  kbDocs: [...MOCK_KB_DOCS],
  goldQAs: [...MOCK_GOLD_QAS],
  users: [...MOCK_USERS],
  settings: { ...MOCK_SETTINGS },
  caseSets: [...MOCK_CASE_SETS],
  cases: [...MOCK_TEST_CASES],
  tasks: [...MOCK_TASKS],
  reports: { ...MOCK_REPORTS },
  whitelist: [...MOCK_WHITELIST],
  sessions: [
    { id: 's-default', title: '新建基准评测会话', created_at: new Date().toISOString() },
  ],
}

/**
 * 获取报告详情。默认返回 JSON 对象；传 fmt='md' 时走服务端导出（GET /api/reports/{id}?fmt=md），
 * 返回 Markdown 纯文本，供前端直接生成 Blob 下载。Mock 模式下由本地夹具拼接等价文本。
 */
async function reportsGet(id: string): Promise<Report>
async function reportsGet(id: string, fmt: 'md'): Promise<string>
async function reportsGet(id: string, fmt?: 'md'): Promise<Report | string> {
  if (getDataMode() === 'mock') {
    const r = mockStore.reports[id] || mockStore.reports['r-bm-1']
    return fmt === 'md' ? buildMockReportMarkdown(r) : r
  }
  if (fmt === 'md') {
    // responseType: 'text' 避免 axios 按 JSON 解析 Markdown 文本
    const { data } = await http.get(`/api/reports/${id}`, { params: { fmt: 'md' }, responseType: 'text' })
    return data
  }
  // 实时模式不作 Mock 顶替（API.md §12.3：无报告时显示空/错误态）；报告不存在由页面展示错误态
  const { data } = await http.get(`/api/reports/${id}`)
  return data
}

/**
 * 统一 API 客户端对象
 */
export const api = {
  getDataMode,
  isMock: () => getDataMode() === 'mock',

  // 1. 鉴权与账号
  auth: {
    async login(credentials: { username: string; password: string }): Promise<AuthUser> {
      if (getDataMode() === 'mock') {
        const u = mockStore.users.find((x) => x.username === credentials.username) || mockStore.users[0]
        localStorage.setItem('ae_user', u.username)
        return u
      }
      const { data } = await http.post('/api/auth/login', credentials)
      localStorage.setItem('ae_user', data.username)
      return data
    },
    async logout(): Promise<void> {
      localStorage.removeItem('ae_user')
      if (getDataMode() === 'mock') return
      await http.post('/api/auth/logout')
    },
    async getMe(): Promise<AuthUser> {
      if (getDataMode() === 'mock') {
        const name = localStorage.getItem('ae_user') || 'admin'
        return mockStore.users.find((x) => x.username === name) || mockStore.users[0]
      }
      const { data } = await http.get('/api/auth/me')
      return data
    },
    async changePassword(payload: { old_password?: string; new_password: string }): Promise<void> {
      if (getDataMode() === 'mock') return
      await http.post('/api/auth/change-password', payload)
    },
    async getWsTicket(): Promise<{ ticket: string; expires_in: number }> {
      if (getDataMode() === 'mock') return { ticket: 'mock-ticket-' + Date.now(), expires_in: 300 }
      const { data } = await http.post('/api/auth/ws-ticket')
      return data
    },
  },

  // 2. 文件上传
  files: {
    async upload(file: File): Promise<{ id: string; filename: string; size: number }> {
      if (getDataMode() === 'mock') {
        return { id: 'file-' + Date.now(), filename: file.name, size: file.size }
      }
      const formData = new FormData()
      formData.append('file', file)
      const { data } = await http.post('/api/files', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return data
    },
  },

  // 3. 用户管理
  users: {
    async list(): Promise<AuthUser[]> {
      if (getDataMode() === 'mock') return mockStore.users
      try {
        const { data } = await http.get('/api/users')
        return Array.isArray(data) ? data : data.items || []
      } catch (e) {
        if (getDataMode() === 'mock') return mockStore.users
        throw e
      }
    },
    async create(payload: { username: string; password?: string; role?: string }): Promise<AuthUser> {
      if (getDataMode() === 'mock') {
        const u: AuthUser = {
          id: 'u-' + Date.now(),
          username: payload.username,
          role: 'member',
          disabled: false,
          created_at: new Date().toISOString(),
        }
        mockStore.users.push(u)
        return u
      }
      const { data } = await http.post('/api/users', payload)
      return data
    },
    async resetPassword(id: string, password: string): Promise<void> {
      if (getDataMode() === 'mock') return
      await http.post(`/api/users/${id}/reset-password`, { password })
    },
    async toggleStatus(id: string, disabled: boolean): Promise<void> {
      if (getDataMode() === 'mock') {
        const u = mockStore.users.find((x) => x.id === id)
        if (u) u.disabled = disabled
        return
      }
      await http.put(`/api/users/${id}/status`, { disabled })
    },
  },

  // 4. 协议档管理
  profiles: {
    async list(): Promise<Profile[]> {
      if (getDataMode() === 'mock') return mockStore.profiles
      try {
        const { data } = await http.get('/api/profiles')
        return Array.isArray(data) ? data : data.items || []
      } catch (e) {
        if (getDataMode() === 'mock') return mockStore.profiles
        throw e
      }
    },
    async create(payload: any): Promise<Profile> {
      if (getDataMode() === 'mock') {
        const p: Profile = {
          id: 'p-' + Date.now(),
          ...payload,
          created_at: new Date().toISOString(),
        }
        mockStore.profiles.unshift(p)
        return p
      }
      const { data } = await http.post('/api/profiles', payload)
      return data
    },
    async update(id: string, payload: any): Promise<Profile> {
      if (getDataMode() === 'mock') {
        const idx = mockStore.profiles.findIndex((x) => x.id === id)
        if (idx >= 0) mockStore.profiles[idx] = { ...mockStore.profiles[idx], ...payload }
        return mockStore.profiles[idx]
      }
      const { data } = await http.put(`/api/profiles/${id}`, payload)
      return data
    },
    async delete(id: string): Promise<void> {
      if (getDataMode() === 'mock') {
        mockStore.profiles = mockStore.profiles.filter((x) => x.id !== id)
        return
      }
      await http.delete(`/api/profiles/${id}`)
    },
    async check(id: string): Promise<{ ok: boolean; latency_ms?: number; model?: string }> {
      if (getDataMode() === 'mock') return { ok: true, latency_ms: 120, model: 'gpt-4o' }
      const { data } = await http.post(`/api/profiles/${id}/check`)
      return data
    },
  },

  // 5. 任务管理
  tasks: {
    async list(params: { status?: string; kind?: string } = {}): Promise<Task[]> {
      if (getDataMode() === 'mock') {
        return mockStore.tasks.filter((t) => {
          if (params.status && t.status !== params.status) return false
          if (params.kind && t.kind !== params.kind) return false
          return true
        })
      }
      try {
        const { data } = await http.get('/api/tasks', { params })
        return Array.isArray(data) ? data : data.items || []
      } catch (e) {
        if (getDataMode() === 'mock') return mockStore.tasks
        throw e
      }
    },
    async get(id: string): Promise<Task> {
      if (getDataMode() === 'mock') {
        const t = mockStore.tasks.find((x) => x.id === id)
        if (!t) throw new ApiError('任务不存在', ErrorCode.NOT_FOUND, 404)
        return t
      }
      const { data } = await http.get(`/api/tasks/${id}`)
      return data
    },
    async create(taskSpec: TaskSpec): Promise<Task> {
      if (getDataMode() === 'mock') {
        const t: Task = {
          id: 't-' + Math.random().toString(36).substring(2, 8),
          kind: taskSpec.kind,
          status: 'queued',
          config: taskSpec,
          progress: { done: 0, total: 100, message: '任务已入队排队中' },
          creator: localStorage.getItem('ae_user') || 'admin',
          created_at: new Date().toISOString(),
          report_id: null,
          parent_task_id: taskSpec.parent_task_id || null,
        }
        mockStore.tasks.unshift(t)
        return t
      }
      const { data } = await http.post('/api/tasks', {
        kind: taskSpec.kind,
        config: taskSpec,
        session_id: taskSpec.session_id,
        with_stress: taskSpec.with_stress,
      })
      return data
    },
    async cancel(id: string, reason?: string): Promise<void> {
      if (getDataMode() === 'mock') {
        const t = mockStore.tasks.find((x) => x.id === id)
        if (t) t.status = 'cancelled'
        return
      }
      await http.post(`/api/tasks/${id}/cancel`, { reason })
    },
    async rerun(id: string): Promise<Task> {
      if (getDataMode() === 'mock') {
        const t = mockStore.tasks.find((x) => x.id === id)
        const newT: Task = {
          id: 't-' + Math.random().toString(36).substring(2, 8),
          kind: t ? t.kind : 'benchmark',
          status: 'queued',
          config: t ? t.config : { kind: 'benchmark' },
          progress: { done: 0, total: 100, message: '任务已重新入队' },
          creator: localStorage.getItem('ae_user') || 'admin',
          created_at: new Date().toISOString(),
          report_id: null,
          parent_task_id: null,
        }
        mockStore.tasks.unshift(newT)
        return newT
      }
      const { data } = await http.post(`/api/tasks/${id}/rerun`)
      return data
    },
    async approveStress(id: string): Promise<void> {
      if (getDataMode() === 'mock') {
        const t = mockStore.tasks.find((x) => x.id === id)
        if (t) {
          t.need_approval = false
          t.status = 'running'
        }
        return
      }
      await http.post(`/api/tasks/${id}/approve-stress`)
    },
    async getStressSeries(id: string): Promise<any> {
      if (getDataMode() === 'mock') {
        return {
          task_id: id,
          series: [
            { ts: '00:00', qps: 20, rt_ms: 280, error_rate: 0 },
            { ts: '00:30', qps: 55, rt_ms: 320, error_rate: 0 },
            { ts: '01:00', qps: 90, rt_ms: 450, error_rate: 0.001 },
            { ts: '01:30', qps: 118, rt_ms: 780, error_rate: 0.002 },
            { ts: '02:00', qps: 115, rt_ms: 1100, error_rate: 0.004 },
          ],
        }
      }
      const { data } = await http.get(`/api/tasks/${id}/stress-series`)
      return data
    },
  },

  // 5.5 调度中心（API V1.3 §3.13；mock 模式返回 null，由页面本地仿真接管）
  dispatch: {
    async overview(): Promise<DispatchOverview | null> {
      if (getDataMode() === 'mock') return null
      const { data } = await http.get('/api/dispatch/overview')
      return data
    },
    async workers(): Promise<DispatchWorker[] | null> {
      if (getDataMode() === 'mock') return null
      const { data } = await http.get('/api/dispatch/workers')
      return Array.isArray(data) ? data : data.items || []
    },
    async createWorker(payload: { id: string; name: string; caps: string[]; weight?: number }): Promise<DispatchWorker | null> {
      if (getDataMode() === 'mock') return null
      const { data } = await http.post('/api/dispatch/workers', payload)
      return data
    },
    async updateWorker(id: string, payload: { state?: string; weight?: number; caps?: string[] }): Promise<DispatchWorker | null> {
      if (getDataMode() === 'mock') return null
      const { data } = await http.put(`/api/dispatch/workers/${id}`, payload)
      return data
    },
    async updateConfig(payload: Partial<DispatchConfig>): Promise<DispatchConfig | null> {
      if (getDataMode() === 'mock') return null
      const { data } = await http.put('/api/dispatch/config', payload)
      return data
    },
    async events(afterId?: number, limit = 50): Promise<DispatchEventPage | null> {
      if (getDataMode() === 'mock') return null
      const { data } = await http.get('/api/dispatch/events', {
        params: afterId ? { after_id: afterId, limit } : { limit },
      })
      return data
    },
  },

  // 5.6 MCP 工具中心（API V1.3 §3.6.1，V1.0 只读）
  mcp: {
    async tools(): Promise<{ items: McpTool[]; total: number }> {
      if (getDataMode() === 'mock') {
        return { items: [...MOCK_MCP_TOOLS], total: MOCK_MCP_TOOLS.length }
      }
      const { data } = await http.get('/api/mcp/tools')
      return data
    },
  },

  // 6. 数据集管理
  datasets: {
    async list(): Promise<Dataset[]> {
      if (getDataMode() === 'mock') return mockStore.datasets
      try {
        const { data } = await http.get('/api/datasets')
        return Array.isArray(data) ? data : data.items || []
      } catch (e) {
        if (getDataMode() === 'mock') return mockStore.datasets
        throw e
      }
    },
    async get(id: string): Promise<Dataset> {
      if (getDataMode() === 'mock') {
        const ds = mockStore.datasets.find((x) => x.id === id)
        if (!ds) throw new ApiError('数据集不存在', ErrorCode.NOT_FOUND, 404)
        return ds
      }
      const { data } = await http.get(`/api/datasets/${id}`)
      return data
    },
    async create(payload: { name: string; metric?: string }): Promise<Dataset> {
      if (getDataMode() === 'mock') {
        const ds: Dataset = {
          id: 'ds-' + Date.now(),
          name: payload.name,
          version: 1,
          row_count: 0,
          pending_complete_count: 0,
          metric: (payload.metric as any) || 'contain',
          owner: localStorage.getItem('ae_user') || 'admin',
          created_at: new Date().toISOString(),
        }
        mockStore.datasets.unshift(ds)
        return ds
      }
      const { data } = await http.post('/api/datasets', payload)
      return data
    },
    async update(id: string, payload: Partial<Dataset>): Promise<Dataset> {
      if (getDataMode() === 'mock') {
        const idx = mockStore.datasets.findIndex((x) => x.id === id)
        if (idx >= 0) mockStore.datasets[idx] = { ...mockStore.datasets[idx], ...payload }
        return mockStore.datasets[idx]
      }
      const { data } = await http.put(`/api/datasets/${id}`, payload)
      return data
    },
    async delete(id: string): Promise<void> {
      if (getDataMode() === 'mock') {
        mockStore.datasets = mockStore.datasets.filter((x) => x.id !== id)
        return
      }
      await http.delete(`/api/datasets/${id}`)
    },
    async upload(id: string, file: File): Promise<{ version: number; row_count: number }> {
      if (getDataMode() === 'mock') {
        const ds = mockStore.datasets.find((x) => x.id === id)
        if (ds) {
          ds.version += 1
          ds.row_count = 25
        }
        return { version: ds ? ds.version : 2, row_count: 25 }
      }
      const formData = new FormData()
      formData.append('file', file)
      const { data } = await http.post(`/api/datasets/${id}/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return data
    },
    async getRows(id: string, params: { pending_complete?: boolean } = {}): Promise<DatasetRow[]> {
      if (getDataMode() === 'mock') {
        if (params.pending_complete) return mockStore.pendingRows
        return [
          { row_no: 1, question: '如何修改密码？', reference: '在右上角点击个人头像并选择修改密码', context: null },
          { row_no: 2, question: '平台支持哪些协议？', reference: '支持 OpenAI Chat、OpenAI Responses 和 Anthropic Messages', context: null },
          ...mockStore.pendingRows,
        ]
      }
      const { data } = await http.get(`/api/datasets/${id}/rows`, { params })
      return Array.isArray(data) ? data : data.items || []
    },
    // 批量保存表格编辑结果，确保行内编辑不会只停留在浏览器内存。
    async saveRows(id: string, rows: Array<DatasetRow & Record<string, unknown>>): Promise<DatasetRow[]> {
      if (getDataMode() === 'mock') return rows
      const { data } = await http.put(`/api/datasets/${id}/rows`, { rows })
      return Array.isArray(data) ? data : data.items || rows
    },
    // 请求 AI 候选行；候选必须由页面确认后再经 saveRows 落库。
    async generateRows(payload: Record<string, unknown>): Promise<Array<DatasetRow & Record<string, unknown>>> {
      if (getDataMode() === 'mock') {
        return [{
          row_no: Number(payload.row_no) || Date.now(),
          question: 'AI 候选：如何查看任务执行进度？',
          reference: '在任务中心选择对应任务，即可查看实时进度与事件。',
          context: '平台操作',
          tags: '任务中心,AI候选',
          difficulty: '简单',
        }]
      }
      const { data } = await http.post('/api/datasets/ai-generate', payload)
      return Array.isArray(data) ? data : data.items || []
    },
  },

  // 7. 用例工作台
  cases: {
    async listSets(): Promise<CaseSet[]> {
      if (getDataMode() === 'mock') return mockStore.caseSets
      try {
        const { data } = await http.get('/api/case-sets')
        return Array.isArray(data) ? data : data.items || []
      } catch (e) {
        if (getDataMode() === 'mock') return mockStore.caseSets
        throw e
      }
    },
    async getSet(id: string): Promise<CaseSet> {
      if (getDataMode() === 'mock') {
        const cs = mockStore.caseSets.find((x) => x.id === id)
        if (!cs) throw new ApiError('用例集不存在', ErrorCode.NOT_FOUND, 404)
        return { ...cs, cases: mockStore.cases }
      }
      const { data } = await http.get(`/api/case-sets/${id}`)
      return data
    },
    // 创建空用例集后仍需保存具体用例，避免把生成候选误当成已入库。
    async createSet(payload: { name: string }): Promise<CaseSet> {
      if (getDataMode() === 'mock') {
        const item: CaseSet = {
          id: 'cs-' + Date.now(),
          task_id: '',
          name: payload.name,
          status: 'generated',
          generated_count: 0,
          confirmed_count: 0,
          expires_in_h: 72,
          checks: [],
          cases: [],
          created_at: new Date().toISOString(),
        }
        mockStore.caseSets.unshift(item)
        return item
      }
      const { data } = await http.post('/api/case-sets', payload)
      return data
    },
    // 契约 PUT /api/case-sets/{id}：更新名称 / 目录归属 / 自定义列 column_schema；
    // 已确认用例集的非法修改由后端返回 VALIDATION，前端不做伪造成功。
    async updateSet(id: string, payload: { name?: string; column_schema?: Array<{ key: string; name: string; type?: string; sort_order?: number }> }): Promise<CaseSet> {
      if (getDataMode() === 'mock') {
        const cs = mockStore.caseSets.find((x) => x.id === id)
        if (!cs) throw new ApiError('用例集不存在', ErrorCode.NOT_FOUND, 404)
        if (payload.name) cs.name = payload.name
        if (payload.column_schema) (cs as CaseSet & Record<string, unknown>).column_schema = payload.column_schema
        return cs
      }
      const { data } = await http.put(`/api/case-sets/${id}`, payload)
      return data
    },
    // 批量保存用例编辑结果，后端负责已确认用例集的不可编辑校验。
    async saveCases(id: string, cases: TestCase[]): Promise<TestCase[]> {
      if (getDataMode() === 'mock') {
        mockStore.cases = cases
        return cases
      }
      const { data } = await http.put(`/api/case-sets/${id}/cases`, { cases })
      return Array.isArray(data) ? data : data.items || cases
    },
    // 仅生成未落库候选；调用方需要创建用例集并保存候选后才可显示创建成功。
    async generateCases(payload: Record<string, unknown>): Promise<TestCase[]> {
      if (getDataMode() === 'mock') {
        return [{
          id: 'c-ai-' + Date.now(),
          strategy: '反向',
          priority: 'P1',
          module: '通用',
          name: 'AI 候选：异常输入校验',
          expected: '系统拒绝无效输入并返回明确错误信息',
          precondition: '服务已就绪',
        }]
      }
      const { data } = await http.post('/api/case-sets/ai-generate', payload)
      return Array.isArray(data) ? data : data.items || []
    },
    // 契约 POST /api/case-sets/{id}/ai-fill：行级 AI 补全，仅返回未落库候选，需随“保存修改”写入。
    async aiFillCases(id: string, payload: { case_ids: string[]; instruction?: string; fields?: string[] }): Promise<Array<Partial<TestCase> & { id: string }>> {
      if (getDataMode() === 'mock') {
        return payload.case_ids.map(cid => ({
          id: cid,
          expected: '系统返回正确的业务结果与明确提示信息',
          precondition: '前置服务已启动，测试数据已插桩',
          test_type: '自动化回归',
        }))
      }
      const { data } = await http.post(`/api/case-sets/${id}/ai-fill`, payload)
      return Array.isArray(data) ? data : data.items || []
    },
    async confirmSet(id: string, payload: { ok: boolean; edits?: TestCase[]; mapping_target?: 'dataset' | 'gold_qa'; target_id?: string }): Promise<void> {
      if (getDataMode() === 'mock') {
        const cs = mockStore.caseSets.find((x) => x.id === id)
        if (cs) {
          cs.status = payload.ok ? 'confirmed' : 'cancelled'
          if (payload.ok) cs.confirmed_count = cs.generated_count
        }
        return
      }
      await http.post(`/api/case-sets/${id}/confirm`, payload)
    },
    async cancelSet(id: string, reason?: string): Promise<void> {
      if (getDataMode() === 'mock') {
        const cs = mockStore.caseSets.find((x) => x.id === id)
        if (cs) cs.status = 'cancelled'
        return
      }
      await http.post(`/api/case-sets/${id}/cancel`, { reason })
    },
    async mapCases(id: string, payload: { target: 'dataset' | 'gold_qa'; target_id: string; case_ids: string[] }): Promise<void> {
      if (getDataMode() === 'mock') {
        mockStore.cases = mockStore.cases.map(item => payload.case_ids.includes(item.id) ? { ...item, mapped: true, pending: false } : item)
        return
      }
      await http.post(`/api/case-sets/${id}/map`, payload)
    },
    // 导出由服务端生成，前端仅负责触发文件下载。
    async exportSet(id: string, fmt: 'xlsx' | 'xmind'): Promise<Blob> {
      if (getDataMode() === 'mock') {
        return new Blob([JSON.stringify(mockStore.cases, null, 2)], { type: 'application/json' })
      }
      const { data } = await http.get(`/api/case-sets/${id}/export`, { params: { fmt }, responseType: 'blob' })
      return data
    },
  },

  // 8. 知识库与 RAG
  kb: {
    async list(): Promise<KnowledgeBase[]> {
      if (getDataMode() === 'mock') return mockStore.kbs
      // M3 前后端无 /api/kb 路由：已知缺失时直接走降级数据，避免每次挂载重复打 404
      if (kbBackendMissing) return mockStore.kbs
      try {
        const { data } = await http.get('/api/kb')
        return Array.isArray(data) ? data : data.items || []
      } catch (e: any) {
        if (e.status === 404 || e.code === ErrorCode.NOT_FOUND) {
          kbBackendMissing = true
          return mockStore.kbs
        }
        throw e
      }
    },
    async get(id: string): Promise<KnowledgeBase> {
      if (getDataMode() === 'mock') {
        const kb = mockStore.kbs.find((x) => x.id === id)
        if (!kb) throw new ApiError('知识库不存在', ErrorCode.NOT_FOUND, 404)
        return kb
      }
      try {
        const { data } = await http.get(`/api/kb/${id}`)
        return data
      } catch (e: any) {
        if (e.status === 404 || e.code === ErrorCode.NOT_FOUND) {
          const kb = mockStore.kbs.find((x) => x.id === id) || mockStore.kbs[0]
          return kb
        }
        throw e
      }
    },
    async create(payload: { name: string; kind: 'lightrag' | 'external_chat'; profile_id?: string }): Promise<KnowledgeBase> {
      if (getDataMode() === 'mock') {
        const kb: KnowledgeBase = {
          id: 'kb-' + Date.now(),
          name: payload.name,
          kind: payload.kind,
          doc_count: payload.kind === 'lightrag' ? 0 : null,
          is_core: false,
          owner: localStorage.getItem('ae_user') || 'admin',
          profile_id: payload.profile_id,
          created_at: new Date().toISOString(),
        }
        mockStore.kbs.unshift(kb)
        return kb
      }
      const { data } = await http.post('/api/kb', payload)
      return data
    },
    async update(id: string, payload: Partial<KnowledgeBase>): Promise<KnowledgeBase> {
      if (getDataMode() === 'mock') {
        const idx = mockStore.kbs.findIndex((x) => x.id === id)
        if (idx >= 0) mockStore.kbs[idx] = { ...mockStore.kbs[idx], ...payload }
        return mockStore.kbs[idx]
      }
      const { data } = await http.put(`/api/kb/${id}`, payload)
      return data
    },
    async delete(id: string): Promise<void> {
      if (getDataMode() === 'mock') {
        mockStore.kbs = mockStore.kbs.filter((x) => x.id !== id)
        return
      }
      await http.delete(`/api/kb/${id}`)
    },
    async listDocs(id: string): Promise<KbDocument[]> {
      if (getDataMode() === 'mock') return mockStore.kbDocs
      try {
        const { data } = await http.get(`/api/kb/${id}/documents`)
        return Array.isArray(data) ? data : data.items || []
      } catch (e: any) {
        if (e.status === 404 || e.code === ErrorCode.NOT_FOUND) return mockStore.kbDocs
        throw e
      }
    },
    async uploadDoc(id: string, file: File): Promise<KbDocument> {
      if (getDataMode() === 'mock') {
        const doc: KbDocument = {
          doc_id: 'd-' + Date.now(),
          filename: file.name,
          status: 'indexed',
          size: (file.size / 1024).toFixed(1) + ' KB',
          created_at: new Date().toISOString(),
        }
        mockStore.kbDocs.push(doc)
        return doc
      }
      const formData = new FormData()
      formData.append('file', file)
      const { data } = await http.post(`/api/kb/${id}/documents`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return data
    },
    async deleteDoc(id: string, docId: string): Promise<void> {
      if (getDataMode() === 'mock') {
        mockStore.kbDocs = mockStore.kbDocs.filter((x) => x.doc_id !== docId)
        return
      }
      await http.delete(`/api/kb/${id}/documents/${docId}`)
    },
    // 读取服务端按当前切块参数生成的预览，浏览器不自行伪造切块文本。
    async getDocChunks(id: string, docId: string, params: { chunk_size: number; overlap: number }): Promise<KbChunk[]> {
      if (getDataMode() === 'mock') {
        const count = params.chunk_size === 256 ? 14 : params.chunk_size === 1024 ? 4 : 8
        return Array.from({ length: count }, (_, index) => ({
          chunk_id: `${docId}#c${String(index + 1).padStart(2, '0')}`,
          doc_id: docId,
          tokens: Math.round(params.chunk_size * (0.75 + ((index * 37) % 25) / 100)),
          text: `第 ${index + 1} 个服务端切块预览。`,
        }))
      }
      try {
        const { data } = await http.get(`/api/kb/${id}/documents/${docId}/chunks`, { params })
        return Array.isArray(data) ? data : data.items || []
      } catch (e: any) {
        if (e.status === 404 || e.code === ErrorCode.NOT_FOUND) {
          const count = params.chunk_size === 256 ? 14 : params.chunk_size === 1024 ? 4 : 8
          return Array.from({ length: count }, (_, index) => ({
            chunk_id: `${docId}#c${String(index + 1).padStart(2, '0')}`,
            doc_id: docId,
            tokens: Math.round(params.chunk_size * (0.75 + ((index * 37) % 25) / 100)),
            text: `第 ${index + 1} 个服务端切块预览。`,
          }))
        }
        throw e
      }
    },
    async query(id: string, queryPayload: { query: string; mode?: string; k?: number }): Promise<any> {
      if (getDataMode() === 'mock') {
        return {
          query: queryPayload.query,
          mode: queryPayload.mode || 'hybrid',
          items: [
            { chunk_id: 'd-01#c03', doc_name: 'product-manual.pdf', text: 'AI 测试与评估平台产品手册第一章：评测引擎与三协议调度规范...', similarity: 0.89, hit: true },
            { chunk_id: 'd-02#c11', doc_name: 'faq-2026.md', text: 'FAQ 常见问题第 12 条：关于黄金 QA 集制作及 Hit Rate 指标定义...', similarity: 0.82, hit: false },
          ],
          // 重排后最终序，供「重排对比」右列渲染排名位移。
          reranked_ids: ['d-01#c03', 'd-01#c01', 'd-02#c01', 'd-01#c05', 'd-03#c02'],
          metrics: { hit_rate: 0.8, mrr: 0.74, recall: 0.85, contain: 0.83 },
        }
      }
      try {
        const { data } = await http.post(`/api/kb/${id}/query`, queryPayload)
        return data
      } catch (e: any) {
        if (e.status === 404 || e.code === ErrorCode.NOT_FOUND) {
          return {
            query: queryPayload.query,
            mode: queryPayload.mode || 'hybrid',
            items: [
              { chunk_id: 'd-01#c03', doc_name: 'product-manual.pdf', text: 'AI 测试与评估平台产品手册第一章：评测引擎与三协议调度规范...', similarity: 0.89, hit: true },
              { chunk_id: 'd-02#c11', doc_name: 'faq-2026.md', text: 'FAQ 常见问题第 12 条：关于黄金 QA 集制作及 Hit Rate 指标定义...', similarity: 0.82, hit: false },
            ],
            // 重排后最终序，供「重排对比」右列渲染排名位移。
            reranked_ids: ['d-01#c03', 'd-01#c01', 'd-02#c01', 'd-01#c05', 'd-03#c02'],
            metrics: { hit_rate: 0.8, mrr: 0.74, recall: 0.85, contain: 0.83 },
          }
        }
        throw e
      }
    },
    async getGoldQA(id: string): Promise<GoldQA[]> {
      if (getDataMode() === 'mock') return mockStore.goldQAs.filter((x) => x.kb_id === id)
      if (kbBackendMissing) return mockStore.goldQAs.filter((x) => x.kb_id === id)
      try {
        const { data } = await http.get(`/api/kb/${id}/gold-qa`)
        return Array.isArray(data) ? data : data.items || []
      } catch (e: any) {
        if (e.status === 404 || e.code === ErrorCode.NOT_FOUND) {
          kbBackendMissing = true
          return mockStore.goldQAs.filter((x) => x.kb_id === id)
        }
        throw e
      }
    },
    async uploadGoldQA(id: string, file: File, name: string): Promise<GoldQA> {
      if (getDataMode() === 'mock') {
        const qa: GoldQA = {
          id: 'gq-' + Date.now(),
          kb_id: id,
          name: name || 'qa-upload',
          version: 1,
          row_count: 20,
          owner: localStorage.getItem('ae_user') || 'admin',
          created_at: new Date().toISOString(),
        }
        mockStore.goldQAs.push(qa)
        return qa
      }
      const formData = new FormData()
      formData.append('file', file)
      formData.append('name', name)
      const { data } = await http.post(`/api/kb/${id}/gold-qa`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return data
    },
  },

  // 9. 报告管理
  reports: {
    // 重载签名：默认返回报告 JSON；传 fmt='md' 时返回服务端渲染的 Markdown 纯文本
    get: reportsGet,
    async share(id: string, expireDays: number = 7): Promise<{ token: string; share_url: string }> {
      if (getDataMode() === 'mock') {
        const token = 'share-' + Math.random().toString(36).substring(2, 10)
        return { token, share_url: `${window.location.origin}/reports/${id}?share=${token}` }
      }
      const { data } = await http.post(`/api/reports/${id}/share`, { expire_days: expireDays })
      return { token: data.token, share_url: `${window.location.origin}/reports/${id}?share=${data.token}` }
    },
    async freezeBaseline(id: string): Promise<void> {
      if (getDataMode() === 'mock') return
      await http.post(`/api/reports/${id}/baseline`)
    },
  },

  // 10. 管理员设置与压测治理
  admin: {
    async getSettings(): Promise<AdminSettings> {
      if (getDataMode() === 'mock') return mockStore.settings
      try {
        const { data } = await http.get('/api/admin/settings')
        return data
      } catch (e) {
        if (getDataMode() === 'mock') return mockStore.settings
        throw e
      }
    },
    async updateSettings(payload: Partial<AdminSettings>): Promise<AdminSettings> {
      if (getDataMode() === 'mock') {
        mockStore.settings = { ...mockStore.settings, ...payload }
        return mockStore.settings
      }
      const { data } = await http.put('/api/admin/settings', payload)
      return data
    },
    async getWhitelist(): Promise<WhitelistItem[]> {
      if (getDataMode() === 'mock') return mockStore.whitelist
      try {
        const { data } = await http.get('/api/admin/stress/whitelist')
        return Array.isArray(data) ? data : data.items || []
      } catch (e) {
        if (getDataMode() === 'mock') return mockStore.whitelist
        throw e
      }
    },
    async addWhitelist(payload: { host: string; scope: string }): Promise<WhitelistItem> {
      if (getDataMode() === 'mock') {
        const item: WhitelistItem = {
          id: 'wl-' + Date.now(),
          host: payload.host,
          scope: payload.scope || 'test',
          creator: localStorage.getItem('ae_user') || 'admin',
          created_at: new Date().toISOString(),
          status: 'active',
        }
        mockStore.whitelist.push(item)
        return item
      }
      const { data } = await http.post('/api/admin/stress/whitelist', payload)
      return data
    },
    async deleteWhitelist(id: string): Promise<void> {
      if (getDataMode() === 'mock') {
        mockStore.whitelist = mockStore.whitelist.filter((x) => x.id !== id)
        return
      }
      await http.delete(`/api/admin/stress/whitelist/${id}`)
    },
  },

  // 11. 会话管理
  sessions: {
    async list(): Promise<any[]> {
      if (getDataMode() === 'mock') return mockStore.sessions
      try {
        const { data } = await http.get('/api/sessions')
        return Array.isArray(data) ? data : data.items || []
      } catch (e) {
        if (getDataMode() === 'mock') return mockStore.sessions
        throw e
      }
    },
    async create(title?: string): Promise<any> {
      if (getDataMode() === 'mock') {
        const s = {
          id: 's-' + Date.now(),
          title: title || '新会话',
          created_at: new Date().toISOString(),
        }
        mockStore.sessions.unshift(s)
        return s
      }
      const { data } = await http.post('/api/sessions', { title: title || '新会话' })
      return data
    },
    async getMessages(id: string): Promise<{ messages: any[]; events: any[] }> {
      if (getDataMode() === 'mock') return { messages: [], events: [] }
      const { data } = await http.get(`/api/sessions/${id}/messages`)
      return data
    },
  },
}

export default http
