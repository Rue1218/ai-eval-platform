<template>
  <div class="attachment-preview-card" :class="{ compact }">
    <button
      class="attachment-visual"
      type="button"
      :disabled="!source"
      :title="previewLabel"
      @click="openPreview"
    >
      <img v-if="isImage && source" :src="source" :alt="filename" class="attachment-image" loading="lazy" decoding="async" />
      <span v-else class="attachment-file-visual">
        <span class="attachment-file-mark">{{ extension }}</span>
        <span class="attachment-file-action">{{ previewLabel }}</span>
      </span>
      <span v-if="uploading" class="attachment-uploading">上传中 {{ uploadProgress }}%</span>
      <span v-else-if="error" class="attachment-uploading error">上传失败</span>
    </button>

    <div class="attachment-meta">
      <span class="attachment-name" :title="filename">{{ filename }}</span>
      <span class="attachment-size">{{ formattedSize }}</span>
    </div>

    <button
      v-if="removable"
      class="attachment-remove"
      type="button"
      title="移除附件"
      aria-label="移除附件"
      @click="$emit('remove')"
    >
      ×
    </button>
  </div>

  <Teleport to="body">
    <div v-if="open" class="attachment-lightbox" @click.self="open = false">
      <button class="attachment-close" type="button" aria-label="关闭预览" @click="open = false">×</button>
      <div class="attachment-lightbox-panel">
        <div class="attachment-lightbox-head">
          <span class="attachment-lightbox-title">{{ filename }}</span>
          <a
            v-if="source"
            class="attachment-lightbox-download"
            :href="source"
            :download="filename"
            target="_blank"
            rel="noopener"
          >
            打开 / 下载
          </a>
        </div>

        <img v-if="isImage && source" :src="source" :alt="filename" class="attachment-lightbox-image" decoding="async" />
        <iframe v-else-if="previewKind === 'pdf' && source" :src="source" :title="filename" class="attachment-lightbox-document" />
        <pre v-else-if="previewKind === 'text'" class="attachment-lightbox-text">{{ textContent }}</pre>
        <div v-else class="attachment-unsupported">
          <span class="attachment-file-mark large">{{ extension }}</span>
          <strong>该格式暂不支持内嵌预览</strong>
          <span>文件已上传，点击右上角“打开 / 下载”查看。</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

/** 附件展示所需的最小字段；既兼容本地暂存文件，也兼容历史消息的文件引用。 */
export interface AttachmentPreviewItem {
  id?: string
  file_id?: string
  name?: string
  filename?: string
  size?: number | string
  content_type?: string | null
  contentType?: string
  content_url?: string
  preview_url?: string
  previewUrl?: string
  file?: File
  uploading?: boolean
  uploadProgress?: number
  error?: boolean
}

const props = withDefaults(
  defineProps<{
    attachment: AttachmentPreviewItem
    compact?: boolean
    removable?: boolean
  }>(),
  {
    compact: false,
    removable: false,
  },
)

defineEmits<{
  (event: 'remove'): void
}>()

const open = ref(false)
const textContent = ref('')

const filename = computed(() => props.attachment.filename || props.attachment.name || props.attachment.file_id || props.attachment.id || '附件')
const extension = computed(() => {
  const suffix = filename.value.split('.').pop() || 'FILE'
  return suffix.slice(0, 5).toUpperCase()
})
const source = computed(() => {
  if (props.attachment.preview_url) return props.attachment.preview_url
  if (props.attachment.previewUrl) return props.attachment.previewUrl
  if (props.attachment.content_url) return props.attachment.content_url
  const fileId = props.attachment.file_id || props.attachment.id
  return fileId ? `/api/files/${fileId}/content` : ''
})
const contentType = computed(() => props.attachment.content_type || props.attachment.contentType || props.attachment.file?.type || '')
const isImage = computed(() => contentType.value.startsWith('image/') || ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'].includes(extension.value.toLowerCase()))
const previewKind = computed<'pdf' | 'text' | 'file'>(() => {
  const suffix = extension.value.toLowerCase()
  if (suffix === 'pdf') return 'pdf'
  if (['md', 'txt', 'csv', 'json', 'jsonl', 'yaml', 'yml', 'html'].includes(suffix)) return 'text'
  return 'file'
})
const previewLabel = computed(() => {
  if (isImage.value || previewKind.value !== 'file') return '点击预览'
  return source.value ? '打开文件' : '已上传'
})
const formattedSize = computed(() => {
  const size = props.attachment.size
  if (typeof size === 'string') return size
  if (typeof size !== 'number') return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
})
const uploading = computed(() => Boolean(props.attachment.uploading))
const uploadProgress = computed(() => Math.min(100, Math.max(0, Number(props.attachment.uploadProgress) || 0)))
const error = computed(() => Boolean(props.attachment.error))

/** 打开图片、PDF、文本预览；Office 等格式保留清晰的不可嵌入提示。 */
async function openPreview() {
  if (!source.value) return
  if (previewKind.value === 'text') {
    try {
      if (props.attachment.file) {
        textContent.value = await props.attachment.file.text()
      } else {
        const response = await fetch(source.value)
        if (!response.ok) throw new Error('文件读取失败')
        textContent.value = await response.text()
      }
    } catch {
      textContent.value = '文件预览失败，请点击右上角“打开 / 下载”查看。'
    }
  }
  open.value = true
}
</script>

<style scoped>
.attachment-preview-card {
  position: relative;
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  gap: 9px;
  width: min(250px, 100%);
  padding: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 11px;
  background: var(--bg-elevated);
  color: var(--text-primary);
}

.attachment-preview-card.compact {
  width: min(210px, 100%);
  grid-template-columns: 54px minmax(0, 1fr);
}

.attachment-preview-card.compact .attachment-visual {
  width: 54px;
  height: 48px;
}

.attachment-preview-card.compact .attachment-file-action {
  max-width: 52px;
}

.attachment-preview-card.compact .attachment-name {
  font-size: 11px;
}

.attachment-visual {
  position: relative;
  width: 76px;
  height: 66px;
  padding: 0;
  overflow: hidden;
  border: 0;
  border-radius: 7px;
  background: var(--bg-main);
  color: var(--text-secondary);
  cursor: pointer;
}

.attachment-visual:disabled {
  cursor: default;
}

.attachment-image {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.attachment-file-visual,
.attachment-unsupported {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: 100%;
  height: 100%;
}

.attachment-file-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 34px;
  height: 24px;
  padding: 0 5px;
  border-radius: 5px;
  background: var(--t-agent);
  color: var(--c-agent);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
}

.attachment-file-mark.large {
  min-width: 64px;
  height: 42px;
  font-size: 13px;
}

.attachment-file-action {
  max-width: 70px;
  overflow: hidden;
  color: var(--text-tertiary);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-uploading {
  position: absolute;
  inset: auto 4px 4px;
  border-radius: 999px;
  background: rgba(17, 24, 39, 0.72);
  color: #fff;
  font-size: 10px;
  line-height: 18px;
}

.attachment-uploading.error {
  background: color-mix(in srgb, var(--accent-error) 82%, transparent);
}

.attachment-meta {
  min-width: 0;
  align-self: center;
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding-right: 5px;
}

.attachment-name {
  overflow: hidden;
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-size {
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: 10px;
}

.attachment-remove {
  position: absolute;
  top: -7px;
  right: -7px;
  width: 20px;
  height: 20px;
  border: 1px solid var(--border-subtle);
  border-radius: 50%;
  background: var(--bg-main);
  color: var(--text-tertiary);
  cursor: pointer;
  font-size: 14px;
  line-height: 17px;
}

.attachment-remove:hover {
  color: var(--accent-error);
}

.attachment-lightbox {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(2, 6, 23, 0.78);
}

.attachment-lightbox-panel {
  display: flex;
  flex-direction: column;
  width: min(980px, 94vw);
  height: min(760px, 88vh);
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 14px;
  background: var(--bg-main);
  box-shadow: 0 18px 70px rgba(0, 0, 0, 0.35);
}

.attachment-lightbox-head {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 48px;
  padding: 0 16px;
  border-bottom: 1px solid var(--border-subtle);
}

.attachment-lightbox-title {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-lightbox-download {
  margin-left: auto;
  color: var(--accent-ai);
  font-size: 12px;
  text-decoration: none;
  white-space: nowrap;
}

.attachment-lightbox-image,
.attachment-lightbox-document {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 0;
  border: 0;
  object-fit: contain;
  background: #0f172a;
}

.attachment-lightbox-text {
  flex: 1;
  min-height: 0;
  margin: 0;
  overflow: auto;
  padding: 20px;
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.attachment-unsupported {
  flex: 1;
  gap: 12px;
  color: var(--text-secondary);
  font-size: 13px;
}

.attachment-unsupported span:last-child {
  color: var(--text-tertiary);
  font-size: 12px;
}

.attachment-close {
  position: fixed;
  top: 15px;
  right: 20px;
  z-index: 1;
  width: 34px;
  height: 34px;
  border: 0;
  border-radius: 50%;
  background: rgba(15, 23, 42, 0.8);
  color: #fff;
  cursor: pointer;
  font-size: 22px;
  line-height: 30px;
}

@media (max-width: 600px) {
  .attachment-lightbox {
    padding: 10px;
  }

  .attachment-lightbox-panel {
    width: 100%;
    height: min(760px, 84vh);
  }
}
</style>
