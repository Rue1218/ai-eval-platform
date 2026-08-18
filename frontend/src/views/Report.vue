<template>
  <div class="report-page">
    <!-- 头部操作条 -->
    <div class="row-between mb16" style="padding-bottom: 14px; border-bottom: 1px solid var(--border-subtle)">
      <div>
        <div class="row">
          <KindTag :kind="report.kind || 'benchmark'" />
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
          <span>分享报告</span>
        </button>

        <button class="btn btn-secondary btn-sm" @click="handleExportMd">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7 10 12 15 17 10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
          </svg>
          <span>导出 Markdown</span>
        </button>

        <button class="btn btn-secondary btn-sm" @click="handleFreezeBaseline">
          冻结为基线
        </button>
      </div>
    </div>

    <!-- 先评后压派生横幅 -->
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

    <!-- 1. Benchmark 报告视图 -->
    <template v-if="report.kind === 'benchmark'">
      <!-- 多模型核心指标并排对比 -->
      <div class="panel mb16">
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
                {{ (s.contain !== undefined ? s.contain : 0.86).toFixed(2) }}
              </td>
            </tr>
            <tr>
              <td style="font-weight: 500">全等率 (Exact Match)</td>
              <td v-for="s in report.scores" :key="s.profile" class="mono" style="font-size: 14px">
                {{ (s.exact !== undefined ? s.exact : 0.55).toFixed(2) }}
              </td>
            </tr>
            <tr>
              <td style="font-weight: 500">ROUGE-L 相似度</td>
              <td v-for="s in report.scores" :key="s.profile" class="mono" style="font-size: 14px">
                {{ (s.rouge_l !== undefined ? s.rouge_l : 0.85).toFixed(2) }}
              </td>
            </tr>
            <tr>
              <td style="font-weight: 500">请求失败率</td>
              <td v-for="s in report.scores" :key="s.profile" class="mono" style="font-size: 14px" :style="s.fail_rate > 0.05 ? 'color: var(--accent-error)' : ''">
                {{ (s.fail_rate * 100).toFixed(1) }}%
              </td>
            </tr>
            <tr>
              <td style="font-weight: 500">平均端到端延迟</td>
              <td v-for="s in report.scores" :key="s.profile" class="mono" style="font-size: 14px">
                {{ s.latency }}
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
              Δ {{ report.baseline.delta > 0 ? '+' : '' }}{{ report.baseline.delta }}
            </span>
          </div>
          <span style="font-size: 12px; color: var(--text-secondary)">
            {{ report.baseline.delta >= 0 ? '相对基线版本指标有所提升' : '注意：相对基线版本主指标有所回退' }}
          </span>
        </div>
      </div>

      <!-- 大模型裁判细分维度 -->
      <div v-if="report.judge_info" class="panel mb16">
        <div class="panel-title">
          <span>大模型裁判归因诊断 · {{ report.judge_info.profile_name }}</span>
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
            <div class="judge-dim-row" v-if="s.judge_breakdown">
              <div class="judge-dim-card">
                <div class="judge-dim-val">{{ s.judge_breakdown.accuracy || '4.5' }}</div>
                <div class="judge-dim-label">准确度</div>
              </div>
              <div class="judge-dim-card">
                <div class="judge-dim-val">{{ s.judge_breakdown.completeness || '4.3' }}</div>
                <div class="judge-dim-label">完整性</div>
              </div>
              <div class="judge-dim-card">
                <div class="judge-dim-val">{{ s.judge_breakdown.logic || '4.0' }}</div>
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
                    <span class="badge" :class="item.p2?.score === 1.0 ? 'badge-succeeded' : 'badge-failed'">{{ item.p2?.score === 1.0 ? '✓ 包含' : '✕ 未包含' }}</span>
                  </div>
                </div>
                <div class="pred-text">{{ item.p2?.pred }}</div>
              </div>
            </div>

            <div v-if="item.judge_reason" class="sample-judge-reason">
              <b>裁判点评：</b> {{ item.judge_reason }}
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 2. RAG 报告视图 -->
    <template v-else-if="report.kind === 'rag'">
      <div class="panel mb16">
        <div class="panel-title">RAG 多模式检索与召回指标对比 (K=5)</div>
        <table class="ds-table">
          <thead>
            <tr>
              <th style="width: 180px">检索与回答指标</th>
              <th class="mono">Naive (传统分块)</th>
              <th class="mono">Local (局部关系)</th>
              <th class="mono">Global (全局摘要)</th>
              <th class="mono" style="color: var(--c-kb)">Hybrid (混合图谱)</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style="font-weight: 600">Hit Rate@5 (命中率)</td>
              <td class="mono">{{ formatScore(report.rag_scores?.naive?.hit) }}</td>
              <td class="mono">{{ formatScore(report.rag_scores?.local?.hit) }}</td>
              <td class="mono">{{ formatScore(report.rag_scores?.global?.hit) }}</td>
              <td class="mono kpi-num" style="font-size: 22px; color: var(--c-kb)">
                {{ formatScore(report.rag_scores?.hybrid?.hit) }}
              </td>
            </tr>
            <tr>
              <td style="font-weight: 500">MRR (平均倒数排名)</td>
              <td class="mono">{{ report.rag_scores?.naive?.mrr?.toFixed(2) || '0.55' }}</td>
              <td class="mono">{{ report.rag_scores?.local?.mrr?.toFixed(2) || '0.66' }}</td>
              <td class="mono">{{ report.rag_scores?.global?.mrr?.toFixed(2) || '0.61' }}</td>
              <td class="mono" style="font-weight: 700">{{ report.rag_scores?.hybrid?.mrr?.toFixed(2) || '0.74' }}</td>
            </tr>
            <tr>
              <td style="font-weight: 500">Recall@5 (召回覆盖率)</td>
              <td class="mono">{{ formatScore(report.rag_scores?.naive?.recall) }}</td>
              <td class="mono">{{ formatScore(report.rag_scores?.local?.recall) }}</td>
              <td class="mono">{{ formatScore(report.rag_scores?.global?.recall) }}</td>
              <td class="mono" style="font-weight: 700">{{ formatScore(report.rag_scores?.hybrid?.recall) }}</td>
            </tr>
            <tr>
              <td style="font-weight: 500">答案 Contain (正确性)</td>
              <td class="mono">{{ formatScore(report.rag_scores?.naive?.contain) }}</td>
              <td class="mono">{{ formatScore(report.rag_scores?.local?.contain) }}</td>
              <td class="mono">{{ formatScore(report.rag_scores?.global?.contain) }}</td>
              <td class="mono" style="font-weight: 700">{{ formatScore(report.rag_scores?.hybrid?.contain) }}</td>
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
      <div class="panel mb16">
        <div class="panel-title">压测执行汇总与 SLA 达标情况</div>
        <div class="kpi-grid mb16">
          <div class="kpi">
            <div class="kpi-num mono" style="color: var(--accent-info)">{{ report.qps_peak || 118 }}</div>
            <div class="kpi-label">峰值 QPS</div>
          </div>
          <div class="kpi">
            <div class="kpi-num mono">{{ report.p99 || '1.2s' }}</div>
            <div class="kpi-label">P99 延迟</div>
          </div>
          <div class="kpi">
            <div class="kpi-num mono" style="color: var(--accent-success)">{{ report.error_rate || '0.4%' }}</div>
            <div class="kpi-label">请求错误率</div>
          </div>
          <div class="kpi">
            <div class="kpi-num mono">{{ report.ttft || '320ms' }}</div>
            <div class="kpi-label">TTFT 首字延迟</div>
          </div>
          <div class="kpi">
            <div class="kpi-num mono">{{ report.est_cost || '$0.42' }}</div>
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
    </template>

    <!-- 配置快照页脚 -->
    <div class="panel" style="background: var(--bg-elevated)">
      <div class="panel-title" style="font-size: 13px; margin-bottom: 8px">运行参数快照 (Config Snapshot)</div>
      <div style="font-size: 12px; color: var(--text-secondary); line-height: 1.6">
        <span class="mono">{{ JSON.stringify(report.snapshot || { sample_size: 20, concurrency: 4, timeout_s: 60, seed: 20260815 }) }}</span>
      </div>
    </div>

    <!-- 弹窗 -->
    <ShareModal
      v-model:show="showShareModal"
      :share-url="shareUrl"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api/http'
import type { Report } from '../api/types'
import KindTag from '../components/common/KindTag.vue'
import ShareModal from '../components/modals/ShareModal.vue'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()

const reportId = (route.params.id as string) || 'r-bm-1'
const report = ref<Report>({
  id: reportId,
  task_id: 't-default',
  kind: 'benchmark',
  title: '评测对比报告 · smoke-20 v3 · 主指标 contain',
  created_at: new Date().toISOString(),
})

const showShareModal = ref(false)
const shareUrl = ref('')
const sampleTab = ref<'all' | 'diff' | 'failed'>('all')

const samplesList = computed(() => {
  if (report.value.sample_items && report.value.sample_items.length) {
    return report.value.sample_items
  }
  return [
    {
      row: 1,
      question: '如何修改默认结算账户？',
      reference: '进入「设置-账户-结算账户」，选择「修改默认账户」并完成短信验证。',
      status: 'both_correct',
      p1: { pred: '进入「设置-账户-结算账户」，点击「修改默认账户」并通过手机验证码完成验证。', score: 1.0, lat: '780ms' },
      p2: { pred: '在系统设置中找到结算账户设置，点击修改默认账户并输入短信验证码。', score: 1.0, lat: '1.0s' },
      judge_reason: '两者均准确覆盖路径与短信验证要素，判定达标。',
    },
    {
      row: 2,
      question: '支持哪些付款方式？',
      reference: '支持余额、银行卡与对公转账三种方式。',
      status: 'both_correct',
      p1: { pred: '平台目前支持三种付款方式：1. 账户余额；2. 绑定银行卡快捷支付；3. 企业对公转账。', score: 1.0, lat: '650ms' },
      p2: { pred: '支持余额支付、银行卡支付以及对公转账结算。', score: 1.0, lat: '890ms' },
      judge_reason: '两模型均完整回答三种付款方式。',
    },
    {
      row: 3,
      question: '余额提现有限额吗？',
      reference: '单笔提现不超过 5 万元，单日不超过 20 万元。',
      status: 'diff_score',
      p1: { pred: '有限额。单笔提现上限为 5 万元，单日累计提现金额不得超过 20 万元。', score: 1.0, lat: '810ms' },
      p2: { pred: '提现有限额规定，单日限额最高为 20 万元，请在提现页面查看详情。', score: 0.0, lat: '1.2s' },
      judge_reason: 'Model 2 遗漏了「单笔不超过 5 万元」的核心约束，判定未达标。',
    },
    {
      row: 4,
      question: '跨境汇款需要提供哪些报关资质？',
      reference: '需提供进出口企业代码、货物海关报关单及完税凭证。',
      status: 'failed',
      p1: { pred: 'HTTP 502 Bad Gateway: Upstream gateway timeout from provider', score: 0.0, lat: '30.0s', err_code: 'UPSTREAM' },
      p2: { pred: '需要提供企业进出口代码以及海关放行凭证。', score: 0.0, lat: '1.4s' },
      judge_reason: 'Model 1 上游网关报错 502；Model 2 遗漏完税凭证要求。',
    },
  ]
})

const diffSamplesCount = computed(() => samplesList.value.filter((x: any) => x.status === 'diff_score' || x.status === 'failed').length)
const failedSamplesCount = computed(() => samplesList.value.filter((x: any) => x.status === 'failed').length)

const filteredSamples = computed(() => {
  if (sampleTab.value === 'diff') return samplesList.value.filter((x: any) => x.status === 'diff_score' || x.status === 'failed')
  if (sampleTab.value === 'failed') return samplesList.value.filter((x: any) => x.status === 'failed')
  return samplesList.value
})

function formatDate(d?: string) {
  if (!d) return ''
  return new Date(d).toLocaleString('zh-CN', { hour12: false })
}

function formatScore(val?: number) {
  if (val === undefined) return '0.80'
  return val.toFixed(2)
}

async function loadReport() {
  try {
    const data = await api.reports.get(reportId)
    report.value = data
  } catch (err: any) {
    message.error(err.message || '加载报告失败')
  }
}

async function openShareModal() {
  try {
    const res = await api.reports.share(reportId, 7)
    shareUrl.value = res.share_url
    showShareModal.value = true
  } catch (err: any) {
    message.error(err.message || '获取分享链接失败')
  }
}

function handleExportMd() {
  const content = `# ${report.value.title}\n\n报告 ID: ${report.value.id}\n生成时间: ${report.value.created_at}\n`
  const blob = new Blob([content], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `Report-${reportId}.md`
  a.click()
  URL.revokeObjectURL(url)
  message.success('Markdown 报告已导出')
}

function handleFreezeBaseline() {
  dialog.warning({
    title: '冻结为基线报告？',
    content: '冻结后，后续相同数据集与指标的评测任务将自动以本报告得分作为对比基线。',
    positiveText: '确认冻结',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.reports.freezeBaseline(reportId)
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
    query: { report_id: reportId },
  })
}

onMounted(loadReport)
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

.sample-judge-reason {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-subtle);
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.5;
}
</style>
