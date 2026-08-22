<template>
  <div class="login-wrapper">
    <div class="login-card scanline">
      <div class="login-brand">
        <div class="login-mark">A</div>
        <div class="login-eyebrow">SECURE ACCESS · V1.6.3</div>
        <h1 class="login-title">AI 测试与评估平台</h1>
        <div class="login-desc">
          对话完成：用例（可选）→ Benchmark 和 / 或 RAG →（可选）压测 → 报告
        </div>
        <div class="login-status-row">
          <span class="status-badge">
            <span class="status-dot"></span>
            AGENT 后端
          </span>
          <span class="status-text">{{ agentStatusText }}</span>
        </div>
      </div>

      <div class="login-form">
        <div class="form-field">
          <label class="field-label">用户名</label>
          <n-input
            v-model:value="username"
            size="large"
            placeholder="admin / alice / boss"
            :theme-overrides="inputThemeOverrides"
            @keydown.enter="submitLogin"
          />
        </div>

        <div class="form-field">
          <label class="field-label">密码</label>
          <n-input
            v-model:value="password"
            type="password"
            show-password-on="click"
            size="large"
            placeholder="不少于 8 位，含字母和数字"
            :theme-overrides="inputThemeOverrides"
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

        <button class="login-btn" :disabled="loading" @click="submitLogin">
          {{ loading ? '登录中...' : '登 录' }}
        </button>
      </div>

      <div class="login-foot">
        <div>原型演示账号（单一角色，全员同权）：admin / admin123（首登强制改密）</div>
        <div>alice / Alice123 · bob / Bob12345 · boss / Boss1234</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage, type InputProps } from 'naive-ui'
import { useAuthStore } from '../stores/auth'

type InputThemeOverrides = NonNullable<InputProps['themeOverrides']>

const router = useRouter()
const message = useMessage()
const auth = useAuthStore()

const username = ref('admin')
const password = ref('admin123')
const loading = ref(false)
const errorMsg = ref('')

// Naive UI Input 定制样式
const inputThemeOverrides: InputThemeOverrides = {
  heightLarge: '46px',
  borderRadius: '12px',
  border: '1px solid #e2e8f0',
  borderHover: '1px solid #94a3b8',
  borderFocus: '1px solid #6366f1',
  boxShadowFocus: '0 0 0 3px rgba(99, 102, 241, 0.12)',
  color: '#ffffff',
  textColor: '#0f172a',
  placeholderColor: '#94a3b8',
  fontSizeLarge: '14px',
  iconColor: '#94a3b8',
  iconColorHover: '#475569',
}

// 状态行：默认显示连接状态
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
  position: relative;
  display: grid;
  place-items: center;
  min-height: 100vh;
  padding: 24px;
  background:
    radial-gradient(900px 520px at 12% -8%, rgba(16, 185, 129, 0.16), transparent 60%),
    radial-gradient(1100px 640px at 88% 108%, rgba(94, 234, 212, 0.18), transparent 62%),
    linear-gradient(158deg, #e7f4ec 0%, #f4f8f8 34%, #e9f5f0 58%, #eef7ec 82%, #e4f2ef 100%);
  background-attachment: fixed;
  animation: mint-breathe 9s ease-in-out infinite;
  overflow: hidden;
}

@keyframes mint-breathe {
  0%, 100% { filter: saturate(1); }
  50% { filter: saturate(1.15); }
}

/* 双层工程网格纹理：120px 主格 + 24px 细格 */
.login-wrapper::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(16, 185, 129, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(16, 185, 129, 0.08) 1px, transparent 1px),
    linear-gradient(rgba(16, 185, 129, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(16, 185, 129, 0.035) 1px, transparent 1px);
  background-size: 120px 120px, 120px 120px, 24px 24px, 24px 24px;
}

.login-card {
  position: relative;
  z-index: 1;
  width: 440px;
  max-width: calc(100vw - 32px);
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border: 1px solid rgba(255, 255, 255, 0.95);
  border-radius: 28px;
  padding: 40px 36px 32px;
  box-shadow:
    0 24px 60px -12px rgba(15, 23, 42, 0.1),
    0 2px 6px rgba(0, 0, 0, 0.03);
  animation: card-in 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes card-in {
  from {
    opacity: 0;
    transform: translateY(20px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

/* 扫描线光效：流光扫过卡片 */
.scanline {
  position: relative;
  overflow: hidden;
}

.scanline::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 160px;
  pointer-events: none;
  background: linear-gradient(100deg, transparent, rgba(94, 234, 212, 0.2) 45%, rgba(99, 102, 241, 0.16) 58%, transparent);
  transform: translateX(-200px);
  animation: scan-x 5.2s cubic-bezier(0.4, 0, 0.2, 1) infinite;
}

@keyframes scan-x {
  0% { transform: translateX(-200px); }
  60%, 100% { transform: translateX(800px); }
}

.login-brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  margin-bottom: 24px;
}

.login-mark {
  width: 48px;
  height: 48px;
  margin: 0 auto 16px;
  border-radius: 14px;
  background: #0f172a;
  color: #ffffff;
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 26px;
  display: grid;
  place-items: center;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.15);
  user-select: none;
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.login-mark:hover {
  transform: scale(1.06) rotate(-2deg);
}

.login-eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.16em;
  color: #94a3b8;
  text-transform: uppercase;
  margin-bottom: 8px;
}

.login-title {
  font-family: var(--font-body);
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #0f172a;
  margin: 0;
  line-height: 1.3;
}

.login-desc {
  font-size: 12px;
  color: #64748b;
  margin-top: 8px;
  line-height: 1.6;
  max-width: 340px;
}

.login-status-row {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 16px;
  gap: 10px;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px 3px 8px;
  background: rgba(238, 242, 255, 0.95);
  border: 1px solid rgba(199, 210, 254, 0.8);
  border-radius: 999px;
  color: #4f46e5;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #6366f1;
  box-shadow: 0 0 8px rgba(99, 102, 241, 0.8);
  animation: dot-pulse 2s infinite ease-in-out;
}

@keyframes dot-pulse {
  0%, 100% {
    transform: scale(1);
    opacity: 0.85;
    box-shadow: 0 0 4px rgba(99, 102, 241, 0.6);
  }
  50% {
    transform: scale(1.4);
    opacity: 1;
    box-shadow: 0 0 10px rgba(99, 102, 241, 0.9);
  }
}

.status-text {
  font-family: var(--font-mono);
  font-size: 11px;
  color: #64748b;
  letter-spacing: 0.01em;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  font-size: 13px;
  font-weight: 500;
  color: #334155;
}

.login-error {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #ef4444;
  font-size: 12.5px;
  padding: 8px 12px;
  background: #fef2f2;
  border: 1px solid #fee2e2;
  border-radius: 10px;
}

.login-btn {
  width: 100%;
  height: 46px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.25em;
  margin-top: 4px;
  border-radius: 12px;
  background: #0f172a;
  color: #ffffff;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.15);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.login-btn:hover:not(:disabled) {
  background: #1e293b;
  transform: translateY(-1.5px);
  box-shadow: 0 8px 20px -2px rgba(15, 23, 42, 0.25);
}

.login-btn:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.15);
}

.login-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.login-foot {
  display: flex;
  flex-direction: column;
  gap: 3px;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 11px;
  color: #94a3b8;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px dashed #e2e8f0;
  line-height: 1.8;
}

@media (max-width: 700px) {
  .login-wrapper {
    padding: 16px;
  }
  .login-card {
    padding: 32px 22px 24px;
    border-radius: 20px;
  }
}
</style>

