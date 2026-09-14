<template>
  <article
    class="task-run-card"
    :class="`is-${snapshot.status || tool.status}`"
    :data-task-tool="snapshot.action"
    :data-task-id="snapshot.taskId || undefined"
  >
    <header class="task-run-summary">
      <span class="task-run-icon"><ToolIcon :name="snapshot.action" /></span>
      <span class="task-run-title">
        <strong>{{ taskActionLabels[snapshot.action] || snapshot.action }}</strong>
        <small>{{ snapshot.taskId || '等待任务编号返回' }}</small>
      </span>
      <span class="task-run-state">{{ taskStatusLabels[snapshot.status || ''] || statusLabels[tool.status] || tool.status }}</span>
    </header>

    <div class="task-run-body">
      <div v-if="snapshot.progress || snapshot.status === 'queued' || snapshot.status === 'running'" class="task-run-progress">
        <div class="task-run-progress-head">
          <span>{{ snapshot.message || (snapshot.status === 'queued' ? '已入队，等待 Worker 执行' : '正在同步 Worker 进度') }}</span>
          <strong v-if="percent !== null">{{ percent }}%</strong>
        </div>
        <div class="task-run-progress-track" role="progressbar" :aria-valuenow="percent ?? undefined" aria-valuemin="0" aria-valuemax="100">
          <i :style="{ width: `${percent ?? 8}%` }" />
        </div>
      </div>

      <dl class="task-run-meta">
        <template v-if="snapshot.kind"><dt>类型</dt><dd>{{ snapshot.kind }}</dd></template>
        <template v-if="snapshot.taskId"><dt>任务</dt><dd class="task-run-id">{{ snapshot.taskId }}</dd></template>
      </dl>

      <router-link v-if="snapshot.reportId" class="task-run-report" :to="`/reports/${snapshot.reportId}`">查看评测报告</router-link>

      <details class="task-run-details">
        <summary>调用详情</summary>
        <section>
          <h4>参数</h4>
          <pre>{{ tool.display.arguments_preview ?? '尚未提供安全参数预览' }}</pre>
        </section>
        <section v-if="tool.event === 'tool.result'">
          <h4>结果</h4>
          <pre>{{ tool.display.result_preview === '' ? '（空输出）' : tool.display.result_preview ?? '未提供结果预览' }}</pre>
        </section>
      </details>

      <p v-if="tool.display.truncated" class="task-run-notice">预览已截断，未提供完整结果接口。</p>
      <p v-if="tool.display.unavailable_reason" class="task-run-notice">{{ tool.display.unavailable_reason }}</p>
      <ToolInteraction v-for="interaction in interactions.filter(item => item.kind === 'task_confirmation')" :key="interaction.key" :interaction="interaction" :can-control="canControl" :online="online" @respond="(record, data) => emit('respond', record, data)" />
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Data, InteractionRecord, LoopRecord, ToolRun } from '../../../api/agentLoopTypes'
import { taskActionLabels, taskCardSnapshot, taskProgressPercent, taskStatusLabels } from '../../../agent/loop/taskPresentation'
import { statusLabels } from '../../../agent/loop/toolPresentation'
import ToolIcon from './ToolIcon.vue'
import ToolInteraction from './ToolInteraction.vue'

const props = defineProps<{
  tool: ToolRun
  task?: LoopRecord | null
  interactions: InteractionRecord[]
  canControl: boolean
  online: boolean
}>()
const emit = defineEmits<{ respond: [InteractionRecord, Data] }>()

/** 任务卡片用持久 Worker 事实刷新，不把一次工具调用的旧结果误认为最终状态。 */
const snapshot = computed(() => taskCardSnapshot(props.tool, props.task))
const percent = computed(() => taskProgressPercent(snapshot.value.progress))
</script>

<style scoped>
.task-run-card{margin:10px 0;border:1px solid #cfe3d8;border-radius:12px;background:#fbfefc;box-shadow:0 7px 22px rgba(20,68,50,.06);overflow:hidden;font-family:var(--font-body)}
.task-run-summary{display:flex;align-items:center;gap:10px;padding:13px 15px;background:#f4fbf7;border-bottom:1px solid #e1eee6}
.task-run-icon{display:grid;place-items:center;width:32px;height:32px;border-radius:9px;background:#e2f3e9;color:#167052}.task-run-icon :deep(svg){width:18px;height:18px}
.task-run-title{display:flex;flex:1;min-width:0;flex-direction:column;gap:2px}.task-run-title strong{color:#193a2c;font-size:14px;font-weight:680}.task-run-title small{overflow:hidden;color:#6b8075;font:12px/1.3 var(--font-mono);text-overflow:ellipsis;white-space:nowrap}
.task-run-state{flex:0 0 auto;padding:4px 8px;border-radius:999px;background:#e0f4e8;color:#176c50;font-size:12px;font-weight:650}.is-failed .task-run-state,.is-cancelled .task-run-state{background:#fff0e9;color:#a44a27}
.task-run-body{padding:13px 15px 15px}.task-run-progress{margin-bottom:12px}.task-run-progress-head{display:flex;justify-content:space-between;gap:12px;color:#536b5e;font-size:12px;line-height:1.45}.task-run-progress-head strong{color:#1b7557;font-variant-numeric:tabular-nums}
.task-run-progress-track{height:6px;margin-top:7px;overflow:hidden;border-radius:99px;background:#e3eee7}.task-run-progress-track i{display:block;min-width:8px;height:100%;border-radius:inherit;background:#2aa376;transition:width .42s cubic-bezier(.2,.8,.2,1)}
.task-run-meta{display:grid;grid-template-columns:auto minmax(0,1fr);gap:5px 10px;margin:0;color:#536b5e;font-size:12px}.task-run-meta dt{color:#83968b}.task-run-meta dd{min-width:0;margin:0;overflow-wrap:anywhere}.task-run-id{color:#37584a;font-family:var(--font-mono);font-size:11.5px}
.task-run-report{display:inline-flex;margin-top:12px;color:#177457;font-size:12px;font-weight:650;text-decoration:none}.task-run-report:hover{text-decoration:underline}
.task-run-details{margin-top:12px;border-top:1px solid #e4eee8;padding-top:10px}.task-run-details>summary{color:#587166;font-size:12px;cursor:pointer}.task-run-details section{margin-top:10px}.task-run-details h4{margin:0 0 5px;color:#637a6f;font-size:12px}.task-run-details pre{max-height:280px;overflow:auto;margin:0;border:1px solid #dceae2;border-radius:7px;background:#f7fbf8;padding:9px;color:#285542;font:12px/1.6 var(--font-mono);overflow-wrap:anywhere;white-space:pre-wrap}.task-run-notice{margin:10px 0 0;color:#86623d;font-size:12px}
[data-theme='dark'] .task-run-card{border-color:rgba(72,187,120,.25);background:#12251d;box-shadow:none}.task-run-summary{background:#173325;border-color:rgba(255,255,255,.08)}[data-theme='dark'] .task-run-icon{background:rgba(52,211,153,.16);color:#6ee7b7}[data-theme='dark'] .task-run-title strong{color:#e5f7ec}[data-theme='dark'] .task-run-title small,[data-theme='dark'] .task-run-meta{color:#afc8ba}[data-theme='dark'] .task-run-meta dt{color:#779587}[data-theme='dark'] .task-run-id{color:#c2ead3}[data-theme='dark'] .task-run-progress-head{color:#c4d9cd}[data-theme='dark'] .task-run-progress-track{background:#294638}[data-theme='dark'] .task-run-details{border-color:rgba(255,255,255,.1)}[data-theme='dark'] .task-run-details>summary,[data-theme='dark'] .task-run-details h4{color:#bbd4c6}[data-theme='dark'] .task-run-details pre{border-color:rgba(255,255,255,.1);background:#0e1b15;color:#c7ead5}
@media(prefers-reduced-motion:reduce){.task-run-progress-track i{transition:none}}
</style>
