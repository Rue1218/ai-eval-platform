<template>
  <div class="login-wrap">
    <n-card class="login-card" title="AI 测试与评估平台">
      <n-form @keyup.enter="onLogin">
        <n-form-item label="用户名">
          <n-input v-model:value="username" placeholder="请输入用户名" />
        </n-form-item>
        <n-form-item label="密码">
          <n-input v-model:value="password" type="password" show-password-on="click" placeholder="请输入密码" />
        </n-form-item>
      </n-form>
      <n-button type="primary" block :loading="loading" @click="onLogin">登录</n-button>
    </n-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const message = useMessage()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const loading = ref(false)

async function onLogin() {
  if (!username.value || !password.value) {
    message.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    router.push('/agent')
  } catch (e) {
    message.error(e.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f6f8;
}
.login-card {
  width: 360px;
}
</style>
