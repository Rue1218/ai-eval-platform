<template>
  <n-modal :show="show" preset="card" :title="filename || '图片预览'"
    style="width: min(1200px, 96vw)" @update:show="emit('update:show', $event)">
    <div class="image-preview-content">
      <WorkspaceImageViewer v-if="show" :key="src" :src="src" :alt="filename || '生成图片'" />
    </div>
  </n-modal>
</template>

<script setup lang="ts">
import { NModal } from 'naive-ui'
import WorkspaceImageViewer from '../workspace/WorkspaceImageViewer.vue'

/** 生成图片和附件共用弹窗，关闭后销毁查看器，下次打开重新适配窗口。 */
defineProps<{ show: boolean; src: string; filename?: string }>()
const emit = defineEmits<{ (event: 'update:show', show: boolean): void }>()
</script>

<style scoped>
.image-preview-content { height: 72vh; height: 72dvh; min-height: 180px; }
</style>
