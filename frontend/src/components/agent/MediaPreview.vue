<template>
  <div class="media-preview" :class="{ 'no-anim': noAnim }">
    <button type="button" class="media-frame" @click="open = true">
      <img :src="src" :alt="filename || '生成图片'" class="media-img" />
      <span class="media-hint">点击预览</span>
    </button>
    <div class="media-actions">
      <span class="media-name">{{ filename || '生成图片' }}</span>
      <a class="media-download" :href="src" :download="filename || 'image.png'" target="_blank" rel="noopener">
        下载
      </a>
    </div>
  </div>

  <Teleport to="body">
    <div v-if="open" class="media-lightbox" @click.self="open = false">
      <button type="button" class="media-close" aria-label="关闭预览" @click="open = false">×</button>
      <img :src="src" :alt="filename || '生成图片'" class="media-full" />
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  src: string
  filename?: string
  noAnim?: boolean
}>()

const open = ref(false)
</script>

<style scoped>
.media-preview {
  max-width: min(420px, 88%);
  margin: 6px 0 10px;
  animation: msg-in 0.26s cubic-bezier(0.2, 0.9, 0.3, 1);
}
.media-preview.no-anim {
  animation: none;
}
.media-frame {
  position: relative;
  display: block;
  width: 100%;
  padding: 0;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  overflow: hidden;
  background: var(--bg-elevated);
  cursor: zoom-in;
}
.media-img {
  display: block;
  width: 100%;
  max-height: 360px;
  object-fit: contain;
  background: #0f172a;
}
.media-hint {
  position: absolute;
  right: 8px;
  bottom: 8px;
  font-size: 11px;
  color: #e2e8f0;
  background: rgba(15, 23, 42, 0.72);
  padding: 2px 8px;
  border-radius: 999px;
}
.media-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  padding: 0 2px;
}
.media-name {
  font-size: 12px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.media-download {
  margin-left: auto;
  font-size: 12px;
  color: var(--accent-ai, #10b981);
  text-decoration: none;
}
.media-lightbox {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  background: rgba(2, 6, 23, 0.82);
  padding: 24px;
}
.media-full {
  max-width: min(96vw, 1100px);
  max-height: 90vh;
  object-fit: contain;
  border-radius: 8px;
}
.media-close {
  position: absolute;
  top: 16px;
  right: 20px;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 50%;
  background: rgba(15, 23, 42, 0.8);
  color: #fff;
  font-size: 22px;
  cursor: pointer;
}
@keyframes msg-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>
