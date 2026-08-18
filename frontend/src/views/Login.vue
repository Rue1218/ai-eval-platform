<template>
  <div class="login-wrapper">
    <div class="login-card">
      <div class="login-brand">
        <div class="login-mark">A</div>
        <div class="login-title">AI 测试与评估平台</div>
        <div class="login-desc">
          对话驱动大模型质量评测：用例生成 → Benchmark / RAG → 先评后压 → 对比报告
        </div>
      </div>

      <div class="login-form">
        <div class="field">
          <label class="field-label">用户名</label>
          <n-input
            v-model:value="username"
            size="large"
            placeholder="输入用户名 (例如 admin)"
            @keydown.enter="submitLogin"
          />
        </div>

        <div class="field">
          <label class="field-label">密码</label>
          <n-input
            v-model:value="password"
            type="password"
            show-password-on="click"
            size="large"
            placeholder="输入密码"
            @keydown.enter="submitLogin"
          />
        </div>

        <div v-if="errorMsg" class="login-error">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <span>{{ errorMsg }}</span>
        </div>

        <button class="btn btn-sign login-btn" :disabled="loading" @click="submitLogin">
          {{ loading ? '登录中...' : '登 录' }}
        </button>
      </div>

      <div class="login-foot mono">
        <span>初始管理员：admin / admin123</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const message = useMessage()
const auth = useAuthStore()

const username = ref('admin')
const password = ref('admin123')
const loading = ref(false)
const errorMsg = ref('')

async function submitLogin() {
  if (!username.value.trim() || !password.value) {
    errorMsg.value = '请输入用户名和密码'
    return
  }

  errorMsg.value = ''
  loading.value = true
  try {
    const user = await auth.login(username.value, password.value)
    message.success(`欢迎回来，${user.username}`)
    router.push('/agent')
  } catch (err: any) {
    errorMsg.value = '用户名或密码错误，请检查'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrapper {
  display: grid;
  place-items: center;
  height: 100vh;
  padding: 20px;
}

.login-card {
  width: 420px;
  max-width: 100%;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  border-radius: 20px;
  padding: 36px 32px 28px;
  box-shadow: 0 20px 50px rgba(17, 24, 39, 0.1), 0 1px 3px rgba(17, 24, 39, 0.04);
  animation: card-in 0.3s cubic-bezier(0.2, 0.9, 0.3, 1);
}
@keyframes card-in {
  from {
    opacity: 0;
    transform: translateY(16px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.login-brand {
  text-align: center;
  margin-bottom: 28px;
}
.login-mark {
  width: 44px;
  height: 44px;
  margin: 0 auto 14px;
  border-radius: 12px;
  background: var(--text-primary);
  color: var(--bg-main);
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 24px;
  display: grid;
  place-items: center;
}
.login-title {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
}
.login-desc {
  font-size: 12.5px;
  color: var(--text-secondary);
  margin-top: 6px;
  line-height: 1.5;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
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

.login-error {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--accent-error);
  font-size: 12.5px;
  padding: 6px 10px;
  background: #fef2f2;
  border-radius: 8px;
}

.login-btn {
  width: 100%;
  height: 42px;
  font-size: 15px;
  font-weight: 600;
  margin-top: 6px;
  border-radius: 12px;
}

.login-foot {
  text-align: center;
  font-size: 11px;
  color: var(--text-tertiary);
  margin-top: 24px;
}
</style>
