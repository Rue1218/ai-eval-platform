<template>
  <n-drawer :show="show" :width="520" @update:show="$emit('update:show', $event)">
    <n-drawer-content title="任务详情" closable>
      <div v-if="task" class="task-detail">
        <!-- 头部概览 -->
        <div class="td-header">
          <div class="row">
            <KindTag :kind="task.kind" />
            <StatusBadge :status="task.status" />
          </div>
          <div class="td-meta mono">
            ID: {{ task.id }} · 创建者: {{ task.creator }} · {{ formatDate(task.created_at) }}
          </div>
          <div v-if="task.parent_task_id" class="td-parent mono">
            ↳ 继承自父任务: {{ task.parent_task_id }}
          </div>
        </div>

        <!-- 进度信息 -->
        <div v-if="task.progress" class="panel" style="margin-top: 14px">
          <div class="panel-title">当前进度</div>
          <div class="row-between mb8">
            <span class="mono" style="font-size: 13px">{{ task.progress.done }}/{{ task.progress.total }}</span>
            <span style="font-size: 12px; color: var(--text-secondary)">{{ task.progress.message }}</span>
          </div>
          <div class="progress-bar">
            <i :style="{ width: `${progressPercent}%` }"></i>
          </div>
        </div>

        <!-- 配置快照 -->
        <div class="panel" style="margin-top: 14px">
          <div class="panel-title" @click="showConfig = !showConfig" style="cursor: pointer">
            <span>配置快照</span>
            <span style="font-size: 12px; color: var(--text-tertiary)">{{ showConfig ? '折叠' : '展开' }}</span>
          </div>
          <pre v-if="showConfig" class="code" style="max-height: 200px; font-size: 11px">{{ JSON.stringify(task.config || {}, null, 2) }}</pre>
        </div>

        <!-- 事件时间线 -->
        <div class="panel" style="margin-top: 14px">
          <div class="panel-title">执行时间线</div>
          <div v-if="events && events.length" class="timeline">
            <div
              v-for="ev in events"
              :key="ev.id || ev.created_at"
              class="tl-item"
              :class="ev.event_type === 'failed' ? 'err' : ev.event_type === 'succeeded' ? 'ok' : 'info'"
            >
              <div class="tl-time">{{ ev.created_at }}</div>
              <div style="font-weight: 500; font-size: 13px">{{ ev.message }}</div>
            </div>
          </div>
          <div v-else style="font-size: 12px; color: var(--text-tertiary); text-align: center; padding: 12px">
            暂无事件记录
          </div>
        </div>
      </div>

      <template #footer>
        <div style="display: flex; gap: 8px; justify-content: flex-end">
          <router-link
            v-if="task?.report_id"
            :to="`/reports/${task.report_id}`"
            class="btn btn-primary btn-sm"
          >
            查看报告
          </router-link>
          <button
            v-if="task && ['queued', 'running'].includes(task.status)"
            class="btn btn-secondary btn-sm danger-text"
            @click="$emit('cancel', task)"
          >
            取消任务
          </button>
          <button
            v-if="task"
            class="btn btn-secondary btn-sm"
            @click="$emit('rerun', task)"
          >
            复制为新任务
          </button>
        </div>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { Task, TaskEvent } from '../../api/types'
import { api } from '../../api/http'
import StatusBadge from '../common/StatusBadge.vue'
import KindTag from '../common/KindTag.vue'

const props = defineProps<{
  show: boolean
  task?: Task | null
}>()

defineEmits<{
  (e: 'update:show', val: boolean): void
  (e: 'cancel', task: Task): void
  (e: 'rerun', task: Task): void
}>()

const showConfig = ref(false)
const events = ref<TaskEvent[]>([])

const progressPercent = computed(() => {
  if (!props.task?.progress) return 0
  if (props.task.progress.percent !== undefined) return props.task.progress.percent
  if (props.task.progress.total > 0) {
    return Math.round((props.task.progress.done / props.task.progress.total) * 100)
  }
  return 0
})

function formatDate(d?: string) {
  if (!d) return ''
  return new Date(d).toLocaleString('zh-CN', { hour12: false })
}

async function loadDetail() {
  if (!props.task?.id) return
  try {
    const full = await api.tasks.get(props.task.id)
    events.value = full.events || props.task.events || [
      { id: '1', task_id: props.task.id, event_type: 'queued', message: '任务入队', created_at: formatDate(props.task.created_at) },
    ]
  } catch (err) {
    events.value = props.task.events || []
  }
}

watch(() => props.show, (val) => {
  if (val) loadDetail()
})
</script>

<style scoped>
.td-header {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-subtle);
}
.td-meta {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-top: 6px;
}
.td-parent {
  font-size: 11px;
  color: var(--c-tasks);
  margin-top: 4px;
}

.timeline {
  position: relative;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 6px;
}
.timeline::before {
  content: '';
  position: absolute;
  left: 4px;
  top: 6px;
  bottom: 6px;
  width: 1px;
  background: var(--border-subtle);
}
.tl-item {
  position: relative;
  font-size: 13px;
}
.tl-item::before {
  content: '';
  position: absolute;
  left: -20px;
  top: 5px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--bg-main);
  border: 2px solid var(--text-tertiary);
}
.tl-item.ok::before {
  border-color: var(--accent-success);
}
.tl-item.err::before {
  border-color: var(--accent-error);
}
.tl-item.info::before {
  border-color: var(--accent-info);
}
.tl-time {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-tertiary);
  margin-bottom: 2px;
}
</style>
