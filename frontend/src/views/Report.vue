<template>
  <div class="report-page">
    <template v-if="report">
      <!-- 头部操作条 -->
      <div class="row-between mb16" style="padding-bottom: 14px; border-bottom: 1px solid var(--border-subtle)">
        <div>
          <div class="row">
            <KindTag :kind="report.kind" />
            <span style="font-size: 18px; font-weight: 700">{{ report.title || '评测报告' }}</span>
          </div>
          <div class="mono mt8" style="font-size: 11.5px; color: var(--text-tertiary)">
            报告 ID: {{ report.id }} · 关联任务: {{ report.task_id }} · 生成时间: {{ formatDate(report.created_at) }}
          </div>
        </div>

        <div class="row">
          <button class="btn btn-secondary btn-sm" @click="handleInterpret">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
            </svg>
            <span>在对话中解读</span>
          </button>

          <button class="btn btn-secondary btn-sm" @click="openShareModal">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="18" cy="5" r="3"></circle>
              <circle cx="6" cy="12" r="3"></circle>
              <circle cx="18" cy="19" r="3"></circle>
              <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"></line>
              <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"></line>
            </svg>
            <span>分享 (7天)</span>
          </button>

          <button class="btn btn-secondary btn-sm" @click="handleExportMd">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>导出 Markdown</span>
          </button>

          <!-- 压测报告不支持冻结为基线（基线仅面向质量评测语义） -->
          <button v-if="report.kind !== 'stress'" class="btn btn-secondary btn-sm" @click="handleFreezeBaseline">
            冻结为基线
          </button>
        </div>
      </div>

      <!-- 先评后压派生横幅（质量报告 → 压测报告） -->
      <div v-if="report.child_stress_report_id" class="cascade-banner">
        <div class="row">
          <span class="kind-tag kind-stress">先评后压</span>
          <span style="font-size: 13.5px; font-weight: 500">
            该质量评测成功后已自动派生发压任务（任务 ID: {{ report.child_stress_task_id }}）
          </span>
        </div>
        <router-link :to="`/reports/${report.child_stress_report_id}`" class="btn btn-sign btn-sm">
          查看关联压测报告 →
        </router-link>
      </div>

      <!-- 压测报告回溯横幅（压测报告 → 父质量报告） -->
      <div v-if="report.kind === 'stress' && report.parent_report_id" class="cascade-banner">
        <div class="row">
          <span class="badge badge-succeeded">继承自质量评测</span>
          <span style="font-size: 13.5px; font-weight: 500">
            本压测报告继承自质量评测（父报告 ID: {{ report.parent_report_id }}<template v-if="report.parent_task_id"> · 任务 ID: {{ report.parent_task_id }}</template>）
          </span>
        </div>
        <router-link :to="`/reports/${report.parent_report_id}`" class="btn btn-sign btn-sm">
          查看父质量报告 →
        </router-link>
      </div>

      <!-- 1. Benchmark 报告视图 -->
      <template v-if="report.kind === 'benchmark'">
        <!-- 多模型核心指标并排对比 -->
        <div class="panel glow mb16 table-responsive" style="--glow-c: var(--c-reports); overflow-x: auto">
          <div class="panel-title">模型得分并排对比 (≤5 列)</div>
          <table class="ds-table">
            <thead>
              <tr>
                <th style="width: 160px">评估维度 / 指标</th>
                <th v-for="s in report.scores" :key="s.profile" class="mono" style="font-size: 13px; font-weight: 600">
                  {{ s.profile_name || s.profile }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style="font-weight: 600">主指标 (Contain 包含率)</td>
                <td v-for="s in report.scores" :key="s.profile" class="mono kpi-num" style="font-size: 22px; color: var(--c-datasets)">
                  {{ s.contain !== undefined ? s.contain.toFixed(2) : '—' }}
                </td>
              </tr>
              <tr>
                <td style="font-weight: 500">全等率 (Exact Match)</td>
                <td v-for="s in report.scores" :key="s.profile" class="mono" style="font-size: 14px">
                  {{ s.exact !== undefined ? s.exact.toFixed(2) : '—' }}
                </td>
              </tr>
              <tr>
                <td style="font-weight: 500">ROUGE-L 相似度</td>
                <td v-for="s in report.scores" :key="s.profile" class="mono" style="font-size: 14px">
                  {{ s.rouge_l !== undefined ? s.rouge_l.toFixed(2) : '—' }}
                </td>
              </tr>
              <tr>
                <td style="font-weight: 500">请求失败率</td>
                <td v-for="s in report.scores" :key="s.profile" class="mono" style="font-size: 14px" :style="s.fail_rate > 0.05 ? 'color: var(--accent-error)' : ''">
                  {{ s.fail_rate !== undefined ? (s.fail_rate * 100).toFixed(1) + '%' : '—' }}
                </td>
              </tr>
              <tr>
                <td style="font-weight: 500">平均端到端延迟</td>
                <td v-for="s in report.scores" :key="s.profile" class="mono" style="font-size: 14px">
                  {{ s.latency ?? '—' }}
                </td>
              </tr>
              <tr v-if="report.scores?.some((s) => s.judge !== undefined)">
                <td style="font-weight: 600">大模型裁判打分 (Judge)</td>
                <td v-for="s in report.scores" :key="s.profile" class="mono" style="font-size: 16px; font-weight: 700; color: var(--c-agent)">
                  {{ s.judge !== undefined ? s.judge + ' 分' : '—' }}
                </td>
              </tr>
            </tbody>
          </table>

          <!-- 基线对比横幅 -->
          <div v-if="report.baseline" class="baseline-banner mt16">
            <div class="row">
              <span style="font-size: 13px; font-weight: 500">基线对比：{{ report.baseline.name || `任务 #${report.baseline.task_id}` }}</span>
              <span class="delta-badge" :class="report.baseline.delta >= 0 ? 'pos' : 'neg'">
                Δ {{ report.baseline.delta > 0 ? '+' : '' }}{{ (report.baseline.delta * 100).toFixed(1) }}%
              </span>
            </div>
            <span style="font-size: 12px; color: var(--text-secondary)">
              {{ report.baseline.delta >= 0
                ? `主指标 contain 相对基线提升 ${(report.baseline.delta * 100).toFixed(1)}pp。`
                : `主指标 contain 相对基线退化 ${Math.abs(report.baseline.delta * 100).toFixed(1)}pp，建议排查分歧样本。` }}
            </span>
          </div>
        </div>

        <!-- 大模型裁判细分维度 -->
        <!-- 多维度对比雷达图（有得分数据时展示，对齐原型 bm-radar） -->
        <div v-if="report.scores?.length" class="panel glow mb16" style="--glow-c: var(--c-reports)">
          <div class="panel-title">多维度对比雷达图（归一化 0~1）</div>
          <RadarMetricsChart :scores="report.scores" />
        </div>

        <div v-if="report.judge_info" class="panel glow mb16" style="--glow-c: var(--c-reports)">
          <div class="row-between" style="margin-bottom: 8px">
            <div class="panel-title" style="margin-bottom: 0">
              <span>大模型裁判归因诊断 · {{ report.judge_info.profile_name }}</span>
            </div>
            <span v-if="hasJudgeScores" class="badge badge-succeeded">Judge 开启</span>
          </div>
          <div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 12px">
            打分准则：{{ report.judge_info.criteria }}
          </div>
          <div class="info-strip" style="line-height: 1.6; font-size: 13px; margin-bottom: 14px">
            <b>综合诊断结论：</b> {{ report.judge_info.reasoning_summary }}
          </div>

          <div class="judge-breakdown-grid">
            <div v-for="s in report.scores" :key="s.profile" class="judge-col">
              <div style="font-weight: 600; font-size: 13px; margin-bottom: 8px">{{ s.profile_name || s.profile }}</div>
              <div class="judge-dim-row">
                <div class="judge-dim-card">
                  <div class="judge-dim-val">{{ s.judge_breakdown?.accuracy ?? '—' }}</div>
                  <div class="judge-dim-label">准确度</div>
                </div>
                <div class="judge-dim-card">
                  <div class="judge-dim-val">{{ s.judge_breakdown?.completeness ?? '—' }}</div>
                  <div class="judge-dim-label">完整性</div>
                </div>
                <div class="judge-dim-card">
                  <div class="judge-dim-val">{{ s.judge_breakdown?.logic ?? '—' }}</div>
                  <div class="judge-dim-label">逻辑条理性</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 样本级对比与诊断 (支持全部 / 仅看差异 / 仅看失败) -->
        <div class="panel mb16">
          <div class="row-between mb16">
            <div class="panel-title" style="margin-bottom: 0">样本级输出并排对比</div>
            <div class="sample-filter-tab">
              <button :class="{ active: sampleTab === 'all' }" @click="sampleTab = 'all'">全部样本 ({{ samplesList.length }})</button>
              <button :class="{ active: sampleTab === 'diff' }" @click="sampleTab = 'diff'">仅看差异/错误 ({{ diffSamplesCount }})</button>
              <button :class="{ active: sampleTab === 'failed' }" @click="sampleTab = 'failed'">仅看失败 ({{ failedSamplesCount }})</button>
            </div>
          </div>

          <div class="sample-cards">
            <div v-for="item in filteredSamples" :key="item.row" class="sample-item">
              <div class="sample-head">
                <span class="mono sample-no">#{{ item.row }}</span>
                <span class="sample-q">{{ item.question }}</span>
                <span v-if="item.status === 'both_correct'" class="badge badge-succeeded">一致正确</span>
                <span v-else-if="item.status === 'diff_score'" class="badge badge-awaiting_case_confirm">得分分歧</span>
                <span v-else-if="item.status === 'failed'" class="badge badge-failed">请求失败</span>
              </div>

              <div class="sample-ref">
                <span class="ref-label">标准参考 (Reference):</span>
                <span>{{ item.reference }}</span>
              </div>

              <div class="sample-models-grid">
                <div class="model-pred-box" :class="{ err: item.p1?.err_code }">
                  <div class="row-between mb8">
                    <span class="mono" style="font-weight: 600; font-size: 12px">{{ report.scores?.[0]?.profile_name || 'Model 1' }}</span>
                    <div class="row" style="gap: 6px">
                      <span class="mono" style="font-size: 11px; color: var(--text-tertiary)">{{ item.p1?.lat }}</span>
                      <span v-if="item.p1?.err_code" class="status-tag-err">{{ item.p1.err_code }}</span>
                      <span class="badge" :class="item.p1?.score === 1.0 ? 'badge-succeeded' : 'badge-failed'">{{ item.p1?.score === 1.0 ? '✓ 包含' : '✕ 未包含' }}</span>
                    </div>
                  </div>
                  <div class="pred-text">{{ item.p1?.pred }}</div>
                </div>

                <div v-if="item.p2" class="model-pred-box" :class="{ err: item.p2?.err_code }">
                  <div class="row-between mb8">
                    <span class="mono" style="font-weight: 600; font-size: 12px">{{ report.scores?.[1]?.profile_name || 'Model 2' }}</span>
                    <div class="row" style="gap: 6px">
                      <span class="mono" style="font-size: 11px; color: var(--text-tertiary)">{{ item.p2?.lat }}</span>
                      <span v-if="item.p2?.err_code" class="status-tag-err">{{ item.p2.err_code }}</span>
                      <span class="badge" :class="item.p2?.score === 1.0 ? 'badge-succeeded' : 'badge-failed'">{{ item.p2?.score === 1.0 ? '✓ 包含' : '✕ 未包含' }}</span>
                    </div>
                  </div>
                  <div class="pred-text">{{ item.p2?.pred }}</div>
                </div>
              </div>

              <!-- 样本级 raw 展开：Judge 推理归因 + HTTP 原始请求/响应 -->
              <div v-if="hasRawPayload(item)" style="margin-top: 10px">
                <button class="link-btn" @click="toggleRaw(item.row)">{{ isRawExpanded(item.row) ? '收起 raw' : '展开 raw' }}</button>
                <div v-if="isRawExpanded(item.row)">
                  <div class="mono mt8" style="font-size: 11px; color: var(--text-tertiary)">Judge 裁判推理归因：</div>
                  <div style="font-size: 12.5px; color: var(--text-secondary); margin: 4px 0 8px">{{ item.judge_reason || '—' }}</div>
                  <div class="mono" style="font-size: 11px; color: var(--text-tertiary)">HTTP Raw Request / Response Inspector:</div>
                  <pre class="raw-box">{{ sampleRawJson(item) }}</pre>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 2. RAG 报告视图 -->
      <template v-else-if="report.kind === 'rag'">
        <!-- 4 种检索模式横向对比柱状条 -->
        <div class="panel glow mb16" style="--glow-c: var(--c-kb)">
          <div class="panel-title">4 种检索模式横向对比柱状条 (K={{ report.k || 5 }})</div>
          <template v-for="grp in ragMetricGroups" :key="grp.key">
            <div class="eyebrow" style="margin: 14px 0 8px">{{ grp.label }}</div>
            <div class="rc-bars" style="margin-bottom: 0">
              <div v-for="m in ragModes" :key="m" class="rc-bar-row">
                <span class="rc-bar-label" style="width: 110px; flex-basis: 110px">{{ m }}</span>
                <span class="rc-bar-track">
                  <i :style="{ width: ragBarPct(m, grp.key), background: ragBarBg(m, grp.key) }"></i>
                </span>
                <span class="rc-bar-val" :style="isDegradedHit(m, grp.key) ? 'color: var(--accent-error); font-weight: 700' : ''">
                  {{ ragBarText(m, grp.key) }}
                </span>
              </div>
            </div>
          </template>
        </div>

        <div class="panel glow mb16" style="--glow-c: var(--c-kb)">
          <div class="panel-title">RAG 多模式检索与召回指标对比 (K={{ report.k || 5 }})</div>
          <table class="ds-table">
            <thead>
              <tr>
                <th style="width: 180px">检索与回答指标</th>
                <th v-for="m in ragModes" :key="m" class="mono" :style="m === 'hybrid' ? 'color: var(--c-kb)' : ''">
                  {{ RAG_MODE_LABELS[m] || m }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style="font-weight: 600">Hit Rate@{{ report.k || 5 }} (命中率)</td>
                <td
                  v-for="m in ragModes"
                  :key="m"
                  class="mono"
                  :class="{ 'kpi-num': m === 'hybrid' }"
                  :style="m === 'hybrid' ? 'font-size: 22px; color: var(--c-kb)' : ''"
                >
                  {{ formatScore(report.rag_scores?.[m]?.hit) }}
                </td>
              </tr>
              <tr>
                <td style="font-weight: 500">MRR (平均倒数排名)</td>
                <td v-for="m in ragModes" :key="m" class="mono" :style="m === 'hybrid' ? 'font-weight: 700' : ''">
                  {{ formatScore(report.rag_scores?.[m]?.mrr) }}
                </td>
              </tr>
              <tr>
                <td style="font-weight: 500">Recall@{{ report.k || 5 }} (召回覆盖率)</td>
                <td v-for="m in ragModes" :key="m" class="mono" :style="m === 'hybrid' ? 'font-weight: 700' : ''">
                  {{ formatScore(report.rag_scores?.[m]?.recall) }}
                </td>
              </tr>
              <tr>
                <td style="font-weight: 500">答案 Contain (正确性)</td>
                <td v-for="m in ragModes" :key="m" class="mono" :style="m === 'hybrid' ? 'font-weight: 700' : ''">
                  {{ formatScore(report.rag_scores?.[m]?.contain) }}
                </td>
              </tr>
            </tbody>
          </table>

          <!-- 退化警示 -->
          <div v-if="report.degraded" class="error-strip mt16" style="border-radius: 8px">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink: 0">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
            <div>
              <b>退化预警：</b> 相对基线版本，{{ report.degraded.mode }} 检索模式命中率指标退化了
              <b style="color: var(--accent-error)">{{ Math.abs(report.degraded.pp) }} pp</b>（超出 5pp 阈值）。
            </div>
          </div>

          <div class="mt8" style="font-size: 12px; color: var(--text-tertiary)">
            {{ report.hit_note || '注：样本中未配置 expected_doc_ids 的行未计入 Hit Rate@K 命中率分母。' }}
          </div>
        </div>
      </template>

      <!-- 3. 压测报告视图 (M4) -->
      <template v-else-if="report.kind === 'stress'">
        <div class="panel glow mb16" style="--glow-c: var(--c-stress)">
          <div class="panel-title">压测执行汇总与 SLA 达标情况</div>
          <div class="kpi-grid mb16">
            <div class="kpi">
              <div class="kpi-num mono" style="color: var(--accent-info)">{{ report.qps_peak ?? '—' }}</div>
              <div class="kpi-label">峰值 QPS</div>
            </div>
            <div class="kpi">
              <div class="kpi-num mono">{{ report.p99 ?? '—' }}</div>
              <div class="kpi-label">P99 延迟</div>
            </div>
            <div class="kpi">
              <div class="kpi-num mono" style="color: var(--accent-success)">{{ report.error_rate ?? '—' }}</div>
              <div class="kpi-label">请求错误率</div>
            </div>
            <div class="kpi">
              <div class="kpi-num mono">{{ report.ttft ?? '—' }}</div>
              <div class="kpi-label">TTFT 首字延迟</div>
            </div>
            <div class="kpi">
              <div class="kpi-num mono">{{ report.est_cost ?? '—' }}</div>
              <div class="kpi-label">估算费用</div>
            </div>
          </div>

          <div v-if="report.sla_p99_ms" class="panel" style="background: var(--bg-elevated); font-size: 13px">
            <div class="row-between mb8">
              <span>SLA 阈值判定 (P99 ≤ {{ report.sla_p99_ms }}ms):</span>
              <span class="badge" :class="report.sla_met ? 'badge-succeeded' : 'badge-failed'">
                {{ report.sla_met ? '✓ SLA 达标' : '✕ 未达标' }}
              </span>
            </div>
            <div v-if="report.knee" style="font-size: 12px; color: var(--text-secondary)">
              拐点分析: {{ report.knee }}
            </div>
          </div>
        </div>

        <!-- 压测时序性能曲线（QPS / P99 RT / 错误率，对齐原型 stress-chart） -->
        <div v-if="stressSeries.length" class="panel glow mb16" style="--glow-c: var(--c-stress)">
          <div class="panel-title">时序性能曲线</div>
          <StressSeriesChart :series="stressSeries" />
        </div>
      </template>

      <!-- 配置快照页脚 -->
      <div class="panel" style="background: var(--bg-elevated)">
        <div class="panel-title" style="font-size: 13px; margin-bottom: 8px">运行参数快照 (Config Snapshot)</div>
        <div style="font-size: 12px; color: var(--text-secondary); line-height: 1.6">
          <span class="mono">{{ report.snapshot ? JSON.stringify(report.snapshot) : '—' }}</span>
        </div>
      </div>
    </template>

    <!-- 加载中与加载失败空态（不保留任何默认报告对象） -->
    <div v-else-if="loading" class="empty" style="min-height: 320px">
      <div style="font-size: 13px; color: var(--text-tertiary)">报告加载中…</div>
    </div>
    <EmptyState
      v-else
      title="报告未加载"
      description="未能从服务端获取报告数据，请检查登录态、接口地址与报告 ID 后重试。"
    >
      <template #action>
        <button class="btn btn-secondary btn-sm" @click="loadReport">重新加载</button>
      </template>
    </EmptyState>

    <!-- 弹窗 -->
    <ShareModal
      v-model:show="showShareModal"
      :share-url="shareUrl"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api/http'
import type { Report, RagScores, StressSeriesPoint } from '../api/types'
import KindTag from '../components/common/KindTag.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ShareModal from '../components/modals/ShareModal.vue'
import RadarMetricsChart from '../components/charts/RadarMetricsChart.vue'
import StressSeriesChart from '../components/charts/StressSeriesChart.vue'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()

// /reports 列表路由与 /reports/:id 详情路由复用本组件；无 id 时不得发起 /api/reports/undefined 请求
const reportId = computed(() => (route.params.id as string) || '')
// 报告数据仅来自服务端 / Mock 夹具，加载失败时保持 null 并展示空态
const report = ref<Report | null>(null)
const loading = ref(true)

const showShareModal = ref(false)
const shareUrl = ref('')
const sampleTab = ref<'all' | 'diff' | 'failed'>('all')
// 压测时序数据：优先取报告内嵌 series，缺失时回退调 stress-series 接口补齐
const stressSeries = ref<StressSeriesPoint[]>([])

// 样本明细完全取自报告数据，缺失时为空列表（不再内置演示样本）
const samplesList = computed(() => report.value?.sample_items || [])

const diffSamplesCount = computed(() => samplesList.value.filter((x: any) => x.status === 'diff_score' || x.status === 'failed').length)
const failedSamplesCount = computed(() => samplesList.value.filter((x: any) => x.status === 'failed').length)

const filteredSamples = computed(() => {
  if (sampleTab.value === 'diff') return samplesList.value.filter((x: any) => x.status === 'diff_score' || x.status === 'failed')
  if (sampleTab.value === 'failed') return samplesList.value.filter((x: any) => x.status === 'failed')
  return samplesList.value
})

// 任一协议档存在 Judge 打分时，裁判专区标题右侧展示「Judge 开启」徽章
const hasJudgeScores = computed(() => !!report.value?.scores?.some((s) => s.judge !== undefined))

// RAG 检索模式中文标签（表头展示用）
const RAG_MODE_LABELS: Record<string, string> = {
  naive: 'Naive (传统分块)',
  local: 'Local (局部关系)',
  global: 'Global (全局摘要)',
  hybrid: 'Hybrid (混合图谱)',
}

// RAG 模式专属配色（对齐原型 report.html：naive 灰 / local 靛 / global 青 / hybrid 蓝）
const RAG_MODE_COLORS: Record<string, string> = {
  naive: '#9CA3AF',
  local: '#4F46E5',
  global: '#0E7490',
  hybrid: '#1D4ED8',
}

type RagMetricKey = 'hit' | 'mrr' | 'recall' | 'contain'

// 模式列动态渲染：report.modes 缺失时按平台固定四模式兜底（指标值缺失仍显示 —）
const ragModes = computed<Array<'naive' | 'local' | 'global' | 'hybrid'>>(() =>
  report.value?.modes?.length ? report.value.modes : ['naive', 'local', 'global', 'hybrid'],
)

// 柱状条按 4 个指标分组渲染
const ragMetricGroups = computed<Array<{ key: RagMetricKey; label: string }>>(() => {
  const k = report.value?.k || 5
  return [
    { key: 'hit', label: `Hit Rate@${k}` },
    { key: 'mrr', label: 'MRR (平均倒数排名)' },
    { key: 'recall', label: `Recall@${k}` },
    { key: 'contain', label: '答案规则分 contain' },
  ]
})

// 读取某模式某指标得分，缺失返回 undefined 由调用方降级为「—」
function ragModeScore(mode: string, metric: RagMetricKey): number | undefined {
  return report.value?.rag_scores?.[mode as keyof RagScores]?.[metric]
}

// 退化标红仅作用于 Hit Rate 组内 degraded.mode 指定的模式（对齐原型口径）
function isDegradedHit(mode: string, metric: RagMetricKey): boolean {
  return metric === 'hit' && report.value?.degraded?.mode === mode
}

function ragBarPct(mode: string, metric: RagMetricKey): string {
  const v = ragModeScore(mode, metric)
  return `${Math.round((v ?? 0) * 100)}%`
}

function ragBarBg(mode: string, metric: RagMetricKey): string {
  return isDegradedHit(mode, metric) ? 'var(--accent-error)' : RAG_MODE_COLORS[mode] || 'var(--c-datasets)'
}

function ragBarText(mode: string, metric: RagMetricKey): string {
  const v = ragModeScore(mode, metric)
  return v === undefined ? '—' : v.toFixed(2)
}

// 已展开 raw 的样本行号集合（用新 Set 赋值保证响应式触发）
const expandedRawRows = ref<Set<number>>(new Set())

function toggleRaw(row: number) {
  const next = new Set(expandedRawRows.value)
  if (next.has(row)) next.delete(row)
  else next.add(row)
  expandedRawRows.value = next
}

function isRawExpanded(row: number): boolean {
  return expandedRawRows.value.has(row)
}

// 样本存在裁判归因或任一模型输出时才展示「展开 raw」入口
function hasRawPayload(item: any): boolean {
  return !!(item.judge_reason || item.p1 || item.p2)
}

// 拼装样本级 raw request/response JSON（字段对齐原型 Inspector）
function sampleRawJson(item: any): string {
  const scores = report.value?.scores || []
  return JSON.stringify(
    {
      sample_row: item.row,
      p1_model: scores[0]?.profile_name || scores[0]?.profile,
      p1_latency_ms: item.p1?.lat,
      p1_raw_response: item.p1?.pred,
      p2_model: scores[1]?.profile_name || scores[1]?.profile,
      p2_latency_ms: item.p2?.lat,
      p2_raw_response: item.p2?.pred,
    },
    null,
    2,
  )
}

function formatDate(d?: string) {
  if (!d) return ''
  return new Date(d).toLocaleString('zh-CN', { hour12: false })
}

function formatScore(val?: number) {
  if (val === undefined) return '—'
  return val.toFixed(2)
}

async function loadReport() {
  if (!reportId.value) {
    // 列表路由无报告 ID：直接展示空态（对齐原型 report.html 实时模式无数据行为）
    report.value = null
    loading.value = false
    return
  }
  loading.value = true
  stressSeries.value = []
  try {
    report.value = await api.reports.get(reportId.value)
    // 压测报告：报告内嵌 series 缺失时，额外拉取 stress-series 时序接口（对齐原型 live 行为）
    if (report.value?.kind === 'stress') {
      if (report.value.series?.length) {
        stressSeries.value = report.value.series
      } else if (report.value.task_id) {
        try {
          const res = await api.tasks.getStressSeries(report.value.task_id)
          // 契约字段为 points；mock 与早期实现使用 series，两者兼容读取
          stressSeries.value = res?.points || res?.series || []
        } catch {
          // 时序接口失败不阻断报告主体展示
          stressSeries.value = []
        }
      }
    }
  } catch (err: any) {
    report.value = null
    message.error(err.message || '加载报告失败')
  } finally {
    loading.value = false
  }
}

async function openShareModal() {
  try {
    const res = await api.reports.share(reportId.value, 7)
    shareUrl.value = res.share_url
    showShareModal.value = true
  } catch (err: any) {
    message.error(err.message || '获取分享链接失败')
  }
}

// 导出 Markdown：内容由服务端（GET /api/reports/{id}?fmt=md）或 Mock 夹具生成，前端仅触发 Blob 下载
async function handleExportMd() {
  try {
    const md = await api.reports.get(reportId.value, 'md')
    const blob = new Blob([md], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `Report-${reportId.value}.md`
    a.click()
    URL.revokeObjectURL(url)
    message.success('Markdown 报告已导出')
  } catch (err: any) {
    message.error(err.message || '导出失败')
  }
}

function handleFreezeBaseline() {
  dialog.warning({
    title: '冻结为基线报告？',
    content: '冻结后，后续相同数据集与指标的评测任务将自动以本报告得分作为对比基线。',
    positiveText: '确认冻结',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.reports.freezeBaseline(reportId.value)
        message.success('已冻结为基线')
      } catch (err: any) {
        message.error(err.message || '冻结失败')
      }
    },
  })
}

function handleInterpret() {
  router.push({
    path: '/agent',
    query: { report_id: reportId.value },
  })
}

onMounted(loadReport)
// 同组件内切换报告（如先评后压横幅互跳）时按新 id 重新加载
watch(reportId, () => loadReport())
</script>

<style scoped>
.report-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.cascade-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-radius: 12px;
  background: rgba(14, 116, 144, 0.08);
  border: 1px solid rgba(14, 116, 144, 0.25);
  margin-bottom: 8px;
}

.baseline-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(99, 102, 241, 0.22);
}
.delta-badge {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 6px;
}
.delta-badge.pos {
  background: rgba(16, 185, 129, 0.15);
  color: var(--accent-success);
}
.delta-badge.neg {
  background: rgba(239, 68, 68, 0.15);
  color: var(--accent-error);
}

.judge-breakdown-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.judge-col {
  padding: 12px;
  background: var(--bg-elevated);
  border-radius: 10px;
  border: 1px solid var(--border-subtle);
}
.judge-dim-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.judge-dim-card {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  text-align: center;
}
.judge-dim-val {
  font-family: var(--font-mono);
  font-size: 16px;
  font-weight: 700;
  color: var(--c-agent);
}
.judge-dim-label {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.sample-filter-tab {
  display: inline-flex;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 2px;
  background: var(--bg-elevated);
}
.sample-filter-tab button {
  border: 0;
  background: transparent;
  padding: 4px 12px;
  font-size: 12px;
  border-radius: 6px;
  cursor: pointer;
  color: var(--text-secondary);
}
.sample-filter-tab button.active {
  background: var(--text-primary);
  color: #fff;
  font-weight: 600;
}

.sample-cards {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.sample-item {
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 14px 16px;
  background: var(--bg-main);
}
.sample-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.sample-no {
  font-size: 12px;
  font-weight: 700;
  color: var(--c-datasets);
}
.sample-q {
  font-size: 14px;
  font-weight: 600;
  flex: 1;
}

.sample-ref {
  font-size: 12.5px;
  color: var(--text-secondary);
  margin-bottom: 12px;
  background: var(--bg-elevated);
  padding: 6px 10px;
  border-radius: 6px;
}
.ref-label {
  font-weight: 600;
  margin-right: 6px;
  color: var(--text-primary);
}

.sample-models-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.model-pred-box {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--bg-elevated);
}
.model-pred-box.err {
  border-color: rgba(239, 68, 68, 0.35);
  background: rgba(239, 68, 68, 0.04);
}
.pred-text {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-primary);
}

/* 样本失败行的错误码徽标（mono 字体、红底浅字，对齐原型 .status-tag-err） */
.status-tag-err {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  font-family: var(--font-mono);
  background: rgba(239, 68, 68, 0.12);
  color: var(--accent-error);
  border: 1px solid rgba(239, 68, 68, 0.3);
}

/* 样本 raw 展开区：深色 JSON 查看器（对齐原型 .raw-box） */
.raw-box {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.6;
  max-height: 180px;
  overflow-y: auto;
  margin-top: 6px;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 移动端：并排对比栅格折为单列 */
@media (max-width: 700px) {
  .judge-breakdown-grid,
  .sample-models-grid {
    grid-template-columns: 1fr;
  }
}
</style>
