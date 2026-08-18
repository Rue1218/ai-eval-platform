/* ============================================================
   AI 测试与评估平台 — 前端 API 统一调用层 (API V1.2)
   对应契约文档：docs/AI测试与评估平台-API.md

   默认是实时模式：任意网络/HTTP 错误都会抛给页面，绝不静默回退。
   仅 ?data=mock（或 localStorage ae_data_mode=mock）使用 MOCK_SEED。
   ============================================================ */
(function (global) {
  'use strict';

  const query = new URLSearchParams(global.location ? global.location.search : '');
  const configuredBase = global.AE_CONFIG && global.AE_CONFIG.apiBase;
  const API_BASE = (query.get('apiBase') || configuredBase || '/api').replace(/\/$/, '');
  let dataMode = query.get('data') || localStorage.getItem('ae_data_mode') || 'live';
  if (!['live', 'mock'].includes(dataMode)) dataMode = 'live';

  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function db() { return global.AE && global.AE.DB; }
  function bodyOf(config) {
    if (!config.body || typeof config.body !== 'string') return config.body || {};
    try { return JSON.parse(config.body); } catch (_) { return {}; }
  }
  function list(items) { return { items: items || [], total: (items || []).length }; }

  function startMock() {
    const store = db();
    const seed = global.AE && global.AE.MOCK_SEED;
    if (!store || !seed || store.__mockLoaded) return;
    Object.keys(store).forEach(key => { if (key !== '__mockLoaded') delete store[key]; });
    Object.assign(store, clone(seed), { __mockLoaded: true });
    store.reportsList = Object.values(store.reports || {}).map(({ id, title, kind, created_at, task_id }) => ({ id, title, kind, created_at, task_id }));
    store.sessions = [{ id: 's0', title: '新会话', created_at: new Date().toISOString() }];
  }

  /* Mock 适配器有意与 fetch 分支隔离：它只服务演示，不掩盖实时联调失败。 */
  function mockRequest(endpoint, config) {
    startMock();
    const store = db();
    const method = config.method || 'GET';
    const path = endpoint.split('?')[0];
    const payload = bodyOf(config);
    const resource = (collection, id) => (store[collection] || []).find(x => String(x.id) === String(id));

    if (path === '/auth/login') return store.users.find(u => u.username === payload.username) || store.users[0];
    if (path === '/auth/me') return store.users[0];
    if (path === '/auth/logout' || path === '/auth/change-password') return { ok: true };
    if (path === '/auth/ws-ticket') return { ticket: 'mock-ws-ticket', expires_in: 300 };
    if (path === '/files') return { id: 'file-' + Date.now(), filename: 'mock-upload', size: 0 };
    if (path === '/users') return method === 'GET' ? list(store.users) : { ...payload, id: 'u-' + Date.now() };
    if (path === '/sessions') return method === 'GET' ? list(store.sessions) : { ...payload, id: 's-' + Date.now() };
    if (/^\/sessions\/[^/]+\/messages$/.test(path)) return { messages: [], events: [] };
    if (path === '/profiles') return method === 'GET' ? list(store.profiles) : { ...payload, id: 'p-' + Date.now() };
    if (/^\/profiles\/[^/]+\/check$/.test(path)) return { ok: true, latency_ms: 128, model: 'gpt-4.1' };
    if (/^\/kb\/[^/]+\/documents$/.test(path) && method === 'GET') return list(store.kbDocs || []);
    if (/^\/profiles\/[^/]+$/.test(path)) return resource('profiles', path.split('/')[2]) || { ok: true };
    if (path === '/datasets') return method === 'GET' ? list(store.datasets) : { ...payload, id: 'ds-' + Date.now() };
    if (/^\/datasets\/[^/]+\/rows$/.test(path)) return method === 'GET' ? list(store.pendingRows) : { ok: true };
    if (/^\/datasets\/[^/]+$/.test(path)) return resource('datasets', path.split('/')[2]) || { ok: true };
    if (path === '/case-sets') return method === 'GET' ? list(store.caseSets) : { ...payload, id: 'cs-' + Date.now() };
    if (/^\/case-sets\/[^/]+$/.test(path)) return resource('caseSets', path.split('/')[2]) || { ok: true };
    if (path === '/kb') return method === 'GET' ? list(store.kbs) : { ...payload, id: 'kb-' + Date.now() };
    if (/^\/kb\/[^/]+\/gold-qa$/.test(path)) return list((store.goldQAs || []).filter(x => x.kb_id === path.split('/')[2]));
    if (/^\/kb\/[^/]+\/query$/.test(path)) return { items: [], query: payload.query, mode: payload.mode || 'hybrid' };
    if (/^\/kb\/[^/]+$/.test(path)) return resource('kbs', path.split('/')[2]) || { ok: true };
    if (path === '/tasks') {
      if (method === 'GET') return list(store.tasks);
      const task = { id: 't-' + Date.now(), ...payload, status: 'queued', created_at: new Date().toISOString(), progress: { done: 0, total: 0, message: '任务已入队' } };
      store.tasks.unshift(task); return task;
    }
    if (/^\/tasks\/[^/]+$/.test(path)) return resource('tasks', path.split('/')[2]) || { ok: true };
    if (path === '/reports') return list(store.reportsList);
    if (/^\/reports\/[^/]+$/.test(path)) return (store.reports || {})[path.split('/')[2]] || { ok: true };
    if (/^\/reports\/[^/]+\/share$/.test(path)) return { token: 'mock-share-token', expire_days: payload.expire_days || 7 };
    if (/^\/reports\/[^/]+\/baseline$/.test(path)) return { ok: true };
    if (path === '/dispatch/overview') return { max_running_tasks: store.settings.max_running_tasks, strategy: '负载均衡', queued_count: 1, running_count: 1 };
    if (path === '/dispatch/workers') return method === 'GET' ? list([]) : { ...payload, id: payload.id || 'worker-' + Date.now() };
    if (path === '/admin/settings') return store.settings;
    if (path === '/admin/stress/settings') return store.settings;
    if (path === '/admin/stress/whitelist') {
      const hosts = (store.settings.stress || {}).host_whitelist || [];
      return list(hosts.map((host, index) => ({ id: `mock-wl-${index + 1}`, host, scope: 'test,staging', creator: 'admin', created_at: '2026-08-18', status: 'active' })));
    }
    if (path === '/admin/stress/usage') return { peak_qps: 462, threshold_hit_rate: 0.28, points: [310, 385, 462, 342, 418, 460, 455].map((qps, index) => ({ ts: `2026-08-${12 + index}`, qps })) };
    if (path === '/mcp/servers' || path === '/mcp/tools' || path === '/skills') return list([]);
    return { ok: true, mock: true };
  }

  function normalizeList(value) { return Array.isArray(value) ? list(value) : value; }
  function cacheResponse(endpoint, method, value) {
    const store = db();
    if (!store || method !== 'GET' || !value) return value;
    const path = endpoint.split('?')[0];
    const map = { '/users': 'users', '/profiles': 'profiles', '/datasets': 'datasets', '/case-sets': 'caseSets', '/kb': 'kbs', '/tasks': 'tasks', '/sessions': 'sessions' };
    if (map[path] && Array.isArray(value.items)) store[map[path]] = value.items;
    if (path === '/reports' && Array.isArray(value.items)) store.reportsList = value.items;
    if (path === '/admin/settings' && typeof value === 'object') Object.assign(store.settings, value);
    if (/^\/kb\/[^/]+\/gold-qa$/.test(path) && Array.isArray(value.items)) {
      const kbId = path.split('/')[2];
      store.goldQAs = (store.goldQAs || []).filter(x => x.kb_id !== kbId).concat(value.items);
    }
    if (/^\/reports\/[^/]+$/.test(path) && value.id) store.reports[value.id] = value;
    return value;
  }

  async function request(endpoint, options = {}) {
    const body = options.body;
    const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
    const headers = { Accept: 'application/json', ...(isForm ? {} : { 'Content-Type': 'application/json' }), ...(options.headers || {}) };
    const config = { method: options.method || 'GET', headers, credentials: 'include', ...options };
    if (body && typeof body === 'object' && !isForm) config.body = JSON.stringify(body);

    if (dataMode === 'mock') return cacheResponse(endpoint, config.method, mockRequest(endpoint, config));

    const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint}`;
    let response;
    try {
      response = await fetch(url, config);
    } catch (cause) {
      const error = new Error(`无法连接 API：${url}`);
      error.code = 'NETWORK'; error.cause = cause; throw error;
    }
    if (!response.ok) {
      let errorBody;
      try { errorBody = await response.json(); } catch (_) { errorBody = {}; }
      const error = new Error(errorBody.message || `HTTP ${response.status} ${response.statusText}`);
      error.code = errorBody.code || 'INTERNAL'; error.status = response.status;
      error.fields = errorBody.fields; error.response = errorBody;
      if (response.status === 401 && !url.includes('/auth/login') && global.AE && global.AE.toast) global.AE.toast('warning', '登录态已失效，请重新登录');
      throw error;
    }
    if (options.responseType === 'blob') return response.blob();
    if (options.responseType === 'text') return response.text();
    if (response.status === 204) return { ok: true };
    const result = normalizeList(await response.json());
    return cacheResponse(endpoint, config.method, result);
  }

  /* ─── 统一 API 客户端对象 ─── */
  const API = {
    request,
    runtime: {
      apiBase: API_BASE,
      get mode() { return dataMode; }
    },
    isMock: () => dataMode === 'mock',

    /* 1. 鉴权与账号 (Auth & Users) */
    auth: {
      login: (credentials) => request('/auth/login', { method: 'POST', body: credentials }),
      logout: () => request('/auth/logout', { method: 'POST' }),
      getMe: () => request('/auth/me'),
      changePassword: (data) => request('/auth/change-password', { method: 'POST', body: data }),
      getWsTicket: () => request('/auth/ws-ticket', { method: 'POST' })
    },
    files: {
      upload: (formData) => request('/files', { method: 'POST', body: formData }),
      get: (id) => request(`/files/${id}`)
    },
    users: {
      list: () => request('/users'),
      get: (id) => request(`/users/${id}`),
      create: (data) => request('/users', { method: 'POST', body: data }),
      update: (id, data) => request(`/users/${id}`, { method: 'PUT', body: data }),
      delete: (id) => request(`/users/${id}`, { method: 'DELETE' }),
      resetPassword: (id, password) => request(`/users/${id}/reset-password`, { method: 'POST', body: { password } }),
      toggleStatus: (id, disabled) => request(`/users/${id}/status`, { method: 'PUT', body: { disabled } }),
      getAuditLogs: (id) => request(`/users/${id}/audit-logs`)
    },

    /* 2. 智能体会话 (Agent Sessions & WS) */
    agent: {
      getSessions: () => request('/sessions'),
      createSession: (data) => request('/sessions', { method: 'POST', body: data }),
      getSessionMessages: (id) => request(`/sessions/${id}/messages`),
      connectWs: (ticket, onMessage, onError, options = {}) => {
        const base = new URL(API_BASE, location.href);
        const proto = base.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new URL(`${proto}//${base.host}/ws/agent`);
        ws.searchParams.set('ticket', ticket);
        if (options.sessionId) ws.searchParams.set('session_id', options.sessionId);
        if (Number.isInteger(options.lastEventId)) ws.searchParams.set('last_event_id', String(options.lastEventId));
        const socket = new WebSocket(ws.toString());
        socket.onmessage = (event) => {
          try { onMessage(JSON.parse(event.data)); } catch (e) { onMessage(event.data); }
        };
        if (onError) socket.onerror = onError;
        return socket;
      }
    },

    /* 3. 任务与调度 (Tasks & Dispatch) */
    tasks: {
      list: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return request(`/tasks${qs ? '?' + qs : ''}`);
      },
      get: (id) => request(`/tasks/${id}`),
      create: (taskSpec) => request('/tasks', { method: 'POST', body: taskSpec }),
      cancel: (id, reason) => request(`/tasks/${id}/cancel`, { method: 'POST', body: { reason } }),
      rerun: (id) => request(`/tasks/${id}/rerun`, { method: 'POST' }),
      approveStress: (id) => request(`/tasks/${id}/approve-stress`, { method: 'POST' }),
      getStressSeries: (id) => request(`/tasks/${id}/stress-series`)
    },
    dispatch: {
      getOverview: () => request('/dispatch/overview'),
      getWorkers: () => request('/dispatch/workers'),
      createWorker: (worker) => request('/dispatch/workers', { method: 'POST', body: worker }),
      updateWorker: (id, worker) => request(`/dispatch/workers/${id}`, { method: 'PUT', body: worker }),
      updateConfig: (config) => request('/dispatch/config', { method: 'PUT', body: config })
    },

    /* 4. 数据集管理 (Datasets & Gold QA) */
    datasets: {
      list: () => request('/datasets'),
      get: (id) => request(`/datasets/${id}`),
      create: (data) => request('/datasets', { method: 'POST', body: data }),
      update: (id, data) => request(`/datasets/${id}`, { method: 'PUT', body: data }),
      delete: (id) => request(`/datasets/${id}`, { method: 'DELETE' }),
      upload: (id, formData) => request(`/datasets/${id}/upload`, { method: 'POST', body: formData }),
      getRows: (id, params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return request(`/datasets/${id}/rows${qs ? '?' + qs : ''}`);
      },
      saveRows: (id, rows) => request(`/datasets/${id}/rows`, { method: 'PUT', body: { rows } }),
      aiGenerate: (spec) => request('/datasets/ai-generate', { method: 'POST', body: spec })
    },

    /* 5. 用例工作台 (Case Sets) */
    cases: {
      listSets: () => request('/case-sets'),
      getSet: (id) => request(`/case-sets/${id}`),
      createSet: (data) => request('/case-sets', { method: 'POST', body: data }),
      saveCases: (id, cases) => request(`/case-sets/${id}/cases`, { method: 'PUT', body: { cases } }),
      confirmSet: (id, mappingSpec) => request(`/case-sets/${id}/confirm`, { method: 'POST', body: mappingSpec }),
      cancelSet: (id, reason) => request(`/case-sets/${id}/cancel`, { method: 'POST', body: { reason } }),
      batchMap: (id, mappingSpec) => request(`/case-sets/${id}/map`, { method: 'POST', body: mappingSpec }),
      exportSet: (id, fmt) => request(`/case-sets/${id}/export?fmt=${encodeURIComponent(fmt)}`, { responseType: 'blob' }),
      aiGenerate: (spec) => request('/case-sets/ai-generate', { method: 'POST', body: spec })
    },

    /* 6. 知识库与切块检索 (Knowledge Base) */
    kb: {
      list: () => request('/kb'),
      get: (id) => request(`/kb/${id}`),
      create: (data) => request('/kb', { method: 'POST', body: data }),
      update: (id, data) => request(`/kb/${id}`, { method: 'PUT', body: data }),
      delete: (id) => request(`/kb/${id}`, { method: 'DELETE' }),
      listDocs: (id) => request(`/kb/${id}/documents`),
      getDocChunks: (id, docId, params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return request(`/kb/${id}/documents/${docId}/chunks${qs ? '?' + qs : ''}`);
      },
      uploadDocs: (id, formData) => request(`/kb/${id}/documents`, { method: 'POST', body: formData }),
      deleteDoc: (id, docId) => request(`/kb/${id}/documents/${docId}`, { method: 'DELETE' }),
      query: (id, queryParams) => request(`/kb/${id}/query`, { method: 'POST', body: queryParams }),
      getGoldQA: (id) => request(`/kb/${id}/gold-qa`),
      uploadGoldQA: (id, data) => request(`/kb/${id}/gold-qa`, { method: 'POST', body: data })
    },

    /* 7. 评测报告 (Reports) */
    reports: {
      list: () => request('/reports'),
      get: (id, fmt) => request(`/reports/${id}${fmt ? '?fmt=' + fmt : ''}`, { responseType: fmt === 'md' ? 'text' : 'json' }),
      getSamples: (id, params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return request(`/reports/${id}/samples${qs ? '?' + qs : ''}`);
      },
      share: (id, expireDays = 7) => request(`/reports/${id}/share`, { method: 'POST', body: { expire_days: expireDays } }),
      freezeBaseline: (id) => request(`/reports/${id}/baseline`, { method: 'POST' })
    },

    /* 8. 协议档与压测治理 (Profiles & Stress Governance) */
    profiles: {
      list: () => request('/profiles'),
      get: (id) => request(`/profiles/${id}`),
      create: (data) => request('/profiles', { method: 'POST', body: data }),
      update: (id, data) => request(`/profiles/${id}`, { method: 'PUT', body: data }),
      delete: (id) => request(`/profiles/${id}`, { method: 'DELETE' }),
      check: (id) => request(`/profiles/${id}/check`, { method: 'POST' })
    },
    mcp: {
      listServers: () => request('/mcp/servers'),
      createServer: (data) => request('/mcp/servers', { method: 'POST', body: data }),
      updateServer: (id, data) => request(`/mcp/servers/${id}`, { method: 'PUT', body: data }),
      deleteServer: (id) => request(`/mcp/servers/${id}`, { method: 'DELETE' }),
      checkServer: (id) => request(`/mcp/servers/${id}/check`, { method: 'POST' }),
      listTools: () => request('/mcp/tools')
    },
    skills: {
      listSkills: () => request('/skills'),
      getSkill: (id) => request(`/skills/${id}`),
      createSkill: (data) => request('/skills', { method: 'POST', body: data }),
      updateSkill: (id, data) => request(`/skills/${id}`, { method: 'PUT', body: data }),
      deleteSkill: (id) => request(`/skills/${id}`, { method: 'DELETE' })
    },
    settings: {
      getSettings: () => request('/admin/settings'),
      updateSettings: (data) => request('/admin/settings', { method: 'PUT', body: data })
    },
    stress: {
      getSettings: () => request('/admin/stress/settings'),
      updateSettings: (settings) => request('/admin/stress/settings', { method: 'PUT', body: settings }),
      getUsage: () => request('/admin/stress/usage'),
      getWhitelist: () => request('/admin/stress/whitelist'),
      addWhitelist: (item) => request('/admin/stress/whitelist', { method: 'POST', body: item }),
      deleteWhitelist: (id) => request(`/admin/stress/whitelist/${id}`, { method: 'DELETE' })
    }
  };

  if (dataMode === 'mock') startMock();

  // 挂载至全局
  global.AE_API = API;
  if (global.AE) {
    global.AE.API = API;
  }
})(typeof window !== 'undefined' ? window : this);
