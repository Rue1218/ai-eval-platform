<template>
  <div v-if="task && isVisible" class="progress-dock">
    <div class="progress-dock-inner" :class="{ stress: task.kind === 'stress' }">
      <!-- 任务类型标签 -->
      <span class="kind-tag" :class="`kind-${task.kind}`">{{ kindName }}</span>

      <!-- 进度条与数字 -->
      <div class="progress-bar">
        <i :style="{ width: `${progressPercent}%` }"></i>
      </div>

      <div class="progress-nums mono">
        {{ task.progress?.done || 0 }}/{{ task.progress?.total || 100 }}
      </div>

      <!-- 进度提示文本 -->
      <div class="progress-msg" :title="task.progress?.message">
        {{ task.progress?.message || '任务进行中...' }}
      </div>

      <!-- 压测迷你指标 -->
      <div v-if="task.kind === 'stress' && miniSeries" class="mini-series">
        <span>QPS: <b class="ms-qps">{{ miniSeries.qps || 0 }}</b></span>
        <span>RT: <b class="ms-rt">{{ miniSeries.rt || '320ms' }}</b></span>
        <span>Err: <b class="ms-err">{{ miniSeries.err || '0%' }}</b></span>
      </div>

      <!-- 操作按钮 -->
      <div style="margin-left: auto; display: flex; align-items: center; gap: 8px">
        <template v-if="task.status === 'awaiting_case_confirm'">
          <router-link to="/cases" class="btn btn-primary btn-sm">去确认用例</router-link>
        </template>
        <template v-else-if="['queued', 'running'].includes(task.status)">
          <button class="btn btn-secondary btn-sm danger-text" @click="handleCancel">
            {{ task.kind === 'stress' ? '立即停止' : '取消评测' }}
          </button>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import type { Task } from '../../api/types'

const props = defineProps<{
  task?: Task | null
  miniSeries?: { qps?: number; rt?: string; err?: string }
}>()

const emit = defineEmits<{
  (e: 'cancel', taskId: string): void
}>()

const dialog = useDialog()
const message = useMessage()

const isVisible = computed(() => {
  if (!props.task) return false
  return ['queued', 'running', 'awaiting_case_confirm'].includes(props.task.status)
})

const kindName = computed(() => {
  const map: Record<string, string> = {
    benchmark: '基准评测',
    rag: 'RAG 评测',
    testcase: '用例生成',
    stress: '压测',
  }
  return map[props.task?.kind || 'benchmark'] || '任务'
})

const progressPercent = computed(() => {
  if (!props.task?.progress) return 10
  if (props.task.progress.percent !== undefined) return props.task.progress.percent
  if (props.task.progress.total > 0) {
    return Math.round((props.task.progress.done / props.task.progress.total) * 100)
  }
  return 20
})

function handleCancel() {
  if (!props.task) return
  const isStress = props.task.kind === 'stress'
  dialog.warning({
    title: isStress ? '立即停止发压？' : '取消评测任务？',
    content: isStress
      ? '发压引擎将立即中断请求发送。'
      : '评测任务将在当前运行的样本结束后停止，已评测样本将被保留。',
    positiveText: isStress ? '立即停止' : '取消任务',
    negativeText: '暂不取消',
    onPositiveClick: () => {
      emit('cancel', props.task!.id)
      message.info('已提交取消请求')
    },
  })
}
</script>

<style scoped>
.progress-dock {
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-main);
  padding: 10px 24px;
}
.progress-dock-inner {
  max-width: 760px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 12px;
}
.progress-bar {
  flex: 1;
  height: 6px;
  border-radius: 999px;
  background: var(--bg-elevated);
  overflow: hidden;
  min-width: 80px;
}
.progress-bar > i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--accent-ai);
  transition: width 0.4s ease;
}
.progress-nums {
  font-size: 12px;
  color: var(--text-primary);
  white-space: nowrap;
}
.progress-msg {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 260px;
}

.mini-series {
  display: flex;
  gap: 10px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.mini-series b {
  color: var(--text-primary);
}
.mini-series .ms-qps {
  color: var(--accent-info);
}
.mini-series .ms-rt {
  color: var(--accent-warning);
}
.mini-series .ms-err {
  color: var(--accent-error);
}

@media (max-width: 640px) {
  .progress-dock {
    padding: 8px 12px;
  }
  .progress-dock-inner {
    flex-wrap: wrap;
    gap: 8px;
  }
  .progress-bar {
    order: 2;
    width: 100%;
    flex: 1 0 100%;
  }
  .progress-msg {
    max-width: 140px;
    font-size: 11.5px;
  }
  .progress-nums {
    font-size: 11.5px;
  }
}
</style>
