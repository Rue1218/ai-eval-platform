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
  type GoldQA,
  type Task,
  type TaskSpec,
  type Report,
  type AdminSettings,
  type CaseSet,
  type TestCase,
  type WhitelistItem,
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
    async confirmSet(id: string, payload: { ok: boolean; edits?: any[] }): Promise<void> {
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
    async mapCases(id: string, payload: { target_type: 'dataset' | 'gold_qa'; target_id: string }): Promise<void> {
      if (getDataMode() === 'mock') return
      await http.post(`/api/case-sets/${id}/map`, payload)
    },
  },

  // 8. 知识库与 RAG
  kb: {
    async list(): Promise<KnowledgeBase[]> {
      if (getDataMode() === 'mock') return mockStore.kbs
      try {
        const { data } = await http.get('/api/kb')
        return Array.isArray(data) ? data : data.items || []
      } catch (e) {
        if (getDataMode() === 'mock') return mockStore.kbs
        throw e
      }
    },
    async get(id: string): Promise<KnowledgeBase> {
      if (getDataMode() === 'mock') {
        const kb = mockStore.kbs.find((x) => x.id === id)
        if (!kb) throw new ApiError('知识库不存在', ErrorCode.NOT_FOUND, 404)
        return kb
      }
      const { data } = await http.get(`/api/kb/${id}`)
      return data
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
      const { data } = await http.get(`/api/kb/${id}/documents`)
      return Array.isArray(data) ? data : data.items || []
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
    async query(id: string, queryPayload: { query: string; mode?: string }): Promise<any> {
      if (getDataMode() === 'mock') {
        return {
          query: queryPayload.query,
          mode: queryPayload.mode || 'hybrid',
          response: 'LightRAG 混合检索结果：根据提供的知识库文档，平台支持混合召回与图谱实体关联...',
          chunks: [
            { chunk_id: 'ck-01', doc_id: 'd-01', text: 'AI 测试与评估平台产品手册第一章：评测引擎与三协议调度规范...', tokens: 180, similarity: 0.89 },
            { chunk_id: 'ck-02', doc_id: 'd-02', text: 'FAQ 常见问题第 12 条：关于黄金 QA 集制作及 Hit Rate 指标定义...', tokens: 140, similarity: 0.82 },
          ],
        }
      }
      const { data } = await http.post(`/api/kb/${id}/query`, queryPayload)
      return data
    },
    async getGoldQA(id: string): Promise<GoldQA[]> {
      if (getDataMode() === 'mock') return mockStore.goldQAs.filter((x) => x.kb_id === id)
      const { data } = await http.get(`/api/kb/${id}/gold-qa`)
      return Array.isArray(data) ? data : data.items || []
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
    async get(id: string): Promise<Report> {
      if (getDataMode() === 'mock') {
        const r = mockStore.reports[id] || mockStore.reports['r-bm-1']
        return r
      }
      const { data } = await http.get(`/api/reports/${id}`)
      return data
    },
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
