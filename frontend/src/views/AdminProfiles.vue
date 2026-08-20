<template>
  <div class="profiles-page">
    <!-- 4 Tab 架构（API V1.3 §3.6：协议档 / MCP 工具只读 / 技能受控说明 / 运行时治理） -->
    <div class="row" style="gap: 8px">
      <button
        v-for="t in tabs"
        :key="t.key"
        class="profile-tab-btn"
        :class="{ active: activeTab === t.key }"
        @click="activeTab = t.key"
      >
        {{ t.label }}
      </button>
    </div>

    <template v-if="activeTab === 'profiles'">
    <!-- 顶部指定 Agent 后端设置 -->
    <div class="panel mb16">
      <div class="panel-title">智能体后台模型配置 (Agent Backend)</div>
      <div class="row" style="gap: 16px">
        <div style="font-size: 13px; color: var(--text-secondary)">
          指定系统唯一的 Agent 决策后台协议档：
        </div>
        <n-select
          v-model:value="selectedAgentProfileId"
          style="width: 260px"
          :options="agentProfileOptions"
          @update:value="handleUpdateAgentProfile"
        />
        <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">
          (保存即刻全局生效)
        </span>
      </div>
    </div>

    <!-- 协议档列表 -->
    <div class="panel">
      <div class="panel-title">
        <div class="row" style="gap: 12px">
          <span>大模型协议档与供应商管理</span>
          <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">({{ profiles.length }} 个模型)</span>

          <!-- 视图模式切换器 -->
          <div class="view-mode-toggle">
            <button
              class="toggle-btn"
              :class="{ active: viewMode === 'cards' }"
              @click="viewMode = 'cards'"
            >
              📇 供应商卡片视图
            </button>
            <button
              class="toggle-btn"
              :class="{ active: viewMode === 'table' }"
              @click="viewMode = 'table'"
            >
              📑 详细表格视图
            </button>
          </div>
        </div>

        <div class="row">
          <button class="btn btn-primary btn-sm" @click="openModal(null)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            <span>新增协议档</span>
          </button>

          <button class="btn btn-secondary btn-sm" :disabled="loading" @click="loadProfiles">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="23 4 23 10 17 10"></polyline>
              <polyline points="1 20 1 14 7 14"></polyline>
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
            </svg>
            <span>刷新</span>
          </button>
        </div>
      </div>

      <!-- 模式 1：供应商分类多卡片视图 -->
      <div v-if="viewMode === 'cards'" class="vendor-cards-container">
        <div
          v-for="group in vendorGroups"
          :key="group.key"
          class="vendor-group-card"
        >
          <div class="vendor-group-header">
            <div class="vendor-info">
              <div class="vendor-title-row">
                <span class="vendor-badge">{{ group.icon }}</span>
                <span class="vendor-name">{{ group.name }}</span>
                <span class="vendor-count-badge">{{ group.profiles.length }} 个模型</span>
              </div>
              <div class="vendor-url mono">{{ group.base_url }}</div>
            </div>
            <div class="vendor-actions">
              <button
                class="btn btn-secondary btn-xs"
                @click="openModalWithVendor(group)"
              >
                + 添加此供应商模型
              </button>
            </div>
          </div>

          <!-- 模型卡片列表 -->
          <div class="vendor-models-grid">
            <div
              v-for="p in group.profiles"
              :key="p.id"
              class="model-chip-card"
              :class="{ 'is-agent-core': p.id === selectedAgentProfileId }"
            >
              <div class="model-chip-top">
                <div class="model-chip-title-wrap">
                  <span class="model-chip-name">{{ p.name }}</span>
                  <span v-if="p.id === selectedAgentProfileId" class="tag-soft agent-core-tag">★ Agent 核心</span>
                </div>
                <!-- 探活胶囊 -->
                <span
                  v-if="pingStates[p.id]"
                  class="ping-badge"
                  :class="pingStates[p.id].ok ? 'ok' : 'err'"
                  title="点击重新探活"
                  @click="handlePing(p)"
                >
                  {{ pingStates[p.id].ok ? `● 正常 (${pingStates[p.id].latencyMs ?? '—'}ms)` : '✕ 连接失败' }}
                </span>
                <button v-else class="link-btn small" :disabled="pingingId === p.id" @click="handlePing(p)">
                  {{ pingingId === p.id ? '探活中…' : '探活' }}
                </button>
              </div>

              <div class="model-chip-meta">
                <span class="mono model-id-tag">{{ p.model }}</span>
                <span class="mono protocol-tag">{{ p.protocol }}</span>
                <span class="mono window-tag" title="上下文窗口容量">{{ formatContextWindow(p.context_window) }}</span>
              </div>

              <div class="model-chip-bottom">
                <div class="row" style="gap: 4px; flex-wrap: wrap">
                  <span v-if="p.usages?.includes('target')" class="kind-tag kind-benchmark">被测</span>
                  <span v-if="p.usages?.includes('judge')" class="kind-tag kind-cases">裁判</span>
                  <span v-if="p.usages?.includes('agent')" class="kind-tag kind-rag">Agent</span>
                </div>
                <div class="row" style="gap: 6px">
                  <button class="link-btn small" @click="openModal(p)">编辑</button>
                  <button
                    class="link-btn danger small"
                    :disabled="p.id === selectedAgentProfileId"
                    :title="p.id === selectedAgentProfileId ? '当前档已被指定为 Agent 后端，禁止删除' : ''"
                    @click="handleDelete(p)"
                  >
                    删除
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="profiles.length === 0" class="empty-state-wrap">
          <EmptyState title="暂无模型协议档" description="点击右上角新增 OpenAI / Anthropic / Xiaomi Mimo 协议档">
            <template #action>
              <button class="btn btn-primary btn-sm" @click="openModal(null)">新增协议档</button>
            </template>
          </EmptyState>
        </div>
      </div>

      <!-- 模式 2：详细表格视图 -->
      <table v-else class="ds-table">
        <thead>
          <tr>
            <th>协议档名称</th>
            <th style="width: 160px">协议类型</th>
            <th style="width: 140px">模型标识</th>
            <th style="width: 100px">上下文窗口</th>
            <th>Base URL</th>
            <th style="width: 140px">用途标签</th>
            <!-- P2 连通性探活列（对齐原型 admin-profiles.html：行内 ping-badge） -->
            <th style="width: 130px">探活</th>
            <th style="width: 200px; text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in profiles" :key="p.id">
            <td style="font-weight: 600; font-size: 14px">
              <span class="row" style="gap: 6px">
                <span>{{ p.name }}</span>
                <!-- P4 名称徽标对齐原型「★ Agent 核心驱动」 -->
                <span v-if="p.id === selectedAgentProfileId" class="tag-soft agent-core-tag">★ Agent 核心驱动</span>
              </span>
            </td>
            <td>
              <span class="mono" style="font-size: 12px">{{ p.protocol }}</span>
            </td>
            <td>
              <span class="mono" style="font-size: 12px; font-weight: 500">{{ p.model }}</span>
            </td>
            <td>
              <span class="mono window-tag">{{ formatContextWindow(p.context_window) }}</span>
            </td>
            <td>
              <span class="mono" style="font-size: 11.5px; color: var(--text-secondary)">{{ p.base_url }}</span>
            </td>
            <td>
              <div class="row" style="gap: 4px; flex-wrap: wrap">
                <span v-if="p.usages?.includes('target')" class="kind-tag kind-benchmark">被测</span>
                <span v-if="p.usages?.includes('judge')" class="kind-tag kind-cases">裁判</span>
                <span v-if="p.usages?.includes('agent')" class="kind-tag kind-rag">Agent</span>
              </div>
            </td>
            <td>
              <!-- P2 探活胶囊：点击原位刷新（复用 api.profiles.check），不弹窗 -->
              <span
                v-if="pingStates[p.id]"
                class="ping-badge"
                :class="pingStates[p.id].ok ? 'ok' : 'err'"
                title="点击重新探活"
                @click="handlePing(p)"
              >
                {{ pingStates[p.id].ok ? `● 正常 (${pingStates[p.id].latencyMs ?? '—'}ms)` : '✕ 连接失败' }}
              </span>
              <button v-else class="link-btn" :disabled="pingingId === p.id" @click="handlePing(p)">
                {{ pingingId === p.id ? '探活中…' : '探活' }}
              </button>
            </td>
            <td style="text-align: right">
              <div class="row" style="justify-content: flex-end; gap: 4px">
                <button class="link-btn" :disabled="checkingId === p.id" @click="handleCheck(p)">
                  {{ checkingId === p.id ? '检查中...' : '连通详情' }}
                </button>
                <button class="link-btn" @click="openModal(p)">编辑</button>
                <button
                  class="link-btn danger"
                  :disabled="p.id === selectedAgentProfileId"
                  :title="p.id === selectedAgentProfileId ? '当前档已被指定为 Agent 后端，禁止删除' : ''"
                  @click="handleDelete(p)"
                >
                  删除
                </button>
              </div>
            </td>
          </tr>

          <tr v-if="profiles.length === 0">
            <td colspan="7">
              <EmptyState title="暂无模型协议档" description="点击右上角新增 OpenAI / Anthropic 协议档">
                <template #action>
                  <button class="btn btn-primary btn-sm" @click="openModal(null)">新增协议档</button>
                </template>
              </EmptyState>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    </template>

    <!-- Tab 2：MCP 工具中心（V1.0 只读；外部 MCP Server 管理能力未启用） -->
    <template v-else-if="activeTab === 'mcp'">
      <div class="panel mb16">
        <div class="row-between mb12">
          <div>
            <span style="font-weight: 700; font-size: 15px">MCP (Model Context Protocol) 工具中心</span>
            <div class="small tertiary" style="margin-top: 2px">
              Agent 作为 MCP Host 运行时，通过短工具完成资产发现与建单；禁止挂载长耗时阻塞工具。
            </div>
          </div>
          <button class="btn btn-sign btn-sm" disabled title="V1.0 不接入外部 MCP Server（API §3.6.1）">
            + 接入外部 MCP Server（能力未启用）
          </button>
        </div>

        <div class="panel" style="background: var(--bg-elevated); padding: 14px 16px">
          <div class="row-between mb12">
            <span class="panel-title" style="margin: 0">内置受控短工具清单</span>
            <span class="small tertiary">共 {{ mcpTools.length }} 个受控工具 · 严格沙箱校验 · 只读</span>
          </div>
          <table class="ds-table">
            <thead>
              <tr>
                <th style="width: 180px">工具名称</th>
                <th>职责说明</th>
                <th style="width: 100px">权限级别</th>
                <th style="width: 100px">来源</th>
                <th style="width: 90px">状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in mcpTools" :key="t.name">
                <td class="mono" style="font-weight: 600; color: var(--c-profiles)">{{ t.name }}</td>
                <td class="small">{{ t.desc }}</td>
                <td>
                  <span class="tag-soft" :style="t.permission === 'write' ? { color: 'var(--accent-warning)' } : {}">
                    {{ t.permission === 'write' ? 'WRITE' : 'READ' }}
                  </span>
                </td>
                <td class="small tertiary mono">builtin</td>
                <td>
                  <span class="badge badge-succeeded">已启用</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="small tertiary" style="margin-top: 12px; line-height: 1.6">
          外部 MCP Server 的接入、探活、解绑与动态发现在 V1.0 不开放（API §3.6.1）；平台仅使用上表内置短工具。
        </div>
      </div>
    </template>

    <!-- Tab 3：Agent 技能编排（V1.0 受控边界：固定系统提示词，不回显、不可自定义） -->
    <template v-else-if="activeTab === 'skills'">
      <div class="panel mb16">
        <div class="row-between mb12">
          <div>
            <span style="font-weight: 700; font-size: 15px">Agent 技能编排 (Skills & Prompts)</span>
            <div class="small tertiary" style="margin-top: 2px">
              智能体在基准对比、RAG 评估、用例生成与压测场景下的 4 大核心内置技能（PRD 5.5.2）。
            </div>
          </div>
          <button class="btn btn-sign btn-sm" disabled title="V1.0 使用服务端固定系统提示词，不开放自定义技能（API §3.6.2）">
            + 创建自定义技能（能力未启用）
          </button>
        </div>

        <div class="skill-grid">
          <div v-for="s in builtinSkills" :key="s.id" class="skill-card">
            <div class="skill-head">
              <div class="row" style="gap: 8px; align-items: center">
                <span style="font-size: 20px">{{ s.icon }}</span>
                <div>
                  <span class="skill-title">{{ s.name }}</span>
                  <div class="small tertiary mono" style="font-size: 10px">{{ s.id }}</div>
                </div>
              </div>
              <span class="tag-soft">内置核心</span>
            </div>
            <div class="small" style="color: var(--text-secondary); line-height: 1.5">{{ s.desc }}</div>
            <div class="row wrap" style="gap: 6px; margin-top: auto">
              <span class="small tertiary">依赖工具:</span>
              <span v-for="tool in s.tools" :key="tool" class="tag-soft mono" style="font-size: 10px">{{ tool }}</span>
            </div>
          </div>
        </div>

        <div class="small tertiary" style="margin-top: 14px; line-height: 1.6">
          V1.0 使用服务端固定系统提示词与固定短工具绑定，System Prompt 不回显、不可编辑（API §3.6.2）；
          如后续批准可配置技能，将另起 API 版本并补安全审计、版本化与回滚契约。
        </div>
      </div>
    </template>

    <!-- Tab 4：Agent 运行时与主机治理（写入 /api/admin/settings.runtime，带审计） -->
    <template v-else>
      <div class="panel mb16" style="padding: 16px 20px">
        <div class="panel-title mb8">WebSocket 智能体会话与连接参数</div>
        <div class="row wrap mb16" style="gap: 16px">
          <div class="field" style="width: 220px">
            <span class="field-label">心跳 Ping 间隔 (秒)</span>
            <n-input-number v-model:value="runtimeForm.ws_ping_s" :min="5" :max="300" style="width: 100%" />
          </div>
          <div class="field" style="width: 220px">
            <span class="field-label">连接超时断开 (秒)</span>
            <n-input-number v-model:value="runtimeForm.ws_timeout_s" :min="5" :max="300" style="width: 100%" />
          </div>
          <div class="field" style="width: 220px">
            <span class="field-label">WS Ticket 授权 TTL (秒)</span>
            <n-input-number :value="300" disabled style="width: 100%" />
            <span class="field-hint">一次性授权票据，固定 5 分钟（PRD 5.1）</span>
          </div>
        </div>

        <div class="panel-title mb8">会话占槽与并发互斥规则</div>
        <p class="small tertiary mb12">
          当前会话有进行中任务（含压测子任务）时，主按钮自动禁用，完成后方可开启新长任务（PRD 3.4）。
        </p>
        <div class="field mb16">
          <label class="row" style="gap: 8px; cursor: pointer">
            <n-switch v-model:value="runtimeForm.strict_session_slot" />
            <span style="font-weight: 600">严格会话占槽互斥：压测子任务执行期间保持槽位独占</span>
          </label>
        </div>

        <button class="btn btn-sign btn-sm" :disabled="runtimeSaving" @click="saveRuntime">
          {{ runtimeSaving ? '保存中…' : '保存运行时参数' }}
        </button>
      </div>
    </template>

    <!-- 弹窗 -->
    <ProfileModal
      v-model:show="showModal"
      :profile="selectedProfile"
      :initial-data="modalInitialData"
      @success="loadProfiles"
    />

    <CheckResultModal
      v-model:show="showCheckModal"
      :result="checkResult"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMessage, useDialog, NSelect, NInputNumber, NSwitch } from 'naive-ui'
import { api } from '../api/http'
import type { Profile, ProfileCheckOut, McpTool } from '../api/types'
import EmptyState from '../components/common/EmptyState.vue'
import ProfileModal from '../components/modals/ProfileModal.vue'
import CheckResultModal from '../components/modals/CheckResultModal.vue'

const message = useMessage()
const dialog = useDialog()

// 4 Tab 架构（API V1.3 §3.6）：profiles / mcp / skills / runtime
type TabKey = 'profiles' | 'mcp' | 'skills' | 'runtime'
const tabs: { key: TabKey; label: string }[] = [
  { key: 'profiles', label: '协议档治理' },
  { key: 'mcp', label: '🛠 MCP 服务器与工具清单' },
  { key: 'skills', label: '🧠 Agent 技能与 Prompt 编排' },
  { key: 'runtime', label: '⚙ 运行时与主机治理' },
]
const activeTab = ref<TabKey>('profiles')

// MCP 内置短工具清单（只读，来自 /api/mcp/tools）
const mcpTools = ref<McpTool[]>([])

// PRD 5.5.2 的 4 大核心内置技能（V1.0 受控展示，不回显 System Prompt）
const builtinSkills = [
  {
    id: 'skill-benchmark',
    icon: '📊',
    name: '基准对比',
    desc: '自动识别被测模型数量、推荐标准评测集并构建先评后压 TaskSpec。',
    tools: ['model.list', 'dataset.list', 'task.create'],
  },
  {
    id: 'skill-rag',
    icon: '🔍',
    name: 'RAG 质量评估',
    desc: '自动装载知识库切块与黄金 QA，评测 LightRAG 4 模式检索表现。',
    tools: ['kb.list', 'task.create', 'report.get'],
  },
  {
    id: 'skill-testcase',
    icon: '🧪',
    name: 'PRD 用例生成',
    desc: '按 6 大策略精细配比（40/25/15/10/5/5）提炼测试用例。',
    tools: ['dataset.list', 'task.create'],
  },
  {
    id: 'skill-stress',
    icon: '🚀',
    name: '共享容量压测',
    desc: '继承父任务 endpoint 与抽样问答，定位 SLA 拐点与成本开销。',
    tools: ['dispatch.overview', 'task.create', 'task.cancel'],
  },
]

// 运行时治理表单（settings.runtime）
const runtimeForm = ref({ ws_ping_s: 15, ws_timeout_s: 45, strict_session_slot: true })
const runtimeSaving = ref(false)

// 视图模式：'cards' (供应商分类多卡片视图) | 'table' (详细表格视图)
const viewMode = ref<'cards' | 'table'>('cards')

const profiles = ref<Profile[]>([])
const loading = ref(false)
const selectedAgentProfileId = ref<string | null>(null)
// 最近一次成功保存的 Agent 协议档 ID，用于保存失败时回滚选择器
const lastSavedAgentProfileId = ref<string | null>(null)

const showModal = ref(false)
const selectedProfile = ref<Profile | null>(null)

const showCheckModal = ref(false)
const checkResult = ref<ProfileCheckOut | null>(null)
const checkingId = ref<string | null>(null)

// P2 行内探活状态：按协议档 id 记录最近一次探活结果（仅前端会话内缓存，不落库）
interface PingState {
  ok: boolean
  latencyMs: number | null
}
const pingStates = ref<Record<string, PingState>>({})
const pingingId = ref<string | null>(null)

const agentProfileOptions = computed(() =>
  profiles.value.map((p) => ({ label: `${p.name} (${p.model})`, value: p.id })),
)

interface VendorGroup {
  key: string
  name: string
  icon: string
  base_url: string
  protocol: any
  profiles: Profile[]
}

/** 智能归类供应商分组 */
const vendorGroups = computed<VendorGroup[]>(() => {
  const groups: Record<string, VendorGroup> = {}

  for (const p of profiles.value) {
    const url = (p.base_url || '').toLowerCase()
    const name = (p.name || '').toLowerCase()
    const model = (p.model || '').toLowerCase()

    let key = 'custom'
    let vName = '自定义端点 / 内部代理'
    let icon = '🌐'

    if (url.includes('nvidia') || name.includes('nvidia') || model.includes('nvidia')) {
      key = 'nvidia'
      vName = 'NVIDIA NIM'
      icon = '🟢'
    } else if (url.includes('xiaomimimo') || name.includes('mimo') || model.includes('mimo')) {
      key = 'mimo'
      vName = 'Xiaomi Mimo'
      icon = '⚡'
    } else if (url.includes('openai.com') || name.includes('openai') || model.startsWith('gpt-')) {
      key = 'openai'
      vName = 'OpenAI'
      icon = '🤖'
    } else if (url.includes('anthropic.com') || name.includes('claude') || model.startsWith('claude-')) {
      key = 'anthropic'
      vName = 'Anthropic Claude'
      icon = '🔮'
    } else if (url.includes('deepseek') || name.includes('deepseek') || model.includes('deepseek')) {
      key = 'deepseek'
      vName = 'DeepSeek'
      icon = '🐋'
    } else if (url.includes('siliconflow') || name.includes('silicon') || name.includes('硅基')) {
      key = 'siliconflow'
      vName = 'SiliconFlow (硅基流动)'
      icon = '⚡'
    } else if (url.includes('aliyuncs') || url.includes('dashscope') || name.includes('qwen') || model.includes('qwen')) {
      key = 'qwen'
      vName = 'Alibaba Qwen (通义千问)'
      icon = '☁️'
    } else if (url.includes('volces.com') || name.includes('doubao') || name.includes('火山') || name.includes('豆包')) {
      key = 'volcengine'
      vName = 'ByteDance Doubao (火山引擎)'
      icon = '🌋'
    } else if (url.includes('qianfan') || url.includes('baidubce') || name.includes('ernie') || name.includes('文心') || name.includes('千帆')) {
      key = 'qianfan'
      vName = 'Baidu Qianfan (百度千帆)'
      icon = '🐻'
    } else if (url.includes('hunyuan') || name.includes('混元')) {
      key = 'hunyuan'
      vName = 'Tencent Hunyuan (腾讯混元)'
      icon = '🐧'
    } else if (url.includes('groq') || name.includes('groq')) {
      key = 'groq'
      vName = 'Groq'
      icon = '⚡'
    } else if (url.includes('11434') || url.includes('ollama') || name.includes('ollama')) {
      key = 'ollama'
      vName = 'Ollama (本地私有)'
      icon = '🦙'
    } else if (url.includes('bigmodel.cn') || name.includes('glm') || model.includes('glm') || name.includes('智谱')) {
      key = 'zhipu'
      vName = 'Zhipu GLM (智谱清言)'
      icon = '🌟'
    } else if (url.includes('moonshot') || name.includes('kimi') || name.includes('moonshot') || name.includes('月之暗面')) {
      key = 'moonshot'
      vName = 'Moonshot (月之暗面)'
      icon = '🌙'
    } else if (url.includes('mistral') || name.includes('mistral')) {
      key = 'mistral'
      vName = 'Mistral AI'
      icon = '🌪️'
    } else if (url.includes('together') || name.includes('together')) {
      key = 'together'
      vName = 'Together AI'
      icon = '🤝'
    }

    if (!groups[key]) {
      groups[key] = {
        key,
        name: vName,
        icon,
        base_url: p.base_url,
        protocol: p.protocol,
        profiles: [],
      }
    }
    groups[key].profiles.push(p)
  }

  return Object.values(groups)
})

function formatContextWindow(tokens?: number): string {
  if (!tokens || tokens === 200000) return '200k'
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(0)}M`
  return `${(tokens / 1000).toFixed(0)}k`
}

const modalInitialData = ref<{ vendorKey?: string; base_url?: string; protocol?: any; name?: string } | null>(null)

function openModal(profile: Profile | null) {
  selectedProfile.value = profile
  modalInitialData.value = null
  showModal.value = true
}

function openModalWithVendor(group: VendorGroup) {
  selectedProfile.value = null
  modalInitialData.value = {
    vendorKey: group.key !== 'custom' ? group.key : undefined,
    base_url: group.base_url,
    protocol: group.protocol,
    name: group.name,
  }
  showModal.value = true
}

async function loadProfiles() {
  loading.value = true
  try {
    const [pList, settings, tools] = await Promise.all([
      api.profiles.list(),
      api.admin.getSettings(),
      api.mcp.tools(),
    ])
    profiles.value = pList
    // 仅以后端配置为准：未指定时不默认选中首个协议档，避免误导性「Agent 核心驱动」标记
    selectedAgentProfileId.value = settings.agent_profile_id || null
    lastSavedAgentProfileId.value = selectedAgentProfileId.value
    mcpTools.value = tools.items
    if (settings.runtime) runtimeForm.value = { ...settings.runtime }
  } catch (err: any) {
    message.error(err.message || '加载协议档失败')
  } finally {
    loading.value = false
  }
}

/** 保存运行时治理参数（settings.runtime，后端写审计） */
async function saveRuntime() {
  runtimeSaving.value = true
  try {
    await api.admin.updateSettings({ runtime: { ...runtimeForm.value } } as any)
    message.success('运行时参数已更新生效（写审计）')
  } catch (err: any) {
    message.error(err.message || '运行时参数保存失败')
  } finally {
    runtimeSaving.value = false
  }
}

async function handleUpdateAgentProfile(profileId: string) {
  try {
    await api.admin.updateSettings({ agent_profile_id: profileId })
    lastSavedAgentProfileId.value = profileId
    message.success('Agent 后端模型已指定')
  } catch (err: any) {
    // 保存失败时回滚选择器，保持 UI 与后端状态一致
    selectedAgentProfileId.value = lastSavedAgentProfileId.value
    message.error(err.message || '设置失败')
  }
}

/** P2 行内探活：原位刷新 ping-badge（复用 api.profiles.check，不泄露凭据） */
async function handlePing(p: Profile) {
  pingingId.value = p.id
  try {
    const res = await api.profiles.check(p.id)
    pingStates.value[p.id] = { ok: !!res.ok, latencyMs: res.latency_ms ?? null }
    if (res.ok) {
      message.success(`[${p.name}] 连通性正常 · 延迟 ${res.latency_ms ?? '—'}ms`)
    } else {
      message.error(`[${p.name}] 连通性测试失败`)
    }
  } catch (err: any) {
    pingStates.value[p.id] = { ok: false, latencyMs: null }
    message.error(`[${p.name}] ${err.message || '连通性测试失败'}`)
  } finally {
    pingingId.value = null
  }
}

/** 连通详情：保留原有 CheckResultModal 弹窗（展示完整检查结果/错误信息） */
async function handleCheck(p: Profile) {
  checkingId.value = p.id
  try {
    const res = await api.profiles.check(p.id)
    checkResult.value = res
    showCheckModal.value = true
  } catch (err: any) {
    checkResult.value = { ok: false, error: err.message || '连接失败' }
    showCheckModal.value = true
  } finally {
    checkingId.value = null
  }
}

function handleDelete(p: Profile) {
  dialog.warning({
    title: `删除协议档「${p.name}」？`,
    content: '删除后，依赖此协议档的评测任务将无法再次发起。',
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.profiles.delete(p.id)
        message.success('协议档已删除')
        loadProfiles()
      } catch (err: any) {
        message.error(err.message || '删除失败')
      }
    },
  })
}

onMounted(loadProfiles)
</script>

<style scoped>
.profiles-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
/* 视图切换按钮组 */
.view-mode-toggle {
  display: inline-flex;
  background: var(--bg-elevated, rgba(243, 244, 246, 1));
  padding: 3px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle, rgba(229, 231, 235, 1));
}
.toggle-btn {
  border: none;
  background: transparent;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  color: var(--text-secondary, #6b7280);
  transition: all 0.15s ease;
}
.toggle-btn.active {
  background: var(--bg-card, #ffffff);
  color: var(--c-profiles, #4f46e5);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

/* 供应商多卡片容器 */
.vendor-cards-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.vendor-group-card {
  border: 1px solid var(--border-subtle, rgba(229, 231, 235, 1));
  border-radius: 14px;
  background: linear-gradient(180deg, var(--bg-surface, #fafafa) 0%, rgba(255, 255, 255, 0.6) 100%);
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
  transition: all 0.2s ease;
}
.vendor-group-card:hover {
  border-color: rgba(99, 102, 241, 0.25);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.03);
}
.vendor-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-subtle, rgba(229, 231, 235, 0.6));
  padding-bottom: 12px;
}
.vendor-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.vendor-badge {
  font-size: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.vendor-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary, #111827);
  letter-spacing: -0.01em;
}
.vendor-count-badge {
  font-size: 11px;
  background: rgba(79, 70, 229, 0.1);
  color: var(--c-profiles, #4f46e5);
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 600;
  border: 1px solid rgba(79, 70, 229, 0.15);
}
.vendor-url {
  font-size: 11.5px;
  color: var(--text-secondary, #6b7280);
  margin-top: 2px;
}
.vendor-models-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

/* 模型芯片卡片与流光动效 */
@keyframes core-mesh {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
@keyframes pulse-border {
  0%, 100% { border-color: rgba(99, 102, 241, 0.55); box-shadow: 0 0 12px rgba(99, 102, 241, 0.12); }
  50% { border-color: rgba(56, 189, 248, 0.85); box-shadow: 0 0 20px rgba(56, 189, 248, 0.22); }
}

.model-chip-card {
  background: var(--bg-card, #ffffff);
  border: 1px solid var(--border-subtle, rgba(229, 231, 235, 1));
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  position: relative;
  transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1);
}
.model-chip-card:hover {
  transform: translateY(-2px);
  border-color: rgba(99, 102, 241, 0.45);
  box-shadow: 0 6px 20px -2px rgba(99, 102, 241, 0.1);
}
.model-chip-card.is-agent-core {
  border-width: 1.5px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.07), rgba(56, 189, 248, 0.08), rgba(168, 85, 247, 0.06), rgba(99, 102, 241, 0.07));
  background-size: 300% 300%;
  animation: core-mesh 6s ease infinite, pulse-border 3.2s ease-in-out infinite;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.15);
}
.model-chip-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.model-chip-title-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.model-chip-name {
  font-size: 13.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.model-chip-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}
.model-id-tag {
  background: rgba(15, 23, 42, 0.06);
  padding: 2px 7px;
  border-radius: 5px;
  font-weight: 500;
  color: var(--text-primary, #1e293b);
}
.protocol-tag {
  color: var(--text-tertiary, #9ca3af);
}
.window-tag {
  display: inline-block;
  padding: 1px 5px;
  background: var(--t-profiles, rgba(79, 70, 229, 0.08));
  color: var(--c-profiles, #4f46e5);
  border-radius: 4px;
  font-size: 10.5px;
  font-weight: 600;
}
.model-chip-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
  padding-top: 8px;
  border-top: 1px solid rgba(229, 231, 235, 0.5);
}
.btn-xs {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 6px;
}
.link-btn.small {
  font-size: 12px;
}

/* P2 连通性探活胶囊 */
.ping-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
}
.ping-badge.ok {
  background: rgba(16, 185, 129, 0.12);
  color: var(--accent-success);
  border: 1px solid rgba(16, 185, 129, 0.3);
}
.ping-badge.err {
  background: rgba(239, 68, 68, 0.12);
  color: var(--accent-error);
  border: 1px solid rgba(239, 68, 68, 0.3);
}
/* P4 Agent 核心驱动徽标 */
.agent-core-tag {
  border-color: #c7d2fe;
  color: var(--c-tasks);
  font-weight: 700;
  font-size: 11px;
}
/* 4 Tab 页签 */
.profile-tab-btn {
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.18s ease;
}
.profile-tab-btn:hover {
  color: var(--text-primary);
  border-color: var(--c-profiles);
}
.profile-tab-btn.active {
  background: var(--t-profiles, rgba(79, 70, 229, 0.1));
  color: var(--c-profiles);
  border-color: var(--c-profiles);
}
/* 技能卡片网格 */
.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}
.skill-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--bg-elevated);
}
.skill-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.skill-title {
  font-weight: 700;
  font-size: 14px;
}
</style>
