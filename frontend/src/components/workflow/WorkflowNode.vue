<template>
  <div
    class="wf-node"
    :class="[
      `status-${node.status}`,
      `cat-${node.category}`,
      {
        selected: isSelected,
        disabled: node.disabled,
        running: node.status === 'running',
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
    <!-- 运行状态下的流光边框动画 -->
    <div v-if="node.status === 'running'" class="node-border-beam"></div>

    <!-- 顶部渐变强调条 -->
    <div class="node-accent-bar"></div>

    <!-- 节点头部 -->
    <div class="node-header">
      <div class="node-icon-box">
        <span class="node-icon">{{ node.icon }}</span>
      </div>
      <div class="node-title-area">
        <div class="row" style="align-items: center; gap: 6px">
          <span class="node-title" :title="node.name">{{ node.name }}</span>
        </div>
        <div class="node-sub-info">
          <span class="node-category-tag">{{ categoryLabel }}</span>
          <span class="node-id-tag mono">{{ node.id.substring(0, 7) }}</span>
        </div>
      </div>

      <!-- 状态图标/指示灯 -->
      <div class="node-status-badge">
        <span v-if="node.status === 'running'" class="status-spinner" title="节点正在调度执行中..."></span>
        <span v-else-if="node.status === 'succeeded'" class="status-icon success" title="执行成功">✓</span>
        <span v-else-if="node.status === 'failed'" class="status-icon error" title="执行异常">✕</span>
        <i v-else class="status-dot" :class="node.status" :title="statusLabel"></i>
      </div>
    </div>

    <!-- 节点主体概要信息与可视化参数 -->
    <div class="node-body">
      <div class="node-summary-tags">
        <span
          v-for="(tag, idx) in summaryTags"
          :key="idx"
          class="summary-tag"
          :class="{ highlight: idx === 0 }"
        >
          {{ tag }}
        </span>
      </div>

      <!-- 实时执行进度条（running 状态展示） -->
      <div v-if="node.status === 'running' && node.progress != null" class="node-progress-wrap">
        <div class="progress-info row-between">
          <span class="small tertiary">执行进度</span>
          <span class="small mono font-bold" style="color: var(--accent-ai)">{{ node.progress }}%</span>
        </div>
        <div class="node-progress-bar">
          <div class="progress-fill" :style="{ width: `${node.progress}%` }"></div>
        </div>
      </div>
    </div>

    <!-- 快捷操作悬浮栏 -->
    <div class="node-actions">
      <button class="action-btn" title="配置参数与依赖" @click.stop="$emit('inspect-node', node)">
        ⚙️
      </button>
      <button class="action-btn" title="复制节点副本" @click.stop="$emit('duplicate-node', node)">
        📋
      </button>
      <button class="action-btn danger" title="删除此节点" @click.stop="$emit('delete-node', node.id)">
        🗑
      </button>
    </div>

    <!-- 左侧输入锚点列表 (Inputs) - 精确像素定位 -->
    <div
      v-for="port in node.inputs"
      :key="port.id"
      class="port-anchor-wrap input-anchor-wrap"
      :style="{ top: `${getPortY(port.id, 'input')}px` }"
      :title="`${port.label} [类型: ${port.type}]`"
    >
      <div
        class="port-anchor input-anchor"
        :data-node-id="node.id"
        :data-port-id="port.id"
        :data-port-direction="'input'"
        @pointerdown.stop="$emit('port-pointerdown', $event, node.id, port.id, 'input')"
        @pointerup.stop="$emit('port-pointerup', $event, node.id, port.id, 'input')"
      >
        <span class="anchor-center"></span>
      </div>
      <span class="port-tooltip-label left">{{ port.label }}</span>
    </div>

    <!-- 右侧输出锚点列表 (Outputs) - 精确像素定位 -->
    <div
      v-for="port in node.outputs"
      :key="port.id"
      class="port-anchor-wrap output-anchor-wrap"
      :class="{
        'port-pass': port.id === 'pass',
        'port-fail': port.id === 'fail',
      }"
      :style="{ top: `${getPortY(port.id, 'output')}px` }"
      :title="`${port.label} [类型: ${port.type}]`"
    >
      <span class="port-tooltip-label right">{{ port.label }}</span>
      <div
        class="port-anchor output-anchor"
        :class="{
          'anchor-pass': port.id === 'pass',
          'anchor-fail': port.id === 'fail',
        }"
        :data-node-id="node.id"
        :data-port-id="port.id"
        :data-port-direction="'output'"
        @pointerdown.stop="$emit('port-pointerdown', $event, node.id, port.id, 'output')"
        @pointerup.stop="$emit('port-pointerup', $event, node.id, port.id, 'output')"
      >
        <span class="anchor-center"></span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { type WorkflowNode, getNodePortY } from './workflowTypes'

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

function getPortY(portId: string, direction: 'input' | 'output'): number {
  return getNodePortY(props.node, portId, direction)
}

const categoryLabel = computed(() => {
  switch (props.node.category) {
    case 'trigger':
      return '调度触发'
    case 'eval':
      return '评测引擎'
    case 'data':
      return '数据用例'
    case 'gate_stress':
      return '门禁/压测'
    case 'output':
      return '汇总报告'
    default:
      return '工作流组件'
  }
})

const statusLabel = computed(() => {
  switch (props.node.status) {
    case 'queued':
      return '已就绪排队'
    case 'running':
      return '执行中...'
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
      tags.push(`心跳: ${cfg.heartbeat_ms || 500}ms`)
      break
    case 'worker_target':
      tags.push(`节点: ${cfg.worker_id || 'worker-01'}`)
      if (cfg.caps?.length) tags.push(`能力: ${cfg.caps.join('/')}`)
      tags.push(`权重: ${cfg.weight || 100}`)
      break
    case 'dataset_source':
      tags.push(`数据集: ${cfg.dataset_name || '基准集'}`)
      if (cfg.sample_size) tags.push(`抽样: ${cfg.sample_size} 条`)
      if (cfg.metric) tags.push(`主指标: ${cfg.metric}`)
      break
    case 'case_gen':
      tags.push('PRD 6大策略生成')
      tags.push(`目标: ${cfg.mapping_target === 'dataset' ? '基准集' : '黄金QA'}`)
      break
    case 'benchmark_eval':
      if (cfg.profile_ids?.length) tags.push(`对比: ${cfg.profile_ids.length} 个模型`)
      if (cfg.concurrency) tags.push(`并发: ${cfg.concurrency}`)
      if (cfg.with_stress) tags.push('⚡ 级联压测')
      break
    case 'rag_eval':
      tags.push(`知识库: ${cfg.kb_name || '默认库'}`)
      if (cfg.rag_modes?.length) tags.push(`模式: ${cfg.rag_modes.join('/')}`)
      if (cfg.top_k) tags.push(`Top-${cfg.top_k}`)
      break
    case 'llm_judge':
      tags.push(`裁判: ${cfg.judge_profile_id || 'GPT-4o'}`)
      if (cfg.pass_score) tags.push(`及格: ${cfg.pass_score} 分`)
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
      tags.push(`格式: ${cfg.format || '全量雷达图'}`)
      if (cfg.auto_share) tags.push('🔗 免登分享')
      break
  }

  return tags.length ? tags : ['已配置就绪']
})
</script>

<style scoped>
.wf-node {
  position: absolute;
  width: 264px;
  min-height: 108px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
  cursor: grab;
  user-select: none;
  z-index: 2;
  transition: box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1), border-color 0.2s;
  backdrop-filter: blur(12px);
}

.wf-node:hover {
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.14);
  border-color: color-mix(in srgb, var(--node-accent) 60%, var(--border-subtle));
}

.wf-node:active {
  cursor: grabbing;
}

.wf-node.selected {
  border-color: var(--node-accent);
  box-shadow: 0 0 0 2px var(--node-accent), 0 12px 32px rgba(0, 0, 0, 0.16);
  z-index: 6;
}

.wf-node.disabled {
  opacity: 0.5;
  filter: grayscale(0.85);
}

/* 顶部渐变强调条 */
.node-accent-bar {
  height: 4px;
  width: 100%;
  background: linear-gradient(90deg, var(--node-accent) 0%, color-mix(in srgb, var(--node-accent) 40%, transparent) 100%);
  border-top-left-radius: 11px;
  border-top-right-radius: 11px;
}

/* 执行流光动画 */
.node-border-beam {
  position: absolute;
  inset: -2px;
  border-radius: 14px;
  background: linear-gradient(90deg, transparent 0%, var(--accent-ai) 50%, var(--accent-success) 100%);
  opacity: 0.8;
  z-index: -1;
  filter: blur(4px);
  animation: pulse-glow 1.5s ease-in-out infinite alternate;
}

@keyframes pulse-glow {
  0% { opacity: 0.4; filter: blur(3px); }
  100% { opacity: 0.9; filter: blur(6px); }
}

.node-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px 6px;
}

.node-icon-box {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
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
  letter-spacing: -0.2px;
}

.node-sub-info {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}

.node-category-tag {
  font-size: 10px;
  font-weight: 500;
  color: var(--text-secondary);
  background: var(--bg-elevated);
  padding: 1px 5px;
  border-radius: 4px;
  border: 1px solid var(--border-subtle);
}

.node-id-tag {
  font-size: 10px;
  color: var(--text-tertiary);
}

.node-status-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-tertiary);
}

.status-dot.queued {
  background: var(--accent-warning);
  box-shadow: 0 0 6px var(--accent-warning);
}

.status-dot.succeeded {
  background: var(--accent-success);
  box-shadow: 0 0 6px var(--accent-success);
}

.status-dot.failed {
  background: var(--accent-error);
}

.status-icon {
  font-size: 11px;
  font-weight: bold;
  border-radius: 50%;
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.status-icon.success {
  background: var(--accent-success);
  color: #fff;
}

.status-icon.error {
  background: var(--accent-error);
  color: #fff;
}

.status-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--accent-ai);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.75s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.node-body {
  padding: 4px 12px 12px;
}

.node-summary-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.summary-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 5px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  white-space: nowrap;
  max-width: 230px;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: all 0.15s;
}

.summary-tag.highlight {
  font-weight: 500;
  border-color: color-mix(in srgb, var(--node-accent) 40%, var(--border-subtle));
  color: var(--text-primary);
}

.node-progress-wrap {
  margin-top: 8px;
}

.progress-info {
  margin-bottom: 3px;
}

.node-progress-bar {
  height: 4px;
  background: var(--bg-elevated);
  border-radius: 2px;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-ai) 0%, var(--accent-success) 100%);
  transition: width 0.25s ease;
}

.node-actions {
  position: absolute;
  top: -30px;
  right: 0;
  display: none;
  gap: 4px;
  background: var(--bg-main);
  padding: 3px 6px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  z-index: 10;
}

.wf-node:hover .node-actions,
.wf-node.selected .node-actions {
  display: flex;
}

.action-btn {
  background: transparent;
  border: none;
  font-size: 12px;
  cursor: pointer;
  padding: 3px 5px;
  border-radius: 4px;
  color: var(--text-secondary);
  transition: background 0.15s, transform 0.15s;
}

.action-btn:hover {
  background: var(--row-hover);
  transform: scale(1.1);
}

.action-btn.danger:hover {
  color: var(--accent-error);
}

/* ═══ 精准像素对齐的端口锚点 ═══ */
.port-anchor-wrap {
  position: absolute;
  display: flex;
  align-items: center;
  transform: translateY(-50%);
  z-index: 10;
  pointer-events: auto;
}

.input-anchor-wrap {
  left: -8px;
}

.output-anchor-wrap {
  right: -8px;
}

.port-anchor {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--bg-main);
  border: 2px solid var(--node-accent);
  cursor: crosshair;
  transition: transform 0.18s cubic-bezier(0.4, 0, 0.2, 1), background 0.18s, box-shadow 0.18s;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
}

.anchor-center {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--node-accent);
  pointer-events: none;
}

.port-anchor:hover {
  transform: scale(1.45);
  background: var(--node-accent);
  box-shadow: 0 0 12px var(--node-accent);
}

.port-anchor:hover .anchor-center {
  background: #ffffff;
}

/* 锚点微标签（悬浮呈现） */
.port-tooltip-label {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  font-size: 10px;
  font-weight: 500;
  color: var(--text-tertiary);
  white-space: nowrap;
  pointer-events: none;
  background: var(--bg-main);
  padding: 1px 5px;
  border-radius: 4px;
  border: 1px solid var(--border-subtle);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
  opacity: 0;
  transition: opacity 0.15s, transform 0.15s;
}

.port-tooltip-label.left {
  left: 20px;
}

.port-tooltip-label.right {
  right: 20px;
}

.port-anchor-wrap:hover .port-tooltip-label {
  opacity: 1;
}

.port-anchor.anchor-pass {
  border-color: var(--accent-success);
}
.port-anchor.anchor-pass .anchor-center {
  background: var(--accent-success);
}
.port-anchor.anchor-pass:hover {
  background: var(--accent-success);
  box-shadow: 0 0 12px var(--accent-success);
}

.port-anchor.anchor-fail {
  border-color: var(--accent-error);
}
.port-anchor.anchor-fail .anchor-center {
  background: var(--accent-error);
}
.port-anchor.anchor-fail:hover {
  background: var(--accent-error);
  box-shadow: 0 0 12px var(--accent-error);
}
</style>
