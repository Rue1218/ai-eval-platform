<template>
  <div class="model-compare-page">
    <!-- ═══════════ 发起评测表单 ═══════════ -->
    <div v-if="!taskId" class="panel glow" style="--glow-c: var(--c-reports)">
      <div class="panel-title">
        <div class="row">
          <span>双模型对比测评</span>
          <span class="small tertiary">基准模型 vs 对照模型 · 同一数据集 / 同一运行配置（控制变量）</span>
        </div>
      </div>

      <div class="compare-form">
        <div class="form-grid">
          <div class="field">
            <label class="field-label">基准模型</label>
            <n-select
              v-model:value="form.baseProfileId"
              :options="targetOptions"
              placeholder="选择基准模型"
              filterable
              clearable
            />
          </div>
          <div class="field">
            <label class="field-label">对照模型</label>
            <n-select
              v-model:value="form.compareProfileId"
              :options="targetOptions"
              placeholder="选择对照模型"
              filterable
              clearable
            />
          </div>
          <div class="field">
            <label class="field-label">数据集</label>
            <n-select
              v-model:value="form.datasetId"
              :options="datasetOptions"
              placeholder="选择数据集"
              filterable
              clearable
            />
          </div>
        </div>

        <div class="form-grid">
          <div class="field">
            <label class="field-label">抽样条数</label>
            <n-input-number v-model:value="form.sampleSize" :min="1" :max="1000" style="width: 100%" />
          </div>
          <div class="field">
            <label class="field-label">并发数</label>
            <n-input-number v-model:value="form.concurrency" :min="1" :max="100" style="width: 100%" />
          </div>
          <div class="field">
            <label class="field-label">温度</label>
            <n-input-number v-model:value="form.temperature" :min="0" :max="2" :step="0.1" style="width: 100%" />
          </div>
          <div class="field">
            <label class="field-label">最大输出 Tokens</label>
            <n-input-number v-model:value="form.maxTokens" :min="1" :max="32768" style="width: 100%" />
          </div>
        </div>

        <div class="field" style="margin-top: 12px">
          <label class="field-label">系统提示词（可选）</label>
          <n-input v-model:value="form.systemPrompt" type="textarea" :rows="2" placeholder="所有模型使用同一系统提示词" />
        </div>

        <div class="row-between" style="margin-top: 14px; align-items: center">
          <div class="field" style="margin: 0; flex: 1">
            <div class="row" style="gap: 10px; align-items: center">
              <n-switch v-model:value="form.useJudge" />
              <span class="field-label" style="margin: 0">启用 LLM 裁判打分（0-100 质量分）</span>
            </div>
            <n-select
              v-if="form.useJudge"
              v-model:value="form.judgeProfileId"
              :options="judgeOptions"
              placeholder="选择裁判协议档（usages 含 judge）"
              filterable
              clearable
              style="margin-top: 8px; max-width: 480px"
            />
          </div>
          <div class="row" style="gap: 8px">
            <button class="btn btn-secondary" @click="resetForm">重置</button>
            <button class="btn btn-primary" :disabled="launching" @click="launch">
              {{ launching ? '创建任务中…' : '开始对比评测' }}
            </button>
          </div>
        </div>
        <div v-if="errorText" class="field-error" style="margin-top: 8px">{{ errorText }}</div>
      </div>
    </div>

    <!-- ═══════════ 任务进行中 ═══════════ -->
    <div v-else-if="!report" class="panel glow" style="--glow-c: var(--c-reports)">
      <div class="panel-title">
        <div class="row">
          <span>评测进行中</span>
          <button class="btn btn-secondary btn-sm" @click="goBack">返回修改配置</button>
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
          <button class="btn btn-secondary btn-sm" @click="goBack">重新发起</button>
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
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { api } from '../api/http'
import type { Profile, Dataset, Task, Report, BenchmarkScore, CompareSampleRow, TaskStatus, TaskEvent } from '../api/types'

const message = useMessage()
const router = useRouter()

const profiles = ref<Profile[]>([])
const datasets = ref<Dataset[]>([])
const loading = ref(false)
const launching = ref(false)
const errorText = ref('')

const form = ref({
  baseProfileId: null as string | null,
  compareProfileId: null as string | null,
  datasetId: null as string | null,
  sampleSize: 50,
  concurrency: 4,
  temperature: 0,
  maxTokens: 1024,
  systemPrompt: '',
  useJudge: false,
  judgeProfileId: null as string | null,
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

const targetOptions = computed(() =>
  profiles.value
    .filter(p => p.usages?.includes('target') || p.usages?.includes('benchmark'))
    .map(p => ({ label: `${p.name} · ${p.model}`, value: p.id })),
)
const judgeOptions = computed(() =>
  profiles.value.filter(p => p.usages?.includes('judge')).map(p => ({
    label: `${p.name} · ${p.model}`,
    value: p.id,
  })),
)
const datasetOptions = computed(() =>
  datasets.value.map(d => ({ label: `${d.name} (v${d.version}) · ${d.row_count} 行`, value: d.id })),
)

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

function validate(): string {
  if (!form.value.baseProfileId || !form.value.compareProfileId) return '请选择基准模型与对照模型'
  if (form.value.baseProfileId === form.value.compareProfileId) return '基准模型与对照模型不能相同'
  if (!form.value.datasetId) return '请选择数据集'
  if (form.value.useJudge && !form.value.judgeProfileId) return '启用 LLM 裁判时需要选择裁判协议档'
  return ''
}

async function launch() {
  const err = validate()
  if (err) { errorText.value = err; return }
  errorText.value = ''
  launching.value = true
  try {
    const task = await api.tasks.create({
      kind: 'benchmark',
      profile_ids: [form.value.baseProfileId!, form.value.compareProfileId!],
      dataset_id: form.value.datasetId!,
      run: {
        sample_size: form.value.sampleSize,
        concurrency: form.value.concurrency,
        temperature: form.value.temperature,
        max_tokens: form.value.maxTokens,
        system_prompt: form.value.systemPrompt || undefined,
        use_judge: form.value.useJudge,
        judge_profile_id: form.value.useJudge ? form.value.judgeProfileId || undefined : undefined,
      },
    })
    taskId.value = task.id
    logEntries.value = []
    startPolling()
  } catch (e: any) {
    message.error(e.message || '创建任务失败')
  } finally {
    launching.value = false
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
    } catch (e: any) {
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

function resetForm() {
  form.value = {
    baseProfileId: null, compareProfileId: null, datasetId: null,
    sampleSize: 50, concurrency: 4, temperature: 0, maxTokens: 1024,
    systemPrompt: '', useJudge: false, judgeProfileId: null,
  }
  errorText.value = ''
}

function openReport() {
  if (task.value?.report_id) {
    router.push(`/reports/${task.value.report_id}`)
  }
}

onMounted(async () => {
  loading.value = true
  try {
    ;[profiles.value, datasets.value] = await Promise.all([api.profiles.list(), api.datasets.list()])
  } catch (e: any) {
    message.error(e.message || '加载模型与数据集失败')
  } finally {
    loading.value = false
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
