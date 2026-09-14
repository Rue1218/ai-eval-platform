<template>
  <div
    ref="viewerContainerRef"
    class="workspace-video-viewer"
    tabindex="0"
    @keydown="handleKeydown"
    @mouseenter="onUserActivity"
    @mousemove="onUserActivity"
    @mouseleave="onMouseLeave"
  >
    <!-- 顶部状态与元信息工具栏 -->
    <div class="video-toolbar">
      <div class="toolbar-left">
        <span class="format-badge">{{ videoFormat }}</span>
        <span class="video-title" :title="fileName">{{ fileName }}</span>
      </div>

      <div class="toolbar-meta">
        <span v-if="videoWidth && videoHeight" class="meta-item">
          {{ videoWidth }} × {{ videoHeight }}
        </span>
        <span v-if="videoWidth && duration" class="meta-sep">·</span>
        <span v-if="duration" class="meta-item">{{ formatTime(duration) }}</span>
        <span v-if="fileSize" class="meta-sep">·</span>
        <span v-if="fileSize" class="meta-item">{{ formatBytes(fileSize) }}</span>
      </div>

      <div class="toolbar-actions">
        <button
          class="tool-btn"
          :class="{ 'is-active': isLooping }"
          :title="isLooping ? '循环播放: 开启' : '循环播放: 关闭'"
          @click="toggleLoop"
        >
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="17 1 21 5 17 9" />
            <path d="M3 11V9a4 4 0 0 1 4-4h14" />
            <polyline points="7 23 3 19 7 15" />
            <path d="M21 13v2a4 4 0 0 1-4 4H3" />
          </svg>
          <span class="btn-text">循环</span>
        </button>

        <button
          v-if="supportsPiP"
          class="tool-btn"
          :class="{ 'is-active': isPiP }"
          title="画中画模式 (PiP)"
          @click="togglePiP"
        >
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2" />
            <rect x="12" y="9" width="8" height="6" rx="1" fill="currentColor" fill-opacity="0.3" />
          </svg>
          <span class="btn-text">画中画</span>
        </button>

        <button class="tool-btn" title="下载原视频文件" @click="downloadVideo">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          <span class="btn-text">下载</span>
        </button>

        <button class="tool-btn" :title="isFullscreen ? '退出全屏' : '全屏播放 (F)'" @click="toggleFullscreen">
          <svg v-if="!isFullscreen" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
          </svg>
          <svg v-else viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3" />
          </svg>
        </button>
      </div>
    </div>

    <!-- 播放舞台主区域 -->
    <div class="video-stage" @click="handleStageClick">
      <video
        ref="videoRef"
        class="main-video"
        :src="currentSrc"
        :loop="isLooping"
        playsinline
        preload="metadata"
        @loadedmetadata="onLoadedMetadata"
        @timeupdate="onTimeUpdate"
        @progress="onProgress"
        @play="isPlaying = true"
        @pause="isPlaying = false"
        @ended="onEnded"
        @waiting="isBuffering = true"
        @playing="isBuffering = false"
        @canplay="isBuffering = false"
        @error="onError"
        @enterpictureinpicture="isPiP = true"
        @leavepictureinpicture="isPiP = false"
      />

      <!-- 居中大播放/暂停视觉反馈 -->
      <transition name="fade">
        <div v-if="!isPlaying && !hasError && !isBuffering" class="big-play-btn" @click.stop="togglePlay">
          <svg viewBox="0 0 24 24" width="36" height="36" fill="currentColor">
            <polygon points="5 3 19 12 5 21 5 3" />
          </svg>
        </div>
      </transition>

      <!-- 缓冲菊花 -->
      <div v-if="isBuffering && !hasError" class="buffering-spinner">
        <div class="spinner-circle" />
        <span class="spinner-text">缓冲中…</span>
      </div>

      <!-- 快进/快退浮层提示 -->
      <transition name="pop">
        <div v-if="seekFeedbackText" class="seek-feedback-badge">
          {{ seekFeedbackText }}
        </div>
      </transition>

      <!-- 解码错误 / 无法播放容错卡片 -->
      <div v-if="hasError" class="video-error-overlay" @click.stop>
        <div class="error-card">
          <div class="error-icon">⚠️</div>
          <h3 class="error-title">该视频暂无法在当前浏览器直接解码</h3>
          <p class="error-desc">
            浏览器未原生支持此文件的编码或容器封装（常见于某些 MKV、AVI 或专有编码）。推荐使用标准 MP4 (H.264/AAC) 或 WebM 格式，或直接下载到本地专业播放器中查看。
          </p>
          <div class="error-actions">
            <button class="btn btn-primary" @click="downloadVideo">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              <span>下载原文件</span>
            </button>
            <button v-if="fallbackBlobUrl && currentSrc !== fallbackBlobUrl" class="btn" @click="tryFallbackBlob">
              尝试 Blob 重载
            </button>
            <button class="btn" @click="reloadVideo">
              重试加载
            </button>
          </div>
        </div>
      </div>

      <!-- 底部悬浮交互式控制条 -->
      <div
        class="video-controls-bar"
        :class="{ 'is-hidden': controlsHidden && isPlaying && !hasError }"
        @click.stop
      >
        <!-- 进度条轨道 -->
        <div
          ref="progressBarRef"
          class="progress-bar-container"
          @mousedown="onProgressMouseDown"
          @mousemove="onProgressHover"
          @mouseleave="onProgressHoverEnd"
        >
          <!-- 悬停时间浮动标签 -->
          <div
            v-if="hoverTimeText"
            class="hover-time-bubble"
            :style="{ left: `${hoverPercent}%` }"
          >
            {{ hoverTimeText }}
          </div>

          <div class="progress-track">
            <!-- 缓冲段 -->
            <div class="progress-buffered" :style="{ width: `${bufferedPercent}%` }" />
            <!-- 已播放段 -->
            <div class="progress-played" :style="{ width: `${playedPercent}%` }" />
            <!-- 拖拽手柄 -->
            <div class="progress-thumb" :style="{ left: `${playedPercent}%` }" />
          </div>
        </div>

        <!-- 按钮与指标控制行 -->
        <div class="controls-row">
          <div class="controls-left">
            <!-- 播放/暂停 -->
            <button class="ctrl-btn" :title="isPlaying ? '暂停 (空格)' : '播放 (空格)'" @click="togglePlay">
              <svg v-if="!isPlaying" viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
              <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
                <rect x="6" y="4" width="4" height="16" />
                <rect x="14" y="4" width="4" height="16" />
              </svg>
            </button>

            <!-- 快退 5 秒 -->
            <button class="ctrl-btn" title="快退 5 秒 (←)" @click="seekBy(-5)">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="11 19 2 12 11 5 11 19" />
                <polygon points="22 19 13 12 22 5 22 19" />
              </svg>
            </button>

            <!-- 快进 5 秒 -->
            <button class="ctrl-btn" title="快进 5 秒 (→)" @click="seekBy(5)">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="13 19 22 12 13 5 13 19" />
                <polygon points="2 19 11 12 2 5 2 19" />
              </svg>
            </button>

            <!-- 时间码 -->
            <div class="time-display mono">
              <span class="time-current">{{ formatTime(currentTime) }}</span>
              <span class="time-divider">/</span>
              <span class="time-duration">{{ formatTime(duration) }}</span>
            </div>
          </div>

          <div class="controls-right">
            <!-- 音量控制 -->
            <div class="volume-control-group">
              <button class="ctrl-btn" :title="isMuted ? '取消静音 (M)' : '静音 (M)'" @click="toggleMute">
                <svg v-if="isMuted || volume === 0" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                  <line x1="23" y1="9" x2="17" y2="15" />
                  <line x1="17" y1="9" x2="23" y2="15" />
                </svg>
                <svg v-else-if="volume < 0.5" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                  <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
                </svg>
                <svg v-else viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                  <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07" />
                </svg>
              </button>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                class="volume-slider"
                :value="isMuted ? 0 : volume"
                @input="onVolumeInput"
              />
            </div>

            <!-- 倍速选择 -->
            <div class="playback-rate-menu">
              <button class="ctrl-btn rate-btn" title="播放倍速" @click="showRateMenu = !showRateMenu">
                {{ playbackRate === 1 ? '倍速' : `${playbackRate}x` }}
              </button>
              <div v-if="showRateMenu" class="rate-dropdown" @mouseleave="showRateMenu = false">
                <button
                  v-for="rate in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]"
                  :key="rate"
                  class="rate-option"
                  :class="{ 'is-selected': playbackRate === rate }"
                  @click="setPlaybackRate(rate)"
                >
                  {{ rate }}x
                </button>
              </div>
            </div>

            <!-- 全屏按钮 -->
            <button class="ctrl-btn" :title="isFullscreen ? '退出全屏 (F)' : '全屏 (F)'" @click="toggleFullscreen">
              <svg v-if="!isFullscreen" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="15 3 21 3 21 9" />
                <polyline points="9 21 3 21 3 15" />
                <line x1="21" y1="3" x2="14" y2="10" />
                <line x1="3" y1="21" x2="10" y2="14" />
              </svg>
              <svg v-else viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="4 14 10 14 10 20" />
                <polyline points="20 10 14 10 14 4" />
                <line x1="14" y1="10" x2="21" y2="3" />
                <line x1="10" y1="14" x2="3" y2="21" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps<{
  src: string
  fileName: string
  fileSize?: number
  fallbackBlobUrl?: string | null
}>()

const emit = defineEmits<{
  (e: 'download'): void
}>()

// 元素引用
const viewerContainerRef = ref<HTMLDivElement | null>(null)
const videoRef = ref<HTMLVideoElement | null>(null)
const progressBarRef = ref<HTMLDivElement | null>(null)

// 播放状态
const currentSrc = ref(props.src)
const isPlaying = ref(false)
const isBuffering = ref(false)
const isLooping = ref(false)
const isPiP = ref(false)
const isFullscreen = ref(false)
const hasError = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const bufferedEnd = ref(0)
const volume = ref(1)
const isMuted = ref(false)
const playbackRate = ref(1)
const showRateMenu = ref(false)

// 视频元数据
const videoWidth = ref(0)
const videoHeight = ref(0)

// 控制条自动隐藏定时器
const controlsHidden = ref(false)
let hideTimer: any = null

// 快进快退视觉反馈
const seekFeedbackText = ref('')
let feedbackTimer: any = null

// 进度条悬浮提示
const hoverPercent = ref(0)
const hoverTimeText = ref('')

const supportsPiP = typeof document !== 'undefined' && 'pictureInPictureEnabled' in document

const videoFormat = computed(() => {
  const ext = props.fileName.toLowerCase().split('.').pop() || ''
  return ext.toUpperCase()
})

const playedPercent = computed(() => {
  if (!duration.value || duration.value <= 0) return 0
  return Math.min(100, Math.max(0, (currentTime.value / duration.value) * 100))
})

const bufferedPercent = computed(() => {
  if (!duration.value || duration.value <= 0) return 0
  return Math.min(100, Math.max(0, (bufferedEnd.value / duration.value) * 100))
})

// 监听源地址变更
watch(
  () => props.src,
  (newSrc) => {
    currentSrc.value = newSrc
    hasError.value = false
    isPlaying.value = false
    currentTime.value = 0
    duration.value = 0
    if (videoRef.value) {
      videoRef.value.load()
    }
  },
)

// 音量与偏好记忆
onMounted(() => {
  const savedVol = localStorage.getItem('ae_workspace_video_volume')
  if (savedVol !== null) {
    const v = Number.parseFloat(savedVol)
    if (!Number.isNaN(v) && v >= 0 && v <= 1) {
      volume.value = v
      if (videoRef.value) videoRef.value.volume = v
    }
  }

  document.addEventListener('fullscreenchange', handleFullscreenChange)
})

onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', handleFullscreenChange)
  if (hideTimer) clearTimeout(hideTimer)
  if (feedbackTimer) clearTimeout(feedbackTimer)
})

function onLoadedMetadata(): void {
  if (!videoRef.value) return
  hasError.value = false
  duration.value = videoRef.value.duration || 0
  videoWidth.value = videoRef.value.videoWidth || 0
  videoHeight.value = videoRef.value.videoHeight || 0
  videoRef.value.volume = volume.value
}

function onTimeUpdate(): void {
  if (!videoRef.value) return
  currentTime.value = videoRef.value.currentTime || 0
}

function onProgress(): void {
  if (!videoRef.value) return
  const buf = videoRef.value.buffered
  if (buf && buf.length > 0) {
    bufferedEnd.value = buf.end(buf.length - 1)
  }
}

function onEnded(): void {
  isPlaying.value = false
  if (!isLooping.value) {
    showControls()
  }
}

function onError(): void {
  hasError.value = true
  isBuffering.value = false
  isPlaying.value = false
}

function tryFallbackBlob(): void {
  if (props.fallbackBlobUrl) {
    currentSrc.value = props.fallbackBlobUrl
    hasError.value = false
    if (videoRef.value) {
      videoRef.value.load()
    }
  }
}

function reloadVideo(): void {
  hasError.value = false
  if (videoRef.value) {
    videoRef.value.load()
  }
}

function togglePlay(): void {
  if (!videoRef.value || hasError.value) return
  if (videoRef.value.paused) {
    void videoRef.value.play()
    startHideTimer()
  } else {
    videoRef.value.pause()
    showControls()
  }
}

function handleStageClick(): void {
  togglePlay()
}

function seekBy(deltaSeconds: number): void {
  if (!videoRef.value || !duration.value) return
  const target = Math.max(0, Math.min(duration.value, videoRef.value.currentTime + deltaSeconds))
  videoRef.value.currentTime = target
  currentTime.value = target

  // 显示跳秒气泡反馈
  seekFeedbackText.value = deltaSeconds > 0 ? `+${deltaSeconds}s` : `${deltaSeconds}s`
  if (feedbackTimer) clearTimeout(feedbackTimer)
  feedbackTimer = setTimeout(() => {
    seekFeedbackText.value = ''
  }, 700)
}

function toggleMute(): void {
  if (!videoRef.value) return
  isMuted.value = !isMuted.value
  videoRef.value.muted = isMuted.value
}

function onVolumeInput(e: Event): void {
  const val = Number.parseFloat((e.target as HTMLInputElement).value)
  volume.value = val
  if (videoRef.value) {
    videoRef.value.volume = val
    if (val > 0 && isMuted.value) {
      isMuted.value = false
      videoRef.value.muted = false
    }
  }
  localStorage.setItem('ae_workspace_video_volume', val.toString())
}

function setPlaybackRate(rate: number): void {
  playbackRate.value = rate
  if (videoRef.value) {
    videoRef.value.playbackRate = rate
  }
  showRateMenu.value = false
}

function toggleLoop(): void {
  isLooping.value = !isLooping.value
}

async function togglePiP(): Promise<void> {
  if (!videoRef.value) return
  try {
    if (document.pictureInPictureElement) {
      await document.exitPictureInPicture()
      isPiP.value = false
    } else {
      await videoRef.value.requestPictureInPicture()
      isPiP.value = true
    }
  } catch (err) {
    console.warn('PiP 操作失败', err)
  }
}

async function toggleFullscreen(): Promise<void> {
  const container = viewerContainerRef.value
  if (!container) return
  if (!document.fullscreenElement) {
    try {
      await container.requestFullscreen()
      isFullscreen.value = true
    } catch {
      // 降级使用视频全屏
      if (videoRef.value && 'webkitEnterFullscreen' in videoRef.value) {
        // iOS Safari 私有全屏 API（不在标准 HTMLVideoElement 类型中）
        ;(videoRef.value as HTMLVideoElement & { webkitEnterFullscreen: () => void }).webkitEnterFullscreen()
      }
    }
  } else {
    await document.exitFullscreen()
    isFullscreen.value = false
  }
}

function handleFullscreenChange(): void {
  isFullscreen.value = !!document.fullscreenElement
}

function onProgressMouseDown(e: MouseEvent): void {
  if (!progressBarRef.value || !duration.value || !videoRef.value) return
  const rect = progressBarRef.value.getBoundingClientRect()
  const clickX = e.clientX - rect.left
  const pct = Math.max(0, Math.min(1, clickX / rect.width))
  const newTime = pct * duration.value
  videoRef.value.currentTime = newTime
  currentTime.value = newTime

  function onMouseMove(moveEvent: MouseEvent): void {
    if (!progressBarRef.value || !duration.value || !videoRef.value) return
    const moveX = moveEvent.clientX - rect.left
    const movePct = Math.max(0, Math.min(1, moveX / rect.width))
    const moveTime = movePct * duration.value
    videoRef.value.currentTime = moveTime
    currentTime.value = moveTime
  }

  function onMouseUp(): void {
    window.removeEventListener('mousemove', onMouseMove)
    window.removeEventListener('mouseup', onMouseUp)
  }

  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', onMouseUp)
}

function onProgressHover(e: MouseEvent): void {
  if (!progressBarRef.value || !duration.value) return
  const rect = progressBarRef.value.getBoundingClientRect()
  const hoverX = e.clientX - rect.left
  const pct = Math.max(0, Math.min(1, hoverX / rect.width))
  hoverPercent.value = pct * 100
  hoverTimeText.value = formatTime(pct * duration.value)
}

function onProgressHoverEnd(): void {
  hoverTimeText.value = ''
}

function onUserActivity(): void {
  controlsHidden.value = false
  if (isPlaying.value) {
    startHideTimer()
  }
}

function onMouseLeave(): void {
  if (isPlaying.value) {
    controlsHidden.value = true
  }
}

function startHideTimer(): void {
  if (hideTimer) clearTimeout(hideTimer)
  hideTimer = setTimeout(() => {
    if (isPlaying.value) {
      controlsHidden.value = true
    }
  }, 2500)
}

function showControls(): void {
  controlsHidden.value = false
  if (hideTimer) clearTimeout(hideTimer)
}

function handleKeydown(e: KeyboardEvent): void {
  // 如果焦点在输入框等控件中，跳过视频快捷键
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement)?.tagName)) {
    return
  }

  if (e.code === 'Space' || e.key === ' ' || e.key === 'k' || e.key === 'K') {
    e.preventDefault()
    togglePlay()
  } else if (e.key === 'ArrowLeft' || e.key === 'j' || e.key === 'J') {
    e.preventDefault()
    seekBy(-5)
  } else if (e.key === 'ArrowRight' || e.key === 'l' || e.key === 'L') {
    e.preventDefault()
    seekBy(5)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    volume.value = Math.min(1, Number((volume.value + 0.1).toFixed(2)))
    if (videoRef.value) videoRef.value.volume = volume.value
    localStorage.setItem('ae_workspace_video_volume', volume.value.toString())
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    volume.value = Math.max(0, Number((volume.value - 0.1).toFixed(2)))
    if (videoRef.value) videoRef.value.volume = volume.value
    localStorage.setItem('ae_workspace_video_volume', volume.value.toString())
  } else if (e.key === 'm' || e.key === 'M') {
    e.preventDefault()
    toggleMute()
  } else if (e.key === 'f' || e.key === 'F') {
    e.preventDefault()
    void toggleFullscreen()
  }
}

function downloadVideo(): void {
  emit('download')
  const link = document.createElement('a')
  link.href = currentSrc.value
  link.download = props.fileName
  link.click()
}

function formatTime(seconds: number): string {
  if (!seconds || Number.isNaN(seconds) || seconds < 0) return '00:00'
  const s = Math.floor(seconds)
  const hrs = Math.floor(s / 3600)
  const mins = Math.floor((s % 3600) / 60)
  const secs = s % 60

  const paddedMins = mins.toString().padStart(2, '0')
  const paddedSecs = secs.toString().padStart(2, '0')

  if (hrs > 0) {
    return `${hrs}:${paddedMins}:${paddedSecs}`
  }
  return `${paddedMins}:${paddedSecs}`
}

function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let val = bytes
  let idx = 0
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024
    idx++
  }
  return `${val.toFixed(val >= 10 || idx === 0 ? 0 : 1)} ${units[idx]}`
}
</script>

<style scoped>
.workspace-video-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--bg-card, #111827);
  color: #f3f4f6;
  border-radius: 8px;
  overflow: hidden;
  outline: none;
  position: relative;
  user-select: none;
}

/* 顶部工具栏 */
.video-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: rgba(17, 24, 39, 0.95);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 12px;
  z-index: 10;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.format-badge {
  font-size: 11px;
  font-weight: 700;
  background: #1f5947;
  color: #ffffff;
  padding: 2px 6px;
  border-radius: 4px;
  letter-spacing: 0.5px;
}

.video-title {
  font-weight: 600;
  color: #f9fafb;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 260px;
}

.toolbar-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #9ca3af;
  font-size: 12px;
}

.meta-sep {
  color: rgba(255, 255, 255, 0.2);
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: rgba(255, 255, 255, 0.06);
  color: #d1d5db;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tool-btn:hover {
  background: rgba(255, 255, 255, 0.15);
  color: #ffffff;
}

.tool-btn.is-active {
  background: rgba(31, 89, 71, 0.6);
  border-color: #1f5947;
  color: #6ee7b7;
}

/* 主播放舞台 */
.video-stage {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #090d16;
  position: relative;
  overflow: hidden;
  cursor: pointer;
}

.main-video {
  width: 100%;
  height: 100%;
  max-height: 100%;
  object-fit: contain;
  background: #000000;
}

/* 大播放按钮 */
.big-play-btn {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 68px;
  height: 68px;
  background: rgba(17, 24, 39, 0.75);
  backdrop-filter: blur(8px);
  border: 2px solid rgba(255, 255, 255, 0.25);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  cursor: pointer;
  transition: all 0.2s ease;
}

.big-play-btn:hover {
  transform: translate(-50%, -50%) scale(1.1);
  background: #1f5947;
  border-color: #1f5947;
}

/* 缓冲旋转器 */
.buffering-spinner {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  pointer-events: none;
}

.spinner-circle {
  width: 42px;
  height: 42px;
  border: 3px solid rgba(255, 255, 255, 0.2);
  border-top-color: #10b981;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.spinner-text {
  font-size: 12px;
  color: #d1d5db;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* 快进/快退气泡反馈 */
.seek-feedback-badge {
  position: absolute;
  top: 40%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(6px);
  color: #ffffff;
  padding: 8px 18px;
  border-radius: 20px;
  font-size: 15px;
  font-weight: 600;
  pointer-events: none;
}

/* 解码异常卡片 */
.video-error-overlay {
  position: absolute;
  inset: 0;
  background: rgba(10, 15, 28, 0.92);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 20;
}

.error-card {
  max-width: 460px;
  background: #182234;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 24px;
  text-align: center;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
}

.error-icon {
  font-size: 36px;
  margin-bottom: 12px;
}

.error-title {
  font-size: 16px;
  font-weight: 600;
  color: #f9fafb;
  margin: 0 0 10px 0;
}

.error-desc {
  font-size: 13px;
  line-height: 1.6;
  color: #9ca3af;
  margin: 0 0 20px 0;
}

.error-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex-wrap: wrap;
}

/* 底部交互控制栏 */
.video-controls-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  background: linear-gradient(to top, rgba(9, 13, 22, 0.95) 0%, rgba(9, 13, 22, 0.6) 70%, transparent 100%);
  padding: 16px 16px 12px 16px;
  transition: opacity 0.25s ease, transform 0.25s ease;
  z-index: 15;
  cursor: default;
}

.video-controls-bar.is-hidden {
  opacity: 0;
  transform: translateY(8px);
  pointer-events: none;
}

/* 进度条轨道 */
.progress-bar-container {
  position: relative;
  height: 16px;
  display: flex;
  align-items: center;
  cursor: pointer;
  margin-bottom: 8px;
}

.progress-track {
  position: relative;
  width: 100%;
  height: 4px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 2px;
  transition: height 0.15s ease;
}

.progress-bar-container:hover .progress-track {
  height: 6px;
}

.progress-buffered {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  background: rgba(255, 255, 255, 0.35);
  border-radius: 2px;
}

.progress-played {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  background: #10b981;
  border-radius: 2px;
}

.progress-thumb {
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%) scale(0);
  width: 12px;
  height: 12px;
  background: #ffffff;
  border-radius: 50%;
  box-shadow: 0 0 6px rgba(0, 0, 0, 0.4);
  transition: transform 0.15s ease;
}

.progress-bar-container:hover .progress-thumb {
  transform: translate(-50%, -50%) scale(1);
}

/* 进度条悬停气泡 */
.hover-time-bubble {
  position: absolute;
  bottom: 18px;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.85);
  color: #ffffff;
  padding: 3px 7px;
  border-radius: 4px;
  font-size: 11px;
  pointer-events: none;
  white-space: nowrap;
}

/* 控制按钮与时间码行 */
.controls-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.controls-left,
.controls-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ctrl-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: transparent;
  border: none;
  color: #e5e7eb;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.ctrl-btn:hover {
  background: rgba(255, 255, 255, 0.15);
  color: #ffffff;
}

.time-display {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #d1d5db;
  padding: 0 6px;
}

.time-divider {
  color: #6b7280;
}

/* 音量滑块 */
.volume-control-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.volume-slider {
  width: 65px;
  height: 4px;
  cursor: pointer;
  accent-color: #10b981;
}

/* 倍速菜单 */
.playback-rate-menu {
  position: relative;
}

.rate-btn {
  font-size: 12px;
  font-weight: 600;
  width: auto;
  padding: 0 8px;
}

.rate-dropdown {
  position: absolute;
  bottom: 38px;
  right: 0;
  background: rgba(17, 24, 39, 0.95);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  z-index: 30;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.5);
}

.rate-option {
  background: transparent;
  border: none;
  color: #d1d5db;
  padding: 4px 12px;
  font-size: 12px;
  border-radius: 4px;
  cursor: pointer;
  text-align: center;
  transition: all 0.1s ease;
}

.rate-option:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.rate-option.is-selected {
  background: #1f5947;
  color: #ffffff;
  font-weight: 600;
}

/* 按钮通用风格（在错误卡片中） */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(255, 255, 255, 0.08);
  color: #f3f4f6;
  padding: 6px 14px;
}

.btn:hover {
  background: rgba(255, 255, 255, 0.18);
}

.btn-primary {
  background: #1f5947;
  border-color: #1f5947;
  color: #ffffff;
}

.btn-primary:hover {
  background: #174a3a;
  border-color: #174a3a;
}

/* 动效 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translate(-50%, -50%) scale(0.85);
}

.pop-enter-active,
.pop-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.pop-enter-from,
.pop-leave-to {
  opacity: 0;
  transform: translate(-50%, -50%) scale(0.9);
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
</style>
