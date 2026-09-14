<template>
  <section class="media-preview" :class="`is-${preview.kind}`">
    <header>
      <strong>{{ preview.kind === 'image' ? '生成图片' : '图生视频' }}</strong>
      <span :class="{ pending: !ready }">{{ stateLabel }}</span>
    </header>
    <div v-if="preview.kind === 'image' && preview.imageUrls.length" class="image-grid">
      <button v-for="url in preview.imageUrls" :key="url" type="button" class="image-link" :disabled="failedImages.has(url)" title="点击弹窗预览" @click="openImage(url)">
        <img :src="url" alt="生成的图片预览" loading="lazy" decoding="async" @error="markImageFailed(url)">
        <span v-if="failedImages.has(url)">图片临时地址已失效</span>
      </button>
    </div>
    <div v-else-if="preview.kind === 'video' && preview.videoUrl" class="video-wrap">
      <video ref="inlineVideo" controls playsinline preload="metadata" :src="preview.videoUrl">当前浏览器不支持视频播放。</video>
      <button type="button" class="video-popup" @click="openVideo">弹窗预览</button>
    </div>
    <p v-else class="media-pending">{{ pendingText }}</p>
    <footer v-if="preview.model || preview.upstreamTaskId">
      <span v-if="preview.model">模型：{{ preview.model }}</span>
      <span v-if="preview.upstreamTaskId">任务：{{ preview.upstreamTaskId }}</span>
    </footer>
  </section>

  <Teleport to="body">
    <div v-if="lightbox" class="media-lightbox" @click.self="closeLightbox">
      <button type="button" class="media-lightbox-close" aria-label="关闭预览" @click="closeLightbox">×</button>
      <div class="media-lightbox-body" @click.self="closeLightbox">
        <WorkspaceImageViewer v-if="lightbox.kind === 'image'" :src="lightbox.url" alt="生成的图片预览" />
        <video v-else :src="preview.videoUrl || ''" class="media-lightbox-video" controls autoplay playsinline>当前浏览器不支持视频播放。</video>
      </div>
      <div class="media-lightbox-bar">
        <span class="media-lightbox-title">
          {{ lightbox.kind === 'image' ? '生成图片' : '生成视频' }}<template v-if="preview.model"> · {{ preview.model }}</template>
        </span>
        <a class="media-lightbox-download" :href="lightbox.kind === 'image' ? lightbox.url : (preview.videoUrl || '')" target="_blank" rel="noopener noreferrer" download>下载原文件</a>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { MediaPreview } from '../../../agent/loop/mediaPresentation'
import WorkspaceImageViewer from '../../workspace/WorkspaceImageViewer.vue'

/** 弹窗预览状态；图片带地址，视频复用卡片上的成品地址。 */
type LightboxState = { kind: 'image'; url: string } | { kind: 'video' }

const props = defineProps<{ preview: MediaPreview }>()
const failedImages = ref(new Set<string>())
const lightbox = ref<LightboxState | null>(null)
const inlineVideo = ref<HTMLVideoElement | null>(null)

/** 视频只有拿到成品地址才视为可播放，避免把提交成功误显示为生成完成。 */
const ready = computed(() => props.preview.kind === 'image'
  ? props.preview.imageUrls.some(url => !failedImages.value.has(url))
  : Boolean(props.preview.videoUrl))
const stateLabel = computed(() => ready.value ? '可预览'
  : props.preview.kind === 'image' && failedImages.value.size ? '地址失效' : props.preview.status)
const pendingText = computed(() => props.preview.kind === 'video'
  ? '视频任务已提交，等待工具查询到可播放结果。'
  : failedImages.value.size ? '图片临时地址已失效，请重新生成。' : '图片生成完成，但没有可用的 HTTPS 预览地址。')

function markImageFailed(url: string): void {
  /** 替换 Set 引用，确保临时地址失效后的状态触发 Vue 更新。 */
  failedImages.value = new Set([...failedImages.value, url])
}

/** 点击缩略图在页内弹窗预览，不再依赖新标签页或浏览器下载行为。 */
function openImage(url: string): void {
  lightbox.value = { kind: 'image', url }
}

/** 打开弹窗前暂停行内播放，避免弹窗与卡片同时出声。 */
function openVideo(): void {
  inlineVideo.value?.pause()
  lightbox.value = { kind: 'video' }
}

function closeLightbox(): void {
  lightbox.value = null
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') closeLightbox()
}

watch(lightbox, value => {
  if (value) window.addEventListener('keydown', onKeydown)
  else window.removeEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.media-preview{margin:10px 0;border:1px solid #dce8e4;border-radius:9px;background:linear-gradient(135deg,#f8fffc,#f4f9ff);padding:11px}.media-preview header,.media-preview footer{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:12px;color:#466158}.media-preview header span{color:#237f60}.media-preview header span.pending{color:#a16207}.image-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(136px,1fr));gap:8px;margin-top:10px}.image-link{position:relative;display:block;width:100%;min-height:96px;padding:0;overflow:hidden;border:1px solid #cfe1da;border-radius:7px;background:#edf5f1;cursor:zoom-in}.image-link img{display:block;width:100%;aspect-ratio:1/1;object-fit:cover;transition:transform .2s ease}.image-link:hover img{transform:scale(1.025)}.image-link:disabled{cursor:default}.image-link:disabled:hover img{transform:none}.image-link span{position:absolute;inset:auto 6px 6px;padding:3px 5px;border-radius:4px;background:#7f1d1dcc;color:#fff;font-size:11px}.video-wrap{display:grid;gap:8px;margin-top:10px}.video-wrap video{display:block;width:100%;max-height:360px;border-radius:7px;background:#101828}.video-popup{width:max-content;padding:0;border:0;background:transparent;color:#176fbe;font-size:12px;cursor:pointer}.video-popup:hover{text-decoration:underline}.media-pending{margin:10px 0 2px;color:#866827;font-size:12px}.media-preview footer{justify-content:flex-start;flex-wrap:wrap;margin-top:9px;color:#64748b}.media-preview footer span{overflow-wrap:anywhere}
.media-lightbox{position:fixed;inset:0;z-index:90;display:grid;grid-template-rows:minmax(0,1fr) auto;place-items:center;gap:14px;padding:28px 28px 20px;background:rgba(2,6,23,.84)}.media-lightbox-body{display:grid;place-items:center;min-width:0;min-height:0;width:100%;height:100%}.media-lightbox-body :deep(.workspace-image-viewer){width:min(94vw,1280px);height:100%;border:0}.media-lightbox-video{max-width:min(94vw,1280px);max-height:100%;border-radius:10px;background:#0f172a;box-shadow:0 18px 60px rgba(0,0,0,.42)}.media-lightbox-bar{display:flex;align-items:center;gap:14px;max-width:min(94vw,1280px);color:#cbd5e1;font-size:12px}.media-lightbox-title{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.media-lightbox-download{margin-left:auto;color:#7dd3a8;text-decoration:none;white-space:nowrap}.media-lightbox-download:hover{text-decoration:underline}.media-lightbox-close{position:fixed;top:16px;right:20px;width:36px;height:36px;border:0;border-radius:50%;background:rgba(15,23,42,.8);color:#fff;cursor:pointer;font-size:22px;line-height:32px}@media (prefers-reduced-motion:reduce){.image-link img{transition:none}}
</style>
