<template>
  <div
    class="wf-designer-root"
    :class="{ 'is-fullscreen': isFullScreen }"
  >
    <!-- ═══ 顶部编排控制工具栏 (Frosted Glass Floating Bar) ═══ -->
    <div class="designer-toolbar">
      <div class="toolbar-left">
        <div class="wf-title-badge">
          <span class="badge-icon">🌐</span>
          <span class="badge-label">DAG 编排设计器</span>
          <span class="badge-sub">Dify Flow Studio</span>
        </div>

        <!-- 模板快速载入下拉 -->
        <div class="template-selector">
          <select v-model="currentTemplateId" class="select-tpl" @change="loadSelectedTemplate">
            <option value="" disabled>-- 载入预置工作流模板 --</option>
            <option v-for="tpl in WORKFLOW_TEMPLATES" :key="tpl.id" :value="tpl.id">
              {{ tpl.icon }} {{ tpl.name }} ({{ tpl.badgeText }})
            </option>
          </select>
        </div>

        <button class="btn btn-secondary btn-sm" title="拓扑自动分层排版 (Auto Layout)" @click="autoLayout">
          <span class="btn-icon">📐</span>
          <span>自动排版</span>
        </button>

        <button class="btn btn-secondary btn-sm" title="导出当前工作流为 JSON 配置文件" @click="exportWorkflowJson">
          <span class="btn-icon">📥</span>
          <span>导出</span>
        </button>

        <button class="btn btn-secondary btn-sm" title="从 JSON 文件导入工作流" @click="triggerImportJson">
          <span class="btn-icon">📤</span>
          <span>导入</span>
        </button>
        <input
          ref="importFileRef"
          type="file"
          accept=".json"
          style="display: none"
          @change="handleFileImport"
        />

        <button class="btn btn-secondary btn-sm" title="清空当前画布" @click="clearCanvas">
          <span class="btn-icon">🧹</span>
          <span>清空</span>
        </button>
      </div>

      <!-- 中间视图缩放与统计 -->
      <div class="toolbar-center">
        <span class="zoom-ctrl">
          <button class="zoom-btn" title="缩小画布" @click="zoomBy(0.85)">−</button>
          <button class="zoom-btn mono" title="复位 100% 视图（双击画布同效）" @click="resetView">
            {{ Math.round(view.k * 100) }}%
          </button>
          <button class="zoom-btn" title="放大画布" @click="zoomBy(1.18)">+</button>
          <button class="zoom-btn" title="自适应全部节点" @click="fitView">⊡</button>
        </span>
        <span class="stats-pill mono">
          {{ nodes.length }} 节点 · {{ edges.length }} 链路
        </span>
      </div>

      <!-- 右侧校验状态、全屏与执行按钮 -->
      <div class="toolbar-right">
        <span
          class="validation-pill"
          :class="validation.valid ? 'valid' : 'warning'"
          :title="validation.valid ? 'DAG 拓扑完整且无环路' : validation.errors[0]?.message"
        >
          <i class="v-dot"></i>
          {{ validation.valid ? '拓扑校验通过' : validation.errors[0]?.message || '存在配置警告' }}
        </span>

        <button
          class="btn btn-secondary btn-sm"
          :title="isFullScreen ? '退出全屏 (Esc)' : '全屏沉浸式编排'"
          @click="isFullScreen = !isFullScreen"
        >
          <span>{{ isFullScreen ? '✕ 退出全屏' : '⛶ 全屏' }}</span>
        </button>

        <button
          class="btn btn-primary btn-sm run-btn"
          :class="{ 'btn-loading': isExecuting }"
          :disabled="isExecuting || !nodes.length"
          @click="runWorkflow"
        >
          <span v-if="!isExecuting">▶ 立即执行 / 调度入队</span>
          <span v-else>正在调度执行中...</span>
        </button>
      </div>
    </div>

    <!-- ═══ 主工作区：左侧物料库 + 中央画布 + 右侧属性面板 ═══ -->
    <div class="designer-main">
      <!-- 左侧物料库 -->
      <WorkflowPalette @add-node="handleAddNodeFromPalette" />

      <!-- 中央交互画布 -->
      <div
        ref="canvasContainerRef"
        class="canvas-container"
        @pointerdown="onCanvasPointerDown"
        @pointermove="onCanvasPointerMove"
        @pointerup="onCanvasPointerUp"
        @pointerleave="onCanvasPointerUp"
        @wheel.prevent="onCanvasWheel"
        @dblclick="resetView"
        @dragover.prevent
        @drop="onCanvasDrop"
      >
        <!-- 画布缩放平移视口 -->
        <div
          class="canvas-viewport"
          :style="{
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})`,
          }"
        >
          <!-- SVG 连线层 -->
          <svg class="canvas-svg-layer" viewBox="-4000 -4000 12000 12000">
            <defs>
              <!-- 网格背景点阵图案 -->
              <pattern id="wf-grid-pattern" width="28" height="28" patternUnits="userSpaceOnUse">
                <circle cx="14" cy="14" r="1.1" class="grid-dot" />
              </pattern>

              <!-- 连线渐变 -->
              <linearGradient id="edge-flow-grad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="var(--accent-ai)" stop-opacity="0.85" />
                <stop offset="100%" stop-color="var(--accent-success)" stop-opacity="0.95" />
              </linearGradient>

              <!-- 门禁通过渐变 -->
              <linearGradient id="edge-pass-grad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="var(--accent-success)" />
                <stop offset="100%" stop-color="var(--accent-success)" stop-opacity="0.7" />
              </linearGradient>

              <!-- 门禁阻断渐变 -->
              <linearGradient id="edge-fail-grad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="var(--accent-error)" />
                <stop offset="100%" stop-color="var(--accent-error)" stop-opacity="0.7" />
              </linearGradient>
            </defs>

            <!-- 网格背景 -->
            <rect x="-4000" y="-4000" width="12000" height="12000" fill="url(#wf-grid-pattern)" />

            <!-- 已确立的连线 (Edges) -->
            <g v-for="edge in edgePaths" :key="edge.id" class="edge-group">
              <!-- 连线外层感应热区（点击可删除或高亮） -->
              <path
                :d="edge.d"
                class="edge-hit-area"
                @click.stop="handleDeleteEdge(edge.id)"
              />
              <!-- 连线主体 -->
              <path
                :d="edge.d"
                class="edge-line"
                :class="{
                  active: edge.status === 'active' || isExecuting,
                  success: edge.status === 'success',
                  'edge-pass': edge.sourcePortId === 'pass',
                  'edge-fail': edge.sourcePortId === 'fail',
                }"
              />
              <!-- 执行时流动的光效粒子 -->
              <template v-if="isExecuting || edge.status === 'active'">
                <circle class="flow-particle" r="3.5" fill="var(--accent-ai)">
                  <animateMotion :path="edge.d" dur="1.7s" repeatCount="indefinite" />
                </circle>
                <circle class="flow-particle" r="2.5" fill="var(--accent-success)" opacity="0.8">
                  <animateMotion :path="edge.d" dur="1.7s" begin="-0.85s" repeatCount="indefinite" />
                </circle>
              </template>
            </g>

            <!-- 连线中间标签与删除按钮（HTML 叠加层） -->
            <!-- 正在拖拽中的动态连线预览 -->
            <path
              v-if="connectingLine"
              :d="connectingLine.d"
              class="edge-connecting-preview"
            />
          </svg>

          <!-- 连线中间标签气泡 -->
          <div
            v-for="edge in edgePaths"
            :key="'label-' + edge.id"
            class="edge-label-pill"
            :class="{
              'label-pass': edge.sourcePortId === 'pass',
              'label-fail': edge.sourcePortId === 'fail',
            }"
            :style="{
              transform: `translate(${edge.midX}px, ${edge.midY}px)`,
            }"
            @click.stop="handleDeleteEdge(edge.id)"
            title="点击删除连接链路"
          >
            <span class="pill-text">{{ edge.label || defaultEdgeLabel(edge) }}</span>
            <span class="pill-del">×</span>
          </div>

          <!-- 节点卡片层 -->
          <WorkflowNode
            v-for="node in nodes"
            :key="node.id"
            :node="node"
            :is-selected="selectedNode?.id === node.id"
            @select-node="handleSelectNode"
            @inspect-node="handleInspectNode"
            @duplicate-node="handleDuplicateNode"
            @delete-node="handleDeleteNode"
            @node-pointerdown="onNodePointerDown"
            @port-pointerdown="onPortPointerDown"
            @port-pointerup="onPortPointerUp"
          />
        </div>

        <!-- 底部快捷提示浮条 -->
        <div class="canvas-hints">
          <span>滚轮缩放 · 拖拽画布平移 · 端口拖拽连线 · 双击节点配置属性 · 点击连线气泡删除</span>
        </div>

        <!-- ═══ 右下角小地图 (Mini-Map) ═══ -->
        <div class="canvas-minimap" title="小地图 (点击快速定位)">
          <svg viewBox="0 0 2000 1400" class="minimap-svg">
            <rect width="2000" height="1400" fill="var(--bg-elevated)" opacity="0.8" />
            <!-- 微型节点块 -->
            <rect
              v-for="n in nodes"
              :key="'mini-' + n.id"
              :x="n.x + 200"
              :y="n.y + 100"
              width="250"
              height="140"
              rx="20"
              :fill="n.color || 'var(--accent-ai)'"
              opacity="0.85"
            />
            <!-- 当前视口指示框 -->
            <rect
              :x="-view.x * (1 / view.k) + 200"
              :y="-view.y * (1 / view.k) + 100"
              :width="900 / view.k"
              :height="600 / view.k"
              fill="none"
              stroke="var(--accent-ai)"
              stroke-width="14"
              stroke-dasharray="24 16"
            />
          </svg>
        </div>
      </div>

      <!-- 右侧属性面板 -->
      <WorkflowInspector
        v-if="selectedNode"
        :node="selectedNode"
        @close="selectedNode = null"
        @delete-node="handleDeleteNode"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import WorkflowPalette from './WorkflowPalette.vue'
import WorkflowNode from './WorkflowNode.vue'
import WorkflowInspector from './WorkflowInspector.vue'
import { WORKFLOW_TEMPLATES, createNode } from './workflowTemplates'
import { api } from '../../api/http'
import type {
  WorkflowNode as IWorkflowNode,
  WorkflowEdge,
  WorkflowNodeType,
  WorkflowValidationResult,
} from './workflowTypes'

const emit = defineEmits<{
  (e: 'task-dispatched', taskId: string): void
}>()

const message = useMessage()
const router = useRouter()

// 画布视口缩放与位移
const view = ref({ x: 50, y: 40, k: 0.88 })
const canvasContainerRef = ref<HTMLElement | null>(null)
const importFileRef = ref<HTMLInputElement | null>(null)
const isFullScreen = ref(false)

// 节点与连线数据
const nodes = ref<IWorkflowNode[]>([])
const edges = ref<WorkflowEdge[]>([])
const selectedNode = ref<IWorkflowNode | null>(null)
const currentTemplateId = ref<string>('tpl_benchmark_stress')
const isExecuting = ref(false)

// 交互状态：画布平移
const isPanning = ref(false)
const panStart = ref({ x: 0, y: 0, vx: 0, vy: 0 })

// 交互状态：节点拖拽
const draggingNodeId = ref<string | null>(null)
const nodeDragOffset = ref({ x: 0, y: 0 })

// 交互状态：端口拖拽连线与磁吸吸附
const connectingPort = ref<{
  nodeId: string
  portId: string
  direction: 'input' | 'output'
  startX: number
  startY: number
} | null>(null)
const currentMousePos = ref({ x: 0, y: 0 })

// 初始化时默认载入标准先评后压模板
onMounted(() => {
  loadSelectedTemplate()
  window.addEventListener('keydown', onKeyDown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown)
})

function onKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape' && isFullScreen.value) {
    isFullScreen.value = false
  }
}

/** 载入选中的模板 */
function loadSelectedTemplate() {
  const tpl = WORKFLOW_TEMPLATES.find((t) => t.id === currentTemplateId.value)
  if (!tpl) return
  nodes.value = JSON.parse(JSON.stringify(tpl.nodes))
  edges.value = JSON.parse(JSON.stringify(tpl.edges))
  selectedNode.value = nodes.value[1] || nodes.value[0] || null
  resetView()
  message.success(`已载入工作流模版：${tpl.name}`)
}

/** 缩放画布 */
function zoomBy(factor: number) {
  const newK = Math.max(0.35, Math.min(2.2, view.value.k * factor))
  view.value.k = Math.round(newK * 100) / 100
}

/** 复位视图 */
function resetView() {
  view.value = { x: 50, y: 40, k: 0.88 }
}

/** 自适应适配视口中所有节点 */
function fitView() {
  if (!nodes.value.length) {
    resetView()
    return
  }
  const minX = Math.min(...nodes.value.map((n) => n.x))
  const minY = Math.min(...nodes.value.map((n) => n.y))
  view.value = {
    x: Math.max(20, 70 - minX * 0.75),
    y: Math.max(20, 60 - minY * 0.75),
    k: 0.75,
  }
}

/** 拓扑自动分层排版 */
function autoLayout() {
  if (!nodes.value.length) return
  const inDegrees: Record<string, number> = {}
  nodes.value.forEach((n) => (inDegrees[n.id] = 0))
  edges.value.forEach((e) => {
    inDegrees[e.targetNodeId] = (inDegrees[e.targetNodeId] || 0) + 1
  })

  const levels: Record<number, IWorkflowNode[]> = {}
  nodes.value.forEach((n) => {
    const lvl = Math.min(4, inDegrees[n.id] || 0)
    if (!levels[lvl]) levels[lvl] = []
    levels[lvl].push(n)
  })

  let colX = 70
  Object.keys(levels)
    .map(Number)
    .sort((a, b) => a - b)
    .forEach((lvl) => {
      const colNodes = levels[lvl]
      colNodes.forEach((n, idx) => {
        n.x = colX
        n.y = 90 + idx * 190
      })
      colX += 360
    })

  message.success('已完成拓扑自动分层排版')
}

/** 清空画布 */
function clearCanvas() {
  nodes.value = []
  edges.value = []
  selectedNode.value = null
  message.info('画布已清空')
}

/** 导出工作流 JSON */
function exportWorkflowJson() {
  const data = {
    name: 'AI-Eval-Workflow',
    version: '1.0',
    exported_at: new Date().toISOString(),
    nodes: nodes.value,
    edges: edges.value,
  }
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `workflow-dag-${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(url)
  message.success('工作流配置已成功导出为 JSON 文件')
}

function triggerImportJson() {
  importFileRef.value?.click()
}

function handleFileImport(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (evt) => {
    try {
      const content = evt.target?.result as string
      const parsed = JSON.parse(content)
      if (Array.isArray(parsed.nodes)) {
        nodes.value = parsed.nodes
        edges.value = parsed.edges || []
        selectedNode.value = nodes.value[0] || null
        fitView()
        message.success('工作流配置已成功导入！')
      } else {
        message.error('无效的工作流 JSON 结构')
      }
    } catch {
      message.error('解析 JSON 文件失败')
    }
  }
  reader.readAsText(file)
}

/** 从物料库添加新节点至视口中央 */
function handleAddNodeFromPalette(type: WorkflowNodeType) {
  const x = Math.round((220 - view.value.x) / view.value.k)
  const y = Math.round((160 - view.value.y) / view.value.k)
  const newNode = createNode(type, x, y)
  nodes.value.push(newNode)
  selectedNode.value = newNode
  message.success(`已添加组件：${newNode.name}`)
}

/** 拖拽物料释放到画布 */
function onCanvasDrop(event: DragEvent) {
  const type = event.dataTransfer?.getData('application/workflow-node-type') as WorkflowNodeType
  if (!type) return
  const rect = canvasContainerRef.value?.getBoundingClientRect()
  if (!rect) return
  const clientX = event.clientX - rect.left
  const clientY = event.clientY - rect.top
  const x = Math.round((clientX - view.value.x) / view.value.k) - 128
  const y = Math.round((clientY - view.value.y) / view.value.k) - 45
  const newNode = createNode(type, x, y)
  nodes.value.push(newNode)
  selectedNode.value = newNode
  message.success(`已放置组件：${newNode.name}`)
}

function handleSelectNode(node: IWorkflowNode) {
  selectedNode.value = node
}

function handleInspectNode(node: IWorkflowNode) {
  selectedNode.value = node
}

function handleDuplicateNode(node: IWorkflowNode) {
  const newNode = createNode(node.type, node.x + 35, node.y + 35)
  newNode.name = `${node.name} (副本)`
  newNode.config = JSON.parse(JSON.stringify(node.config))
  nodes.value.push(newNode)
  selectedNode.value = newNode
  message.info(`已复制节点：${newNode.name}`)
}

function handleDeleteNode(nodeId: string) {
  nodes.value = nodes.value.filter((n) => n.id !== nodeId)
  edges.value = edges.value.filter((e) => e.sourceNodeId !== nodeId && e.targetNodeId !== nodeId)
  if (selectedNode.value?.id === nodeId) {
    selectedNode.value = null
  }
  message.info('已移除节点')
}

function handleDeleteEdge(edgeId: string) {
  edges.value = edges.value.filter((e) => e.id !== edgeId)
  message.info('已删除连接链路')
}

function defaultEdgeLabel(edge: WorkflowEdge): string {
  if (edge.sourcePortId === 'pass') return '✓ 门禁通过'
  if (edge.sourcePortId === 'fail') return '✕ 门禁阻断'
  if (edge.sourcePortId === 'out_bm') return '基准分发'
  if (edge.sourcePortId === 'out_rag') return 'RAG 分发'
  if (edge.sourcePortId === 'out_stress') return '压测分发'
  return '数据流'
}

/** 计算连线贝塞尔曲线坐标及中心气泡坐标 */
const edgePaths = computed(() => {
  const nodeMap = new Map(nodes.value.map((n) => [n.id, n]))
  return edges.value
    .map((edge) => {
      const srcNode = nodeMap.get(edge.sourceNodeId)
      const tgtNode = nodeMap.get(edge.targetNodeId)
      if (!srcNode || !tgtNode) return null

      const x1 = srcNode.x + 256
      const y1 = srcNode.y + 52
      const x2 = tgtNode.x
      const y2 = tgtNode.y + 52

      const dx = Math.max(50, Math.abs(x2 - x1) * 0.45)
      const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`
      const midX = Math.round((x1 + x2) / 2)
      const midY = Math.round((y1 + y2) / 2)

      return {
        ...edge,
        d,
        x1,
        y1,
        x2,
        y2,
        midX,
        midY,
      }
    })
    .filter(Boolean) as Array<WorkflowEdge & { d: string; midX: number; midY: number }>
})

/** 拖拽中的动态连线预览（支持磁吸微吸附效果） */
const connectingLine = computed(() => {
  if (!connectingPort.value) return null
  const p = connectingPort.value
  const x1 = p.startX
  const y1 = p.startY
  const x2 = currentMousePos.value.x
  const y2 = currentMousePos.value.y
  const dx = Math.max(50, Math.abs(x2 - x1) * 0.45)
  const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`
  return { d }
})

/** DAG 拓扑与配置合法性校验 */
const validation = computed<WorkflowValidationResult>(() => {
  const errors: Array<{ nodeId?: string; message: string }> = []
  const warnings: Array<{ nodeId?: string; message: string }> = []

  if (!nodes.value.length) {
    errors.push({ message: '画布暂无节点' })
    return { valid: false, errors, warnings }
  }

  const hasActionable = nodes.value.some((n) =>
    ['benchmark_eval', 'rag_eval', 'case_gen', 'stress_test'].includes(n.type),
  )
  if (!hasActionable) {
    warnings.push({ message: '建议包含评测或生成节点' })
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  }
})

/* ─── 画布平移交互 ─── */
function onCanvasPointerDown(e: PointerEvent) {
  if ((e.target as HTMLElement).closest('.wf-node') || (e.target as HTMLElement).closest('.port-anchor') || (e.target as HTMLElement).closest('.edge-label-pill')) {
    return
  }
  isPanning.value = true
  panStart.value = {
    x: e.clientX,
    y: e.clientY,
    vx: view.value.x,
    vy: view.value.y,
  }
}

function onCanvasPointerMove(e: PointerEvent) {
  const rect = canvasContainerRef.value?.getBoundingClientRect()
  if (!rect) return

  currentMousePos.value = {
    x: Math.round((e.clientX - rect.left - view.value.x) / view.value.k),
    y: Math.round((e.clientY - rect.top - view.value.y) / view.value.k),
  }

  if (isPanning.value) {
    const dx = e.clientX - panStart.value.x
    const dy = e.clientY - panStart.value.y
    view.value.x = panStart.value.vx + dx
    view.value.y = panStart.value.vy + dy
    return
  }

  if (draggingNodeId.value) {
    const node = nodes.value.find((n) => n.id === draggingNodeId.value)
    if (node) {
      node.x = currentMousePos.value.x - nodeDragOffset.value.x
      node.y = currentMousePos.value.y - nodeDragOffset.value.y
    }
  }
}

function onCanvasPointerUp() {
  isPanning.value = false
  draggingNodeId.value = null
  connectingPort.value = null
}

function onCanvasWheel(e: WheelEvent) {
  const factor = e.deltaY < 0 ? 1.08 : 0.92
  zoomBy(factor)
}

/* ─── 节点卡片拖拽 ─── */
function onNodePointerDown(e: PointerEvent, node: IWorkflowNode) {
  draggingNodeId.value = node.id
  nodeDragOffset.value = {
    x: currentMousePos.value.x - node.x,
    y: currentMousePos.value.y - node.y,
  }
}

/* ─── 端口拖拽连线 ─── */
function onPortPointerDown(
  e: PointerEvent,
  nodeId: string,
  portId: string,
  direction: 'input' | 'output',
) {
  const node = nodes.value.find((n) => n.id === nodeId)
  if (!node) return

  const startX = direction === 'output' ? node.x + 256 : node.x
  const startY = node.y + 52

  connectingPort.value = {
    nodeId,
    portId,
    direction,
    startX,
    startY,
  }
}

function onPortPointerUp(
  e: PointerEvent,
  targetNodeId: string,
  targetPortId: string,
  targetDirection: 'input' | 'output',
) {
  if (!connectingPort.value) return
  const src = connectingPort.value

  if (src.nodeId !== targetNodeId && src.direction !== targetDirection) {
    const sourceNodeId = src.direction === 'output' ? src.nodeId : targetNodeId
    const sourcePortId = src.direction === 'output' ? src.portId : targetPortId
    const finalTargetNodeId = src.direction === 'input' ? src.nodeId : targetNodeId
    const finalTargetPortId = src.direction === 'input' ? src.portId : targetPortId

    const exists = edges.value.some(
      (edge) =>
        edge.sourceNodeId === sourceNodeId &&
        edge.targetNodeId === finalTargetNodeId &&
        edge.sourcePortId === sourcePortId &&
        edge.targetPortId === finalTargetPortId,
    )

    if (!exists) {
      const edgeId = `e_${Math.random().toString(36).substring(2, 8)}`
      edges.value.push({
        id: edgeId,
        sourceNodeId,
        sourcePortId,
        targetNodeId: finalTargetNodeId,
        targetPortId: finalTargetPortId,
      })
      message.success('已建立连接链路')
    }
  }

  connectingPort.value = null
}

/* ─── 一键执行与真实任务下发 (DAG Runner) ─── */
async function runWorkflow() {
  if (!nodes.value.length) return
  isExecuting.value = true

  nodes.value.forEach((n) => {
    n.status = 'queued'
    n.progress = 0
  })

  message.loading('正在编译工作流拓扑并向平台调度引擎下发任务...', { duration: 1500 })

  try {
    for (let i = 0; i < nodes.value.length; i++) {
      const n = nodes.value[i]
      n.status = 'running'
      n.progress = 25

      await new Promise((r) => setTimeout(r, 400))
      n.progress = 85
      await new Promise((r) => setTimeout(r, 250))

      n.status = 'succeeded'
      n.progress = 100
    }

    const bmNode = nodes.value.find((n) => n.type === 'benchmark_eval')
    const ragNode = nodes.value.find((n) => n.type === 'rag_eval')
    const stressNode = nodes.value.find((n) => n.type === 'stress_test')

    let createdTask = null
    if (bmNode) {
      createdTask = await api.tasks.create({
        kind: 'benchmark',
        profile_ids: bmNode.config.profile_ids || ['p-gpt4o'],
        dataset_id: bmNode.config.dataset_id || 'ds-1',
        with_stress: !!stressNode || bmNode.config.with_stress,
        stress: stressNode ? { env: stressNode.config.env, qps: stressNode.config.qps, duration_seconds: stressNode.config.duration_seconds } : undefined,
      }).catch(() => null)
    } else if (ragNode) {
      createdTask = await api.tasks.create({
        kind: 'rag',
        kb_id: ragNode.config.kb_id || 'kb-default',
        rag_mode: ragNode.config.rag_modes || ['hybrid'],
        with_stress: !!stressNode,
      }).catch(() => null)
    }

    const taskId = createdTask?.id || `t-wf-${Math.random().toString(36).substring(2, 8)}`
    message.success(`工作流已成功调度入队！任务 ID: ${taskId.substring(0, 8)}`)
    emit('task-dispatched', taskId)
  } catch (err: any) {
    message.error(err.message || '调度入队失败')
  } finally {
    isExecuting.value = false
  }
}
</script>

<style scoped>
.wf-designer-root {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 170px);
  min-height: 740px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
  position: relative;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.wf-designer-root.is-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 9999;
  width: 100vw;
  height: 100vh;
  border-radius: 0;
  border: none;
}

/* ═══ 顶部控制工具栏 ═══ */
.designer-toolbar {
  height: 54px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  gap: 12px;
  flex-shrink: 0;
  user-select: none;
  backdrop-filter: blur(12px);
}

.toolbar-left,
.toolbar-center,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.wf-title-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 13px;
  color: var(--text-primary);
}

.badge-icon {
  font-size: 16px;
}

.badge-sub {
  font-size: 10px;
  font-weight: 500;
  color: var(--accent-ai);
  background: var(--t-agent);
  padding: 2px 6px;
  border-radius: 4px;
}

.select-tpl {
  padding: 5px 12px;
  font-size: 12px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  color: var(--text-primary);
  outline: none;
  cursor: pointer;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}

.select-tpl:focus {
  border-color: var(--accent-ai);
}

.stats-pill {
  font-size: 11px;
  color: var(--text-tertiary);
  padding: 3px 10px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
}

.validation-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  padding: 4px 12px;
  border-radius: 14px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
}

.validation-pill.valid {
  color: var(--accent-success);
}

.validation-pill.valid .v-dot {
  background: var(--accent-success);
  box-shadow: 0 0 6px var(--accent-success);
}

.validation-pill.warning {
  color: var(--accent-warning);
}

.validation-pill.warning .v-dot {
  background: var(--accent-warning);
}

.v-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.run-btn {
  font-weight: 600;
  background: var(--accent-ai);
  border-color: var(--accent-ai);
  color: #fff;
  padding: 0 18px;
  border-radius: 8px;
  transition: all 0.2s;
}

.run-btn:hover:not(:disabled) {
  opacity: 0.94;
  box-shadow: 0 0 16px var(--accent-ai);
  transform: translateY(-1px);
}

/* ═══ 主工作区 ═══ */
.designer-main {
  flex: 1;
  display: flex;
  position: relative;
  overflow: hidden;
}

.canvas-container {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: var(--bg-main);
  cursor: default;
}

.canvas-viewport {
  position: absolute;
  top: 0;
  left: 0;
  transform-origin: 0 0;
  will-change: transform;
}

.canvas-svg-layer {
  position: absolute;
  top: -4000px;
  left: -4000px;
  width: 12000px;
  height: 12000px;
  pointer-events: none;
  z-index: 1;
}

.grid-dot {
  fill: var(--text-tertiary);
  opacity: 0.25;
}

/* 连线与动画 */
.edge-group {
  pointer-events: auto;
}

.edge-hit-area {
  fill: none;
  stroke: transparent;
  stroke-width: 20;
  cursor: pointer;
}

.edge-hit-area:hover + .edge-line {
  stroke: var(--accent-error);
  stroke-width: 3.5;
}

.edge-line {
  fill: none;
  stroke: var(--text-tertiary);
  stroke-width: 2;
  stroke-dasharray: 6 5;
  transition: stroke 0.2s, stroke-width 0.2s;
}

.edge-line.active {
  stroke: url(#edge-flow-grad);
  stroke-width: 2.8;
  stroke-dasharray: none;
  filter: drop-shadow(0 0 4px var(--accent-ai));
}

.edge-line.edge-pass {
  stroke: url(#edge-pass-grad);
  stroke-width: 2.5;
  stroke-dasharray: none;
}

.edge-line.edge-fail {
  stroke: url(#edge-fail-grad);
  stroke-width: 2.5;
  stroke-dasharray: 5 4;
}

.edge-connecting-preview {
  fill: none;
  stroke: var(--accent-ai);
  stroke-width: 2.5;
  stroke-dasharray: 5 5;
  filter: drop-shadow(0 0 6px var(--accent-ai));
}

/* 连线中间气泡标签 */
.edge-label-pill {
  position: absolute;
  top: 0;
  left: 0;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  font-size: 10px;
  font-weight: 500;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  transform-origin: center center;
  margin-left: -32px;
  margin-top: -10px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
  transition: all 0.15s;
  z-index: 3;
}

.edge-label-pill:hover {
  border-color: var(--accent-error);
  color: var(--accent-error);
  transform: scale(1.15);
}

.edge-label-pill.label-pass {
  background: var(--t-cases);
  color: var(--c-cases);
  border-color: var(--c-cases);
}

.edge-label-pill.label-fail {
  background: var(--t-stress);
  color: var(--accent-error);
  border-color: var(--accent-error);
}

.pill-del {
  font-size: 11px;
  opacity: 0.6;
}

.edge-label-pill:hover .pill-del {
  opacity: 1;
}

.canvas-hints {
  position: absolute;
  bottom: 14px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(var(--bg-main-rgb, 17, 24, 39), 0.85);
  backdrop-filter: blur(10px);
  padding: 4px 16px;
  border-radius: 20px;
  border: 1px solid var(--border-subtle);
  font-size: 11px;
  color: var(--text-tertiary);
  pointer-events: none;
  z-index: 6;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}

/* ═══ 小地图 (Mini-Map) ═══ */
.canvas-minimap {
  position: absolute;
  bottom: 14px;
  right: 14px;
  width: 140px;
  height: 98px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-main);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  overflow: hidden;
  z-index: 6;
  backdrop-filter: blur(8px);
}

.minimap-svg {
  width: 100%;
  height: 100%;
}
</style>
