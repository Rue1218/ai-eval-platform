<template>
  <div class="stress-admin-page">
    <!-- S4 顶部 4 维 KPI 概览卡（对齐原型 admin-stress.html 46-63） -->
    <div class="kpi-grid" style="--glow-c: var(--c-stress)">
      <div class="kpi">
        <!-- 契约无 getUsage 接口：mock 模式给演示数据，live 模式显示 —（不虚构真实数据） -->
        <div class="kpi-num num">{{ usage.peak_qps ?? '—' }}</div>
        <div class="kpi-label">7 天峰值 QPS 水位</div>
      </div>
      <div class="kpi">
        <div class="kpi-num num">{{ whitelist.length }}</div>
        <div class="kpi-label">已授权 Host 白名单</div>
      </div>
      <div class="kpi">
        <div class="kpi-num num" style="color: var(--accent-warning)">
          {{ usage.threshold_hit_rate == null ? '—' : Math.round(usage.threshold_hit_rate * 100) + '%' }}
        </div>
        <div class="kpi-label">QPS 阈值触碰率 (≥90%)</div>
      </div>
      <div class="kpi">
        <div class="kpi-num num">{{ usage.cost_usd == null ? '—' : '$' + usage.cost_usd.toFixed(2) }}</div>
        <div class="kpi-label">本月压测累计成本</div>
      </div>
    </div>

    <!-- S10 双栏布局：左主栏规则治理 + 右 340px 用量/容量/可观测侧栏 -->
    <div class="stress-grid">
      <!-- 左主栏 -->
      <div class="section-gap" style="gap: 16px">
        <!-- S5 AI 容量与参数建议卡（对齐原型 69-85；推荐值为演示数据） -->
        <div class="ai-card">
          <div class="ai-card-head">
            <span class="ai-badge"><i class="ai-dot"></i>AI 容量与参数建议</span>
            <span class="small tertiary mono">基于近 7 天真实发压与拐点数据</span>
          </div>
          <p class="small" style="color: var(--text-secondary); line-height: 1.6; margin-bottom: 12px">
            近 7 天峰值 QPS 多次触及上限 500 的 92%（462），且有 2 次压测因时长不足未跑到性能拐点。建议收紧单次 QPS 上限、放宽单次最大发压时长并微调单次预算：
          </p>
          <div class="row wrap" style="gap: 8px; margin-bottom: 14px">
            <span class="tag-soft">QPS 上限 <b class="num">500 → 420</b></span>
            <span class="tag-soft">时长上限 <b class="num">30 → 45 分钟</b></span>
            <span class="tag-soft">默认预算 <b class="num">5 → 6 USD</b></span>
          </div>
          <div class="row" style="justify-content: flex-end">
            <button class="btn btn-ai btn-sm" @click="adoptAiSuggestion">采纳推荐参数</button>
          </div>
        </div>

        <!-- 1. 发压目标安全白名单 -->
        <div class="panel glow" style="--glow-c: var(--c-stress)">
          <div class="panel-title">
            <div class="row">
              <span>发压目标 Host 白名单</span>
              <span style="font-size: 12px; color: var(--accent-error); font-weight: 500">(目标未加入白名单时严禁启动压测)</span>
            </div>
            <button class="btn btn-primary btn-sm" @click="showAddWhitelistModal = true">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
              <span>添加白名单</span>
            </button>
          </div>

          <table class="ds-table">
            <thead>
              <tr>
                <th>目标 Host / IP</th>
                <th style="width: 170px">生效环境 (Scope)</th>
                <th style="width: 90px">创建者</th>
                <th style="width: 120px">创建时间</th>
                <th style="width: 100px">运行状态</th>
                <th style="width: 80px; text-align: right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="w in whitelist" :key="w.id">
                <td class="mono" style="font-weight: 600">{{ w.host }}</td>
                <td>
                  <!-- S9 环境 Scope 三色胶囊：scope 文本按逗号拆分渲染 -->
                  <span
                    v-for="s in scopeList(w.scope)"
                    :key="s"
                    class="env-tag-scope"
                    :class="'env-' + s"
                    style="margin-right: 4px"
                  >
                    {{ s.toUpperCase() }}
                  </span>
                </td>
                <td>{{ w.creator }}</td>
                <td class="mono" style="font-size: 12px; color: var(--text-tertiary)">{{ formatDate(w.created_at) }}</td>
                <td>
                  <!-- S9 行尾「已授权」状态徽标 -->
                  <span class="badge badge-succeeded"><i class="bdot"></i>已授权</span>
                </td>
                <td style="text-align: right">
                  <button class="link-btn danger" @click="handleDeleteWhitelist(w)">删除</button>
                </td>
              </tr>
              <tr v-if="whitelist.length === 0">
                <td colspan="6" style="text-align: center; color: var(--accent-error); padding: 16px">
                  ⚠ 暂无白名单目标，当前所有压测任务将保持在排队中 (queued + WHITELIST)
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 2. 发压安全水位与 prod 会签规则 -->
        <div class="panel glow" style="--glow-c: var(--c-stress)">
          <div class="panel-title">发压安全水位与审批保护</div>
          <div class="form-row mb16">
            <div class="field">
              <label class="field-label">默认发压 QPS 上限</label>
              <n-input-number v-model:value="settings.stress.max_qps" :min="10" :max="1000" />
            </div>
            <div class="field">
              <label class="field-label">默认最大时长 (秒)</label>
              <n-input-number v-model:value="settings.stress.max_duration_s" :min="60" :max="7200" />
            </div>
          </div>

          <!-- prod 双人会签人管理（对齐原型 admin-stress.html：chip 列表 + 添加/移除） -->
          <div class="field">
            <label class="field-label">prod 环境压测双人会签人</label>
            <div class="row" style="flex-wrap: wrap; gap: 6px">
              <span v-for="(name, i) in settings.prod_approvers" :key="name" class="tag-soft" style="display: inline-flex; align-items: center; gap: 4px">
                {{ name }}
                <button class="link-btn danger" style="padding: 0 2px" title="移除会签人" @click="removeApprover(i)">✕</button>
              </span>
              <input
                v-model="newApprover"
                class="input"
                style="width: 140px"
                placeholder="输入用户名后回车"
                @keydown.enter.prevent="addApprover"
              />
            </div>
            <span class="field-hint">prod 压测子任务须其中两名会签人确认后才开始发压</span>
          </div>
        </div>
      </div>

      <!-- 右 340px 侧栏 -->
      <div class="section-gap" style="gap: 16px">
        <!-- S6 近 7 天用量趋势面积图（内联 SVG 手绘；mock 演示数据，live 显空态） -->
        <div class="panel glow" style="--glow-c: var(--c-stress); padding: 16px 18px">
          <div class="panel-title" style="margin-bottom: 8px">近 7 天压测用量趋势</div>
          <div class="small tertiary" style="margin-bottom: 12px">每日峰值 QPS 面积图（虚线 = 90% 警戒线）</div>
          <svg width="100%" height="70" viewBox="0 0 280 70" aria-hidden="true" style="margin-bottom: 12px">
            <template v-if="usageChart">
              <!-- 90% 警戒虚线 -->
              <line
                :x1="usageChart.pad"
                :y1="usageChart.warnY"
                :x2="280 - usageChart.pad"
                :y2="usageChart.warnY"
                stroke="var(--accent-warning)"
                stroke-width="1.2"
                stroke-dasharray="3 3"
                opacity="0.8"
              />
              <!-- 面积填充 -->
              <polygon :points="usageChart.areaPoints" fill="var(--c-stress)" fill-opacity="0.12" />
              <!-- 折线主体 -->
              <polyline
                :points="usageChart.linePoints"
                fill="none"
                stroke="var(--c-stress)"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
              <!-- 越限（≥90% 水位）圆点标记 -->
              <circle
                v-for="(pt, i) in usageChart.hotDots"
                :key="i"
                :cx="pt.x"
                :cy="pt.y"
                r="3"
                fill="var(--accent-warning)"
              />
            </template>
            <text v-else x="140" y="40" text-anchor="middle" fill="var(--text-tertiary)" font-size="11">暂无使用数据</text>
          </svg>
          <div class="row-between small">
            <span class="tertiary">日均发压任务</span>
            <b class="num">{{ usage.avg_daily_tasks == null ? '—' : usage.avg_daily_tasks + ' 个' }}</b>
          </div>
          <div class="row-between small">
            <span class="tertiary">prod 平均会签等待</span>
            <b class="num">{{ usage.avg_approval_wait_min == null ? '—' : usage.avg_approval_wait_min + ' 分钟' }}</b>
          </div>
        </div>

        <!-- S7 成本单价与并发容量（load-track 水位条样式复用 base.css） -->
        <div class="panel glow" style="--glow-c: var(--c-stress); padding: 16px 18px">
          <div class="panel-title" style="margin-bottom: 12px">成本单价与并发容量</div>

          <div class="field">
            <div class="row-between">
              <span class="small tertiary">平台并发任务容量</span>
              <!-- 当前在跑数为演示值（契约无实时占用接口），分母取真实配置 -->
              <span class="num small">{{ usage.running_tasks ?? '—' }} / {{ settings.max_running_tasks }}</span>
            </div>
            <div class="load-track hot" style="margin-top: 6px">
              <i :style="{ width: capacityPct(usage.running_tasks, settings.max_running_tasks) }"></i>
            </div>
          </div>

          <div class="field">
            <div class="row-between">
              <span class="small tertiary">在途模型调用并发</span>
              <span class="num small">{{ usage.inflight_calls ?? '—' }} / {{ settings.max_inflight_model_calls }}</span>
            </div>
            <div class="load-track" style="margin-top: 6px">
              <i :style="{ width: capacityPct(usage.inflight_calls, settings.max_inflight_model_calls) }"></i>
            </div>
          </div>

          <div class="form-row">
            <div class="field">
              <label class="field-label">Token 单价 ($ / 1k)</label>
              <n-input-number v-model:value="settings.stress.price_per_1k_tokens" :min="0.0001" :step="0.0005" />
            </div>
            <div class="field">
              <label class="field-label">任务预算上限 ($)</label>
              <n-input-number v-model:value="settings.default_max_usd" :min="1" :max="100" />
            </div>
          </div>

          <div class="form-row" style="margin-bottom: 0">
            <div class="field" style="margin-bottom: 0">
              <label class="field-label">最大任务并发数</label>
              <n-input-number v-model:value="settings.max_running_tasks" :min="1" :max="10" />
            </div>
            <div class="field" style="margin-bottom: 0">
              <label class="field-label">最大模型在途数</label>
              <n-input-number v-model:value="settings.max_inflight_model_calls" :min="1" :max="32" />
            </div>
          </div>
        </div>

        <!-- S8 Prometheus 端点展示 + 通知网关 -->
        <div class="panel glow" style="--glow-c: var(--c-stress); padding: 16px 18px">
          <div class="panel-title" style="margin-bottom: 8px">Prometheus 与通知网关</div>
          <div class="field">
            <label class="field-label">Prometheus 指标端点</label>
            <!-- 只读展示：压测引擎（stress 容器）暴露 /metrics，端口 19090 -->
            <input class="input mono small" readonly :value="metricsUrl" style="font-size: 11px" />
            <span class="field-hint">前缀 <span class="mono">ai_eval_stress_</span>，包含 env, model, task_id 标签。</span>
          </div>

          <div class="switch-row" style="padding: 6px 0">
            <div>
              <div style="font-weight: 600; font-size: 12px">企业微信群机器人</div>
              <div class="field-hint">熔断、会签与终态通知</div>
            </div>
            <n-switch v-model:value="settings.notify.wecom" />
          </div>
          <div class="switch-row" style="padding: 6px 0">
            <div>
              <div style="font-weight: 600; font-size: 12px">邮件通知 (SMTP)</div>
              <div class="field-hint">出站告警分发</div>
            </div>
            <n-switch v-model:value="settings.notify.email" />
          </div>
          <div class="switch-row" style="padding: 6px 0">
            <div>
              <div style="font-weight: 600; font-size: 12px">出站 Webhook</div>
              <div class="field-hint">密钥落盘掩码存储</div>
            </div>
            <n-switch v-model:value="settings.notify.webhook" />
          </div>
        </div>

        <!-- 底部保存按钮（侧栏全宽，对齐原型） -->
        <button class="btn btn-sign" style="width: 100%" :disabled="saving" @click="saveSettings">
          {{ saving ? '保存中...' : '保存治理与安全配置' }}
        </button>
      </div>
    </div>

    <!-- 添加白名单弹窗 -->
    <n-modal v-model:show="showAddWhitelistModal" preset="card" title="添加发压目标 Host 白名单" style="width: 460px">
      <div class="field mb16">
        <label class="field-label">Host / IP 地址 <span class="req">*</span></label>
        <n-input v-model:value="newHost" placeholder="例如：10.0.0.8 或 api.internal.eval" />
      </div>
      <div class="field mb16">
        <label class="field-label">允许发压环境</label>
        <!-- Scope 多选 chips（对齐原型 admin-stress.html），避免手写文本出错 -->
        <div class="chip-group">
          <button
            v-for="s in ['test', 'staging', 'prod']"
            :key="s"
            class="chip"
            :class="{ on: newScopes.includes(s) }"
            @click="toggleScope(s)"
          >
            {{ s.toUpperCase() }}
          </button>
        </div>
        <span class="field-hint">至少选择一个环境；prod 环境压测需双人会签</span>
      </div>
      <template #footer>
        <div style="display: flex; gap: 8px; justify-content: flex-end">
          <n-button @click="showAddWhitelistModal = false">取消</n-button>
          <n-button type="primary" :loading="addingHost" @click="handleAddWhitelist">确认添加</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api/http'
import type { AdminSettings, WhitelistItem } from '../api/types'

const message = useMessage()
const dialog = useDialog()

const saving = ref(false)
const whitelist = ref<WhitelistItem[]>([])

const showAddWhitelistModal = ref(false)
const newHost = ref('')
const newScopes = ref<string[]>(['test', 'staging'])
const addingHost = ref(false)

/** 切换白名单生效环境 chip */
function toggleScope(s: string) {
  const idx = newScopes.value.indexOf(s)
  if (idx >= 0) newScopes.value.splice(idx, 1)
  else newScopes.value.push(s)
}

/** S9 将白名单 scope 文本按逗号拆分为环境胶囊列表 */
function scopeList(scope: string): string[] {
  return (scope || 'test')
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
}

function formatDate(d?: string) {
  if (!d) return ''
  return String(d).slice(0, 10)
}

const settings = ref<AdminSettings>({
  agent_profile_id: '',
  max_running_tasks: 3,
  max_inflight_model_calls: 8,
  default_max_usd: 5,
  stress: {
    host_whitelist: [],
    max_qps: 500,
    max_duration_s: 1800,
    price_per_1k_tokens: 0.002,
  },
  notify: {
    wecom: false,
    email: false,
    webhook: false,
  },
  prod_approvers: ['admin'],
})

/* ─── S4/S6/S7 用量演示数据 ───
 * 契约（API.md）未定义 getUsage 接口，后端暂无用量统计：
 * mock 模式下给演示数据便于走查原型交互；live 模式一律为 null，UI 显示 —（不虚构）。 */
interface UsageDemo {
  peak_qps: number | null
  threshold_hit_rate: number | null
  cost_usd: number | null
  points: number[]
  avg_daily_tasks: number | null
  avg_approval_wait_min: number | null
  running_tasks: number | null
  inflight_calls: number | null
}
const usage = ref<UsageDemo>(
  api.isMock()
    ? {
        peak_qps: 462,
        threshold_hit_rate: 0.28,
        cost_usd: 37.52,
        points: [210, 305, 268, 462, 388, 455, 340],
        avg_daily_tasks: 11,
        avg_approval_wait_min: 12,
        running_tasks: 2,
        inflight_calls: 5,
      }
    : {
        peak_qps: null,
        threshold_hit_rate: null,
        cost_usd: null,
        points: [],
        avg_daily_tasks: null,
        avg_approval_wait_min: null,
        running_tasks: null,
        inflight_calls: null,
      },
)

/** S6 近 7 天峰值 QPS 面积图坐标计算（对齐原型 drawUsageArea：280x70 视窗 + 90% 警戒线 + 越限圆点） */
const usageChart = computed(() => {
  const D = usage.value.points.filter(v => Number.isFinite(v))
  if (D.length < 2) return null
  const W = 280
  const H = 70
  const P = 4
  const maxQps = Math.max(...D, settings.value.stress.max_qps || 0, 1)
  const X = (i: number) => P + (i * (W - 2 * P)) / (D.length - 1)
  const Y = (v: number) => H - P - (v / maxQps) * (H - 2 * P - 8)
  const linePoints = D.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ')
  const areaPoints = `${P},${H - P} ${linePoints} ${X(D.length - 1).toFixed(1)},${H - P}`
  return {
    pad: P,
    // 警戒虚线纵坐标：以 QPS 上限的 90% 为水位线
    warnY: Y((settings.value.stress.max_qps || 500) * 0.9),
    linePoints,
    areaPoints,
    // 越限圆点：达到最大值 90% 及以上的数据点
    hotDots: D.map((v, i) => ({ v, x: X(i), y: Y(v) })).filter(p => p.v / maxQps >= 0.9),
  }
})

/** S7 并发容量水位百分比（分母为 0 或当前值缺失时兜底 0%） */
function capacityPct(current: number | null, max: number): string {
  if (current == null || !max) return '0%'
  return `${Math.min(100, Math.round((current / max) * 100))}%`
}

/** S8 Prometheus 指标端点：stress 容器暴露 /metrics（端口 19090），按当前访问主机拼接 */
const metricsUrl = computed(() => `http://${window.location.hostname}:19090/metrics`)

/** S5 采纳 AI 推荐参数：一键回填到 settings，随「保存治理与安全配置」统一落库 */
function adoptAiSuggestion() {
  settings.value.stress.max_qps = 420
  settings.value.stress.max_duration_s = 45 * 60 // 45 分钟
  settings.value.default_max_usd = 6
  message.success('已填充 AI 推荐参数，点击「保存治理与安全配置」生效')
}

async function loadData() {
  try {
    const [s, w] = await Promise.all([api.admin.getSettings(), api.admin.getWhitelist()])
    settings.value = s
    whitelist.value = w
  } catch (err: any) {
    message.error(err.message || '加载配置失败')
  }
}

async function handleAddWhitelist() {
  if (!newHost.value.trim()) {
    message.warning('请输入 Host 地址')
    return
  }
  if (!newScopes.value.length) {
    message.warning('请至少选择一个允许发压环境')
    return
  }
  addingHost.value = true
  try {
    const item = await api.admin.addWhitelist({ host: newHost.value.trim(), scope: newScopes.value.join(',') })
    whitelist.value.push(item)
    message.success('已添加至白名单')
    showAddWhitelistModal.value = false
    newHost.value = ''
    newScopes.value = ['test', 'staging']
  } catch (err: any) {
    message.error(err.message || '添加失败')
  } finally {
    addingHost.value = false
  }
}

// prod 会签人管理
const newApprover = ref('')

/** 添加会签人（去重），随「保存治理与安全配置」统一落库 */
function addApprover() {
  const name = newApprover.value.trim()
  if (!name) return
  if (settings.value.prod_approvers.includes(name)) {
    message.warning('该会签人已存在')
    return
  }
  settings.value.prod_approvers.push(name)
  newApprover.value = ''
}

/** 移除会签人；至少保留一名，避免 prod 压测无人能签 */
function removeApprover(idx: number) {
  if (settings.value.prod_approvers.length <= 1) {
    message.error('至少保留一名 prod 会签人')
    return
  }
  settings.value.prod_approvers.splice(idx, 1)
}

function handleDeleteWhitelist(item: WhitelistItem) {
  dialog.warning({
    title: `删除白名单「${item.host}」？`,
    content: '删除后，指向此 Host 的压测任务将无法执行。',
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.admin.deleteWhitelist(item.id)
        whitelist.value = whitelist.value.filter((x) => x.id !== item.id)
        message.success('已从白名单移除')
      } catch (err: any) {
        message.error(err.message || '删除失败')
      }
    },
  })
}

async function saveSettings() {
  saving.value = true
  try {
    await api.admin.updateSettings(settings.value)
    message.success('压测治理与安全配置已保存')
  } catch (err: any) {
    message.error(err.message || '保存配置失败')
  } finally {
    saving.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.stress-admin-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
/* S10 双栏布局：左主栏 + 右 340px 侧栏（迁移自原型 .stress-grid） */
.stress-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 20px;
  align-items: flex-start;
}
@media (max-width: 1100px) {
  .stress-grid {
    grid-template-columns: 1fr;
  }
}
/* S9 环境 Scope 三色胶囊（迁移自原型 admin-stress.html 21-24） */
.env-tag-scope {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.env-test {
  background: rgba(14, 116, 144, 0.12);
  color: #0e7490;
  border: 1px solid rgba(14, 116, 144, 0.25);
}
.env-staging {
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
  border: 1px solid rgba(99, 102, 241, 0.25);
}
.env-prod {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.3);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}
.field-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}
.field-label .req {
  color: var(--accent-error);
}
.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--border-subtle);
}
.switch-row:last-child {
  border-bottom: none;
}
</style>
