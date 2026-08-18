<template>
  <div class="users-admin-page">
    <div class="panel">
      <div class="panel-title">
        <div class="row">
          <span>平台成员账号列表</span>
          <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">({{ users.length }} 个成员)</span>
        </div>

        <div class="row">
          <button class="btn btn-primary btn-sm" @click="showUserModal = true">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            <span>开通新成员</span>
          </button>

          <button class="btn btn-secondary btn-sm" :disabled="loading" @click="loadUsers">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="23 4 23 10 17 10"></polyline>
              <polyline points="1 20 1 14 7 14"></polyline>
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
            </svg>
            <span>刷新</span>
          </button>
        </div>
      </div>

      <table class="ds-table">
        <thead>
          <tr>
            <th>用户名</th>
            <th style="width: 140px">角色权限</th>
            <th style="width: 120px">账号状态</th>
            <th style="width: 160px">注册时间</th>
            <th style="width: 180px; text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td style="font-weight: 600; font-size: 14px">
              <span class="row" style="gap: 8px">
                <span class="user-avatar-sm">{{ u.username.charAt(0).toUpperCase() }}</span>
                <span>{{ u.username }}</span>
              </span>
            </td>
            <td>
              <span class="kind-tag" style="background: var(--t-users); color: var(--c-users)">平台成员</span>
            </td>
            <td>
              <span v-if="!u.disabled" class="badge badge-succeeded">正常</span>
              <span v-else class="badge badge-failed">已停用</span>
            </td>
            <td class="mono" style="font-size: 12px; color: var(--text-tertiary)">
              {{ formatDate(u.created_at) }}
            </td>
            <td style="text-align: right">
              <div class="row" style="justify-content: flex-end; gap: 4px">
                <button class="link-btn" @click="openResetPassword(u)">重置密码</button>
                <button
                  class="link-btn"
                  :class="u.disabled ? '' : 'danger'"
                  @click="handleToggleStatus(u)"
                >
                  {{ u.disabled ? '启用' : '停用' }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 弹窗 -->
    <UserModal
      v-model:show="showUserModal"
      @success="loadUsers"
    />

    <ResetPasswordModal
      v-model:show="showResetModal"
      :user="selectedUser"
      @success="loadUsers"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api/http'
import type { AuthUser } from '../api/types'
import UserModal from '../components/modals/UserModal.vue'
import ResetPasswordModal from '../components/modals/ResetPasswordModal.vue'

const message = useMessage()
const dialog = useDialog()

const users = ref<AuthUser[]>([])
const loading = ref(false)

const showUserModal = ref(false)
const showResetModal = ref(false)
const selectedUser = ref<AuthUser | null>(null)

function formatDate(d?: string) {
  if (!d) return ''
  return new Date(d).toLocaleDateString('zh-CN')
}

async function loadUsers() {
  loading.value = true
  try {
    users.value = await api.users.list()
  } catch (err: any) {
    message.error(err.message || '加载用户列表失败')
  } finally {
    loading.value = false
  }
}

function openResetPassword(user: AuthUser) {
  selectedUser.value = user
  showResetModal.value = true
}

function handleToggleStatus(user: AuthUser) {
  const targetDisabled = !user.disabled
  const actionText = targetDisabled ? '停用' : '启用'

  dialog.warning({
    title: `${actionText}用户「${user.username}」？`,
    content: targetDisabled
      ? '停用后该用户将无法登录平台，正在运行的任务仍将保留。'
      : '启用后该用户可恢复正常登录。',
    positiveText: `确认${actionText}`,
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.users.toggleStatus(user.id, targetDisabled)
        user.disabled = targetDisabled
        message.success(`已${actionText}该账号`)
      } catch (err: any) {
        message.error(err.message || `${actionText}失败`)
      }
    },
  })
}

onMounted(loadUsers)
</script>

<style scoped>
.users-admin-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.user-avatar-sm {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--accent-ai);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  display: grid;
  place-items: center;
}
</style>
