<template>
  <n-modal
    :show="show"
    preset="card"
    title="分享评测报告"
    style="width: 480px"
    @update:show="$emit('update:show', $event)"
  >
    <div class="share-box">
      <div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 12px">
        生成的只读分享链接在 7 天内有效，访问者无需登录即可查看报告内容与指标。
      </div>

      <div class="field">
        <label class="field-label">只读分享链接</label>
        <n-input-group>
          <n-input :value="shareUrl" readonly placeholder="正在生成分享链接..." />
          <n-button type="primary" @click="handleCopy">复制链接</n-button>
        </n-input-group>
      </div>
    </div>

    <template #footer>
      <div style="display: flex; justify-content: flex-end">
        <n-button @click="$emit('update:show', false)">关闭</n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { useMessage } from 'naive-ui'

const props = defineProps<{
  show: boolean
  shareUrl: string
}>()

defineEmits<{
  (e: 'update:show', val: boolean): void
}>()

const message = useMessage()

function handleCopy() {
  if (!props.shareUrl) return
  navigator.clipboard.writeText(props.shareUrl).then(() => {
    message.success('已复制分享链接')
  })
}
</script>

<style scoped>
.share-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}
</style>
