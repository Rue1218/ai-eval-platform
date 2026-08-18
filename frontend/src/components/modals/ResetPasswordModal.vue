<template>
  <n-modal
    :show="show"
    preset="card"
    :title="`重置用户「${user?.username}」的密码`"
    style="width: 440px"
    @update:show="$emit('update:show', $event)"
  >
    <div class="reset-form">
      <div class="field">
        <label class="field-label">新密码 <span class="req">*</span></label>
        <n-input
          v-model:value="password"
          type="password"
          show-password-on="click"
          placeholder="至少 8 位，包含字母与数字"
        />
      </div>
    </div>

    <template #footer>
      <div style="display: flex; gap: 8px; justify-content: flex-end">
        <n-button @click="$emit('update:show', false)">取消</n-button>
        <n-button type="primary" :loading="saving" @click="handleReset">重置密码</n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../../api/http'
import type { AuthUser } from '../../api/types'

const props = defineProps<{
  show: boolean
  user?: AuthUser | null
}>()

const emit = defineEmits<{
  (e: 'update:show', val: boolean): void
  (e: 'success'): void
}>()

const message = useMessage()
const saving = ref(false)
const password = ref('')

watch(
  () => props.show,
  (val) => {
    if (val) password.value = ''
  },
)

async function handleReset() {
  if (!props.user?.id) return
  if (!password.value || password.value.length < 8) {
    message.warning('新密码长度不能少于 8 位')
    return
  }

  saving.value = true
  try {
    await api.users.resetPassword(props.user.id, password.value)
    message.success('密码已重置')
    emit('update:show', false)
    emit('success')
  } catch (err: any) {
    message.error(err.message || '密码重置失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.reset-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
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
.field-label .req {
  color: var(--accent-error);
}
</style>
