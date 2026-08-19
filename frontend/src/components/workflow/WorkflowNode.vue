<template>
  <div
    class="wf-node"
    :class="[
      `status-${node.status}`,
      {
        selected: isSelected,
        disabled: node.disabled,
      },
    ]"
    :style="{
      transform: `translate(${node.x}px, ${node.y}px)`,
      '--node-accent': node.color || 'var(--accent-ai)',
    }"
    @pointerdown.stop="$emit('node-pointerdown', $event, node)"
    @click.stop="$emit('select-node', node)"
    @dblclick.stop="$emit('inspect-node', node)"
  >
    <!-- 节点顶部强调边条 -->
    <div class="node-accent-bar"></div>

    <!-- 节点头部 -->
    <div class="node-header">
      <div class="node-icon-box">
        <span class="node-icon">{{ node.icon }}</span>
      </div>
      <div class="node-title-area">
        <span class="node-title" :title="node.name">{{ node.name }}</span>
        <span class="node-category-tag">{{ categoryLabel }}</span>
      </div>
      <!-- 状态图标/指示器 -->
      <div class="node-status-badge">
        <span v-if="node.status === 'running'" class="status-spinner" title="执行中..."></span>
        <i v-else class="status-dot" :class="node.status" :title="statusLabel"></i>
      </div>
    </div>

    <!-- 节点主体概要信息 -->
    <div class="node-body">
      <div class="node-summary-tags">
        <span
          v-for="(tag, idx) in summaryTags"
          :key="idx"
          class="summary-tag"
        >
          {{ tag }}
        </span>
      </div>

      <!-- 实时进度条（running 状态展示） -->
      <div v-if="node.status === 'running' && node.progress != null" class="node-progress-bar">
        <div class="progress-fill" :style="{ width: `${node.progress}%` }"></div>
      </div>
    </div>

    <!-- 快捷操作悬浮栏 -->
    <div class="node-actions">
      <button class="action-btn" title="配置属性" @click.stop="$emit('inspect-node', node)">
        ⚙️
      </button>
      <button class="action-btn" title="复制节点" @click.stop="$emit('duplicate-node', node)">
        📋
      </button>
      <button class="action-btn danger" title="删除节点" @click.stop="$emit('delete-node', node.id)">
        🗑
      </button>
    </div>

    <!-- 左侧输入锚点列表 -->
    <div class="ports-container input-ports">
      <div
        v-for="port in node.inputs"
        :key="port.id"
        class="port-item input-port"
        :title="`${port.label} (${port.type})`"
      >
        <div
          class="port-anchor input-anchor"
          :data-node-id="node.id"
          :data-port-id="port.id"
          :data-port-direction="'input'"
          @pointerdown.stop="$emit('port-pointerdown', $event, node.id, port.id, 'input')"
          @pointerup.stop="$emit('port-pointerup', $event, node.id, port.id, 'input')"
        ></div>
        <span class="port-label">{{ port.label }}</span>
      </div>
    </div>

    <!-- 右侧输出锚点列表 -->
    <div class="ports-container output-ports">
      <div
        v-for="port in node.outputs"
        :key="port.id"
        class="port-item output-port"
        :title="`${port.label} (${port.type})`"
      >
        <span class="port-label">{{ port.label }}</span>
        <div
          class="port-anchor output-anchor"
          :data-node-id="node.id"
          :data-port-id="port.id"
          :data-port-direction="'output'"
          @pointerdown.stop="$emit('port-pointerdown', $event, node.id, port.id, 'output')"
          @pointerup.stop="$emit('port-pointerup', $event, node.id, port.id, 'output')"
        ></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { WorkflowNode } from './workflowTypes'

const props = defineProps<{
  node: WorkflowNode
  isSelected?: boolean
}>()

defineEmits<{
  (e: 'select-node', node: WorkflowNode): void
  (e: 'inspect-node', node: WorkflowNode): void
  (e: 'duplicate-node', node: WorkflowNode): void
  (e: 'delete-node', nodeId: string): void
  (e: 'node-pointerdown', event: PointerEvent, node: WorkflowNode): void
  (e: 'port-pointerdown', event: PointerEvent, nodeId: string, portId: string, direction: 'input' | 'output'): void
  (e: 'port-pointerup', event: PointerEvent, nodeId: string, portId: string, direction: 'input' | 'output'): void
}>()

const categoryLabel = computed(() => {
  switch (props.node.category) {
    case 'trigger':
      return '调度'
    case 'eval':
      return '评测'
    case 'data':
      return '数据'
    case 'gate_stress':
      return '门禁/压测'
    case 'output':
      return '输出'
    default:
      return '组件'
  }
})

const statusLabel = computed(() => {
  switch (props.node.status) {
    case 'queued':
      return '排队中'
    case 'running':
      return '执行中'
    case 'succeeded':
      return '执行成功'
    case 'failed':
      return '执行失败'
    case 'skipped':
      return '已跳过'
    default:
      return '待命'
  }
})

/** 提取节点核心参数概要展示标签 */
const summaryTags = computed(() => {
  const cfg = props.node.config || {}
  const tags: string[] = []

  switch (props.node.type) {
    case 'agent_kernel':
      tags.push(`策略: ${cfg.strategy || '负载均衡'}`)
      tags.push(`并发: ${cfg.max_running_tasks || 4}`)
      break
    case 'worker_target':
      tags.push(cfg.worker_id || 'worker-01')
      if (cfg.caps?.length) tags.push(`${cfg.caps.join('/')}`)
      break
    case 'dataset_source':
      tags.push(cfg.dataset_name || '基准数据集')
      if (cfg.sample_size) tags.push(`抽样: ${cfg.sample_size}`)
      if (cfg.metric) tags.push(`指标: ${cfg.metric}`)
      break
    case 'case_gen':
      tags.push('PRD 6大策略')
      if (cfg.mapping_target) tags.push(`目标: ${cfg.mapping_target === 'dataset' ? '数据集' : '黄金QA'}`)
      break
    case 'benchmark_eval':
      if (cfg.profile_ids?.length) tags.push(`${cfg.profile_ids.length} 个模型对比`)
      if (cfg.concurrency) tags.push(`并发: ${cfg.concurrency}`)
      if (cfg.with_stress) tags.push('含先评后压')
      break
    case 'rag_eval':
      tags.push(cfg.kb_name || '知识库')
      if (cfg.rag_modes?.length) tags.push(`模式: ${cfg.rag_modes.join('/')}`)
      if (cfg.top_k) tags.push(`Top-${cfg.top_k}`)
      break
    case 'llm_judge':
      tags.push(`裁判: ${cfg.judge_profile_id || '默认'}`)
      if (cfg.pass_score) tags.push(`及格分: ${cfg.pass_score}`)
      break
    case 'quality_gate':
      tags.push(`门禁: ${cfg.metric || 'contain_rate'} ${cfg.operator || '>='} ${cfg.threshold ?? 85}%`)
      break
    case 'stress_test':
      tags.push(`环境: ${cfg.env || 'test'}`)
      if (cfg.qps) tags.push(`QPS: ${cfg.qps}`)
      if (cfg.duration_seconds) tags.push(`时长: ${cfg.duration_seconds}s`)
      break
    case 'eval_report':
      tags.push(`格式: ${cfg.format || '全量'}`)
      if (cfg.auto_share) tags.push('公开分享')
      break
  }

  return tags.length ? tags : ['已就绪']
})
</script>

<style scoped>
.wf-node {
  position: absolute;
  width: 240px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  cursor: grab;
  user-select: none;
  z-index: 2;
  transition: box-shadow 0.18s, border-color 0.18s;
}

.wf-node:active {
  cursor: grabbing;
}

.wf-node.selected {
  border-color: var(--node-accent);
  box-shadow: 0 0 0 2px var(--node-accent), 0 8px 24px rgba(0, 0, 0, 0.14);
  z-index: 5;
}

.wf-node.disabled {
  opacity: 0.55;
  filter: grayscale(0.8);
}

.node-accent-bar {
  height: 3px;
  width: 100%;
  background: var(--node-accent);
  border-top-left-radius: 9px;
  border-top-right-radius: 9px;
}

.node-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px 6px;
}

.node-icon-box {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
}

.node-title-area {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.node-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-category-tag {
  font-size: 10px;
  color: var(--text-tertiary);
  margin-top: 1px;
}

.node-status-badge {
  display: flex;
  align-items: center;
  justify-content: center;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-tertiary);
}

.status-dot.queued {
  background: var(--accent-warning);
}

.status-dot.succeeded {
  background: var(--accent-success);
  box-shadow: 0 0 6px var(--accent-success);
}

.status-dot.failed {
  background: var(--accent-error);
}

.status-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid var(--accent-ai);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.node-body {
  padding: 4px 12px 10px;
}

.node-summary-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.summary-tag {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  white-space: nowrap;
  max-width: 210px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-progress-bar {
  height: 3px;
  background: var(--bg-elevated);
  border-radius: 2px;
  overflow: hidden;
  margin-top: 6px;
}

.progress-fill {
  height: 100%;
  background: var(--accent-ai);
  transition: width 0.2s ease;
}

.node-actions {
  position: absolute;
  top: -28px;
  right: 0;
  display: none;
  gap: 4px;
  background: var(--bg-main);
  padding: 2px 4px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.wf-node:hover .node-actions,
.wf-node.selected .node-actions {
  display: flex;
}

.action-btn {
  background: transparent;
  border: none;
  font-size: 11px;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
  color: var(--text-secondary);
  transition: background 0.15s;
}

.action-btn:hover {
  background: var(--row-hover);
}

.action-btn.danger:hover {
  color: var(--accent-error);
}

/* 锚点容器与布局 */
.ports-container {
  position: absolute;
  top: 38px;
  bottom: 8px;
  display: flex;
  flex-direction: column;
  justify-content: space-around;
  pointer-events: none;
}

.input-ports {
  left: -8px;
}

.output-ports {
  right: -8px;
}

.port-item {
  display: flex;
  align-items: center;
  gap: 4px;
  pointer-events: auto;
}

.port-anchor {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--bg-main);
  border: 2px solid var(--node-accent);
  cursor: crosshair;
  transition: transform 0.15s, background 0.15s, box-shadow 0.15s;
  position: relative;
  z-index: 10;
}

.port-anchor:hover {
  transform: scale(1.35);
  background: var(--node-accent);
  box-shadow: 0 0 8px var(--node-accent);
}

.port-label {
  font-size: 10px;
  color: var(--text-tertiary);
  pointer-events: none;
}

.input-port .port-label {
  margin-left: 2px;
}

.output-port .port-label {
  margin-right: 2px;
}
</style>
