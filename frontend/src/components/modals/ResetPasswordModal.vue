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
      <div v-if="!isSelf" class="field">
        <label class="field-label">你的登录密码 <span class="req">*</span></label>
        <n-input
          v-model:value="currentPassword"
          type="password"
          show-password-on="click"
          placeholder="重置他人密码需确认你的身份"
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
import { computed, ref, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../../api/http'
import type { AuthUser } from '../../api/types'
import { useAuthStore } from '../../stores/auth'

const props = defineProps<{
  show: boolean
  user?: AuthUser | null
}>()

const emit = defineEmits<{
  (e: 'update:show', val: boolean): void
  (e: 'success'): void
}>()

const message = useMessage()
const auth = useAuthStore()
const saving = ref(false)
const password = ref('')
const currentPassword = ref('')

// 重置本人密码无需二次确认；重置他人密码需先验证操作者身份
const isSelf = computed(() => !!props.user && props.user.id === auth.user?.id)

watch(
  () => props.show,
  (val) => {
    if (val) {
      password.value = ''
      currentPassword.value = ''
    }
  },
)

async function handleReset() {
  if (!props.user?.id) return
  if (!password.value || password.value.length < 8) {
    message.warning('新密码长度不能少于 8 位')
    return
  }
  if (!isSelf.value && !currentPassword.value) {
    message.warning('重置他人密码需输入你本人的登录密码')
    return
  }

  saving.value = true
  try {
    await api.users.resetPassword(
      props.user.id,
      password.value,
      isSelf.value ? undefined : currentPassword.value,
    )
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
