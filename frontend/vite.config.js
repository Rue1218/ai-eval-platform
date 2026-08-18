import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { execSync } from 'node:child_process'

// 获取当前构建对应的 Git 提交 ID（短 hash）
// 优先级：构建环境变量（docker build arg）> CI 环境变量 > 本地 git 命令
function getGitCommit() {
  if (process.env.BUILD_VERSION) {
    return process.env.BUILD_VERSION
  }
  if (process.env.GITHUB_SHA) {
    return process.env.GITHUB_SHA.slice(0, 8)
  }
  try {
    return execSync('git rev-parse --short HEAD', { encoding: 'utf8' }).trim()
  } catch {
    return 'unknown'
  }
}

const buildTime = process.env.BUILD_TIME || new Date().toISOString()
const gitCommit = getGitCommit()

export default defineConfig({
  plugins: [vue()],
  define: {
    __BUILD_VERSION__: JSON.stringify(gitCommit),
    __BUILD_TIME__: JSON.stringify(buildTime),
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
