<template>
  <div class="workspace-image-viewer">
    <!-- 顶部控制条 -->
    <div class="image-toolbar">
      <div class="zoom-controls">
        <button class="tool-btn" title="缩小" @click="zoomOut">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8" />
            <line x1="8" y1="11" x2="14" y2="11" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </button>
        <span class="zoom-text">{{ Math.round(scale * 100) }}%</span>
        <button class="tool-btn" title="放大" @click="zoomIn">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8" />
            <line x1="11" y1="8" x2="11" y2="14" />
            <line x1="8" y1="11" x2="14" y2="11" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </button>
        <button class="tool-btn" title="1:1 还原" @click="resetScale">1:1</button>
        <button class="tool-btn" title="适应窗口" @click="fitToWindow">适应</button>
        <button class="tool-btn" title="顺时针旋转 90°" @click="rotate">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
          </svg>
        </button>
      </div>
      <div class="image-meta">
        <span v-if="naturalWidth && naturalHeight">{{ naturalWidth }} × {{ naturalHeight }} px</span>
        <span v-if="fileSize" class="meta-sep">·</span>
        <span v-if="fileSize">{{ formatBytes(fileSize) }}</span>
        <button class="tool-btn download-btn" title="下载原图" @click="download">
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
    <div class="image-stage checkerboard" @wheel.prevent="handleWheel">
      <div
        class="image-wrapper"
        :style="{
          transform: `scale(${scale}) rotate(${rotation}deg)`,
          transition: isDragging ? 'none' : 'transform 0.15s ease-out',
        }"
      >
        <img
          ref="imgRef"
          :src="src"
          :alt="alt"
          class="stage-img"
          @load="onImageLoad"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
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

watch(
  () => props.src,
  () => {
    scale.value = 1
    rotation.value = 0
  },
)

function onImageLoad(): void {
  if (imgRef.value) {
    naturalWidth.value = imgRef.value.naturalWidth
    naturalHeight.value = imgRef.value.naturalHeight
  }
}

function zoomIn(): void {
  scale.value = Math.min(5, Number((scale.value + 0.25).toFixed(2)))
}

function zoomOut(): void {
  scale.value = Math.max(0.1, Number((scale.value - 0.25).toFixed(2)))
}

function resetScale(): void {
  scale.value = 1
  rotation.value = 0
}

function fitToWindow(): void {
  scale.value = 0.85
}

function rotate(): void {
  rotation.value = (rotation.value + 90) % 360
}

function handleWheel(e: WheelEvent): void {
  if (e.deltaY < 0) {
    zoomIn()
  } else {
    zoomOut()
  }
}

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
}

.zoom-controls {
  display: flex;
  align-items: center;
  gap: 8px;
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
}

.image-stage:active {
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
  display: flex;
  align-items: center;
  justify-content: center;
  transform-origin: center center;
}

.stage-img {
  max-width: 80vw;
  max-height: 70vh;
  object-fit: contain;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.12);
  border-radius: 4px;
}
</style>
