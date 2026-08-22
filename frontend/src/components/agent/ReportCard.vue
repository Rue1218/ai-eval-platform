<template>
  <div class="report-card">
    <div class="rc-head">
      <span class="kind-tag" :class="`kind-${report.kind || 'benchmark'}`">{{ kindLabel }}</span>
      <span class="rc-title">{{ report.title || '评测报告已生成' }}</span>
    </div>

    <!-- Benchmark 得分对比条 -->
    <div v-if="report.scores && report.scores.length" class="rc-bars">
      <div v-for="item in report.scores" :key="item.profile" class="rc-bar-row">
        <span class="rc-bar-label">{{ item.profile_name || item.profile }}</span>
        <div class="rc-bar-track">
          <i :style="{ width: `${Math.round((item.contain || item.exact || 0.8) * 100)}%` }"></i>
        </div>
        <span class="rc-bar-val mono">{{ (item.contain || item.exact || 0.8).toFixed(2) }}</span>
      </div>
    </div>

    <!-- RAG / 压测 KPI -->
    <div v-else-if="report.rag_scores" class="report-card-kpis">
      <div class="kpi-item">
        <div class="kpi-num">{{ report.rag_scores.hybrid?.hit ? (report.rag_scores.hybrid.hit * 100).toFixed(0) : 80 }}<span class="unit">%</span></div>
        <div class="kpi-label">Hit Rate@5</div>
      </div>
      <div class="kpi-item">
        <div class="kpi-num">{{ report.rag_scores.hybrid?.mrr ? report.rag_scores.hybrid.mrr.toFixed(2) : '0.74' }}</div>
        <div class="kpi-label">MRR</div>
      </div>
      <div class="kpi-item">
        <div class="kpi-num">{{ report.rag_scores.hybrid?.contain ? (report.rag_scores.hybrid.contain * 100).toFixed(0) : 83 }}<span class="unit">%</span></div>
        <div class="kpi-label">答案 Contain</div>
      </div>
    </div>

    <!-- 底部操作按钮 -->
    <div class="rc-foot">
      <button class="btn btn-secondary btn-sm" @click="handleInterpret">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
        <span>在对话中解读</span>
      </button>
      <router-link :to="`/reports/${report.id || reportId}`" class="btn btn-sign btn-sm">
        <span>查看完整报告</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="9 18 15 12 9 6"></polyline>
        </svg>
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '../../api/http'
import type { Report } from '../../api/types'

const props = defineProps<{
  reportId: string
}>()

const emit = defineEmits<{
  (e: 'interpret', reportId: string): void
}>()

const report = ref<Partial<Report>>({
  id: props.reportId,
  kind: 'benchmark',
  title: '评测报告',
})

const kindLabel = computed(() => {
  const map: Record<string, string> = {
    benchmark: '基准评测',
    rag: 'RAG 评测',
    stress: '压测报告',
    testcase: '用例报告',
  }
  return map[report.value.kind || 'benchmark'] || '报告'
})

async function fetchReport() {
  try {
    const data = await api.reports.get(props.reportId)
    report.value = data
  } catch (e) {
    console.error('Failed to load report for card:', e)
  }
}

function handleInterpret() {
  emit('interpret', props.reportId)
}

onMounted(fetchReport)
</script>

<style scoped>
.report-card {
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--bg-main);
  padding: 16px 20px;
  box-shadow: 0 4px 16px rgba(17, 24, 39, 0.06);
  max-width: 640px;
  animation: card-up 0.3s cubic-bezier(0.2, 0.9, 0.3, 1.05);
}
@keyframes card-up {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.rc-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.rc-title {
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rc-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 10px 0 14px;
}
.rc-bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.rc-bar-label {
  width: 120px;
  flex: 0 0 120px;
  font-size: 12px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rc-bar-track {
  flex: 1;
  height: 8px;
  border-radius: 999px;
  background: var(--bg-elevated);
  overflow: hidden;
}
.rc-bar-track > i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--c-datasets);
  animation: bar-grow 0.5s cubic-bezier(0.2, 0.9, 0.3, 1) both;
}
@keyframes bar-grow {
  from {
    width: 0;
  }
}
.rc-bar-val {
  width: 38px;
  flex: 0 0 38px;
  text-align: right;
  font-size: 12px;
  font-weight: 600;
}

.report-card-kpis {
  display: flex;
  gap: 24px;
  margin: 10px 0 14px;
}
.kpi-item .kpi-num {
  font-size: 20px;
  font-weight: 700;
}
.kpi-item .unit {
  font-size: 12px;
  color: var(--text-tertiary);
}
.kpi-item .kpi-label {
  font-size: 11px;
  color: var(--text-secondary);
}

.rc-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
}

@media (max-width: 640px) {
  .report-card {
    padding: 12px 14px;
  }
  .rc-bar-label {
    width: 90px;
    flex: 0 0 90px;
  }
  .report-card-kpis {
    gap: 14px;
  }
  .rc-foot {
    flex-wrap: wrap;
  }
  .rc-foot .btn {
    flex: 1 1 calc(50% - 6px);
    justify-content: center;
  }
}
</style>
