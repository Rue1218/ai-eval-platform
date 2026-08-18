/* ============================================================
   AI 测试与评估平台 — 共享 UI、静态枚举与页面数据缓存
   数据口径：API V1.2；状态机与文案：PRD V1.6.3 + 设计规范 V1.2

   说明：STATIC/枚举是 UI 固定配置；DB 是 API 响应缓存，初始为空。
   仅在 URL 带 ?data=mock 时，api.js 才会用 MOCK_SEED 填充 DB。
   ============================================================ */
window.AE = (function () {
  'use strict';

  /* ─── 角色：单一角色「成员」，全员同权（不再区分管理员/工程师） ─── */
  const ROLES = { member: '成员' };
  function getRole() { return 'member'; }
  function setRole() { /* 单角色：保留接口，不再写入 */ }
  function getUser() {
    return { username: localStorage.getItem('ae_user') || 'admin', role: 'member' };
  }
  const canWrite = () => true;
  const isAdmin = () => true;

  /* ─── 测试对象模式：大模型 / RAG（全局，顶栏居中切换，localStorage 持久化） ─── */
  const MODES = {
    llm: { label: '大模型', desc: '基础模型 / 推理接口 / 对比评测 / 模型压测', kinds: ['benchmark', 'stress', 'testcase'], c: 'var(--c-datasets)', t: 'var(--t-datasets)' },
    rag: { label: 'RAG', desc: 'LightRAG / 外部 RAG / 知识库 / 黄金 QA', kinds: ['rag', 'testcase'], c: 'var(--c-kb)', t: 'var(--t-kb)' }
  };
  function getMode() { return localStorage.getItem('ae_mode') === 'rag' ? 'rag' : 'llm'; }
  function getDataMode() {
    const queryMode = new URLSearchParams(location.search).get('data');
    const mode = queryMode || localStorage.getItem('ae_data_mode') || 'live';
    return mode === 'mock' ? 'mock' : 'live';
  }
  function dataSourceBadgeHtml() {
    const mode = getDataMode();
    return `<span class="data-source-badge ${mode}" title="${mode === 'live' ? '请求会真实发送到 API；失败会直接显示错误' : '仅使用原型 Mock 种子，不会请求后端'}">${mode === 'live' ? '● 实时 API' : '◆ 示例 Mock'}</span>`;
  }
  function setMode(m, silent) {
    if (!MODES[m]) return;
    localStorage.setItem('ae_mode', m);
    document.querySelectorAll('.mode-switch .mode-opt').forEach(b => b.classList.toggle('on', b.dataset.mode === m));
    window.dispatchEvent(new CustomEvent('ae:mode', { detail: m }));
    if (!silent) toast('info', `已切换至「${MODES[m].label}」模式（${MODES[m].desc}）`);
  }
  function modeMatch(kind) { return MODES[getMode()].kinds.includes(kind); }
  const MODE_ICON = {
    llm: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="2"/><rect x="10" y="10" width="4" height="4"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/></svg>',
    rag: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M5 5.5A2.5 2.5 0 0 1 7.5 3H19v15H7.5A2.5 2.5 0 0 0 5 20.5Z"/><path d="M5 18.5V5.5"/><path d="M9 7.5h6"/></svg>'
  };
  function modeSwitchHtml() {
    const cur = getMode();
    return `<div class="mode-switch" data-od-id="mode-switch" role="tablist" aria-label="测试对象模式">${Object.keys(MODES).map(m =>
      `<button class="mode-opt ${m === cur ? 'on' : ''}" data-mode="${m}" role="tab" aria-selected="${m === cur}" title="测试对象：${MODES[m].label}（${MODES[m].desc}）">${MODE_ICON[m]}<span class="mode-label">${MODES[m].label}</span><i class="mode-dot"></i></button>`).join('')}</div>`;
  }

  /* ─── 枚举与文案（PRD / 规范 §7.3） ───────────────────────── */
  const STATUS = {
    queued: { label: '排队中', cls: 'queued' },
    running: { label: '运行中', cls: 'running' },
    awaiting_case_confirm: { label: '待用例确认', cls: 'awaiting_case_confirm' },
    succeeded: { label: '已成功', cls: 'succeeded' },
    failed: { label: '已失败', cls: 'failed' },
    cancelled: { label: '已取消', cls: 'cancelled' }
  };
  const KIND = {
    benchmark: { label: 'benchmark', cls: 'kind-benchmark', name: '基准评测' },
    rag: { label: 'rag', cls: 'kind-rag', name: 'RAG 评测' },
    testcase: { label: 'testcase', cls: 'kind-testcase', name: '用例生成' },
    stress: { label: 'stress', cls: 'kind-stress', name: '压测' }
  };
  const ERR_TEXT = {
    UNAUTHORIZED: '没有权限做这件事',
    VALIDATION: '请检查标红字段',
    NOT_FOUND: '资源不存在或已删除',
    BUDGET_EXCEEDED: '已达本任务预算上限',
    CONCURRENCY: '平台并发已满，任务保持排队',
    WHITELIST: '目标不在压测白名单',
    NEED_APPROVAL: '等待会签后才能发压',
    UPSTREAM: '被测接口失败，详见样本错误',
    TIMEOUT: '超时',
    INTERNAL: '内部错误，请重试或联系平台维护者'
  };

  /* ─── Mock 种子（只供 ?data=mock 的原型演示，绝不作为实时 API 回退） ─── */
  const MOCK_SEED = {
    profiles: [
      { id: 'p-gpt', name: 'gpt-test', protocol: 'openai_chat', base_url: 'https://api.example.com', model: 'gpt-4.1', usages: ['target'], created_at: '2026-08-02T09:00:00Z' },
      { id: 'p-claude', name: 'claude-x', protocol: 'anthropic_messages', base_url: 'https://api.anthropic.example.com', model: 'claude-sonnet-4.5', usages: ['target'], created_at: '2026-08-02T09:10:00Z' },
      { id: 'p-agent', name: 'agent-主', protocol: 'anthropic_messages', base_url: 'https://api.anthropic.example.com', model: 'claude-sonnet-4.5', usages: ['agent'], created_at: '2026-08-01T08:00:00Z' },
      { id: 'p-judge', name: 'judge-1', protocol: 'openai_responses', base_url: 'https://api.example.com', model: 'o4', usages: ['judge'], created_at: '2026-08-03T10:00:00Z' },
      { id: 'p-ragsvc', name: 'rag-客服外挂', protocol: 'openai_chat', base_url: 'http://10.0.0.8:8080', model: 'rag-chat-v2', usages: ['target'], created_at: '2026-08-05T11:00:00Z' }
    ],
    datasets: [
      { id: 'ds-smoke', name: 'smoke-20', version: 3, row_count: 20, pending_complete_count: 2, metric: 'contain', owner: 'alice', created_at: '2026-08-10T03:00:00Z' },
      { id: 'ds-pay', name: '支付链路问答', version: 1, row_count: 156, pending_complete_count: 0, metric: 'rouge_l', owner: 'bob', created_at: '2026-08-12T07:30:00Z' },
      { id: 'ds-faq', name: 'FAQ-标准问', version: 2, row_count: 480, pending_complete_count: 6, metric: 'exact', owner: 'alice', created_at: '2026-08-14T02:20:00Z' }
    ],
    pendingRows: [
      { row_no: 3, question: '', reference: '在「设置-账单」中申请', context: null, source_case_id: 'c-018' },
      { row_no: 17, question: '如何导出上一年度对账单？', reference: '', context: null, source_case_id: 'c-031' }
    ],
    kbs: [
      { id: 'kb-default', name: 'default', kind: 'lightrag', doc_count: 12, is_core: true, owner: 'admin' },
      { id: 'kb-cs', name: '外挂客服', kind: 'external_chat', doc_count: null, is_core: false, owner: 'alice', profile_id: 'p-ragsvc' }
    ],
    kbDocs: [
      { doc_id: 'd-01', filename: 'product-manual.pdf', status: 'indexed', size: '2.4 MB' },
      { doc_id: 'd-02', filename: 'faq-2026.md', status: 'indexed', size: '88 KB' },
      { doc_id: 'd-03', filename: 'refund-policy.html', status: 'indexing', size: '41 KB' }
    ],
    goldQAs: [
      { id: 'gq-1', kb_id: 'kb-default', name: 'qa-v1', version: 2, row_count: 20, owner: 'admin', created_at: '2026-08-13T02:00:00Z' },
      { id: 'gq-2', kb_id: 'kb-cs', name: '客服黄金集', version: 1, row_count: 64, owner: 'alice', created_at: '2026-08-15T09:30:00Z' }
    ],
    users: [
      { id: 'u-admin', username: 'admin', role: 'member', disabled: false, created_at: '2026-08-01T00:00:00Z' },
      { id: 'u-alice', username: 'alice', role: 'member', disabled: false, created_at: '2026-08-02T03:00:00Z' },
      { id: 'u-bob', username: 'bob', role: 'member', disabled: false, created_at: '2026-08-04T06:00:00Z' },
      { id: 'u-boss', username: 'boss', role: 'member', disabled: false, created_at: '2026-08-06T08:00:00Z' },
      { id: 'u-carol', username: 'carol', role: 'member', disabled: true, created_at: '2026-08-07T09:00:00Z' }
    ],
    settings: {
      agent_profile_id: 'p-agent',
      max_running_tasks: 3,
      max_inflight_model_calls: 8,
      default_max_usd: 5,
      stress: { host_whitelist: ['10.0.0.8'], max_qps: 500, max_duration_s: 1800, price_per_1k_tokens: 0.002 },
      notify: { wecom: false, email: false, webhook: false },
      prod_approvers: ['admin', 'bob']
    },
    caseSets: [
      {
        id: 'cs-pay', task_id: 't-case-1', name: 'PRD-支付', status: 'generated',
        generated_count: 40, confirmed_count: 0, expires_in_h: 70.2,
        checks: [
          { level: 'error', code: 'no_core_positive', message: '无核心正向用例' },
          { level: 'error', code: 'missing_constraint_negative', message: '缺约束反向用例' }
        ]
      },
      { id: 'cs-login', task_id: 't-case-0', name: 'PRD-登录', status: 'confirmed', generated_count: 32, confirmed_count: 26, expires_in_h: 0, checks: [] },
      { id: 'cs-coupon', task_id: 't-case-2', name: 'PRD-优惠券', status: 'cancelled', generated_count: 45, confirmed_count: 0, expires_in_h: 0, checks: [] }
    ],
    cases: [
      { id: 'c-001', strategy: '正向', priority: 'P0', module: '登录', name: '正确账密登录成功', expected: '进入工作台首页', mapped: true, pending: false },
      { id: 'c-002', strategy: '正向', priority: 'P0', module: '支付', name: '余额充足时支付成功', expected: '订单状态变为已支付', mapped: true, pending: false },
      { id: 'c-003', strategy: '反向', priority: 'P1', module: '登录', name: '错误密码登录', expected: '提示用户名或密码错误', mapped: false, pending: true },
      { id: 'c-004', strategy: '反向', priority: 'P1', module: '支付', name: '余额不足支付', expected: '返回余额不足错误码', mapped: true, pending: false },
      { id: 'c-005', strategy: '边界', priority: 'P1', module: '支付', name: '支付金额为 0.01', expected: '允许最小金额支付', mapped: true, pending: false },
      { id: 'c-006', strategy: '边界', priority: 'P2', module: '支付', name: '支付金额达单笔上限', expected: '按限额规则拦截', mapped: false, pending: true },
      { id: 'c-007', strategy: '状态', priority: 'P1', module: '订单', name: '重复提交支付请求', expected: '幂等返回同一订单', mapped: true, pending: false },
      { id: 'c-008', strategy: '场景', priority: 'P2', module: '支付', name: '支付中断网重试', expected: '恢复后可查询最终状态', mapped: true, pending: false }
    ],
    tasks: [
      { id: 'a1f3c2', kind: 'benchmark', status: 'running', progress: { percent: 40, done: 40, total: 100, message: '正在调用被测 gpt-test' }, ref: 'smoke-20 v3', creator: 'alice', created_at: -120, report_id: null, parent_task_id: null },
      { id: 'b2e8d1', kind: 'rag', status: 'succeeded', progress: { done: 20, total: 20, message: '完成' }, ref: 'default 库 · qa-v1 v2', creator: 'bob', created_at: -3700, report_id: 'r-rag-1', parent_task_id: null },
      { id: 'c3d9e7', kind: 'stress', status: 'queued', progress: { done: 0, total: 1, message: '等待会签' }, ref: '↳ 父任务 b2e8d1', creator: 'bob', created_at: -3600, report_id: null, parent_task_id: 'b2e8d1', need_approval: true },
      { id: 'd4c1a9', kind: 'testcase', status: 'awaiting_case_confirm', progress: { done: 1, total: 2, message: '用例已生成，等待确认' }, ref: 'PRD-支付', creator: 'alice', created_at: -86400, report_id: null, parent_task_id: null },
      { id: 'e5f2b8', kind: 'benchmark', status: 'succeeded', progress: { done: 20, total: 20, message: '完成' }, ref: 'smoke-20 v3', creator: 'alice', created_at: -90000, report_id: 'r-bm-1', parent_task_id: null },
      { id: 'f6a7c4', kind: 'benchmark', status: 'failed', progress: { done: 11, total: 100, message: 'UPSTREAM：被测接口持续 5xx' }, ref: 'FAQ-标准问 v2', creator: 'bob', created_at: -180000, report_id: null, parent_task_id: null },
      { id: 'g7b3d5', kind: 'stress', status: 'succeeded', progress: { done: 1, total: 1, message: '完成' }, ref: '↳ 父任务 e5f2b8', creator: 'alice', created_at: -89000, report_id: 'r-st-1', parent_task_id: 'e5f2b8' },
      { id: 'h8c4e6', kind: 'rag', status: 'cancelled', progress: { done: 7, total: 20, message: '已被创建者取消' }, ref: '外挂客服 · 客服黄金集 v1', creator: 'alice', created_at: -260000, report_id: null, parent_task_id: null }
    ],
    reports: {
      'r-bm-1': {
        id: 'r-bm-1', task_id: 'e5f2b8', kind: 'benchmark', created_at: '2026-08-15T06:02:00Z',
        title: 'Benchmark 报告 · smoke-20 v3 · 主指标 contain',
        snapshot: { dataset: 'smoke-20', dataset_version: 3, metric: 'contain', sample_size: 20, concurrency: 4, timeout_s: 60, seed: 20260815 },
        baseline: { task_id: 'e0base88', delta: -0.07 },
        scores: [
          { profile: 'gpt-test', contain: 0.86, fail_rate: 0.02, latency: '820ms', judge: 4.2 },
          { profile: 'claude-x', contain: 0.79, fail_rate: 0.05, latency: '1.1s', judge: 3.9 }
        ],
        failed_items: [
          { row: 7, question: '如何修改默认结算账户？', error: 'UPSTREAM', raw: 'HTTP 502 from upstream, body truncated…' },
          { row: 13, question: '退款多久到账？', error: 'TIMEOUT', raw: 'timeout after 60s' }
        ]
      },
      'r-rag-1': {
        id: 'r-rag-1', task_id: 'b2e8d1', kind: 'rag', created_at: '2026-08-17T01:12:00Z',
        title: 'RAG 报告 · default 库 · qa-v1 v2 · K=5',
        k: 5, modes: ['naive', 'local', 'global', 'hybrid'],
        scores: {
          naive: { hit: 0.62, mrr: 0.55, recall: 0.70, contain: 0.74 },
          local: { hit: 0.71, mrr: 0.66, recall: 0.78, contain: 0.77 },
          global: { hit: 0.68, mrr: 0.61, recall: 0.75, contain: 0.72 },
          hybrid: { hit: 0.80, mrr: 0.74, recall: 0.85, contain: 0.83 }
        },
        degraded: { mode: 'hybrid', pp: -6 },
        hit_note: '20 条样本中 3 条无 expected_doc_ids，未计入 Hit Rate 分母'
      },
      'r-st-1': {
        id: 'r-st-1', task_id: 'g7b3d5', kind: 'stress', created_at: '2026-08-15T06:40:00Z',
        title: '压测报告 · 继承自任务 e5f2b8 · env=test',
        env: 'test', qps_peak: 118, p99: '1.2s', error_rate: '0.4%', ttft: '320ms', tpot: '45ms', tokens_per_s: '1.8k', est_cost: '$0.42',
        sla_p99_ms: 1500, sla_met: true, knee: '第 3 分钟首次 P99 > SLA（或错误率 ≥1%）'
      }
    }
  };

  /* ─── API 响应缓存（实时模式从 API 写入；不可放示例业务数据） ─── */
  const DB = {
    profiles: [], datasets: [], pendingRows: [], kbs: [], kbDocs: [], goldQAs: [],
    users: [], caseSets: [], cases: [], tasks: [], reports: {}, reportsList: [], sessions: [],
    settings: {
      agent_profile_id: null, max_running_tasks: null, max_inflight_model_calls: null,
      default_max_usd: null, stress: {}, notify: {}, prod_approvers: []
    }
  };

  /* ─── 工具 ────────────────────────────────────────────────── */
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  function relTime(ts) {
    const diff = typeof ts === 'number' && ts < 0 ? -ts * 1000 : Date.now() - new Date(ts).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1) return '刚刚';
    if (m < 60) return m + ' 分钟前';
    const h = Math.floor(m / 60);
    if (h < 24) return h + ' 小时前';
    return Math.floor(h / 24) + ' 天前';
  }
  function statusBadge(st, extra) {
    const m = STATUS[st] || STATUS.queued;
    return `<span class="badge badge-${m.cls}"><i class="bdot"></i>${m.label}${extra ? `<span class="tertiary">· ${esc(extra)}</span>` : ''}</span>`;
  }
  function kindTag(k) {
    const m = KIND[k] || KIND.benchmark;
    return `<span class="kind-tag ${m.cls}">${m.label}</span>`;
  }
  function agentModel() {
    const p = (DB.profiles || []).find(x => x.id === DB.settings.agent_profile_id);
    return p ? p.model : '未配置';
  }

  /* ─── Toast（规范 §14.2） ─────────────────────────────────── */
  const ICONS = {
    success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8.5 12.2 2.4 2.4 4.6-5"/></svg>',
    error: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5"/><circle cx="12" cy="16.4" r=".4" fill="currentColor"/></svg>',
    warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5 21 20H3Z"/><path d="M12 10v4"/><circle cx="12" cy="17" r=".4" fill="currentColor"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><circle cx="12" cy="7.6" r=".4" fill="currentColor"/></svg>'
  };
  function toast(type, text, ms) {
    let stack = document.querySelector('.toast-stack');
    if (!stack) { stack = document.createElement('div'); stack.className = 'toast-stack'; document.body.appendChild(stack); }
    while (stack.children.length >= 3) stack.firstChild.remove();
    const el = document.createElement('div');
    el.className = 'toast toast-' + type;
    el.innerHTML = `<span class="toast-icon">${ICONS[type] || ICONS.info}</span><div class="grow">${esc(text)}</div>`;
    stack.appendChild(el);
    const ttl = ms || (type === 'error' ? 5000 : 3000);
    setTimeout(() => { el.classList.add('leaving'); setTimeout(() => el.remove(), 220); }, ttl);
  }
  function toastErr(code) { toast('error', ERR_TEXT[code] || code); }

  /* ─── Dialog / Modal / Drawer（规范 §14，层级 2000/1500） ─── */
  function closeOverlay(el) { if (el && el.parentNode) { el.style.opacity = '0'; setTimeout(() => el.remove(), 140); } }
  function dialog(opt) {
    // opt: {title, body(html), okText, okClass, cancelText, onOk, danger, maskClosable}
    const ov = document.createElement('div');
    ov.className = 'overlay';
    ov.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-head">${esc(opt.title)}</div>
        <div class="modal-body">${opt.body || ''}</div>
        <div class="modal-foot">
          <button class="btn btn-secondary" data-act="cancel">${esc(opt.cancelText || '返回')}</button>
          <button class="btn ${opt.okClass || 'btn-danger'}" data-act="ok">${esc(opt.okText || '确定')}</button>
        </div>
      </div>`;
    document.body.appendChild(ov);
    ov.querySelector('[data-act=cancel]').onclick = () => closeOverlay(ov);
    ov.querySelector('[data-act=ok]').onclick = () => { const r = opt.onOk && opt.onOk(); if (r !== false) closeOverlay(ov); };
    if (opt.maskClosable) ov.addEventListener('mousedown', e => { if (e.target === ov) closeOverlay(ov); });
    ov.addEventListener('keydown', e => { if (e.key === 'Escape' && opt.maskClosable) closeOverlay(ov); });
    ov.querySelector('[data-act=ok]').focus();
    return ov;
  }
  function modal(opt) {
    // opt: {title, body(html), wide, foot(html), noMaskClose, onMount(el, close)}
    const ov = document.createElement('div');
    ov.className = 'overlay';
    ov.innerHTML = `
      <div class="modal ${opt.wide ? 'wide' : ''}" role="dialog" aria-modal="true">
        <div class="modal-head">${esc(opt.title)}<button class="modal-x" aria-label="关闭"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>
        <div class="modal-body">${opt.body || ''}</div>
        ${opt.foot ? `<div class="modal-foot">${opt.foot}</div>` : ''}
      </div>`;
    document.body.appendChild(ov);
    const close = () => closeOverlay(ov);
    ov.querySelector('.modal-x').onclick = close;
    if (!opt.noMaskClose) ov.addEventListener('mousedown', e => { if (e.target === ov) close(); });
    if (opt.onMount) opt.onMount(ov, close);
    return { el: ov, close };
  }
  function drawer(opt) {
    // opt: {title, body(html), wide, foot(html), onMount(el, close)}
    const mask = document.createElement('div');
    mask.className = 'drawer-mask';
    const dr = document.createElement('div');
    dr.className = 'drawer' + (opt.wide ? ' wide' : '');
    dr.setAttribute('role', 'dialog');
    dr.innerHTML = `
      <div class="drawer-head">${esc(opt.title)}<button class="modal-x" aria-label="关闭"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>
      <div class="drawer-body">${opt.body || ''}</div>
      ${opt.foot ? `<div class="drawer-foot">${opt.foot}</div>` : ''}`;
    document.body.appendChild(mask); document.body.appendChild(dr);
    const close = () => { closeOverlay(mask); dr.style.transform = 'translateX(60px)'; dr.style.opacity = '0'; setTimeout(() => dr.remove(), 180); };
    mask.onclick = close;
    dr.querySelector('.modal-x').onclick = close;
    document.addEventListener('keydown', function onEsc(e) { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onEsc); } });
    if (opt.onMount) opt.onMount(dr, close);
    return { el: dr, close };
  }

  /* ─── 修改密码（设计方案 1.1 顶栏用户菜单：改密 / 退出） ─── */
  function changePassword() {
    modal({
      title: '修改密码',
      body: `
        <div class="field"><span class="field-label">当前密码 <i class="req">*</i></span><input class="input" id="cp-old" type="password" autocomplete="current-password"></div>
        <div class="field"><span class="field-label">新密码 <i class="req">*</i></span><input class="input" id="cp-new" type="password" placeholder="≥8 位，含字母和数字" autocomplete="new-password"></div>
        <div class="field"><span class="field-label">确认新密码 <i class="req">*</i></span><input class="input" id="cp-new2" type="password" autocomplete="new-password"></div>
        <div class="field-error" id="cp-err" style="display:none"></div>`,
      foot: `<button class="btn btn-sign" id="cp-ok">确认修改</button>`,
      onMount: (el, close) => {
        el.querySelector('#cp-ok').onclick = () => {
          const o = el.querySelector('#cp-old').value;
          const a = el.querySelector('#cp-new').value;
          const b = el.querySelector('#cp-new2').value;
          const err = el.querySelector('#cp-err');
          const show = t => { err.textContent = t; err.style.display = ''; };
          if (!o) return show('请输入当前密码');
          if (a.length < 8 || !/[a-zA-Z]/.test(a) || !/\d/.test(a)) return show('密码需不少于 8 位，且包含字母和数字');
          if (a !== b) return show('两次输入的密码不一致');
          close();
          toast('success', '密码已更新（写审计）');
        };
      }
    });
  }

  /* ─── 外壳渲染 ────────────────────────────────────────────── */
  const NAV = [
    { group: '评测' },
    { id: 'agent', label: '智能体', href: 'agent.html', t: 'var(--t-agent)', c: 'var(--c-agent)', ico: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a5 5 0 0 1 5 5v1a5 5 0 0 1-5 5 5 5 0 0 1-5-5V8a5 5 0 0 1 5-5Z"/><path d="M5 21c0-3.3 3.1-5 7-5s7 1.7 7 5"/></svg>' },
    { id: 'dispatch', label: '调度中心', href: 'dispatch.html', t: 'var(--t-agent)', c: 'var(--c-agent)', ico: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="2.4"/><circle cx="5" cy="5" r="1.8"/><circle cx="19" cy="5" r="1.8"/><circle cx="5" cy="19" r="1.8"/><circle cx="19" cy="19" r="1.8"/><path d="M6.4 6.4 10 10M13.9 10.1l3.7-3.7M6.4 17.6 10 14M13.9 13.9l3.7 3.7"/></svg>' },
    { id: 'tasks', label: '任务中心', href: 'tasks.html', t: 'var(--t-tasks)', c: 'var(--c-tasks)', ico: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 9h8M8 13h5"/></svg>' },
    { id: 'report', label: '评测报告', href: 'report.html', t: 'var(--t-reports)', c: 'var(--c-reports)', ico: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M5 20V10M12 20V4M19 20v-7"/></svg>' },
    { id: 'datasets', label: '数据集', href: 'datasets.html', t: 'var(--t-datasets)', c: 'var(--c-datasets)', ico: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg>' },
    { id: 'cases', label: '用例', href: 'cases.html', t: 'var(--t-cases)', c: 'var(--c-cases)', ico: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11.5 11 14l4.5-5"/><rect x="4" y="4" width="16" height="16" rx="3"/></svg>' },
    { id: 'kb', label: '知识库', href: 'kb.html', t: 'var(--t-kb)', c: 'var(--c-kb)', ico: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 5.5A2.5 2.5 0 0 1 7.5 3H19v15H7.5A2.5 2.5 0 0 0 5 20.5Z"/><path d="M5 18.5V5.5"/><path d="M9 7.5h6"/></svg>' },
    { group: '管理' },
    { id: 'profiles', label: '协议档', href: 'admin-profiles.html', t: 'var(--t-profiles)', c: 'var(--c-profiles)', ico: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="M7 10h4M7 14h7"/></svg>' },
    { id: 'stress', label: '压测治理', href: 'admin-stress.html', t: 'var(--t-stress)', c: 'var(--c-stress)', ico: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l5-6 4 3 6-8"/><path d="M18 6h3v3"/></svg>' },
    { id: 'users', label: '账号', href: 'admin-users.html', t: 'var(--t-users)', c: 'var(--c-users)', ico: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="9" cy="8" r="3.5"/><path d="M3.5 20c.6-3.2 2.9-5 5.5-5s4.9 1.8 5.5 5"/><path d="M16 8.5h5M18.5 6v5"/></svg>' }
  ];

  function renderShell(activeId, pageTitle, opts) {
    opts = opts || {};
    const user = getUser();
    const root = document.getElementById('app');
    if (!root) return;
    root.className = 'app';

    let navHtml = '';
    NAV.forEach(n => {
      if (n.group) {
        navHtml += `<div class="nav-group">${n.group}</div>`;
        return;
      }
      const dot = n.id === 'agent' && opts.agentDot ? `<i class="nav-dot ${opts.agentDot}"></i>` : '';
      navHtml += `<a class="nav-item ${n.id === activeId ? 'active' : ''}" style="--t:${n.t};--c:${n.c}" href="${n.href}" data-od-id="nav-${n.id}">
        <span class="nav-ico">${n.ico}</span><span class="nav-label">${n.label}</span>${dot}</a>`;
    });

    root.innerHTML = `
      <aside class="sidebar" data-od-id="sidebar">
        <div class="brand">
          <span class="brand-mark">A</span>
          <span class="brand-text"><span class="brand-name">AI Eval</span><br><span class="brand-sub">TEST &amp; EVAL</span></span>
        </div>
        <nav class="nav">${navHtml}</nav>
        <div class="sidebar-foot">
          <button class="sidebar-fold" id="ae-fold" title="折叠 / 展开导航栏（260px ⇄ 72px）">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m14 6-6 6 6 6"/></svg>
            <span class="fold-label">收起导航</span>
          </button>
          <div class="user-card">
            <span class="avatar">${esc(user.username[0].toUpperCase())}</span>
            <span class="user-meta"><span class="user-name">${esc(user.username)}</span><br><span class="user-role">${ROLES.member}</span></span>
          </div>
        </div>
      </aside>
      <div class="main" data-od-id="main">
        <header class="topbar" data-od-id="topbar">
          <div class="topbar-title">${esc(pageTitle)}${opts.titleExtra || ''}</div>
          ${modeSwitchHtml()}
          <div class="topbar-actions">
            ${dataSourceBadgeHtml()}
            ${opts.topbarActions || ''}
            <button class="btn btn-ghost btn-sm" id="ae-chpwd">改密</button>
            <button class="btn btn-ghost btn-sm" id="ae-logout">退出</button>
          </div>
        </header>
        <div class="content ${opts.flush ? 'flush' : ''}" id="page-content"></div>
      </div>`;

    document.title = pageTitle + ' · AI 测试与评估平台';

    // 导航栏自由伸缩：展开 260px / 折叠 72px，localStorage 跨页持久化
    if (localStorage.getItem('ae_sidebar_fold') === '1') root.classList.add('folded');
    root.querySelector('#ae-fold').onclick = () => {
      const folded = root.classList.toggle('folded');
      localStorage.setItem('ae_sidebar_fold', folded ? '1' : '0');
    };

    root.querySelectorAll('.mode-switch .mode-opt').forEach(b => { b.onclick = () => setMode(b.dataset.mode); });
    root.querySelector('#ae-chpwd').onclick = changePassword;
    root.querySelector('#ae-logout').onclick = () => {
      dialog({
        title: '退出登录？',
        body: '进行中的任务<strong>不会</strong>停止。',
        okText: '退出', okClass: 'btn-sign', cancelText: '返回',
        onOk: () => { location.href = 'login.html'; }
      });
    };
    return document.getElementById('page-content');
  }

  /* 权限守卫：单角色全员同权，直通（保留接口以兼容各页调用） */
  function guard() { return true; }

  /* ─── 发起评测抽屉（字段 = 确认卡 = POST /api/tasks） ─────── */
  function runConfigFoldHtml(prefix) {
    return `
      <div class="run-fold" id="${prefix}-runfold">
        <div class="run-fold-head" data-fold>运行配置（默认值）<span class="small tertiary">sample 1000 · 并发 4 · 超时 60s · 重试 1 · T=0 · 1024 tokens</span><svg class="chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="m6 9 6 6 6-6"/></svg></div>
        <div class="run-fold-body">
          <div class="form-row-3">
            <div class="field"><span class="field-label">sample_size</span><input class="input num" value="1000" type="number"></div>
            <div class="field"><span class="field-label">concurrency</span><input class="input num" value="4" type="number"></div>
            <div class="field"><span class="field-label">timeout_s</span><input class="input num" value="60" type="number"></div>
          </div>
          <div class="form-row-3">
            <div class="field"><span class="field-label">retry</span><input class="input num" value="1" type="number"></div>
            <div class="field"><span class="field-label">temperature</span><input class="input num" value="0" type="number" step="0.1"></div>
            <div class="field"><span class="field-label">max_tokens</span><input class="input num" value="1024" type="number"></div>
          </div>
          <div class="field"><span class="field-label">max_usd（单任务预算，默认 ${DB.settings.default_max_usd}）</span><input class="input num" value="${DB.settings.default_max_usd}" type="number" step="0.5" min="0">
            <span class="field-hint">累计 usage 超限即停并返回 BUDGET_EXCEEDED（F-CM-06）</span></div>
          <div class="field"><span class="field-label">system_prompt（可选）</span><input class="input" placeholder="留空则不注入"></div>
        </div>
      </div>`;
  }
  function bindFold(el) {
    el.querySelectorAll('[data-fold]').forEach(h => {
      h.onclick = () => h.parentElement.classList.toggle('open');
    });
  }
  function stressFieldsHtml(prefix) {
    return `
      <div class="switch-row" style="border-top:1px solid var(--border-subtle);margin-top:4px;padding-top:14px">
        <div><div style="font-weight:500">质量成功后自动压测</div><div class="field-hint">with_stress：同一 endpoint 先评后压</div></div>
        <label class="switch"><input type="checkbox" id="${prefix}-ws"><span class="track"></span></label>
      </div>
      <div id="${prefix}-stress" style="display:none">
        <div class="form-row-3">
          <div class="field"><span class="field-label">env <i class="req">*</i></span>
            <select class="select" id="${prefix}-env"><option>dev</option><option selected>test</option><option>staging</option><option>prod</option></select></div>
          <div class="field"><span class="field-label">qps <i class="req">*</i></span><input class="input num" id="${prefix}-qps" value="10" type="number"></div>
          <div class="field"><span class="field-label">duration_s <i class="req">*</i></span><input class="input num" id="${prefix}-dur" value="120" type="number"></div>
        </div>
        <div class="field"><span class="field-label">sla_p99_ms（可选，不填不出「是否达标」）</span><input class="input num" id="${prefix}-sla" placeholder="如 1500" type="number"></div>
        <div class="field-hint" id="${prefix}-prod-note" style="display:none;color:var(--accent-warning)">env=prod：压测入队前需会签（会签人：${esc((DB.settings.prod_approvers || []).join('、') || '待 API 返回') }）</div>
      </div>`;
  }
  function bindStressFields(el, prefix) {
    const ws = el.querySelector('#' + prefix + '-ws');
    const box = el.querySelector('#' + prefix + '-stress');
    ws.onchange = () => { box.style.display = ws.checked ? '' : 'none'; };
    const env = el.querySelector('#' + prefix + '-env');
    const note = el.querySelector('#' + prefix + '-prod-note');
    env.onchange = () => { note.style.display = env.value === 'prod' ? '' : 'none'; };
  }

  return {
    DB, MOCK_SEED, ROLES, STATUS, KIND, ERR_TEXT,
    getRole, setRole, getUser, canWrite, isAdmin,
    MODES, getMode, setMode, modeMatch, getDataMode,
    esc, relTime, statusBadge, kindTag, agentModel,
    toast, toastErr, dialog, modal, drawer, changePassword,
    renderShell, guard,
    runConfigFoldHtml, bindFold, stressFieldsHtml, bindStressFields
  };
})();
