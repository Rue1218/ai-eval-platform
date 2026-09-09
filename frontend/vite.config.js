import { defineConfig, loadEnv } from 'vite'
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

// 本地联调可指向已有 API；REST 与 WS 必须使用同一后端，避免静态预览服务误接消息。
export default defineConfig(({ mode }) => {
  const apiTarget = loadEnv(mode, process.cwd(), '').API_PROXY_TARGET || 'http://localhost:8000'
  return {
  plugins: [vue()],
  resolve: {
    alias: {
      mermaid: 'mermaid/dist/mermaid.esm.min.mjs',
    },
  },
  build: {
    // 大依赖手动分包：mermaid/echarts/katex 均为低频更新的大体积库，
    // 拆分后业务代码改动不会使其缓存失效，显著改善构建产物缓存命中率
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('mermaid') || id.includes('cytoscape') || id.includes('dagre') || id.includes('d3-')) {
              return 'vendor-mermaid'
            }
            if (id.includes('echarts') || id.includes('zrender')) {
              return 'vendor-echarts'
            }
            if (id.includes('katex')) {
              return 'vendor-katex'
            }
            if (id.includes('naive-ui') || id.includes('@vicons')) {
              return 'vendor-naive'
            }
          }
        },
      },
    },
  },
  define: {
    __BUILD_VERSION__: JSON.stringify(gitCommit),
    __BUILD_TIME__: JSON.stringify(buildTime),
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: apiTarget.replace(/^http/, 'ws'),
        ws: true,
      },
    },
  },
  }
})
