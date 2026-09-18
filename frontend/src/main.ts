import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import App from './App.vue'
import router from './router'
import { useThemeStore } from './stores/theme'
import './styles/tokens.css'
import './styles/base.css'

// 构建信息：由 vite.config.js 在构建时注入
// 北京时间：强制用 Asia/Shanghai 时区，不依赖浏览器本地时区
const beijingTime = (value: string) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
const frontCommit = __BUILD_VERSION__.slice(0, 8)
const frontBuildTime = beijingTime(__BUILD_TIME__)

console.log(
  '%cAI 测试与评估平台',
  'background:#1f5947;color:#fff;padding:4px 10px;border-radius:4px;font-weight:700;font-size:13px',
)
console.log(`前端构建：版本 ${frontCommit} · 构建时间 ${frontBuildTime || '未知'}（北京时间）`)

// 前后端版本对照：前端构建时间只在 frontend/ 变更时更新，用后端 /api/health 的
// 运行版本判断线上是否已部署到最新提交；health 不可用时静默跳过，不影响启动。
interface HealthPayload {
  commit?: string
  build_time?: string
}
fetch('/api/health')
  .then((res) => (res.ok ? (res.json() as Promise<HealthPayload>) : null))
  .then((health) => {
    if (!health?.commit) return
    const backCommit = health.commit.slice(0, 8)
    const backBuildTime = health.build_time ? beijingTime(health.build_time) : ''
    const detail = `后端运行：版本 ${backCommit}${backBuildTime ? ` · 构建时间 ${backBuildTime}（北京时间）` : ''}`
    console.log(detail)
    if (frontCommit !== 'unknown' && backCommit !== 'unknown' && backCommit !== frontCommit) {
      console.warn(`前后端版本不一致（前端 ${frontCommit}），请确认部署是否完成`)
    }
  })
  .catch(() => {})

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(naive)

// 应用明暗主题（M0：data-theme 切换，禁止 Vue 响应式改写 CSS 变量）
useThemeStore(pinia).apply()

app.mount('#app')
