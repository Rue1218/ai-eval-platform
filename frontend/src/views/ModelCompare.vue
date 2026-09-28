<template>
  <div class="model-compare-page">
    <!-- 历史对比仅支持查询已有任务。 -->
    <div v-if="!taskId" class="panel glow" style="--glow-c: var(--c-reports)">
      <div class="panel-title">历史模型对比</div>
      <div class="row" style="gap: 8px">
        <n-input v-model:value="historyTaskId" placeholder="输入历史基准评测任务 ID" />
        <button class="btn btn-primary" @click="openHistoricalTask">查询</button>
        <router-link class="btn btn-secondary" to="/reports">查看历史报告</router-link>
      </div>
    </div>

    <!-- ═══════════ 任务进行中 ═══════════ -->
    <div v-else-if="!report" class="panel glow" style="--glow-c: var(--c-reports)">
      <div class="panel-title">
        <div class="row">
          <span>评测进行中</span>
          <button class="btn btn-secondary btn-sm" @click="goBack">返回历史查询</button>
        </div>
      </div>
      <div v-if="task" class="compare-progress">
        <div class="row-between">
          <span class="small">任务 {{ task.id.slice(0, 8) }} · 状态 <b>{{ statusText }}</b></span>
          <span class="small tertiary">样本 {{ task.progress?.done ?? 0 }} / {{ task.progress?.total ?? '—' }}</span>
        </div>
        <n-progress
          type="line"
          :percentage="task.progress?.percent ?? 0"
          :show-indicator="false"
          color="var(--c-reports)"
          style="margin-top: 10px"
        />
        <div v-if="taskFailedText" class="field-error" style="margin-top: 12px">{{ taskFailedText }}</div>
      </div>

      <!-- 运行日志窗口 -->
      <div class="run-log-panel" style="margin-top: 14px">
        <div class="row-between" style="margin-bottom: 6px">
          <span class="panel-title" style="margin: 0">运行日志</span>
          <span class="small tertiary">{{ logEntries.length }} 条</span>
        </div>
        <div ref="logBox" class="run-log-box">
          <div v-for="entry in logEntries" :key="entry.id" class="log-line" :class="logClass(entry)">
            <span class="log-time mono">{{ formatLogTime(entry.ts) }}</span>
            <span class="log-event mono">{{ entry.event }}</span>
            <span class="log-msg">{{ entry.message || '—' }}</span>
          </div>
          <div v-if="!logEntries.length" class="small tertiary" style="text-align: center; padding: 14px">
            等待任务日志…
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════ 结果对比 ═══════════ -->
    <template v-else>
      <div class="row-between" style="margin-bottom: 12px">
        <div class="row" style="gap: 8px">
          <button class="btn btn-secondary btn-sm" @click="goBack">返回历史查询</button>
          <button class="btn btn-secondary btn-sm" @click="refreshResult">刷新</button>
        </div>
        <button class="btn btn-secondary btn-sm" @click="openReport">查看完整报告</button>
      </div>

      <!-- 控制变量声明横幅 -->
      <div class="info-strip" style="margin: 0 0 12px; padding: 6px 14px; border-radius: 8px">
        <b>控制变量：</b>数据集 <span class="mono">{{ report.dataset_name }} v{{ report.dataset_version }}</span>
        · 抽样 {{ form.sampleSize || report.sample_total || '—' }} 条
        · 并发 {{ form.concurrency || '—' }}
        · 温度 {{ form.temperature ?? '—' }}
        · 主指标 {{ report.metric || 'contain' }}
        <span v-if="taskDuration">· 任务总耗时 {{ taskDuration }}</span>
        <span v-if="report.judge"> · 裁判：{{ report.judge.profile_name || '—' }}</span>
      </div>

      <!-- 两列对比卡片 -->
      <div class="compare-cards" style="--glow-c: var(--c-reports)">
        <div
          v-for="(score, idx) in orderedScores"
          :key="score.profile_id"
          class="panel glow"
          style="--glow-c: var(--c-reports)"
        >
          <div class="panel-title">
            <div class="row">
              <span>{{ idx === 0 ? '基准模型' : '对照模型' }}</span>
              <span class="mono small tertiary" style="font-weight: 400">{{ score.profile_name }} · {{ score.model }}</span>
            </div>
          </div>
          <table class="cmp-metric-table">
            <tbody>
              <tr>
                <td>质量分（{{ report.metric || 'contain' }}）</td>
                <td class="num">{{ formatNum(score.score) }}</td>
                <td class="delta">{{ deltaFor(idx, 'score') }}</td>
              </tr>
              <tr>
                <td>Exact</td>
                <td class="num">{{ formatNum(score.exact) }}</td>
                <td class="delta">{{ deltaFor(idx, 'exact') }}</td>
              </tr>
              <tr>
                <td>Rouge-L</td>
                <td class="num">{{ formatNum(score.rouge_l) }}</td>
                <td class="delta">{{ deltaFor(idx, 'rouge_l') }}</td>
              </tr>
              <tr>
                <td>LLM 裁判分</td>
                <td class="num">{{ formatNum(score.judge) }}</td>
                <td class="delta">{{ deltaFor(idx, 'judge') }}</td>
              </tr>
              <tr>
                <td>平均耗时</td>
                <td class="num">{{ score.latency_ms_avg != null ? `${score.latency_ms_avg} ms` : '—' }}</td>
                <td class="delta">{{ deltaFor(idx, 'latency_ms_avg') }}</td>
              </tr>
              <tr>
                <td>总 Tokens</td>
                <td class="num">{{ score.usage?.total_tokens ?? '—' }}</td>
                <td class="delta">{{ deltaTokens(idx) }}</td>
              </tr>
              <tr>
                <td>估算费用</td>
                <td class="num">{{ score.est_cost_usd != null ? `$${score.est_cost_usd.toFixed(4)}` : '—' }}</td>
                <td class="delta">{{ deltaCost(idx) }}</td>
              </tr>
              <tr>
                <td>失败样本</td>
                <td class="num">{{ score.sample_failed ?? '—' }} / {{ score.sample_total ?? '—' }}</td>
                <td class="delta"></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 逐题对比表 -->
      <div class="panel glow" style="--glow-c: var(--c-reports)">
        <div class="panel-title">
          <div class="row">
            <span>逐题对比</span>
            <span class="small tertiary">共 {{ samplesTotal }} 题</span>
          </div>
          <div class="row" style="gap: 6px">
            <button
              v-for="f in sampleFilters"
              :key="f.value"
              class="btn btn-sm"
              :class="sampleFilter === f.value ? 'btn-primary' : 'btn-secondary'"
              @click="changeFilter(f.value)"
            >
              {{ f.label }}
            </button>
          </div>
        </div>

        <table class="ds-table cmp-sample-table">
          <thead>
            <tr>
              <th style="width: 50px">#</th>
              <th style="width: 180px">问题</th>
              <th>基准模型输出</th>
              <th>对照模型输出</th>
              <th style="width: 120px">基准 (分/耗时)</th>
              <th style="width: 120px">对照 (分/耗时)</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in samples" :key="row.row_no" :class="{ 'row-diff': row.diff }">
              <td class="mono small tertiary">{{ row.row_no }}</td>
              <td>
                <div class="sample-q">{{ row.question }}</div>
                <div v-if="row.reference" class="sample-ref small tertiary">参考：{{ truncate(row.reference, 60) }}</div>
              </td>
              <td>
                <div v-if="pred(row, baseProfileId)?.error" class="small" style="color: var(--accent-error)">{{ pred(row, baseProfileId)?.error }}</div>
                <div v-else class="sample-out">{{ truncate(pred(row, baseProfileId)?.output || '—', 200) }}</div>
              </td>
              <td>
                <div v-if="pred(row, compareProfileId)?.error" class="small" style="color: var(--accent-error)">{{ pred(row, compareProfileId)?.error }}</div>
                <div v-else class="sample-out">{{ truncate(pred(row, compareProfileId)?.output || '—', 200) }}</div>
              </td>
              <td class="small mono">{{ metricCell(row, baseProfileId) }}</td>
              <td class="small mono">{{ metricCell(row, compareProfileId) }}</td>
            </tr>
            <tr v-if="!samples.length">
              <td colspan="6" class="small tertiary" style="text-align: center; padding: 24px 0">暂无样本数据</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 运行日志窗口（结果保留可回溯） -->
      <div class="panel glow" style="--glow-c: var(--c-reports)">
        <div class="panel-title">
          <div class="row">
            <span>运行日志</span>
            <span class="small tertiary">{{ logEntries.length }} 条</span>
          </div>
        </div>
        <div ref="logBox" class="run-log-box">
          <div v-for="entry in logEntries" :key="entry.id" class="log-line" :class="logClass(entry)">
            <span class="log-time mono">{{ formatLogTime(entry.ts) }}</span>
            <span class="log-event mono">{{ entry.event }}</span>
            <span class="log-msg">{{ entry.message || '—' }}</span>
          </div>
          <div v-if="!logEntries.length" class="small tertiary" style="text-align: center; padding: 14px">
            无运行日志
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { api } from '../api/http'
import type { Task, Report, BenchmarkScore, CompareSampleRow, TaskStatus, TaskEvent } from '../api/types'

const message = useMessage()
const router = useRouter()
const route = useRoute()

const historyTaskId = ref('')
const form = ref({
  baseProfileId: null as string | null,
  compareProfileId: null as string | null,
  sampleSize: 0,
  concurrency: 0,
  temperature: 0,
})

// 任务 / 结果
const taskId = ref<string | null>(null)
const task = ref<Task | null>(null)
const report = ref<Report | null>(null)
const samples = ref<CompareSampleRow[]>([])
const samplesTotal = ref(0)
const sampleFilter = ref<'all' | 'diff' | 'fail'>('all')
const pollTimer = ref<number | null>(null)

// 运行日志窗口
const logEntries = ref<TaskEvent[]>([])
const logBox = ref<HTMLElement | null>(null)

function mergeEvents(events?: TaskEvent[] | null) {
  if (!events?.length) return
  const existing = new Set(logEntries.value.map(e => e.id))
  const fresh = events.filter(e => !existing.has(e.id))
  if (!fresh.length) return
  logEntries.value.push(...fresh)
  if (logEntries.value.length > 300) logEntries.value = logEntries.value.slice(-300)
  nextTick(() => {
    if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
  })
}

function logClass(ev: TaskEvent): string {
  if (ev.level === 'error') return 'err'
  if (ev.event === 'finish') return 'ok'
  if (ev.event === 'progress') return 'progress'
  if (ev.event === 'log') return 'log'
  return 'info'
}

function formatLogTime(ts?: string): string {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false })
}

const baseProfileId = computed(() => form.value.baseProfileId)
const compareProfileId = computed(() => form.value.compareProfileId)

const orderedScores = computed<BenchmarkScore[]>(() => {
  const scores = report.value?.scores || []
  const base = scores.find(s => s.profile_id === form.value.baseProfileId)
  const cmp = scores.find(s => s.profile_id === form.value.compareProfileId)
  const rest = scores.filter(s => s.profile_id !== form.value.baseProfileId && s.profile_id !== form.value.compareProfileId)
  return [base, cmp, ...rest].filter((s): s is BenchmarkScore => !!s)
})

const statusText = computed(() => {
  const map: Record<TaskStatus, string> = {
    queued: '排队中', running: '执行中', awaiting_case_confirm: '待确认', succeeded: '成功', failed: '失败', cancelled: '已取消',
  }
  return map[task.value?.status || 'queued']
})

const taskFailedText = computed(() => {
  if (task.value?.status === 'failed' || task.value?.status === 'cancelled') {
    return task.value.result?.error_message || `任务${task.value.status === 'failed' ? '失败' : '已取消'}`
  }
  return ''
})

const taskDuration = computed(() => {
  if (!task.value?.created_at || !report.value?.created_at) return ''
  const ms = new Date(report.value.created_at).getTime() - new Date(task.value.created_at).getTime()
  if (ms < 0) return ''
  return ms >= 60000 ? `${Math.round(ms / 60000)} 分钟 ${Math.round((ms % 60000) / 1000)} 秒` : `${(ms / 1000).toFixed(1)} 秒`
})

const sampleFilters = [
  { value: 'all' as const, label: '全部' },
  { value: 'diff' as const, label: '仅差异' },
  { value: 'fail' as const, label: '仅失败' },
]

function pred(row: CompareSampleRow, profileId: string | null) {
  return row.predictions.find(p => p.profile_id === profileId) || null
}

function formatNum(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return v.toFixed(3)
}

function metricCell(row: CompareSampleRow, profileId: string | null): string {
  const p = pred(row, profileId)
  if (!p) return '—'
  if (p.error) return p.error.slice(0, 30)
  const parts: string[] = []
  if (p.score != null) parts.push(`分 ${p.score.toFixed(2)}`)
  if (p.judge_score != null) parts.push(`裁判 ${p.judge_score}`)
  if (p.latency_ms != null) parts.push(`${p.latency_ms}ms`)
  return parts.join(' · ') || '—'
}

type DeltaKey = 'score' | 'exact' | 'rouge_l' | 'judge' | 'latency_ms_avg'

/** Δ 差值：仅在对 照卡片（idx=1）上展示相对基准模型的差值。 */
function deltaFor(idx: number, key: DeltaKey): string {
  if (idx !== 1) return ''
  const base = orderedScores.value[0]
  const cmp = orderedScores.value[1]
  const b = base?.[key]
  const c = cmp?.[key]
  if (b == null || c == null) return '—'
  const d = c - b
  const sign = d > 0 ? '+' : ''
  return key === 'latency_ms_avg' ? `${sign}${d.toFixed(0)} ms` : `${sign}${d.toFixed(3)}`
}

function deltaTokens(idx: number): string {
  if (idx !== 1) return ''
  const b = orderedScores.value[0]?.usage?.total_tokens
  const c = orderedScores.value[1]?.usage?.total_tokens
  if (b == null || c == null) return '—'
  const d = c - b
  return `${d > 0 ? '+' : ''}${Math.round(d)}`
}

function deltaCost(idx: number): string {
  if (idx !== 1) return ''
  const b = orderedScores.value[0]?.est_cost_usd
  const c = orderedScores.value[1]?.est_cost_usd
  if (b == null || c == null) return '—'
  const d = c - b
  return `${d > 0 ? '+' : ''}$${d.toFixed(4)}`
}

function truncate(text: string, len: number): string {
  if (!text) return ''
  return text.length > len ? `${text.slice(0, len)}…` : text
}

/** 只读取已有 benchmark 任务及报告，不再从该页创建评测。 */
async function openHistoricalTask() {
  const id = historyTaskId.value.trim()
  if (!id) {
    message.warning('请输入历史任务 ID')
    return
  }
  try {
    const existing = await api.tasks.get(id)
    if (existing.kind !== 'benchmark') {
      message.warning('该任务不是模型对比评测，请在任务中心查看')
      return
    }
    task.value = existing
    taskId.value = existing.id
    form.value = {
      baseProfileId: existing.config.profile_ids?.[0] || null,
      compareProfileId: existing.config.profile_ids?.[1] || null,
      sampleSize: existing.config.run?.sample_size || 0,
      concurrency: existing.config.run?.concurrency || 0,
      temperature: existing.config.run?.temperature || 0,
    }
    logEntries.value = []
    mergeEvents(existing.events)
    if (existing.report_id) await loadResult()
    else if (existing.status === 'queued' || existing.status === 'running') startPolling()
  } catch (e: any) {
    message.error(e.message || '加载历史任务失败')
  }
}

function startPolling() {
  stopPolling()
  pollTimer.value = window.setInterval(async () => {
    if (!taskId.value) return
    try {
      task.value = await api.tasks.get(taskId.value)
      mergeEvents(task.value.events)
      if (task.value.status === 'succeeded') {
        stopPolling()
        await loadResult()
      } else if (task.value.status === 'failed' || task.value.status === 'cancelled') {
        stopPolling()
      }
    } catch {
      // 轮询失败不中断，下次继续
    }
  }, 2000)
}

function stopPolling() {
  if (pollTimer.value !== null) {
    window.clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

async function loadResult() {
  if (!task.value?.report_id) return
  try {
    report.value = await api.reports.get(task.value.report_id)
    await loadSamples('all')
  } catch (e: any) {
    message.error(e.message || '加载报告失败')
  }
}

async function loadSamples(filter: 'all' | 'diff' | 'fail') {
  if (!task.value?.report_id) return
  const data = await api.reports.samples(task.value.report_id, { filter, limit: 100 })
  samples.value = data.items
  samplesTotal.value = data.total
}

async function changeFilter(f: 'all' | 'diff' | 'fail') {
  sampleFilter.value = f
  await loadSamples(f)
}

async function refreshResult() {
  await loadResult()
}

function goBack() {
  stopPolling()
  taskId.value = null
  task.value = null
  report.value = null
  samples.value = []
  samplesTotal.value = 0
  logEntries.value = []
}

function openReport() {
  if (task.value?.report_id) {
    router.push(`/reports/${task.value.report_id}`)
  }
}

onMounted(() => {
  const queryId = route.query.task_id
  if (typeof queryId === 'string' && queryId) {
    historyTaskId.value = queryId
    void openHistoricalTask()
  }
})

onUnmounted(stopPolling)
</script>

<style scoped>
.model-compare-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.compare-form {
  display: flex;
  flex-direction: column;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
@media (max-width: 900px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}
.field-error {
  color: var(--accent-error);
  font-size: 12px;
}
.compare-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
@media (max-width: 1000px) {
  .compare-cards {
    grid-template-columns: 1fr;
  }
}
.cmp-metric-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.cmp-metric-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border-subtle);
}
.cmp-metric-table td:first-child {
  color: var(--text-secondary);
}
.cmp-metric-table .num {
  font-family: var(--font-mono);
  text-align: right;
  color: var(--text-primary);
  font-weight: 600;
}
.cmp-metric-table .delta {
  width: 60px;
  text-align: right;
  font-size: 11px;
  color: var(--text-tertiary);
}
.compare-progress {
  padding: 8px 4px 4px;
}
.sample-q {
  font-size: 12px;
  color: var(--text-primary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.sample-ref {
  margin-top: 4px;
}
.sample-out {
  font-size: 12px;
  color: var(--text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.5;
}
.row-diff {
  background: color-mix(in srgb, var(--accent-warning) 6%, transparent);
}
/* 运行日志窗口 */
.run-log-box {
  max-height: 260px;
  overflow-y: auto;
  background: color-mix(in srgb, var(--bg-main) 60%, var(--bg-elevated));
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 6px 10px;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
}
.log-line {
  display: flex;
  gap: 10px;
  align-items: baseline;
  padding: 2px 0;
  border-bottom: 1px dashed color-mix(in srgb, var(--border-subtle) 50%, transparent);
  white-space: nowrap;
  overflow: hidden;
}
.log-line:last-child {
  border-bottom: none;
}
.log-time {
  color: var(--text-tertiary);
  flex: 0 0 auto;
}
.log-event {
  color: var(--text-tertiary);
  width: 64px;
  flex: 0 0 auto;
}
.log-msg {
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
}
.log-line.progress .log-event {
  color: var(--c-reports);
}
.log-line.log .log-event {
  color: var(--accent-info);
}
.log-line.ok .log-event {
  color: var(--accent-success);
}
.log-line.err .log-event {
  color: var(--accent-error);
}
</style>
