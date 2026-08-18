<template>
  <div class="cases-workbench">
    <div class="ft-layout">
      <!-- 左侧：目录树侧边栏 -->
      <div class="ft-sidebar">
        <div class="ft-header">
          <div class="row-between mb8">
            <span style="font-weight: 600; font-size: 13px">用例集目录</span>
            <button class="btn btn-secondary btn-sm" style="font-size: 11px" @click="handleCreateCaseSet">+ 新建集</button>
          </div>
          <input v-model="treeSearch" class="input" placeholder="搜索用例集..." style="height: 30px; font-size: 12px" />
        </div>

        <div class="ft-tree">
          <div v-for="folder in filteredFolders" :key="folder.id">
            <div class="ft-node folder" @click="folder.open = !folder.open">
              <span class="ft-icon">{{ folder.open ? '▾' : '▸' }}</span>
              <span>📁 {{ folder.name }}</span>
              <span class="ft-badge">{{ folder.items.length }}</span>
            </div>

            <div v-if="folder.open" class="ft-folder-child">
              <div
                v-for="item in folder.items"
                :key="item.id"
                class="ft-node"
                :class="{ active: activeSetId === item.id }"
                @click="selectCaseSet(item.id)"
              >
                <span class="ft-icon">📋</span>
                <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ item.name }}</span>
                <span
                  class="badge"
                  :class="item.status === 'confirmed' ? 'badge-succeeded' : item.status === 'cancelled' ? 'badge-cancelled' : 'badge-awaiting_case_confirm'"
                  style="font-size: 10px; padding: 1px 5px; margin-left: auto"
                >
                  {{ item.status === 'confirmed' ? '已入库' : item.status === 'cancelled' ? '已废弃' : '待确认' }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：用例数据表格工作台 -->
      <div v-if="currentSet" class="workspace-main">
        <!-- 1. 顶部工具栏 -->
        <div class="ws-toolbar">
          <div class="row" style="gap: 8px; align-items: center">
            <span style="font-weight: 700; font-size: 15px">{{ currentSet.name }}</span>
            <span class="tag-soft">生成 <b class="num mono">{{ currentSet.generated_count }}</b> 条</span>
            <span class="tag-soft" style="color: var(--accent-warning); border-color: #FDE68A">
              {{ currentSet.status === 'confirmed' ? '✓ 已入库' : currentSet.status === 'cancelled' ? '已废弃' : `72h 倒计时: 剩 ${Math.floor(currentSet.expires_in_h || 70)}h` }}
            </span>
          </div>

          <div class="row" style="gap: 8px; align-items: center; margin-left: auto">
            <button class="btn btn-secondary btn-sm" @click="addCase">+ 新增用例</button>
            <button class="btn btn-ai btn-sm" @click="handleAiGenCases">✨ AI 生成用例集</button>
            <button class="btn btn-ai btn-sm" @click="handleAiFillCase">AI 补全断言</button>
            <button class="btn btn-secondary btn-sm" @click="exportXlsx">导出 xlsx</button>
            <button class="btn btn-secondary btn-sm" @click="exportXmind">导出 xmind</button>
            <button
              v-if="currentSet.status !== 'confirmed'"
              class="btn btn-sign btn-sm"
              @click="confirmAllCases"
            >
              确认入库
            </button>
          </div>
        </div>

        <!-- 2. 策略分布与 AI 自检横幅 -->
        <div class="strategy-banner">
          <span class="tertiary" style="font-weight: 600">策略覆盖分布:</span>
          <div class="row wrap" style="gap: 6px">
            <span v-for="st in strategyCounts" :key="st.name" class="tag-soft" style="font-size: 11px">
              {{ st.name }} <b class="num mono">{{ st.count }}</b>
            </span>
          </div>
          <span class="grow"></span>
          <span v-if="currentSet.checks?.length" class="badge badge-failed" style="font-size: 11px">
            ⚠ 自检: {{ currentSet.checks.map(c => c.message).join('; ') }}
          </span>
          <span v-else class="st-ok small">✓ 策略自检通过</span>
        </div>

        <!-- 3. 用例表格数据网格 -->
        <div class="ws-grid-container">
          <table class="ds-table">
            <thead>
              <tr>
                <th style="width: 40px"><input type="checkbox" checked /></th>
                <th style="width: 75px">策略</th>
                <th style="width: 65px">级别</th>
                <th style="min-width: 90px">模块</th>
                <th style="min-width: 180px">用例名称 <i class="req" style="color: var(--accent-error)">*</i></th>
                <th style="min-width: 220px">预期结果 <i class="req" style="color: var(--accent-error)">*</i></th>
                <th style="min-width: 140px">前置条件</th>
                <th style="width: 90px">映射状态</th>
                <th style="width: 75px; text-align: right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(c, idx) in cases" :key="c.id">
                <td><input type="checkbox" :checked="!c.pending" /></td>
                <td class="cell-edit">
                  <span class="kind-tag" :class="getStrategyTagClass(c.strategy)">{{ c.strategy }}</span>
                </td>
                <td class="cell-edit">
                  <span class="prio" :class="`prio-${c.priority}`">{{ c.priority }}</span>
                </td>
                <td class="cell-edit" @click="editCell(c, 'module')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'module'"
                    v-model="c.module"
                    class="cell-input"
                    autofocus
                    @blur="editingCell = null"
                    @keyup.enter="editingCell = null"
                  />
                  <span v-else>{{ c.module }}</span>
                </td>
                <td class="cell-edit" @click="editCell(c, 'name')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'name'"
                    v-model="c.name"
                    class="cell-input"
                    autofocus
                    @blur="editingCell = null"
                    @keyup.enter="editingCell = null"
                  />
                  <span v-else style="font-weight: 500">{{ c.name }}</span>
                </td>
                <td class="cell-edit" @click="editCell(c, 'expected')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'expected'"
                    v-model="c.expected"
                    class="cell-input"
                    autofocus
                    @blur="editingCell = null"
                    @keyup.enter="editingCell = null"
                  />
                  <span v-else>{{ c.expected }}</span>
                </td>
                <td class="cell-edit" @click="editCell(c, 'precondition')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'precondition'"
                    v-model="c.precondition"
                    class="cell-input"
                    autofocus
                    @blur="editingCell = null"
                    @keyup.enter="editingCell = null"
                  />
                  <span v-else class="small tertiary">{{ c.precondition || '无' }}</span>
                </td>
                <td>
                  <span v-if="c.mapped" class="badge badge-succeeded">✓ 已映射</span>
                  <span v-else class="badge badge-awaiting_case_confirm">待补全</span>
                </td>
                <td style="text-align: right">
                  <button class="link-btn danger" @click="deleteCase(idx)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 4. 底部状态栏与批量映射 -->
        <div class="ws-status-bar">
          <span>已选 <b class="num mono">{{ adoptedCount }}</b> / {{ cases.length }} 条</span>
          <select v-model="mapTarget" class="select" style="height: 28px; padding: 2px 24px 2px 8px; font-size: 12px">
            <option value="dataset">映射至基准数据集 · smoke-20</option>
            <option value="gold_qa">映射至黄金 QA · qa-v1</option>
          </select>
          <button class="btn btn-secondary btn-sm" @click="handleBatchMap">批量执行映射</button>
          <span class="grow"></span>
          <span class="tertiary">采纳率: <b class="num mono">{{ adoptionRate }}%</b></span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useMessage } from 'naive-ui'

const message = useMessage()

const treeSearch = ref('')
const activeSetId = ref('cs-pay')
const mapTarget = ref('dataset')

const caseSets = ref([
  {
    id: 'cs-pay',
    name: 'PRD-支付',
    status: 'generated',
    generated_count: 40,
    confirmed_count: 0,
    expires_in_h: 70.2,
    checks: [
      { level: 'error', code: 'no_core_positive', message: '无核心正向用例' },
      { level: 'error', code: 'missing_constraint_negative', message: '缺约束反向用例' },
    ],
  },
  { id: 'cs-login', name: 'PRD-登录', status: 'confirmed', generated_count: 32, confirmed_count: 26, expires_in_h: 0, checks: [] },
  { id: 'cs-coupon', name: 'PRD-优惠券', status: 'cancelled', generated_count: 45, confirmed_count: 0, expires_in_h: 0, checks: [] },
])

const currentSet = computed(() => caseSets.value.find(s => s.id === activeSetId.value) || caseSets.value[0])

const folders = ref([
  {
    id: 'f-cases-core',
    name: '业务需求生成集',
    open: true,
    items: [
      { id: 'cs-pay', name: 'PRD-支付', status: 'generated' },
      { id: 'cs-login', name: 'PRD-登录', status: 'confirmed' },
      { id: 'cs-coupon', name: 'PRD-优惠券', status: 'cancelled' },
    ],
  },
])

const filteredFolders = computed(() => {
  const kw = treeSearch.value.trim().toLowerCase()
  if (!kw) return folders.value
  return folders.value.map(f => ({
    ...f,
    items: f.items.filter(it => it.name.toLowerCase().includes(kw)),
  })).filter(f => f.items.length > 0)
})

const cases = ref([
  { id: 'c-001', strategy: '正向', priority: 'P0', module: '登录', name: '正确账密登录成功', expected: '进入工作台首页', mapped: true, pending: false, precondition: '账号状态正常' },
  { id: 'c-002', strategy: '正向', priority: 'P0', module: '支付', name: '余额充足时支付成功', expected: '订单状态变为已支付', mapped: true, pending: false, precondition: '账户余额 ≥ 订单金额' },
  { id: 'c-003', strategy: '反向', priority: 'P1', module: '登录', name: '错误密码登录', expected: '提示用户名或密码错误', mapped: false, pending: true, precondition: '无' },
  { id: 'c-004', strategy: '反向', priority: 'P1', module: '支付', name: '余额不足支付', expected: '返回余额不足错误码', mapped: true, pending: false, precondition: '账户余额 < 订单金额' },
  { id: 'c-005', strategy: '边界', priority: 'P1', module: '支付', name: '支付金额为 0.01 元', expected: '允许最小金额支付', mapped: true, pending: false, precondition: '收银台已加载' },
  { id: 'c-006', strategy: '边界', priority: 'P2', module: '支付', name: '支付金额达单笔上限 5 万元', expected: '按限额规则拦截并弹窗提示', mapped: false, pending: true, precondition: '单笔限额已配置' },
  { id: 'c-007', strategy: '状态', priority: 'P1', module: '订单', name: '重复提交支付请求', expected: '幂等返回同一订单号', mapped: true, pending: false, precondition: '订单已创建' },
  { id: 'c-008', strategy: '场景', priority: 'P2', module: '支付', name: '支付中断网重试', expected: '网络恢复后可查询最终状态', mapped: true, pending: false, precondition: '弱网模拟环境' },
])

const strategyCounts = computed(() => {
  const strats = ['正向', '反向', '边界', '状态', '场景']
  return strats.map(s => ({
    name: s,
    count: cases.value.filter(c => c.strategy === s).length,
  }))
})

const adoptedCount = computed(() => cases.value.filter(c => !c.pending).length)
const adoptionRate = computed(() => Math.round((adoptedCount.value / (cases.value.length || 1)) * 100))

const editingCell = ref<{ row: any; field: string } | null>(null)
function editCell(row: any, field: string) {
  editingCell.value = { row, field }
}

function selectCaseSet(id: string) {
  activeSetId.value = id
}

function getStrategyTagClass(st: string) {
  switch (st) {
    case '正向': return 'kind-testcase'
    case '反向': return 'kind-stress'
    case '边界': return 'kind-profiles'
    case '状态': return 'kind-benchmark'
    default: return 'kind-rag'
  }
}

function addCase() {
  cases.value.push({
    id: `c-${Date.now()}`,
    strategy: '正向',
    priority: 'P1',
    module: '通用',
    name: '新建业务测试用例',
    expected: '断言结果符合预期',
    mapped: false,
    pending: false,
    precondition: '无',
  })
  message.success('已添加新用例')
}

function deleteCase(idx: number) {
  cases.value.splice(idx, 1)
  message.success('已删除用例')
}

function handleCreateCaseSet() {
  message.info('请在智能体对话中上传 PRD 文档，由 Agent 自动拆解生成')
}

function handleAiGenCases() {
  message.info('AI 正在依据 PRD 规范补充覆盖正向、约束反向与异常用例...')
  setTimeout(() => {
    cases.value.unshift({
      id: `c-ai-${Date.now()}`,
      strategy: '反向',
      priority: 'P0',
      module: '支付约束',
      name: '非白名单商户调用支付接口',
      expected: '系统拦截并记录 WHITELIST 审计日志',
      mapped: true,
      pending: false,
      precondition: '商户号未入白名单',
    })
    if (currentSet.value) {
      currentSet.value.checks = []
    }
    message.success('AI 已补全约束反向用例，规则自检通过！')
  }, 1000)
}

function handleAiFillCase() {
  message.info('AI 正在自动推导未填写的前置条件与断言表达式...')
  setTimeout(() => {
    cases.value.forEach(c => {
      if (c.precondition === '无') c.precondition = '前置服务已就绪'
    })
    message.success('已补全用例前置与断言')
  }, 800)
}

function confirmAllCases() {
  if (currentSet.value) {
    currentSet.value.status = 'confirmed'
    message.success('用例集已正式确认入库！')
  }
}

function handleBatchMap() {
  cases.value.forEach(c => { c.mapped = true; c.pending = false })
  message.success(`已批量将 ${cases.value.length} 条用例映射至 ${mapTarget.value === 'dataset' ? '基准数据集' : '黄金问答集'}`)
}

function exportXlsx() {
  message.success('用例集已成功导出为 Excel (.xlsx)')
}

function exportXmind() {
  message.success('用例集已成功导出为脑图 (.xmind)')
}
</script>

<style scoped>
.cases-workbench {
  height: calc(100vh - var(--topbar-h) - 20px);
}
.ft-layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  height: 100%;
  background: var(--bg-main);
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
}
.ft-sidebar {
  border-right: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  display: flex;
  flex-direction: column;
  height: 100%;
}
.ft-header {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-subtle);
}
.ft-tree {
  flex: 1;
  overflow-y: auto;
  padding: 10px 8px;
}
.ft-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.12s ease;
}
.ft-node:hover {
  background: rgba(17, 24, 39, 0.04);
}
.ft-node.active {
  background: color-mix(in srgb, var(--accent-ai) 12%, var(--bg-main));
  color: var(--accent-ai);
  font-weight: 600;
}
.ft-node.folder {
  font-weight: 600;
  color: var(--text-secondary);
}
.ft-folder-child {
  padding-left: 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ft-icon {
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 16px;
}
.ft-badge {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-tertiary);
}
.workspace-main {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--bg-main);
}
.ws-toolbar {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.strategy-banner {
  padding: 8px 16px;
  background: color-mix(in srgb, var(--accent-ai) 4%, var(--bg-main));
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 12.5px;
}
.ws-grid-container {
  flex: 1;
  overflow: auto;
}
.ws-status-bar {
  padding: 8px 16px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 16px;
  font-family: var(--font-mono);
  font-size: 12px;
  background: var(--bg-elevated);
  color: var(--text-secondary);
}
.prio {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
}
.prio-P0 { background: #FEE2E2; color: #DC2626; }
.prio-P1 { background: #FEF3C7; color: #D97706; }
.prio-P2 { background: #E0E7FF; color: #4F46E5; }
.prio-P3 { background: #F3F4F6; color: #6B7280; }
.st-ok {
  color: var(--accent-success);
}
</style>
