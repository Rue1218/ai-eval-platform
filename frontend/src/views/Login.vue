<template>
  <div class="login-wrapper">
    <div class="login-card scanline">
      <div class="login-brand">
        <div class="login-mark">A</div>
        <div class="eyebrow" style="margin-bottom: 8px">SECURE ACCESS · V1.6.3</div>
        <div class="login-title">AI 测试与评估平台</div>
        <!-- L4 副标题文案对齐原型 login.html:37 -->
        <div class="login-desc">
          对话完成：用例（可选）→ Benchmark 和 / 或 RAG →（可选）压测 → 报告
        </div>
        <div class="row" style="justify-content: center; margin-top: 14px; gap: 8px">
          <span class="ai-badge"><i class="ai-dot"></i>AGENT 后端</span>
          <!-- L3 后端状态行：优先显示 Agent 模型名，获取失败时仅显示连接状态 -->
          <span class="small tertiary mono" style="font-size: 11px">{{ agentStatusText }}</span>
        </div>
      </div>

      <div class="login-form">
        <div class="field">
          <label class="field-label">用户名</label>
          <n-input
            v-model:value="username"
            size="large"
            placeholder="admin / alice / boss"
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
            placeholder="不少于 8 位，含字母和数字"
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

      <!-- L5 演示账号提示对齐原型 login.html:55-58；
           注意：live 环境仅初始管理员 admin / admin123 有效（由 BOOTSTRAP_ADMIN_PASSWORD 注入），
           alice / bob / boss 为原型演示账号，仅作展示 -->
      <div class="login-foot mono">
        <span>原型演示账号（单一角色，全员同权）：admin / admin123（首登强制改密）</span>
        <span>alice / Alice123 · bob / Bob12345 · boss / Boss1234</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '../stores/auth'
import { api } from '../api/http'

const router = useRouter()
const message = useMessage()
const auth = useAuthStore()

const username = ref('admin')
const password = ref('admin123')
const loading = ref(false)
const errorMsg = ref('')

// L3 后端状态行：默认仅显示连接状态，成功获取设置后前置 Agent 模型名
const agentStatusText = ref('连接正常 · 调度器运行中')

/** 登录页健康探测：未登录状态下调用免密公网健康接口，避免触发受保护接口 401 日志 */
async function loadAgentStatus() {
  try {
    const res = await fetch('/api/health')
    if (res.ok) {
      agentStatusText.value = '连接正常 · 调度器运行中'
    }
  } catch {
    // 忽略失败：保持默认兜底状态文案
  }
}

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

onMounted(loadAgentStatus)
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
  /* L2 玻璃拟态（对齐原型 login.html 12-19）：半透明白底 + 20px 背景模糊 */
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: 20px;
  padding: 36px 32px 28px;
  box-shadow: 0 24px 64px rgba(17, 24, 39, 0.12);
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
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: center;
  font-size: 11px;
  color: var(--text-tertiary);
  margin-top: 24px;
  padding-top: 14px;
  border-top: 1px dashed var(--border-subtle);
  line-height: 1.9;
}

@media (max-width: 700px) {
  .login-wrapper {
    height: 100dvh;
    padding: 14px;
  }
  .login-card {
    padding: 28px 20px 22px;
    border-radius: 16px;
  }
}
</style>
