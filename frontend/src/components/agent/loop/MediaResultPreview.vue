<template>
  <section class="media-preview" :class="`is-${preview.kind}`">
    <header>
      <strong>{{ preview.kind === 'image' ? '生成图片' : '图生视频' }}</strong>
      <span :class="{ pending: !ready }">{{ stateLabel }}</span>
    </header>
    <div v-if="preview.kind === 'image' && preview.imageUrls.length" class="image-grid">
      <a v-for="url in preview.imageUrls" :key="url" :href="url" target="_blank" rel="noopener noreferrer" class="image-link" title="在新窗口查看原图">
        <img :src="url" alt="生成的图片预览" loading="lazy" decoding="async" @error="markImageFailed(url)">
        <span v-if="failedImages.has(url)">图片临时地址已失效</span>
      </a>
    </div>
    <div v-else-if="preview.kind === 'video' && preview.videoUrl" class="video-wrap">
      <video controls playsinline preload="metadata" :src="preview.videoUrl">当前浏览器不支持视频播放。</video>
      <a :href="preview.videoUrl" target="_blank" rel="noopener noreferrer">在新窗口打开视频</a>
    </div>
    <p v-else class="media-pending">{{ pendingText }}</p>
    <footer v-if="preview.model || preview.upstreamTaskId">
      <span v-if="preview.model">模型：{{ preview.model }}</span>
      <span v-if="preview.upstreamTaskId">任务：{{ preview.upstreamTaskId }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { MediaPreview } from '../../../agent/loop/mediaPresentation'

const props = defineProps<{ preview: MediaPreview }>()
const failedImages = ref(new Set<string>())

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
</script>

<style scoped>
.media-preview{margin:10px 0;border:1px solid #dce8e4;border-radius:9px;background:linear-gradient(135deg,#f8fffc,#f4f9ff);padding:11px}.media-preview header,.media-preview footer{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:12px;color:#466158}.media-preview header span{color:#237f60}.media-preview header span.pending{color:#a16207}.image-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(136px,1fr));gap:8px;margin-top:10px}.image-link{position:relative;display:block;min-height:96px;overflow:hidden;border:1px solid #cfe1da;border-radius:7px;background:#edf5f1}.image-link img{display:block;width:100%;aspect-ratio:1/1;object-fit:cover;transition:transform .2s ease}.image-link:hover img{transform:scale(1.025)}.image-link span{position:absolute;inset:auto 6px 6px;padding:3px 5px;border-radius:4px;background:#7f1d1dcc;color:#fff;font-size:11px}.video-wrap{display:grid;gap:8px;margin-top:10px}.video-wrap video{display:block;width:100%;max-height:360px;border-radius:7px;background:#101828}.video-wrap a{width:max-content;color:#176fbe;font-size:12px}.media-pending{margin:10px 0 2px;color:#866827;font-size:12px}.media-preview footer{justify-content:flex-start;flex-wrap:wrap;margin-top:9px;color:#64748b}.media-preview footer span{overflow-wrap:anywhere}@media (prefers-reduced-motion:reduce){.image-link img{transition:none}}
</style>
