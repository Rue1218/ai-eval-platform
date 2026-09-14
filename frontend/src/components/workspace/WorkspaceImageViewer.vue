<template>
  <div class="workspace-image-viewer">
    <!-- 顶部控制条 -->
    <div class="image-toolbar">
      <div class="zoom-controls">
        <button type="button" class="tool-btn" title="缩小（−）" aria-label="缩小" :disabled="!ready || scale <= MIN_IMAGE_SCALE" @click="zoomOut">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8" />
            <line x1="8" y1="11" x2="14" y2="11" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </button>
        <span class="zoom-text">{{ Math.round(scale * 100) }}%</span>
        <button type="button" class="tool-btn" title="放大（+）" aria-label="放大" :disabled="!ready || scale >= MAX_IMAGE_SCALE" @click="zoomIn">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8" />
            <line x1="11" y1="8" x2="11" y2="14" />
            <line x1="8" y1="11" x2="14" y2="11" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </button>
        <button type="button" class="tool-btn" title="1:1 原始像素" :disabled="!ready" @click="resetScale">1:1</button>
        <button type="button" class="tool-btn" title="适应窗口（0）" :disabled="!ready" @click="fitToWindow">适应</button>
        <button type="button" class="tool-btn" title="顺时针旋转 90°" aria-label="顺时针旋转 90 度" :disabled="!ready" @click="rotate">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
          </svg>
        </button>
      </div>
      <div class="image-meta">
        <span v-if="naturalWidth && naturalHeight">{{ naturalWidth }} × {{ naturalHeight }} px</span>
        <span v-if="fileSize" class="meta-sep">·</span>
        <span v-if="fileSize">{{ formatBytes(fileSize) }}</span>
        <button type="button" class="tool-btn download-btn" title="下载原图" @click="download">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          <span>下载</span>
        </button>
      </div>
    </div>

    <!-- 图片展示主舞台（棋盘底纹 + 居中） -->
    <div ref="stageRef" class="image-stage checkerboard" :class="{ dragging: isDragging }"
      tabindex="0" aria-label="图片预览区域，可滚轮缩放、拖动查看，按加减键缩放，按 0 适应窗口"
      @wheel.prevent="handleWheel" @keydown="handleKeydown"
      @pointerdown="startDrag" @pointermove="moveDrag" @pointerup="stopDrag"
      @pointercancel="stopDrag" @lostpointercapture="stopDrag"
    >
      <span v-if="loadError" class="image-state" role="alert">图片加载失败，请尝试重新打开或下载原图。</span>
      <span v-else-if="!ready" class="image-state" role="status">正在加载图片…</span>
      <div
        class="image-wrapper"
        :style="{
          transform: `translate(${offsetX}px, ${offsetY}px) scale(${scale}) rotate(${rotation}deg)`,
          visibility: ready ? 'visible' : 'hidden',
        }"
      >
        <img
          ref="imgRef"
          :key="src"
          :src="src"
          :alt="alt"
          class="stage-img"
          :style="{ width: `${naturalWidth}px`, height: `${naturalHeight}px` }"
          :draggable="false"
          @load="onImageLoad"
          @error="loadError = true"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { clampImageOffset, clampImageScale, fitImageScale, MAX_IMAGE_SCALE, MIN_IMAGE_SCALE } from '../../utils/imageViewport'
import { formatBytes } from '../../utils/format'

const props = defineProps<{
  src: string
  alt?: string
  fileSize?: number
}>()

const scale = ref(1)
const rotation = ref(0)
const naturalWidth = ref(0)
const naturalHeight = ref(0)
const isDragging = ref(false)
const imgRef = ref<HTMLImageElement | null>(null)
const stageRef = ref<HTMLDivElement | null>(null)
const loadError = ref(false)
const offsetX = ref(0)
const offsetY = ref(0)
const ready = computed(() => naturalWidth.value > 0 && naturalHeight.value > 0 && !loadError.value)
let fitMode = true
let observer: ResizeObserver | undefined
// 只捕获一根指针，鼠标与触屏共用拖动路径，避免多指交替跳动。
let drag: { id: number; x: number; y: number } | null = null

watch(
  () => props.src,
  () => {
    scale.value = 1
    rotation.value = 0
    naturalWidth.value = 0
    naturalHeight.value = 0
    loadError.value = false
    offsetX.value = offsetY.value = 0
    fitMode = true
    stopDrag()
  },
)

/** 首次显示按真实容器尺寸适配，不依赖写死的视口比例。 */
function onImageLoad(): void {
  if (imgRef.value) {
    naturalWidth.value = imgRef.value.naturalWidth
    naturalHeight.value = imgRef.value.naturalHeight
    loadError.value = false
    fitToWindow()
  }
}

/** 缩放后重新限制偏移，保证图片不会移出可见区域。 */
function constrainOffset(): void {
  const stage = stageRef.value
  if (!stage) return
  const swapped = rotation.value % 180 !== 0
  offsetX.value = clampImageOffset(offsetX.value, (swapped ? naturalHeight.value : naturalWidth.value) * scale.value, stage.clientWidth)
  offsetY.value = clampImageOffset(offsetY.value, (swapped ? naturalWidth.value : naturalHeight.value) * scale.value, stage.clientHeight)
}

/** 围绕舞台中心缩放，保留当前查看区域；比例严格限定在 1%–500%。 */
function setScale(value: number): void {
  if (!ready.value) return
  fitMode = false
  const next = clampImageScale(value)
  offsetX.value *= next / scale.value
  offsetY.value *= next / scale.value
  scale.value = next
  constrainOffset()
}

/** 采用倍率步进，大图适配比例很小时也能平滑调整。 */
function zoomIn(): void { setScale(scale.value * 1.25) }
/** 缩小与放大互为逆运算。 */
function zoomOut(): void { setScale(scale.value / 1.25) }

/** 还原到原始像素尺寸及方向，并居中展示。 */
function resetScale(): void {
  setScale(1)
  rotation.value = 0
  offsetX.value = offsetY.value = 0
}

/** 旋转后按交换的宽高适配，预留边缘空隙。 */
function fitToWindow(): void {
  const stage = stageRef.value
  if (!ready.value || !stage) return
  fitMode = true
  scale.value = fitImageScale(naturalWidth.value, naturalHeight.value, Math.max(1, stage.clientWidth - 32), Math.max(1, stage.clientHeight - 32), rotation.value)
  offsetX.value = offsetY.value = 0
}

/** 适配模式旋转后重新适配，手动缩放模式只校正拖动边界。 */
function rotate(): void {
  rotation.value = (rotation.value + 90) % 360
  if (fitMode) fitToWindow()
  else constrainOffset()
}

/** 滚轮只作用于图片舞台，不触发页面滚动；零增量不缩放。 */
function handleWheel(e: WheelEvent): void {
  if (e.deltaY < 0) {
    zoomIn()
  } else if (e.deltaY > 0) {
    zoomOut()
  }
}

/** 键盘缩放仅在图片舞台获得焦点时处理，不抢占页面其他快捷键。 */
function handleKeydown(event: KeyboardEvent): void {
  if (event.ctrlKey || event.metaKey || event.altKey) return
  if (['+', '=', '-', '0'].includes(event.key)) {
    event.preventDefault()
    if (event.key === '-') zoomOut()
    else if (event.key === '0') fitToWindow()
    else zoomIn()
  }
}

/** 捕获指针，拖动越过窗口边缘也能可靠结束。 */
function startDrag(event: PointerEvent): void {
  if (!ready.value || event.button !== 0 || drag) return
  stageRef.value?.focus()
  drag = { id: event.pointerId, x: event.clientX - offsetX.value, y: event.clientY - offsetY.value }
  stageRef.value?.setPointerCapture(event.pointerId)
  isDragging.value = true
  event.preventDefault()
}

/** 拖动只修改平移量，缩放与旋转保持不变。 */
function moveDrag(event: PointerEvent): void {
  if (!drag || drag.id !== event.pointerId) return
  offsetX.value = event.clientX - drag.x
  offsetY.value = event.clientY - drag.y
  constrainOffset()
}

/** 结束、取消、换图与卸载均释放拖动状态。 */
function stopDrag(): void {
  const id = drag?.id
  drag = null
  isDragging.value = false
  if (id !== undefined && stageRef.value?.hasPointerCapture(id)) stageRef.value.releasePointerCapture(id)
}

onMounted(() => {
  observer = new ResizeObserver(() => { if (fitMode) fitToWindow(); else constrainOffset() })
  if (stageRef.value) observer.observe(stageRef.value)
})
onBeforeUnmount(() => { observer?.disconnect(); stopDrag() })

/** 下载沿用原图地址，不导出缩放后的渲染内容。 */
function download(): void {
  const link = document.createElement('a')
  link.href = props.src
  link.download = props.alt || 'image'
  link.click()
}
</script>

<style scoped>
.workspace-image-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  background: var(--bg-main, #ffffff);
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--border-subtle, #e5e7eb);
}

.image-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: var(--bg-elevated, #f4f8f8);
  border-bottom: 1px solid var(--border-subtle, #e5e7eb);
  font-size: 13px;
  user-select: none;
  flex-wrap: wrap;
  gap: 8px;
  flex-shrink: 0;
}

.zoom-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle, #e5e7eb);
  background: var(--bg-main, #ffffff);
  color: var(--text-primary, #111827);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tool-btn:hover {
  background: var(--row-hover, rgba(17, 24, 39, 0.04));
  border-color: var(--text-tertiary, #9ca3af);
}
.tool-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.tool-btn:focus-visible, .image-stage:focus-visible { outline: 2px solid var(--accent-ai, #1f5947); outline-offset: -2px; }

.download-btn {
  color: var(--accent-ai, #1f5947);
  border-color: color-mix(in srgb, var(--accent-ai, #1f5947) 30%, transparent);
}

.download-btn:hover {
  background: color-mix(in srgb, var(--accent-ai, #1f5947) 8%, transparent);
  border-color: var(--accent-ai, #1f5947);
}

.zoom-text {
  min-width: 48px;
  text-align: center;
  font-family: var(--font-mono, monospace);
  color: var(--text-secondary, #4b5563);
  font-size: 12px;
  font-weight: 500;
}

.image-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary, #4b5563);
  font-size: 12px;
}

.meta-sep {
  opacity: 0.35;
}

.image-stage {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  cursor: grab;
  min-height: 0;
  touch-action: none;
  user-select: none;
}

.image-stage.dragging {
  cursor: grabbing;
}

.checkerboard {
  background-color: #ffffff;
  background-image: linear-gradient(45deg, #f1f5f9 25%, transparent 25%),
    linear-gradient(-45deg, #f1f5f9 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #f1f5f9 75%),
    linear-gradient(-45deg, transparent 75%, #f1f5f9 75%);
  background-size: 20px 20px;
  background-position: 0 0, 0 10px, 10px -10px, -10px 0px;
}

[data-theme='dark'] .checkerboard {
  background-color: #0b0f19;
  background-image: linear-gradient(45deg, #131b2e 25%, transparent 25%),
    linear-gradient(-45deg, #131b2e 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #131b2e 75%),
    linear-gradient(-45deg, transparent 75%, #131b2e 75%);
}

.image-wrapper {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  transform-origin: center center;
}

.stage-img {
  max-width: none;
  max-height: none;
  flex-shrink: 0;
  object-fit: contain;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.12);
  border-radius: 4px;
}
.image-state { position: absolute; padding: 20px; color: var(--text-secondary, #4b5563); text-align: center; }
</style>
