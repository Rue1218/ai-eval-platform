import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import App from './App.vue'
import router from './router'
import { useThemeStore } from './stores/theme'
import './styles/tokens.css'
import './styles/base.css'

// 构建信息：由 vite.config.js 在构建时注入
const pad = (n: number) => String(n).padStart(2, '0')
const buildDate = new Date(__BUILD_TIME__)
const utcTime = `${buildDate.getUTCFullYear()}-${pad(buildDate.getUTCMonth() + 1)}-${pad(buildDate.getUTCDate())} ${pad(buildDate.getUTCHours())}:${pad(buildDate.getUTCMinutes())}:${pad(buildDate.getUTCSeconds())}`
// 北京时间：强制用 Asia/Shanghai 时区，不依赖浏览器本地时区
const beijingTime = buildDate.toLocaleString('zh-CN', {
  timeZone: 'Asia/Shanghai',
  hour12: false,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

// 仅开发环境打印构建信息，生产环境不暴露版本与构建时间
if (import.meta.env.DEV) {
  console.log(
    '%cAI 测试与评估平台',
    'background:#6366F1;color:#fff;padding:4px 10px;border-radius:4px;font-weight:700;font-size:13px',
  )
  console.log(`版本（Git Commit）：${__BUILD_VERSION__}`)
  console.log(`构建时间（UTC）：${utcTime}`)
  console.log(`构建时间（北京时间）：${beijingTime}`)
}

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(naive)

// 应用明暗主题（M0：data-theme 切换，禁止 Vue 响应式改写 CSS 变量）
useThemeStore(pinia).apply()

app.mount('#app')
